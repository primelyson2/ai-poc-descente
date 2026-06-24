"""AI Chat — Chat설정(변수 / Team / User Prompt) 기반으로 RUN_TEAM 을 호출.

화면 코드(사용자 제공 PL/SQL 블록)를 서버에서 조립해 실행한다 (블록 생성은
app.plsql.build_run_team_block 가 담당, agents.run_team 과 동일 빌더):

    DECLARE
      l_conv_id     VARCHAR2(256);
      l_answer      CLOB;
      l_user_prompt CLOB;
      @변수@                         -- Chat설정의 '변수'
    BEGIN
      l_conv_id := DBMS_CLOUD_AI.CREATE_CONVERSATION();  -- 또는 :in_conv 재사용
      l_user_prompt := '@User Prompt@';  -- ##메시지## 자리에 :msg 바인드
      l_answer := DBMS_CLOUD_AI_AGENT.RUN_TEAM(
        team_name => :team_name, user_prompt => l_user_prompt,
        params => '{"conversation_id":"' || l_conv_id || '"}'
      );
      :out_conv := l_conv_id; :out_answer := l_answer;
    END;

치환/바인드 규칙:
- @변수@        : Chat설정의 변수 선언을 DECLARE 절에 그대로 삽입.
- @TEAM@        : :team_name 바인드.
- ##메시지##    : User Prompt 안의 자리표시자를 `' || :msg || '` 로 바꿔 메시지만 바인드.
                 (User Prompt 의 작은따옴표는 의도된 PL/SQL 연결이므로 escape 하지 않는다.)
- multi turn ON : conversation_id 가 넘어오면 그 값을 재사용해 대화 컨텍스트 유지.
  multi turn OFF: 매 전송마다 CREATE_CONVERSATION 으로 새 conversation 생성.

응답에는 답변과 함께 단계별 timeline·thinking·raw_logs 를 동봉한다 (RUN_TEAM 직후
history 테이블을 조회 — Oracle 은 실행 중 스트리밍/콜백을 제공하지 않으므로 완료 후 조회가
유일한 방법). 화면은 이를 각 답변 아래에 인라인 표시한다.

보안 메모: variables/user_prompt 는 **신뢰된 테스터가 작성하는 raw PL/SQL** 로 취급한다
(임의 PL/SQL 삽입 가능). 런타임 사용자 입력(메시지)은 :msg 바인드로 격리된다. 위험 패턴
경고는 화면의 Chat설정 저장 단계에서 1차로 거른다.
"""
from __future__ import annotations

import logging
import time

import oracledb
from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import build_run_team_block, first_line, read_clob
from app.routers.agents import build_timeline_and_logs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

MESSAGE_PLACEHOLDER = "##메시지##"


def _user_prompt_expr(user_prompt: str) -> tuple[str, bool]:
    """User Prompt 템플릿을 user_prompt 인자용 PL/SQL 표현식으로 변환.

    ##메시지## 는 `' || :msg || '` 로 치환해 메시지만 바인드한다.
    반환: (PL/SQL 표현식, :msg 사용 여부)
    """
    use_msg = MESSAGE_PLACEHOLDER in user_prompt
    src = user_prompt.replace(MESSAGE_PLACEHOLDER, "' || :msg || '") if use_msg else user_prompt
    return "'" + src + "'", use_msg


@router.post("/send")
async def chat_send(payload: dict, database: str = Depends(current_db)) -> dict:
    team = (payload.get("team") or "").strip()
    variables = payload.get("variables") or ""
    user_prompt = payload.get("user_prompt") or ""
    message = payload.get("message") or ""
    multi_turn = bool(payload.get("multi_turn"))
    conv_in = (payload.get("conversation_id") or "").strip()

    if not team:
        raise HTTPException(status_code=400,
                            detail={"error": "Team 이 비어 있습니다 (Chat설정에서 Team 을 선택하세요)"})
    if not user_prompt.strip():
        raise HTTPException(status_code=400,
                            detail={"error": "User Prompt 가 비어 있습니다 (Chat설정을 확인하세요)"})

    reuse_conv = multi_turn and bool(conv_in)
    user_prompt_sql, use_msg = _user_prompt_expr(user_prompt)
    plsql = build_run_team_block(
        variables=variables, reuse_conv=reuse_conv, user_prompt_sql=user_prompt_sql,
    )

    pool = db.get_pool(database)
    t0 = time.perf_counter()
    conv_id = ""
    answer = ""
    try:
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                out_conv = cur.var(str, size=4000)
                out_answer = cur.var(oracledb.DB_TYPE_CLOB)
                binds = {"team_name": team, "out_conv": out_conv, "out_answer": out_answer}
                if use_msg:
                    binds["msg"] = message
                if reuse_conv:
                    binds["in_conv"] = conv_in
                await cur.execute(plsql, binds)
                conv_id = out_conv.getvalue() or ""
                answer = await read_clob(out_answer.getvalue())
            await conn.commit()
    except Exception as exc:
        logger.warning("chat RUN_TEAM failed: db=%s team=%s: %s", database, team, first_line(exc))
        raise HTTPException(status_code=400, detail={"error": first_line(exc), "team": team})

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # 단계별 timeline·thinking 동봉 — 실패해도 답변은 그대로 반환 (디버깅 보조 정보일 뿐).
    extras = {"timeline": [], "thinking": {"rows": [], "error": None}, "raw_logs": {}}
    try:
        extras = await build_timeline_and_logs(database, conv_id)
    except Exception as exc:
        logger.warning("chat timeline build failed: db=%s conv=%s: %s",
                       database, conv_id, first_line(exc))

    return {
        "conversation_id": conv_id,
        "answer": answer or "",
        "elapsed_ms": elapsed_ms,
        "timeline": extras.get("timeline", []),
        "thinking": extras.get("thinking", {"rows": [], "error": None}),
        "raw_logs": extras.get("raw_logs", {}),
    }
