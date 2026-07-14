#!/usr/bin/env python3
"""ADB 직접 LLM 호출 + ADB DB Link Source bridge로 ASTA A/B/C를 비교한다."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import oracledb

from tools.asta_deploy_adb import connect
from tools.run_asta_prompt_abc import load_samples


def clob_text(value) -> str:
    reader = getattr(value, "read", None)
    return str(reader() if callable(reader) else value or "")


def call_clob(cur, name: str, args: list) -> str:
    return clob_text(cur.callfunc(name, oracledb.DB_TYPE_CLOB, args))


def source_evidence(cur, sql: str, run_id: str, repeat_policy: str = "AUTO") -> dict:
    try:
        raw = call_clob(cur, "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", [
            "DB0903_TESTDB", sql, run_id, 100, repeat_policy, "N", 1800,
        ])
        return json.loads(raw)
    except Exception as exc:
        return {
            "status": "FAILED", "run_id": run_id,
            "error": {"code": type(exc).__name__, "message": str(exc)[:4000]},
        }


def vector_evidence(cur, sql: str) -> dict:
    return json.loads(call_clob(cur, "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES", [sql, 3]))


def build_tuning_context(mode: str, workload: str = "OLTP", strategy: str = "AUTO") -> dict:
    strategy_notes = {
        "AUTO": "측정된 지배 병목 하나를 선택해 국소적으로 구조 재작성하세요.",
        "DOMINANT_NOT_EXISTS": "지배적인 correlated NOT EXISTS만 key producer로 분리해 반복 Starts를 제거하세요. DISTINCT CTE가 optimizer에 merge되어 Starts가 유지될 수 있으므로 새 hint 없이 UNION DISTINCT와 결과가 항상 빈 동일 projection branch를 set-operation barrier로 사용하고, XPLAN에서 producer Starts=1인지 확인하세요.",
        "CORRELATED_MIN": "반복 correlated MIN만 정확/와일드카드 grain을 보존해 사전 집계하세요.",
        "REPEATED_FACT_SCAN": "동일 fact table 반복 scan만 조건부 집계 또는 공통 producer로 합치세요.",
    }
    return {
        "prompt_mode": mode,
        "source": "ASTA_PROMPT_ABC_ADB_EXPERIMENT",
        "workload_type": workload.upper(),
        "optimization_goal": "MINIMIZE_ELAPSED_TIME" if workload.upper() == "BATCH" else "MINIMIZE_BUFFER_READS",
        "user_notes": strategy_notes.get(strategy, strategy),
        "candidate_strategy": strategy,
    }


def build_prompt(cur, sql: str, mode: str, source: dict, vector: dict,
                 workload: str = "OLTP", strategy: str = "AUTO") -> str:
    context = build_tuning_context(mode, workload, strategy)
    prompt = call_clob(cur, "ASTA_LLM_PKG.BUILD_TUNING_PROMPT", [
        sql,
        json.dumps(source, ensure_ascii=False),
        json.dumps(vector, ensure_ascii=False),
        json.dumps(context, ensure_ascii=False),
    ])
    return prompt


def evidence_oracle_error(evidence: dict) -> str | None:
    error = evidence.get("error")
    if not isinstance(error, dict):
        return None
    message = str(error.get("message") or "").strip()
    code = error.get("code")
    if "ORA-" in message.upper():
        return message[:4000]
    if isinstance(code, (int, float)):
        return f"ORA-{abs(int(code)):05d}: {message}"[:4000]
    return message[:4000] or None


def generate(cur, prompt: str, profile: str, max_attempts: int = 3) -> tuple[str, int, float]:
    started = time.monotonic()
    prompt_clob = cur.var(oracledb.DB_TYPE_CLOB)
    prompt_clob.setvalue(0, prompt)
    for attempt in range(1, max_attempts + 1):
        cur.execute(
            "select dbms_cloud_ai.generate(prompt=>:p,profile_name=>:profile,action=>'chat') from dual",
            p=prompt_clob,
            profile=profile,
        )
        raw = clob_text(cur.fetchone()[0])
        if raw.strip():
            return raw, attempt, round((time.monotonic() - started) * 1000, 3)
    return "", max_attempts, round((time.monotonic() - started) * 1000, 3)


def extract_candidate(cur, raw: str) -> tuple[str | None, str | None]:
    if not raw.strip():
        return None, "EMPTY_LLM_RESPONSE"
    try:
        sql = call_clob(cur, "ASTA_SQL_GUARD_PKG.EXTRACT_CANDIDATE_SQL", [raw]).strip()
        return (sql or None), (None if sql else "EMPTY_CANDIDATE")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:1000]


def declared_candidate_error(raw: str) -> str | None:
    """Preserve a model's explicit refusal/error instead of flattening it to EMPTY_CANDIDATE."""
    text = (raw or "").strip()
    if not text:
        return "EMPTY_LLM_RESPONSE"
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            payload = json.loads(text[start:end + 1])
            error = payload.get("candidate_error")
            if error:
                return str(error)[:1000]
            if payload.get("candidate_sql") is None:
                return "NO_CANDIDATE_DECLARED"
        except (TypeError, ValueError):
            pass
    upper = text.upper()
    if "NO_SAFE_EFFECTIVE_REWRITE" in upper:
        return "NO_SAFE_EFFECTIVE_REWRITE"
    if "NO_REWRITE" in upper or "NO CANDIDATE" in upper:
        return "NO_CANDIDATE_DECLARED"
    return None


