"""메뉴 [Select AI Test - 페르소나분석] — 페르소나+질문으로 추출 SQL 생성 → 실행 → 분석.

화면은 2단계로 진행한다:
  1단계  POST /persona-analysis/gen-sql : 추출 SQL 만 생성해 반환(생성된 SQL 을 먼저 확인).
     - mode='showsql'    : '페르소나 기반 질문'(페르소나 프롬프트 + 사용자 질문)을
                           GENERATE(action=>'showsql') 로 추출 SQL 생성. showprompt 결과도 참고용 반환.
     - mode='showprompt2': showprompt 로 스키마 컨텍스트를 받고, 페르소나(+질문)를 프롬프트에 추가해
                           GENERATE(action=>'chat') 로 추출 SQL 을 직접 생성.
  2단계  POST /persona-analysis/analyze : (사용자가 확인/수정한) SQL 을 실행(최대 ROW_LIMIT 행)하고
                           페르소나 프롬프트 + 조회 데이터로 GENERATE(action=>'chat') 자연어 분석.

기존 nl2sql/profiles 헬퍼를 재사용한다. 오류는 first_line 으로 한 줄 노출한다.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.nl2sql import ROW_LIMIT, _clean_sql, _is_read_only, _serialize_rows
from app.routers.profiles import _GENERATE_SQL, _normalize_cell

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona-analysis", tags=["persona-analysis"])

# gen-sql 단계에서 프롬프트에 덧붙이는 공통 지시 — 개별(raw) 행 대신 집계 결과 SELECT 를 유도한다.
# 생성 SQL 은 실행 시 최대 ROW_LIMIT(100) 행만 읽으므로 원시행 나열은 분석 근거가 빈약하다.
# 페르소나 프롬프트를 건드리지 않고 여기(코드) 한 곳에만 두어 모든 페르소나에 자동 적용한다.
# 분석(analyze) 프롬프트에는 붙이지 않는다(SQL 생성 때만).
_AGG_DIRECTIVE = (
    "[집계 우선 조회] 개별 행을 나열하지 말고 GROUP BY·COUNT·SUM·AVG·비율(RATIO_TO_REPORT) 등 "
    "집계 결과를 반환하는 SELECT 를 생성하라(상위 N·구간·세그먼트 요약 우선). "
    "단, 개별 레코드 확인 자체가 목적인 질문이면 상세 행을 허용한다."
)


# ── 1단계: SQL 생성만 ─────────────────────────────────────────────
@router.post("/gen-sql")
async def persona_gen_sql(payload: dict, database: str = Depends(current_db)) -> dict:
    profile_name = (payload.get("profile_name") or "").strip()
    question = (payload.get("question") or "").strip()
    persona_prompt = payload.get("persona_prompt") or ""
    mode = (payload.get("mode") or "showsql").strip()

    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    if not persona_prompt.strip():
        raise HTTPException(status_code=400, detail={"error": "페르소나(분석 프롬프트)를 선택하세요"})
    if mode not in ("showsql", "showprompt2"):
        mode = "showsql"

    def result(*, sql=None, showprompt=None, error=None, stage=None, gen_ms=None) -> dict:
        return {"sql": sql, "showprompt": showprompt, "error": error, "stage": stage, "gen_ms": gen_ms}

    t0 = time.perf_counter()
    showprompt = None
    try:
        if mode == "showprompt2":
            # B) showprompt 로 스키마 컨텍스트를 받고, chat 으로 추출 SQL 을 직접 생성.
            sp_row = await db.fetch_one(database, _GENERATE_SQL, p=question, pn=profile_name, a="showprompt")
            showprompt = (sp_row or {}).get("r") or ""
            gen_prompt = (
                persona_prompt.strip() + "\n\n"
                "[요청] 위 분석에 필요한 데이터를 조회하는 Oracle SELECT 문 하나만 생성하라. "
                "설명·주석·마크다운 없이 실행 가능한 SQL 만 출력하라.\n"
                + _AGG_DIRECTIVE + "\n"
                f"[질문] {question}\n"
                "[스키마 컨텍스트]\n" + showprompt
            )
            gen_row = await db.fetch_one(database, _GENERATE_SQL, p=gen_prompt, pn=profile_name, a="chat")
            sql = _clean_sql((gen_row or {}).get("r") or "")
        else:
            # A) '페르소나 기반 질문'(페르소나 프롬프트 + 사용자 질문)으로 showsql 생성.
            gen_question = (
                persona_prompt.strip()
                + "\n\n[데이터 조회 요청] 위 분석에 필요한 데이터를 조회한다: " + question
                + "\n" + _AGG_DIRECTIVE
            )
            sql_row = await db.fetch_one(database, _GENERATE_SQL, p=gen_question, pn=profile_name, a="showsql")
            sql = _clean_sql((sql_row or {}).get("r") or "")
            try:
                sp_row = await db.fetch_one(database, _GENERATE_SQL, p=gen_question, pn=profile_name, a="showprompt")
                showprompt = (sp_row or {}).get("r") or ""
            except Exception:  # showprompt 실패는 참고정보라 무시
                showprompt = None
    except Exception as exc:
        gen_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("persona gensql failed: db=%s profile=%s mode=%s: %s", database, profile_name, mode, msg)
        return result(error=msg, stage="gensql", showprompt=showprompt, gen_ms=gen_ms)
    gen_ms = int((time.perf_counter() - t0) * 1000)

    if not sql:
        return result(error="모델이 SQL 을 생성하지 못했습니다 (빈 응답)", stage="empty",
                      showprompt=showprompt, gen_ms=gen_ms)
    if not _is_read_only(sql):
        return result(sql=sql, showprompt=showprompt, gen_ms=gen_ms, stage="validate",
                      error="생성된 문장이 조회(SELECT/WITH) 가 아니라 실행을 거부했습니다")
    return result(sql=sql, showprompt=showprompt, gen_ms=gen_ms)


# ── 2단계: 실행 + 분석 ────────────────────────────────────────────
@router.post("/analyze")
async def persona_analyze(payload: dict, database: str = Depends(current_db)) -> dict:
    profile_name = (payload.get("profile_name") or "").strip()
    persona_prompt = payload.get("persona_prompt") or ""
    sql = _clean_sql(payload.get("sql") or "")

    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})
    if not persona_prompt.strip():
        raise HTTPException(status_code=400, detail={"error": "페르소나(분석 프롬프트)가 비어 있습니다"})
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "실행할 SQL 이 없습니다"})
    if not _is_read_only(sql):
        raise HTTPException(status_code=400, detail={"error": "조회(SELECT/WITH) 문장만 실행할 수 있습니다"})

    def result(*, analysis=None, columns=None, rows=None, truncated=False,
               error=None, stage=None, exec_ms=None, analyze_ms=None) -> dict:
        parts = [m for m in (exec_ms, analyze_ms) if m is not None]
        return {"analysis": analysis, "columns": columns or [], "rows": rows or [],
                "truncated": truncated, "error": error, "stage": stage,
                "exec_ms": exec_ms, "analyze_ms": analyze_ms,
                "total_ms": (sum(parts) if parts else None)}

    # 실행 — 최대 ROW_LIMIT 행.
    t0 = time.perf_counter()
    try:
        pool = db.get_pool(database)
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchmany(ROW_LIMIT)
        rows = [[_normalize_cell(v) for v in r] for r in fetched]
    except Exception as exc:
        exec_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("persona analyze exec failed: db=%s: %s", database, msg)
        return result(error=msg, stage="execute", exec_ms=exec_ms)
    exec_ms = int((time.perf_counter() - t0) * 1000)
    truncated = len(rows) == ROW_LIMIT

    if not rows:
        return result(columns=columns, rows=rows, error="조회 결과가 0행이라 분석을 건너뜁니다",
                      stage="empty", exec_ms=exec_ms)

    # 분석 — 페르소나 프롬프트 + 조회 데이터로 chat.
    data_text, included = _serialize_rows(columns, rows)
    final_prompt = (
        persona_prompt.strip()
        + f"\n\n[분석 대상 데이터] (조회 {len(rows)}행 중 {included}행)\n"
        + data_text
    )
    t1 = time.perf_counter()
    try:
        an_row = await db.fetch_one(database, _GENERATE_SQL, p=final_prompt, pn=profile_name, a="chat")
    except Exception as exc:
        analyze_ms = int((time.perf_counter() - t1) * 1000)
        msg = first_line(exc)
        logger.warning("persona analyze failed: db=%s profile=%s: %s", database, profile_name, msg)
        # 분석만 실패 — 조회 행은 유지해서 반환.
        return result(columns=columns, rows=rows, truncated=truncated,
                      error=msg, stage="analyze", exec_ms=exec_ms, analyze_ms=analyze_ms)
    analyze_ms = int((time.perf_counter() - t1) * 1000)
    analysis = ((an_row or {}).get("r") or "").strip()

    return result(analysis=analysis, columns=columns, rows=rows, truncated=truncated,
                  exec_ms=exec_ms, analyze_ms=analyze_ms)
