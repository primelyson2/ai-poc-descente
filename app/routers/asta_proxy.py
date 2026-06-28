"""Thin ASTA ORDS proxy for OADT2.

Production ASTA execution belongs in ADB PL/SQL exposed through ORDS.
This router only normalizes the browser payload enough to call the configured
ORDS endpoints and passes JSON responses through without Python-side SQL
evidence, Vector, LLM, SQLTUNE, or report generation.

작성자: 도상훈
파일 용도: OADT2 UI와 ADB ORDS 기반 ASTA PL/SQL 런타임 사이를 연결하는 얇은 FastAPI 프록시이다."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urljoin
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app import asta_audit, db
from app.deps import current_db, get_config

router = APIRouter(prefix="/asta", tags=["asta"])

DEFAULT_LLM_PROFILE = "ASTA_GPT5_PROFILE"
DEFAULT_SOURCE_DB_ID = "DB0903_TESTDB"
DEFAULT_TIMEOUT_SECONDS = 2100
ASYNC_RUNS: dict[str, dict[str, Any]] = {}
ASYNC_LOCK = asyncio.Lock()


def _utc_now() -> str:
    """ASTA 내부 처리 보조 함수: utc now."""
    return datetime.now(timezone.utc).isoformat()


def _new_proxy_run_id() -> str:
    """ASTA 내부 처리 보조 함수: new proxy run id."""
    return f"OADT2-ASTA-{uuid.uuid4().hex}"


def _initial_progress(run_id: str) -> list[dict[str, Any]]:
    """ASTA 내부 처리 보조 함수: initial progress."""
    now = _utc_now()
    return [
        {"seq": 1, "code": "REQUEST_RECEIVED", "label": "OADT2 request received", "status": "DONE", "detail": "요청 수신", "started_at": now, "completed_at": now},
        {"seq": 2, "code": "ORDS_DISPATCH", "label": "ADB ORDS analyze call", "status": "RUNNING", "detail": "ADB ORDS/PLSQL 실행 중", "started_at": now},
        {"seq": 3, "code": "SQL_GUARD", "label": "ADB SQL guard", "status": "PENDING", "detail": "ADB progress 준비 중"},
        {"seq": 4, "code": "BEFORE_EVIDENCE", "label": "Source evidence via DB Link", "status": "PENDING"},
        {"seq": 5, "code": "SQL_TUNING_ADVISOR", "label": "SQL Tuning Advisor", "status": "PENDING"},
        {"seq": 6, "code": "VECTOR_KB", "label": "ADB Vector KB search", "status": "PENDING"},
        {"seq": 7, "code": "LLM_REWRITE", "label": "ADB AI tuning", "status": "PENDING"},
        {"seq": 8, "code": "AFTER_EVIDENCE", "label": "Tuned SQL evidence", "status": "PENDING"},
        {"seq": 9, "code": "LLM_FINAL_REVIEW", "label": "Before/After comparison", "status": "PENDING"},
        {"seq": 10, "code": "FINAL_REPORT", "label": "Final report synthesis", "status": "PENDING"},
        {"seq": 11, "code": "VECTOR_SAVE", "label": "ADB Vector KB save", "status": "PENDING"},
    ]


async def _store_async_run(run_id: str, record: dict[str, Any]) -> None:
    """ASTA 내부 처리 보조 함수: store async run."""
    async with ASYNC_LOCK:
        ASYNC_RUNS[run_id] = record


async def _get_async_run(run_id: str) -> dict[str, Any] | None:
    """ASTA 내부 처리 보조 함수: get async run."""
    async with ASYNC_LOCK:
        rec = ASYNC_RUNS.get(run_id)
        return dict(rec) if isinstance(rec, dict) else None


async def _complete_async_run(run_id: str, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
    """ASTA 내부 처리 보조 함수: complete async run."""
    async with ASYNC_LOCK:
        rec = ASYNC_RUNS.get(run_id) or {"run_id": run_id, "progress": _initial_progress(run_id), "created_at": _utc_now()}
        if result is not None:
            rec["status"] = result.get("status") or "COMPLETED"
            rec["result"] = result
            rec["progress"] = result.get("progress") or rec.get("progress") or []
            rec["completed_at"] = _utc_now()
        elif error is not None:
            rec["status"] = "FAILED"
            rec["error"] = error
            rec["completed_at"] = _utc_now()
            progress = rec.get("progress") if isinstance(rec.get("progress"), list) else _initial_progress(run_id)
            for step in progress:
                if step.get("status") == "RUNNING":
                    step["status"] = "FAILED"
                    step["detail"] = str(error.get("message") or error.get("error") or "ASTA ORDS background execution failed")[:1000]
                    step["completed_at"] = rec["completed_at"]
                    break
            rec["progress"] = progress
        ASYNC_RUNS[run_id] = rec


async def _run_ords_analyze_background(run_id: str, ords_url: str, ords_payload: dict[str, Any], timeout: int, audit_context: dict[str, Any], database: str) -> None:
    """ASTA 내부 처리 보조 함수: run ords analyze background."""
    started = perf_counter()
    try:
        result = await _post_json_to_ords(ords_url, ords_payload, timeout)
        annotated = _annotate_proxy(result)
        annotated.setdefault("run_id", run_id)
        await _complete_async_run(run_id, result=annotated)
        asta_audit.write_run_index(audit_context["request_id"], annotated, database=database, fallback_attempted=False)
        asta_audit.write_event("analyze_background_complete", {**audit_context, **asta_audit.result_fields(annotated, prefix="final"), "ords_status": annotated.get("status"), "fallback_attempted": False, "latency_ms": round((perf_counter() - started) * 1000)})
    except Exception as exc:
        error = {"error": "ASTA ORDS background error", "message": str(exc)}
        await _complete_async_run(run_id, error=error)
        asta_audit.write_event("analyze_background_error", {**audit_context, "latency_ms": round((perf_counter() - started) * 1000), "message": str(exc)[:1000]})


def _async_progress_response(record: dict[str, Any]) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: async progress response."""
    result = record.get("result") if isinstance(record.get("result"), dict) else None
    if result is not None:
        return _annotate_proxy(dict(result))
    out = {
        "run_id": record.get("run_id"),
        "status": record.get("status") or "RUNNING",
        "created_at": record.get("created_at"),
        "completed_at": record.get("completed_at"),
        "progress": record.get("progress") or [],
        "proxy": {"source": "FASTAPI_ASYNC_PROXY", "external_call": False},
    }
    if record.get("error"):
        out["error"] = record.get("error")
    return out


