-- db/deploy/04_source_smoke.sql
-- Run on Source BaseDB as helper owner after 01_source_compile.sql.

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
WHENEVER SQLERROR EXIT SQL.SQLCODE

PROMPT == ASTA Source helper smoke ==

VARIABLE result_json CLOB
VARIABLE store_status VARCHAR2(32767)

BEGIN
  :result_json := asta_source_pkg.run_evidence(
    p_sql              => 'select * from dual',
    p_run_id           => 'SMOKE_SOURCE_001',
    p_fetch_rows       => 10,
    p_repeat_policy    => 'ONCE',
    p_run_advisor      => 'N',
    p_sqltune_time_sec => 60
  );
END;
/

BEGIN
  asta_source_pkg.run_evidence_store_proc(
    p_sql              => 'select * from dual',
    p_run_id           => 'SMOKE_SOURCE_CHUNK_001',
    p_fetch_rows       => 10,
    p_repeat_policy    => 'ONCE',
    p_run_advisor      => 'N',
    p_sqltune_time_sec => 60,
    p_status_json      => :store_status
  );
END;
/

PRINT store_status
PRINT result_json

DECLARE
  l_status VARCHAR2(30);
BEGIN
  SELECT JSON_VALUE(:result_json, '$.status' RETURNING VARCHAR2(30) ERROR ON ERROR)
  INTO   l_status
  FROM   dual;

  IF l_status <> 'COMPLETED' THEN
    RAISE_APPLICATION_ERROR(-20911, 'Source helper smoke failed: status=' || l_status);
  END IF;
  DBMS_OUTPUT.PUT_LINE('OK: Source helper smoke completed');
END;
/

DECLARE
  l_store_status VARCHAR2(30);
  l_result_json  CLOB;
  l_chunk        VARCHAR2(32767);
  l_offset       PLS_INTEGER := 1;
  l_chunk_size   PLS_INTEGER := 8000;
  l_status       VARCHAR2(30);
  l_contract     VARCHAR2(30);
BEGIN
  SELECT JSON_VALUE(:store_status, '$.status' RETURNING VARCHAR2(30) ERROR ON ERROR)
  INTO   l_store_status
  FROM   dual;

  IF l_store_status <> 'STORED' THEN
    RAISE_APPLICATION_ERROR(-20912, 'Source helper store smoke failed: status=' || l_store_status);
  END IF;

  DBMS_LOB.CREATETEMPORARY(l_result_json, TRUE);
  LOOP
    l_chunk := asta_source_pkg.get_result_chunk(
      p_run_id => 'SMOKE_SOURCE_CHUNK_001',
      p_offset => l_offset,
      p_amount => l_chunk_size
    );
    EXIT WHEN l_chunk IS NULL;
    DBMS_LOB.WRITEAPPEND(l_result_json, LENGTH(l_chunk), l_chunk);
    EXIT WHEN LENGTH(l_chunk) < l_chunk_size;
    l_offset := l_offset + l_chunk_size;
  END LOOP;

  IF DBMS_LOB.GETLENGTH(l_result_json) = 0 THEN
    RAISE_APPLICATION_ERROR(-20913, 'Source helper chunk smoke returned empty JSON');
  END IF;

  SELECT JSON_VALUE(l_result_json, '$.status' RETURNING VARCHAR2(30) ERROR ON ERROR),
         JSON_VALUE(l_result_json, '$.contract_version' RETURNING VARCHAR2(30) ERROR ON ERROR)
  INTO   l_status, l_contract
  FROM   dual;

  IF l_status <> 'COMPLETED' OR l_contract <> 'asta.v1' THEN
    RAISE_APPLICATION_ERROR(-20914, 'Source helper chunk smoke invalid JSON: status=' || l_status || ', contract=' || l_contract);
  END IF;

  DBMS_OUTPUT.PUT_LINE('OK: Source helper store/chunk smoke reconstructed asta.v1 JSON over DB-link-safe contract');
END;
/
