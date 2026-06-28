-- db/deploy/08_deployment_precheck.sql
-- Run on ADB ASTA schema before/after deployment to inspect required objects.

SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF

PROMPT == ASTA deployment precheck ==
SHOW USER

PROMPT Tables
SELECT table_name
FROM user_tables
WHERE table_name IN (
  'ASTA_RUNS', 'ASTA_RUN_PROGRESS', 'ASTA_SOURCE_CONNECTIONS',
  'ASTA_TUNING_CASES', 'ASTA_TUNING_CASE_CHUNKS'
)
ORDER BY table_name;

PROMPT Packages
SELECT object_name, object_type, status
FROM user_objects
WHERE object_name IN (
  'ASTA_SQL_GUARD_PKG', 'ASTA_SOURCE_BRIDGE_PKG', 'ASTA_VECTOR_PKG',
  'ASTA_LLM_PKG', 'ASTA_REPORT_PKG', 'ASTA_PKG'
)
ORDER BY object_name, object_type;

PROMPT Source allowlist rows
SELECT source_db_id, db_link_name, source_schema, enabled, updated_at
FROM asta_source_connections
ORDER BY source_db_id;

PROMPT ASTA DBMS_CLOUD_AI profiles visible to current schema
SELECT profile_name, status
FROM user_cloud_ai_profiles
WHERE UPPER(profile_name) LIKE 'ASTA%'
ORDER BY profile_name;

PROMPT DB links visible to current schema
SELECT db_link, username, host
FROM user_db_links
ORDER BY db_link;
