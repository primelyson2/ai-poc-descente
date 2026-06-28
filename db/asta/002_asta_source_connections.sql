-- db/asta/002_asta_source_connections.sql
-- Allowlist table for Source BaseDB connections used by ASTA_SOURCE_BRIDGE_PKG.
--
-- SECURITY: Only entries in this table with ENABLED='Y' may be used as DB Link
-- targets. The DB_LINK_NAME value is injected into dynamic SQL inside
-- ASTA_SOURCE_BRIDGE_PKG only after validation; the value itself must pass a
-- ^[A-Za-z][A-Za-z0-9_$#]*(\.[A-Za-z0-9_$#]+)*$ character check.
--
-- Install on ADB (ASTA schema). Run after 001_asta_repository.sql.

CREATE TABLE asta_source_connections (
  source_db_id   VARCHAR2(64)  NOT NULL,
  db_link_name   VARCHAR2(128) NOT NULL,
  source_schema  VARCHAR2(128),
  description    VARCHAR2(512),
  enabled        VARCHAR2(1)   DEFAULT 'Y' NOT NULL
                   CONSTRAINT asta_src_conn_en_ck CHECK (enabled IN ('Y', 'N')),
  created_at     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT asta_source_conn_pk PRIMARY KEY (source_db_id)
);

COMMENT ON TABLE asta_source_connections IS
  'Allowlist of Source BaseDB DB Links for ASTA_SOURCE_BRIDGE_PKG. '
  'Only rows with ENABLED=''Y'' are accepted. '
  'DB_LINK_NAME must be a valid Oracle identifier.';

COMMENT ON COLUMN asta_source_connections.source_db_id IS
  'Logical identifier sent in the analyze payload (e.g. DB0903_TESTDB).';

COMMENT ON COLUMN asta_source_connections.db_link_name IS
  'Oracle DB Link name. Must exist in the ASTA schema. '
  'Injected into dynamic SQL only via allowlist lookup and identifier validation.';

COMMENT ON COLUMN asta_source_connections.source_schema IS
  'Default schema on the Source DB (informational; enforced in helper package).';

COMMENT ON COLUMN asta_source_connections.enabled IS
  '''Y'' to permit connections, ''N'' to block without deleting the row.';

-- Example entry (adjust before use):
-- INSERT INTO asta_source_connections(source_db_id, db_link_name, source_schema, description)
-- VALUES ('DB0903_TESTDB', 'DB0903_LINK', 'DEVDO', 'Test BaseDB via DB Link');
-- COMMIT;
