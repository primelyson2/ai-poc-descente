"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

from __future__ import annotations

from pathlib import Path
import json
import re
import sys

import oracledb

try:
    oracledb.init_oracle_client(lib_dir="/home/ubuntu/oracle/instantclient_21_10")
except Exception:
    # Already initialized or unavailable; connection will surface actionable errors.
    pass

ROOT = Path(__file__).resolve().parents[1]


def source_config():
    """Source DB 배포에 필요한 접속 환경 설정을 읽는다."""
    raw = json.loads((ROOT / ".secrets/source_db.json").read_text())
    cfg = raw["DB0903_LINK"]
    return cfg["user"], cfg["password"], cfg["dsn"]


def split_sqlplus_script(text: str) -> list[str]:
    """SQL*Plus 스타일 스크립트를 실행 가능한 개별 문장으로 분리한다."""
    statements = []
    buf = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        upper = stripped.upper()
        if stripped == "/":
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            continue
        if upper.startswith(("SHOW ", "PROMPT ", "WHENEVER ", "SPOOL ", "SET ")):
            continue
        if stripped.startswith("--"):
            continue
        buf.append(line)
    stmt = "\n".join(buf).strip()
    if stmt:
        statements.append(stmt)
    return statements


def exec_stmt(cur, stmt: str):
    """한 개의 SQL/PLSQL 문장을 실행하고 오류 정보를 표준화한다."""
    s = stmt.strip()
    if s.endswith(";") and not re.match(r"(?is)^\s*(create\s+or\s+replace\s+package|declare|begin)", s):
        s = s[:-1]
    cur.execute(s)


def clob_to_str(v):
    """Oracle CLOB 값을 Python 문자열로 안전하게 변환한다."""
    return v.read() if hasattr(v, "read") else v


def main():
    """명령행 인자를 읽어 ASTA 도구의 전체 작업 흐름을 실행한다."""
    user, password, dsn = source_config()
    conn = oracledb.connect(user=user, password=password, dsn=dsn)
    cur = conn.cursor()
    log = []
    try:
        cur.execute("select user from dual")
        log.append(f"connected_user={cur.fetchone()[0]}")
        cur.execute("select count(*) from user_tables where table_name='ASTA_SOURCE_RESULTS'")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                CREATE TABLE asta_source_results(
                  run_id VARCHAR2(128) PRIMARY KEY,
                  response_json CLOB CHECK (response_json IS JSON),
                  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
                )
            """)
            log.append("created ASTA_SOURCE_RESULTS")
        else:
            log.append("skip ASTA_SOURCE_RESULTS existing")
        cur.execute("select count(*) from user_tables where table_name='ASTA_SOURCE_ADVISOR_RESULTS'")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                CREATE TABLE asta_source_advisor_results(
                  run_id VARCHAR2(128) PRIMARY KEY,
                  status VARCHAR2(30),
                  report CLOB,
                  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
                )
            """)
            log.append("created ASTA_SOURCE_ADVISOR_RESULTS")
        else:
            log.append("skip ASTA_SOURCE_ADVISOR_RESULTS existing")
        text = (ROOT / "db/source/asta_source_pkg.sql").read_text()
        for stmt in split_sqlplus_script(text):
            exec_stmt(cur, stmt)
        log.append("compiled db/source/asta_source_pkg.sql")
        cur.execute("select object_name, object_type, status from user_objects where object_name='ASTA_SOURCE_PKG' order by object_type")
        objects = cur.fetchall()
        cur.execute("select name,type,line,position,text from user_errors where name='ASTA_SOURCE_PKG' order by sequence")
        errors = cur.fetchall()
        smoke = None
        if not errors:
            cur.execute("""
                select asta_source_pkg.run_evidence(
                  p_sql => 'select * from dual',
                  p_run_id => 'SMOKE_SOURCE_DIRECT_001',
                  p_fetch_rows => 10,
                  p_repeat_policy => 'ONCE',
                  p_run_advisor => 'N',
                  p_sqltune_time_sec => 60
                ) from dual
            """)
            smoke = clob_to_str(cur.fetchone()[0])
        print(json.dumps({"log": log, "objects": objects, "errors": errors, "smoke": smoke}, ensure_ascii=False, indent=2, default=str))
        return 1 if errors else 0
    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    sys.exit(main())
