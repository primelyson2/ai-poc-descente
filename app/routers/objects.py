"""기능요구사항03 (메뉴 [1] Profile Object Comment & Annotation) — 실제 DDL 호출.

- GET  /api/objects/{owner}/{table}/metadata         조회
- PUT  /api/objects/{owner}/{table}/comment          테이블 코멘트 수정
- PUT  /api/objects/{owner}/{table}/columns/{column}/comment
- PUT  /api/objects/{owner}/{table}/annotation       테이블 annotation 수정 (23ai)
- PUT  /api/objects/{owner}/{table}/columns/{column}/annotation
- POST /api/objects/{owner}/{table}/columns/bulk     컬럼 메타데이터 일괄 저장

> identifier (owner/table/column/annotation name) 는 bind 불가 → whitelist 정규식 검증 후 직접 보간.
> COMMENT / Annotation 의 텍스트 값은 반드시 bind (또는 single-quote 이스케이프).
> Oracle DDL 은 auto-commit 이므로 bulk 실패 시 ROLLBACK 불가 — 어디서 멈췄는지 응답에 명시.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from app import db
from app.deps import current_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/objects", tags=["objects"])

# Oracle unquoted identifier: 영문자로 시작, A-Z 0-9 _ $ # 만 허용 (대문자 변환 후 검증)
IDENT_RE = re.compile(r"^[A-Z][A-Z0-9_$#]*$")
# Annotation 이름은 mixed-case 허용
ANNOT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


def _ident(name: str, label: str) -> str:
    """대문자로 정규화 + whitelist 검증. 통과한 식별자를 반환."""
    if not name:
        raise HTTPException(status_code=400, detail={"error": f"{label} required"})
    u = name.upper()
    if not IDENT_RE.match(u):
        raise HTTPException(status_code=400, detail={"error": f"invalid {label}: {name}"})
    return u


def _annot_name(name: str) -> str:
    if not name or not ANNOT_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail={"error": f"invalid annotation name: {name}"})
    return name


def _first_line(exc: Exception) -> str:
    s = str(exc).strip()
    return s.splitlines()[0] if s else "execution failed"


def _sql_literal(value: str | None) -> str:
    """문자열 리터럴 — single-quote 이스케이프. None 은 빈 문자열로."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    return "'" + value.replace("'", "''") + "'"


# === 메타데이터 조회 ===