def _options(payload: dict[str, Any]) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: options."""
    raw = payload.get("options")
    return raw if isinstance(raw, dict) else {}


def _int_option(payload: dict[str, Any], key: str, default: int) -> int:
    """ASTA 내부 처리 보조 함수: int option."""
    options = _options(payload)
    value = options.get(key, payload.get(key, default))
    if key == "sqltune_time_limit" and value == default:
        value = options.get("sqltune_timeout_seconds", payload.get("sqltune_timeout_seconds", default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sqltune_time_limit(payload: dict[str, Any]) -> int:
    """ASTA 내부 처리 보조 함수: sqltune time limit."""
    return max(60, min(_int_option(payload, "sqltune_time_limit", 1800), 1800))


def _bool_option(payload: dict[str, Any], key: str, default: bool) -> bool:
    """ASTA 내부 처리 보조 함수: bool option."""
    options = _options(payload)
    value = payload.get(key, options.get(key, default))
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "n", "no", "off"}
    return bool(value)


def _coerce_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize OADT2's UI payload to the ADB ORDS ASTA contract."""
    options = _options(payload)
    sql = payload.get("sql") or payload.get("sql_text") or ""
    llm_profile = payload.get("llm_profile") or payload.get("ai_profile") or options.get("llm_profile")
    llm_profile = llm_profile or DEFAULT_LLM_PROFILE
    tuning_context = payload.get("tuning_context") or options.get("tuning_context") or {}
    if not isinstance(tuning_context, dict):
        tuning_context = {"note": str(tuning_context)}
    run_advisor = _bool_option(payload, "run_advisor", _bool_option(payload, "use_sqltune", False))
    out = dict(payload)
    clean_options = dict(options)
    clean_options.pop("source_schema", None)
    clean_options.pop("source_db_link", None)
    out.pop("source_schema", None)
    out.pop("source_db_link", None)
    if "options" in out:
        out["options"] = clean_options
    out.update(
        {
            "sql": str(sql).strip(),
            "sql_text": str(sql).strip(),
            "source_db_id": payload.get("source_db_id") or DEFAULT_SOURCE_DB_ID,
            "fetch_rows": _int_option(payload, "fetch_rows", 100),
            "benchmark_repeat": _int_option(payload, "benchmark_repeat", 1),
            "sqltune_time_limit": _sqltune_time_limit(payload),
            "vector_top_k": _int_option(payload, "vector_top_k", 3),
            "use_llm": _bool_option(payload, "use_llm", True),
            "run_advisor": run_advisor,
            "use_sqltune": run_advisor,
            "llm_profile": llm_profile,
            "ai_profile": payload.get("ai_profile") or llm_profile,
            "tuning_context": tuning_context,
        }
    )
    return out