def build_ora_retry_prompt(original_prompt: str, failed_sql: str, oracle_error: str) -> str:
    """Ask for one corrected candidate with the exact Oracle failure attached."""
    return (
        original_prompt
        + "\n\nThe previous candidate failed Oracle validation or execution. Correct only that candidate "
          "while preserving the original SQL semantics. Return only one complete executable Oracle SELECT "
          "or WITH statement; no JSON, Markdown, prose, semicolon, or slash.\n\n"
        + "FAILED CANDIDATE:\n" + failed_sql
        + "\n\nEXACT ORACLE ERROR:\n" + oracle_error[:4000]
    )


def metric(evidence: dict, key: str):
    return evidence.get(key)


def compare(before: dict, after: dict) -> dict:
    bbuf = metric(before, "last_cr_buffer_gets")
    abuf = metric(after, "last_cr_buffer_gets")
    bel = metric(before, "last_elapsed_time_us")
    ael = metric(after, "last_elapsed_time_us")
    rows_match = metric(before, "row_count") == metric(after, "row_count")
    output_match = metric(before, "last_output_rows") == metric(after, "last_output_rows")
    pct = None
    if isinstance(bbuf, (int, float)) and isinstance(abuf, (int, float)) and bbuf:
        pct = round((bbuf - abuf) * 100 / bbuf, 3)
    return {
        "row_count_matches": rows_match,
        "output_rows_match": output_match,
        "runtime_shape_equivalent": rows_match and output_match,
        "before_buffer_gets": bbuf,
        "after_buffer_gets": abuf,
        "buffer_gets_reduction_pct": pct,
        "before_disk_reads": metric(before, "last_disk_reads"),
        "after_disk_reads": metric(after, "last_disk_reads"),
        "before_elapsed_time_us": bel,
        "after_elapsed_time_us": ael,
    }


def _median_metric(runs: list[dict], key: str) -> float | int | None:
    values = [run.get(key) for run in runs if isinstance(run.get(key), (int, float))]
    if not values:
        return None
    value = float(statistics.median(values))
    return int(value) if value.is_integer() else round(value, 3)


def _noise_pct(runs: list[dict], key: str) -> float | None:
    values = [float(run[key]) for run in runs if isinstance(run.get(key), (int, float))]
    if len(values) < 2:
        return None
    middle = statistics.median(values)
    if middle <= 0:
        return None
    return round((max(values) - min(values)) * 100.0 / middle, 3)


