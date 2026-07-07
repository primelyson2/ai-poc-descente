#!/usr/bin/env python3
"""BATCH 샘플 원본/후보의 실제 시간과 full-result digest를 순차 검증한다."""

from __future__ import annotations

import hashlib
import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import oracledb

from tools.asta_batch_samples import BATCH_SAMPLES
from tools.asta_deploy_adb import connect


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "asta_batch_samples_20260707" / "verification.json"


def _text(value) -> str:
    return value.read() if hasattr(value, "read") else str(value)


def _num(payload: dict, name: str) -> int | None:
    value = payload.get(name)
    if value is None:
        return None
    return int(float(value))


def execute(cur, sql: str, run_id: str) -> dict:
    started = time.monotonic()
    value = cur.callfunc(
        "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
        oracledb.DB_TYPE_CLOB,
        ["DB0903_TESTDB", sql, run_id, 500, "ONCE", "N", 90, None, "FULL_RESULT", 100000],
    )
    payload = json.loads(_text(value))
    elapsed_us = _num(payload, "last_elapsed_time_us")
    return {
        "status": str(payload.get("status") or "UNKNOWN").upper(),
        "wall_elapsed_sec": round(time.monotonic() - started, 6),
        "elapsed_sec": round((elapsed_us or 0) / 1_000_000, 6),
        "elapsed_us": elapsed_us,
        "buffer_gets": _num(payload, "last_cr_buffer_gets"),
        "row_count": _num(payload, "result_total_rows") or _num(payload, "row_count"),
        "result_digest": payload.get("result_digest"),
        "metadata_digest": payload.get("result_metadata_digest") or payload.get("metadata_digest"),
        "result_digest_scope": payload.get("result_digest_scope"),
        "result_complete": payload.get("result_evidence_complete"),
        "error_code": payload.get("error_code"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default="")
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    selected = {value.strip() for value in args.samples.split(",") if value.strip()}
    samples = [sample for sample in BATCH_SAMPLES if not selected or sample["id"] in selected]
    if not samples:
        raise SystemExit("no matching batch samples")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    # FULL_RESULT는 bounded 실행 + full count + full digest로 동일 SELECT를 최대 3회
    # 수행한다. SQL 자체 목표(35~75초)와 별개로 검증 왕복에는 충분한 여유를 둔다.
    conn.call_timeout = 360_000
    cur = conn.cursor()
    results = []
    if args.append and OUT.exists():
        previous = json.loads(OUT.read_text(encoding="utf-8"))
        results = [
            item for item in previous.get("samples", [])
            if item.get("sample_id") not in {sample["id"] for sample in samples}
        ]
    try:
        for sample in samples:
            suffix = uuid.uuid4().hex[:10]
            original = execute(cur, sample["sql"], f"BATCH-{sample['id'][-2:]}-O-{suffix}")
            candidate = execute(cur, sample["candidate_sql"], f"BATCH-{sample['id'][-2:]}-C-{suffix}")
            digests_match = (
                original["status"] == candidate["status"] == "COMPLETED"
                and original["result_digest"] == candidate["result_digest"]
                and original["metadata_digest"] == candidate["metadata_digest"]
                and original["row_count"] == candidate["row_count"]
                and bool(original["result_complete"])
                and bool(candidate["result_complete"])
            )
            improvement = None
            if original["elapsed_us"] and candidate["elapsed_us"] is not None:
                improvement = round(
                    (original["elapsed_us"] - candidate["elapsed_us"])
                    * 100.0
                    / original["elapsed_us"],
                    4,
                )
            item = {
                "sample_id": sample["id"],
                "label": sample["label"],
                "pattern": sample["pattern"],
                "workload": sample["workload"],
                "change_summary": sample["change_summary"],
                "sql_sha256": hashlib.sha256(sample["sql"].encode()).hexdigest(),
                "candidate_sql_sha256": hashlib.sha256(sample["candidate_sql"].encode()).hexdigest(),
                "original": {k: v for k, v in original.items() if k not in {"result_digest", "metadata_digest"}},
                "candidate": {k: v for k, v in candidate.items() if k not in {"result_digest", "metadata_digest"}},
                "elapsed_improvement_pct": improvement,
                "equivalence_status": "VERIFIED" if digests_match else "NON_EQUIVALENT",
                "result_digest_scope": "FULL_RESULT",
                "result_digest_matches": digests_match,
            }
            results.append(item)
            results.sort(key=lambda value: value["sample_id"])
            OUT.write_text(
                json.dumps(
                    {
                        "schema": "asta.batch-samples.v1",
                        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                        "status": "RUNNING",
                        "source_db_id": "DB0903_TESTDB",
                        "samples": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(json.dumps(item, ensure_ascii=False), flush=True)
    finally:
        cur.close()
        conn.close()

    valid = all(
        item["original"]["status"] == item["candidate"]["status"] == "COMPLETED"
        and 35 <= item["original"]["elapsed_sec"] <= 75
        and item["elapsed_improvement_pct"] is not None
        and item["elapsed_improvement_pct"] >= 20
        and item["result_digest_matches"]
        for item in results
    )
    payload = {
        "schema": "asta.batch-samples.v1",
        "generated_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "status": "COMPLETED" if valid else "REJECTED",
        "source_db_id": "DB0903_TESTDB",
        "sample_count": len(results),
        "samples": results,
        "safety": {"select_with_only": True, "db_changes": False, "side_effects": False},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
