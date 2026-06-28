"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

from __future__ import annotations

from pathlib import Path
import json
import sys
import oracledb
import yaml

ROOT = Path(__file__).resolve().parents[1]


def connect():
    """환경변수와 wallet 설정을 사용해 Oracle DB 연결을 연다."""
    conf = yaml.safe_load((ROOT / "config.yaml").read_text())
    db = conf["databases"][0]
    wallet = str((ROOT / db["wallet_location"]).resolve())
    return oracledb.connect(
        user=db["user"], password=db["password"], dsn=db["dsn"],
        config_dir=wallet, wallet_location=wallet, wallet_password=db.get("wallet_password")
    )


def clob_to_str(v):
    """Oracle CLOB 값을 Python 문자열로 안전하게 변환한다."""
    if v is None:
        return None
    return v.read() if hasattr(v, "read") else str(v)


def parse_json(name, value):
    """문자열 또는 CLOB 형태의 JSON 응답을 dict로 파싱한다."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} did not return valid JSON: {exc}: {value[:500]}") from exc
    return value


def require_run_retrievable(out, run_id):
    """ASTA 실행 결과가 공개 조회 엔드포인트에서 다시 읽히는지 검증한다."""
    for endpoint in ["get_run", "get_progress", "get_report"]:
        value = out[f"analyze_persistence_{endpoint}"]
        value_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        payload = parse_json(endpoint, value)
        if not isinstance(payload, dict):
            raise RuntimeError(f"{endpoint} returned non-object JSON for {run_id}: {value_text[:1000]}")
        if payload.get("status") == "FAILED" or payload.get("error"):
            raise RuntimeError(f"{endpoint} failed for {run_id}: {value_text[:1000]}")

conn = connect()
cur = conn.cursor()
out = {}
had_error = False
queries = {
    "guard_ok": "select asta_sql_guard_pkg.inspect_sql('select * from dual') from dual",
    "guard_fail": "select asta_sql_guard_pkg.inspect_sql('drop table t') from dual",
    "vector_smoke": "select asta_vector_pkg.search_similar_cases('select * from dual', 3) from dual",
    "profiles": "select asta_pkg.list_profiles from dual",
    "source_connection": "select asta_source_bridge_pkg.get_connection_json('DB0903_TESTDB') from dual",
}
for name, sql in queries.items():
    try:
        cur.execute(sql)
        out[name] = clob_to_str(cur.fetchone()[0])
    except Exception as e:
        out[name] = {"error": f"{type(e).__name__}: {e}"}
try:
    cur.execute("""
        select asta_source_bridge_pkg.run_source_evidence(
          p_source_db_id => 'DB0903_TESTDB',
          p_sql => 'select * from dual',
          p_run_id => 'SMOKE_ADB_BRIDGE_001',
          p_fetch_rows => 10,
          p_repeat_policy => 'ONCE',
          p_run_advisor => 'Y',
          p_sqltune_time_sec => 60
        ) from dual
    """)
    out["bridge_smoke"] = clob_to_str(cur.fetchone()[0])
except Exception as e:
    had_error = True
    out["bridge_smoke"] = {"error": f"{type(e).__name__}: {e}"}
try:
    analyze_body = json.dumps({
        "sql": "select * from dual",
        "source_db_id": "DB0903_TESTDB",
        "fetch_rows": 10,
        "vector_top_k": 1,
        "use_llm": False,
        "run_advisor": True,
        "sqltune_time_limit": 60,
    })
    analyze_out = cur.var(oracledb.DB_TYPE_CLOB)
    cur.execute("begin :out := asta_pkg.analyze_sql(:body); end;", out=analyze_out, body=analyze_body)
    analyze_json = clob_to_str(analyze_out.getvalue())
    analyze_text = analyze_json or ""
    out["analyze_smoke"] = analyze_json
    analyze_payload = parse_json("analyze_smoke", analyze_json)
    if not isinstance(analyze_payload, dict):
        raise RuntimeError(f"analyze_smoke returned non-object JSON: {analyze_text[:1000]}")
    run_id = analyze_payload.get("run_id")
    runtime_evidence = analyze_payload.get("runtime_evidence") or {}
    advisor = runtime_evidence.get("advisor") or {}
    if runtime_evidence.get("advisor_requested") is not True:
        raise RuntimeError(f"analyze_smoke did not request advisor: {analyze_text[:1000]}")
    if advisor.get("status") not in {"COMPLETED", "SKIPPED", "FAILED"}:
        raise RuntimeError(f"analyze_smoke advisor status missing/unexpected: {analyze_text[:1000]}")
    progress = analyze_payload.get("progress") or []
    advisor_progress = [p for p in progress if p.get("code") == "SQL_TUNING_ADVISOR"]
    if not advisor_progress or not advisor_progress[0].get("detail"):
        raise RuntimeError(f"analyze_smoke advisor progress detail missing: {analyze_text[:1000]}")
    if not run_id:
        raise RuntimeError(f"analyze_smoke did not return run_id: {analyze_text[:1000]}")
    for endpoint, sql in {
        "get_run": "begin :out := asta_pkg.get_run(:run_id); end;",
        "get_progress": "begin :out := asta_pkg.get_progress(:run_id); end;",
        "get_report": "begin :out := asta_pkg.get_report(:run_id); end;",
    }.items():
        lookup_out = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute(sql, out=lookup_out, run_id=run_id)
        out[f"analyze_persistence_{endpoint}"] = clob_to_str(lookup_out.getvalue())
    require_run_retrievable(out, run_id)
except Exception as e:
    had_error = True
    out["analyze_persistence_smoke"] = {"error": f"{type(e).__name__}: {e}"}
cur.close(); conn.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
sys.exit(1 if had_error else 0)
