"""Select AI Test - Table list — User Prompt 템플릿의 자리표시자를 입력값으로 병합 →
DBMS_CLOUD_AI.GENERATE(action=>'showsql') 로 SQL 생성 → 그 SELECT 를 직접 실행해
정렬된 컬럼 헤더 + 위치 기반 행 배열을 반환한다.

반환 SQL 은 신뢰 불가 입력이므로 SELECT/WITH 만 허용(읽기전용 가드)하고 ROW_LIMIT 으로 제한한다.
오류는 숨기지 않고 first_line 으로 한 줄 노출한다(프로젝트 관례).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.profiles import _GENERATE_SQL, _normalize_cell  # GENERATE 패턴/셀 정규화 재사용

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nl2sql", tags=["nl2sql"])

# User Prompt 템플릿 자리표시자 — 화면 입력값으로 치환
PH_MESSAGE = "##메시지##"
PH_COLUMNS = "##조회할 컬럼##"
PH_SORT = "##정렬기준##"
PH_BASEDATE = "##기준일##"   # 실행 시 오늘 날짜(YYYYMMDD)로 치환

ROW_LIMIT = 100


def _clean_sql(raw: str) -> str:
    """showsql 반환값 정리 — 마크다운 펜스/후행 세미콜론·공백 제거."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:3].lower() == "sql":
            s = s[3:].lstrip()
    return s.rstrip().rstrip(";").rstrip()


def _is_read_only(s: str) -> bool:
    head = s.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


@router.post("/run")
async def nl2sql_run(payload: dict, database: str = Depends(current_db)) -> dict:
    profile_name = (payload.get("profile_name") or "").strip()
    user_prompt = payload.get("user_prompt") or ""
    message = payload.get("message") or ""
    columns_in = payload.get("columns") or ""
    sort_by = payload.get("sort_by") or ""

    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})
    if not message.strip():
        raise HTTPException(status_code=400, detail={"error": "message required"})
    if PH_MESSAGE not in user_prompt:
        raise HTTPException(
            status_code=400,
            detail={"error": f"User Prompt 에 {PH_MESSAGE} 자리표시자가 없습니다"},
        )

    # 1) 템플릿 병합 — GENERATE 의 prompt 는 :p 바인드라 plain replace 로 안전.
    #    ##기준일## 은 실행 시점의 오늘 날짜(YYYYMMDD)로 자동 치환한다(선택 자리표시자).
    merged = (
        user_prompt
        .replace(PH_COLUMNS, columns_in)
        .replace(PH_SORT, sort_by)
        .replace(PH_BASEDATE, datetime.now().strftime("%Y%m%d"))
        .replace(PH_MESSAGE, message)
    )

    # 2) showsql 로 SQL 문자열 생성. (생성 시간 측정)
    t0 = time.perf_counter()
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=merged, pn=profile_name, a="showsql")
    except Exception as exc:
        gen_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("nl2sql GENERATE failed: db=%s profile=%s: %s", database, profile_name, msg)
        return {"sql": None, "columns": [], "rows": [], "error": msg, "stage": "generate",
                "gen_ms": gen_ms, "exec_ms": None, "total_ms": gen_ms}
    gen_ms = int((time.perf_counter() - t0) * 1000)

    sql = _clean_sql((row or {}).get("r") or "")
    if not sql:
        return {"sql": None, "columns": [], "rows": [],
                "error": "모델이 SQL 을 생성하지 못했습니다 (빈 응답)", "stage": "empty",
                "gen_ms": gen_ms, "exec_ms": None, "total_ms": gen_ms}
    if not _is_read_only(sql):
        return {"sql": sql, "columns": [], "rows": [],
                "error": "생성된 문장이 조회(SELECT/WITH) 가 아니라 실행을 거부했습니다",
                "stage": "validate", "gen_ms": gen_ms, "exec_ms": None, "total_ms": gen_ms}

    # 3) 생성된 SELECT 실행 — 정렬 컬럼 + 위치 기반 행. fetchmany 로 ROW_LIMIT 제한. (실행 시간 측정)
    t1 = time.perf_counter()
    try:
        pool = db.get_pool(database)
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                await cur.execute(sql)
                columns = [d[0].lower() for d in (cur.description or [])]
                fetched = await cur.fetchmany(ROW_LIMIT)
        rows = [[_normalize_cell(v) for v in r] for r in fetched]
    except Exception as exc:
        exec_ms = int((time.perf_counter() - t1) * 1000)
        msg = first_line(exc)
        logger.warning("nl2sql exec failed: db=%s profile=%s: %s", database, profile_name, msg)
        return {"sql": sql, "columns": [], "rows": [], "error": msg, "stage": "execute",
                "gen_ms": gen_ms, "exec_ms": exec_ms, "total_ms": gen_ms + exec_ms}
    exec_ms = int((time.perf_counter() - t1) * 1000)

    return {"sql": sql, "columns": columns, "rows": rows, "error": None,
            "truncated": len(rows) == ROW_LIMIT,
            "gen_ms": gen_ms, "exec_ms": exec_ms, "total_ms": gen_ms + exec_ms}


