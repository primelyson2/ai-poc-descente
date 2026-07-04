"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

from __future__ import annotations

from pathlib import Path
import json
import re
import sys

import oracledb
import yaml

ROOT = Path(__file__).resolve().parents[1]

DEPLOY_PACKAGE_ORDER = [
    "db/adb/asta_sql_guard_pkg.sql",
    "db/adb/asta_source_bridge_pkg.sql",
    "db/adb/asta_vector_pkg.sql",
    "db/adb/asta_llm_pkg.sql",
    "db/adb/asta_report_pkg.sql",
    "db/adb/asta_pkg.sql",
]


def connect():
    """환경변수와 wallet 설정을 사용해 Oracle DB 연결을 연다."""
    conf = yaml.safe_load((ROOT / "config.yaml").read_text())
    db = conf["databases"][0]
    wallet = str((ROOT / db["wallet_location"]).resolve())
    return oracledb.connect(
        user=db["user"],
        password=db["password"],
        dsn=db["dsn"],
        config_dir=wallet,
        wallet_location=wallet,
        wallet_password=db.get("wallet_password"),
    )


def split_sqlplus_script(text: str) -> list[str]:
    """SQL*Plus 스타일 스크립트를 실행 가능한 개별 문장으로 분리한다."""
    statements: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped:
            buf.append(line)
            continue
        if stripped == "/":
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            continue
        if upper.startswith(("SHOW ", "PROMPT ", "WHENEVER ", "SPOOL ")):
            continue
        if stripped.startswith("--"):
            buf.append(line)
            continue
        buf.append(line)
    stmt = "\n".join(buf).strip()
    if stmt:
        # strip a final SQL semicolon for plain SQL but not PL/SQL package bodies handled by slash
        statements.append(stmt)
    return statements


def exec_stmt(cur, stmt: str):
    """한 개의 SQL/PLSQL 문장을 실행하고 오류 정보를 표준화한다."""
    s = "\n".join(line for line in stmt.strip().splitlines() if not line.strip().startswith("--")).strip()
    if s.endswith(";") and not re.match(r"(?is)^\s*(create\s+or\s+replace\s+package|declare|begin)", s):
        s = s[:-1]
    cur.execute(s)


def object_exists(cur, table: str, name: str) -> bool:
    """배포 대상 객체가 데이터베이스에 존재하는지 확인한다."""
    cur.execute(f"select count(*) from {table} where {('table_name' if table == 'user_tables' else 'index_name')} = :n", n=name.upper())
    return cur.fetchone()[0] > 0


def run_script(cur, rel: str):
    """지정된 ASTA 배포 SQL 파일을 순서대로 실행한다."""
    text = (ROOT / rel).read_text()
    path = ROOT / rel
    # Package/PLSQL scripts use SQL*Plus slash separators. Plain DDL scripts use semicolons.
    if "CREATE OR REPLACE PACKAGE" not in text.upper() and "DECLARE" not in text.upper() and "BEGIN" not in text.upper():
        text_no_comments = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
        for stmt in [s.strip() for s in text_no_comments.split(";") if s.strip()]:
            # Deploy automation only executes structural DDL from these files; skip comments/metadata/examples.
            if not stmt.upper().startswith(("CREATE ", "ALTER ")):
                continue
            try:
                exec_stmt(cur, stmt)
            except Exception as e:
                raise RuntimeError(f"failed in {rel}: {stmt[:300]!r}") from e
        return
    for stmt in split_sqlplus_script(text):
        try:
            exec_stmt(cur, stmt)
        except Exception as e:
            raise RuntimeError(f"failed in {rel}: {stmt[:300]!r}") from e


def main():
    """명령행 인자를 읽어 ASTA 도구의 전체 작업 흐름을 실행한다."""
    conn = connect()
    cur = conn.cursor()
    log: list[str] = []
    try:
        cur.execute("select user from dual")
        user = cur.fetchone()[0]
        log.append(f"connected_user={user}")

        # Repository DDL: raw scripts are safe on this clean target, but guard anyway.
        if not object_exists(cur, "user_tables", "ASTA_RUNS"):
            run_script(cur, "db/asta/001_asta_repository.sql")
            log.append("installed db/asta/001_asta_repository.sql")
        else:
            log.append("skip ASTA_RUNS/ASTA_RUN_PROGRESS existing")

        if not object_exists(cur, "user_tables", "ASTA_SOURCE_CONNECTIONS"):
            run_script(cur, "db/asta/002_asta_source_connections.sql")
            log.append("installed db/asta/002_asta_source_connections.sql")
        else:
            log.append("skip ASTA_SOURCE_CONNECTIONS existing")

        # ASTA_RUNS created by 001 already includes SOURCE_DB_ID; skip additive migration here.
        log.append("skip db/asta/003_asta_runs_source_db_id.sql; column included in fresh DDL")

        if not object_exists(cur, "user_tables", "ASTA_TUNING_CASES"):
            run_script(cur, "db/asta/004_asta_vector_tables.sql")
            log.append("installed db/asta/004_asta_vector_tables.sql")
        else:
            log.append("skip vector tables existing")

        run_script(cur, "db/asta/005_asta_async_run_columns.sql")
        log.append("applied db/asta/005_asta_async_run_columns.sql")

        run_script(cur, "db/asta/006_asta_llm_call_log.sql")
        log.append("applied db/asta/006_asta_llm_call_log.sql")

        for rel in DEPLOY_PACKAGE_ORDER:
            run_script(cur, rel)
            log.append(f"compiled {rel}")

        cur.execute(
            """
            MERGE INTO asta_source_connections t
            USING (
              SELECT 'DB0903_TESTDB' source_db_id,
                     'DB0903_LINK' db_link_name,
                     'DEVDO' source_schema,
                     'ASTA source link via DB0903_LINK' description
              FROM dual
            ) s
            ON (t.source_db_id = s.source_db_id)
            WHEN NOT MATCHED THEN INSERT(source_db_id, db_link_name, source_schema, description, enabled)
              VALUES(s.source_db_id, s.db_link_name, s.source_schema, s.description, 'Y')
            """
        )
        log.append("preserved existing ASTA_SOURCE_CONNECTIONS mapping; inserted DB0903_LINK/DEVDO only if absent")
        conn.commit()

        # ORDS module install. This may fail if ORDS is not enabled/granted.
        try:
            run_script(cur, "db/ords/asta_ords_module.sql")
            conn.commit()
            log.append("installed ORDS module asta.v1")
        except Exception as e:
            conn.rollback()
            log.append(f"ORDS install failed: {type(e).__name__}: {e}")

        # Status summary.
        cur.execute(
            """
            select object_name, object_type, status
            from user_objects
            where object_name like 'ASTA%'
            order by object_name, object_type
            """
        )
        objects = cur.fetchall()
        cur.execute(
            """
            select name, type, line, position, text
            from user_errors
            where name like 'ASTA%'
            order by name, type, sequence
            """
        )
        errors = cur.fetchall()
        cur.execute("select source_db_id, db_link_name, source_schema, enabled from asta_source_connections order by source_db_id")
        links = cur.fetchall()
        print(json.dumps({"log": log, "objects": objects, "errors": errors, "source_connections": links}, ensure_ascii=False, indent=2, default=str))
        return 1 if errors else 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
