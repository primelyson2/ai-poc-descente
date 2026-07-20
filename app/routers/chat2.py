"""메뉴 [AI Chat v2] — SELECT AI narrate 기반 자연어 답변.

질문 + (선택) '추출할 정보 Guide' 를 Chat설정의 User Prompt 템플릿에 치환해
DBMS_CLOUD_AI.GENERATE(action=>'narrate') 로 실행한다. Guide 가 비면 프롬프트의
'질문 답변을 위해 추출할 정보' 블록을 제거한다.

AI Chat(chat.py, RUN_TEAM) 과는 소스를 분리한다 — chat.py 를 참조하지 않는다.
질의/응답은 conversation 에 연결해 USER_CLOUD_AI_CONVERSATION_PROMPTS 에 기록(nl2sql 과 동일 패턴).
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.profiles import _GENERATE_SQL

router = APIRouter(prefix="/chat2", tags=["chat2"])

PH_MESSAGE = "##메시지##"
PH_INFO = "##조회할 정보##"
PH_BASEDATE = "##기준일##"
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")

# Guide 미입력 시 제거할 '질문 답변을 위해 추출할 정보' 블록(헤더 라인 ~ ##조회할 정보## 라인).
_INFO_BLOCK_RE = re.compile(
    r"[^\n]*질문 답변을 위해 추출할 정보.*?" + re.escape(PH_INFO) + r"[^\n]*\n?", re.S)
_INFO_LINE_RE = re.compile(r"[^\n]*" + re.escape(PH_INFO) + r"[^\n]*\n?")


def _build_prompt(user_prompt: str, message: str, extract_info: str) -> str:
    """User Prompt 템플릿 치환. extract_info 있으면 ##조회할 정보##→값, 없으면 블록 제거."""
    up = user_prompt or ""
    if (extract_info or "").strip():
        up = up.replace(PH_INFO, extract_info)
    else:
        up = _INFO_BLOCK_RE.sub("", up)   # 헤더~placeholder 블록 제거
        up = _INFO_LINE_RE.sub("", up)    # 잔여 placeholder 라인 폴백 제거
    return up.replace(PH_BASEDATE, datetime.now().strftime("%Y%m%d")).replace(PH_MESSAGE, message)


@router.post("/send")
async def chat2_send(payload: dict, database: str = Depends(current_db)) -> dict:
    """narrate 실행. body: {profile_name, user_prompt, message, extract_info, mode,
    retention_days, multi_turn, conversation_id}. 반환: {answer, conversation_id, elapsed_ms, error}."""
    profile_name = (payload.get("profile_name") or "").strip()
    user_prompt = payload.get("user_prompt") or ""
    message = payload.get("message") or ""
    extract_info = payload.get("extract_info") or ""
    mode = (payload.get("mode") or "dbms_cloud_ai").strip()
    multi_turn = bool(payload.get("multi_turn"))
    in_conv = (payload.get("conversation_id") or "").strip()
    try:
        retention_days = int(payload.get("retention_days"))
    except (TypeError, ValueError):
        retention_days = None
    if retention_days is not None and retention_days < 7:
        retention_days = 7

    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})
    if not message.strip():
        raise HTTPException(status_code=400, detail={"error": "message required"})
    if PH_MESSAGE not in user_prompt:
        raise HTTPException(status_code=400, detail={"error": f"User Prompt 에 {PH_MESSAGE} 자리표시자가 없습니다"})
    if mode == "select_ai" and not _IDENT_RE.match(profile_name):
        return {"answer": None, "conversation_id": None, "elapsed_ms": 0,
                "error": "profile_name 형식이 올바르지 않습니다 (select ai 모드)"}

    merged = _build_prompt(user_prompt, message, extract_info)

    # 한 커넥션에서 conversation 연결 후 narrate 실행 → 이력 기록. 대화설정은 best-effort.
    conversation_id = None
    t0 = time.perf_counter()
    try:
        pool = db.get_pool(database)
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                try:
                    if multi_turn and in_conv:
                        conversation_id = in_conv
                    else:
                        cidv = cur.var(str)
                        if retention_days is not None and retention_days != 7:
                            await cur.execute(
                                "BEGIN :cid := DBMS_CLOUD_AI.CREATE_CONVERSATION(attributes => :attrs); END;",
                                cid=cidv, attrs='{"retention_days":%d}' % retention_days)
                        else:
                            await cur.execute("BEGIN :cid := DBMS_CLOUD_AI.CREATE_CONVERSATION(); END;", cid=cidv)
                        conversation_id = cidv.getvalue()
                    await cur.execute(
                        "BEGIN DBMS_CLOUD_AI.SET_PROFILE(:pn); DBMS_CLOUD_AI.SET_CONVERSATION_ID(:cid); END;",
                        pn=profile_name, cid=conversation_id)
                except Exception:  # noqa: BLE001 — 이력 기록 불가 환경(생성은 계속)
                    conversation_id = None
                if mode == "select_ai":
                    if not conversation_id:  # 대화설정 실패 시 세션 프로파일 보장
                        await cur.execute("BEGIN DBMS_CLOUD_AI.SET_PROFILE(:pn); END;", pn=profile_name)
                    await cur.execute('select ai narrate "' + merged + '"')
                else:
                    await cur.execute(
                        "SELECT DBMS_CLOUD_AI.GENERATE(prompt=>:p, profile_name=>:pn, action=>'narrate') FROM dual",
                        p=merged, pn=profile_name)
                r = await cur.fetchone()
        answer = (r[0] if r else "") or ""
    except Exception as exc:  # noqa: BLE001
        return {"answer": None, "conversation_id": conversation_id,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000), "error": first_line(exc)}
    return {"answer": answer, "conversation_id": conversation_id,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000), "error": None}
