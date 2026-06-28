-- db/ords/asta_ords_module.sql
-- ORDS module exposing ADB ASTA packages. Run in the ORDS-enabled ASTA schema.

BEGIN
  ORDS.DELETE_MODULE(p_module_name => 'asta.v1');
EXCEPTION
  WHEN OTHERS THEN
    NULL;
END;
/

BEGIN
  ORDS.DEFINE_MODULE(
    p_module_name    => 'asta.v1',
    p_base_path      => 'asta/',
    p_items_per_page => 0,
    p_status         => 'PUBLISHED',
    p_comments       => 'OADT2 ASTA ADB/ORDS migration endpoints'
  );

  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'asta.v1',
    p_pattern     => 'analyze',
    p_comments    => 'Run ASTA analysis in ADB PL/SQL'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'asta.v1',
    p_pattern     => 'analyze',
    p_method      => 'POST',
    p_source_type => ORDS.source_type_plsql,
    p_source      => q'[
DECLARE
  l_response CLOB;
  l_offset   PLS_INTEGER := 1;
  l_chunk    VARCHAR2(32767);
BEGIN
  l_response := ASTA_PKG.ANALYZE_SQL(:body_text);

  OWA_UTIL.mime_header('application/json; charset=utf-8', FALSE);
  HTP.p('Cache-Control: no-store');
  HTP.p('Pragma: no-cache');
  HTP.p('X-Content-Type-Options: nosniff');
  HTP.p('X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL');
  HTP.p('X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY');
  HTP.p('X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY');
  HTP.p('X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT');
  HTP.p('X-ASTA-Api-Version: asta.v1');
  HTP.p('X-ASTA-Contract-Version: asta.v1');
  HTP.p('X-ASTA-Response-Mode: CLOB_CHUNKED_JSON');
  OWA_UTIL.http_header_close;

  WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
    l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
    HTP.prn(l_chunk);
    l_offset := l_offset + 2000;
  END LOOP;
END;
]',
    p_comments    => 'Calls ASTA_PKG.ANALYZE_SQL(:body_text)'
  );

  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'asta.v1',
    p_pattern     => 'profiles',
    p_comments    => 'List selectable ASTA DBMS_CLOUD_AI profiles'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'asta.v1',
    p_pattern     => 'profiles',
    p_method      => 'GET',
    p_source_type => ORDS.source_type_plsql,
    p_source      => q'[
DECLARE
  l_response CLOB;
  l_offset   PLS_INTEGER := 1;
  l_chunk    VARCHAR2(32767);
BEGIN
  l_response := ASTA_PKG.LIST_PROFILES;

  OWA_UTIL.mime_header('application/json; charset=utf-8', FALSE);
  HTP.p('Cache-Control: no-store');
  HTP.p('Pragma: no-cache');
  HTP.p('X-Content-Type-Options: nosniff');
  HTP.p('X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL');
  HTP.p('X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY');
  HTP.p('X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY');
  HTP.p('X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT');
  HTP.p('X-ASTA-Api-Version: asta.v1');
  HTP.p('X-ASTA-Contract-Version: asta.v1');
  HTP.p('X-ASTA-Response-Mode: CLOB_CHUNKED_JSON');
  OWA_UTIL.http_header_close;

  WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
    l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
    HTP.prn(l_chunk);
    l_offset := l_offset + 2000;
  END LOOP;
END;
]',
    p_comments    => 'Calls ASTA_PKG.LIST_PROFILES'
  );

  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id',
    p_comments    => 'Fetch ASTA run JSON'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id',
    p_method      => 'GET',
    p_source_type => ORDS.source_type_plsql,
    p_source      => q'[
DECLARE
  l_response CLOB;
  l_offset   PLS_INTEGER := 1;
  l_chunk    VARCHAR2(32767);
