"""Select AI Test - Table list — User Prompt 템플릿의 자리표시자를 입력값으로 병합 →
DBMS_CLOUD_AI.GENERATE(action=>'showsql') 로 SQL 생성 → 그 SELECT 를 직접 실행해
정렬된 컬럼 헤더 + 위치 기반 행 배열을 반환한다.

반환 SQL 은 신뢰 불가 입력이므로 SELECT/WITH 만 허용(읽기전용 가드)하고 ROW_LIMIT 으로 제한한다.
오류는 숨기지 않고 first_line 으로 한 줄 노출한다(프로젝트 관례).
"""
from __future__ import annotations

import json
import logging
import re
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

# 호출 모드 — Chat설정의 '호출Mode' 라디오와 대응.
#   dbms_cloud_ai : DBMS_CLOUD_AI.GENERATE(action=>'showsql')  (기본)
#   select_ai     : DBMS_CLOUD_AI.SET_PROFILE + 'select ai showsql "<prompt>"'
# select_ai 모드는 프로파일명을 SQL 에 직접 보간하므로 식별자 화이트리스트로 검증한다.
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


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
    mode = (payload.get("mode") or "dbms_cloud_ai").strip()

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

    # 2) showsql 로 SQL 문자열 생성 — 호출 모드별. (생성 시간 측정)
    if mode == "select_ai" and not _IDENT_RE.match(profile_name):
        return {"sql": None, "columns": [], "rows": [],
                "error": "profile_name 형식이 올바르지 않습니다 (select ai 모드)", "stage": "generate",
                "gen_ms": 0, "exec_ms": None, "total_ms": 0}
    t0 = time.perf_counter()
    try:
        if mode == "select_ai":
            # SET_PROFILE(세션) 후 'select ai showsql "<prompt>"' 실행 — 프롬프트는 free text 라 bind 불가.
            # 같은 커넥션에서 SET_PROFILE→select ai 를 순서대로 실행해야 세션 프로파일이 적용된다.
            pool = db.get_pool(database)
            async with pool.acquire() as conn:
                with conn.cursor() as cur:
                    await cur.execute(f"BEGIN DBMS_CLOUD_AI.SET_PROFILE('{profile_name}'); END;")
                    await cur.execute('select ai showsql "' + merged + '"')
                    r = await cur.fetchone()
            raw = (r[0] if r else "") or ""
        else:
            row = await db.fetch_one(database, _GENERATE_SQL, p=merged, pn=profile_name, a="showsql")
            raw = (row or {}).get("r") or ""
    except Exception as exc:
        gen_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("nl2sql generate failed: db=%s profile=%s mode=%s: %s", database, profile_name, mode, msg)
        return {"sql": None, "columns": [], "rows": [], "error": msg, "stage": "generate",
                "gen_ms": gen_ms, "exec_ms": None, "total_ms": gen_ms}
    gen_ms = int((time.perf_counter() - t0) * 1000)

    sql = _clean_sql(raw)
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


# ── prompt05: DB 모드 질문/조회컬럼 저장소 + 컬럼 관련성 평가 ─────────────
# 접속 스키마의 질문/컬럼 테이블(23ai CREATE TABLE IF NOT EXISTS 로 멱등 생성).
_ENSURE_DDL = [
    "CREATE TABLE IF NOT EXISTS T_NL2SQL_QUESTION ("
    " id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,"
    " question CLOB, created_at TIMESTAMP DEFAULT SYSTIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS T_NL2SQL_COLUMN ("
    " id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,"
    " question_id NUMBER, column_name VARCHAR2(400),"
    " created_at TIMESTAMP DEFAULT SYSTIMESTAMP)",
]


async def _ensure_tables(database: str) -> None:
    for ddl in _ENSURE_DDL:
        await db.execute(database, ddl)


async def _insert_returning_id(database: str, sql: str, **binds) -> int:
    """INSERT … RETURNING id INTO :id — 생성된 id 를 반환(pool.acquire + out bind)."""
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            idv = cur.var(int)
            await cur.execute(sql, id=idv, **binds)
            val = idv.getvalue()
        await conn.commit()
    return val[0] if isinstance(val, (list, tuple)) else val


