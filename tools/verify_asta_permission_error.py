#!/usr/bin/env python3
"""Verify the customer-facing ASTA response for a Source SELECT privilege failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

import oracledb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.asta_deploy_adb import connect


TERMINAL = {"COMPLETED", "DONE", "FAILED", "BLOCKED", "REJECTED"}


def _json_lob(value) -> dict:
    text = value.read() if hasattr(value, "read") else str(value)
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {}


def _call(cur, name: str, value: str) -> dict:
    return _json_lob(cur.callfunc(name, oracledb.DB_TYPE_CLOB, [value]))


def main() -> int:
    # Source 계정에 direct SELECT grant가 없음을 이미 확인한 실환경 객체다.
    sql = "select count(*) from DSNT.TGP_ORDER_D"
    run_id = f"OADT2-ASTA-PRIV-{uuid.uuid4().hex[:16]}"
    request = {
        "run_id": run_id,
        "client_run_id": run_id,
        "sql": sql,
        "source_db_id": "DB0903_TESTDB",
        "fetch_rows": 1,
        "benchmark_repeat": 1,
        "use_llm": False,
        "run_advisor": False,
        "use_sqltune": False,
        "sqltune_time_limit": 60,
        "tuning_context": {"workload_type": "OLTP", "user_notes": "permission error contract smoke"},
    }
    conn = connect()
    conn.call_timeout = 120_000
    cur = conn.cursor()
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "--bridge":
            value = cur.callfunc(
                "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
                oracledb.DB_TYPE_CLOB,
                ["DB0903_TESTDB", sql, run_id, 1, "ONCE", "N", 60, None, "BOUNDED", 100],
            )
            payload = _json_lob(value)
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            summary = {
                "run_id": run_id,
                "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                "target_case": "KNOWN_NO_DIRECT_SELECT_GRANT",
                "status": payload.get("status"),
                "oracle_code": error.get("code"),
                "oracle_message": error.get("message"),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if "ORA-" in str(summary["oracle_message"]) else 2
        cur.execute(
            """select run_id, status from (
                 select run_id, status from asta_runs
                  where run_id like 'OADT2-ASTA-PRIV-%'
                    and created_at >= systimestamp - interval '10' minute
                  order by created_at desc
               ) where rownum = 1"""
        )
        existing = cur.fetchone()
        if existing:
            run_id, status = str(existing[0]), str(existing[1]).upper()
        else:
            submitted = _call(cur, "ASTA_PKG.SUBMIT_RUN", json.dumps(request, ensure_ascii=False))
            status = str(submitted.get("status") or "").upper()
        deadline = time.monotonic() + 120
        while status not in TERMINAL:
            if time.monotonic() >= deadline:
                raise TimeoutError("permission error smoke exceeded 120 seconds")
            time.sleep(2)
            cur.execute("select status from asta_runs where run_id=:r", r=run_id)
            row = cur.fetchone()
            status = str(row[0] if row else "NOT_FOUND").upper()
        cur.execute(
            "select status, error_code, error_message from asta_runs where run_id=:r",
            r=run_id,
        )
        final_status, error_code, error_message = cur.fetchone()
        cur.execute(
            """select code, status, detail from asta_run_progress
                where run_id=:r and status='FAILED' order by seq fetch first 1 row only""",
            r=run_id,
        )
        failed_row = cur.fetchone()
        failed_step = (
            {"code": failed_row[0], "status": failed_row[1], "detail": failed_row[2]}
            if failed_row else None
        )
        summary = {
            "run_id": run_id,
            "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "target_case": "KNOWN_NO_DIRECT_SELECT_GRANT",
            "status": final_status,
            "error_code": error_code,
            "error_message": error_message,
            "failed_step": failed_step,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if status == "FAILED" and "ORA-" in str(summary["error_message"]) else 2
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
