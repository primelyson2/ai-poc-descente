"""AI분석 페르소나(T_ANALYSIS_PERSONA) CRUD — Select AI Test - Table list 의 AI분석 팝업용.

- /personas         : 페르소나 목록/추가 (분석 프롬프트 템플릿)
- /personas/{pid}   : 수정/삭제

페르소나는 접속 사용자 스키마의 T_ANALYSIS_PERSONA 에 저장한다(스키마 접두사 없음 — predefined 와 동일 규약).
GET 은 테이블 미생성(ORA-00942) 등에서도 화면이 뜨도록 빈 배열로 graceful 처리하고,
쓰기(POST/PUT/DELETE)는 오류를 숨기지 않고 first_line 으로 한 줄 노출한다(프로젝트 관례).

테이블 DDL 은 Prerequisites.md 참고(대상 ADB 에서 1회 수동 실행).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/personas", tags=["personas"])

_LIST_SQL = (
    "SELECT ID, PERSONA_NAME, DESCRIPTION, PROMPT_TMPL "
    "FROM T_ANALYSIS_PERSONA ORDER BY PERSONA_NAME"
)
_INSERT_SQL = (
    "INSERT INTO T_ANALYSIS_PERSONA (PERSONA_NAME, DESCRIPTION, PROMPT_TMPL) "
    "VALUES (:persona_name, :description, :prompt_tmpl)"
)
_UPDATE_SQL = (
    "UPDATE T_ANALYSIS_PERSONA SET PERSONA_NAME=:persona_name, DESCRIPTION=:description, "
    "PROMPT_TMPL=:prompt_tmpl, MOD_DTM=SYSTIMESTAMP WHERE ID=:id"
)
_DELETE_SQL = "DELETE FROM T_ANALYSIS_PERSONA WHERE ID=:id"


def _row(payload: dict) -> dict:
    """편집 폼 필드를 bind dict 로. 이름·템플릿은 필수, 설명은 선택."""
    name = (payload.get("persona_name") or "").strip()
    tmpl = payload.get("prompt_tmpl") or ""
    if not name:
        raise HTTPException(status_code=400, detail={"error": "persona_name 는 필수입니다"})
    if not str(tmpl).strip():
        raise HTTPException(status_code=400, detail={"error": "prompt_tmpl 는 필수입니다"})
    return {"persona_name": name, "description": payload.get("description") or "", "prompt_tmpl": tmpl}


@router.get("")
async def list_personas(database: str = Depends(current_db)) -> list[dict]:
    try:
        return await db.fetch_all(database, _LIST_SQL)
    except Exception as exc:
        # 테이블 미생성 등 — 화면은 뜨도록 빈 목록. (추가 시도 시 실제 오류가 노출됨)
        logger.warning("personas list failed (returning empty): db=%s: %s", database, first_line(exc))
        return []


@router.post("")
async def create_persona(payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _INSERT_SQL, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.put("/{pid}")
async def update_persona(pid: int, payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _UPDATE_SQL, id=pid, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.delete("/{pid}")
async def delete_persona(pid: int, database: str = Depends(current_db)) -> dict:
    try:
        await db.execute(database, _DELETE_SQL, id=pid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}
