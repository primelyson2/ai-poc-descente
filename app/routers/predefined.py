"""메뉴 [Select AI Test - Predefined Query] — 실제 ADB 호출.

- /predefined           : T_PREDEFINED_QUERY 행 목록/추가/수정/삭제 (드롭다운 + 관리 팝업)
- /predefined/execute   : f_predefined_query() 가 반환한 {"sql":"..."} JSON 에서 SQL 을 꺼내
                          실행해 컬럼/행(Table list)을 반환한다 (nl2sql 과 동일 형식).
- /predefined/export    : execute 가 돌려준 SQL 을 재실행해 전체 row 반환 (CSV 다운로드용).

전제: f_predefined_query 는 LLM 으로 WHERE 를 완성한 SQL 을 {"sql":"..."} JSON(또는 not_found/
error 상태 JSON)으로 반환한다. 앱은 sql 을 꺼내 실행(SELECT/WITH 만 허용)하고 결과를 표로 렌더한다.
객체명은 스키마를 붙이지 않는다 → 접속 사용자 스키마의 T_PREDEFINED_QUERY / f_predefined_query 사용.
오류는 숨기지 않고 first_line 으로 한 줄 노출한다(프로젝트 관례).
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db
from app.plsql import first_line
from app.routers.profiles import _normalize_cell  # 셀 정규화 재사용

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predefined", tags=["predefined"])

ROW_LIMIT = 100

_LIST_SQL = (
    "SELECT ID, DESCRIPTION, SQL_TEXT, ENTITY_SPEC, EXCEPTION_RULES, NL_QUESTION "
    "FROM T_PREDEFINED_QUERY ORDER BY ID"
)
_INSERT_SQL = (
    "INSERT INTO T_PREDEFINED_QUERY (DESCRIPTION, SQL_TEXT, ENTITY_SPEC, EXCEPTION_RULES, NL_QUESTION) "
    "VALUES (:description, :sql_text, :entity_spec, :exception_rules, :nl_question)"
)
_UPDATE_SQL = (
    "UPDATE T_PREDEFINED_QUERY SET DESCRIPTION=:description, SQL_TEXT=:sql_text, "
    "ENTITY_SPEC=:entity_spec, EXCEPTION_RULES=:exception_rules, NL_QUESTION=:nl_question, "
    "MOD_DTM=SYSTIMESTAMP WHERE ID=:id"
)
_DELETE_SQL = "DELETE FROM T_PREDEFINED_QUERY WHERE ID=:id"
# 함수는 완성 SQL 을 {"sql":"..."} JSON 으로 반환한다.
_EXEC_FN_SQL = "SELECT f_predefined_query(:id, :q, :pn) AS r FROM dual"

_FIELDS = ("description", "sql_text", "entity_spec", "exception_rules", "nl_question")


def _row(payload: dict) -> dict:
    """편집 폼 필드를 bind dict 로. 모두 필수 — 누락 시 400."""
    out = {}
    for f in _FIELDS:
        v = payload.get(f)
        if v is None or str(v).strip() == "":
            raise HTTPException(status_code=400, detail={"error": f"{f} 는 필수입니다"})
        out[f] = v
    return out


def _clean_sql(raw: str) -> str:
    """함수 반환 SQL 정리 — 마크다운 펜스/후행 세미콜론·공백 제거."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:3].lower() == "sql":
            s = s[3:].lstrip()
    return s.rstrip().rstrip(";").rstrip()


def _is_read_only(s: str) -> bool:
    head = s.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def _extract_sql(raw: str) -> tuple[str | None, str | None]:
    """f_predefined_query 반환(CLOB)에서 실행할 SQL 을 추출. (sql, error) 반환.
    - 정상: {"sql":"..."} → sql
    - 상태: {"status":"not_found"|"error", "result":{...}} → error
    - JSON 이 아니면 raw 를 SQL 로 간주(구버전 호환).
    LLM 이 sql 값 안의 줄바꿈을 escape 하지 않을 수 있어 json.loads 는 strict=False 로 파싱한다."""
    text = (raw or "").strip()
    if not text:
        return None, "함수가 빈 응답을 반환했습니다"
    # 앞뒤에 텍스트/펜스가 붙어도 첫 '{' ~ 마지막 '}' 만 취한다.
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            text = text[i:j + 1]
    if text.startswith("{"):
        try:
            obj = json.loads(text, strict=False)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            if obj.get("sql"):
                return _clean_sql(str(obj["sql"])), None
            status = obj.get("status")
            if status:
                res = obj.get("result") or {}
                detail = res.get("error") or res.get("missing_entities") or ""
                return None, f"함수가 '{status}' 상태를 반환했습니다" + (f": {detail}" if detail else "")
            return None, "함수 응답에 sql 이 없습니다: " + _first_line(raw)
    # JSON 이 아니면 SQL 로 간주(구버전 호환)
    return _clean_sql(raw), None


async def _run_sql(database: str, sql: str, limit: int | None):
    """SELECT 를 실행 → (columns, rows). limit=None 이면 전체."""
    pool = db.get_pool(database)
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            await cur.execute(sql)
            columns = [d[0].lower() for d in (cur.description or [])]
            fetched = await (cur.fetchmany(limit) if limit else cur.fetchall())
    rows = [[_normalize_cell(v) for v in r] for r in fetched]
    return columns, rows


