"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import time
import urllib.request
import urllib.error
import uuid
import yaml
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "reports" / "asta_10sql_bg_latest"
OUTDIR.mkdir(parents=True, exist_ok=True)
API = "http://127.0.0.1:8000/api/asta/analyze"


def configured_ords_base_url() -> str:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for database in config.get("databases", []):
        base = ((database.get("asta") or {}).get("ords_base_url") or "").strip()
        if base:
            return base.rstrip("/")
    raise RuntimeError("ASTA ORDS base URL is not configured")


def load_samples() -> list[dict]:
    """10개 ASTA 검증 샘플 SQL과 옵션을 파일에서 읽어온다."""
    js = ROOT / "static/js/extensions/tuning_assistant.js"
    script = f"""
const fs = require('fs');
const src = fs.readFileSync({json.dumps(str(js))}, 'utf8');
const start = src.indexOf('const ASTA_SAMPLE_SQLS =');
const arrStart = src.indexOf('[', start);
let depth=0, end=-1, inStr=false, quote='', esc=false;
for (let i=arrStart; i<src.length; i++) {{
  const ch=src[i];
  if (inStr) {{ if (esc) esc=false; else if (ch==='\\\\') esc=true; else if (ch===quote) inStr=false; continue; }}
  if (ch==='\"' || ch==="'") {{ inStr=true; quote=ch; continue; }}
  if (ch==='[') depth++;
  if (ch===']') {{ depth--; if (depth===0) {{ end=i+1; break; }} }}
}}
const arr = eval(src.slice(arrStart,end));
console.log(JSON.stringify(arr.slice(0,10)));
"""
    out = subprocess.check_output(["node", "-e", script], cwd=ROOT, text=True)
    return json.loads(out)


