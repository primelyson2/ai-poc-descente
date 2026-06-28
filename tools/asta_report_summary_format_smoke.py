"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

from pathlib import Path
import json
import oracledb
import yaml

ROOT = Path(__file__).resolve().parents[1]
conf = yaml.safe_load((ROOT / "config.yaml").read_text())
db = conf["databases"][0]
wallet = str((ROOT / db["wallet_location"]).resolve())
conn = oracledb.connect(
    user=db["user"],
    password=db["password"],
    dsn=db["dsn"],
    config_dir=wallet,
    wallet_location=wallet,
    wallet_password=db.get("wallet_password"),
)
cur = conn.cursor()
raw_response = '{"candidate_sql":"-- change_reason: UNION ALL 통합\n-- change_summary: 두 SELECT를 단일 GROUP BY로 변경\n-- change_location: WHERE/GROUP BY\nSELECT yy, count(*) cnt FROM dual GROUP BY yy","change_reason":"UNION ALL 통합","change_summary":"두 SELECT를 단일 GROUP BY로 변경","change_location":"WHERE/GROUP BY","rationale":"Buffer Gets 절감 목적","risk_notes":"결과 동일성 검증 필요"}'
source = {
    "status": "COMPLETED",
    "execution_boundary": "SOURCE_BASEDB_DBLINK_ONLY",
    "sql_id": "abc",
    "plan_hash_value": "123",
    "row_count": 2,
    "repeat_count": 2,
    "elapsed_wall_ms": 135,
    "elapsed_wall_ms_per_exec": 67,
    "last_output_rows": 1,
    "last_cr_buffer_gets": 9334,
    "last_disk_reads": 0,
    "last_elapsed_time_us": 65867,
    "advisor_requested": True,
    "sqltune_time_limit_sec": 1800,
    "advisor": {
        "status": "FAILED",
        "report": "SQLTUNE_ERROR: Source DB is in restricted session mode; DBMS_SQLTUNE cannot be executed safely through the ADB DB Link path.",
    },
}
after = {
    "status": "COMPLETED",
    "execution_boundary": "SOURCE_BASEDB_DBLINK_ONLY",
    "sql_id": "def",
    "plan_hash_value": "456",
    "row_count": 2,
    "repeat_count": 2,
    "elapsed_wall_ms": 114,
    "elapsed_wall_ms_per_exec": 57,
    "last_output_rows": 1,
    "last_cr_buffer_gets": 4667,
    "last_disk_reads": 0,
    "last_elapsed_time_us": 55665,
}
comp = {
    "status": "COMPLETED",
    "row_count_matches": True,
    "output_rows_match": True,
    "before_row_count": 2,
    "after_row_count": 2,
    "before_buffer_gets": 9334,
    "after_buffer_gets": 4667,
    "buffer_gets_delta": 4667,
    "buffer_gets_reduction_pct": 50,
    "before_disk_reads": 0,
    "after_disk_reads": 0,
    "disk_reads_delta": 0,
    "before_elapsed_time_us": 65867,
    "after_elapsed_time_us": 55665,
    "elapsed_time_us_delta": 10202,
}
llm = {"status": "COMPLETED", "raw_response": raw_response}
vector = {"status": "COMPLETED", "search_strategy": "FINGERPRINT_FIRST_CHUNK_SCAN", "top_k": 3, "query_fingerprint": "fp"}
out = cur.var(oracledb.DB_TYPE_CLOB)
cur.execute(
    """
begin :out := asta_report_pkg.build_report(
  p_run_id => 'SMOKE_SUMMARY_FORMAT',
  p_input_sql => 'select * from dual',
  p_source_evidence_json => :source_json,
  p_vector_json => :vector_json,
  p_llm_json => :llm_json,
  p_status => 'COMPLETED',
  p_after_evidence_json => :after_json,
  p_comparison_json => :comp_json
); end;""",
    out=out,
    source_json=json.dumps(source, ensure_ascii=False),
    vector_json=json.dumps(vector, ensure_ascii=False),
    llm_json=json.dumps(llm, ensure_ascii=False),
    after_json=json.dumps(after, ensure_ascii=False),
    comp_json=json.dumps(comp, ensure_ascii=False),
)
report = out.getvalue().read()
path = ROOT / "reports/asta_report_summary_format_smoke_latest.md"
path.write_text(report, encoding="utf-8")
checks = {
    "result_summary_before_input": report.index("## 결과 요약") < report.index("## Input SQL"),
    "llm_readable_heading": "## LLM 튜닝 요약" in report,
    "old_raw_heading_absent": "LLM 원문 요약/응답" not in report,
    "raw_json_dump_absent": '{"candidate_sql"' not in report,
    "advisor_failure_in_summary": "SQLTUNE_ERROR: Source DB is in restricted session mode" in report.split("## Input SQL", 1)[0],
    "candidate_sql_from_raw": "-- change_reason: UNION ALL 통합" in report,
}
print(json.dumps({"path": str(path), "checks": checks, "all_passed": all(checks.values())}, ensure_ascii=False, indent=2))
cur.close()
conn.close()
raise SystemExit(0 if all(checks.values()) else 1)
