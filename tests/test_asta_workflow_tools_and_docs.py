"""Task 9~11: 로컬 도구, 대표 workflow, 문서 계약 테스트."""
from collections import Counter
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(verdict, *, candidate=True, advisor="COMPLETED", vector_cases=None,
           before=(100, 1000, 4), after=(50, 900, 2), equivalent=True):
    labels = {
        "IMPROVED": "개선 성공", "NOT_IMPROVED": "개선실패",
        "CANDIDATE_FAILED": "후보 실행 실패", "NON_EQUIVALENT": "결과 불일치",
        "NO_REWRITE": "개선 SQL 없음", "INSUFFICIENT_EVIDENCE": "측정 불충분",
    }
    progress = [
        {"code": c, "status": "DONE"} for c in
        ["REQUEST_RECEIVED", "ORDS_DISPATCH", "SQL_GUARD", "BEFORE_EVIDENCE",
         "SQL_TUNING_ADVISOR", "LLM_REWRITE", "AFTER_EVIDENCE",
         "BEFORE_AFTER_COMPARE", "VECTOR_KB", "FINAL_REPORT", "VECTOR_SAVE"]
    ]
    if not candidate:
        progress[6]["status"] = progress[7]["status"] = "SKIPPED"
    if advisor == "FAILED": progress[4]["status"] = "FAILED"
    bgets, belapsed, bread = before
    agets, aelapsed, aread = after
    comparison = {"verdict": verdict, "retain_original_sql": verdict != "IMPROVED",
                  "equivalence_status": "EQUIVALENT" if equivalent else "NON_EQUIVALENT",
                  "before_buffer_gets": bgets, "after_buffer_gets": agets,
                  "before_elapsed_time_us": belapsed, "after_elapsed_time_us": aelapsed,
                  "before_disk_reads": bread, "after_disk_reads": aread}
    payload = {
        "run_id": "R1", "status": "COMPLETED", "input_sql": "select * from t",
        "runtime_evidence": {"xplan": "PLAN", "advisor": {"status": advisor}},
        "llm_artifact": {"mode": "SQL_ONLY_STRUCTURAL_REWRITE", "rewrite_available": candidate},
        "comparison": comparison, "vector": {"cases": vector_cases or []},
        "final_review": {"status": "SKIPPED", "reason": "DETERMINISTIC_COMPARISON"},
        "progress": progress,
        "detailed_report_markdown": f"# SQL 튜닝 결과서\n결론: {labels[verdict]}\nverdict: {verdict}\n" +
            ("## 튜닝 SQL\nselect * from t2\n## After XPLAN\nPLAN2" if candidate else "개선 SQL 없음"),
    }
    if candidate:
        payload["candidate_sql"] = "select * from t2"
        payload["after_evidence"] = {"xplan": "PLAN2"}
    return payload


def test_deploy_compile_order_is_dependency_order():
    deploy = load_tool("asta_deploy_adb")
    assert deploy.DEPLOY_PACKAGE_ORDER == [
        "db/adb/asta_sql_guard_pkg.sql", "db/adb/asta_source_bridge_pkg.sql",
        "db/adb/asta_vector_pkg.sql", "db/adb/asta_llm_pkg.sql",
        "db/adb/asta_report_pkg.sql", "db/adb/asta_pkg.sql",
    ]


def test_smoke_contract_accepts_representative_scenarios_and_requeries():
    smoke = load_tool("asta_smoke_adb")
    scenarios = [
        result("IMPROVED"),
        result("NOT_IMPROVED", before=(100, 1000, 8), after=(70, 1200, 3)),
        result("CANDIDATE_FAILED"),
        result("NON_EQUIVALENT", equivalent=False),
        result("NO_REWRITE", candidate=False),
        result("IMPROVED", advisor="FAILED"),
        result("IMPROVED", vector_cases=[]),
        result("IMPROVED", vector_cases=[{"report_ref": "/api/asta/runs/OLD/report"}]),
        result("IMPROVED", before=(100, 1000, 20), after=(50, 900, 5)),
        result("IMPROVED", before=(1000, 100, 0), after=(100, 90, 0)),
    ]
    for payload in scenarios:
        lookups = {"get_run": {"run_id": "R1"}, "get_progress": {"progress": payload["progress"]},
                   "get_report": {"run_id": "R1", "report_markdown": payload["detailed_report_markdown"]}}
        assert smoke.validate_workflow_contract(payload, lookups) == payload["comparison"]["verdict"]


def test_smoke_contract_rejects_order_status_report_and_after_mismatches():
    smoke = load_tool("asta_smoke_adb")
    bad = result("IMPROVED")
    bad["progress"][5], bad["progress"][8] = bad["progress"][8], bad["progress"][5]
    import pytest
    with pytest.raises(RuntimeError, match="progress order"):
        smoke.validate_workflow_contract(bad, {})
    for mutate, message in [
        (lambda p: p["final_review"].update(status="COMPLETED"), "final review"),
        (lambda p: p.update(detailed_report_markdown="결론: 개선실패"), "report verdict"),
        (lambda p: p.pop("after_evidence"), "candidate after"),
    ]:
        bad = result("IMPROVED"); mutate(bad)
        with pytest.raises(RuntimeError, match=message): smoke.validate_workflow_contract(bad, {})


def test_10sql_summary_and_verdict_aggregation_are_deterministic():
    runner = load_tool("run_asta_10_sqls")
    summaries = [runner.summarize(result(v, candidate=v != "NO_REWRITE")) for v in
                 ["IMPROVED", "IMPROVED", "NOT_IMPROVED", "NO_REWRITE"]]
    assert [s["verdict"] for s in summaries] == ["IMPROVED", "IMPROVED", "NOT_IMPROVED", "NO_REWRITE"]
    assert runner.aggregate_verdicts(summaries) == Counter({"IMPROVED": 2, "NOT_IMPROVED": 1, "NO_REWRITE": 1})


def test_current_docs_describe_evidence_aware_workflow_and_links():
    docs = ["OADT2_ASTA_ARCHITECTURE.md", "AI_SQL_TUNING_ASSISTANT_PROGRAM_SPEC.md",
            "AI_SQL_TUNING_ASSISTANT_MANUAL.md", "README.md"]
    texts = [(ROOT / "docs" / name).read_text(encoding="utf-8") for name in docs]
    for text in texts:
        assert "2026-07-03" in text
        assert "Vector" in text or "VECTOR_KB" in text
        assert "BEFORE_AFTER_COMPARE" in text
        assert "XPLAN" in text
        assert "deterministic" in text
        assert "/api/asta/runs/{run_id}/report" in text
        assert "DB Link" in text and "thin proxy" in text
    joined = "\n".join(texts)
    for verdict in ["IMPROVED", "NOT_IMPROVED", "CANDIDATE_FAILED", "NON_EQUIVALENT", "NO_REWRITE"]:
        assert verdict in joined
    assert "LLM_FINAL_REVIEW` | AI Before/After" not in joined
