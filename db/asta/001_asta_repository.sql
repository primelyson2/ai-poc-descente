-- ASTA repository/progress tables for ADB ORDS-first workflow.
CREATE TABLE asta_runs (
  run_id              VARCHAR2(64) PRIMARY KEY,
  status              VARCHAR2(30) NOT NULL,
  input_sql           CLOB,
  tuned_sql           CLOB,
  llm_profile         VARCHAR2(128),
  source_db_id        VARCHAR2(64),
  source_schema       VARCHAR2(128),
  source_db_link      VARCHAR2(128),
  created_at          TIMESTAMP DEFAULT SYSTIMESTAMP,
  started_at          TIMESTAMP,
  completed_at        TIMESTAMP,
  error_code          VARCHAR2(128),
  error_message       VARCHAR2(4000),
  detailed_report_md  CLOB,
  response_json       CLOB CHECK (response_json IS JSON)
);

CREATE TABLE asta_run_progress (
  run_id       VARCHAR2(64) NOT NULL,
  seq          NUMBER NOT NULL,
  code         VARCHAR2(64) NOT NULL,
  label        VARCHAR2(256),
  status       VARCHAR2(30),
  detail       VARCHAR2(4000),
  started_at   TIMESTAMP,
  completed_at TIMESTAMP,
  elapsed_ms   NUMBER,
  CONSTRAINT asta_run_progress_pk PRIMARY KEY (run_id, seq)
);
