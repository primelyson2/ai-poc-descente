"""기능요구사항01 (메뉴 [2] AI Profile Test) — 실제 ADB 호출.

- /profiles, /profiles/{name}/attributes : USER_CLOUD_AI_PROFILES, USER_CLOUD_AI_PROFILE_ATTRIBUTES
- /profiles/benchmark : DBMS_CLOUD_AI.GENERATE 를 profile_name × iterations 로 반복 호출
- /profiles/{name}/objects : 메뉴 [1] (Object Meta) 용 stub — Step 4 에서 교체
"""
from __future__ import annotations

import array
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

import json

from app import db
from app.deps import current_db
from app.plsql import first_line

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profiles"])

_DATA_DIR = Path(__file__).resolve().parent.parent.parent
# region 드롭다운 후보 — project/regions.txt (한 줄 1개, '#' 주석/빈 줄 무시)
REGIONS_FILE = _DATA_DIR / "regions.txt"
# region 별 model 후보 — models.txt ('#region' 섹션 헤더 + 모델 줄).
# 환경별 파일이라 gitignore 대상. 없으면 추적되는 템플릿(models.txt.example)으로 폴백.
MODELS_FILE = _DATA_DIR / "models.txt"
MODELS_EXAMPLE_FILE = _DATA_DIR / "models.txt.example"


def _models_file() -> Path:
    return MODELS_FILE if MODELS_FILE.exists() else MODELS_EXAMPLE_FILE


@router.get("/regions")
async def list_regions() -> list[str]:
    try:
        lines = REGIONS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("regions.txt 읽기 실패: %s", exc)
        return []
    seen: list[str] = []
    for line in lines:
        r = line.strip()
        if not r or r.startswith("#") or r in seen:
            continue
        seen.append(r)
    return seen


@router.get("/models")
async def list_models() -> dict[str, list[str]]:
    """region -> 사용 가능한 model 목록. '#region' 헤더로 섹션을 구분한다.
    실제 파일(models.txt)이 없으면 템플릿(models.txt.example)으로 폴백한다."""
    try:
        lines = _models_file().read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("models.txt 읽기 실패: %s", exc)
        return {}
    result: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            body = s[1:]
            # '#region' = 섹션 헤더 / '# 주석' · '##' = 주석(섹션 영향 없음)
            if body and not body[0].isspace() and not body.startswith("#"):
                current = result.setdefault(body.strip(), [])
            continue
        if current is not None and s not in current:
            current.append(s)
    return result


@router.get("/profiles")
async def list_profiles(database: str = Depends(current_db)) -> list[dict]:
    # has_object_list: USER_CLOUD_AI_PROFILE_ATTRIBUTES 에 object_list 행이 있으면 'Y'
    return await db.fetch_all(
        database,
        "SELECT p.profile_name, p.status, p.description, "
        "       CASE WHEN EXISTS ( "
        "         SELECT 1 FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES a "
        "          WHERE a.profile_name = p.profile_name "
        "            AND a.attribute_name = 'object_list' "
        "       ) THEN 'Y' ELSE 'N' END AS has_object_list "
        "  FROM USER_CLOUD_AI_PROFILES p "
        " ORDER BY p.profile_name",
    )


@router.get("/profiles/{name}/attributes")
async def profile_attributes(name: str, database: str = Depends(current_db)) -> list[dict]:
    return await db.fetch_all(
        database,
        "SELECT attribute_name, attribute_value "
        "FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES "
        "WHERE profile_name = :name "
        "ORDER BY attribute_name",
        name=name,
    )