@router.get("/{owner}/{table}/metadata")
async def object_metadata(
    owner: str, table: str, database: str = Depends(current_db)
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")

    # 1. USER_ANNOTATIONS_USAGE 뷰 존재 여부 (23ai 지원 판별)
    annot_view_rows = await db.fetch_all(
        database,
        "SELECT 1 AS x FROM ALL_VIEWS "
        "WHERE view_name = 'USER_ANNOTATIONS_USAGE' AND ROWNUM <= 1",
    )
    annotations_supported = bool(annot_view_rows)

    # 2. 테이블 코멘트
    tbl_rows = await db.fetch_all(
        database,
        "SELECT comments FROM ALL_TAB_COMMENTS "
        "WHERE UPPER(owner) = :owner AND UPPER(table_name) = :tbl",
        owner=o, tbl=t,
    )
    table_comment = (tbl_rows[0].get("comments") if tbl_rows else None) or ""

    # 3. 컬럼 + 컬럼 코멘트 (LEFT JOIN — 코멘트 없어도 컬럼은 반환)
    col_rows = await db.fetch_all(
        database,
        "SELECT c.column_name, c.data_type, cc.comments "
        "  FROM ALL_TAB_COLUMNS c "
        "  LEFT JOIN ALL_COL_COMMENTS cc "
        "    ON cc.owner = c.owner "
        "   AND cc.table_name = c.table_name "
        "   AND cc.column_name = c.column_name "
        " WHERE UPPER(c.owner) = :owner AND UPPER(c.table_name) = :tbl "
        " ORDER BY c.column_id",
        owner=o, tbl=t,
    )

    # 4. Annotations (테이블 + 컬럼) 일괄
    table_annotations: dict[str, str] = {}
    column_annotations: dict[str, dict[str, str]] = {}
    if annotations_supported:
        try:
            # USER_ANNOTATIONS_USAGE: column_name 이 NULL 이면 테이블 레벨, 값이 있으면 컬럼 레벨
            # (OBJECT_TYPE 은 둘 다 'TABLE' 로 들어옴)
            ann_rows = await db.fetch_all(
                database,
                "SELECT column_name, annotation_name, annotation_value "
                "  FROM USER_ANNOTATIONS_USAGE "
                " WHERE UPPER(object_name) = :tbl",
                tbl=t,
            )
            for r in ann_rows:
                an = r.get("annotation_name")
                av = r.get("annotation_value") or ""
                col = r.get("column_name")
                if col:
                    column_annotations.setdefault(col, {})[an] = av
                else:
                    table_annotations[an] = av
        except Exception as e:
            logger.warning("USER_ANNOTATIONS_USAGE query failed: %s", _first_line(e))
            annotations_supported = False

    columns = [
        {
            "name": r.get("column_name"),
            "data_type": r.get("data_type"),
            "comment": r.get("comments") or "",
            "annotations": column_annotations.get(r.get("column_name"), {}),
        }
        for r in col_rows
    ]

    return {
        "annotations_supported": annotations_supported,
        "table": {"comment": table_comment, "annotations": table_annotations},
        "columns": columns,
    }


# === 단건 수정 ===

@router.put("/{owner}/{table}/comment")
async def update_table_comment(
    owner: str, table: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    text = body.get("text") or ""
    try:
        await db.execute(database, f"COMMENT ON TABLE {o}.{t} IS {_sql_literal(text)}")
    except Exception as exc:
        logger.warning("table comment DDL failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t}


@router.put("/{owner}/{table}/columns/{column}/comment")
async def update_column_comment(
    owner: str, table: str, column: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    c = _ident(column, "column")
    text = body.get("text") or ""
    try:
        await db.execute(database, f"COMMENT ON COLUMN {o}.{t}.{c} IS {_sql_literal(text)}")
    except Exception as exc:
        logger.warning("column comment DDL failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t, "column": c}


@router.put("/{owner}/{table}/annotation")
async def update_table_annotation(
    owner: str, table: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    an = _annot_name(body.get("name", ""))
    av = body.get("value", "") or ""
    if not isinstance(av, str):
        av = str(av)
    av_esc = av.replace("'", "''")
    sql = f"ALTER TABLE {o}.{t} ANNOTATIONS (ADD OR REPLACE {an} '{av_esc}')"
    try:
        await db.execute(database, sql)
    except Exception as exc:
        logger.warning("table annotation DDL failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t, "name": an}


@router.put("/{owner}/{table}/columns/{column}/annotation")
async def update_column_annotation(
    owner: str, table: str, column: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    c = _ident(column, "column")
    an = _annot_name(body.get("name", ""))
    av = body.get("value", "") or ""
    if not isinstance(av, str):
        av = str(av)
    av_esc = av.replace("'", "''")
    sql = f"ALTER TABLE {o}.{t} MODIFY ({c} ANNOTATIONS (ADD OR REPLACE {an} '{av_esc}'))"
    try:
        await db.execute(database, sql)
    except Exception as exc:
        logger.warning("column annotation DDL failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t, "column": c, "name": an}


# === Annotation 삭제 ===

@router.delete("/{owner}/{table}/annotation/{annotation_name}")
async def delete_table_annotation(
    owner: str, table: str, annotation_name: str,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    an = _annot_name(annotation_name)
    try:
        await db.execute(database, f"ALTER TABLE {o}.{t} ANNOTATIONS (DROP {an})")
    except Exception as exc:
        logger.warning("table annotation DROP failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t, "name": an}


@router.delete("/{owner}/{table}/columns/{column}/annotation/{annotation_name}")
async def delete_column_annotation(
    owner: str, table: str, column: str, annotation_name: str,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    c = _ident(column, "column")
    an = _annot_name(annotation_name)
    try:
        await db.execute(
            database,
            f"ALTER TABLE {o}.{t} MODIFY ({c} ANNOTATIONS (DROP {an}))",
        )
    except Exception as exc:
        logger.warning("column annotation DROP failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})
    return {"ok": True, "owner": o, "table": t, "column": c, "name": an}


# === AI 코멘트 추천 (SELECT AI chat mode) ===
# 해당 컬럼의 실제 데이터 100행을 샘플링해 LLM 에게 컬럼 코멘트를 추천받는다.
# DBMS_CLOUD_AI.GENERATE(action => 'chat') — 선택된 Profile 의 model 로 호출.

_SUGGEST_SAMPLE_LIMIT = 100      # 샘플링 행 수
_SUGGEST_VALUE_MAXLEN = 200      # 값 1건 최대 길이(프롬프트 비대화 방지)
_SUGGEST_SAMPLES_MAXLEN = 4000   # 샘플 블록 전체 최대 길이
_SUGGEST_CATEGORICAL_MAX = 20    # 샘플 내 구분값이 이 수 이하이면 범주형(코드/플래그)으로 보고 열거
_GENERATE_CHAT_SQL = (
    "SELECT DBMS_CLOUD_AI.GENERATE(prompt => :p, profile_name => :pn, action => 'chat') AS r "
    "FROM dual"
)


def _stringify_sample(v) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > _SUGGEST_VALUE_MAXLEN:
        s = s[:_SUGGEST_VALUE_MAXLEN] + "…"
    return s


@router.post("/{owner}/{table}/columns/{column}/suggest-comment")
async def suggest_column_comment(
    owner: str, table: str, column: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    c = _ident(column, "column")
    profile_name = (body.get("profile_name") or "").strip()
    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "profile_name required"})

    # 1. 데이터 타입 + 참고 컨텍스트(테이블 코멘트 / 다른 컬럼 코멘트) — 없어도 진행
    dtype = ""
    table_comment = ""
    other_comments: list[str] = []
    try:
        dt_rows = await db.fetch_all(
            database,
            "SELECT data_type FROM ALL_TAB_COLUMNS "
            "WHERE UPPER(owner) = :o AND UPPER(table_name) = :t AND UPPER(column_name) = :c",
            o=o, t=t, c=c,
        )
        if dt_rows:
            dtype = dt_rows[0].get("data_type") or ""
    except Exception as e:
        logger.warning("suggest: data_type query failed: %s", _first_line(e))

    try:
        tc_rows = await db.fetch_all(
            database,
            "SELECT comments FROM ALL_TAB_COMMENTS "
            "WHERE UPPER(owner) = :o AND UPPER(table_name) = :t",
            o=o, t=t,
        )
        if tc_rows:
            table_comment = (tc_rows[0].get("comments") or "").strip()
    except Exception as e:
        logger.warning("suggest: table comment query failed: %s", _first_line(e))

    try:
        # 추천 대상 컬럼(c)을 제외한, 코멘트가 있는 다른 컬럼들 — 의미 추론의 참고 맥락
        cc_rows = await db.fetch_all(
            database,
            "SELECT column_name, comments FROM ALL_COL_COMMENTS "
            "WHERE UPPER(owner) = :o AND UPPER(table_name) = :t "
            "  AND UPPER(column_name) <> :c AND comments IS NOT NULL "
            "ORDER BY column_name",
            o=o, t=t, c=c,
        )
        for r in cc_rows:
            cn = r.get("column_name") or ""
            cm = (r.get("comments") or "").strip()
            if cn and cm:
                other_comments.append(f"- {cn}: {cm}")
    except Exception as e:
        logger.warning("suggest: column comments query failed: %s", _first_line(e))

    # 2. 컬럼 데이터 100행 샘플링 (식별자는 whitelist 검증 후 직접 보간)
    try:
        sample_rows = await db.fetch_all(
            database,
            f"SELECT {c} AS v FROM {o}.{t} "
            f"WHERE {c} IS NOT NULL "
            f"FETCH FIRST {_SUGGEST_SAMPLE_LIMIT} ROWS ONLY",
        )
    except Exception as exc:
        logger.warning("suggest: sample query failed: %s", _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})

    samples: list[str] = []
    used = 0
    for r in sample_rows:
        s = _stringify_sample(r.get("v"))
        if not s:
            continue
        if used + len(s) + 1 > _SUGGEST_SAMPLES_MAXLEN:
            break
        samples.append(s)
        used += len(s) + 1

    sample_block = "\n".join(f"- {s}" for s in samples) if samples else "(데이터 없음)"
    dtype_txt = f" (데이터 타입: {dtype})" if dtype else ""

    # 샘플 기준 구분값(distinct) — 코드/플래그처럼 소수의 값으로 이루어진 범주형 컬럼이면
    # 어떤 구분값들이 있는지 프롬프트에 열거해, 각 값의 의미를 코멘트에 설명하도록 유도한다.
    # (별도 DB 쿼리 없이 이미 가져온 샘플에서 계산 — LOB GROUP BY 제약·추가 부하 회피)
    distinct_seen: list[str] = []
    _seen: set[str] = set()
    for r in sample_rows:
        s = _stringify_sample(r.get("v"))
        if s == "" or s in _seen:
            continue
        _seen.add(s)
        distinct_seen.append(s)
    is_categorical = 0 < len(distinct_seen) <= _SUGGEST_CATEGORICAL_MAX
    distinct_block = ""
    category_hint = ""
    if is_categorical:
        distinct_block = (
            f"\n\n샘플에서 관찰된 구분값({len(distinct_seen)}종): "
            + ", ".join(distinct_seen)
        )
        category_hint = (
            "이 컬럼은 소수의 구분값으로 이루어진 범주형(코드/플래그) 컬럼으로 보입니다. "
            "위 '구분값' 각각이 무엇을 의미하는지 코멘트에 간단히 설명해 주세요 "
            "(예: '회원 데이터 미보유 여부, 1=미보유(비대상), 0=보유(대상)').\n"
        )

    # 날짜/시간 타입이면 데이터 형식(format)을 코멘트에 포함하도록 지시
    _du = dtype.upper()
    is_datetime = _du.startswith("DATE") or _du.startswith("TIMESTAMP")
    date_hint = (
        "이 컬럼은 날짜/시간 타입입니다. 샘플 값의 형태에 맞는 날짜 포맷을 Oracle 날짜 형식 모델로 "
        "표기해 코멘트 끝에 'format=<형식>' 형태로 포함해 주세요 "
        "(예: format=YYYYMMDD 또는 format=YYYY-MM-DD HH24:MI:SS 또는 format=YYYY-MM-DD, HH12:MI:SS).\n"
        if is_datetime else ""
    )

    # 참고 컨텍스트 — 테이블 코멘트 + 다른 컬럼 코멘트(있을 때만 프롬프트에 포함)
    context_parts: list[str] = []
    if table_comment:
        context_parts.append(f"테이블 설명: {table_comment}")
    if other_comments:
        # 컨텍스트 비대화 방지를 위해 총량 제한
        joined = "\n".join(other_comments)
        if len(joined) > _SUGGEST_SAMPLES_MAXLEN:
            joined = joined[:_SUGGEST_SAMPLES_MAXLEN] + "\n…"
        context_parts.append("같은 테이블의 다른 컬럼 코멘트:\n" + joined)
    context_block = ("\n\n참고 컨텍스트:\n" + "\n".join(context_parts)) if context_parts else ""

    prompt = (
        f'다음은 Oracle 테이블 {o}.{t} 의 컬럼 "{c}"{dtype_txt} 에 저장된 실제 데이터 샘플 '
        f"{len(samples)}건입니다.\n"
        "아래 '샘플 데이터' 의 실제 값을 1차 근거로, 참고 컨텍스트(테이블 설명·다른 컬럼 코멘트)를 "
        "보조 근거로 삼아 해당 컬럼의 의미를 새로 추론해 간결한 한국어 코멘트(한 문장)를 제안해 주세요.\n"
        f'참고 컨텍스트에는 컬럼 "{c}" 자신의 기존 코멘트가 포함되어 있지 않으며, 기존 코멘트를 그대로 '
        "베끼지 말고 데이터에서 의미를 직접 도출하세요.\n"
        "샘플은 전체 데이터의 일부이므로, 값의 범위(최소·최대·건수·분포 등)에 대한 설명은 "
        "코멘트에 넣지 마세요.\n"
        f"{date_hint}"
        f"{category_hint}"
        "코멘트 문장만 출력하고, 따옴표나 'AI:' 같은 접두어·부가 설명은 붙이지 마세요.\n"
        f"{context_block}\n\n"
        f"샘플 데이터:\n{sample_block}"
        f"{distinct_block}"
    )

    # 3. SELECT AI chat mode 호출
    try:
        row = await db.fetch_one(database, _GENERATE_CHAT_SQL, p=prompt, pn=profile_name)
    except Exception as exc:
        logger.warning("suggest: GENERATE(chat) failed: db=%s profile=%s: %s",
                       database, profile_name, _first_line(exc))
        raise HTTPException(status_code=400, detail={"error": _first_line(exc)})

    suggestion = ((row or {}).get("r") or "").strip()
    # LLM 이 종종 양끝에 따옴표를 붙임 — 제거
    if len(suggestion) >= 2 and suggestion[0] in "\"'" and suggestion[-1] == suggestion[0]:
        suggestion = suggestion[1:-1].strip()

    return {
        "owner": o, "table": t, "column": c,
        "profile_name": profile_name,
        "sample_count": len(samples),
        "suggestion": suggestion,
    }


# === 컬럼 메타데이터 일괄 저장 ===
# 동일 connection 으로 순차 실행. Oracle DDL 은 auto-commit 이므로 실패시 이전 DDL 은 유지된다 —
# 응답에 어디서 멈췄는지(failed_column) 명시.

@router.post("/{owner}/{table}/columns/bulk")
async def bulk_update_columns(
    owner: str, table: str, body: dict,
    database: str = Depends(current_db),
) -> dict:
    o = _ident(owner, "owner")
    t = _ident(table, "table")
    cols = body.get("columns") or []
    if not isinstance(cols, list) or not cols:
        raise HTTPException(status_code=400, detail={"error": "columns required"})

    pool = db.get_pool(database)
    updated = 0
    failed_column: str | None = None
    failed_kind: str | None = None
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            for item in cols:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                try:
                    c = _ident(name, "column")
                except HTTPException as e:
                    failed_column = str(name)
                    failed_kind = "validate"
                    raise HTTPException(
                        status_code=400,
                        detail={"error": e.detail.get("error", "invalid column"),
                                "failed_column": failed_column, "updated": updated},
                    )

                if "comment" in item:
                    txt = item.get("comment") or ""
                    try:
                        await cur.execute(
                            f"COMMENT ON COLUMN {o}.{t}.{c} IS {_sql_literal(txt)}",
                        )
                        updated += 1
                    except Exception as exc:
                        failed_column = name
                        failed_kind = "comment"
                        raise HTTPException(
                            status_code=400,
                            detail={"error": _first_line(exc),
                                    "failed_column": failed_column,
                                    "failed_kind": failed_kind,
                                    "updated": updated},
                        )

                ann = item.get("annotation")
                if ann and isinstance(ann, dict):
                    try:
                        an = _annot_name(ann.get("name", ""))
                    except HTTPException as e:
                        failed_column = name
                        failed_kind = "annotation"
                        raise HTTPException(
                            status_code=400,
                            detail={"error": e.detail.get("error", "invalid annotation"),
                                    "failed_column": failed_column,
                                    "failed_kind": failed_kind,
                                    "updated": updated},
                        )
                    av = ann.get("value", "") or ""
                    if not isinstance(av, str):
                        av = str(av)
                    av_esc = av.replace("'", "''")
                    sql = f"ALTER TABLE {o}.{t} MODIFY ({c} ANNOTATIONS (ADD OR REPLACE {an} '{av_esc}'))"
                    try:
                        await cur.execute(sql)
                        updated += 1
                    except Exception as exc:
                        failed_column = name
                        failed_kind = "annotation"
                        raise HTTPException(
                            status_code=400,
                            detail={"error": _first_line(exc),
                                    "failed_column": failed_column,
                                    "failed_kind": failed_kind,
                                    "updated": updated},
                        )
    return {"ok": True, "owner": o, "table": t, "updated": updated}
