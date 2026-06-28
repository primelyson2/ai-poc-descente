"""Sanitized ASTA request audit logging.

The audit stream is intentionally small and metadata-only: SQL text, DSNs,
passwords, helper stdout/stderr, and raw ORDS payloads are never persisted here.

작성자: 도상훈
파일 용도: ASTA 요청/실행 감사 로그를 민감정보 없이 기록하고 run_id 조회용 요약 인덱스를 관리한다."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = ROOT / "logs" / "asta"
AUDIT_FILE = "asta_request_audit.jsonl"
SUMMARY_FILE = "latest_summary.md"
RUN_INDEX_FILE = "index.jsonl"
RUN_SNAPSHOT_SUFFIX = ".json"


def new_request_id() -> str:
    """ASTA 감사 로그에서 사용할 고유 요청 ID를 생성한다."""
    return uuid.uuid4().hex


def audit_dir() -> Path:
    """ASTA 감사 로그와 실행 스냅샷을 저장할 디렉터리를 반환한다."""
    return Path(os.environ.get("ASTA_AUDIT_DIR") or DEFAULT_AUDIT_DIR)


def sql_hash(sql: Any) -> str:
    """SQL 원문을 저장하지 않고 비교할 수 있도록 SHA-256 해시를 계산한다."""
    return hashlib.sha256(str(sql or "").encode("utf-8")).hexdigest()


def sql_fingerprint(sql: Any) -> str:
    """리터럴과 숫자를 마스킹한 SQL 지문 해시를 계산한다."""
    text = str(sql or "").strip().lower()
    text = re.sub(r"'([^']|'')*'", "?", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "?", text)
    text = re.sub(r"\s+", " ", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def run_id_hash(run_id: Any) -> str:
    """run_id를 노출하지 않고 조회할 수 있는 짧은 해시를 만든다."""
    return hashlib.sha256(str(run_id or "").encode("utf-8")).hexdigest()[:16]


def run_id_prefix(run_id: Any) -> str:
    """로그 화면에 안전하게 표시할 run_id 축약 문자열을 만든다."""
    value = str(run_id or "").strip()
    if len(value) <= 20:
        return value
    return f"{value[:16]}…{value[-4:]}"


def lookup_context(request_id: str, run_id: Any, endpoint_kind: str) -> dict[str, Any]:
    """run_id 조회 감사 이벤트에 공통으로 들어갈 메타데이터를 만든다."""
    return {
        "request_id": request_id,
        "queried_run_id_prefix": run_id_prefix(run_id),
        "queried_run_id_hash": run_id_hash(run_id),
        "endpoint_kind": endpoint_kind,
    }


def _progress_summary(result: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: progress summary."""
    raw = result.get("progress") if isinstance(result, dict) else None
    if not isinstance(raw, list):
        raw = result.get("steps") if isinstance(result, dict) else None
    if not isinstance(raw, list):
        return ""
    parts: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("code") or item.get("step") or item.get("name")
        status = item.get("status")
        if code and status:
            parts.append(f"{code}:{status}")
    return ",".join(parts)


