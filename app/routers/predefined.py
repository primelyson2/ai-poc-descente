"""메뉴 [Select AI Test - Predefined Query] — 실제 ADB 호출.

- /predefined           : T_PREDEFINED_QUERY 행 목록/추가/수정/삭제 (드롭다운 + 관리 팝업)
- /predefined/execute   : f_predefined_query(p_id, p_question, p_profile_name) 호출 후 결과(CLOB) 반환

객체명은 스키마를 붙이지 않는다 → 접속 사용자 스키마의 T_PREDEFINED_QUERY / f_predefined_query 를 사용.
두 객체는 DB 에 미리 생성돼 있어야 한다(설계: CJ ENM 산출물/…predefined query function.md).
없으면 ORA-00942/06550 등이 그대로 노출된다(프로젝트 관례 = 에러 숨기지 않음).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predefined", tags=["predefined"])

_LIST_SQL = (
    "SELECT ID, DESCRIPTION, NL_QUESTION, SQL_TEXT, ENTITY_PROMPT, FEW_SHOT "
    "FROM T_PREDEFINED_QUERY ORDER BY ID"
)
_INSERT_SQL = (
    "INSERT INTO T_PREDEFINED_QUERY (DESCRIPTION, NL_QUESTION, SQL_TEXT, ENTITY_PROMPT, FEW_SHOT) "
    "VALUES (:description, :nl_question, :sql_text, :entity_prompt, :few_shot)"
)
_UPDATE_SQL = (
    "UPDATE T_PREDEFINED_QUERY SET DESCRIPTION=:description, NL_QUESTION=:nl_question, "
    "SQL_TEXT=:sql_text, ENTITY_PROMPT=:entity_prompt, FEW_SHOT=:few_shot, MOD_DTM=SYSTIMESTAMP "
    "WHERE ID=:id"
)
_DELETE_SQL = "DELETE FROM T_PREDEFINED_QUERY WHERE ID=:id"
_EXEC_SQL = "SELECT f_predefined_query(:id, :q, :pn) AS result FROM dual"

_FIELDS = ("description", "nl_question", "sql_text", "entity_prompt", "few_shot")


def _row(payload: dict) -> dict:
    """편집 폼 5개 필드를 bind dict 로. 모두 NOT NULL 이라 누락 시 400."""
    out = {}
    for f in _FIELDS:
        v = payload.get(f)
        if v is None or str(v).strip() == "":
            raise HTTPException(status_code=400, detail={"error": f"{f} 는 필수입니다"})
        out[f] = v
    return out


@router.get("")
async def list_predefined(database: str = Depends(current_db)) -> list[dict]:
    try:
        return await db.fetch_all(database, _LIST_SQL)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})


@router.post("")
async def create_predefined(payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _INSERT_SQL, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.put("/{pid}")
async def update_predefined(pid: int, payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _UPDATE_SQL, id=pid, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.delete("/{pid}")
async def delete_predefined(pid: int, database: str = Depends(current_db)) -> dict:
    try:
        await db.execute(database, _DELETE_SQL, id=pid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.post("/execute")
async def execute_predefined(payload: dict, database: str = Depends(current_db)) -> dict:
    pid = payload.get("id")
    question = (payload.get("question") or "").strip()
    profile = (payload.get("profile_name") or "").strip()
    if pid is None or str(pid).strip() == "":
        raise HTTPException(status_code=400, detail={"error": "Predefined Query 를 선택하세요"})
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    if not profile:
        raise HTTPException(status_code=400, detail={"error": "AI Profile 을 선택하세요"})
    try:
        row = await db.fetch_one(database, _EXEC_SQL, id=int(pid), q=question, pn=profile)
    except Exception as exc:
        msg = first_line(exc)
        logger.warning("predefined execute failed: db=%s id=%s: %s", database, pid, msg)
        raise HTTPException(status_code=400, detail={"error": msg})
    return {"result": (row or {}).get("result") or ""}
