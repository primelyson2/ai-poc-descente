#!/usr/bin/env python3
"""Run bounded Real ASTA UI samples sequentially and persist redacted gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import oracledb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.asta_deploy_adb import connect
from tools.asta_sample_sql_verifier import load_samples, referenced_objects
from tools.asta_sample_candidates import CANDIDATES
from tools.run_asta_10_sqls import _call_json


OUTDIR = ROOT / "reports" / "asta_sample14_campaign_20260706"
SOURCE_VERIFICATION = ROOT / "reports" / "asta_sample_sqls_under_60s" / "verification.json"
CAMPAIGN_SUMMARY = ROOT / "reports" / "asta_new_samples_20260706" / "campaign_summary.json"
TERMINAL = {"COMPLETED", "DONE", "FAILED", "CANCELLED", "TIMED_OUT", "BLOCKED", "REJECTED"}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _number(*values):
    for value in values:
        if value is not None:
            try:
                return int(float(value))
            except (TypeError, ValueError):
                pass
    return None


def _comparison(payload: dict) -> dict:
    return _dict(payload.get("comparison")) or _dict(_dict(payload.get("artifacts")).get("comparison"))


def _artifact(payload: dict, name: str) -> dict:
    return _dict(_dict(payload.get("artifacts")).get(name))


def _metric(evidence: dict, metric: str):
    return _number(
        evidence.get(f"median_{metric}"),
        evidence.get(f"last_{metric}"),
        evidence.get(metric),
    )


def _lob_json(value) -> dict:
    if value is None:
        return {}
    text = value.read() if hasattr(value, "read") else str(value)
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {}


def wait_for_terminal_safe(cur, run_id: str, timeout_sec: int = 3600) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        progress = _call_json(cur, "ASTA_PKG.GET_PROGRESS", run_id)
        if str(progress.get("status") or "").upper() in TERMINAL:
            cur.execute(
                """select status,
                     json_query(response_json,'$.comparison' returning clob null on error),
                     json_query(response_json,'$.artifacts.source_evidence' returning clob null on error),
                     json_query(response_json,'$.artifacts.after_evidence' returning clob null on error)
                   from asta_runs where run_id=:r""",
                r=run_id,
            )
            status, comparison, before, after = cur.fetchone()
            return {
                "run_id": run_id,
                "status": status,
                "comparison": _lob_json(comparison),
                "artifacts": {
                    "source_evidence": _lob_json(before),
                    "after_evidence": _lob_json(after),
                },
            }
        time.sleep(2)
    raise TimeoutError(f"ASTA run did not become terminal: {run_id}")


def summarize(sample: dict, payload: dict, source_record: dict, candidate_bytes: int) -> dict:
    comparison = _comparison(payload)
    before_evidence = _artifact(payload, "source_evidence") or _dict(payload.get("runtime_evidence"))
    after_evidence = _artifact(payload, "after_evidence")
    before_elapsed = _number(comparison.get("before_elapsed_time_us"), _metric(before_evidence, "elapsed_time_us"))
    after_elapsed = _number(comparison.get("after_elapsed_time_us"), _metric(after_evidence, "elapsed_time_us"))
    before_buffers = _number(comparison.get("before_buffer_gets"), _metric(before_evidence, "buffer_gets"))
    after_buffers = _number(comparison.get("after_buffer_gets"), _metric(after_evidence, "buffer_gets"))
    improvement = None
    if before_elapsed and after_elapsed is not None:
        improvement = round((before_elapsed - after_elapsed) * 100.0 / before_elapsed, 4)
    bind_status = str(comparison.get("bind_stability_status") or "UNKNOWN").upper()
    if str(comparison.get("bind_stability_reason") or "").upper() == "BIND_NOT_APPLICABLE":
        bind_status = "NOT_APPLICABLE"
    status = str(payload.get("status") or "UNKNOWN").upper()
    verdict = str(comparison.get("verdict") or "UNKNOWN").upper()
    return {
        "sample_id": sample["id"],
        "label": sample.get("label"),
        "pattern": sample.get("pattern"),
        "run_id": payload.get("run_id"),
        "status": status,
        "source_status": source_record.get("status"),
        "source_wall_elapsed_sec": source_record.get("elapsed_sec"),
        "source_elapsed_us": source_record.get("source_elapsed_us"),
        "sql_safety": "SELECT_WITH_ONLY_BOUNDED",
        "sql_sha256": hashlib.sha256(sample["sql"].encode("utf-8")).hexdigest(),
        "referenced_objects": sorted(referenced_objects(sample["sql"])),
        "candidate_status": "VALID" if candidate_bytes > 0 and after_evidence.get("status") == "COMPLETED" else "MISSING_OR_FAILED",
        "candidate_bytes": candidate_bytes,
        "final_verdict": verdict,
        "verdict_reason": comparison.get("verdict_reason"),
        "equivalence_status": comparison.get("equivalence_status"),
        "equivalence_reason": comparison.get("equivalence_reason"),
        "optimizer_intent_status": comparison.get("optimizer_intent_status"),
        "optimizer_intent_reason": comparison.get("optimizer_intent_reason"),
        "measurement_status": comparison.get("measurement_status"),
        "measurement_reason": comparison.get("measurement_reason"),
        "bind_status": bind_status,
        "bind_reason": comparison.get("bind_stability_reason"),
        "before": {
            "elapsed_us": before_elapsed,
            "buffer_gets": before_buffers,
            "repeat_count": _number(comparison.get("before_repeat_count"), before_evidence.get("repeat_count")),
            "measurement_run_count": len(before_evidence.get("measurement_runs") or []),
        },
        "after": {
            "elapsed_us": after_elapsed,
            "buffer_gets": after_buffers,
            "repeat_count": _number(comparison.get("after_repeat_count"), after_evidence.get("repeat_count")),
            "measurement_run_count": len(after_evidence.get("measurement_runs") or []),
        },
        "elapsed_improvement_pct": improvement,
        "result_digest_scope": comparison.get("result_digest_scope"),
        "result_digest_matches": comparison.get("result_digest_matches"),
    }


def run(selected_ids: set[str] | None = None) -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    source_payload = json.loads(SOURCE_VERIFICATION.read_text(encoding="utf-8"))
    source_records = {item["sample_id"]: item for item in source_payload["samples"]}
    samples = [sample for sample in load_samples()[1:] if not selected_ids or sample["id"] in selected_ids]
    if not samples:
        raise RuntimeError("no matching samples")
    conn = connect()
    conn.call_timeout = 180_000
    cur = conn.cursor()
    results: list[dict] = []
    started = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    try:
        for sample in samples:
            source_record = source_records.get(sample["id"])
            if not source_record or source_record.get("status") != "COMPLETED" or source_record.get("elapsed_sec", 60) >= 60:
                raise RuntimeError(f"source preflight not satisfied: {sample['id']}")
            candidate_sql = CANDIDATES[sample["id"]]
            conn.call_timeout = 55_000
            candidate_probe_id = f"S14P-{sample['id'][-2:]}-{uuid.uuid4().hex[:12]}"
            candidate_probe = cur.callfunc(
                "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", oracledb.DB_TYPE_CLOB,
                ["DB0903_TESTDB", candidate_sql, candidate_probe_id, 200, "ONCE", "N", 55,
                 None, "FULL_RESULT", 100000],
            )
            candidate_probe_payload = json.loads(
                candidate_probe.read() if hasattr(candidate_probe, "read") else str(candidate_probe)
            )
            if candidate_probe_payload.get("status") != "COMPLETED":
                raise RuntimeError(f"candidate preflight failed: {sample['id']}")
            conn.call_timeout = 180_000
            run_id = f"OADT2-ASTA-S14-{sample['id'].rsplit('-', 1)[-1]}-{uuid.uuid4().hex[:16]}"
            body = {
                "run_id": run_id,
                "client_run_id": run_id,
                "sql": sample["sql"],
                "source_db_id": "DB0903_TESTDB",
                "use_llm": True,
                "validation_candidate_sql": candidate_sql,
                "run_advisor": False,
                "use_sqltune": False,
                "llm_profile": "ASTA_GROK_REASONING_PROFILE",
                "ai_profile": "ASTA_GROK_REASONING_PROFILE",
                "fetch_rows": 200,
                "sqltune_time_limit": 60,
                "tuning_context": {
                    "workload_type": sample.get("workload") or "OLTP",
                    "optimization_goal": "MINIMIZE_BUFFER_READS",
                    "user_notes": f"Bounded sample {sample['id']}: {sample.get('pattern') or ''}",
                },
            }
            submitted = cur.callfunc("ASTA_PKG.SUBMIT_RUN", oracledb.DB_TYPE_CLOB, [json.dumps(body, ensure_ascii=False)])
            submitted_payload = json.loads(submitted.read() if hasattr(submitted, "read") else str(submitted))
            if str(submitted_payload.get("status") or "").upper() not in {"QUEUED", "RUNNING"}:
                raise RuntimeError(f"submit failed for {sample['id']}: {submitted_payload.get('error_code')}")
            payload = wait_for_terminal_safe(cur, run_id, timeout_sec=3600)
            cur.execute("select dbms_lob.getlength(tuned_sql) from asta_runs where run_id=:r", r=run_id)
            candidate_bytes = int(cur.fetchone()[0] or 0)
            result = summarize(sample, payload, source_record, candidate_bytes)
            results.append(result)
            (OUTDIR / f"{sample['id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (OUTDIR / "progress.json").write_text(
                json.dumps({"started_at_kst": started, "results": results}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(json.dumps({
                "sample_id": result["sample_id"], "run_id": result["run_id"],
                "status": result["status"], "verdict": result["final_verdict"],
                "reason": result["verdict_reason"], "before": result["before"],
                "after": result["after"],
            }, ensure_ascii=False), flush=True)
    finally:
        cur.close()
        conn.close()
    completed = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    summary = {"started_at_kst": started, "completed_at_kst": completed, "results": results}
    (OUTDIR / "initial_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def finalize() -> int:
    samples = {sample["id"]: sample for sample in load_samples()[1:]}
    source_payload = json.loads(SOURCE_VERIFICATION.read_text(encoding="utf-8"))
    source_records = {item["sample_id"]: item for item in source_payload["samples"]}
    candidates = []
    for sample_id in sorted(samples):
        item = json.loads((OUTDIR / f"{sample_id}.json").read_text(encoding="utf-8"))
        current_hash = hashlib.sha256(samples[sample_id]["sql"].encode("utf-8")).hexdigest()
        source = source_records[sample_id]
        if item.get("final_verdict") != "IMPROVED":
            raise RuntimeError(f"final sample is not IMPROVED: {sample_id}")
        if item.get("sql_sha256") != current_hash or source.get("sql_sha256") != current_hash:
            raise RuntimeError(f"stale SQL hash evidence: {sample_id}")
        if source.get("status") != "COMPLETED" or source.get("elapsed_sec", 60) >= 60:
            raise RuntimeError(f"invalid Source runtime evidence: {sample_id}")
        item["source_wall_elapsed_sec"] = source["elapsed_sec"]
        item["source_elapsed_us"] = source.get("source_elapsed_us")
        item["tuning_change_summary"] = {
            "asta-awr-02": "상관 EXISTS의 광범위 view 접근을 bounded key 집합 1회 생성 후 join으로 전환",
            "asta-awr-03": "상관 NOT EXISTS 제외키 반복을 bounded anti key 집합으로 전환",
            "asta-awr-04": "제외키 상관 반복을 단일 bounded anti join으로 전환",
            "asta-awr-05": "동일 입출고 fact의 두 집계를 conditional single aggregation으로 통합",
            "asta-awr-06": "중복 NVL/UPPER 조건을 제거해 동일 indexable 조건으로 단순화",
            "asta-awr-07": "DISTINCT+상관 EXISTS를 bounded key join으로 전환",
            "asta-awr-08": "중복 제거 UNION 내부 반복 접근을 bounded key 집합 1회 접근으로 전환",
            "asta-awr-09": "복합키 상관 EXISTS를 bounded key join으로 전환",
            "asta-awr-10": "두 EXISTS producer를 각각 1회 생성한 key join으로 전환",
            "asta-awr-11": "SEMI/ANTI 혼합 반복을 bounded key join과 anti join으로 전환",
            "asta-awr-12": "동일 주문 fact의 두 집계를 conditional single aggregation으로 통합",
            "asta-awr-13": "EXISTS/NOT EXISTS 연쇄를 bounded semi/anti key 집합으로 전환",
            "asta-awr-14": "월판매 SUM/COUNT 이중 GROUP BY를 단일 GROUP BY로 통합",
            "asta-awr-15": "NVL/UPPER/TRIM 함수 상관 조건을 bounded normalized key join으로 전환",
        }[sample_id]
        candidates.append(item)
    conn = connect(); cur = conn.cursor()
    try:
        cur.execute("select count(*) from asta_runs where run_id like 'OADT2-ASTA-S14-%'")
        execution_count = int(cur.fetchone()[0])
        cur.execute("select count(*) from asta_runs where run_id like 'OADT2-ASTA-S14-%' and status in ('QUEUED','RUNNING')")
        active_count = int(cur.fetchone()[0])
    finally:
        cur.close(); conn.close()
    if active_count:
        raise RuntimeError(f"sample campaign still has {active_count} active runs")
    summary = {
        "schema": "asta.new-sample-campaign.v2",
        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "status": "COMPLETED",
        "target_sample_count": 14,
        "successful_sample_count": 14,
        "source_sql_execution_count": 14,
        "asta_e2e_execution_count": execution_count,
        "protected_sample_ids": ["asta-awr-01"],
        "added_sample_ids": [item["sample_id"] for item in candidates],
        "candidates": candidates,
        "safety": {
            "select_with_only": True, "bounded_fanout": True, "side_effects": False,
            "git_commit_or_push": False,
        },
    }
    CAMPAIGN_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    CAMPAIGN_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "COMPLETED", "successful": 14,
                      "asta_e2e_execution_count": execution_count}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default="")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        return finalize()
    selected = {item.strip() for item in args.samples.split(",") if item.strip()} or None
    return run(selected)


if __name__ == "__main__":
    raise SystemExit(main())