@router.get("")
async def list_predefined(database: str = Depends(current_db)) -> list[dict]:
    try:
        return await db.fetch_all(database, _LIST_SQL)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})


@router.post("")
async def create_predefined(payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _INSERT_SQL, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.put("/{pid}")
async def update_predefined(pid: int, payload: dict, database: str = Depends(current_db)) -> dict:
    binds = _row(payload)
    try:
        await db.execute(database, _UPDATE_SQL, id=pid, **binds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.delete("/{pid}")
async def delete_predefined(pid: int, database: str = Depends(current_db)) -> dict:
    try:
        await db.execute(database, _DELETE_SQL, id=pid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": first_line(exc)})
    return {"ok": True}


@router.post("/execute")
async def execute_predefined(payload: dict, database: str = Depends(current_db)) -> dict:
    """f_predefined_query → 실행 SQL 획득 → 실행 → 컬럼/행(최대 ROW_LIMIT). nl2sql/run 과 동일 형식."""
    pid = payload.get("id")
    question = (payload.get("question") or "").strip()
    profile = (payload.get("profile_name") or "").strip()
    if pid is None or str(pid).strip() == "":
        raise HTTPException(status_code=400, detail={"error": "Predefined Query 를 선택하세요"})
    if not question:
        raise HTTPException(status_code=400, detail={"error": "질문을 입력하세요"})
    if not profile:
        raise HTTPException(status_code=400, detail={"error": "AI Profile 을 선택하세요"})

    def result(*, sql=None, columns=None, rows=None, error=None, stage=None,
               gen_ms=None, exec_ms=None, truncated=False) -> dict:
        has_ms = gen_ms is not None or exec_ms is not None
        return {"sql": sql, "columns": columns or [], "rows": rows or [], "error": error,
                "stage": stage, "truncated": truncated, "gen_ms": gen_ms, "exec_ms": exec_ms,
                "total_ms": ((gen_ms or 0) + (exec_ms or 0)) if has_ms else None}

    # 1) 함수 호출 → 실행할 SQL 문자열 (내부에서 엔티티 추출 + 바인드 치환). 생성 시간 측정.
    t0 = time.perf_counter()
    try:
        row = await db.fetch_one(database, _EXEC_FN_SQL, id=int(pid), q=question, pn=profile)
    except Exception as exc:
        gen_ms = int((time.perf_counter() - t0) * 1000)
        msg = first_line(exc)
        logger.warning("predefined generate failed: db=%s id=%s: %s", database, pid, msg)
        return result(error=msg, stage="generate", gen_ms=gen_ms)
    gen_ms = int((time.perf_counter() - t0) * 1000)

    raw = (row or {}).get("r") or ""
    sql, perr = _extract_sql(raw)
    if perr:
        return result(error=perr, stage="parse", gen_ms=gen_ms)
    if not sql:
        return result(error="함수가 SQL 을 반환하지 않았습니다 (빈 응답)", stage="empty", gen_ms=gen_ms)
    if not _is_read_only(sql):
        # sql 값이 SELECT/WITH 가 아닌 경우 — 내용을 그대로 노출
        return result(sql=sql, error="실행할 조회 SQL 이 아닙니다: " + _first_line(sql),
                      stage="validate", gen_ms=gen_ms)

    # 2) 반환된 SELECT 실행 — 정렬 컬럼 + 위치 기반 행. fetchmany 로 ROW_LIMIT 제한. 실행 시간 측정.
    t1 = time.perf_counter()
    try:
        columns, rows = await _run_sql(database, sql, ROW_LIMIT)
    except Exception as exc:
        exec_ms = int((time.perf_counter() - t1) * 1000)
        msg = first_line(exc)
        logger.warning("predefined exec failed: db=%s id=%s: %s", database, pid, msg)
        return result(sql=sql, error=msg, stage="execute", gen_ms=gen_ms, exec_ms=exec_ms)
    exec_ms = int((time.perf_counter() - t1) * 1000)

    return result(sql=sql, columns=columns, rows=rows, gen_ms=gen_ms, exec_ms=exec_ms,
                  truncated=len(rows) == ROW_LIMIT)


@router.post("/export")
async def export_predefined(payload: dict, database: str = Depends(current_db)) -> dict:
    """execute 가 돌려준 SQL 을 재실행해 전체 row 반환(ROW_LIMIT 미적용).
    클라이언트가 보낸 SQL 이므로 read-only 가드를 동일하게 재적용한다."""
    sql = _clean_sql(payload.get("sql") or "")
    if not sql:
        raise HTTPException(status_code=400, detail={"error": "sql required"})
    if not _is_read_only(sql):
        raise HTTPException(status_code=400, detail={"error": "조회(SELECT/WITH) 문장만 실행할 수 있습니다"})
    try:
        columns, rows = await _run_sql(database, sql, None)
    except Exception as exc:
        msg = first_line(exc)
        logger.warning("predefined export failed: db=%s: %s", database, msg)
        raise HTTPException(status_code=400, detail={"error": msg})
    return {"columns": columns, "rows": rows}
