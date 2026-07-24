"""AI Chat for Table list — Chat설정(변수 / Team / User Prompt) 기반으로 RUN_TEAM 을 호출하고,
agent 가 반환한 SQL(들)을 앱이 직접 실행해 table 형태로 답한다. (prompt11)

ai_chat(chat.py) 와 로직이 동일하되 답변 처리만 다르다 — 추후 기능 분리 가능성 때문에
소스를 공유하지 않고 별도 파일로 유지한다(사용자 확정).

agent 응답 JSON 계약 (기본 User Prompt 템플릿이 이 형식만 반환하도록 지시):

    {
      "answers": [
        { "title": "이 SQL 이 조회하는 내용 한 줄 설명", "sql": "SELECT ..." },
        ...                                       -- 복잡한 질문이면 질문을 분해해 N개
      ],
      "note": "여러 SQL 결과를 종합할 때 참고할 설명 (선택)"
    }

파싱 fallback (agent 가 JSON 을 안 지킬 때 — LLM 이므로 방어적으로):
  ① 펜스 제거 후 json.loads (전체 → 첫 '{'~마지막 '}' 부분 순서로 시도)
  ② 실패 시 첫 SELECT/WITH 부터를 단일 SQL 로 간주해 answers 1개로 승격
  ③ 그것도 없으면 stage="extract" 로 answer 원문만 반환 (화면은 텍스트 버블로 표시)

각 SQL 은 개별 실행하며 에러를 격리한다 — 한 SQL 의 ORA 오류가 다른 SQL 실행을 막지 않고,
오류는 해당 항목의 error 로 그대로 노출한다(프로젝트 관례). 미리보기는 5행, 전체 결과는
/export 재실행(다운로드용, Table list 의 export 와 동일 방식).
"""
from __future__ import annotations

import json
import logging
import re
import time

import oracledb
from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import build_run_team_block, first_line, read_clob
from app.routers.agents import build_timeline_and_logs
from app.routers.profiles import _normalize_cell  # 셀 정규화 재사용 (nl2sql 과 동일 패턴)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat_tl", tags=["chat_tl"])

MESSAGE_PLACEHOLDER = "##메시지##"

# 채팅 버블 안 미리보기 행수 — 전체는 /export 다운로드로 제공.
PREVIEW_ROWS = 5


def _user_prompt_expr(user_prompt: str) -> tuple[str, bool]:
    """User Prompt 템플릿을 user_prompt 인자용 PL/SQL 표현식으로 변환.

    ##메시지## 는 `' || :msg || '` 로 치환해 메시지만 바인드한다.
    반환: (PL/SQL 표현식, :msg 사용 여부)
    """
    use_msg = MESSAGE_PLACEHOLDER in user_prompt
    src = user_prompt.replace(MESSAGE_PLACEHOLDER, "' || :msg || '") if use_msg else user_prompt
    return "'" + src + "'", use_msg


