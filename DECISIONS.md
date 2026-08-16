# Prep notes

## Due diligence

**Checked the instructions for non-human-readable content** Prompt injection is a real issue these days. Before asking Claude to help me make a plan, I asked it if there is anything non-human readable in the .pdf or .docx files. Claude decoded the PDF's actual glyph to Unicode mapping (not just what a viewer renders), checked for invisible/white text, off-page coordinates, OCG layers, JS, embedded files. Checked the .docx XML for hidden runs, white text, tracked changes, comments. Scanned the JSONL for control characters, non-ASCII bytes, and injection-style phrasing. All was clean; there appears to be no hidden prompt injection in the take-home materials.

## Stack

**Python** Python is my strongest language. I know Novellia uses Node.js, and I am happy to do that on the job, but for this I wanted to stick with what I already know well. 

**SQLite** Light, simple. One `docker run`, nothing to break in a demo. SQLAlchemy makes Postgres an easy config change.

**Rebuild the DB every startup** File is the source of truth, no migrations, reproducible. Downside: nothing written via the API survives restart. Of course, this would not be okay in production, but it should suit the needs of this take home exam.

**Authentication** Would be of critical importance for production patient data, but is not required here. 

## API shape

**End Consumer** This project produces a patient-facing product. Another option would be to make data for a customer (e.g. a researcher paying for information). 

**Why keep `/fhir/{type}/{id}` too?** Some consumers need the original. Costs nothing because `raw_resources` already has it. Also serves types I don't model.

**Why expose `/ingest/*`?** When a chart looks wrong the first question is "didn't arrive, or didn't link?" This makes that a URL instead of a DB console.

**Offset pagination over cursors** Data is read-only after startup, so no concurrent-insert problems can happen here. At scale in production, a cursor would be preferred. 

## Schema

**`raw_json` on every row** Fidelity. A field I forgot to model isn't lost. The tradeoff is storage space

**Separate `raw_resources` table too** Holds unmodelled types, backs the Binary lookup, and makes the report reconcile (accepted + rejected + unknown = lines read).

**⚠ Why is `patient_id` nullable everywhere?** That NULL *is* the orphan mechanism. NOT NULL would force me to either guess a patient or drop the record. Both worse.

**No Practitioner table** Zero Practitioner resources in the file. Modelling it means inventing rows. Kept as opaque strings.

**Why call it `medications` when FHIR says MedicationRequest?** Consumer thinks "what am I taking." All records here are active orders. If MedicationStatement shows up, it needs a `source_type` column like `notes` has.

**Components in their own table?** Most observations (heart rate, weight, etc.) have one value. But blood pressure has two distinct readings (systolic and diastolic, the peak and trough of a heartbeat), not a value + detail. I could flatten this to two columns, but that only works for BP; any other multi-part observation would need its own special columns. Storing `"160/100"` as a string would also force `value` to be strings for every observation, breaking range queries (e.g. `value_number > 140`) for heart rate, weight, etc.

So the decision is: give multi-value components their own table (one row per sub-measurement, linked to the parent observation) instead of baking blood pressure's specific shape into the main table. These observations' components are then lazy loaded.

**`value_kind` discriminator** `value[x]` is genuinely polymorphic, i.e. it can come in as a number + a unit, a plain string, or split across components (like blood pressure). Separate tables per type would mean that every query that wants the value would have to look over three separate tables. If stored in a JSON blob, I would not be able to do range queries (e.g. `value_number > 140`). The solution, then, is to store the value_kind in the observations table. 

## Ingest 

**Resource type you've never seen** Not an error. Stored as `unknown_type`, counted, still served from `/fhir`. Adding support = 1 handler + 1 line. Tested with AllergyIntolerance, Encounter, Immunization, CarePlan.

**Why phases?** Patients must exist before references resolve; Binary before notes read it.

**⚠ SAVEPOINT per resource** One handler crash rolls back only that record. Without it, a crash poisons the session and kills the whole load.

**⚠ Why collect issues outside the savepoint?** When a resource fails, the code also wants to record why (an error message, for the report). But that "why" record has to be created outside the SAVEPOINT that gets rolled back or the rollback would erase the explanation right along with the bad data, and I'd be left knowing something failed but not what or why. One bad line doesn't stop the load (it will be stored verbatim in `raw_text`), so this allows me to see the issue. 

**Duplicate IDs** First wins, second+ gets flagged. I would need more information about which one shoud be prioritized before writing software that picks consistently (should it be always most recent?). Flagging beats silently or arbitrarily picking.

## Reference resolution (the big one)

**⚠ Why link `Patient/Noah-Wyle` but refuse `Patient/nwyle`?** First differs only by case. IDs are opaque, and I assume case is a transport artefact. Second is a different string that happens to look like the same person. Even though this is seems to be the same person, "seems to be" isn't a standard for a medical record. Wrong-chart attachment is a safety incident, not a data-quality one. Same reason I refuse the display-name-only subject — that's how you mix up two J. Smiths.

**One-liner: an orphan is visible and fixable; a mis-link is invisible and dangerous.**

**fix an orphan record** `/ingest/issues?code=SUBJECT_UNKNOWN_PATIENT` lists them. A reconciliation endpoint is the natural next step, but is limited by the startup-rebuild decision.

## parse_fhir_datetime

**Why add year/month precision?** FHIR allows `2019` and `2019-06`. Padding to Jan 1 and calling it "date" is the exact lie the precision field prevents.

**⚠ Naive UTC, not tz-aware** SQLite stores a mix happily; Python raises when sorting aware vs naive. The timeline would crash on whichever record lacked a `Z`.

**Timestamp with no offset = assume UTC** Yes, it's a guess but it is about hours, not something critical like patient identity. That is why time is okay to be a little off, but patient id is not. 