@router.get("/questions")
async def list_questions(q: str = "", database: str = Depends(current_db)) -> list[dict]:
    """저장된 질문 목록(text-like 검색). q 가 비면 전체(최신순)."""
    await _ensure_tables(database)
    q = (q or "").strip()
    if q:
        return await db.fetch_all(
            database,
            "SELECT id, question FROM T_NL2SQL_QUESTION "
            "WHERE UPPER(question) LIKE '%' || UPPER(:q) || '%' ORDER BY id DESC",
            q=q,
        )
    return await db.fetch_all(
        database, "SELECT id, question FROM T_NL2SQL_QUESTION ORDER BY id DESC")


@router.post("/questions")
async def add_question(payload: dict, database: str = Depends(current_db)) -> dict:
    await _ensure_tables(database)
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    new_id = await _insert_returning_id(
        database,
        "INSERT INTO T_NL2SQL_QUESTION (question) VALUES (:q) RETURNING id INTO :id",
        q=question,
    )
    return {"id": new_id, "question": question}


@router.post("/comment-recommend")
async def comment_recommend(payload: dict, database: str = Depends(current_db)) -> dict:
    """직전 [실행]의 생성 SQL 을 기준으로, 고객 목표 SQL 처럼 나오게 하려면 comment/annotation 을
    어떻게 고쳐야 하는지 LLM 이 분석. showsql 은 재실행하지 않고 body 의 generated_sql 을 그대로 쓴다.
    body: { profile, user_prompt, message, columns, sort_by, generated_sql, desired_sql }"""
    profile = (payload.get("profile") or "").strip()
    user_prompt = payload.get("user_prompt") or ""
    message = (payload.get("message") or "").strip()
    columns_in = payload.get("columns") or ""
    sort_by = payload.get("sort_by") or ""
    generated_sql = (payload.get("generated_sql") or "").strip()
    desired_sql = (payload.get("desired_sql") or "").strip()
    if not profile:
        raise HTTPException(status_code=400, detail={"error": "AI Profile 이 없습니다(Chat설정 선택)"})
    if not message:
        raise HTTPException(status_code=400, detail={"error": "질문이 없습니다 — 먼저 실행하세요"})
    if not generated_sql:
        raise HTTPException(status_code=400, detail={"error": "직전 실행의 생성 SQL 이 없습니다 — 먼저 실행하세요"})
    if not desired_sql:
        raise HTTPException(status_code=400, detail={"error": "생성되어야 할 SQL 을 입력하세요"})
    if PH_MESSAGE not in user_prompt:
        raise HTTPException(status_code=400, detail={"error": f"User Prompt 에 {PH_MESSAGE} 자리표시자가 없습니다"})

    # /run 과 동일한 템플릿 병합 → showprompt 용 프롬프트
    merged = (
        user_prompt
        .replace(PH_COLUMNS, columns_in)
        .replace(PH_SORT, sort_by)
        .replace(PH_BASEDATE, datetime.now().strftime("%Y%m%d"))
        .replace(PH_MESSAGE, message)
    )

    # showprompt(스키마 컨텍스트=comment/annotation 포함) — showsql 은 호출하지 않음
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=merged, pn=profile, a="showprompt")
        showprompt = ((row or {}).get("r") or "").strip()
    except Exception as exc:  # noqa: BLE001
        return {"analysis": None, "analysis_prompt": None, "showprompt": None,
                "model": None, "error": f"showprompt 실패: {first_line(exc)}"}

    # 사용 LLM(모델명) — 표기용
    model = ""
    try:
        mrow = await db.fetch_one(
            database,
            "SELECT attribute_value FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES "
            "WHERE profile_name = :n AND attribute_name = 'model'",
            n=profile,
        )
        model = (mrow or {}).get("attribute_value") or ""
    except Exception:  # noqa: BLE001
        model = ""

    analysis_prompt = (
        "아래 정보를 분석하여 Oracle SELECT AI(NL2SQL)가 고객이 기대하는 SQL을 생성하도록 하기 위한\n"
        "COMMENT 및 ANNOTATION 개선안을 제안해줘.\n\n"
        "분석 대상은 SQL 자체가 아니라, SELECT AI가 참고하는 table과 column의 Schema Metadata(Comment, Annotation)이다.\n\n"
        "### 분석 기준\n\n"
        "1. showsql과 생성되어야 할 SQL의 차이점을 분석한다.\n\n"
        "2. 각 차이가 발생한 이유를 COMMENT 또는 ANNOTATION 관점에서 설명한다.\n"
        "   - 어떤 메타데이터가 부족해서 현재 SQL이 생성되었는지\n"
        "   - LLM이 왜 현재 SQL을 선택했는지\n\n"
        "3. 각 차이점마다\n"
        "   - COMMENT 수정이 적합한지\n"
        "   - ANNOTATION 추가가 적합한지\n"
        "   - 둘 다 필요한지\n"
        "   를 판단하고 수정/추가가 필요한 COMMENT와 ANNOTATION을 제안한다.\n\n"
        "4. 실제 추가 또는 수정할 COMMENT / ANNOTATION 예시를 제안한다.\n"
        "   SELECT AI가 이해하기 쉬운 자연어 형태로 작성한다.\n\n"
        "5. SQL Prompt(User Prompt)는 수정하지 않는다.\n"
        "   COMMENT와 ANNOTATION만으로 해결 가능한 방법을 우선 제안한다.\n"
        "   COMMENT/ANNOTATION만으로 해결이 어려운 경우에만 Prompt 보완이 필요한 이유를 설명한다.\n\n"
        "### 출력 형식\n\n"
        "수정이나 추가할 Comment와 Annotation을 중심으로 아래 형식으로 작성한다.\n\n"
        "> 간단한 차이점분석\n\n"
        "> Table별 COMMENT 수정안 / 제안이유(간단히)\n"
        "Table: \n"
        "Comment: \n"
        "제안이유: \n"
        "> Table별 ANNOTATION 추가안(형태:key, value) / 제안이유(간단히)\n"
        "Table: \n"
        "Annotation-Key:\n"
        "Annotation-Value:\n"
        "제안이유: \n"
        "> Column별 COMMENT 수정안 / 제안이유(간단히)\n"
        "Table: \n"
        "Column: \n"
        "Comment:\n"
        "제안이유: \n"
        "> Column별 ANNOTATION 추가안(형태:key, value) / 제안이유(간단히)\n"
        "Table: \n"
        "Column: \n"
        "Annotation-Key:\n"
        "Annotation-Value:\n"
        "제안이유: \n"
        "> 가장 효과가 큰 필수제안 3가지\n"
        "### 필수 1\n"
        "- Column별 COMMENT 수정안 / 제안이유(간단히)\n"
        "Table:\n"
        "Column:\n"
        "Comment:\n"
        "제안이유:\n\n"
        "### 필수 2\n"
        "- Table별 ANNOTATION 추가안(형태:key, value) / 제안이유(간단히)\n"
        "Table:\n"
        "Annotation-Key:\n"
        "Annotation-Value:\n"
        "제안이유:\n\n"
        "### 필수 3\n"
        "- Table별 COMMENT 수정안 / 제안이유(간단히)\n"
        "Table: \n"
        "Comment: \n"
        "제안이유:\n\n"
        "---\n\n"
        "## 고객 질문\n" + merged + "\n\n"
        "## showprompt 내용\n" + showprompt + "\n\n"
        "## showsql로 생성된 SQL\n" + generated_sql + "\n\n"
        "## 생성되어야 할 SQL\n" + desired_sql + "\n"
    )
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=analysis_prompt, pn=profile, a="chat")
        analysis = (row or {}).get("r") or ""
    except Exception as exc:  # noqa: BLE001
        return {"analysis": None, "analysis_prompt": analysis_prompt, "showprompt": showprompt,
                "model": model, "error": f"분석 호출 실패: {first_line(exc)}"}
    return {"analysis": analysis, "analysis_prompt": analysis_prompt, "showprompt": showprompt,
            "model": model, "error": None}