def _result_digest(run: dict) -> str | None:
    for key in ("result_digest", "result_hash", "result_checksum"):
        if run.get(key):
            return str(run[key])
    return None


def compare_repeated(
    before_runs: list[dict],
    after_runs: list[dict],
    workload: str,
    max_oltp_elapsed_us: int = 3_000_000,
    max_oltp_elapsed_increase_us: int = 300_000,
    sql_text: str | None = None,
) -> dict:
    """Compare independent measurements by median and never call shape-only checks semantic proof."""
    completed_before = [run for run in before_runs if run.get("status") == "COMPLETED"]
    completed_after = [run for run in after_runs if run.get("status") == "COMPLETED"]
    before_elapsed = _median_metric(completed_before, "last_elapsed_time_us")
    after_elapsed = _median_metric(completed_after, "last_elapsed_time_us")
    before_buffers = _median_metric(completed_before, "last_cr_buffer_gets")
    after_buffers = _median_metric(completed_after, "last_cr_buffer_gets")
    row_shapes = {(run.get("row_count"), run.get("last_output_rows")) for run in completed_before + completed_after}
    shape_equivalent = len(row_shapes) == 1 and bool(completed_before) and bool(completed_after)
    before_digests = {_result_digest(run) for run in completed_before}
    after_digests = {_result_digest(run) for run in completed_after}
    before_digests.discard(None); after_digests.discard(None)
    digest_available = bool(before_digests) and bool(after_digests)
    semantic_equivalent = digest_available and len(before_digests) == 1 and before_digests == after_digests
    equivalence = None
    if sql_text is not None:
        from tools.asta_result_equivalence import verify_result_equivalence
        equivalence = verify_result_equivalence(sql_text, completed_before, completed_after)
        semantic_equivalent = equivalence.get("status") == "VERIFIED"
    before_noise = _noise_pct(completed_before, "last_elapsed_time_us")
    after_noise = _noise_pct(completed_after, "last_elapsed_time_us")

    def reduction(before, after):
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or before <= 0:
            return None
        return round((before - after) * 100.0 / before, 4)

    elapsed_pct = reduction(before_elapsed, after_elapsed)
    buffer_pct = reduction(before_buffers, after_buffers)
    primary_pct = elapsed_pct if workload.upper() == "BATCH" else buffer_pct
    latency_guard_passed = workload.upper() != "OLTP" or (
        isinstance(after_elapsed, (int, float))
        and after_elapsed <= max_oltp_elapsed_us
        and (
            not isinstance(before_elapsed, (int, float))
            or after_elapsed - before_elapsed <= max_oltp_elapsed_increase_us
        )
    )
    return {
        "measurement_count_before": len(completed_before),
        "measurement_count_after": len(completed_after),
        "runtime_shape_equivalent": shape_equivalent,
        "reported_equivalent": shape_equivalent,
        "equivalence_strength": (
            equivalence.get("equivalence_strength") if equivalence else
            ("RESULT_DIGEST" if digest_available else "SHAPE_ONLY")
        ),
        "semantic_equivalent": semantic_equivalent,
        "equivalence_status": equivalence.get("status") if equivalence else None,
        "equivalence_verdict": equivalence.get("reason_code") if equivalence else None,
        "equivalence_evidence": equivalence.get("evidence") if equivalence else None,
        "result_digest_scope": equivalence.get("result_digest_scope") if equivalence else None,
        "result_digest_mode": equivalence.get("result_digest_mode") if equivalence else None,
        "before_elapsed_time_us": before_elapsed,
        "after_elapsed_time_us": after_elapsed,
        "elapsed_time_reduction_pct": elapsed_pct,
        "before_buffer_gets": before_buffers,
        "after_buffer_gets": after_buffers,
        "buffer_gets_reduction_pct": buffer_pct,
        "before_elapsed_noise_pct": before_noise,
        "after_elapsed_noise_pct": after_noise,
        "latency_guard_passed": latency_guard_passed,
        "oltp_latency_target_us": max_oltp_elapsed_us if workload.upper() == "OLTP" else None,
        "oltp_max_elapsed_increase_us": max_oltp_elapsed_increase_us if workload.upper() == "OLTP" else None,
        "primary_metric": "ELAPSED_TIME" if workload.upper() == "BATCH" else "BUFFER_READS",
        "primary_reduction_pct": primary_pct,
    }


