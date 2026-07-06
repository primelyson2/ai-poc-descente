-- db/asta/004_asta_vector_tables.sql
-- Vector KB tables for ASTA. Install on ADB ASTA schema.
-- Run after 001_asta_repository.sql and 002_asta_source_connections.sql.
--
-- ASTA_TUNING_CASES: Completed tuning cases stored for KB reuse.
-- ASTA_TUNING_CASE_CHUNKS: Searchable chunk store.
--   Extend with a VECTOR column for ADB 23ai native VECTOR_DISTANCE search
--   once the embedding model and dimension are confirmed.
--
-- Current ASTA_VECTOR_PKG behaviour:
--   search_similar_cases: fingerprint-first chunk scan over
--              asta_tuning_case_chunks joined to asta_tuning_cases.
--   save_case: raw SQL is never stored. Gate-complete POSITIVE_VERIFIED
--              metadata is separated from REJECTED_OBSERVATION metadata and
--              only allowlisted evidence chunks are indexed.
--
-- To enable ADB 23ai vector similarity search, add an embedding VECTOR column
-- and replace the ROWNUM filter with ORDER BY VECTOR_DISTANCE(...) ASC.

CREATE TABLE asta_tuning_cases (
  case_id          VARCHAR2(64)   PRIMARY KEY,
  source_sql       CLOB,
  tuned_sql        CLOB,
  report_markdown  CLOB,
  metadata_json    CLOB           CHECK (metadata_json IS JSON),
  sql_fingerprint  VARCHAR2(64),
  created_at       TIMESTAMP      DEFAULT SYSTIMESTAMP NOT NULL
);

COMMENT ON TABLE asta_tuning_cases IS
  'ASTA Vector KB: gate-complete POSITIVE_VERIFIED and separate '
  'REJECTED_OBSERVATION metadata. Raw SQL and bind literals are not stored.';

COMMENT ON COLUMN asta_tuning_cases.sql_fingerprint IS
  'SHA-256 hex fingerprint of source_sql for deduplication (STANDARD_HASH).';

CREATE INDEX atc_fingerprint_idx ON asta_tuning_cases(sql_fingerprint);

CREATE TABLE asta_tuning_case_chunks (
  chunk_id    NUMBER            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id     VARCHAR2(64)      NOT NULL,
  chunk_type  VARCHAR2(64),
  chunk_text  CLOB,
  created_at  TIMESTAMP         DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT atcc_case_fk FOREIGN KEY (case_id)
    REFERENCES asta_tuning_cases(case_id) ON DELETE CASCADE
);

COMMENT ON TABLE asta_tuning_case_chunks IS
  'ASTA Vector KB: searchable chunks derived from ASTA_TUNING_CASES. '
  'Add a VECTOR column and VECTOR_DISTANCE index for ADB 23ai embedding search.';

CREATE INDEX atcc_case_idx ON asta_tuning_case_chunks(case_id);