def _report_path(result: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: report path."""
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    if isinstance(artifacts, dict):
        for key in ("report_path", "markdown_path", "detailed_report_path"):
            value = artifacts.get(key)
            if value:
                return str(value)
    if result.get("report_path"):
        return str(result.get("report_path"))
    if result.get("detailed_report_markdown"):
        return "inline:detailed_report_markdown"
    return ""


def _advisor_status(result: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: advisor status."""
    evidence = result.get("runtime_evidence") if isinstance(result, dict) else None
    if isinstance(evidence, dict):
        advisor = evidence.get("advisor")
        if isinstance(advisor, dict) and advisor.get("status"):
            return str(advisor.get("status"))
    artifacts = result.get("artifacts") if isinstance(result, dict) else None
    if isinstance(artifacts, dict):
        evidence = artifacts.get("source_evidence")
        if isinstance(evidence, dict):
            advisor = evidence.get("advisor")
            if isinstance(advisor, dict) and advisor.get("status"):
                return str(advisor.get("status"))
    return ""


def base_context(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """ASTA analyze 요청에서 민감정보를 제외한 기본 감사 필드를 만든다."""
    sql = payload.get("sql") or payload.get("sql_text") or ""
    return {
        "request_id": request_id,
        "sql_sha256": sql_hash(sql),
        "sql_fingerprint": sql_fingerprint(sql),
        "source_db_id": payload.get("source_db_id"),
        "use_llm": bool(payload.get("use_llm")),
        "run_advisor": bool(payload.get("run_advisor") or payload.get("use_sqltune")),
        "sqltune_time_limit": payload.get("sqltune_time_limit"),
    }


def _visible_report_text(result: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: visible report text."""
    if not isinstance(result, dict):
        return ""
    for key in ("detailed_report_markdown", "report_markdown", "report", "message"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _artifact_text_sample(result: dict[str, Any]) -> str:
    """ASTA 내부 처리 보조 함수: artifact text sample."""
    if not isinstance(result, dict):
        return ""
    artifacts = result.get("artifacts")
    pieces: list[str] = []
    if isinstance(artifacts, dict):
        for key in ("source_evidence", "after_evidence", "comparison", "vector", "vector_save", "llm", "final_review"):
            value = artifacts.get(key)
            if value is not None:
                pieces.append(json.dumps(value, ensure_ascii=False, default=str)[:12000])
    return "\n".join(pieces)[:60000]


def result_fields(result: dict[str, Any], *, prefix: str = "final") -> dict[str, Any]:
    """ASTA 실행 결과에서 감사/검증에 필요한 요약 필드를 추출한다."""
    visible_report = _visible_report_text(result)
    artifact_sample = _artifact_text_sample(result)
    return {
        "run_id": result.get("run_id") or ((result.get("runtime_evidence") or {}).get("run_id") if isinstance(result.get("runtime_evidence"), dict) else None),
        f"{prefix}_status": result.get("status"),
        f"{prefix}_progress": _progress_summary(result),
        "report_path": _report_path(result),
        "advisor_status": _advisor_status(result),
        "visible_report_has_ora03150": "ORA-03150" in visible_report,
        "visible_report_has_source_direct": "SOURCE_DIRECT" in visible_report.upper() or "SOURCE DIRECT" in visible_report.upper(),
        "visible_report_has_old_result_summary": "## 결과 요약" in visible_report,
        "visible_report_has_tuning_result": "## 튜닝 결과" in visible_report,
        "raw_artifact_has_ora03150": "ORA-03150" in artifact_sample,
        "raw_artifact_has_source_direct": "SOURCE_DIRECT" in artifact_sample.upper() or "SOURCE DIRECT" in artifact_sample.upper(),
        "raw_artifact_has_old_result_summary": "## 결과 요약" in artifact_sample,
    }


def write_event(event: str, fields: dict[str, Any]) -> None:
    """민감정보를 제거한 ASTA 감사 이벤트를 JSONL 파일에 기록한다."""
    safe = {k: v for k, v in fields.items() if v is not None and v != ""}
    safe["event"] = event
    safe["ts"] = datetime.now(timezone.utc).isoformat()
    directory = audit_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / AUDIT_FILE
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")
    _write_summary(directory, safe)


def write_run_index(request_id: str, result: dict[str, Any], *, database: str, fallback_attempted: bool) -> None:
    """Append a searchable analyze-result index without SQL text or secrets."""
    if not isinstance(result, dict):
        return
    fields = result_fields(result)
    run_id = fields.get("run_id")
    raw_proxy = result.get("proxy")
    proxy: dict[str, Any] = raw_proxy if isinstance(raw_proxy, dict) else {}
    record = {
        "request_id": request_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "database": database,
        "run_id": run_id,
        "run_id_prefix": run_id_prefix(run_id),
        "run_id_hash": run_id_hash(run_id),
        "status": result.get("status"),
        "source_boundary": proxy.get("source") or result.get("source"),
        "fallback_attempted": fallback_attempted,
        "advisor_status": fields.get("advisor_status"),
        "progress_summary": fields.get("final_progress"),
        "report_path": fields.get("report_path"),
        "visible_report_has_ora03150": fields.get("visible_report_has_ora03150"),
        "visible_report_has_source_direct": fields.get("visible_report_has_source_direct"),
        "visible_report_has_old_result_summary": fields.get("visible_report_has_old_result_summary"),
        "visible_report_has_tuning_result": fields.get("visible_report_has_tuning_result"),
        "raw_artifact_has_ora03150": fields.get("raw_artifact_has_ora03150"),
        "raw_artifact_has_source_direct": fields.get("raw_artifact_has_source_direct"),
        "raw_artifact_has_old_result_summary": fields.get("raw_artifact_has_old_result_summary"),
    }
    safe = {k: v for k, v in record.items() if v is not None and v != ""}
    directory = Path(os.environ.get("ASTA_RUN_INDEX_DIR") or (ROOT / "reports" / "asta_runs"))
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / RUN_INDEX_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")
    if run_id and (fallback_attempted or "SOURCE_DIRECT_FALLBACK" in str(proxy.get("source") or "").upper()):
        write_run_snapshot(run_id, result, database=database, request_id=request_id, fallback_attempted=fallback_attempted)


def _safe_snapshot_name(run_id: Any) -> str:
    """ASTA 내부 처리 보조 함수: safe snapshot name."""
    value = str(run_id or "").strip()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:180]


def _snapshot_dir() -> Path:
    """ASTA 내부 처리 보조 함수: snapshot dir."""
    directory = Path(os.environ.get("ASTA_RUN_INDEX_DIR") or (ROOT / "reports" / "asta_runs")) / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_run_snapshot(run_id: Any, result: dict[str, Any], *, database: str, request_id: str, fallback_attempted: bool) -> None:
    """Persist the final proxy-visible result for controlled fallback runs."""
    if not isinstance(result, dict):
        return
    name = _safe_snapshot_name(run_id)
    if not name:
        return
    record = {
        "request_id": request_id,
        "database": database,
        "fallback_attempted": fallback_attempted,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }
    (_snapshot_dir() / f"{name}{RUN_SNAPSHOT_SUFFIX}").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_run_snapshot(run_id: Any) -> dict[str, Any] | None:
    """저장된 ASTA 실행 결과 스냅샷을 run_id로 조회한다."""
    name = _safe_snapshot_name(run_id)
    if not name:
        return None
    path = _snapshot_dir() / f"{name}{RUN_SNAPSHOT_SUFFIX}"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, dict) else None


def _write_summary(directory: Path, record: dict[str, Any]) -> None:
    """ASTA 내부 처리 보조 함수: write summary."""
    lines = [
        "# ASTA latest request audit summary",
        "",
        f"- event: `{record.get('event', '')}`",
        f"- ts: `{record.get('ts', '')}`",
        f"- request_id: `{record.get('request_id', '')}`",
        f"- run_id: `{record.get('run_id', '')}`",
        f"- queried_run_id_prefix: `{record.get('queried_run_id_prefix', '')}`",
        f"- endpoint_kind: `{record.get('endpoint_kind', '')}`",
        f"- source_db_id: `{record.get('source_db_id', '')}`",
        f"- status: `{record.get('final_status') or record.get('ords_status') or ''}`",
        f"- progress: `{record.get('final_progress') or record.get('ords_progress') or ''}`",
        f"- fallback_attempted: `{record.get('fallback_attempted', '')}`",
        f"- helper_returncode: `{record.get('helper_returncode', '')}`",
        f"- advisor_status: `{record.get('advisor_status', '')}`",
        f"- evidence_boundary: `{record.get('evidence_boundary', '')}`",
        f"- report_path: `{record.get('report_path', '')}`",
        f"- visible_report_has_ora03150: `{record.get('visible_report_has_ora03150', '')}`",
        f"- visible_report_has_source_direct: `{record.get('visible_report_has_source_direct', '')}`",
        f"- visible_report_has_old_result_summary: `{record.get('visible_report_has_old_result_summary', '')}`",
        f"- visible_report_has_tuning_result: `{record.get('visible_report_has_tuning_result', '')}`",
        f"- raw_artifact_has_ora03150: `{record.get('raw_artifact_has_ora03150', '')}`",
        f"- raw_artifact_has_source_direct: `{record.get('raw_artifact_has_source_direct', '')}`",
        f"- raw_artifact_has_old_result_summary: `{record.get('raw_artifact_has_old_result_summary', '')}`",
        "",
        "SQL text and secrets are intentionally omitted; use sql_sha256/sql_fingerprint for correlation.",
    ]
    (directory / SUMMARY_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