BEGIN
  l_response := ASTA_PKG.GET_RUN(:run_id);

  OWA_UTIL.mime_header('application/json; charset=utf-8', FALSE);
  HTP.p('Cache-Control: no-store');
  HTP.p('Pragma: no-cache');
  HTP.p('X-Content-Type-Options: nosniff');
  HTP.p('X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL');
  HTP.p('X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY');
  HTP.p('X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY');
  HTP.p('X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT');
  HTP.p('X-ASTA-Api-Version: asta.v1');
  HTP.p('X-ASTA-Contract-Version: asta.v1');
  HTP.p('X-ASTA-Response-Mode: CLOB_CHUNKED_JSON');
  OWA_UTIL.http_header_close;

  WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
    l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
    HTP.prn(l_chunk);
    l_offset := l_offset + 2000;
  END LOOP;
END;
]',
    p_comments    => 'Calls ASTA_PKG.GET_RUN(:run_id)'
  );

  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id/progress',
    p_comments    => 'Fetch ASTA run progress JSON'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id/progress',
    p_method      => 'GET',
    p_source_type => ORDS.source_type_plsql,
    p_source      => q'[
DECLARE
  l_response CLOB;
  l_offset   PLS_INTEGER := 1;
  l_chunk    VARCHAR2(32767);
BEGIN
  l_response := ASTA_PKG.GET_PROGRESS(:run_id);

  OWA_UTIL.mime_header('application/json; charset=utf-8', FALSE);
  HTP.p('Cache-Control: no-store');
  HTP.p('Pragma: no-cache');
  HTP.p('X-Content-Type-Options: nosniff');
  HTP.p('X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL');
  HTP.p('X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY');
  HTP.p('X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY');
  HTP.p('X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT');
  HTP.p('X-ASTA-Api-Version: asta.v1');
  HTP.p('X-ASTA-Contract-Version: asta.v1');
  HTP.p('X-ASTA-Response-Mode: CLOB_CHUNKED_JSON');
  OWA_UTIL.http_header_close;

  WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
    l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
    HTP.prn(l_chunk);
    l_offset := l_offset + 2000;
  END LOOP;
END;
]',
    p_comments    => 'Calls ASTA_PKG.GET_PROGRESS(:run_id)'
  );

  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id/report',
    p_comments    => 'Fetch ASTA Markdown report wrapped as JSON'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name => 'asta.v1',
    p_pattern     => 'runs/:run_id/report',
    p_method      => 'GET',
    p_source_type => ORDS.source_type_plsql,
    p_source      => q'[
DECLARE
  l_response CLOB;
  l_offset   PLS_INTEGER := 1;
  l_chunk    VARCHAR2(32767);
BEGIN
  l_response := ASTA_PKG.GET_REPORT(:run_id);

  OWA_UTIL.mime_header('application/json; charset=utf-8', FALSE);
  HTP.p('Cache-Control: no-store');
  HTP.p('Pragma: no-cache');
  HTP.p('X-Content-Type-Options: nosniff');
  HTP.p('X-ASTA-Execution-Boundary: ADB_ORDS_PLSQL');
  HTP.p('X-ASTA-FastAPI-Role: ORDS_PROXY_ONLY');
  HTP.p('X-ASTA-Source-Runtime: SOURCE_BASEDB_DBLINK_ONLY');
  HTP.p('X-ASTA-Guard-Policy: SELECT_WITH_SINGLE_STATEMENT');
  HTP.p('X-ASTA-Api-Version: asta.v1');
  HTP.p('X-ASTA-Contract-Version: asta.v1');
  HTP.p('X-ASTA-Response-Mode: CLOB_CHUNKED_JSON');
  OWA_UTIL.http_header_close;

  WHILE l_offset <= NVL(DBMS_LOB.GETLENGTH(l_response), 0) LOOP
    l_chunk := DBMS_LOB.SUBSTR(l_response, 2000, l_offset);
    HTP.prn(l_chunk);
    l_offset := l_offset + 2000;
  END LOOP;
END;
]',
    p_comments    => 'Calls ASTA_PKG.GET_REPORT(:run_id)'
  );
END;
/

COMMIT;
