"""메뉴 [Select AI Security - VPD] — 행 수준 보안(VPD) 설정·조회·테스트.

  · GET  /vpd/policies        : ALL_POLICIES 조회(등록된 VPD 정책 목록)
  · POST /vpd/run-script      : 화면에서 편집한 1·2·3단계 스크립트를 그대로 실행(문장 단위)
  · POST /vpd/policy/enable   : DBMS_RLS.ENABLE_POLICY (사용중지/재개)
  · POST /vpd/policy/drop     : DBMS_RLS.DROP_POLICY (삭제)
  · POST /vpd/test            : 컨텍스트 값 세팅 → select ai showsql 생성 → 그 SQL 실행(VPD 적용 확인)

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


@router.post("/test")
async def vpd_test(payload: dict, database: str = Depends(current_db)) -> dict:
    """같은 세션에서: 컨텍스트 값 세팅 → GENERATE(showsql) → 생성 SQL 실행(VPD 적용).
    body: { schema, name, value, question, profile }.
    context_name(name) 로 패키지 PKG_OAC_<name>.SET_OBJECT 를 호출한다."""
    schema = _ident((payload.get("schema") or "").strip(), "schema")
    name = _ident((payload.get("name") or "").strip(), "name")
    profile = _ident((payload.get("profile") or "").strip(), "profile")
    value = payload.get("value") or ""
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})

    def result(**kw):
        base = {"sql": None, "columns": [], "rows": [], "error": None, "stage": None}
        base.update(kw)
        return base

    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        # 1) 컨텍스트 값 세팅 (같은 세션이라야 VPD 가 이 값을 본다)
        try:
            with conn.cursor() as cur:
                await cur.execute(
                    f"BEGIN {schema}.PKG_OAC_{name}.SET_OBJECT(:v); END;", {"v": value})
        except Exception as exc:  # noqa: BLE001
            return result(error=first_line(exc), stage="set_context")
        # 2) showsql 로 SQL 생성
        try:
            with conn.cursor() as cur:
                await cur.execute(_GENERATE_SQL, {"p": question, "pn": profile, "a": "showsql"})
                row = await cur.fetchone()
            sql = _clean_sql((row[0] if row else "") or "")
        except Exception as exc:  # noqa: BLE001
            return result(error=first_line(exc), stage="generate")
        if not sql:
            return result(error="모델이 SQL 을 생성하지 못했습니다(빈 응답)", stage="empty")
        if not _is_read_only(sql):
            return result(sql=sql, error="생성 문장이 조회(SELECT/WITH)가 아니라 실행을 건너뜁니다", stage="validate")
        # 3) 생성 SQL 실행 — 같은 세션이므로 VPD 술어가 자동 적용됨
        try:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchmany(ROW_LIMIT)
            rows = [[_normalize_cell(v) for v in r] for r in fetched]
        except Exception as exc:  # noqa: BLE001
            return result(sql=sql, error=first_line(exc), stage="execute")
    return result(sql=sql, columns=columns, rows=rows,
                  truncated=len(rows) == ROW_LIMIT)