@router.delete("/questions/{qid}")
async def delete_question(qid: int, database: str = Depends(current_db)) -> dict:
    """질문 삭제 — 연결된 조회컬럼(T_NL2SQL_COLUMN)을 먼저 삭제한 뒤 질문을 삭제한다."""
    await _ensure_tables(database)
    await db.execute(database, "DELETE FROM T_NL2SQL_COLUMN WHERE question_id = :qid", qid=qid)
    await db.execute(database, "DELETE FROM T_NL2SQL_QUESTION WHERE id = :qid", qid=qid)
    return {"ok": True}


@router.get("/questions/{qid}/columns")
async def list_question_columns(qid: int, database: str = Depends(current_db)) -> list[dict]:
    """특정 질문에 연결된 조회 컬럼."""
    await _ensure_tables(database)
    return await db.fetch_all(
        database,
        "SELECT id, column_name FROM T_NL2SQL_COLUMN WHERE question_id = :qid ORDER BY id",
        qid=qid,
    )


@router.get("/columns")
async def list_all_columns(database: str = Depends(current_db)) -> list[dict]:
    """모든 질문에 걸친 distinct 조회 컬럼('모든 조회칼럼')."""
    await _ensure_tables(database)
    return await db.fetch_all(
        database,
        "SELECT DISTINCT column_name FROM T_NL2SQL_COLUMN "
        "WHERE column_name IS NOT NULL ORDER BY column_name",
    )