# AI분석 — 조회 데이터를 프롬프트에 직렬화할 때의 문자수 상한(초과분은 행 단위로 절단).
ANALYZE_DATA_CHAR_LIMIT = 12000


def _serialize_rows(columns: list[str], rows: list[list]) -> tuple[str, int]:
    """(직렬화 텍스트, 포함 행수). 컬럼 헤더 + '|' 구분 행. 상한 초과 시 뒤 행을 버린다."""
    header = "컬럼: " + ", ".join(columns)
    lines = [header]
    used = len(header)
    included = 0
    for r in rows:
        line = " | ".join("" if v is None else str(v) for v in r)
        if used + len(line) + 1 > ANALYZE_DATA_CHAR_LIMIT:
            break
        lines.append(line)
        used += len(line) + 1
        included += 1
    return "\n".join(lines), included


@router.post("/analyze")
async def nl2sql_analyze(payload: dict, database: str = Depends(current_db)) -> dict:
    """직전 생성 SQL 로 최대 ROW_LIMIT 행을 조회해, 편집된 페르소나 프롬프트와 함께
    DBMS_CLOUD_AI.GENERATE(action=>'chat') 로 자연어 분석 결과를 생성한다.
    클라이언트가 보낸 SQL 이므로 read-only 가드를 동일하게 재적용한다."""
    profile_name = (payload.get("profile_name") or "").strip()
    prompt = payload.get("prompt") or ""
    sql = _clean_sql(payload.get("sql") or "")

    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})
    if not prompt.strip():
        raise HTTPException(status_code=400, detail={"error": "분석 프롬프트가 비어 있습니다"})
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "분석할 SQL 이 없습니다 — 먼저 질문을 실행하세요"})
    if not _is_read_only(sql):
        raise HTTPException(status_code=400, detail={"error": "조회(SELECT/WITH) 문장만 분석할 수 있습니다"})

    def result(*, analysis=None, prompt_out=None, columns=None, row_count=0, truncated=False,
               error=None, stage=None, gen_ms=None, exec_ms=None) -> dict:
        has_ms = gen_ms is not None or exec_ms is not None
        return {"analysis": analysis, "prompt": prompt_out, "columns": columns or [],
                "row_count": row_count, "truncated": truncated, "error": error, "stage": stage,
                "gen_ms": gen_ms, "exec_ms": exec_ms,
                "total_ms": ((gen_ms or 0) + (exec_ms or 0)) if has_ms else None}

    # 1) 데이터 조회 — 최대 ROW_LIMIT 행. (실행 시간 측정)
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
        logger.warning("nl2sql analyze exec failed: db=%s: %s", database, msg)
        return result(error=msg, stage="execute", exec_ms=exec_ms)
    exec_ms = int((time.perf_counter() - t0) * 1000)

    if not rows:
        return result(error="분석할 데이터가 없습니다 (조회 결과 0행)", stage="empty",
                      columns=columns, exec_ms=exec_ms)

    # 2) 분석 프롬프트 조립 — 편집된 프롬프트 + 직렬화된 데이터.
    data_text, included = _serialize_rows(columns, rows)
    final_prompt = (
        prompt.strip()
        + f"\n\n[분석 대상 데이터] (조회 {len(rows)}행 중 {included}행)\n"
        + data_text
    )

    # 3) GENERATE(chat) 로 자연어 분석. (생성 시간 측정)
    t1 = time.perf_counter()
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=final_prompt, pn=profile_name, a="chat")
    except Exception as exc:
        gen_ms = int((time.perf_counter() - t1) * 1000)
        msg = first_line(exc)
        logger.warning("nl2sql analyze GENERATE failed: db=%s profile=%s: %s", database, profile_name, msg)
        return result(error=msg, stage="generate", columns=columns, row_count=len(rows), exec_ms=exec_ms, gen_ms=gen_ms)
    gen_ms = int((time.perf_counter() - t1) * 1000)

    analysis = ((row or {}).get("r") or "").strip()
    return result(analysis=analysis, prompt_out=final_prompt, columns=columns,
                  row_count=len(rows), truncated=len(rows) == ROW_LIMIT,
                  exec_ms=exec_ms, gen_ms=gen_ms)


@router.post("/export")
async def nl2sql_export(payload: dict, database: str = Depends(current_db)) -> dict:
    """이미 생성된 SQL 을 다시 실행해 전체 row 를 반환한다(CSV 다운로드용 — ROW_LIMIT 미적용).
    클라이언트가 보낸 SQL 이므로 read-only 가드를 동일하게 재적용한다."""
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
        logger.warning("nl2sql export failed: db=%s: %s", database, msg)
        raise HTTPException(status_code=400, detail={"error": msg})

    return {"columns": columns, "rows": rows}