@router.put("/profiles/{name}/attributes/{attribute_name}")
async def set_profile_attribute(
    name: str,
    attribute_name: str,
    payload: dict,
    database: str = Depends(current_db),
) -> dict:
    value = payload.get("value", "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    try:
        await db.execute(
            database,
            "BEGIN DBMS_CLOUD_AI.SET_ATTRIBUTE("
            "profile_name => :pn, "
            "attribute_name => :an, "
            "attribute_value => :av); END;",
            pn=name,
            an=attribute_name,
            av=value,
        )
    except Exception as exc:
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "execution failed"
        logger.warning("SET_ATTRIBUTE failed: db=%s profile=%s attr=%s: %s",
                       database, name, attribute_name, msg)
        raise HTTPException(status_code=400, detail={"error": msg})
    return {"ok": True, "profile_name": name, "attribute_name": attribute_name}


_GENERATE_SQL = (
    "SELECT DBMS_CLOUD_AI.GENERATE(prompt => :p, profile_name => :pn, action => :a) AS r "
    "FROM dual"
)
_SET_MODEL_SQL = (
    "BEGIN DBMS_CLOUD_AI.SET_ATTRIBUTE("
    "profile_name => :pn, attribute_name => 'model', attribute_value => :av); END;"
)


async def _run_iterations(database: str, prompt: str, profile_name: str,
                          action: str, iterations: int) -> list[dict]:
    """한 Profile 에 대해 iterations 회 GENERATE 를 호출하고 회차별 측정값을 반환."""
    runs: list[dict] = []
    for i in range(1, iterations + 1):
        # 회차 번호만큼 '.' 을 prompt 끝에 추가 — LLM/캐시 동일 입력 제거용
        prompt_i = prompt + ("." * i)
        t0 = time.perf_counter()
        try:
            row = await db.fetch_one(database, _GENERATE_SQL, p=prompt_i, pn=profile_name, a=action)
            t1 = time.perf_counter()
            runs.append({
                "iteration": i,
                "elapsed_ms": int((t1 - t0) * 1000),
                "response": (row or {}).get("r") or "",
                "error": None,
            })
        except Exception as exc:
            t1 = time.perf_counter()
            msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "execution failed"
            logger.warning("benchmark cell failed: db=%s profile=%s iter=%d: %s",
                           database, profile_name, i, msg)
            runs.append({
                "iteration": i,
                "elapsed_ms": int((t1 - t0) * 1000),
                "response": "",
                "error": msg,
            })
    return runs


def _summarize(runs: list[dict], **extra) -> dict:
    ok = [r["elapsed_ms"] for r in runs if r["error"] is None]
    return {
        **extra,
        "runs": runs,
        "avg_ms": int(sum(ok) / len(ok)) if ok else None,
        "min_ms": min(ok) if ok else None,
        "max_ms": max(ok) if ok else None,
    }


@router.post("/profiles/benchmark")
async def benchmark(payload: dict, database: str = Depends(current_db)) -> dict:
    prompt = (payload.get("prompt") or "").strip()
    action = (payload.get("action") or "chat").strip()
    iterations = max(1, min(int(payload.get("iterations") or 1), 10))
    if not prompt:
        raise HTTPException(status_code=400, detail={"error": "prompt required"})

    profile_name = (payload.get("profile_name") or "").strip()
    models = [m for m in (payload.get("models") or []) if m]

    # 모델 비교 모드 — 단일 Profile 의 model 속성을 선택한 모델로 바꿔가며 측정
    if profile_name and models:
        # 측정 종료 후 복원할 원래 model 백업
        orig_rows = await db.fetch_all(
            database,
            "SELECT attribute_value FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES "
            "WHERE profile_name = :n AND attribute_name = 'model'",
            n=profile_name,
        )
        orig_model = orig_rows[0].get("attribute_value") if orig_rows else None

        results: list[dict] = []
        try:
            for model in models:
                try:
                    await db.execute(database, _SET_MODEL_SQL, pn=profile_name, av=model)
                except Exception as exc:
                    # model 변경 자체가 실패하면 해당 모델의 모든 회차를 오류로 기록하고 계속
                    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "set model failed"
                    logger.warning("benchmark set model failed: db=%s profile=%s model=%s: %s",
                                   database, profile_name, model, msg)
                    runs = [{"iteration": i, "elapsed_ms": 0, "response": "", "error": msg}
                            for i in range(1, iterations + 1)]
                    results.append(_summarize(runs, profile_name=profile_name, model=model))
                    continue
                runs = await _run_iterations(database, prompt, profile_name, action, iterations)
                results.append(_summarize(runs, profile_name=profile_name, model=model))
        finally:
            # 원래 model 로 복원 (실패해도 측정 결과는 반환)
            if orig_model is not None:
                try:
                    await db.execute(database, _SET_MODEL_SQL, pn=profile_name, av=orig_model)
                except Exception as exc:
                    logger.error("benchmark restore model failed: db=%s profile=%s model=%s: %s",
                                 database, profile_name, orig_model, exc)
        return {"iterations": iterations, "profile_name": profile_name,
                "restored_model": orig_model, "results": results}

    # 기존 모드 — 여러 Profile 을 그대로 비교 (개별 Profile 테스트 모달이 사용)
    profile_names = payload.get("profile_names") or []
    if not profile_names:
        raise HTTPException(status_code=400, detail={"error": "profile_name+models or profile_names required"})
    results = []
    for pn in profile_names:
        runs = await _run_iterations(database, prompt, pn, action, iterations)
        results.append(_summarize(runs, profile_name=pn))
    return {"iterations": iterations, "results": results}


# --- Profile 평가 (메뉴 [2] 탭 3) — showsql 로 생성된 SQL 을 평가수행 Profile 이 적정/비적정 판정 ---
def _clean_sql(raw: str) -> str:
    """showsql 반환값 정리 — 마크다운 펜스/후행 세미콜론·공백 제거.
    (nl2sql._clean_sql 와 동일 로직 — profiles→nl2sql 역참조는 순환 import 라 로컬 복제.)"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s[:3].lower() == "sql":
            s = s[3:].lstrip()
    return s.rstrip().rstrip(";").rstrip()


def _parse_verdict(raw: str) -> tuple[str, str]:
    """평가수행 chat 응답 → (verdict, reason).
    1) 마크다운 펜스 제거 후 JSON({"verdict","reason"}) 파싱 시도.
    2) 실패 시 본문에서 '비적정'/'적정' 부분문자열 탐색.
    3) 그래도 없으면 ('판정불가', 원문 앞부분)."""
    s = (raw or "").strip()
    body = re.sub(r"```[a-zA-Z]*|```", "", s).strip()
    try:
        obj = json.loads(body)
        if isinstance(obj, dict):
            v = str(obj.get("verdict") or "").strip()
            reason = str(obj.get("reason") or "").strip()
            verdict = "적정" if v == "적정" else "비적정" if v == "비적정" else ""
            if verdict:
                return verdict, reason or body
    except Exception:
        pass
    if "비적정" in body:
        return "비적정", body
    if "적정" in body:
        return "적정", body
    return "판정불가", body[:500] if body else "평가 응답이 비어 있습니다"


@router.post("/profiles/evaluate")
async def evaluate(payload: dict, database: str = Depends(current_db)) -> dict:
    """평가대상 Profile 이 질의를 변환한 SQL(showsql)을, 평가수행 Profile 이 적정/비적정으로 판정.

    흐름: target model 설정(원본 백업) → showprompt 1회 → N회 [showsql → 평가 chat] → model 원복.
    """
    question = (payload.get("question") or "").strip()
    target_profile = (payload.get("target_profile") or "").strip()
    target_model = (payload.get("target_model") or "").strip()
    judge_profile = (payload.get("evaluator_profile") or payload.get("judge_profile") or "").strip()
    iterations = max(1, min(int(payload.get("iterations") or 1), 10))
    if not question:
        raise HTTPException(status_code=400, detail={"error": "question required"})
    if not target_profile:
        raise HTTPException(status_code=400, detail={"error": "target_profile required"})
    if not judge_profile:
        raise HTTPException(status_code=400, detail={"error": "evaluator_profile required"})

    # 측정 종료 후 복원할 원래 model 백업
    orig_rows = await db.fetch_all(
        database,
        "SELECT attribute_value FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES "
        "WHERE profile_name = :n AND attribute_name = 'model'",
        n=target_profile,
    )
    orig_model = orig_rows[0].get("attribute_value") if orig_rows else None

    prompt_text = ""
    results: list[dict] = []
    try:
        # 평가대상 model 을 선택 모델로 변경 (지정된 경우)
        if target_model:
            await db.execute(database, _SET_MODEL_SQL, pn=target_profile, av=target_model)

        # showprompt 1회 — 스키마 컨텍스트가 포함된 구성 프롬프트 (Question 부분에 사용자 질의 포함)
        try:
            row = await db.fetch_one(database, _GENERATE_SQL, p=question, pn=target_profile, a="showprompt")
            prompt_text = (row or {}).get("r") or ""
        except Exception as exc:
            prompt_text = ""
            logger.warning("evaluate showprompt failed: db=%s profile=%s: %s",
                           database, target_profile, first_line(exc))

        for i in range(1, iterations + 1):
            # showsql — 회차마다 '.' 누적으로 동일 질의 캐싱 무력화 (프런트의 누적 '.' 위에 추가)
            showsql_prompt = question + ("." * i)
            entry = {
                "iteration": i,
                "showsql_prompt": showsql_prompt,   # 1단계: 평가대상에 전달한 프롬프트
                "sql": "",                            # 1단계 응답(생성 SQL)
                "showsql_ms": None,                   # 1단계 showsql 생성 소요시간(ms)
                "eval_prompt": "",                    # 2단계: 평가수행에 전달한 프롬프트
                "eval_response": "",                  # 2단계 응답(LLM 원문)
                "verdict": "오류", "reason": "", "error": None,
            }
            # 1) showsql 로 SQL 생성 (생성시간 측정)
            t0 = time.perf_counter()
            try:
                row = await db.fetch_one(
                    database, _GENERATE_SQL, p=showsql_prompt, pn=target_profile, a="showsql")
                entry["showsql_ms"] = int((time.perf_counter() - t0) * 1000)
                entry["sql"] = _clean_sql((row or {}).get("r") or "")
            except Exception as exc:
                entry["showsql_ms"] = int((time.perf_counter() - t0) * 1000)
                entry["error"] = first_line(exc)
                entry["reason"] = "showsql 생성 실패"
                results.append(entry)
                continue
            if not entry["sql"]:
                entry["verdict"] = "판정불가"
                entry["reason"] = "모델이 SQL 을 생성하지 못했습니다 (빈 응답)"
                results.append(entry)
                continue
            # 2) 평가수행 Profile chat 으로 적정/비적정 판정
            eval_prompt = (
                "당신은 Oracle SQL 품질 심사관입니다. 아래 [프롬프트]는 자연어 질문과 스키마 컨텍스트이고, "
                "[생성SQL]은 그에 대해 생성된 SQL 입니다.\n"
                "[프롬프트]\n" + (prompt_text or question) + "\n"
                "[생성SQL]\n" + entry["sql"] + "\n"
                "생성SQL 이 질문 의도와 스키마에 비추어 적절한지 평가하세요. "
                "반드시 JSON 만 응답: {\"verdict\":\"적정\"|\"비적정\",\"reason\":\"한국어 사유\"}"
            )
            entry["eval_prompt"] = eval_prompt
            try:
                row = await db.fetch_one(database, _GENERATE_SQL, p=eval_prompt, pn=judge_profile, a="chat")
                eval_raw = (row or {}).get("r") or ""
                entry["eval_response"] = eval_raw
                verdict, reason = _parse_verdict(eval_raw)
                entry["verdict"] = verdict
                entry["reason"] = reason
            except Exception as exc:
                entry["error"] = first_line(exc)
                entry["verdict"] = "오류"
                entry["reason"] = "평가 호출 실패"
            results.append(entry)
    finally:
        # 원래 model 로 복원 (실패해도 결과는 반환)
        if target_model and orig_model is not None:
            try:
                await db.execute(database, _SET_MODEL_SQL, pn=target_profile, av=orig_model)
            except Exception as exc:
                logger.error("evaluate restore model failed: db=%s profile=%s model=%s: %s",
                             database, target_profile, orig_model, exc)

    summary = {
        "appropriate": sum(1 for r in results if r["verdict"] == "적정"),
        "inappropriate": sum(1 for r in results if r["verdict"] == "비적정"),
        "unknown": sum(1 for r in results if r["verdict"] == "판정불가"),
        "error": sum(1 for r in results if r["verdict"] == "오류"),
    }
    return {
        "target_profile": target_profile,
        "target_model": target_model,
        "restored_model": orig_model,
        "evaluator_profile": judge_profile,
        "iterations": iterations,
        "question": question,
        "prompt_text": prompt_text,
        "summary": summary,
        "results": results,
    }


# --- 메뉴 [1] (Object Meta) — Profile 의 object_list + 각 테이블 코멘트 요약 ---
@router.get("/profiles/{name}/objects")
async def profile_objects(name: str, database: str = Depends(current_db)) -> list[dict]:
    rows = await db.fetch_all(
        database,
        "SELECT attribute_value FROM USER_CLOUD_AI_PROFILE_ATTRIBUTES "
        "WHERE profile_name = :name AND attribute_name = 'object_list'",
        name=name,
    )
    if not rows:
        return []
    raw = rows[0].get("attribute_value") or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError as e:
        logger.warning("object_list JSON parse failed for profile=%s: %s", name, e)
        return []
    if not isinstance(items, list) or not items:
        return []

    # (owner, table) 쌍을 한 번에 JOIN — N+1 방지
    # FROM JSON_TABLE 로 클라이언트 owner/name 쌍과 ALL_TAB_COMMENTS 조인
    payload_json = json.dumps(items)
    sql = (
        "SELECT j.owner, j.name AS table_name, c.comments, c.table_type "
        "  FROM JSON_TABLE(:payload, '$[*]' "
        "         COLUMNS (owner VARCHAR2(128) PATH '$.owner', "
        "                  name  VARCHAR2(128) PATH '$.name')) j "
        "  LEFT JOIN ALL_TAB_COMMENTS c "
        "    ON UPPER(c.owner) = UPPER(j.owner) "
        "   AND UPPER(c.table_name) = UPPER(j.name)"
    )
    joined = await db.fetch_all(database, sql, payload=payload_json)
    return [
        {
            "owner": r.get("owner"),
            "table": r.get("table_name"),
            # ALL_TAB_COMMENTS.TABLE_TYPE = 'TABLE' | 'VIEW' (존재/권한 없으면 NULL→"")
            "object_type": (r.get("table_type") or "").strip(),
            "table_comment": r.get("comments") or "",
        }
        for r in joined
    ]


# ====================================================================
# 메뉴 [2] Tab 3 — SELECT AI Feedback 관리
#   - GET  /profiles/{name}/feedback/vectab  : <PROFILE>_FEEDBACK_VECINDEX$VECTAB 조회 (display only)
#   - GET  /profiles/feedback/mapped-sql     : v$mapped_sql (NL2SQL 실행 내역 + sql_id)
#   - POST /profiles/{name}/feedback         : DBMS_CLOUD_AI.FEEDBACK 실행 (sql_id / sql_text 모드)
# ====================================================================

_VECTAB_SUFFIX = "_FEEDBACK_VECINDEX$VECTAB"
# Oracle 식별자 화이트리스트 — vectab 명에는 '$' 가 포함되므로 허용.
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
_FEEDBACK_TYPES = {"positive", "negative"}
_FEEDBACK_OPS = {"add", "delete"}


def _first_line(exc: Exception) -> str:
    s = str(exc).strip()
    return s.splitlines()[0] if s else "execution failed"


def _normalize_cell(v):
    """vectab 값 표시용 정규화 — VECTOR(array)/datetime/dict 등을 JSON 직렬화 가능한 형태로."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # 23ai VECTOR 는 thin mode 에서 array.array 로 들어온다 — 앞 8개 차원만 미리보기.
    if isinstance(v, array.array):
        v = list(v)
    if isinstance(v, (list, tuple)):
        head = ", ".join(str(x) for x in v[:8])
        more = f", … ({len(v)} dims)" if len(v) > 8 else ""
        return f"[{head}{more}]"
    if isinstance(v, dict):
        try:
            return json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(v)
    return str(v)


