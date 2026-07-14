"""Thin ASTA ORDS proxy for OADT2.

Production ASTA execution belongs in ADB PL/SQL exposed through ORDS.
This router only normalizes the browser payload enough to call the configured
ORDS endpoints and passes JSON responses through without Python-side SQL
evidence, Vector, LLM, SQLTUNE, or report generation.

작성자: 도상훈
파일 용도: OADT2 UI와 ADB ORDS 기반 ASTA PL/SQL 런타임 사이를 연결하는 얇은 FastAPI 프록시이다."""
from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urljoin
import uuid

import oracledb

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app import asta_audit, db
from app.asta_runtime_gates import apply_runtime_gates
from app.deps import current_db, get_config

router = APIRouter(prefix="/asta", tags=["asta"])

REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
_REPORT_PATH = re.compile(r"^/api/asta/runs/[A-Za-z0-9][A-Za-z0-9_.:-]*/report(?:/view)?$")
_DETAILS = re.compile(r"^<details><summary>축약 SQL 보기</summary>\s*<pre><code>([\s\S]*?)</code></pre>\s*</details>$")


def _report_markdown(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    for key in ("detailed_report_markdown", "report_markdown", "report"):
        if isinstance(payload.get(key), str):
            return payload[key]
    return _report_markdown(payload.get("llm_final_report"))


def _inline_markdown(text: str) -> str:
    out, cursor = [], 0
    for match in re.finditer(r"\[([^]\n]+)\]\(([^)\s]+)\)", text):
        out.append(html.escape(text[cursor:match.start()]))
        label, target = match.groups()
        if _REPORT_PATH.fullmatch(target):
            viewer = target if target.endswith("/view") else target + "/view"
            out.append(f'<a href="{html.escape(viewer, quote=True)}">{html.escape(label)}</a>')
        else:
            out.append(html.escape(label))
        cursor = match.end()
    out.append(html.escape(text[cursor:]))
    return "".join(out)


def _markdown_to_safe_html(markdown: str) -> str:
    """Render the report subset without ever enabling arbitrary raw HTML."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("<details><summary>축약 SQL 보기</summary><pre><code>"):
            block = [line.strip()]
            while i + 1 < len(lines) and "</code></pre></details>" not in block[-1]:
                i += 1; block.append(lines[i])
            details = _DETAILS.fullmatch("\n".join(block))
            if details:
                result.append(f"<details><summary>축약 SQL 보기</summary><pre><code>{html.escape(html.unescape(details.group(1)))}</code></pre></details>")
            else:
                result.append(f"<p>{html.escape(chr(10).join(block))}</p>")
        elif line.startswith("```"):
            language = re.sub(r"[^A-Za-z0-9_-]", "", line[3:].strip())
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]); i += 1
            cls = f' class="language-{language}"' if language else ""
            result.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
        elif (heading := re.match(r"^(#{1,4})\s+(.+)$", line)):
            level = len(heading.group(1)); result.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
        elif line.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            rows = [[c.strip() for c in line.strip().strip("|").split("|")]]; i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            head = "".join(f"<th>{_inline_markdown(c)}</th>" for c in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{_inline_markdown(c)}</td>" for c in row) + "</tr>" for row in rows[1:])
            result.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"); continue
        elif (details := _DETAILS.fullmatch(line.strip())):
            result.append(f"<details><summary>축약 SQL 보기</summary><pre><code>{html.escape(html.unescape(details.group(1)))}</code></pre></details>")
        elif line.startswith("> "):
            result.append(f"<blockquote>{_inline_markdown(line[2:])}</blockquote>")
        elif re.match(r"^\s*[-*+]\s+", line):
            items = []
            while i < len(lines) and (item := re.match(r"^\s*[-*+]\s+(.+)$", lines[i])):
                items.append(f"<li>{_inline_markdown(item.group(1))}</li>"); i += 1
            result.append("<ul>" + "".join(items) + "</ul>"); continue
        elif line.strip():
            result.append(f"<p>{_inline_markdown(line)}</p>")
        i += 1
    return "\n".join(result)


def _report_document(run_id: str, markdown: str) -> str:
    safe_id = html.escape(run_id)
    base = f"/api/asta/runs/{quote(run_id, safe='')}/report"
    content = _markdown_to_safe_html(markdown)
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ASTA 결과서 · {safe_id}</title><style>
body{{margin:0;background:#f4f7fb;color:#172033;font:16px/1.65 system-ui,sans-serif}}main{{max-width:1800px;margin:auto;padding:clamp(12px,2vw,32px)}}article{{background:white;border:1px solid #dfe5ef;border-radius:16px;padding:clamp(16px,2.5vw,40px);box-shadow:0 12px 40px #0f172a14}}nav{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}nav a{{padding:9px 13px;border-radius:9px;background:#2563eb;color:white;text-decoration:none}}nav a+a{{background:#475569}}h1,h2,h3,h4{{line-height:1.25;margin-top:1.5em}}pre{{overflow-x:auto;overflow-y:auto;max-height:70vh;background:#0f172a;color:#e2e8f0;padding:16px;border-radius:10px;white-space:pre;font-size:14px;line-height:1.45}}table{{border-collapse:collapse;width:100%;display:block;overflow:auto}}th,td{{border:1px solid #cbd5e1;padding:8px 12px;text-align:left}}th{{background:#eef2ff}}blockquote{{border-left:4px solid #93c5fd;margin-left:0;padding-left:16px;color:#475569}}.run{{color:#64748b}}@media (max-width:700px){{main{{padding:8px}}article{{border-radius:10px;padding:14px}}pre{{max-height:64vh;font-size:12px;padding:12px}}}}
</style></head><body><main><nav><a href="{base}/download">원본 Markdown 다운로드</a><a href="{base}">JSON API 보기</a></nav><article><div class="run">Run ID: {safe_id}</div>{content}</article></main></body></html>'''

DEFAULT_LLM_PROFILE = "ASTA_GROK_REASONING_PROFILE"
DEFAULT_SOURCE_DB_ID = "DB0903_TESTDB"
DEFAULT_TIMEOUT_SECONDS = 2100
HEARTBEAT_INTERVAL_SECONDS = 5.0
HEARTBEAT_STALE_SECONDS = 20.0
ASYNC_RUNS: dict[str, dict[str, Any]] = {}
ASYNC_LOCK = asyncio.Lock()


def _utc_now() -> str:
    """ASTA 내부 처리 보조 함수: utc now."""
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _runtime_fields(record: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Report proxy liveness without claiming it is Source SQL activity."""
    now = now or datetime.now(timezone.utc)
    unavailable = {"status": "UNAVAILABLE", "reason": "Source DB session observation is not configured"}
    if not record:
        return {"heartbeat_at": None, "heartbeat_age_ms": None, "worker_alive": None, "observation_level": "SOURCE_OBSERVATION_UNAVAILABLE", "stage_started_at": None, "stage_elapsed_ms": None, "stale_warning": False, "upstream_request_active": None, "source_observation": unavailable}
    heartbeat = _parse_timestamp(record.get("heartbeat_at"))
    age = max(0, round((now - heartbeat).total_seconds() * 1000)) if heartbeat else None
    terminal = str(record.get("status") or "").upper() in {"FAILED", "ERROR", "COMPLETED", "DONE"}
    active = bool(record.get("upstream_request_active")) and not terminal
    stale = active and (age is None or age > HEARTBEAT_STALE_SECONDS * 1000)
    alive = active and not stale
    level = "STALE_OR_FAILED" if terminal or stale else ("PROXY_WORKER_ALIVE" if alive else "SOURCE_OBSERVATION_UNAVAILABLE")
    running = next((s for s in record.get("progress", []) if isinstance(s, dict) and str(s.get("status")).upper() == "RUNNING"), None)
    stage_start = _parse_timestamp((running or {}).get("started_at"))
    elapsed = max(0, round((now - stage_start).total_seconds() * 1000)) if stage_start else None
    return {"heartbeat_at": record.get("heartbeat_at"), "heartbeat_age_ms": age, "worker_alive": alive, "observation_level": level, "stage_started_at": (running or {}).get("started_at"), "stage_elapsed_ms": elapsed, "stale_warning": bool(stale), "upstream_request_active": active, "source_observation": unavailable}


async def _heartbeat_loop(run_id: str) -> None:
    while True:
        async with ASYNC_LOCK:
            rec = ASYNC_RUNS.get(run_id)
            if not rec or not rec.get("upstream_request_active"):
                return
            rec["heartbeat_at"] = _utc_now()
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


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
        {"seq": 6, "code": "LLM_REWRITE", "label": "SQL-only structural rewrite", "status": "PENDING"},
        {"seq": 7, "code": "AFTER_EVIDENCE", "label": "Candidate SQL evidence", "status": "PENDING"},
        {"seq": 8, "code": "BEFORE_AFTER_COMPARE", "label": "Deterministic comparison", "status": "PENDING"},
        {"seq": 9, "code": "VECTOR_KB", "label": "Verified Vector KB search", "status": "PENDING"},
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
        rec["upstream_request_active"] = False
        rec["worker_alive"] = False
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
    async with ASYNC_LOCK:
        if run_id in ASYNC_RUNS:
            ASYNC_RUNS[run_id].update({"heartbeat_at": _utc_now(), "upstream_request_active": True, "worker_alive": True})
    heartbeat_task = asyncio.create_task(_heartbeat_loop(run_id))
    try:
        result = await _post_json_to_ords(ords_url, ords_payload, timeout)
        annotated = _annotate_proxy(result)
        annotated.setdefault("run_id", run_id)
        await _complete_async_run(run_id, result=annotated)
        asta_audit.write_run_index(audit_context["request_id"], annotated, database=database, fallback_attempted=False)
        asta_audit.write_event("analyze_background_complete", {**audit_context, **asta_audit.result_fields(annotated, prefix="final"), "ords_status": annotated.get("status"), "fallback_attempted": False, "latency_ms": round((perf_counter() - started) * 1000)})
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else None
        error = detail if isinstance(detail, dict) else {"error": "ASTA ORDS background error", "message": str(exc)}
        await _complete_async_run(run_id, error=error)
        asta_audit.write_event("analyze_background_error", {**audit_context, "latency_ms": round((perf_counter() - started) * 1000), "message": str(exc)[:1000]})
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


def _async_progress_response(record: dict[str, Any]) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: async progress response."""
    result = record.get("result") if isinstance(record.get("result"), dict) else None
    if result is not None:
        out = _annotate_proxy(dict(result))
        out.update(_runtime_fields(record))
        return out
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
    out.update(_runtime_fields(record))
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


def _before_evidence_mode(payload: dict[str, Any]) -> str:
    """Normalize the selectable stage-4 Source execution policy."""
    options = _options(payload)
    value = str(payload.get("before_evidence_mode", options.get("before_evidence_mode", "MINIMAL")))
    mode = value.strip().upper()
    return mode if mode in {"MINIMAL", "FAST_PLAN", "THOROUGH"} else "MINIMAL"


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
    clean_options.pop("prompt_mode", None)
    out.pop("source_schema", None)
    out.pop("source_db_link", None)
    # Deprecated experiment knob: accepted for backward compatibility but has
    # no production meaning in the canonical SQL-only rewrite workflow.
    out.pop("prompt_mode", None)
    tuning_context = dict(tuning_context)
    tuning_context.pop("prompt_mode", None)
    workload_type = str(tuning_context.get("workload_type") or "OLTP").strip().upper()
    if workload_type not in {"OLTP", "BATCH"}:
        workload_type = "OLTP"
    tuning_context["workload_type"] = workload_type
    # Canonical server-owned goal; ignore arbitrary client strings.
    tuning_context["optimization_goal"] = (
        "MINIMIZE_ELAPSED_TIME" if workload_type == "BATCH" else "MINIMIZE_BUFFER_READS"
    )
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
            "execute_source_sql": _bool_option(payload, "execute_source_sql", False),
            "before_evidence_mode": _before_evidence_mode(payload),
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


def _get_json_sync(url: str, timeout: int, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: get json sync."""
    req = urllib_request.Request(url, headers={"Accept": "application/json", **(headers or {})}, method="GET")
    return _request_json_sync(req, timeout)


async def _post_json_to_ords(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: post json to ords."""
    return await asyncio.to_thread(_post_json_sync, url, payload, timeout)


async def _get_json_from_ords(url: str, timeout: int, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: get json from ords."""
    return await asyncio.to_thread(_get_json_sync, url, timeout, headers)


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


def _response_error_message(data: dict[str, Any]) -> str:
    """Extract the most specific ASTA/ORDS error message without hiding ORA text."""
    if data.get("error_message"):
        return str(data.get("error_message"))
    error = data.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error.get("message"))
    if data.get("message"):
        return str(data.get("message"))
    return _response_error_code(data) or "ASTA request failed"


async def _audited_run_lookup(run_id: str, database: str, endpoint_kind: str, suffix: str = "") -> dict[str, Any]:
    """ASTA 내부 처리 보조 함수: audited run lookup."""
    request_id = asta_audit.new_request_id()
    encoded_run_id = _validate_run_id(run_id)
    async_record = await _get_async_run(run_id)
    # LLM raw detail is never served from the legacy in-memory run snapshot;
    # it must remain scoped to the authoritative ADB run_id + call_id row.
    if async_record is not None and endpoint_kind != "llm_call":
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
    telemetry_record = dict(async_record) if async_record else None
    if telemetry_record is not None and isinstance(annotated.get("progress"), list):
        telemetry_record["progress"] = annotated["progress"]
    annotated.update(_runtime_fields(telemetry_record))
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
    artifacts = annotated.get("artifacts") if isinstance(annotated.get("artifacts"), dict) else {}
    gate_comparison = annotated.get("comparison") or artifacts.get("comparison")
    return apply_runtime_gates(annotated) if isinstance(gate_comparison, dict) and gate_comparison else annotated


_HISTORY_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HISTORY_VERDICTS = {"ALL", "IMPROVED", "ANALYSIS_ONLY", "NOT_IMPROVED", "CANDIDATE_FAILED", "NON_EQUIVALENT", "NO_REWRITE", "INSUFFICIENT_EVIDENCE"}


@router.get("/history")
async def get_history(
    q: str | None = None,
    database: str = Depends(current_db),
    date_from: str | None = None,
    date_to: str | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """Search persisted ASTA runs by run ID or input SQL text."""
    # This value crosses the FastAPI→ORDS boundary in a request header. Fold
    # control characters before truncation so browser input cannot create an
    # invalid or injected HTTP header while ordinary whitespace remains searchable.
    search = re.sub(r"[\x00-\x1f\x7f]+", " ", str(q or "")).strip()[:200]
    def clean_date(value: str | None, name: str) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if not _HISTORY_DATE.fullmatch(text):
            raise HTTPException(status_code=422, detail=f"{name} must be YYYY-MM-DD")
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{name} must be a valid date") from exc
        return text
    history_from = clean_date(date_from, "date_from")
    history_to = clean_date(date_to, "date_to")
    if history_from and history_to and history_from > history_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    history_verdict = str(verdict or "ALL").strip().upper()
    if history_verdict not in _HISTORY_VERDICTS:
        raise HTTPException(status_code=422, detail="unsupported history verdict")
    url = _resolve_ords_url(database, "history_path", "/history")
    headers = {"X-ASTA-History-Verdict": history_verdict}
    if search:
        headers["X-ASTA-History-Search"] = search
    if history_from:
        headers["X-ASTA-History-From"] = history_from
    if history_to:
        headers["X-ASTA-History-To"] = history_to
    data = await _get_json_from_ords(url, _ords_timeout(database), headers)
    return _annotate_proxy(data)


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
    started = perf_counter()
    fallback_profiles = [
        profile,
        "ASTA_GROK_GENAI_PROFILE",
        "ASTA_GEMINI_PROFILE",
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
                    # python-oracledb needs an explicit CLOB bind to avoid the
                    # VARCHAR2 32K boundary. Lightweight test cursors may not
                    # implement var(), so they retain the plain string value.
                    prompt_bind: Any = prompt_text
                    if hasattr(cur, "var"):
                        prompt_clob = cur.var(oracledb.DB_TYPE_CLOB)
                        prompt_clob.setvalue(0, prompt_text)
                        prompt_bind = prompt_clob
                    await cur.execute(
                        (
                        "select "
                        "dbms_cloud" "_ai.generate(prompt => :prompt, profile_name => :profile, action => 'chat') "
                        "as response from dual"
                    ),
                        {"prompt": prompt_bind, "profile": candidate_profile},
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
    """ADB에 run을 한 번 제출하고 즉시 QUEUED/RUNNING 응답을 전달한다."""
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
    result = await _post_json_to_ords(ords_url, ords_payload, _ords_timeout(database))
    # Submission responses are QUEUED/RUNNING transport acknowledgements, not
    # gate evidence.  Runtime gates are attached only on final run lookup.
    annotated = _annotate_proxy(result)
    annotated.setdefault("run_id", run_id)
    asta_audit.write_run_index(request_id, annotated, database=database, fallback_attempted=False)
    asta_audit.write_event(
        "analyze_submitted",
        {
            **audit_context,
            **asta_audit.result_fields(annotated, prefix="final"),
            "ords_status": result.get("status"),
            "fallback_attempted": False,
            "async_proxy": False,
            "execution_mode": result.get("execution_mode"),
        },
    )
    result_status = str(annotated.get("status") or "").upper()
    result_error_code = _response_error_code(annotated)
    if result_status in {"FAILED", "ERROR"} or (result_error_code and result_status not in {"QUEUED", "RUNNING", "COMPLETED", "DONE"}):
        client_error_codes = {
            "SQL_GUARD_REJECTED", "RUN_ID_CONFLICT", "IDEMPOTENCY_CONFLICT",
            "SQL_INVALID_IDENTIFIER", "SQL_AMBIGUOUS_COLUMN", "SQL_SET_SHAPE_MISMATCH",
        }
        raise HTTPException(
            status_code=422 if result_error_code in client_error_codes else 502,
            detail={
                "error": result_error_code or "ASTA_SUBMIT_FAILED",
                "message": _response_error_message(annotated),
                "run_id": annotated.get("run_id"),
            },
        )
    return annotated


@router.get("/runs/{run_id}")
async def get_run(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "run")


@router.get("/runs/{run_id}/input-sql")
async def get_run_input_sql(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """Lazily return full submitted SQL only for the selected authenticated run."""
    return await _audited_run_lookup(run_id, database, "input_sql", "input-sql")


@router.get("/runs/{run_id}/progress")
async def get_run_progress(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run progress 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "progress", "progress")


@router.get("/runs/{run_id}/llm-calls/{call_id}")
async def get_run_llm_call(run_id: str, call_id: int, database: str = Depends(current_db)) -> dict[str, Any]:
    """인증된 same-origin 요청에서 선택한 LLM prompt/응답 원문만 지연 조회한다."""
    if call_id < 1:
        raise HTTPException(status_code=400, detail={"error": "invalid call_id"})
    return await _audited_run_lookup(run_id, database, "llm_call", f"llm-calls/{call_id}")


@router.get("/runs/{run_id}/report")
async def get_run_report(run_id: str, database: str = Depends(current_db)) -> dict[str, Any]:
    """ASTA 처리 흐름에서 get run report 작업을 수행한다."""
    return await _audited_run_lookup(run_id, database, "report", "report")


@router.get("/runs/{run_id}/report/view", response_class=HTMLResponse)
async def get_run_report_view(run_id: str, database: str = Depends(current_db)) -> HTMLResponse:
    payload = await _audited_run_lookup(run_id, database, "report_view", "report")
    return HTMLResponse(_report_document(run_id, _report_markdown(payload)), headers={"Content-Security-Policy": REPORT_CSP})


@router.get("/runs/{run_id}/report/download")
async def download_run_report(run_id: str, database: str = Depends(current_db)) -> Response:
    payload = await _audited_run_lookup(run_id, database, "report_download", "report")
    filename_id = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)[:120] or "report"
    return Response(_report_markdown(payload), media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="asta-report-{filename_id}.md"'
    })