def _profile_name(profile: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: profile name."""
    return str(profile.get("name") or profile.get("profile_name") or "").strip()


def _filter_asta_profiles(data: Any) -> list[dict[str, Any]]:
    """ASTA 내부 처리 보조 함수: filter asta profiles."""
    profiles = data.get("profiles") if isinstance(data, dict) else data
    if not isinstance(profiles, list):
        return []
    asta_profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    asta_default = data.get("asta_default") if isinstance(data, dict) else None
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        name = _profile_name(profile)
        if not name or not name.upper().startswith("ASTA") or name in seen:
            continue
        seen.add(name)
        asta_profiles.append(
            {
                "name": name,
                "profile_name": name,
                "display_name": profile.get("display_name") or name,
                "model": profile.get("model") or profile.get("model_name") or "",
                "provider": profile.get("provider") or "",
                "status": profile.get("status") or "",
                "selectable": profile.get("selectable", True),
                "default": bool(profile.get("default", False) or name == asta_default),
            }
        )
    return sorted(asta_profiles, key=lambda item: item["name"])


def _database_config(database: str):
    """ASTA 내부 처리 보조 함수: database config."""
    cfg = get_config()
    if cfg is None:
        raise HTTPException(status_code=500, detail={"error": "config not loaded"})
    item = cfg.get(database)
    if item is None:
        raise HTTPException(status_code=400, detail={"error": "unknown database", "database": database})
    return item


def _asta_settings(database: str) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: asta settings."""
    item = _database_config(database)
    settings = item.asta or {}
    if not isinstance(settings, dict):
        raise HTTPException(status_code=500, detail={"error": "ASTA ORDS setting must be an object", "database": database})
    return settings


def _resolve_ords_url(database: str, path_key: str, default_path: str) -> str:
    """ASTA 내부 처리 보조 함수: resolve ords url."""
    settings = _asta_settings(database)
    base = str(settings.get("ords_base_url") or "").strip()
    if not base:
        raise HTTPException(status_code=500, detail={"error": "ASTA ORDS base URL is not configured", "database": database})
    suffix = str(settings.get(path_key) or default_path).strip() or default_path
    return urljoin(base.rstrip("/") + "/", suffix.lstrip("/"))


def _validate_run_id(run_id: str) -> str:
    """ASTA 내부 처리 보조 함수: validate run id."""
    value = str(run_id or "").strip()
    if not value or value in {".", ".."} or value.startswith(".") or ".." in value:
        raise HTTPException(status_code=400, detail={"error": "invalid run_id"})
    if any(ch in value for ch in "?#\\") or any(ord(ch) < 32 for ch in value):
        raise HTTPException(status_code=400, detail={"error": "invalid run_id"})
    return quote(value, safe="")


def _run_ords_url(database: str, encoded_run_id: str, suffix: str = "") -> str:
    """ASTA 내부 처리 보조 함수: run ords url."""
    suffix_path = f"/{suffix.strip('/')}" if suffix else ""
    path_key = f"run_{suffix.strip('/')}_path" if suffix else "run_path"
    return _resolve_ords_url(database, path_key, f"/runs/{encoded_run_id}{suffix_path}")


def _annotate_proxy(data: dict[str, Any]) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: annotate proxy."""
    data.setdefault("proxy", {})
    if isinstance(data["proxy"], dict):
        data["proxy"].setdefault("source", "ADB_ORDS")
        data["proxy"].setdefault("external_call", True)
    return data


def _ords_timeout(database: str) -> int:
    """ASTA 내부 처리 보조 함수: ords timeout."""
    settings = _asta_settings(database)
    try:
        return int(settings.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _request_json_sync(req: urllib_request.Request, timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: request json sync."""
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise HTTPException(status_code=exc.code, detail={"error": "ASTA ORDS HTTP error", "ords_status": exc.code, "message": detail}) from exc
    except urllib_error.URLError as exc:
        raise HTTPException(status_code=502, detail={"error": "ASTA ORDS unavailable", "message": str(exc.reason)}) from exc
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail={"error": "ASTA ORDS returned non-JSON response", "message": str(exc)}) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail={"error": "ASTA ORDS JSON response must be an object"})
    return data


