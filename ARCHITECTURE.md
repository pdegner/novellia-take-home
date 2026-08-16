# Architecture

## The shape of it

```
JSONL file
    |
    v
ingest/loader.py ---- every line -> raw_resources (nothing is ever dropped)
    |
    v
ingest/registry.py -- resourceType -> handler, run in phase order
    |
    v
ingest/handlers/* --- normalize + resolve references -> domain tables
    |                     |
    |                     +-- anything imperfect -> ingest_issues
    v
services/ ----------- clinical meaning, no HTTP
    |
    v
routers/ ------------ HTTP only: parse, delegate, wrap
```

## Three layers, three jobs

| Layer | Knows about | Does not know about |
|---|---|---|
| `routers/` | HTTP, query params, status codes | SQL, FHIR |
| `services/` | clinical meaning, assembly | HTTP, request objects |
| `repositories/`, `models/` | SQL, the schema | FHIR, HTTP |
| `ingest/` | FHIR | HTTP |

FHIR vocabulary stops at the ingest boundary. Nothing below `ingest/` mentions
a CodeableConcept, and that is deliberate: it means adding a resource type
cannot ripple into the API surface.

## Adding things

**A new FHIR resource type, reusing an existing table** — two files:

1. `app/ingest/handlers/<type>.py`:
   ```python
   @register("AllergyIntolerance")
   def handle_allergy(resource: dict, ctx: IngestContext) -> None:
       patient_id = resolve_subject(resource.get("patient"), ctx)
       ...
       ctx.session.add(Allergy(...))
   ```
2. Add the module path to `HANDLER_MODULES` in `app/ingest/handlers/__init__.py`.

This assumes the target model (`Allergy` above) already exists. Until a type
is registered at all, it is not an error — it lands in `raw_resources` as
`unknown_type`, is counted in `/ingest/report`, and is still served by
`/fhir/{type}/{id}`.

**A new FHIR resource type that needs its own table** — e.g. `Practitioner`:
referenced throughout the file via `recorder`/`requester`/`performer`/
`author`, but never itself present as a resource. Same shape as above,
repeated across more files:

1. `app/models/clinical.py` — a new model class, same shape as `Patient`.
2. `app/schemas/clinical.py` — its response schema.
3. `app/ingest/handlers/<type>.py` — the handler, as above.
4. `app/ingest/handlers/__init__.py` — register the module.
5. `app/repositories/<type>.py` — `list_*`/`get_*`, same shape as
   `repositories/conditions.py`.
6. `app/services/<type>.py` (or add functions to an existing service) —
   assembly, same shape as `get_patient`.
7. `app/routers/<type>.py` — a new top-level router if the resource isn't
   owned by a single patient (a practitioner can be referenced by many
   patients' records), wired into `app/main.py`.

Two decisions this forces, not mechanical:

- **Ingest phase.** Phases set processing order, not file order — `Patient`
  runs in `Phase.SUBJECTS`, first, so its rows exist before anything tries to
  resolve a reference to one. A standalone lookup table doesn't need that and
  can stay in the default `Phase.RECORDS`. But resolving `recorder_ref`/
  `requester_ref`/etc. into real foreign keys does need it — the new type
  would have to ingest in `Phase.SUBJECTS` too, for the same reason.
- **Rewire existing `*_ref` columns, or leave them?** Every practitioner
  reference today is an opaque string pair (`recorder_ref`,
  `recorder_display`, etc.) on five different tables. Turning those into
  foreign keys means touching all five existing handlers and models live.
  The scoped answer under time pressure: leave the strings as they are, add
  the new table alongside as a standalone lookup, and call the FK rewire the
  next increment if there's time.

**A new endpoint** — two files: a function in `app/services/patients.py`, and a
route in `app/routers/patients.py` that calls it.

**A new field on an existing type** — add the column in
`app/models/clinical.py`, populate it in the handler, expose it in
`app/schemas/clinical.py`. The database is rebuilt on every startup, so there
is no migration step.

## Ingest phases

Some records depend on others existing first, so the loader dispatches in
ordered passes rather than sorting the file or doing lazy fixups
(`app/ingest/registry.py`):

| Phase | Types | Why |
|---|---|---|
| `SUBJECTS` (0) | `Patient` | everything else resolves against them |
| `ATTACHMENTS` (1) | `Binary` | notes read their text out of these |
| `RECORDS` (2) | everything clinical | needs both of the above |

## Failure containment

Each resource is handled inside a SAVEPOINT. A handler that raises rolls back
only that record's rows and becomes a `HANDLER_FAILED` issue; the load
continues. Issues are collected outside the savepoint so the explanation
survives the rollback that caused it.

This is why `/ingest/report` is trustworthy: `accepted + rejected +
unknown_type` always equals the number of lines read.

## Why `raw_resources` exists

Three jobs, one table:

1. **Fidelity** — `/fhir/{type}/{id}` returns exactly what the clinic sent.
2. **Unknown types** — a resource we cannot model is still stored and served.
3. **Indirection** — `Binary` payloads are read back from here rather than
   getting a table nobody would ever query directly.

## Known limitations

- The whole file is read into memory before dispatch. Fine at 129 resources;
  a streaming two-pass load is the answer if it grows.
- The database is rebuilt from the file on every startup. No migrations, fully
  reproducible, but nothing written through the API survives a restart —
  including reconciliation links made through
  `POST /ingest/issues/{id}/resolve`.
- Timeline merging happens in Python rather than as a `UNION ALL`.
- No authentication. See the README for how it would be approached.
