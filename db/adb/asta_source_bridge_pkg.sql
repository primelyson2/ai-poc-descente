-- db/adb/asta_source_bridge_pkg.sql
-- ADB bridge to Source BaseDB ASTA_SOURCE_PKG over an allowlisted DB Link.

CREATE OR REPLACE PACKAGE asta_source_bridge_pkg AUTHID DEFINER AS
  FUNCTION run_source_evidence(
    p_source_db_id      IN VARCHAR2,
    p_sql               IN CLOB,
    p_run_id            IN VARCHAR2,
    p_fetch_rows        IN NUMBER   DEFAULT 100,
    p_repeat_policy     IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor       IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec  IN NUMBER   DEFAULT 1800,
    p_source_sql_id     IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB;

  FUNCTION get_connection_json(p_source_db_id IN VARCHAR2) RETURN CLOB;
END asta_source_bridge_pkg;
/

CREATE OR REPLACE PACKAGE BODY asta_source_bridge_pkg AS
  C_MAX_REPEATS CONSTANT PLS_INTEGER := 5;
  C_GUARD_POLICY CONSTANT VARCHAR2(40) := 'SELECT_WITH_SINGLE_STATEMENT';

  FUNCTION json_str(p_val IN VARCHAR2) RETURN VARCHAR2 IS
    l_v VARCHAR2(32767) := p_val;
  BEGIN
    IF l_v IS NULL THEN
      RETURN 'null';
    END IF;
    l_v := REPLACE(l_v, '\', '\\');
    l_v := REPLACE(l_v, '"', '\"');
    l_v := REPLACE(l_v, CHR(8), '\b');
    l_v := REPLACE(l_v, CHR(9), '\t');
    l_v := REPLACE(l_v, CHR(10), '\n');
    l_v := REPLACE(l_v, CHR(13), '\r');
    l_v := REPLACE(l_v, CHR(12), '\f');
    RETURN '"' || l_v || '"';
  END json_str;

  FUNCTION error_json(p_code IN VARCHAR2, p_message IN VARCHAR2) RETURN CLOB IS
  BEGIN
    RETURN TO_CLOB(
      '{"status":"FAILED","code":' || json_str(p_code) ||
      ',"contract_version":"asta.v1"' ||
      ',"execution_boundary":"ADB_SOURCE_BRIDGE_DBLINK"' ||
      ',"connection_source":"ASTA_SOURCE_CONNECTIONS"' ||
      ',"guard_policy":' || json_str(C_GUARD_POLICY) ||
      ',"message":' || json_str(p_message) || '}'
    );
  END error_json;

  FUNCTION validated_db_link_name(p_name IN VARCHAR2) RETURN VARCHAR2 IS
    l_name VARCHAR2(128) := UPPER(TRIM(p_name));
  BEGIN
    IF l_name IS NULL
       OR NOT REGEXP_LIKE(l_name, '^[A-Z][A-Z0-9_$#]*(\.[A-Z0-9_$#]+)*$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_SOURCE_BRIDGE: invalid DB Link name');
    END IF;
    RETURN l_name;
  END validated_db_link_name;

  FUNCTION validated_schema_name(p_name IN VARCHAR2) RETURN VARCHAR2 IS
    l_name VARCHAR2(128) := UPPER(TRIM(p_name));
  BEGIN
    IF l_name IS NULL THEN
      RETURN NULL;
    END IF;
    IF NOT REGEXP_LIKE(l_name, '^[A-Z][A-Z0-9_$#]*$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_SOURCE_BRIDGE: invalid Source schema name');
    END IF;
    RETURN l_name;
  END validated_schema_name;

  FUNCTION validated_source_db_id(p_source_db_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_id VARCHAR2(64) := UPPER(TRIM(p_source_db_id));
  BEGIN
    IF l_id IS NULL
       OR NOT REGEXP_LIKE(l_id, '^[A-Z0-9][A-Z0-9_.:-]{0,63}$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_SOURCE_BRIDGE: invalid source_db_id');
    END IF;
    RETURN l_id;
  END validated_source_db_id;

  FUNCTION validated_run_id(p_run_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_run_id VARCHAR2(64) := TRIM(p_run_id);
  BEGIN
    IF l_run_id IS NULL
       OR LENGTH(l_run_id) > 64
       OR NOT REGEXP_LIKE(l_run_id, '^[A-Za-z0-9][A-Za-z0-9_.:-]*$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_SOURCE_BRIDGE: invalid run_id marker');
    END IF;
    RETURN l_run_id;
  END validated_run_id;

  FUNCTION validated_source_sql_id(p_source_sql_id IN VARCHAR2) RETURN VARCHAR2 IS
    l_sql_id VARCHAR2(13) := LOWER(TRIM(p_source_sql_id));
  BEGIN
    IF l_sql_id IS NULL THEN
      RETURN NULL;
    END IF;
    IF NOT REGEXP_LIKE(l_sql_id, '^[0-9a-z]{13}$') THEN
      RAISE_APPLICATION_ERROR(-20002, 'ASTA_SOURCE_BRIDGE: invalid source_sql_id');
    END IF;
    RETURN l_sql_id;
  END validated_source_sql_id;

  FUNCTION normalized_fetch_rows(p_fetch_rows IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_fetch_rows, 100), 1), 10000);
  END normalized_fetch_rows;

  FUNCTION normalized_repeat_policy(p_repeat_policy IN VARCHAR2) RETURN VARCHAR2 IS
    l_policy VARCHAR2(30) := UPPER(TRIM(NVL(p_repeat_policy, 'AUTO')));
    l_repeat PLS_INTEGER;
  BEGIN
    IF l_policy IN ('AUTO', 'ONCE') THEN
      RETURN l_policy;
    ELSIF REGEXP_LIKE(l_policy, '^REPEAT:[0-9]+$') THEN
      l_repeat := TO_NUMBER(SUBSTR(l_policy, 8));
      RETURN 'REPEAT:' || TO_CHAR(LEAST(GREATEST(l_repeat, 1), C_MAX_REPEATS));
    END IF;

    RAISE_APPLICATION_ERROR(
      -20002,
      'ASTA_SOURCE_BRIDGE: invalid repeat_policy. Use AUTO, ONCE, or REPEAT:<n>'
    );
  END normalized_repeat_policy;

  FUNCTION normalized_run_advisor(p_run_advisor IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN CASE WHEN UPPER(TRIM(NVL(p_run_advisor, 'N'))) = 'Y' THEN 'Y' ELSE 'N' END;
  END normalized_run_advisor;

  FUNCTION normalized_sqltune_time_sec(p_sqltune_time_sec IN NUMBER) RETURN PLS_INTEGER IS
  BEGIN
    RETURN LEAST(GREATEST(NVL(p_sqltune_time_sec, 1800), 60), 1800);
  END normalized_sqltune_time_sec;

  PROCEDURE resolve_connection(
    p_source_db_id IN  VARCHAR2,
    p_db_link_name OUT VARCHAR2,
    p_source_schema OUT VARCHAR2
  ) IS
    l_source_db_id VARCHAR2(64) := validated_source_db_id(p_source_db_id);
  BEGIN
    SELECT db_link_name, source_schema
    INTO   p_db_link_name, p_source_schema
    FROM   asta_source_connections
    WHERE  source_db_id = l_source_db_id
    AND    enabled = 'Y';

    p_db_link_name := validated_db_link_name(p_db_link_name);
    p_source_schema := validated_schema_name(p_source_schema);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(
        -20002,
        'ASTA_SOURCE_BRIDGE: no enabled Source DB Link for source_db_id=' ||
        SUBSTR(NVL(l_source_db_id, '(null)'), 1, 128)
      );
  END resolve_connection;

  FUNCTION run_source_evidence(
    p_source_db_id      IN VARCHAR2,
    p_sql               IN CLOB,
    p_run_id            IN VARCHAR2,
    p_fetch_rows        IN NUMBER   DEFAULT 100,
    p_repeat_policy     IN VARCHAR2 DEFAULT 'AUTO',
    p_run_advisor       IN VARCHAR2 DEFAULT 'N',
    p_sqltune_time_sec  IN NUMBER   DEFAULT 1800,
    p_source_sql_id     IN VARCHAR2 DEFAULT NULL
  ) RETURN CLOB IS
    l_db_link_name VARCHAR2(128);
    l_source_schema VARCHAR2(128);
    l_source_prefix VARCHAR2(130);
    l_stmt          VARCHAR2(1000);
    l_status_vc     VARCHAR2(32767);
    l_chunk         VARCHAR2(32767);
    l_offset        PLS_INTEGER := 1;
    l_chunk_size    PLS_INTEGER := 8000;
    l_sql_vc        VARCHAR2(32767);
    l_result        CLOB;
    l_fetch_rows    PLS_INTEGER;
    l_repeat_policy VARCHAR2(30);
    l_run_advisor   VARCHAR2(1);
    l_run_id         VARCHAR2(64);
    l_source_sql_id  VARCHAR2(13);
    l_sqltune_time_sec PLS_INTEGER;
  BEGIN
    resolve_connection(p_source_db_id, l_db_link_name, l_source_schema);
    asta_sql_guard_pkg.assert_safe_select(p_sql);
    l_run_id := validated_run_id(p_run_id);
    l_source_sql_id := validated_source_sql_id(p_source_sql_id);
    l_fetch_rows := normalized_fetch_rows(p_fetch_rows);
    l_repeat_policy := normalized_repeat_policy(p_repeat_policy);
    l_run_advisor := normalized_run_advisor(p_run_advisor);
    l_sqltune_time_sec := normalized_sqltune_time_sec(p_sqltune_time_sec);
    l_source_prefix := CASE WHEN l_source_schema IS NULL THEN '' ELSE l_source_schema || '.' END;
    l_sql_vc := DBMS_LOB.SUBSTR(p_sql, 32767, 1);

      l_stmt :=
      'BEGIN ' || l_source_prefix ||
      'asta_source_pkg.run_evidence_store_proc@' || l_db_link_name ||
      '(:sql_text, :run_id, :fetch_rows, :repeat_policy, :run_advisor, :sqltune_time_sec, :source_sql_id, :out_json); END;';

    -- Source helper owns its storage transaction via its autonomous
    -- run_evidence_store_vc path. Do not COMMIT or ROLLBACK here:
    -- ASTA_PKG has already created caller-owned ASTA_RUNS/progress state
    -- in the same ADB transaction, and the bridge must not discard it.
    EXECUTE IMMEDIATE l_stmt
      USING IN  l_sql_vc,
            IN  l_run_id,
            IN  l_fetch_rows,
            IN  l_repeat_policy,
            IN  l_run_advisor,
            IN  l_sqltune_time_sec,
            IN  l_source_sql_id,
            OUT l_status_vc;

    IF l_status_vc IS NULL OR INSTR(l_status_vc, '"status":"STORED"') = 0 THEN
      RETURN error_json('SOURCE_BRIDGE', 'Source helper store failed: ' || SUBSTR(l_status_vc, 1, 3000));
    END IF;

    DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
    LOOP
      l_stmt :=
        'BEGIN :chunk := ' || l_source_prefix ||
        'asta_source_pkg.get_result_chunk@' || l_db_link_name ||
        '(:run_id, :offset, :amount); END;';
      EXECUTE IMMEDIATE l_stmt
        USING OUT l_chunk,
              IN  l_run_id,
              IN  l_offset,
              IN  l_chunk_size;
      EXIT WHEN l_chunk IS NULL;
      DBMS_LOB.WRITEAPPEND(l_result, LENGTH(l_chunk), l_chunk);
      EXIT WHEN LENGTH(l_chunk) < l_chunk_size;
      l_offset := l_offset + l_chunk_size;
    END LOOP;

    IF l_result IS NULL OR NVL(DBMS_LOB.GETLENGTH(l_result), 0) = 0 THEN
      RETURN error_json('SOURCE_BRIDGE', 'Source helper returned empty chunked response');
    END IF;
    RETURN l_result;
  EXCEPTION
    WHEN OTHERS THEN
      IF l_run_advisor = 'Y' AND l_db_link_name IS NOT NULL AND l_run_id IS NOT NULL THEN
        BEGIN
          DBMS_LOB.CREATETEMPORARY(l_result, TRUE);
          l_offset := 1;
          LOOP
            l_stmt :=
              'BEGIN :chunk := ' || l_source_prefix ||
              'asta_source_pkg.get_result_chunk@' || l_db_link_name ||
              '(:run_id, :offset, :amount); END;';
            EXECUTE IMMEDIATE l_stmt
              USING OUT l_chunk,
                    IN  l_run_id,
                    IN  l_offset,
                    IN  l_chunk_size;
            EXIT WHEN l_chunk IS NULL;
            DBMS_LOB.WRITEAPPEND(l_result, LENGTH(l_chunk), l_chunk);
            EXIT WHEN LENGTH(l_chunk) < l_chunk_size;
            l_offset := l_offset + l_chunk_size;
          END LOOP;
          IF l_result IS NOT NULL AND NVL(DBMS_LOB.GETLENGTH(l_result), 0) > 0 THEN
            RETURN l_result;
          END IF;
        EXCEPTION
          WHEN OTHERS THEN
            NULL;
        END;
      END IF;
      RETURN error_json('SOURCE_BRIDGE', SUBSTR(SQLERRM, 1, 4000));
  END run_source_evidence;

  FUNCTION get_connection_json(p_source_db_id IN VARCHAR2) RETURN CLOB IS
    l_db_link_name VARCHAR2(128);
    l_source_schema VARCHAR2(128);
  BEGIN
    resolve_connection(p_source_db_id, l_db_link_name, l_source_schema);
    RETURN TO_CLOB(
      '{"status":"COMPLETED","code":"SOURCE_CONNECTION"' ||
      ',"source_db_id":' || json_str(validated_source_db_id(p_source_db_id)) ||
      ',"contract_version":"asta.v1"' ||
      ',"db_link_name":' || json_str(l_db_link_name) ||
      ',"source_schema":' || json_str(l_source_schema) ||
      ',"execution_boundary":"ADB_SOURCE_BRIDGE_DBLINK"' ||
      ',"connection_source":"ASTA_SOURCE_CONNECTIONS"' ||
      ',"guard_policy":' || json_str(C_GUARD_POLICY) ||
      ',"enabled":"Y"}'
    );
  EXCEPTION
    WHEN OTHERS THEN
      RETURN error_json('SOURCE_CONNECTION', SUBSTR(SQLERRM, 1, 4000));
  END get_connection_json;
END asta_source_bridge_pkg;
/