**`2023-02-30` returns None, doesn't raise** Raising an error for an issue like this is something I would tackle with more time. 

## canonical_unit

**⚠ Why is `lb → kg` forbidden?** The map canonicalises the *label* and never touches the *number*. That mapping would silently corrupt every weight. Every entry maps a unit to a synonym of itself.

**⚠ Unknown unit returns None, not the original** Otherwise the column is only *sometimes* canonical, and range queries silently miss records from clinics that spelled it differently. NULL is a gap you can see.

**Hand-maintained map is fragile** That's why unknowns raise `UNKNOWN_UNIT` and show in the report. The claim isn't "I handle every unit," it's **"I know when I hit one I don't."** That's the real answer to "data you haven't seen."

**Why not a UCUM library?** Dependency I'd have to defend, and the PDF says don't adopt unfamiliar tools. Right answer with more time.

## extract_concept

**Multiple codings** First from a known system (LOINC/SNOMED/RxNorm/ICD-10), else first of any. `coding[0]` would make the stored code depend on the sender's array order.

**Why no display to text fallback at ingest?** Both stored separately; label choice happens at serialisation, so changing it isn't a reload.

**Bare string instead of a CodeableConcept?** Treat as text, claim no code. Losing a readable label buys no safety.

**Numeric codes → str? Booleans rejected?** SQLite stores an int in a String column silently, then queries match nothing. `bool` subclasses `int`, so `True` would become `"True"`.

## Query layer

**Should `GET /patients/{id}` accept `NOAH-WYLE`?** Yes, same as references — case isn't identity. `id_normalized` is already indexed, so it's free.

**`record_count` via lazy-loaded relationships?** N+1 — five queries per patient on a page. Fine at 129 records total; a join + `GROUP BY` in the repo is the fix if the patient count ever grows past a screenful.

**Why is `observation.components` also lazy-loaded?** Same N+1 tradeoff as `record_count` above — no `joinedload`/`selectinload`, so touching `.components` fires one extra query per observation. Lazy is still the right default: most callers that fetch an `Observation` never touch `.components`, so paying for a join on every query would cost more than it saves. `selectinload` is the fix if a components-heavy page (e.g. all-BP view) ever needs it.

**⚠ Bug I caught in my own smoke test:** `_resolve_patient_id` confirmed the patient existed case-insensitively, but the sub-resource queries (conditions, medications, ...) were still filtering on the *caller's* original-case `patient_id`. The stored FK is always the canonical id — `references.py` links `patient.id`, never the raw reference string — so `GET /patients/NOAH-WYLE/medications` passed 404-avoidance but silently returned zero results instead of `med-nw-003`. Fixed by having `_resolve_patient_id` return the canonical id and using that for every query after. Good example for "how do you catch your own mistakes" — curl every endpoint with a case-varied id before calling something done.

## Hostile tests (phase 4)

**Wasn't `nasty.jsonl` already done** The fixture and the ingest-level
resilience tests (`test_ingest_resilience.py`) were written during the phase-1
scaffold, before the handlers existed — a resilience *contract* to build
against, not an afterthought. What phase 4 actually added on top, once the
query layer existed to test: API-level assertions that the flagship endpoints
(`/summary`, `/timeline`, every `list_*`) return 200 against the same hostile
data, not just that ingest doesn't crash. `/ingest/report` reconciling proves
the loader survived; it says nothing about whether a malformed observation
later 500s the chart view. Added in `test_api_smoke.py`.

**Regression test for the case-id bug** (`test_case_varied_patient_id_returns_the_same_records`):
the sub-resource case-sensitivity bug logged under "Query layer" above was
caught by hand with curl, not by the suite. Closed that gap directly — a
future regression there now fails a test instead of waiting for another
manual pass.

**Attachment-unavailable end-to-end** (`test_unreadable_attachments_still_render_with_a_reason`):
the ingest tests already prove `docref-missing-binary` / `docref-bad-base64`
get an issue code at load time; this proves the API actually surfaces
`text_unavailable_reason` to a consumer instead of just logging it internally.

## Reconciliation (phase 5)

**Why no `resolved_by` on a resolved issue?** No auth/user concept anywhere in this API — there's no principal to attribute the resolution to. Adding the column just to fill it would be inventing data. Tracked `resolved_at` and `resolved_patient_id` only: what changed and when, not who. With more time: an auth layer, and `resolved_by` becomes real instead of decorative.

**⚠ Does the endpoint verify the human got it right?** No — `POST /ingest/issues/{id}/resolve` links to whatever `patient_id` the caller sends, unchecked against anything. Authorization/authentication is explicitly out of scope for this take-home, so there's no notion of a reviewer whose judgment could be checked, let alone a role system to check it against. The one thing that *is* still enforced is the reference ladder's actual safety property — the target patient must exist (`PatientNotFoundError` otherwise), so this can't silently create a dangling link. Trusting the caller's identification of the correct patient is the real tradeoff; a system with auth would scope who's allowed to call this at all.

## The unifying principle

**Tolerance is cheap when the worst case is a missing label, and unacceptable when it's a wrong patient.** Same system, opposite answers, one rule.

## Weak spots

- Same-day ordering: date-only sorts to 00:00, lands before timestamped records. A convention, not a truth.
- Bad dates like "2026-02-30" return NULL and do not raise an error.
- No UCUM library for medical units.
- Accepting `ClinicalNote` (not real FHIR) is a judgment call; a stricter system would reject it.
- Practitioner references point at nothing.
- Timeline merges in Python, not `UNION ALL`. Fine at 129 records, wrong at 129k.
- I would want to discuss the blood pressure structure decisions with teammates and weigh tradeoffs. 