def _post_json_sync(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: post json sync."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
        method="POST",
    )
    return _request_json_sync(req, timeout)


def _get_json_sync(url: str, timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: get json sync."""
    req = urllib_request.Request(url, headers={"Accept": "application/json"}, method="GET")
    return _request_json_sync(req, timeout)


async def _post_json_to_ords(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: post json to ords."""
    return await asyncio.to_thread(_post_json_sync, url, payload, timeout)


async def _get_json_from_ords(url: str, timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: get json from ords."""
    return await asyncio.to_thread(_get_json_sync, url, timeout)


def _response_error_code(data: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: response error code."""
    if data.get("error_code"):
        return str(data.get("error_code"))
    error = data.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error.get("code"))
    if isinstance(error, str):
        return error
    return ""


async def _audited_run_lookup(run_id: str, database: str, endpoint_kind: str, suffix: str = "") -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: audited run lookup."""
    request_id = asta_audit.new_request_id()
    encoded_run_id = _validate_run_id(run_id)
    async_record = await _get_async_run(run_id)
    if async_record is not None:
        async_response = _async_progress_response(async_record)
        status = str(async_response.get("status") or "").upper()
        if status in {"COMPLETED", "DONE", "FAILED"}:
            return async_response
        if endpoint_kind != "progress":
            return async_response
    started = perf_counter()
    audit_context = {
        **asta_audit.lookup_context(request_id, run_id, endpoint_kind),
        "database": database,
        "ords_endpoint": endpoint_kind,
    }
    try:
        data = await _get_json_from_ords(_run_ords_url(database, encoded_run_id, suffix), _ords_timeout(database))
    except HTTPException as exc:
        asta_audit.write_event(
            "run_lookup_error",
            {
                **audit_context,
                "http_status": exc.status_code,
                "latency_ms": round((perf_counter() - started) * 1000),
            },
        )
        raise
    annotated = _annotate_proxy(data)
    if str(annotated.get("status") or "").upper() == "NOT_FOUND" or _response_error_code(annotated) in {"RUN_NOT_FOUND", "REPORT_NOT_FOUND"}:
        async_record = await _get_async_run(run_id)
        if async_record is not None:
            annotated = _async_progress_response(async_record)
        else:
            local = asta_audit.read_run_snapshot(run_id)
            if local is not None:
                if endpoint_kind == "progress":
                    annotated = {
                        "run_id": local.get("run_id"),
                        "status": local.get("status"),
                        "progress": local.get("progress") or [],
                        "proxy": {"source": "LOCAL_FINAL_RUN_SNAPSHOT", "external_call": False},
                    }
                elif endpoint_kind == "report":
                    annotated = {
                        "run_id": local.get("run_id"),
                        "status": local.get("status"),
                        "detailed_report_markdown": local.get("detailed_report_markdown") or local.get("report_markdown") or local.get("report") or "",
                        "report_markdown": local.get("detailed_report_markdown") or local.get("report_markdown") or local.get("report") or "",
                        "proxy": {"source": "LOCAL_FINAL_RUN_SNAPSHOT", "external_call": False},
                    }
                else:
                    annotated = dict(local)
                    annotated["proxy"] = {"source": "LOCAL_FINAL_RUN_SNAPSHOT", "external_call": False}
    else:
        annotated = _annotate_proxy(annotated)
    asta_audit.write_event(
        "run_lookup_complete",
        {
            **audit_context,
            "body_status": annotated.get("status"),
            "error_code": _response_error_code(annotated),
            "latency_ms": round((perf_counter() - started) * 1000),
            "proxy_source": (annotated.get("proxy") or {}).get("source") if isinstance(annotated.get("proxy"), dict) else None,
        },
    )
    return annotated


@router.get("/profiles")
async def profiles(database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 profiles 작업을 수행한다."""
    ords_url = _resolve_ords_url(database, "profiles_path", "/profiles")
    data = await _get_json_from_ords(ords_url, _ords_timeout(database))
    data["profiles"] = _filter_asta_profiles(data)
    data.setdefault("source", "ADB_ORDS")
    return data


@router.post("/llm-sql-only")
async def llm_sql_only(request: Request, database: str = Depends(current_db)) -> dict[str, Any]:
    """Hidden/debug path: send only the SQL text to the selected cloud AI profile.

    This intentionally bypasses ASTA evidence, SQL guard report building, Vector, SQLTUNE,
    and candidate execution. It is for quick LLM-only comparison from the UI secret action.
    """
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object payload required")
    sql_text = str(payload.get("sql") or payload.get("sql_text") or "").strip()
    if not sql_text:
        raise HTTPException(status_code=400, detail={"error": "sql required"})
    if len(sql_text) > 32767:
        raise HTTPException(status_code=400, detail={"error": "sql too long for SQL-only LLM call"})
    profile = str(payload.get("llm_profile") or payload.get("ai_profile") or DEFAULT_LLM_PROFILE).strip() or DEFAULT_LLM_PROFILE
    prompt_text = str(payload.get("prompt") or payload.get("user_prompt") or "").strip()
    if not prompt_text:
        prompt_text = "\n".join([
            "Oracle Database 기준으로 SQL 튜닝을 요청합니다.",
            "아래 SQL을 Oracle 옵티마이저 관점에서 분석하고, 실행 가능한 개선 SQL을 제안하세요.",
            "DML/DDL/PLSQL은 제안하지 말고 SELECT/WITH 단일문만 제안하세요.",
            "힌트만 추가하는 것보다 구조적 rewrite가 가능하면 우선 제안하세요.",
            "응답에는 병목 추정, 변경 이유, 개선 SQL, 주의사항을 한국어로 포함하세요.",
            "SQL:",
            sql_text,
        ])
    if len(prompt_text) > 32767:
        prompt_text = prompt_text[:32700] + "\n... [truncated for SQL-only LLM prompt]"
    started = perf_counter()
    fallback_profiles = [
        profile,
        "ASTA_GROK_REASONING_PROFILE",
        "ASTA_GROK_GENAI_PROFILE",
        "ASTA_DB_GENAI_TEST",
    ]
    tried_profiles: list[str] = []
    seen_profiles: set[str] = set()
    response = ""
    used_profile = profile
    pool = db.get_pool(database)
    try:
        async with pool.acquire() as conn:
            with conn.cursor() as cur:
                for candidate_profile in fallback_profiles:
                    candidate_profile = str(candidate_profile or "").strip()
                    if not candidate_profile or candidate_profile in seen_profiles:
                        continue
                    seen_profiles.add(candidate_profile)
                    tried_profiles.append(candidate_profile)
                    await cur.execute(
                        (
                        "select "
                        "dbms_cloud" "_ai.generate(prompt => :prompt, profile_name => :profile, action => 'chat') "
                        "as response from dual"
                    ),
                        {"prompt": prompt_text, "profile": candidate_profile},
                    )
                    row = await cur.fetchone()
                    candidate_response = row[0] if row else ""
                    reader = getattr(candidate_response, "read", None)
                    if callable(reader):
                        candidate_response = reader()
                    if str(candidate_response or "").strip():
                        response = candidate_response
                        used_profile = candidate_profile
                        break
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "SQL_ONLY_LLM_FAILED", "message": str(exc)[:2000]}) from exc
    report_markdown = str(response or "").strip()
    empty_response = not report_markdown
    if empty_response:
        report_markdown = (
            "SQL-only LLM이 빈 응답을 반환했습니다.\n\n"
            "- ASTA evidence/SQLTUNE/Vector 없이 Oracle SQL 튜닝 요청 prompt를 "
            "DBMS_CLOUD" "_AI.GENERATE(action='chat')로 보낸 숨김 경로입니다.\n"
            "- 선택한 profile과 fallback profile들이 모두 빈 응답을 반환했습니다.\n"
            "- 같은 SQL로 다시 시도하거나 일반 ASTA 분석을 실행해 evidence 기반 결과서를 확인하세요."
        )
    return {
        "status": "COMPLETED",
        "mode": "SQL_ONLY_LLM",
        "llm_profile": used_profile,
        "requested_llm_profile": profile,
        "tried_profiles": tried_profiles,
        "elapsed_ms": round((perf_counter() - started) * 1000),
        "report_markdown": report_markdown,
        "raw_response_empty": empty_response,
        "proxy": {"source": "FASTAPI_SQL_ONLY_LLM", "external_call": False},
    }