def _clean_sql(raw: str) -> str:
    """SQL 문자열 정리 — 마크다운 펜스/후행 세미콜론·공백 제거. (nl2sql._clean_sql 복사)"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:3].lower() == "sql":
            s = s[3:].lstrip()
    return s.rstrip().rstrip(";").rstrip()


def _is_read_only(s: str) -> bool:
    head = s.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


def _strip_fences(raw: str) -> str:
    """answer 전체에서 마크다운 코드펜스(```json 등) 를 벗긴다."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rstrip()
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_answers(answer: str) -> tuple[list[dict], str | None]:
    """agent answer → (answers[{title, sql}], note). 모듈 docstring 의 ①②③ fallback."""
    s = _strip_fences(answer)

    # ① JSON: raw_decode 로 answer 안의 모든 '{' 위치를 스캔 — 앞뒤 잡담이 섞이거나
    #    JSON 객체가 여러 개 이어져 있어도(REPORTER 가 재작성한 경우 실측) answers 객체를 찾는다.
    #    strict=False: LLM 이 sql 문자열 안에 실제 개행을 넣은 비표준 JSON 도 파싱(실측 사례 — ORA-00911 원인).
    dec = json.JSONDecoder(strict=False)
    idx = 0
    while True:
        start = s.find("{", idx)
        if start == -1:
            break
        try:
            obj, _end = dec.raw_decode(s[start:])
        except Exception:
            idx = start + 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("answers"), list):
            items = []
            for a in obj["answers"]:
                if isinstance(a, dict) and str(a.get("sql") or "").strip():
                    items.append({
                        "title": str(a.get("title") or "").strip(),
                        "sql": str(a["sql"]).strip(),
                    })
            if items:
                note = str(obj.get("note") or "").strip() or None
                return items, note
        idx = start + max(_end, 1)

    # ② fallback: 첫 SELECT/WITH 부터 단일 SQL 로 승격.
    #    깨진 JSON 문자열 안의 SQL 을 집었을 수 있으므로 JSON 꼬리("}] 등)를 잘라내고,
    #    남아 있는 JSON 이스케이프(\" \n \t \\)를 해제한다 — \" 가 남으면 ORA-00911 (실측).
    m = re.search(r"\b(select|with)\b", s, re.IGNORECASE)
    if m:
        frag = s[m.start():].strip()
        cut = len(frag)
        for marker in ('"}]', '"}', '"]', '```'):
            i = frag.find(marker)
            if i != -1:
                cut = min(cut, i)
        frag = frag[:cut].strip()
        if "\\" in frag:
            frag = (frag.replace('\\"', '"').replace("\\n", "\n")
                        .replace("\\t", "\t").replace("\\/", "/").replace("\\\\", "\\"))
        if frag:
            return [{"title": "", "sql": frag}], None

    # ③ SQL 없음
    return [], None


async def _run_preview(database: str, sql: str) -> dict:
    """SQL 1건 실행 — PREVIEW_ROWS 행 + truncated. 오류는 dict 로 반환(격리)."""
    if not _is_read_only(sql):
        return {"columns": [], "rows": [], "truncated": False, "exec_ms": None,
                "error": "생성된 문장이 조회(SELECT/WITH) 가 아니라 실행을 거부했습니다",
                "stage": "validate"}
    t0 = time.perf_counter()
    try:
        pool = db.get_pool(database)
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchmany(PREVIEW_ROWS + 1)  # +1 로 truncated 판정
    except Exception as exc:
        exec_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("chat_tl exec failed: db=%s: %s", database, msg)
        return {"columns": [], "rows": [], "truncated": False, "exec_ms": exec_ms,
                "error": msg, "stage": "execute"}
    exec_ms = int((time.perf_counter() - t0) * 1000)
    truncated = len(fetched) > PREVIEW_ROWS
    rows = [[_normalize_cell(v) for v in r] for r in fetched[:PREVIEW_ROWS]]
    return {"columns": columns, "rows": rows, "truncated": truncated,
            "exec_ms": exec_ms, "error": None, "stage": None}


@router.post("/send")
async def chat_tl_send(payload: dict, database: str = Depends(current_db)) -> dict:
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

    # 1) RUN_TEAM — chat.py 와 동일 파이프라인
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
        logger.warning("chat_tl RUN_TEAM failed: db=%s team=%s: %s", database, team, first_line(exc))
        raise HTTPException(status_code=400, detail={"error": first_line(exc), "team": team})

    run_ms = int((time.perf_counter() - t0) * 1000)

    # 2) answer → SQL 목록 파싱 (①JSON ②단일 SQL 승격 ③extract 실패)
    answers, note = _parse_answers(answer or "")

    # 3) 각 SQL 개별 실행 (에러 격리 — 실패 항목도 결과 목록에 그대로 남긴다)
    results = []
    for item in answers:
        sql = _clean_sql(item["sql"])
        r = await _run_preview(database, sql)
        results.append({"title": item["title"], "sql": sql, **r})

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # 단계별 timeline·thinking 동봉 — 실패해도 답변은 그대로 반환 (디버깅 보조 정보일 뿐).
    extras = {"timeline": [], "thinking": {"rows": [], "error": None}, "raw_logs": {}}
    try:
        extras = await build_timeline_and_logs(database, conv_id)
    except Exception as exc:
        logger.warning("chat_tl timeline build failed: db=%s conv=%s: %s",
                       database, conv_id, first_line(exc))

    return {
        "conversation_id": conv_id,
        "answer": answer or "",
        "note": note,
        "results": results,
        # SQL 을 하나도 못 찾으면 extract 실패 — 화면은 answer 원문을 텍스트 버블로 표시
        "error": None if results else "답변에서 SQL 을 찾지 못했습니다",
        "stage": None if results else "extract",
        "run_ms": run_ms,
        "elapsed_ms": elapsed_ms,
        "timeline": extras.get("timeline", []),
        "thinking": extras.get("thinking", {"rows": [], "error": None}),
        "raw_logs": extras.get("raw_logs", {}),
    }


@router.post("/export")
async def chat_tl_export(payload: dict, database: str = Depends(current_db)) -> dict:
    """미리보기에 쓴 SQL 을 다시 실행해 전체 row 를 반환한다(CSV 다운로드용 — 행수 무제한).
    클라이언트가 보낸 SQL 이므로 read-only 가드를 동일하게 재적용한다. (nl2sql/export 와 동일 방식)"""
    sql = _clean_sql(payload.get("sql") or "")
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "sql required"})
    if not _is_read_only(sql):
        raise HTTPException(status_code=400, detail={"error": "조회(SELECT/WITH) 문장만 실행할 수 있습니다"})

    try:
        pool = db.get_pool(database)
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchall()
        rows = [[_normalize_cell(v) for v in r] for r in fetched]
    except Exception as exc:
        msg = first_line(exc)
        logger.warning("chat_tl export failed: db=%s: %s", database, msg)
        raise HTTPException(status_code=400, detail={"error": msg})

    return {"columns": columns, "rows": rows}
