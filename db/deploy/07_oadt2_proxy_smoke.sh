#!/usr/bin/env bash
# db/deploy/07_oadt2_proxy_smoke.sh
# Smoke the OADT2 FastAPI same-origin proxy after config.yaml points to ORDS.
set -euo pipefail

OADT2_BASE="${OADT2_BASE:-http://127.0.0.1:8000}"
DATABASE_HEADER="${DATABASE_HEADER:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

args=(-sS -X POST "$OADT2_BASE/api/asta/analyze" -H 'Content-Type: application/json')
if [[ -n "$DATABASE_HEADER" ]]; then
  args+=(-H "X-Database: $DATABASE_HEADER")
fi

printf '== OADT2 ASTA proxy smoke ==\n'
printf 'OADT2_BASE=%s\n' "$OADT2_BASE"

curl "${args[@]}" \
  --data '{"sql":"select * from dual","source_db_id":"DB0903_TESTDB","use_llm":false,"fetch_rows":10,"sqltune_time_limit":60,"vector_top_k":3}' \
  | "$PYTHON_BIN" -m json.tool
