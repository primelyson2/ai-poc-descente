#!/usr/bin/env bash
# db/deploy/06_http_smoke.sh
# Secret-free ORDS/OADT2 HTTP smoke helper.
set -euo pipefail

: "${ORDS_BASE:?Set ORDS_BASE, e.g. https://host/ords/<schema-alias>/asta}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

printf '== ASTA ORDS HTTP smoke ==\n'
printf 'ORDS_BASE=%s\n' "$ORDS_BASE"

printf '\n-- GET profiles --\n'
curl -sS "$ORDS_BASE/profiles" | "$PYTHON_BIN" -m json.tool

printf '\n-- POST analyze use_llm=false --\n'
curl -sS -X POST "$ORDS_BASE/analyze" \
  -H 'Content-Type: application/json' \
  --data '{"sql":"select * from dual","source_db_id":"DB0903_TESTDB","use_llm":false,"run_advisor":true,"fetch_rows":10,"sqltune_time_limit":60,"vector_top_k":3}' \
  | tee /tmp/asta_ords_analyze_smoke.json \
  | "$PYTHON_BIN" -m json.tool

RUN_ID="$($PYTHON_BIN - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/asta_ords_analyze_smoke.json')
try:
    data = json.loads(p.read_text())
    print(data.get('run_id') or '')
except Exception:
    print('')
PY
)"

if [[ -n "$RUN_ID" ]]; then
  printf '\n-- GET run %s --\n' "$RUN_ID"
  curl -sS "$ORDS_BASE/runs/$RUN_ID" | "$PYTHON_BIN" -m json.tool

  printf '\n-- GET progress %s --\n' "$RUN_ID"
  curl -sS "$ORDS_BASE/runs/$RUN_ID/progress" | "$PYTHON_BIN" -m json.tool

  printf '\n-- GET report %s --\n' "$RUN_ID"
  curl -sS "$ORDS_BASE/runs/$RUN_ID/report" | "$PYTHON_BIN" -m json.tool
else
  printf '\nWARN: no run_id returned by analyze; skipping run/progress/report follow-up.\n' >&2
fi
