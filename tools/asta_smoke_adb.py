"""ASTA SQL-only ADB smoke와 로컬 artifact 계약 검증 도구.

실제 DB 호출은 main()에서만 수행한다. import/단위 테스트는 외부 연결을 만들지 않는다.
비밀번호, wallet password 또는 접속 문자열은 출력하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
import oracledb
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ["REQUEST_RECEIVED", "ORDS_DISPATCH", "SQL_GUARD", "BEFORE_EVIDENCE",
            "SQL_TUNING_ADVISOR", "LLM_REWRITE", "AFTER_EVIDENCE",
            "BEFORE_AFTER_COMPARE", "VECTOR_KB", "FINAL_REPORT", "VECTOR_SAVE"]
REPORT_LABEL = {"IMPROVED": "개선 성공", "NOT_IMPROVED": "개선실패",
                "NON_EQUIVALENT": "결과 불일치", "CANDIDATE_FAILED": "후보 실행 실패",
                "NO_REWRITE": "개선 SQL 없음", "INSUFFICIENT_EVIDENCE": "측정 불충분"}


def connect():
    conf = yaml.safe_load((ROOT / "config.yaml").read_text())
    db = conf["databases"][0]
    wallet = str((ROOT / db["wallet_location"]).resolve())
    return oracledb.connect(user=db["user"], password=db["password"], dsn=db["dsn"],
                            config_dir=wallet, wallet_location=wallet,
                            wallet_password=db.get("wallet_password"))


def clob_to_str(value):
    return value.read() if hasattr(value, "read") else value


def parse_json(name, value):
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError as exc: raise RuntimeError(f"{name} did not return valid JSON") from exc
    return value


def require_run_retrievable(out, run_id):
    parsed = {}
    for endpoint in ["get_run", "get_progress", "get_report"]:
        value = out[f"analyze_persistence_{endpoint}"]
        payload = parse_json(endpoint, value)
        if not isinstance(payload, dict) or payload.get("status") == "FAILED" or payload.get("error"):
            raise RuntimeError(f"{endpoint} failed for {run_id}")
        parsed[endpoint] = payload
    return parsed


def validate_workflow_contract(payload, lookups):
    """SQL-only/순서/verdict/report/재조회 계약을 실제 JSON 구조로 검증한다."""
    artifacts = payload.get("artifacts") or {}
    progress = payload.get("progress") or []
    codes = [p.get("code") for p in progress]
    if codes != WORKFLOW:
        raise RuntimeError(f"progress order mismatch: {codes}")
    llm = payload.get("llm_artifact") or artifacts.get("llm") or {}
    mode = llm.get("mode") or llm.get("prompt_mode") or llm.get("code")
    if mode not in {"SQL_ONLY_STRUCTURAL_REWRITE", "SQL_ONLY_REWRITE"}:
        raise RuntimeError("LLM artifact is not SQL-only mode")
    comparison = payload.get("comparison") or artifacts.get("comparison") or {}
    verdict = comparison.get("verdict")
    if verdict not in REPORT_LABEL:
        raise RuntimeError("comparison verdict missing")
    review = payload.get("final_review") or artifacts.get("final_review") or {}
    if review.get("status") != "SKIPPED" or review.get("reason") != "DETERMINISTIC_COMPARISON":
        raise RuntimeError("final review is not deterministic/skipped")
    report = payload.get("detailed_report_markdown") or payload.get("report_markdown") or ""
    if REPORT_LABEL[verdict] not in report or (verdict not in report and "verdict" in report.lower()):
        raise RuntimeError("report verdict does not match comparison verdict")
    candidate = bool(payload.get("candidate_sql") or llm.get("candidate_sql") or llm.get("rewrite_available"))
    after = payload.get("after_evidence") or artifacts.get("after_evidence")
    if candidate and not after:
        raise RuntimeError("candidate after evidence/XPLAN missing")
    if not candidate and after:
        raise RuntimeError("after evidence exists without candidate")
    if not candidate and ("개선 SQL 없음" not in report or any(p.get("code") in {"AFTER_EVIDENCE", "BEFORE_AFTER_COMPARE"} and p.get("status") != "SKIPPED" for p in progress)):
        raise RuntimeError("no-rewrite branch mismatch")
    if lookups:
        for name in ("get_run", "get_progress", "get_report"):
            if not isinstance(lookups.get(name), dict): raise RuntimeError(f"{name} requery missing")
    return verdict


def main():
    conn = connect(); cur = conn.cursor(); out = {}; had_error = False
    try:
        body = json.dumps({"sql": "select * from dual", "source_db_id": "DB0903_TESTDB",
                           "fetch_rows": 10, "vector_top_k": 1, "use_llm": True,
                           "run_advisor": True, "sqltune_time_limit": 60})
        result = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute("begin :out := asta_pkg.analyze_sql(:body); end;", out=result, body=body)
        payload = parse_json("analyze", clob_to_str(result.getvalue())); run_id = payload.get("run_id")
        for endpoint, sql in {
            "get_run": "begin :out := asta_pkg.get_run(:run_id); end;",
            "get_progress": "begin :out := asta_pkg.get_progress(:run_id); end;",
            "get_report": "begin :out := asta_pkg.get_report(:run_id); end;",
        }.items():
            value = cur.var(oracledb.DB_TYPE_CLOB); cur.execute(sql, out=value, run_id=run_id)
            out[f"analyze_persistence_{endpoint}"] = clob_to_str(value.getvalue())
        lookups = require_run_retrievable(out, run_id)
        verdict = validate_workflow_contract(payload, lookups)
        # Deliberately emit only non-sensitive contract summary, never config/credentials/raw artifacts.
        print(json.dumps({"run_id": run_id, "status": payload.get("status"), "verdict": verdict,
                          "workflow": WORKFLOW, "requeries": list(lookups)}, ensure_ascii=False, indent=2))
    except Exception as exc:
        had_error = True; print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
    finally:
        cur.close(); conn.close()
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