def rotate_modes(modes: list[str], sample_index: int, cycle_rotation: int) -> list[str]:
    """시간 회차와 sample 위치를 합쳐 mode 실행 순서 편향을 분산한다."""
    if not modes:
        return []
    offset = (sample_index + cycle_rotation) % len(modes)
    return modes[offset:] + modes[:offset]


def write_summary(outdir: pathlib.Path, results: list[dict], started: str) -> None:
    payload = {"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "results": results}
    (outdir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# ASTA A/B/C ADB 실측 비교", "", "| SQL | 모드 | Prompt | 호출 | 후보 | 동일 | Buffer Gets | 감소율 | Elapsed(us) |", "|---|---:|---:|---:|---|---|---:|---:|---:|"]
    for r in results:
        c = r.get("comparison") or {}
        lines.append(f"| {r['sample_id']} | {r['mode']} | {r['prompt_chars']} | {r['llm_call_count']} | {r['candidate_generated']} | {c.get('runtime_shape_equivalent')} | {c.get('before_buffer_gets')} → {c.get('after_buffer_gets')} | {c.get('buffer_gets_reduction_pct')} | {c.get('before_elapsed_time_us')} → {c.get('after_elapsed_time_us')} |")
    (outdir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="asta-awr-01,asta-awr-02,asta-awr-03")
    ap.add_argument("--modes", default="A,B,C")
    ap.add_argument("--profile", default="ASTA_GROK_REASONING_PROFILE")
    ap.add_argument("--outdir", default=str(ROOT / "reports" / "asta_prompt_abc_adb_latest"))
    ap.add_argument("--rotation", type=int, default=int(os.environ.get("ASTA_EXPERIMENT_ROTATION", "0")))
    ap.add_argument("--strategies", default="AUTO")
    ap.add_argument("--benchmark-runs", type=int, default=1)
    ap.add_argument("--ora-retries", type=int, default=0)
    ap.add_argument("--max-oltp-elapsed-us", type=int, default=3_000_000)
    ap.add_argument("--max-oltp-elapsed-increase-us", type=int, default=300_000)
    ap.add_argument("--source-repeat-policy", default="ONCE")
    ap.add_argument("--call-timeout-sec", type=int, default=240)
    args = ap.parse_args()
    ids = {x.strip() for x in args.samples.split(",") if x.strip()}
    modes = [x.strip().upper() for x in args.modes.split(",") if x.strip()]
    strategies = [x.strip().upper() for x in args.strategies.split(",") if x.strip()]
    benchmark_runs = min(max(args.benchmark_runs, 1), 5)
    ora_retries = min(max(args.ora_retries, 0), 2)
    samples = load_samples(ids)
    outdir = pathlib.Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(); results: list[dict] = []
    conn = connect()
    conn.call_timeout = min(max(args.call_timeout_sec, 30), 1800) * 1000
    cur = conn.cursor()
    try:
        for sample_idx, sample in enumerate(samples):
            root_id = f"ABC{uuid.uuid4().hex[:12].upper()}"
            before_runs = [
                source_evidence(cur, sample["sql"], f"{root_id}B{index}", args.source_repeat_policy)
                for index in range(benchmark_runs)
            ]
            before = before_runs[0]
            vector = vector_evidence(cur, sample["sql"])
            ordered_modes = rotate_modes(modes, sample_idx, args.rotation)
            for order_index, mode in enumerate(ordered_modes, 1):
                for strategy in strategies:
                    prompt = build_prompt(cur, sample["sql"], mode, before, vector,
                                          sample.get("workload") or "OLTP", strategy)
                    attempt_prompt = prompt
                    raw_responses: list[str] = []
                    candidate = None; error = None; after_runs: list[dict] = []
                    calls = 0; llm_ms = 0.0
                    for candidate_attempt in range(1, ora_retries + 2):
                        raw, attempt_calls, attempt_ms = generate(cur, attempt_prompt, args.profile)
                        raw_responses.append(raw); calls += attempt_calls; llm_ms += attempt_ms
                        candidate, extraction_error = extract_candidate(cur, raw)
                        error = declared_candidate_error(raw) or extraction_error
                        if not candidate:
                            if error and "ORA-" in error.upper() and candidate_attempt <= ora_retries:
                                attempt_prompt = build_ora_retry_prompt(prompt, raw, error)
                                continue
                            break
                        after_runs = [
                            source_evidence(cur, candidate, f"{root_id}{mode}{candidate_attempt}{index}",
                                            args.source_repeat_policy)
                            for index in range(benchmark_runs)
                        ]
                        execution_error = next((evidence_oracle_error(item) for item in after_runs
                                                if item.get("status") != "COMPLETED"), None)
                        if execution_error and candidate_attempt <= ora_retries:
                            error = execution_error
                            attempt_prompt = build_ora_retry_prompt(prompt, candidate, execution_error)
                            continue
                        error = execution_error
                        break
                    comp = compare_repeated(
                        before_runs, after_runs, sample.get("workload") or "OLTP",
                        args.max_oltp_elapsed_us, args.max_oltp_elapsed_increase_us,
                        sql_text=sample["sql"],
                    ) if candidate and after_runs else {}
                    row = {
                        "sample_id": sample["id"], "label": sample.get("label"), "mode": mode,
                        "strategy": strategy, "execution_order": order_index, "cycle_rotation": args.rotation,
                        "profile": args.profile, "prompt_chars": len(prompt), "llm_call_count": calls,
                        "llm_elapsed_ms": round(llm_ms, 3),
                        "raw_response_chars": sum(len(item) for item in raw_responses),
                        "candidate_attempt_count": len(raw_responses),
                        "candidate_generated": bool(candidate), "candidate_error": error,
                        "candidate_sql": candidate, "comparison": comp,
                        "baseline_buffer_gets": _median_metric(before_runs, "last_cr_buffer_gets"),
                        "baseline_elapsed_time_us": _median_metric(before_runs, "last_elapsed_time_us"),
                        "before_run_id": before_runs[0].get("run_id") if before_runs else None,
                        "after_run_id": after_runs[0].get("run_id") if after_runs else None,
                        "before_run_ids": [item.get("run_id") for item in before_runs],
                        "after_run_ids": [item.get("run_id") for item in after_runs],
                    }
                    results.append(row)
                    suffix = "" if strategy == "AUTO" else f"_{strategy.lower()}"
                    (outdir / f"{sample['id']}_{mode}{suffix}.json").write_text(
                        json.dumps({"result": row, "before_runs": before_runs, "after_runs": after_runs,
                                    "raw_responses": raw_responses,
                                    "before": before_runs[0] if before_runs else {},
                                    "after": after_runs[0] if after_runs else {},
                                    "raw_response": raw_responses[-1] if raw_responses else ""},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
                    write_summary(outdir, results, started)
                    print(json.dumps({k: row[k] for k in ["sample_id", "mode", "strategy", "prompt_chars",
                                                          "llm_call_count", "raw_response_chars",
                                                          "candidate_generated", "candidate_error", "comparison"]},
                                     ensure_ascii=False), flush=True)
    finally:
        cur.close(); conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
