# ASTA Source Helper

Install `asta_source_pkg.sql` only on the Source BaseDB schema that is allowed
to execute bounded SELECT evidence collection for ASTA.

The OADT2 FastAPI app must not connect to this database directly. ADB calls the
helper through an allowlisted DB Link, and ORDS exposes only the ADB package.

## Install Outline

Run as the Source helper owner:

```sql
@db/deploy/01_source_compile.sql
@db/deploy/04_source_smoke.sql
```

`01_source_compile.sql` is the canonical SQL-only install path. It creates or
verifies the Source repository tables used by the DB-link-safe chunk contract,
then compiles `ASTA_SOURCE_PKG`:

- `ASTA_SOURCE_RESULTS(run_id, response_json, created_at)` stores the full
  `asta.v1` evidence JSON CLOB returned by `run_evidence_store_proc`.
- `ASTA_SOURCE_ADVISOR_RESULTS(run_id, status, report, created_at)` stores
  optional SQL Tuning Advisor output from the Source scheduler path.
- Created-at indexes support age-based cleanup. Retain rows until ADB has
  retrieved chunks and persisted the report, then purge old rows by
  `created_at` according to the deployment retention window.

Required grants, issued by a DBA on the Source BaseDB:

```sql
GRANT SELECT  ON v_$sql                     TO <helper_owner>;
GRANT SELECT  ON v_$sql_plan_statistics_all TO <helper_owner>;
GRANT EXECUTE ON dbms_xplan                 TO <helper_owner>;
GRANT EXECUTE ON dbms_sqltune               TO <helper_owner>;
```

`DBMS_SQLTUNE` is only used when ADB passes `p_run_advisor => 'Y'`.
If ADB calls the package through a schema-qualified DB link such as
`DEVDO.asta_source_pkg@DB0903_LINK`, grant `EXECUTE` on `ASTA_SOURCE_PKG` to the
DB-link user or run the helper as that schema.

## Runtime Contract

`ASTA_SOURCE_PKG.RUN_EVIDENCE` accepts SELECT/WITH SQL, injects an
`ASTA_RUN_ID` marker, executes a bounded `COUNT(*)` wrapper, and returns JSON
with explicit `status`, cursor metrics, `DBMS_XPLAN.DISPLAY_CURSOR` output,
and optional SQL Tuning Advisor text. Guard or runtime failures return
`status:"FAILED"` with an `error` object so the ADB bridge can stop later ASTA
steps deterministically.

The helper validates `p_run_id` before embedding it in the SQL marker comment.
Allowed markers are short alphanumeric IDs with `_`, `.`, `:`, and `-`.
`p_repeat_policy` is normalized before execution and must be `AUTO`, `ONCE`,
or `REPEAT:<n>`; repeats are clamped to the package maximum.
`p_run_advisor` and `p_sqltune_time_sec` are normalized inside the Source
helper as well as by the ADB bridge. Responses include `advisor_requested` and
`sqltune_time_limit_sec`, so ADB-side progress/report logic can tell whether a
SQL Tuning Advisor report was skipped by request or failed during execution.
Successful and failed JSON responses include
`contract_version:"asta.v1"` and
`execution_boundary:"SOURCE_BASEDB_DBLINK_ONLY"`. They also include
`guard_policy:"SELECT_WITH_SINGLE_STATEMENT"` so ADB/ORDS consumers can verify
that Source execution stayed inside the single SELECT/WITH guard contract.
Successful responses also include `evidence_method:"BOUNDED_COUNT_GATHER_PLAN_STATS"`,
`metrics_source:"V$SQL_PLAN_STATISTICS_ALL_LAST"`,
`timing_scope:"repeat_loop_total"`, and `elapsed_wall_ms_per_exec` so
ADB-side comparison code can distinguish Source cursor `LAST_*` metrics from
the helper's bounded execution wrapper and wall-clock repeat-loop timing.

## DB-link chunked JSON contract

Remote PL/SQL calls over Oracle DB Link cannot safely pass or return CLOBs, so
ADB must use the Source store/chunk API rather than calling `RUN_EVIDENCE`
directly over the link:

1. ADB resolves `source_db_id` through its allowlisted `ASTA_SOURCE_CONNECTIONS`
   row. Browser/FastAPI payloads must not supply `source_schema` or DB-link
   names.
2. ADB calls
   `ASTA_SOURCE_PKG.RUN_EVIDENCE_STORE_PROC@<DB_LINK>(..., p_status_json OUT)`
   with SQL as `VARCHAR2`. A successful call returns
   `{"status":"STORED","contract_version":"asta.v1",...}` and writes the
   full JSON CLOB to `ASTA_SOURCE_RESULTS` on Source.
3. ADB repeatedly calls
   `ASTA_SOURCE_PKG.get_result_chunk@<DB_LINK>(run_id, offset, 32000)` and
   appends chunks until `NULL` or a short chunk is returned.
4. The reconstructed JSON must parse with `contract_version:"asta.v1"` and the
   normal `status` (`COMPLETED` or structured `FAILED`).

`db/deploy/04_source_smoke.sql` validates both the direct local CLOB path and
the store/chunk path by reconstructing JSON from `get_result_chunk`.

The SQL guard strips comments and string literals before checking forbidden
keywords, so harmless values such as `'drop'` inside SELECT literals are not
misclassified. Semicolon statement terminators are rejected because the helper
executes exactly one bounded SELECT/WITH statement. A standalone SQL*Plus `/`
terminator line is rejected for the same reason. The accepted SQL length is
limited to 32K characters so the VARCHAR2-based guard scans the same text that
is later executed.

No passwords, wallet paths, or application secrets belong in these SQL files.
