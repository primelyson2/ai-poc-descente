#!/usr/bin/env python3
"""ADB→DB Link→Source Advisor job/task cleanup targeted smoke."""

from __future__ import annotations

import json
import uuid

import oracledb

from tools.asta_deploy_adb import connect


SOURCE_DB_ID = "DB0903_TESTDB"
DB_LINK = "ASTA_ORCLAI_LINK"


def clob_text(value) -> str:
    return value.read() if hasattr(value, "read") else str(value or "")


def scheduler_jobs(cur) -> list[tuple]:
    cur.execute(f"""
        select job_name, state, enabled, run_count, failure_count
          from user_scheduler_jobs@{DB_LINK}
         where job_name like 'ASTA_ADV_%'
         order by job_name
    """)
    return [tuple(row) for row in cur.fetchall()]


def tuning_tasks(cur) -> list[str]:
    cur.execute(f"""
        select task_name
          from user_advisor_tasks@{DB_LINK}
         where task_name like 'ASTA_%'
         order by task_name
    """)
    return [str(row[0]) for row in cur.fetchall()]


def main() -> int:
    run_id = "ASTA-ADV-CLEANUP-SMOKE-" + uuid.uuid4().hex[:20]
    sql = "select /* ASTA_ADVISOR_JOB_CLEANUP_SMOKE */ cast(null as number) n, 'ASTA' v from dual"
    conn = connect()
    conn.call_timeout = 120_000
    cur = conn.cursor()
    try:
        jobs_before = scheduler_jobs(cur)
        tasks_before = tuning_tasks(cur)
        value = cur.callfunc(
            "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
            oracledb.DB_TYPE_CLOB,
            [SOURCE_DB_ID, sql, run_id, 10, "ONCE", "Y", 60, None, "BOUNDED", 100],
        )
        payload = json.loads(clob_text(value))
        jobs_after = scheduler_jobs(cur)
        tasks_after = tuning_tasks(cur)
        advisor = payload.get("advisor") if isinstance(payload.get("advisor"), dict) else {}
        cleanup_status = str(advisor.get("cleanup_status") or "")
        result = {
            "run_id": run_id,
            "status": payload.get("status"),
            "advisor_status": advisor.get("status"),
            "cleanup_status": cleanup_status,
            "cleanup_detail": advisor.get("cleanup_detail"),
            "scheduler_jobs_before": jobs_before,
            "scheduler_jobs_after": jobs_after,
            "tuning_tasks_before": tasks_before,
            "tuning_tasks_after": tasks_after,
            "legacy_scheduler_jobs_preserved": jobs_after == jobs_before,
            "tuning_tasks_unchanged": tasks_after == tasks_before,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if str(payload.get("status") or "").upper() != "COMPLETED":
            raise RuntimeError("Source evidence did not complete")
        if str(advisor.get("status") or "").upper() != "COMPLETED":
            raise RuntimeError("SQL Tuning Advisor did not complete")
        if cleanup_status not in {"DROPPED", "ALREADY_REMOVED"}:
            raise RuntimeError(f"unexpected Scheduler cleanup status: {cleanup_status or 'missing'}")
        if jobs_after != jobs_before:
            raise RuntimeError("ASTA_ADV scheduler job set changed; generated job was not isolated or cleaned")
        if tasks_after != tasks_before:
            raise RuntimeError("DBMS_SQLTUNE task set changed; task cleanup regressed")
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