def post_once(payload: dict, timeout: int = 420, url: str = API) -> tuple[int, dict | str]:
    """한 건의 ASTA analyze 요청을 ORDS/FastAPI 엔드포인트로 전송한다."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode(errors="replace")
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body[:4000]
    except Exception as e:
        return 0, {"error": type(e).__name__, "message": str(e)}


def should_retry(http: int, data: dict | str) -> bool:
    """일시적인 오류인지 판정해 재시도 여부를 결정한다."""
    if http in (0, 502, 503, 504):
        return True
    if not isinstance(data, dict):
        return True
    detail_obj = data.get("detail")
    detail = detail_obj if isinstance(detail_obj, dict) else {}
    return detail.get("error") == "ASTA ORDS returned non-JSON response"


def post(payload: dict, timeout: int = 420, attempts: int = 2, url: str = API) -> tuple[int, dict | str, int]:
    """재시도 정책을 적용해 ASTA analyze 요청을 전송한다."""
    last_http: int = 0
    last_data: dict | str = {"error": "not attempted"}
    for attempt in range(1, attempts + 1):
        last_http, last_data = post_once(payload, timeout=timeout, url=url)
        if not should_retry(last_http, last_data):
            return last_http, last_data, attempt
        if attempt < attempts:
            time.sleep(2)
    return last_http, last_data, attempts


def get_json(url: str, timeout: int = 120) -> tuple[int, dict | str]:
    return curl_json("GET", url, None, timeout)


def curl_json(method: str, url: str, payload: dict | None, timeout: int) -> tuple[int, dict | str]:
    command = [
        "curl", "-sS", "--max-time", str(timeout), "-X", method,
        "-H", "Content-Type: application/json", "-w", "\n%{http_code}", url,
    ]
    if payload is not None:
        command.extend(["--data-binary", json.dumps(payload, ensure_ascii=False)])
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout + 5)
        body, _, status_text = completed.stdout.rpartition("\n")
        status = int(status_text) if status_text.isdigit() else 0
        try:
            return status, json.loads(body)
        except Exception:
            return status, (body or completed.stderr)[:4000]
    except Exception as exc:
        return 0, {"error": type(exc).__name__, "message": str(exc)}


def wait_for_ords_terminal(base_url: str, run_id: str, timeout_sec: int = 2400, poll_sec: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    last_status = "QUEUED"
    while time.monotonic() < deadline:
        _, progress = get_json(f"{base_url}/runs/{run_id}/progress")
        if isinstance(progress, dict):
            last_status = str(progress.get("status") or "UNKNOWN").upper()
            if last_status in {"COMPLETED", "DONE", "FAILED", "CANCELLED", "TIMED_OUT", "BLOCKED", "REJECTED"}:
                _, payload = get_json(f"{base_url}/runs/{run_id}", timeout=300)
                return payload if isinstance(payload, dict) else progress
        time.sleep(poll_sec)
    raise TimeoutError(f"ASTA ORDS run timeout: status={last_status}, run_id={run_id}")


def summarize(data):
    """여러 ASTA 실행 결과를 사람이 읽기 쉬운 요약으로 정리한다."""
    if not isinstance(data, dict):
        return {"status":"NON_JSON"}
    md = data.get("detailed_report_markdown") or data.get("report_markdown") or ""
    prog = data.get("progress") if isinstance(data.get("progress"), list) else []
    advisor = ((data.get("runtime_evidence") or {}).get("advisor") or {}).get("status")
    comparison = data.get("comparison") or (data.get("artifacts") or {}).get("comparison") or {}
    return {
        "run_id": data.get("run_id"),
        "status": data.get("status"),
        "advisor_status": advisor,
        "verdict": comparison.get("verdict") or "UNKNOWN",
        "progress": {str(s.get("code")): s.get("status") for s in prog if isinstance(s, dict)},
        "proxy": data.get("proxy"),
        "visible_has_tuning_result": "## 튜닝 결과" in md,
        "visible_has_ora03150": "ORA-03150" in md,
        "visible_has_source_direct": bool(re.search(r"SOURCE_DIRECT|SOURCE DIRECT", md, re.I)),
        "raw_has_source_direct": bool(re.search(r"SOURCE_DIRECT|SOURCE DIRECT|BASEDB_SOURCE_DIRECT", json.dumps(data, ensure_ascii=False), re.I)),
    }


def aggregate_verdicts(summaries):
    """실행 요약을 deterministic comparison verdict별로 집계한다."""
    return Counter(item.get("verdict") or "UNKNOWN" for item in summaries)


def batch_is_healthy(results: list[dict], expected_count: int = 10) -> bool:
    """Loop/CI gate: 전 건 완료 및 안전한 deterministic verdict인지 확인한다."""
    valid_verdicts = {
        "IMPROVED", "NOT_IMPROVED", "CANDIDATE_FAILED", "NON_EQUIVALENT",
        "NO_REWRITE", "INSUFFICIENT_EVIDENCE",
    }
    if len(results) != expected_count:
        return False
    return all(
        item.get("http_status") == 200
        and (item.get("summary") or {}).get("status") == "COMPLETED"
        and (item.get("summary") or {}).get("verdict") in valid_verdicts
        for item in results
    )


def _lob_text(value):
    return value.read() if hasattr(value, "read") else value


def _call_json(cur, function_name: str, argument: str) -> dict:
    import oracledb

    value = cur.callfunc(function_name, oracledb.DB_TYPE_CLOB, [argument])
    payload = json.loads(_lob_text(value))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{function_name} returned non-object JSON")
    return payload


def wait_for_terminal(cur, run_id: str, timeout_sec: int = 2400, poll_sec: float = 2.0) -> dict:
    """작은 progress 응답을 poll하고 terminal 뒤에만 전체 run을 한 번 조회한다."""
    deadline = time.monotonic() + timeout_sec
    last_status = "QUEUED"
    while time.monotonic() < deadline:
        progress = _call_json(cur, "ASTA_PKG.GET_PROGRESS", run_id)
        last_status = str(progress.get("status") or "UNKNOWN").upper()
        if last_status in {"COMPLETED", "DONE", "FAILED", "CANCELLED", "TIMED_OUT", "BLOCKED", "REJECTED"}:
            return _call_json(cur, "ASTA_PKG.GET_RUN", run_id)
        time.sleep(poll_sec)
    raise TimeoutError(f"ASTA run timeout: status={last_status}, run_id={run_id}")


def main() -> int:
    """명령행 인자를 읽어 ASTA 도구의 전체 작업 흐름을 실행한다."""
    samples = load_samples()
    all_results = []
    started = datetime.now(timezone.utc).isoformat()
    base_url = configured_ords_base_url()
    for i, sample in enumerate(samples, 1):
            sid = sample.get("id") or f"sql-{i}"
            run_id = f"OADT2-ASTA-S10-{i:02d}-{uuid.uuid4().hex[:20]}"
            payload = {
                "run_id": run_id,
                "client_run_id": run_id,
                "sql": sample["sql"],
                "source_db_id": "DB0903_TESTDB",
                "use_llm": True,
                "run_advisor": False,
                "use_sqltune": False,
                "llm_profile": "ASTA_GROK_REASONING_PROFILE",
                "ai_profile": "ASTA_GROK_REASONING_PROFILE",
                "fetch_rows": 100,
                "sqltune_time_limit": 60,
                "tuning_context": {
                    "workload_type": sample.get("workload") or "OLTP",
                    "optimization_goal": "MINIMIZE_BUFFER_READS",
                    "user_notes": f"UI sample validation: {sid} {sample.get('pattern') or ''}".strip(),
                },
            }
            t0 = time.time()
            try:
                http, submitted = curl_json("POST", f"{base_url}/analyze", payload, 120)
                attempts = 1
                if not isinstance(submitted, dict) or not submitted.get("run_id"):
                    raise RuntimeError(f"ASTA submit failed: HTTP {http}")
                submitted_run_id = submitted.get("run_id") or run_id
                (OUTDIR / "progress.json").write_text(json.dumps({
                    "started_at": started,
                    "active": {"seq": i, "id": sid, "run_id": submitted_run_id, "submitted_status": submitted.get("status")},
                    "results": all_results,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                data = wait_for_ords_terminal(base_url, submitted_run_id)
                http = 200
            except Exception as exc:
                data = {"run_id": run_id, "status": "FAILED", "error": {"code": type(exc).__name__, "message": str(exc)}}
                attempts = 1
                http = 0
            elapsed = round(time.time() - t0, 3)
            summary = summarize(data)
            result = {"seq": i, "id": sid, "label": sample.get("label"), "pattern": sample.get("pattern"), "http_status": http, "elapsed_sec": elapsed, "attempts": attempts, "summary": summary}
            all_results.append(result)
            safe_artifact = {
                "sample": {"id": sid, "label": sample.get("label"), "pattern": sample.get("pattern")},
                "run_id": summary.get("run_id") or run_id,
                "status": summary.get("status"),
                "verdict": summary.get("verdict"),
                "advisor_status": summary.get("advisor_status"),
                "error_code": data.get("error_code") or (data.get("error") or {}).get("code"),
                "error_message": data.get("error_message") or (data.get("error") or {}).get("message"),
                "comparison": data.get("comparison") or (data.get("artifacts") or {}).get("comparison"),
                "progress": data.get("progress"),
            }
            (OUTDIR / f"{i:02d}_{sid}.json").write_text(json.dumps(safe_artifact, ensure_ascii=False, indent=2), encoding="utf-8")
            md = data.get("detailed_report_markdown") or data.get("report_markdown")
            if md:
                (OUTDIR / f"{i:02d}_{sid}.md").write_text(md, encoding="utf-8")
            (OUTDIR / "progress.json").write_text(json.dumps({"started_at": started, "results": all_results}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    verdict_counts = aggregate_verdicts(r["summary"] for r in all_results)
    final = {"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "verdict_counts": dict(verdict_counts), "results": all_results}
    (OUTDIR / "summary.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    lines=["# ASTA 10 SQL Background Test", "", f"- started: `{started}`", f"- completed: `{final['completed_at']}`", f"- verdicts: `{dict(verdict_counts)}`", "", "| # | id | HTTP | status | verdict | advisor | run_id | flags |", "|---:|---|---:|---|---|---|---|---|"]
    for r in all_results:
        s=r["summary"]
        flags=[]
        for k in ["visible_has_ora03150","visible_has_source_direct","raw_has_source_direct"]:
            if s.get(k): flags.append(k)
        lines.append(f"| {r['seq']} | {r['id']} | {r['http_status']} | {s.get('status')} | {s.get('verdict')} | {s.get('advisor_status')} | {s.get('run_id')} | {', '.join(flags) or '-'} |")
    (OUTDIR / "summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return 0 if batch_is_healthy(all_results, expected_count=len(samples)) else 1

if __name__ == "__main__":
    raise SystemExit(main())