# attributes(JSON) 를 펼쳐 보여줄 키 순서. feedback vector table 의 attributes 컬럼은
# {"response","feedback_type","sql_id","sql_text","feedback_content"} 형태의 JSON.
_ATTR_KEYS = ["response", "feedback_type", "sql_id", "sql_text", "feedback_content"]
# 표시에서 제외할 컬럼(고차원 VECTOR — 화면에 의미 없음).
_HIDE_COLS = {"embedding"}


@router.get("/profiles/{name}/feedback/vectab")
async def feedback_vectab(name: str, database: str = Depends(current_db)) -> dict:
    """선택한 Profile 의 Feedback Vector Table 내용을 조회 (display only).

    규칙: 테이블명 = '<PROFILE_NAME>_FEEDBACK_VECINDEX$VECTAB'.
    테이블이 없으면 exists=False 만 돌려주고 row 는 조회하지 않는다.
    """
    table_name = f"{name}{_VECTAB_SUFFIX}"
    # 존재 확인 — 실제 저장된 table_name(대소문자) 을 받아 후속 조회에 사용
    found = await db.fetch_all(
        database,
        "SELECT table_name FROM user_tables WHERE UPPER(table_name) = UPPER(:t)",
        t=table_name,
    )
    if not found:
        return {"table_name": table_name, "exists": False, "columns": [], "rows": []}

    actual = found[0]["table_name"]
    if not _IDENT_RE.match(actual):
        # 화이트리스트 위반(정상 경로에선 발생하지 않음) — 보간 금지
        return {"table_name": actual, "exists": True, "columns": [], "rows": []}

    # 표시 컬럼 구성: embedding(VECTOR) 은 제외하고, attributes(JSON) 는 JSON_TABLE 로
    # 키별 컬럼으로 펼친다. 식별자는 user_tab_columns 메타 + 화이트리스트 검증 후 직접 보간
    # (thin DDL/bind 제약 회피와 동일 원칙).
    cols_meta = await db.fetch_all(
        database,
        "SELECT column_name FROM user_tab_columns "
        "WHERE table_name = :t ORDER BY column_id",
        t=actual,
    )

    select_parts: list[str] = []   # SQL SELECT 식
    display_cols: list[str] = []   # 화면 컬럼 순서(소문자 키)
    has_attr = False
    for c in cols_meta:
        col = c["column_name"]
        low = col.lower()
        if low in _HIDE_COLS:
            continue
        if low == "attributes":
            has_attr = True
            display_cols.extend(_ATTR_KEYS)  # attributes 자리에 펼친 키를 배치
            continue
        if not _IDENT_RE.match(col):
            continue
        select_parts.append(f't."{col}"')
        display_cols.append(low)

    from_clause = f'"{actual}" t'
    if has_attr:
        # JSON_TABLE 로 attributes JSON 을 스칼라 컬럼으로 추출. 컬럼 별칭은 _ATTR_KEYS 와 동일.
        jt_cols = ",\n            ".join(
            f"{k} VARCHAR2(4000) PATH '$.{k}'" for k in _ATTR_KEYS
        )
        select_parts.extend(f"jt.{k}" for k in _ATTR_KEYS)
        from_clause += (
            f", JSON_TABLE(t.\"ATTRIBUTES\", '$'\n"
            f"          COLUMNS (\n            {jt_cols}\n          )) jt"
        )

    if not select_parts:
        return {"table_name": actual, "exists": True, "columns": display_cols, "rows": []}

    # 행 수가 많을 수 있어 상위 500행으로 제한.
    sql = (
        f"SELECT {', '.join(select_parts)}\n"
        f"FROM {from_clause}\n"
        f"FETCH FIRST 500 ROWS ONLY"
    )
    data = await db.fetch_all(database, sql)
    rows = [{k: _normalize_cell(v) for k, v in r.items()} for r in data]
    return {"table_name": actual, "exists": True, "columns": display_cols, "rows": rows}


