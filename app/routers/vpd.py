"""메뉴 [Select AI Security - VPD] — 행 수준 보안(VPD) 설정·조회·테스트.

  · GET  /vpd/policies        : ALL_POLICIES 조회(등록된 VPD 정책 목록)
  · POST /vpd/run-script      : 화면에서 편집한 1·2·3단계 스크립트를 그대로 실행(문장 단위)
  · POST /vpd/policy/enable   : DBMS_RLS.ENABLE_POLICY (사용중지/재개)
  · POST /vpd/policy/drop     : DBMS_RLS.DROP_POLICY (삭제)
  · GET  /vpd/contexts        : DBA_CONTEXT 조회(정의된 Application Context, SCHEMA 필터)
  · POST /vpd/set-context     : 세터 호출 블록 실행 → 같은 세션 SESSION_CONTEXT 조회(설정 확인)
  · POST /vpd/showsql         : select ai showsql 로 SQL 만 생성(실행 안 함)
  · POST /vpd/exec-sql        : set_block 으로 컨텍스트 세팅 후 같은 세션에서 SQL 실행(VPD 적용)

식별자(스키마/객체/정책/함수/컨텍스트명)는 bind 불가 → 화이트리스트 검증 후 보간.
값·프롬프트 등 자유 문자열은 bind. 오류는 first_line 으로 한 줄 노출(프로젝트 관례).
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.nl2sql import ROW_LIMIT, _clean_sql, _is_read_only
from app.routers.profiles import _GENERATE_SQL, _normalize_cell

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vpd", tags=["vpd"])

_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


def _ident(name: str, label: str) -> str:
    if not name:
        raise HTTPException(status_code=400, detail={"error": f"{label} required"})
    if not _IDENT_RE.match(name):
        raise HTTPException(status_code=400, detail={"error": f"invalid {label}: {name}"})
    return name


# ── 스크립트 문장 분리(SQL*Plus 관례: '/' 는 PL/SQL 종결, ';' 는 단문 종결) ──
def _is_block(text: str) -> bool:
    # 선행 주석(--)·빈 줄을 걷어낸 뒤 첫 키워드로 PL/SQL 블록 여부 판단
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    head = re.sub(r"\s+", " ", " ".join(lines)).strip().upper()
    if head.startswith("DECLARE") or head.startswith("BEGIN"):
        return True
    return re.search(r"\bCREATE\b.*\b(PACKAGE|FUNCTION|PROCEDURE|TRIGGER|TYPE)\b", head) is not None


def _split_statements(script: str) -> list[str]:
    """편집 스크립트를 실행 가능한 문장 리스트로 분리.
    - 한 줄이 '/' 뿐이면 지금까지의 버퍼(PL/SQL 블록)를 하나의 문장으로 종결.
    - PL/SQL 블록이 아닌 단문은 ';' 에서 종결(후행 ';' 제거)."""
    stmts: list[str] = []
    buf: list[str] = []
    for raw in (script or "").splitlines():
        if raw.strip() == "/":
            s = "\n".join(buf).strip()
            if s:
                stmts.append(s)  # PL/SQL 블록/DDL — 'END;' 포함, '/' 만 제외
            buf = []
            continue
        buf.append(raw)
        if raw.rstrip().endswith(";"):
            cur = "\n".join(buf).strip()
            if cur and not _is_block(cur):
                stmts.append(cur[:-1].rstrip())  # 단문: 후행 ';' 제거
                buf = []
    tail = "\n".join(buf).strip()
    if tail:
        stmts.append(tail[:-1].rstrip() if (tail.endswith(";") and not _is_block(tail)) else tail)
    # 주석/공백만 있는 조각 제거
    out = []
    for s in stmts:
        body = "\n".join(ln for ln in s.splitlines() if not ln.strip().startswith("--")).strip()
        if body:
            out.append(s)
    return out


@router.get("/policies")
async def list_policies(database: str = Depends(current_db)) -> list[dict]:
    """등록된 VPD 정책(ALL_POLICIES). 권한/뷰 없으면 오류를 그대로 전파."""
    return await db.fetch_all(
        database,
        "SELECT object_owner, object_name, policy_name, pf_owner, package, function, "
        "       sel, ins, upd, del, idx, enable "
        "  FROM all_policies "
        " ORDER BY object_owner, object_name, policy_name",
    )


@router.get("/contexts")
async def list_contexts(schema: str = "", database: str = Depends(current_db)) -> list[dict]:
    """정의된 Application Context 네임스페이스(DBA_CONTEXT).
    namespace / schema / package(= CREATE CONTEXT … USING 유닛) 를 반환한다.
    schema 파라미터가 있으면 SCHEMA 부분일치(대소문자 무시)로 필터한다(값은 bind).
    (DBA_CONTEXT 는 세션 활성 여부와 무관하게 '정의된' 컨텍스트 전체를 보여준다 —
     조회에는 접속 계정에 DBA_CONTEXT SELECT 권한이 필요하다.)"""
    schema = (schema or "").strip()
    if schema:
        return await db.fetch_all(
            database,
            "SELECT namespace, schema, package FROM dba_context "
            "WHERE UPPER(schema) LIKE '%' || UPPER(:s) || '%' ORDER BY namespace",
            s=schema,
        )
    return await db.fetch_all(
        database,
        "SELECT namespace, schema, package FROM dba_context ORDER BY namespace",
    )


@router.post("/run-script")
async def run_script(payload: dict, database: str = Depends(current_db)) -> dict:
    """편집 스크립트를 문장 단위로 순차 실행. 오류가 나도 계속 진행하고 문장별 결과를 반환."""
    script = payload.get("script") or ""
    stmts = _split_statements(script)
    if not stmts:
        raise HTTPException(status_code=400, detail={"error": "실행할 문장이 없습니다"})

    results: list[dict] = []
    ok = 0
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        for i, stmt in enumerate(stmts):
            snippet = re.sub(r"\s+", " ", stmt).strip()[:80]
            try:
                with conn.cursor() as cur:
                    await cur.execute(stmt)
                results.append({"i": i + 1, "ok": True, "error": None, "snippet": snippet})
                ok += 1
            except Exception as exc:  # noqa: BLE001 — 문장별 오류 노출
                msg = first_line(exc)
                logger.warning("vpd run-script stmt %d failed: db=%s: %s", i + 1, database, msg)
                results.append({"i": i + 1, "ok": False, "error": msg, "snippet": snippet})
        try:
            await conn.commit()
        except Exception:  # DDL 은 auto-commit — 실패해도 무시
            pass
    return {"total": len(stmts), "ok_count": ok, "fail_count": len(stmts) - ok, "results": results}


@router.post("/policy/enable")
async def policy_enable(payload: dict, database: str = Depends(current_db)) -> dict:
    o = _ident((payload.get("object_schema") or "").strip(), "object_schema")
    t = _ident((payload.get("object_name") or "").strip(), "object_name")
    p = _ident((payload.get("policy_name") or "").strip(), "policy_name")
    enable = 1 if payload.get("enable") else 0
    try:
        await db.execute(
            database,
            f"BEGIN DBMS_RLS.ENABLE_POLICY(object_schema => '{o}', object_name => '{t}', "
            f"policy_name => '{p}', enable => {'TRUE' if enable else 'FALSE'}); END;",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True, "enable": bool(enable)}


@router.post("/policy/drop")
async def policy_drop(payload: dict, database: str = Depends(current_db)) -> dict:
    o = _ident((payload.get("object_schema") or "").strip(), "object_schema")
    t = _ident((payload.get("object_name") or "").strip(), "object_name")
    p = _ident((payload.get("policy_name") or "").strip(), "policy_name")
    try:
        await db.execute(
            database,
            f"BEGIN DBMS_RLS.DROP_POLICY(object_schema => '{o}', object_name => '{t}', "
            f"policy_name => '{p}'); END;",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


def _strip_slash(block: str) -> str:
    """SQL*Plus 종결자 '/' 를 제거해 anonymous block 을 execute 가능하게 한다."""
    b = (block or "").strip()
    if b.endswith("/"):
        b = b[: b.rfind("/")].rstrip()
    return b


@router.post("/set-context")
async def set_context(payload: dict, database: str = Depends(current_db)) -> dict:
    """편집한 세터 호출 블록을 실행한 뒤, 같은 세션의 SESSION_CONTEXT 를 조회해 반환.
    body: { block }.  VPD 컨텍스트 세터가 정상 동작하는지 확인용."""
    block = _strip_slash(payload.get("block") or "")
    if not block:
        raise HTTPException(status_code=400, detail={"error": "실행할 코드가 없습니다"})
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        try:
            with conn.cursor() as cur:
                await cur.execute(block)
        except Exception as exc:  # noqa: BLE001
            return {"error": first_line(exc), "session_context": []}
        try:
            with conn.cursor() as cur:
                await cur.execute(
                    "SELECT namespace, attribute, value FROM session_context "
                    "ORDER BY namespace, attribute")
                cols = [d[0].lower() for d in (cur.description or [])]
                rows = await cur.fetchall()
            data = [dict(zip(cols, r)) for r in rows]
        except Exception as exc:  # noqa: BLE001
            return {"error": first_line(exc), "session_context": []}
    return {"error": None, "session_context": data}


@router.post("/showsql")
async def showsql(payload: dict, database: str = Depends(current_db)) -> dict:
    """select ai showsql 로 SQL 만 생성(실행하지 않음). body: { profile, question }."""
    profile = _ident((payload.get("profile") or "").strip(), "profile")
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        try:
            with conn.cursor() as cur:
                await cur.execute(_GENERATE_SQL, {"p": question, "pn": profile, "a": "showsql"})
                row = await cur.fetchone()
            sql = _clean_sql((row[0] if row else "") or "")
        except Exception as exc:  # noqa: BLE001
            return {"sql": None, "error": first_line(exc)}
    if not sql:
        return {"sql": None, "error": "모델이 SQL 을 생성하지 못했습니다(빈 응답)"}
    return {"sql": sql, "error": None}


@router.post("/exec-sql")
async def exec_sql(payload: dict, database: str = Depends(current_db)) -> dict:
    """set_block(있으면)으로 컨텍스트를 세팅한 뒤 같은 세션에서 sql 을 실행(VPD 적용).
    body: { sql, set_block? }.  VPD 는 세션 스코프라 세팅과 실행이 같은 커넥션이어야 한다."""
    sql = _clean_sql((payload.get("sql") or "").strip())
    set_block = _strip_slash(payload.get("set_block") or "")
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "실행할 SQL 이 없습니다"})
    if not _is_read_only(sql):
        return {"columns": [], "rows": [], "truncated": False,
                "error": "조회(SELECT/WITH) 문장만 실행합니다"}
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        if set_block:
            try:
                with conn.cursor() as cur:
                    await cur.execute(set_block)
            except Exception as exc:  # noqa: BLE001
                return {"columns": [], "rows": [], "truncated": False,
                        "error": f"컨텍스트 설정 실패: {first_line(exc)}"}
        try:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchmany(ROW_LIMIT)
            rows = [[_normalize_cell(v) for v in r] for r in fetched]
        except Exception as exc:  # noqa: BLE001
            return {"columns": [], "rows": [], "truncated": False, "error": first_line(exc)}
    return {"columns": columns, "rows": rows, "truncated": len(rows) == ROW_LIMIT, "error": None}
