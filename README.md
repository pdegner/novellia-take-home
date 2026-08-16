# Novellia Health API

A patient-centric API over FHIR clinical data.

> **Status: in progress.** The ingest harness, provenance layer, data-quality
> endpoints, and raw FHIR passthrough are working. The resource handlers and
> the patient query layer are still being built — `/ingest/report` shows
> exactly what is and is not wired up yet.

## Run it

```bash
make run      # Docker, on http://localhost:8000  (nothing else needed)
```

or locally:

```bash
make dev      # uvicorn with autoreload
make test     # pytest
```

Interactive docs at `http://localhost:8000/docs`.

## Who this API is for

The consumer is a product surface showing a person their own health record —
so the primary endpoints are shaped like a chart, not like FHIR. A client
asking "what is going on with this patient" makes one call to
`/patients/{id}/summary` and gets conditions, medications, recent vitals and
notes already resolved, decoded, and labelled. No CodeableConcepts, no
`value[x]`, no references to chase.

Two secondary surfaces exist for consumers that need something else:

- **`/fhir/{type}/{id}`** returns the source resource unchanged, for
  integration work where translation is the wrong answer.
- **`/ingest/*`** exposes what arrived and what could not be resolved, because
  the first question when a chart looks wrong is "did it not arrive, or did it
  not link?"

## Endpoints

| Route | Purpose |
|---|---|
| `GET /health` | liveness and load counts |
| `GET /patients` | list, filter by name and gender |
| `GET /patients/{id}` | demographics |
| `GET /patients/{id}/summary` | the chart view, in one call |
| `GET /patients/{id}/timeline` | every dated record, merged chronologically |
| `GET /patients/{id}/conditions` | filter by status, code |
| `GET /patients/{id}/medications` | filter by status, code |
| `GET /patients/{id}/observations` | filter by code, date range, value range |
| `GET /patients/{id}/procedures` | filter by code |
| `GET /patients/{id}/notes` | text already decoded from both source shapes |
| `GET /fhir/{type}/{id}` | source resource, unchanged |
| `GET /ingest/report` | counts by type and by issue code |
| `GET /ingest/issues` | the individual imperfect records |
| `POST /ingest/issues/{id}/resolve` | link an orphaned record to a patient by hand |

## Handling messy data

The supplied file has 129 resources and a number of deliberate defects. How
each is handled:

| What arrived | What we do |
|---|---|
| `Patient/Noah-Wyle` where the id is `noah-wyle` | link, warn `SUBJECT_CASE_NORMALIZED` — case is a transport artefact |
| `Patient/nwyle`, matching no patient | **do not link**, error `SUBJECT_UNKNOWN_PATIENT` |
| subject with only `display: "Katherine LaNasa"` | **do not link**, error `SUBJECT_UNRESOLVABLE` |
| `Condition` with no `code` | keep it, flag `MISSING_CODE` — an unlabelled diagnosis beats a missing one |
| `valueString` where siblings use `valueQuantity` | `value_kind` discriminator; both are first-class |
| blood pressure with no top-level value | stored as components |
| `mmHg` / `beats/minute` / bare `%` | canonical unit alongside the original |
| date-only vs. full timestamps | normalised timestamp **plus** the precision received |
| `ClinicalNote` — not a real FHIR type | accepted, provenance recorded in `source_type` |
| `DocumentReference` → `Binary` base64 | resolved and decoded at ingest |
| a resource type we have never seen | stored, counted, still served from `/fhir` |
| a line that is not valid JSON | recorded verbatim, load continues |

### The one rule worth stating plainly

**The system never guesses which patient a record belongs to.**

Matching `Patient/nwyle` or a bare display name onto a chart by name similarity
would silently attach clinical data to the wrong person. That is a
patient-safety failure, not a data-quality one. Where the source is ambiguous
the record is kept, stored unlinked, and surfaced through `/ingest/issues` for
a human to reconcile — `POST /ingest/issues/{id}/resolve` is that reconciliation
step, linking the record once a person, not the machine, has made the call. An
orphaned record is visible and fixable; a mis-linked one is invisible and
dangerous.

## Schema

Hybrid: typed columns for anything queryable, plus `raw_json` on every row for
fidelity. Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

- `patients`, `conditions`, `medications`, `observations`,
  `observation_components`, `procedures`, `notes` — the domain
- `raw_resources` — one row per source line, whatever it turned out to be
- `ingest_issues` — every imperfection, filterable by code and severity

`patient_id` is nullable on every clinical table. That NULL, plus an issue row,
*is* the orphan mechanism — there is no separate quarantine table.

## Authentication

Not implemented, per the brief. The approach would be:

- **Transport**: TLS everywhere; no PHI over plaintext.
- **AuthN**: OAuth2 / OIDC with short-lived JWTs (SMART-on-FHIR is the standard
  in this domain and would matter if clinic systems were the caller).
- **AuthZ**: the interesting half. Every endpoint here is patient-scoped, so
  the check is per-record, not per-route: a patient token may read only its own
  subject; a clinician token is scoped to their care relationships. That
  belongs in the repository layer, not in routers, so no endpoint can forget it.
- **Audit**: HIPAA expects access logging — who read which record, when. The
  `raw_resources` / `ingest_issues` pattern extends naturally to an
  append-only access log.
- **De-identification**: `/ingest/issues` echoes fragments of source records
  and would need redaction before non-clinical staff could see it.

## Tools and AI usage

<!-- TODO(Patti): the instructions ask for this explicitly. Be specific and
     honest -- it is a question about judgment, not a confession. Cover:
     - Python/FastAPI/SQLAlchemy because that is where I am strongest
     - Claude Code for scaffolding, schema drafting, and hostile test fixtures
     - which parts you wrote yourself and which you reviewed line by line
     - anything you rejected from the AI's suggestions, and why -->

## Known limitations

See [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations). The short version:
the database is rebuilt from the file on every startup, the whole file is read
into memory, and timeline merging happens in Python rather than in SQL.

The UNIT_ALIASES would need to be manually updated in normalize.py. 


## Notes

### normalize.py
There are different precisions of dates e.g. "diabetic since 2019" vs. "blood drawn 2025-01-05T08:00:00Z"

every unit entry maps a unit to a synonym of itself, never a conversion. (pounds to lbs, not pounds to kg). New units will map to None. The tempting alternative — falling back to the raw spelling — makes value_unit_canonical a column that's only sometimes canonical. A range query filtering on it would then silently miss every record from a clinic that spelled the unit differently. A NULL is a gap you can see; a plausible-looking wrong value isn't. Something I could do with more time. 

SNOMED wins over local codes. If no SMOMED, pick the first one in the array. 
