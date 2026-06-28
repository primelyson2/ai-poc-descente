# ASTA ADB Packages

These scripts are additive ADB-side artifacts for the OADT2 ASTA ORDS-first
migration. They keep FastAPI as a same-origin ORDS proxy and move ASTA runtime
responsibility into PL/SQL.

## Install Order

```sql
@db/asta/001_asta_repository.sql
@db/asta/002_asta_source_connections.sql
@db/asta/003_asta_runs_source_db_id.sql
@db/asta/004_asta_vector_tables.sql
@db/adb/asta_sql_guard_pkg.sql
@db/adb/asta_source_bridge_pkg.sql
@db/adb/asta_vector_pkg.sql
@db/adb/asta_llm_pkg.sql
@db/adb/asta_report_pkg.sql
@db/adb/asta_pkg.sql
@db/ords/asta_ords_module.sql
```

`004_asta_vector_tables.sql` creates `asta_tuning_cases` and
`asta_tuning_case_chunks`. To enable ADB 23ai VECTOR_DISTANCE similarity
search, add an embedding `VECTOR` column to `asta_tuning_case_chunks` after
the embedding model and dimension are confirmed.

`db/asta` currently holds the repository DDL created earlier in the migration.
The package scripts in this directory depend on those tables but do not deploy
live DB changes by themselves.

## Public Contract

ORDS calls `ASTA.ASTA_PKG.ANALYZE_SQL(:body_text)` for `POST /asta/analyze`.
The package returns JSON with `run_id`, `status`, `architecture`,
`progress`, and `detailed_report_markdown`.

`GET /asta/runs/:run_id/progress` calls `ASTA.ASTA_PKG.GET_PROGRESS(:run_id)`
and returns the canonical 11-step progress array used by the UI.
Progress rows store `elapsed_ms` when a step moves from `RUNNING` to a terminal
state. `ANALYZE_SQL` also persists the same progress array into the run
response JSON, so immediate analyze responses and later progress polling use
the same source of truth.
Public run lookup endpoints validate `run_id` before repository access and
return structured JSON failures for invalid or missing runs. Profile, progress,
and report responses include the same `migration_boundary` metadata used by the
analyze response, so consumers can verify that FastAPI remained an ORDS proxy
and ASTA execution stayed in ADB PL/SQL/Source DB Link packages.
All public JSON response families include `contract_version:"asta.v1"`; ORDS
also emits `X-ASTA-Contract-Version: asta.v1` for handler-level verification.
Public responses and ORDS headers also carry
`guard_policy:"SELECT_WITH_SINGLE_STATEMENT"` /
`X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT`, keeping the HTTP contract
aligned with the Source and ADB SQL guards.

Source DB execution is only available through `ASTA_SOURCE_BRIDGE_PKG`, which
resolves `source_db_id` from `ASTA_SOURCE_CONNECTIONS` before invoking the
Source helper package over a DB Link. The bridge validates DB Link and Source
schema identifiers before building the remote PL/SQL call. It also normalizes
fetch-row bounds, repeat policy, SQL Tuning Advisor enablement, and SQLTUNE
time limits before binding the remote helper call. Run markers are validated
on the ADB side before the DB Link call, and direct bridge callers get the same
`REPEAT:<n>` clamp as the Source helper.
`ASTA_PKG` records `source_db_id` and updates `source_schema/source_db_link`
from the bridge allowlist result instead of trusting browser payload values.
The browser and FastAPI proxy do not forward `source_schema` or
`source_db_link`; those values are only resolved from the ADB allowlist.
ADB main package clamps request-controlled fetch rows, vector top-k, and
SQLTUNE time limits before dispatching any package work.
Source helper `FAILED` or `error.message` JSON is treated as a Source evidence
failure before later workflow steps are marked successful.

`ASTA_LLM_PKG` validates profile names so ADB-side LLM execution stays on
`ASTA*` DBMS_CLOUD_AI profiles. Candidate SQL is extracted only from JSON
`candidate_sql` or fenced SQL blocks and must pass `ASTA_SQL_GUARD_PKG` before
it is exposed for tuned evidence. Prompts request JSON-only output to keep
candidate extraction deterministic. LLM responses expose
`response_contract:"JSON_ONLY"` and tuning responses expose
`candidate_guard_policy:"SELECT_WITH_SINGLE_STATEMENT"` for static and runtime
contract checks.
The Source and ADB SQL guards cap input SQL at 32K characters to match their
VARCHAR2 scrub/keyword scan window.

`ASTA_PKG` builds the before/after comparison from Source helper JSON inside
PL/SQL. The canonical response includes top-level `runtime_evidence`,
`after_evidence`, `comparison`, and `vector_save` fields, with the same objects
also preserved under `artifacts` for report/debug consumers. The response also
includes `migration_boundary` metadata documenting `ORDS_PROXY_ONLY`,
`ADB_ORDS_PLSQL`, and `SOURCE_BASEDB_DBLINK_ONLY` ownership.

`ASTA_VECTOR_PKG` includes a SHA-256 SQL fingerprint in configured and
not-configured JSON responses so runs can be correlated without storing
secrets or adding Python-local vector execution. Vector search/save responses
also include `execution_boundary:"ADB_VECTOR_PLSQL"`. `SAVE_CASE` writes the
case row plus bounded `SOURCE_SQL`, `TUNED_SQL`, and `REPORT_MARKDOWN` chunks
into `ASTA_TUNING_CASE_CHUNKS`; `SEARCH_SIMILAR_CASES` joins chunks to cases
and ranks exact SQL-fingerprint matches first using
`search_strategy:"FINGERPRINT_FIRST_CHUNK_SCAN"`.
`ASTA_SQL_GUARD_PKG.INSPECT_SQL` returns
`execution_boundary:"ADB_SQL_GUARD_PLSQL"`, and report responses identify
`report_source:"ADB_REPORT_PLSQL"` plus
`response_contract:"CLOB_CHUNKED_JSON"`.

The ORDS module script deletes the `asta.v1` module before redefining it, which
makes local SQL artifact review and repeated deployment runs deterministic.
Every JSON handler emits `X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL` along with
`X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY`,
`X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY`,
`X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT`,
`X-ASTA-Api-Version: asta.v1`, `X-ASTA-Contract-Version: asta.v1`, no-cache,
and nosniff headers.
