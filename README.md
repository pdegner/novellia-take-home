# Novellia Health API

A patient-centric API over FHIR clinical data.

## Run it

```bash
make run      # Docker, on http://localhost:8000  (nothing else needed)
```

or locally:

```bash
make dev      # uvicorn with autoreload
make test     # pytest — 98 passing, including tests/fixtures/nasty.jsonl
make demo     # curls every endpoint, annotated, including the broken records
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
| `valueString` where siblings use `valueQuantity` | `value_kind` discriminator |
| blood pressure with no top-level value | stored as components |
| `mmHg` / `beats/minute` / bare `%` | canonical unit alongside the original |
| date-only vs. full timestamps | normalised timestamp **plus** the precision received |
| `ClinicalNote` — not a real FHIR type | accepted, provenance recorded in `source_type` |
| `DocumentReference` → `Binary` base64 | resolved and decoded at ingest |
| a resource type we have never seen | stored, counted, still served from `/fhir` |
| a line that is not valid JSON | recorded verbatim, load continues |

Two smaller rules behind that table, both in the same spirit as the one
below — refuse to guess, make the gap visible instead of papering over it:

- **Units are relabeled, never converted.** The canonical-unit map turns a
  spelling into its canonical spelling (`beats/minute` → `/min`); it never
  turns one unit into another. An unrecognized unit stores `None` rather than
  the raw string, so a range query can't silently skip records from a clinic
  that spelled a unit differently — a `NULL` is a gap you can see.
- **A concept with several codes prefers a known system** — LOINC, then
  SNOMED, then RxNorm, then ICD-10 — and falls back to whichever is listed
  first only when none of those are present.

### The key rule

**The system never guesses which patient a record belongs to.**

Matching `Patient/nwyle` or a bare display name onto a chart by name similarity
could silently attach clinical data to the wrong person. That is a
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

## Tools and AI usage

Python/FastAPI/SQLAlchemy because the instructions explicitly say not to learn a new framework for the exercise, and this is my strongest stack.

I used Claude Code throughout, in three different modes:

- **Scaffolding, once.** Project layout, `pyproject.toml`, Dockerfile,
  Makefile, config/db bootstrap, SQLAlchemy models, an empty handler
  registry, router stubs, and the pytest harness. All were reviewed before I wrote
  any logic against it.
- **Paired, for everything with a real decision in it.** The subject
  resolution ladder, unit/date/code normalization, the repositories, and the
  summary/timeline services were built one function at a time: I directed
  each one, Claude drafted it, I read and edited it before moving to the
  next. `DECISIONS.md` has the reasoning behind each call,
  logged as it happened rather than reconstructed after.
- **Solo, once, by exception.** The hostile-input fixture (`nasty.jsonl`) and
  its ingest-level resilience tests were drafted by Claude *before* the
  handlers existed, as a contract to build against. Later, once the paired
  work had established the pattern, I had Claude write the remaining
  API-level survival tests solo — by that point they were mechanical repeats
  of an established shape, not new decisions.

The most valuable catch in this project was mine, not the model's: querying
`GET /patients/NOAH-WYLE/medications` by hand turned up a case-sensitivity bug
in the query layer that all 90-some tests at the time missed — the id lookup
normalized case but the sub-resource queries still filtered on the caller's
original-case string. Curling the running API before calling something done
is what found it, not the test suite. Full writeup in `DECISIONS.md`.

## Known limitations

See [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations). The short version:
the database is rebuilt from the file on every startup, the whole file is
read into memory, and timeline merging happens in Python rather than in SQL.
One consequence worth naming: reconciliation links made through
`POST /ingest/issues/{id}/resolve` are in-memory-DB writes, so they don't
survive a restart either.

`PREFERRED_CODE_SYSTEMS` and the unit-canonicalization map in
`normalize.py` are both hand-maintained lists; an unfamiliar code system or
unit spelling doesn't crash anything, but extending coverage means editing
the list by hand.