@router.post("/analyze")
async def analyze(request: Request, background_tasks: BackgroundTasks, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 analyze 작업을 수행한다."""
    request_id = asta_audit.new_request_id()
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object payload required")
    ords_payload = _coerce_payload(payload)
    run_id = str(ords_payload.get("run_id") or _new_proxy_run_id())
    ords_payload["run_id"] = run_id
    ords_payload["client_run_id"] = run_id
    audit_context = asta_audit.base_context(request_id, ords_payload)
    audit_context["request_id"] = request_id
    audit_context["run_id_prefix"] = asta_audit.run_id_prefix(run_id)
    asta_audit.write_event(
        "analyze_start",
        {
            **audit_context,
            "database": database,
            "fallback_attempted": False,
            "async_proxy": True,
        },
    )
    ords_url = _resolve_ords_url(database, "analyze_path", "/analyze")
    if background_tasks is None:
        result = await _post_json_to_ords(ords_url, ords_payload, _ords_timeout(database))
        annotated = _annotate_proxy(result)
        asta_audit.write_run_index(request_id, annotated, database=database, fallback_attempted=False)
        asta_audit.write_event(
            "analyze_complete",
            {
                **audit_context,
                **asta_audit.result_fields(annotated, prefix="final"),
                "ords_status": result.get("status"),
                "fallback_attempted": False,
                "async_proxy": False,
            },
        )
        return annotated

    await _store_async_run(
        run_id,
        {
            "run_id": run_id,
            "status": "RUNNING",
            "created_at": _utc_now(),
            "progress": _initial_progress(run_id),
        },
    )
    background_tasks.add_task(
        _run_ords_analyze_background,
        run_id,
        ords_url,
        ords_payload,
        _ords_timeout(database),
        audit_context,
        database,
    )
    return {
        "run_id": run_id,
        "status": "RUNNING",
        "progress": _initial_progress(run_id),
        "proxy": {"source": "FASTAPI_ASYNC_PROXY", "external_call": False},
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "run")


@router.get("/runs/{run_id}/progress")
async def get_run_progress(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run progress 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "progress", "progress")


@router.get("/runs/{run_id}/report")
async def get_run_report(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run report 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "report", "report")
