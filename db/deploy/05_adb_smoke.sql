-- db/deploy/05_adb_smoke.sql
-- Run on ADB ASTA schema after 02_adb_compile.sql and allowlist insertion.

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
WHENEVER SQLERROR EXIT SQL.SQLCODE

PROMPT == ASTA ADB package smoke ==
SHOW USER

PROMPT SQL guard PASS case
SELECT asta_sql_guard_pkg.inspect_sql('select * from dual') AS guard_ok FROM dual;

PROMPT SQL guard FAIL case (should return JSON status FAILED, not raise to SQL client)
SELECT asta_sql_guard_pkg.inspect_sql('drop table t') AS guard_fail FROM dual;

PROMPT Vector package smoke (NOT_CONFIGURED or COMPLETED acceptable)
SELECT asta_vector_pkg.search_similar_cases('select * from dual', 3) AS vector_smoke FROM dual;

PROMPT Profile listing smoke
SELECT asta_pkg.list_profiles AS profiles_json FROM dual;

PROMPT Source connection allowlist smoke. Replace DB0903_TESTDB if needed.
SELECT asta_source_bridge_pkg.get_connection_json('DB0903_TESTDB') AS source_connection_json FROM dual;

PROMPT Optional: bridge smoke if DB link and Source helper are ready.
PROMPT Uncomment after ASTA_SOURCE_CONNECTIONS points to a verified DB link.
-- SELECT asta_source_bridge_pkg.run_source_evidence(
--   p_source_db_id => 'DB0903_TESTDB',
--   p_sql => 'select * from dual',
--   p_run_id => 'SMOKE_ADB_BRIDGE_001',
--   p_fetch_rows => 10,
--   p_repeat_policy => 'ONCE',
--   p_run_advisor => 'N',
--   p_sqltune_time_sec => 60
-- ) AS bridge_json FROM dual;

PROMPT ADB smoke script complete.