@router.get("/profiles/feedback/mapped-sql")
async def feedback_mapped_sql(database: str = Depends(current_db)) -> list[dict]:
    """v$mapped_sql — SELECT AI NL2SQL 실행 내역(sql_id 확인용).

    조회 권한(GRANT READ ON SYS.V_$MAPPED_SQL)이 없으면 ORA 오류가 그대로 전파된다.
    """
    # SQL_FULLTEXT 가 'select ai' 로 '시작'하는 행만 노출(select ai 단축구문). GENERATE 호출은 제외.
    # 성능: 시작 키워드라 SQL_TEXT(VARCHAR2(1000)) 로 판정해도 SQL_FULLTEXT 시작과 동일하다
    #       (CLOB(SQL_FULLTEXT) 에 정규식을 걸면 전 행 materialize 되어 느림).
    #       표시용 sql_fulltext(CLOB) 는 매칭된 소수 행에만 fetch 된다.
    return await db.fetch_all(
        database,
        "SELECT sql_id, sql_fulltext, mapped_sql_text, use_count, "
        "       CAST(translation_timestamp AS TIMESTAMP) AS translation_timestamp "
        "  FROM v$mapped_sql "
        " WHERE REGEXP_LIKE(sql_text, '^[[:space:]]*select[[:space:]]+ai[[:space:]]', 'i') "
        " ORDER BY translation_timestamp DESC",
    )


