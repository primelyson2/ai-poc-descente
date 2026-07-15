"""메뉴 [Select AI Test - History] — SELECT AI 실행 내역(v$mapped_sql) 읽기전용 조회.

  · GET /history/mapped-sql : v$mapped_sql 에서 'select ai …' 실행 내역을 조회

AI Profile Test 의 [Feedback 추가 - Positive] 팝업과 같은 소스(v$mapped_sql)를 보지만,
목적(내역 상시 조회)·수명주기가 달라 전용 라우터로 분리한다. 표시 컬럼 확장 시 이 파일의
SELECT 만 수정한다(피드백 팝업 endpoint 와 결합하지 않는다).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.profiles import _GENERATE_SQL, _parse_verdict

router = APIRouter(prefix="/history", tags=["history"])


def _parse_dt(s: str) -> datetime | None:
    """datetime-local(YYYY-MM-DDTHH:MM) 등 ISO 계열 문자열을 datetime 으로. 빈값이면 None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)  # 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM[:SS]' 처리
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


@router.get("/mapped-sql")
async def mapped_sql(
    start: str = "",
    end: str = "",
    text: str = "",
    database: str = Depends(current_db),
) -> list[dict]:
    """v$mapped_sql — SELECT AI(NL2SQL) 실행 내역.

    조회조건:
      · start/end : translation_timestamp 범위(시작~종료일시, 양끝 포함). ISO 문자열.
      · text      : sql_fulltext 부분일치(LIKE, 대소문자 무시).
    조회 권한(GRANT READ ON SYS.V_$MAPPED_SQL)이 없으면 ORA 오류가 그대로 전파된다.
    표시 컬럼을 늘리려면 아래 SELECT 만 수정한다(예: sql_text, parsing_schema_name, 실행통계).
    """
    # SQL_FULLTEXT 가 'select ai' 로 '시작'하는 행만 노출(select ai 단축구문). GENERATE 호출은 제외.
    # 성능: 시작 키워드라 SQL_TEXT(VARCHAR2(1000)) 로 판정해도 SQL_FULLTEXT 시작과 동일하다
    #       (CLOB(SQL_FULLTEXT) 에 정규식을 걸면 전 행 materialize 되어 느림).
    conds = ["REGEXP_LIKE(sql_text, '^[[:space:]]*select[[:space:]]+ai[[:space:]]', 'i')"]
    binds: dict = {}

    s_dt = _parse_dt(start)
    if start.strip() and s_dt is None:
        raise HTTPException(status_code=400, detail={"error": f"시작일시 형식 오류: {start}"})
    if s_dt is not None:
        # 바인드명 start/end 는 Oracle 예약어(START/END) → ORA-01745. sdt/edt 사용.
        conds.append("CAST(translation_timestamp AS TIMESTAMP) >= :sdt")
        binds["sdt"] = s_dt

    e_dt = _parse_dt(end)
    if end.strip() and e_dt is None:
        raise HTTPException(status_code=400, detail={"error": f"종료일시 형식 오류: {end}"})
    if e_dt is not None:
        conds.append("CAST(translation_timestamp AS TIMESTAMP) <= :edt")
        binds["edt"] = e_dt

    text = (text or "").strip()
    if text:
        # sql_fulltext(CLOB) 부분일치. 값은 bind, 대소문자 무시.
        conds.append("UPPER(sql_fulltext) LIKE UPPER(:pat)")
        binds["pat"] = f"%{text}%"

    # mapped_sql_text(VARCHAR2)는 긴 SQL 이 잘리므로, 전체 CLOB 인 mapped_sql_fulltext 를 사용
    # (기존 응답 키/프런트 유지 위해 mapped_sql_text 로 alias).
    sql = (
        "SELECT sql_id, sql_fulltext, mapped_sql_fulltext AS mapped_sql_text, use_count, "
        "       CAST(translation_timestamp AS TIMESTAMP) AS translation_timestamp "
        "  FROM v$mapped_sql "
        " WHERE " + " AND ".join(conds) +
        " ORDER BY translation_timestamp DESC"
    )
    return await db.fetch_all(database, sql, **binds)


def _extract_question(fulltext: str) -> str:
    """sql_fulltext(= select ai <action> "<프롬프트>") 에서 따옴표 안의 프롬프트만 추출.
    따옴표가 없으면 원문 그대로."""
    s = (fulltext or "").strip()
    i, j = s.find('"'), s.rfind('"')
    if i >= 0 and j > i:
        return s[i + 1:j].strip()
    return s


@router.post("/evaluate")
async def evaluate(payload: dict, database: str = Depends(current_db)) -> dict:
    """이미 생성된 SQL(mapped_sql_text)을 LLM-as-judge 로 평가.

    AI Profile Test 의 'Profile평가' 와 같은 판정 로직(심사 Profile 의 chat)을 재사용하되,
    showsql 로 SQL 을 재생성하지 않고 caller 가 준 SQL 을 그대로 심사한다.
    [프롬프트]는 선택 Profile 의 showprompt(스키마 컨텍스트 = comment/annotation 포함)로 구성하고,
    showprompt 실패/빈응답 시 원문(sql_fulltext)으로 폴백한다.
    body: { profile(심사 Profile), prompt(=sql_fulltext 질문원문), sql(=평가할 생성 SQL) }
    """
    profile = (payload.get("profile") or "").strip()
    prompt = (payload.get("prompt") or "").strip()
    sql = (payload.get("sql") or "").strip()
    if not profile:
        raise HTTPException(status_code=400, detail={"error": "평가 Profile 을 선택하세요"})
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "평가할 SQL(mapped_sql_text)이 없습니다"})

    # 1) 스키마 컨텍스트 포함 [프롬프트] — 선택 Profile 로 showprompt(comment/annotation 포함).
    #    실패/빈응답 시 원문(prompt)으로 폴백. (profiles.evaluate 의 prompt_text 와 동일 취지)
    question = _extract_question(prompt)
    schema_prompt = ""
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=question or prompt, pn=profile, a="showprompt")
        schema_prompt = ((row or {}).get("r") or "").strip()
    except Exception:  # noqa: BLE001 — showprompt 실패는 폴백으로 흡수
        schema_prompt = ""
    prompt_for_judge = schema_prompt or prompt or "(없음)"

    # 2) 판정 프롬프트 — profiles.evaluate 의 문안과 동일(일관성 유지).
    eval_prompt = (
        "당신은 Oracle SQL 품질 심사관입니다. 아래 [프롬프트]는 자연어 질문과 스키마 컨텍스트이고, "
        "[생성SQL]은 그에 대해 생성된 SQL 입니다.\n"
        "[프롬프트]\n" + prompt_for_judge + "\n"
        "[생성SQL]\n" + sql + "\n"
        "생성SQL 이 질문 의도와 스키마에 비추어 적절한지 평가하세요. "
        "반드시 JSON 만 응답: {\"verdict\":\"적정\"|\"비적정\",\"reason\":\"한국어 사유\"}"
    )
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=eval_prompt, pn=profile, a="chat")
        eval_raw = (row or {}).get("r") or ""
        verdict, reason = _parse_verdict(eval_raw)
    except Exception as exc:  # noqa: BLE001 — 오류를 숨기지 않고 결과에 노출
        return {"verdict": "오류", "reason": "평가 호출 실패", "schema_included": bool(schema_prompt),
                "eval_response": None, "eval_prompt": eval_prompt, "error": first_line(exc)}
    return {"verdict": verdict, "reason": reason, "schema_included": bool(schema_prompt),
            "eval_response": eval_raw, "eval_prompt": eval_prompt, "error": None}
