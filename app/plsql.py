"""RUN_TEAM PL/SQL 블록 빌더 + 공용 헬퍼.

chat.py 와 agents.py 가 공유한다 (중복 제거). 모두 저수준이라 DB 쿼리는 하지 않는다.
"""
from __future__ import annotations


def first_line(exc: Exception) -> str:
    """예외 메시지의 첫 줄만 (ORA-XXXX 한 줄 노출용)."""
    s = str(exc).strip()
    return s.splitlines()[0] if s else "execution failed"


async def read_clob(lob) -> str:
    """OUT 바인드 CLOB 값을 문자열로. thin/thick·async 모두 대응."""
    if lob is None:
        return ""
    if hasattr(lob, "read"):
        r = lob.read()
        if hasattr(r, "__await__"):
            return await r
        return r
    return str(lob)


def build_run_team_block(*, variables: str = "", reuse_conv: bool = False,
                         user_prompt_sql: str = ":user_prompt") -> str:
    """DBMS_CLOUD_AI_AGENT.RUN_TEAM 호출 익명 PL/SQL 블록을 생성한다.

    바인드:
      :team_name (IN), :out_conv (OUT VARCHAR2), :out_answer (OUT CLOB),
      reuse_conv=True 면 :in_conv (IN),
      user_prompt_sql 표현식이 참조하는 :user_prompt / :msg (IN).

    인자:
      variables       : DECLARE 절에 그대로 삽입할 추가 선언 (신뢰된 입력 — raw PL/SQL).
      reuse_conv       : True → :in_conv 재사용, False → CREATE_CONVERSATION() 신규.
      user_prompt_sql  : user_prompt 인자로 대입할 PL/SQL 표현식.
          agents = ':user_prompt'                  (프롬프트 전체를 바인드)
          chat   = "'<앞부분>' || :msg || '<뒷부분>'" (메시지만 바인드, 템플릿은 소스)

    User Prompt 는 인자에 직접 인라인하지 않고 지역변수 l_user_prompt 로 조립해
    넘긴다 (가독성 + 메시지 바인드 분리).
    """
    decls = (variables or "").strip()
    decl_line = ("\n  " + decls) if decls else ""
    # multi turn ON + conversation_id 전달 → 기존 id 재사용, 아니면 새로 생성
    conv_expr = ":in_conv" if reuse_conv else "DBMS_CLOUD_AI.CREATE_CONVERSATION()"
    return f"""
DECLARE
  l_conv_id     VARCHAR2(256);
  l_answer      CLOB;
  l_user_prompt CLOB;{decl_line}
BEGIN
  l_conv_id := {conv_expr};
  l_user_prompt := {user_prompt_sql};
  l_answer := DBMS_CLOUD_AI_AGENT.RUN_TEAM(
    team_name   => :team_name,
    user_prompt => l_user_prompt,
    params      => '{{"conversation_id":"' || l_conv_id || '"}}'
  );
  :out_conv := l_conv_id;
  :out_answer := l_answer;
END;
"""
