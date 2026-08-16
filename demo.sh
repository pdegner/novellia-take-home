#!/usr/bin/env bash
# Walks the API, with an emphasis on the records that are deliberately broken.
# Each call is annotated with the design claim it demonstrates.
#
#   ./demo.sh [base_url]        default: http://localhost:8000

set -uo pipefail
BASE="${1:-http://localhost:8000}"

if command -v jq >/dev/null 2>&1; then
  PRETTY="jq ."
else
  PRETTY="python3 -m json.tool"
fi

step() {
  printf '\n\033[1;36m== %s\033[0m\n\033[0;90m%s\033[0m\n' "$1" "$2"
}

call() {
  printf '\033[0;33m$ curl %s\033[0m\n' "$1"
  curl -s "$BASE$1" | eval "$PRETTY"
}

step "Liveness" "Confirms the file was found and how much of it loaded."
call "/health"

step "Ingest report" \
  "accepted + rejected + unknown_type == total_lines. Nothing is dropped silently."
call "/ingest/report"

step "Case-normalised reference" \
  "med-nw-003 says Patient/Noah-Wyle; the id is noah-wyle. Linked, with a warning."
call "/ingest/issues?code=SUBJECT_CASE_NORMALIZED"

step "Unknown patient reference -- REFUSED" \
  "obs-nw-006 says Patient/nwyle. It is probably Noah Wyle. 'Probably' is not a
standard you apply to a chart, so it stays unlinked."
call "/ingest/issues?code=SUBJECT_UNKNOWN_PATIENT"

step "Display-only subject -- REFUSED" \
  "obs-kl-bad-001 identifies its patient by name alone. Name matching is how you
attach a lab result to the wrong person."
call "/ingest/issues?code=SUBJECT_UNRESOLVABLE"

step "Condition with no code" \
  "cond-nw-bad-001 has no diagnosis code. Kept and flagged: an unlabelled active
diagnosis is better than a missing one."
call "/ingest/issues?code=MISSING_CODE"

step "Closing the loop -- reconciling an orphan" \
  "The ladder above refused to link obs-nw-006 on its own. A human can still
say so explicitly: POST /ingest/issues/{id}/resolve."
ISSUE_ID=$(curl -s "$BASE/ingest/issues?code=SUBJECT_UNKNOWN_PATIENT" \
  | python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; print(items[0]["id"] if items else "")')
if [ -n "$ISSUE_ID" ]; then
  printf '\033[0;33m$ curl -X POST %s/ingest/issues/%s/resolve -d {"patient_id":"noah-wyle"}\033[0m\n' "$BASE" "$ISSUE_ID"
  curl -s -X POST "$BASE/ingest/issues/$ISSUE_ID/resolve" \
    -H 'Content-Type: application/json' \
    -d '{"patient_id": "noah-wyle"}' | eval "$PRETTY"
else
  printf '  (already resolved by an earlier run of this script -- restart the server to reset)\n'
fi

step "Patient summary" "The flagship view: one call for a whole chart."
call "/patients/noah-wyle/summary"

step "Timeline" "Mixed date precision, ordered correctly, precision preserved."
call "/patients/noah-wyle/timeline?limit=10"

step "Notes" \
  "One inline ClinicalNote (a type FHIR does not define) and one base64 payload
behind a DocumentReference -> Binary hop. The consumer sees neither difference."
call "/patients/noah-wyle/notes"

step "Polymorphic observation values" \
  "Blood pressure has no top-level value (components), and smoking status is a
string where its siblings are numbers."
call "/patients/patrick-ball/observations"

step "Raw FHIR passthrough" "The escape hatch: source resource, unchanged."
call "/fhir/Observation/obs-nw-006"

printf '\n\033[1;32mDone.\033[0m Interactive docs: %s/docs\n' "$BASE"
