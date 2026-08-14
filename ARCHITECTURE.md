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

**A new FHIR resource type** — two files:

1. `app/ingest/handlers/<type>.py`:
   ```python
   @register("AllergyIntolerance")
   def handle_allergy(resource: dict, ctx: IngestContext) -> None:
       patient_id = resolve_subject(resource.get("patient"), ctx)
       ...
       ctx.session.add(Allergy(...))
   ```
2. Add the module path to `HANDLER_MODULES` in `app/ingest/handlers/__init__.py`.

Until you do, the type is not an error — it lands in `raw_resources` as
`unknown_type`, is counted in `/ingest/report`, and is still served by
`/fhir/{type}/{id}`.

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
  reproducible, but nothing written through the API survives a restart.
- Timeline merging happens in Python rather than as a `UNION ALL`.
- No authentication. See the README for how it would be approached.
