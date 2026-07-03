#!/usr/bin/env python3
"""ADB 직접 LLM 호출 + ADB DB Link Source bridge로 ASTA A/B/C를 비교한다."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
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


def source_evidence(cur, sql: str, run_id: str) -> dict:
    raw = call_clob(cur, "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", [
        "DB0903_TESTDB", sql, run_id, 100, "AUTO", "N", 1800,
    ])
    return json.loads(raw)


def vector_evidence(cur, sql: str) -> dict:
    return json.loads(call_clob(cur, "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES", [sql, 3]))


def build_prompt(cur, sql: str, mode: str, source: dict, vector: dict) -> str:
    context = {"prompt_mode": mode, "source": "ASTA_PROMPT_ABC_ADB_EXPERIMENT"}
    return call_clob(cur, "ASTA_LLM_PKG.BUILD_TUNING_PROMPT", [
        sql,
        json.dumps(source, ensure_ascii=False),
        json.dumps(vector, ensure_ascii=False),
        json.dumps(context, ensure_ascii=False),
    ])


def generate(cur, prompt: str, profile: str, max_attempts: int = 3) -> tuple[str, int, float]:
    started = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        cur.execute(
            "select dbms_cloud_ai.generate(prompt=>:p,profile_name=>:profile,action=>'chat') from dual",
            p=prompt,
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
    ap.add_argument("--profile", default="ASTA_GPT5_PROFILE")
    ap.add_argument("--outdir", default=str(ROOT / "reports" / "asta_prompt_abc_adb_latest"))
    ap.add_argument("--rotation", type=int, default=int(os.environ.get("ASTA_EXPERIMENT_ROTATION", "0")))
    args = ap.parse_args()
    ids = {x.strip() for x in args.samples.split(",") if x.strip()}
    modes = [x.strip().upper() for x in args.modes.split(",") if x.strip()]
    samples = load_samples(ids)
    outdir = pathlib.Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(); results: list[dict] = []
    conn = connect(); cur = conn.cursor()
    try:
        for sample_idx, sample in enumerate(samples):
            root_id = f"ABC{uuid.uuid4().hex[:12].upper()}"
            before = source_evidence(cur, sample["sql"], root_id + "B")
            vector = vector_evidence(cur, sample["sql"])
            ordered_modes = rotate_modes(modes, sample_idx, args.rotation)
            for order_index, mode in enumerate(ordered_modes, 1):
                prompt = build_prompt(cur, sample["sql"], mode, before, vector)
                raw, calls, llm_ms = generate(cur, prompt, args.profile)
                candidate, error = extract_candidate(cur, raw)
                after = source_evidence(cur, candidate, root_id + mode) if candidate else {}
                comp = compare(before, after) if candidate and after.get("status") == "COMPLETED" else {}
                row = {
                    "sample_id": sample["id"], "label": sample.get("label"), "mode": mode,
                    "execution_order": order_index, "cycle_rotation": args.rotation,
                    "profile": args.profile, "prompt_chars": len(prompt), "llm_call_count": calls,
                    "llm_elapsed_ms": llm_ms, "raw_response_chars": len(raw),
                    "candidate_generated": bool(candidate), "candidate_error": error,
                    "candidate_sql": candidate, "comparison": comp,
                    "before_run_id": before.get("run_id"), "after_run_id": after.get("run_id"),
                }
                results.append(row)
                (outdir / f"{sample['id']}_{mode}.json").write_text(json.dumps({"result": row, "before": before, "after": after, "raw_response": raw}, ensure_ascii=False, indent=2), encoding="utf-8")
                write_summary(outdir, results, started)
                print(json.dumps({k: row[k] for k in ["sample_id", "mode", "prompt_chars", "llm_call_count", "raw_response_chars", "candidate_generated", "candidate_error", "comparison"]}, ensure_ascii=False), flush=True)
    finally:
        cur.close(); conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
