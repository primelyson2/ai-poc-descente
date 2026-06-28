#!/usr/bin/env python3
"""Collect source-side runtime XPLAN for OADT2 ASTA.

Runs in a separate process so it can initialize python-oracledb thick mode for
BaseDB native network encryption while the FastAPI app remains thin-mode for ADB.
Input: JSON on stdin. Output: JSON on stdout. Secrets are read from file/env and
never printed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import oracledb

DEFAULT_SOURCE_DB_LINK = "DB0903_LINK"
DEFAULT_SOURCE_SCHEMA = "DEVDO"
DEFAULT_SOURCE_DSN = "(DESCRIPTION=(CONNECT_TIMEOUT=5)(TRANSPORT_CONNECT_TIMEOUT=3)(ADDRESS=(PROTOCOL=TCP)(HOST=127.0.0.1)(PORT=11521))(CONNECT_DATA=(SERVICE_NAME=db0903_pdb1.sub12230451020.vcndsh.oraclevcn.com)))"


def _run_id(sql: str) -> str:
    return "OADT2-ASTA-" + hashlib.sha1(sql.encode("utf-8", errors="ignore")).hexdigest()[:12].upper()


def _normalize_source_sql(sql: str, source_schema: str, source_db_link: str) -> str:
    schema = re.sub(r"[^A-Za-z0-9_$#]", "", str(source_schema or DEFAULT_SOURCE_SCHEMA)).upper()
    text = str(sql or "")
    text = re.sub(r"@\s*" + re.escape(str(source_db_link or DEFAULT_SOURCE_DB_LINK)) + r"\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bASKORACLE\.", f"{schema}.", text, flags=re.IGNORECASE)
    return text.rstrip(";").strip()


def _load_source_config(secret_file: str | None, source_db_link: str) -> dict[str, str]:
    link = str(source_db_link or DEFAULT_SOURCE_DB_LINK).upper()
    if link != DEFAULT_SOURCE_DB_LINK:
        raise RuntimeError(f"Unsupported source_db_link for direct source execution: {source_db_link}")
    cfg: dict[str, Any] = {}
    p = Path(secret_file) if secret_file else Path(".secrets/source_db.json")
    if p.exists():
        raw = json.loads(p.read_text(encoding="utf-8"))
        cfg = raw.get(link, raw) if isinstance(raw, dict) else {}
    user = os.environ.get("ASTA_SOURCE_DB_USER") or cfg.get("user") or DEFAULT_SOURCE_SCHEMA
    password = os.environ.get("ASTA_SOURCE_DB_PASSWORD") or cfg.get("password")
    dsn = os.environ.get("ASTA_SOURCE_DB_DSN") or cfg.get("dsn") or DEFAULT_SOURCE_DSN
    if not password or not dsn:
        raise RuntimeError("Source DB direct connection is not configured")
    return {"user": str(user), "password": str(password), "dsn": str(dsn)}


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    client_dir = os.environ.get("ORACLE_CLIENT_LIB_DIR") or "/home/ubuntu/oracle/instantclient_21_10"
    if Path(client_dir).exists():
        oracledb.init_oracle_client(lib_dir=client_dir)

    source_schema = payload.get("source_schema") or DEFAULT_SOURCE_SCHEMA
    source_db_link = payload.get("source_db_link") or DEFAULT_SOURCE_DB_LINK
    source_sql = _normalize_source_sql(payload.get("sql") or "", source_schema, source_db_link)
    if not source_sql:
        raise RuntimeError("SQL text required")

    run_marker = _run_id(source_sql)
    fetch_limit = max(1, min(int(payload.get("fetch_rows") or 100), 100000))
    sqltune_time_limit = max(1, min(int(payload.get("sqltune_time_limit") or 1800), 7200))
    run_advisor = bool(payload.get("run_advisor", True))
    runtime_sql = (
        f"SELECT /*+ gather_plan_statistics */ /* ASTA_RUN_ID={run_marker} */ COUNT(*) AS ASTA_ROW_COUNT\n"
        "  FROM (\n"
        f"{source_sql}\n"
        "  ) ASTA_SRC\n"
        " WHERE ROWNUM <= :asta_fetch_rows"
    )
    cfg = _load_source_config(payload.get("secret_file"), source_db_link)
    started = time.perf_counter()
    with oracledb.connect(user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"]) as conn:
        with conn.cursor() as cur:
            cur.execute(runtime_sql, {"asta_fetch_rows": fetch_limit})
            row = cur.fetchone()
            execution_ms = int((time.perf_counter() - started) * 1000)
            row_count = int(row[0]) if row and row[0] is not None else 0
            repeat_count = 1
            if execution_ms < 1000 and row_count <= fetch_limit:
                # Warm-cache comparison for short/small SQL: physical reads can dominate elapsed time.
                # Re-run the same marked SQL so V$SQL_PLAN_STATISTICS_ALL.LAST_* reflects the warmed execution.
                for _ in range(2):
                    started = time.perf_counter()
                    cur.execute(runtime_sql, {"asta_fetch_rows": fetch_limit})
                    row = cur.fetchone()
                    execution_ms = int((time.perf_counter() - started) * 1000)
                    row_count = int(row[0]) if row and row[0] is not None else 0
                    repeat_count += 1
            cur.execute(
                """
                SELECT sql_id, child_number, plan_hash_value, elapsed_time, cpu_time,
                       buffer_gets, disk_reads, rows_processed
                  FROM v$sql
                 WHERE sql_text LIKE :marker
                 ORDER BY last_active_time DESC, child_number DESC
                 FETCH FIRST 1 ROW ONLY
                """,
                {"marker": f"%ASTA_RUN_ID={run_marker}%"},
            )
            cursor_row = cur.fetchone()
            if not cursor_row:
                raise RuntimeError("Executed source cursor was not found in source V$SQL")
            sql_id, child_number, plan_hash_value, elapsed_time, cpu_time, buffer_gets, disk_reads, rows_processed = cursor_row
            cur.execute(
                """
                SELECT plan_table_output
                  FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(
                         sql_id          => :sql_id,
                         cursor_child_no => :child_number,
                         format          => 'ALLSTATS LAST +PREDICATE +PEEKED_BINDS +OUTLINE +NOTE'
                       ))
                """,
                {"sql_id": sql_id, "child_number": child_number},
            )
            plan_rows = cur.fetchall()
            cur.execute(
                """
                SELECT MAX(CASE WHEN id IN (0,1) THEN last_output_rows END) AS last_output_rows,
                       MAX(last_cr_buffer_gets) AS last_cr_buffer_gets,
                       MAX(last_disk_reads) AS last_disk_reads,
                       MAX(last_elapsed_time) AS last_elapsed_time_us
                  FROM v$sql_plan_statistics_all
                 WHERE sql_id = :sql_id
                   AND child_number = :child_number
                """,
                {"sql_id": sql_id, "child_number": child_number},
            )
            stats_row = cur.fetchone() or (None, None, None, None)
            last_output_rows, last_cr_buffer_gets, last_disk_reads, last_elapsed_time_us = stats_row

            advisor = {
                "status": "skipped",
                "message": "Source SQL Tuning Advisor was not requested.",
            }
            if run_advisor:
                try:
                    task_name = f"OADT2_STA_{run_marker[-12:]}"
                    try:
                        cur.execute("BEGIN DBMS_SQLTUNE.DROP_TUNING_TASK(:task_name); EXCEPTION WHEN OTHERS THEN NULL; END;", {"task_name": task_name})
                    except Exception:
                        pass
                    task_var = cur.var(str, 128)
                    cur.execute(
                        """
                        BEGIN
                          :task_name_out := DBMS_SQLTUNE.CREATE_TUNING_TASK(
                            sql_text    => :sql_text,
                            user_name   => :user_name,
                            scope       => DBMS_SQLTUNE.SCOPE_COMPREHENSIVE,
                            time_limit  => :time_limit,
                            task_name   => :task_name_in,
                            description => :description
                          );
                          DBMS_SQLTUNE.EXECUTE_TUNING_TASK(:task_name_in);
                        END;
                        """,
                        {
                            "sql_text": source_sql,
                            "user_name": cfg["user"].upper(),
                            "time_limit": sqltune_time_limit,
                            "task_name_in": task_name,
                            "task_name_out": task_var,
                            "description": f"OADT2 source-side SQL Tuning Advisor {run_marker}",
                        },
                    )
                    actual_task_name = task_var.getvalue() or task_name
                    cur.execute(
                        "SELECT DBMS_SQLTUNE.REPORT_TUNING_TASK(:task_name, 'TEXT', 'ALL', 'ALL') FROM dual",
                        {"task_name": actual_task_name},
                    )
                    report_row = cur.fetchone()
                    report = report_row[0].read() if report_row and hasattr(report_row[0], "read") else (report_row[0] if report_row else "")
                    advisor = {
                        "status": "completed",
                        "message": "Source DB SQL Tuning Advisor completed.",
                        "task_name": actual_task_name,
                        "time_limit": sqltune_time_limit,
                        "execution_location": "BASEDB_SOURCE_DIRECT",
                        "report": str(report or ""),
                    }
                except Exception as exc:
                    advisor = {
                        "status": "unavailable",
                        "message": str(exc).splitlines()[0],
                        "execution_location": "BASEDB_SOURCE_DIRECT",
                        "time_limit": sqltune_time_limit,
                    }

    plan_text = "\n".join(str(r[0] or "") for r in plan_rows)
    result = {
        "plan_text": plan_text,
        "sql_id": sql_id,
        "child_number": child_number,
        "plan_hash_value": plan_hash_value,
        "row_count": row_count,
        "execution_ms": int(last_elapsed_time_us / 1000) if last_elapsed_time_us is not None else execution_ms,
        "elapsed_time_us": last_elapsed_time_us if last_elapsed_time_us is not None else elapsed_time,
        "cpu_time_us": cpu_time,
        "buffer_gets": last_cr_buffer_gets if last_cr_buffer_gets is not None else buffer_gets,
        "disk_reads": last_disk_reads if last_disk_reads is not None else disk_reads,
        "rows_processed": last_output_rows if last_output_rows is not None else rows_processed,
        "vsql_cumulative_buffer_gets": buffer_gets,
        "vsql_cumulative_disk_reads": disk_reads,
        "vsql_cumulative_rows_processed": rows_processed,
        "metric_source": "V$SQL_PLAN_STATISTICS_ALL.LAST_*",
        "execution_repeat_count": repeat_count,
        "fetch_rows": fetch_limit,
        "run_marker": run_marker,
        "execution_location": "BASEDB_SOURCE_DIRECT",
        "xplan_has_remote": "REMOTE" in plan_text.upper(),
        "advisor": advisor,
    }
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