@router.post("/columns")
async def add_column(payload: dict, database: str = Depends(current_db)) -> dict:
    await _ensure_tables(database)
    name = (payload.get("column_name") or "").strip()
    qid = payload.get("question_id")
    if not name:
        raise HTTPException(status_code=400, detail={"error": "컬럼명을 입력하세요"})
    new_id = await _insert_returning_id(
        database,
        "INSERT INTO T_NL2SQL_COLUMN (question_id, column_name) "
        "VALUES (:qid, :name) RETURNING id INTO :id",
        qid=qid, name=name,
    )
    return {"id": new_id, "column_name": name, "question_id": qid}


def _parse_eval_json(raw: str, columns: list[str]) -> dict:
    """LLM 응답(JSON) → {columns:[{name,relevant,reason}], summary}. 실패 시 원문 요약."""
    s = re.sub(r"```[a-zA-Z]*|```", "", (raw or "")).strip()
    try:
        obj = json.loads(s)
        cols = []
        for c in (obj.get("columns") or []):
            cols.append({
                "name": str(c.get("name") or "").strip(),
                "relevant": bool(c.get("relevant")),
                "reason": str(c.get("reason") or "").strip(),
            })
        if cols:
            return {"columns": cols, "summary": str(obj.get("summary") or "").strip()}
    except Exception:  # noqa: BLE001 — JSON 아니면 폴백
        pass
    return {"columns": [{"name": c, "relevant": None, "reason": ""} for c in columns],
            "summary": s[:1000] if s else "평가 응답을 해석하지 못했습니다"}


@router.post("/columns/evaluate")
async def evaluate_columns(payload: dict, database: str = Depends(current_db)) -> dict:
    """선택 컬럼이 질문과 관련 있는지 LLM 평가.
    profile 로 showprompt(스키마 컨텍스트=comment/annotation 포함) 확보 후 chat 으로 판정."""
    profile = (payload.get("profile") or "").strip()
    question = (payload.get("question") or "").strip()
    columns = [str(c).strip() for c in (payload.get("columns") or []) if str(c).strip()]
    if not profile:
        raise HTTPException(status_code=400, detail={"error": "평가할 AI Profile 이 없습니다(Chat설정 선택)"})
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    if not columns:
        raise HTTPException(status_code=400, detail={"error": "평가할 컬럼을 선택하세요"})

    # 1) 스키마 컨텍스트(showprompt). 실패/빈응답이면 질문만으로 진행.
    schema_ctx = ""
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=question, pn=profile, a="showprompt")
        schema_ctx = ((row or {}).get("r") or "").strip()
    except Exception:  # noqa: BLE001
        schema_ctx = ""

    eval_prompt = (
        "당신은 데이터 분석 질문과 DB 스키마를 이해하는 심사관입니다. 아래 [질문]에 답하기 위한 "
        "조회 컬럼으로 [선택 컬럼]의 각 항목이 관련 있는지 스키마에 비추어 평가하세요.\n"
        "[질문]\n" + question + "\n"
        "[스키마 컨텍스트]\n" + (schema_ctx or "(제공 안 됨)") + "\n"
        "[선택 컬럼]\n" + ", ".join(columns) + "\n"
        "반드시 JSON 만 응답: "
        "{\"columns\":[{\"name\":\"컬럼명\",\"relevant\":true|false,\"reason\":\"한국어 사유\"}],"
        "\"summary\":\"한국어 총평\"}"
    )
    try:
        row = await db.fetch_one(database, _GENERATE_SQL, p=eval_prompt, pn=profile, a="chat")
        raw = (row or {}).get("r") or ""
    except Exception as exc:  # noqa: BLE001
        return {"columns": [], "summary": None, "schema_included": bool(schema_ctx),
                "eval_prompt": eval_prompt, "error": first_line(exc)}

    parsed = _parse_eval_json(raw, columns)
    return {"columns": parsed["columns"], "summary": parsed["summary"],
            "schema_included": bool(schema_ctx), "eval_prompt": eval_prompt, "error": None}
