# ASTA ADB/ORDS Deployment Runbook

This directory contains deployment helpers for the OADT2 ASTA ADB/ORDS migration.

The scripts are intentionally **secret-free**. They do not create DB links, credentials, wallets, DBMS_CLOUD_AI profiles, or ORDS schema mappings. Create/verify those in the target environment first.

## Current canonical Source connection

The current live/demo allowlist is:

- ADB owner: `ADMIN`
- Logical `source_db_id`: `DB0903_TESTDB`
- ADB DB Link: `DB0903_LINK`
- Source helper schema: `DEVDO`

Older readiness notes that mention Source helper schema `ADMIN` were pre-fix discovery notes. Use the allowlisted `DEVDO` / `DB0903_LINK` contract unless the target environment is explicitly changed and re-smoked.

## Deployment phases

### 0. Confirm names before running

- ADB package/schema owner: usually the ORDS-enabled deployment owner (`ADMIN` in the current live/demo environment; some examples use `ASTA`).
- ORDS-enabled schema: must match the package owner or `db/ords/asta_ords_module.sql` package references must be patched.
- Source helper owner/schema on BaseDB: current live/demo value is `DEVDO`.
- ADB DB Link name to Source DB: current live/demo value is `DB0903_LINK`.
- Logical `source_db_id`: current live/demo value is `DB0903_TESTDB`.

### 1. Source BaseDB helper

Run on Source BaseDB as helper owner after DBA grants:

```sql
@db/deploy/01_source_compile.sql
@db/deploy/04_source_smoke.sql
```

`01_source_compile.sql` is the SQL-only Source install path. It creates/verifies:

- `ASTA_SOURCE_RESULTS` with `response_json CLOB CHECK (response_json IS JSON)` and a `created_at` cleanup index.
- `ASTA_SOURCE_ADVISOR_RESULTS` with advisor `report CLOB` and a `created_at` cleanup index.
- `ASTA_SOURCE_PKG` package spec/body validity.

Cleanup policy: retain rows until ADB has retrieved the chunks and persisted the ASTA report, then purge old rows by `created_at` according to the deployment retention window.

`04_source_smoke.sql` validates both contracts:

- Direct local `run_evidence(...) RETURN CLOB` for Source-only sanity.
- DB-link-safe `run_evidence_store_proc(...)` returning `STORED`, followed by `get_result_chunk(...)` reconstruction and `asta.v1` JSON validation.

Required DBA grants are listed in `db/source/README.md`.

### 2. ADB repository and packages

Run on ADB as the ASTA owner:

```sql
@db/deploy/02_adb_compile.sql
```

Then insert the real allowlist row. Do **not** leave placeholder values:

```sql
MERGE INTO asta_source_connections t
USING (
  SELECT 'DB0903_TESTDB' source_db_id,
         'DB0903_LINK' db_link_name,
         'DEVDO' source_schema,
         'ASTA source link via DB0903_LINK' description
  FROM dual
) s
ON (t.source_db_id = s.source_db_id)
WHEN MATCHED THEN UPDATE SET
  t.db_link_name = s.db_link_name,
  t.source_schema = s.source_schema,
  t.description = s.description,
  t.enabled = 'Y',
  t.updated_at = SYSTIMESTAMP
WHEN NOT MATCHED THEN INSERT(source_db_id, db_link_name, source_schema, description, enabled)
  VALUES(s.source_db_id, s.db_link_name, s.source_schema, s.description, 'Y');
COMMIT;
```

The browser and FastAPI proxy must send only the logical `source_db_id`; they must not send or trust `source_schema` or DB-link names.

Run ADB smoke tests:

```sql
@db/deploy/05_adb_smoke.sql
```

### 3. ORDS module

Run on the ORDS-enabled ADB schema after `ASTA_PKG` compiles:

```sql
@db/deploy/03_ords_install.sql
```

If the package owner is not `ASTA`, patch `db/ords/asta_ords_module.sql` first.

### 4. HTTP smoke

Set `ORDS_BASE` to the actual base URL that maps to `p_base_path => 'asta/'`.

```bash
ORDS_BASE='https://<host>/ords/<schema-alias>/asta' \
  bash db/deploy/06_http_smoke.sh
```

## Important caveats

- `db/asta/001_asta_repository.sql`, `002_asta_source_connections.sql`, and `004_asta_vector_tables.sql` use raw `CREATE TABLE`/`CREATE INDEX`. `02_adb_compile.sql` does prechecks and skips those files if tables already exist. `006_asta_llm_call_log.sql` creates the autonomous two-stage LLM prompt/response audit store and is idempotent.
- Source helper CLOB evidence over DB Link uses the store/chunk VARCHAR2 contract (`run_evidence_store_proc` + `get_result_chunk`); do not call `run_evidence` directly over the DB Link.
- `ASTA_VECTOR_PKG` is currently fingerprint-first chunk scan, not full VECTOR_DISTANCE embedding search.
- `ASTA_LLM_PKG` requires same-owner ASTA DBMS_CLOUD_AI profiles/credentials under definer-rights execution.