@router.post("/profiles/{name}/feedback")
async def add_feedback(name: str, payload: dict, database: str = Depends(current_db)) -> dict:
    """DBMS_CLOUD_AI.FEEDBACK 실행.

    - sql_id 모드 : {sql_id, feedback_type, operation('add'|'delete')}
    - sql_text 모드: {sql_text, feedback_type, response}
    """
    feedback_type = (payload.get("feedback_type") or "").strip().lower()
    sql_id = (payload.get("sql_id") or "").strip()
    sql_text = (payload.get("sql_text") or "").strip()

    if sql_id:
        operation = (payload.get("operation") or "add").strip().lower()
        if operation not in _FEEDBACK_OPS:
            raise HTTPException(status_code=400, detail={"error": "operation must be add/delete"})
        # delete 는 feedback_type 불필요, add 는 필수
        if operation == "add" and feedback_type not in _FEEDBACK_TYPES:
            raise HTTPException(status_code=400, detail={"error": "feedback_type must be positive/negative"})
        try:
            if operation == "delete":
                await db.execute(
                    database,
                    "BEGIN DBMS_CLOUD_AI.FEEDBACK(profile_name => :pn, sql_id => :sid, "
                    "operation => 'delete'); END;",
                    pn=name, sid=sql_id,
                )
            else:
                await db.execute(
                    database,
                    "BEGIN DBMS_CLOUD_AI.FEEDBACK(profile_name => :pn, sql_id => :sid, "
                    "feedback_type => :ft, operation => 'add'); END;",
                    pn=name, sid=sql_id, ft=feedback_type,
                )
        except Exception as exc:
            msg = _first_line(exc)
            logger.warning("FEEDBACK(sql_id) failed: db=%s profile=%s sql_id=%s op=%s: %s",
                           database, name, sql_id, operation, msg)
            raise HTTPException(status_code=400, detail={"error": msg})
        return {"ok": True, "profile_name": name, "sql_id": sql_id, "operation": operation}

    if sql_text:
        if feedback_type not in _FEEDBACK_TYPES:
            raise HTTPException(status_code=400, detail={"error": "feedback_type must be positive/negative"})
        operation = (payload.get("operation") or "add").strip().lower()
        if operation not in _FEEDBACK_OPS:
            raise HTTPException(status_code=400, detail={"error": "operation must be add/delete"})
        response = payload.get("response") or ""
        feedback_content = payload.get("feedback_content") or ""
        # feedback_content 는 선택 — 값이 있을 때만 바인드/파라미터를 추가한다(빈 문자열을 굳이 넣지 않음).
        binds = {"pn": name, "st": sql_text, "ft": feedback_type, "resp": response, "op": operation}
        fc_clause = ""
        if feedback_content:
            fc_clause = ", feedback_content => :fc"
            binds["fc"] = feedback_content
        try:
            await db.execute(
                database,
                "BEGIN DBMS_CLOUD_AI.FEEDBACK(profile_name => :pn, sql_text => :st, "
                f"feedback_type => :ft, response => :resp{fc_clause}, operation => :op); END;",
                **binds,
            )
        except Exception as exc:
            msg = _first_line(exc)
            logger.warning("FEEDBACK(sql_text) failed: db=%s profile=%s op=%s: %s",
                           database, name, operation, msg)
            raise HTTPException(status_code=400, detail={"error": msg})
        return {"ok": True, "profile_name": name, "mode": "sql_text", "operation": operation}

    raise HTTPException(status_code=400, detail={"error": "sql_id or sql_text required"})
