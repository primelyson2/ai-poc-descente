"""메뉴 [Select AI Test - History2] — SELECT AI 대화 이력(영구) 읽기전용 조회.

  · GET /history2/prompts : USER_CLOUD_AI_CONVERSATION_PROMPTS 조회(질의·응답·시각 등)
  · GET /history2/facets  : 필터 드롭다운용 distinct profile_name / prompt_action

History(v$mapped_sql)는 shared pool(임시)이라 재시작·aging 시 소멸하지만, 이 화면은
conversation 으로 실행된 SELECT AI 의 질의/응답이 딕셔너리 뷰에 **영구 저장**된 것을 본다
(Guide_Select-AI-History.md 참고). USER_ 뷰라 접속 스키마 소유 대화만 보인다.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db

router = APIRouter(prefix="/history2", tags=["history2"])


def _parse_dt(s: str) -> datetime | None:
    """datetime-local(YYYY-MM-DDTHH:MM) 등 ISO 계열 문자열을 datetime 으로. 빈값이면 None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


@router.get("/prompts")
async def prompts(
    start: str = "",
    end: str = "",
    text: str = "",
    profile: str = "",
    action: str = "",
    database: str = Depends(current_db),
) -> list[dict]:
    """USER_CLOUD_AI_CONVERSATION_PROMPTS — SELECT AI 대화 질의/응답 이력.

    조회조건:
      · start/end : created 범위(시작~종료일시, 양끝 포함). ISO 문자열.
      · text      : prompt/prompt_response 부분일치(LIKE, 대소문자 무시).
      · profile   : profile_name 정확일치.
      · action    : prompt_action 정확일치(SHOWSQL/RUNSQL/CHAT/…).
    뷰가 없거나 23ai 미만이면 ORA 오류가 그대로 전파된다.
    """
    conds: list[str] = []
    binds: dict = {}

    # created 는 TIMESTAMP WITH TIME ZONE — thin mode 회피 위해 CAST(... AS TIMESTAMP).
    # 바인드명 start/end 는 예약어(START/END) → ORA-01745. sdt/edt 사용.
    s_dt = _parse_dt(start)
    if start.strip() and s_dt is None:
        raise HTTPException(status_code=400, detail={"error": f"시작일시 형식 오류: {start}"})
    if s_dt is not None:
        conds.append("CAST(created AS TIMESTAMP) >= :sdt")
        binds["sdt"] = s_dt

    e_dt = _parse_dt(end)
    if end.strip() and e_dt is None:
        raise HTTPException(status_code=400, detail={"error": f"종료일시 형식 오류: {end}"})
    if e_dt is not None:
        conds.append("CAST(created AS TIMESTAMP) <= :edt")
        binds["edt"] = e_dt

    text = (text or "").strip()
    if text:
        conds.append("(UPPER(prompt) LIKE UPPER(:pat) OR UPPER(prompt_response) LIKE UPPER(:pat))")
        binds["pat"] = f"%{text}%"

    profile = (profile or "").strip()
    if profile:
        conds.append("profile_name = :prof")
        binds["prof"] = profile

    action = (action or "").strip()
    if action:
        conds.append("prompt_action = :act")
        binds["act"] = action

    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (
        "SELECT conversation_id, conversation_title, profile_name, prompt_action, "
        "       prompt, prompt_response, CAST(created AS TIMESTAMP) AS created, "
        "       client_identifier, sid "
        "  FROM user_cloud_ai_conversation_prompts" + where +
        " ORDER BY created DESC"
    )
    return await db.fetch_all(database, sql, **binds)


@router.get("/facets")
async def facets(database: str = Depends(current_db)) -> dict:
    """필터 드롭다운용 — 뷰에 실제로 존재하는 distinct profile_name / prompt_action."""
    profs = await db.fetch_all(
        database,
        "SELECT DISTINCT profile_name FROM user_cloud_ai_conversation_prompts "
        "WHERE profile_name IS NOT NULL ORDER BY profile_name",
    )
    acts = await db.fetch_all(
        database,
        "SELECT DISTINCT prompt_action FROM user_cloud_ai_conversation_prompts "
        "WHERE prompt_action IS NOT NULL ORDER BY prompt_action",
    )
    return {
        "profiles": [r["profile_name"] for r in profs],
        "actions": [r["prompt_action"] for r in acts],
    }
