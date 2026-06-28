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
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "reports" / "asta_10sql_bg_latest"
OUTDIR.mkdir(parents=True, exist_ok=True)
API = "http://127.0.0.1:8000/api/asta/analyze"


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


def post_once(payload: dict, timeout: int = 420) -> tuple[int, dict | str]:
    """한 건의 ASTA analyze 요청을 ORDS/FastAPI 엔드포인트로 전송한다."""
    req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
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


def post(payload: dict, timeout: int = 420, attempts: int = 2) -> tuple[int, dict | str, int]:
    """재시도 정책을 적용해 ASTA analyze 요청을 전송한다."""
    last_http: int = 0
    last_data: dict | str = {"error": "not attempted"}
    for attempt in range(1, attempts + 1):
        last_http, last_data = post_once(payload, timeout=timeout)
        if not should_retry(last_http, last_data):
            return last_http, last_data, attempt
        if attempt < attempts:
            time.sleep(2)
    return last_http, last_data, attempts


def summarize(data):
    """여러 ASTA 실행 결과를 사람이 읽기 쉬운 요약으로 정리한다."""
    if not isinstance(data, dict):
        return {"status":"NON_JSON"}
    md = data.get("detailed_report_markdown") or data.get("report_markdown") or ""
    prog = data.get("progress") if isinstance(data.get("progress"), list) else []
    advisor = ((data.get("runtime_evidence") or {}).get("advisor") or {}).get("status")
    return {
        "run_id": data.get("run_id"),
        "status": data.get("status"),
        "advisor_status": advisor,
        "progress": {str(s.get("code")): s.get("status") for s in prog if isinstance(s, dict)},
        "proxy": data.get("proxy"),
        "visible_has_tuning_result": "## 튜닝 결과" in md,
        "visible_has_ora03150": "ORA-03150" in md,
        "visible_has_source_direct": bool(re.search(r"SOURCE_DIRECT|SOURCE DIRECT", md, re.I)),
        "raw_has_source_direct": bool(re.search(r"SOURCE_DIRECT|SOURCE DIRECT|BASEDB_SOURCE_DIRECT", json.dumps(data, ensure_ascii=False), re.I)),
    }


def main():
    """명령행 인자를 읽어 ASTA 도구의 전체 작업 흐름을 실행한다."""
    samples = load_samples()
    all_results = []
    started = datetime.now(timezone.utc).isoformat()
    for i, sample in enumerate(samples, 1):
        sid = sample.get("id") or f"sql-{i}"
        payload = {
            "sql": sample["sql"],
            "source_db_id": "DB0903_TESTDB",
            "use_llm": True,
            "run_advisor": True,
            "use_sqltune": True,
            "llm_profile": "ASTA_GROK_REASONING_PROFILE",
            "ai_profile": "ASTA_GROK_REASONING_PROFILE",
            "fetch_rows": 100,
            "sqltune_time_limit": 60,
        }
        t0 = time.time()
        http, data, attempts = post(payload)
        elapsed = round(time.time()-t0, 3)
        result = {"seq": i, "id": sid, "label": sample.get("label"), "http_status": http, "elapsed_sec": elapsed, "attempts": attempts, "summary": summarize(data)}
        all_results.append(result)
        (OUTDIR / f"{i:02d}_{sid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if isinstance(data, dict):
            md = data.get("detailed_report_markdown") or data.get("report_markdown")
            if md:
                (OUTDIR / f"{i:02d}_{sid}.md").write_text(md, encoding="utf-8")
        (OUTDIR / "progress.json").write_text(json.dumps({"started_at": started, "results": all_results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    final = {"started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(), "results": all_results}
    (OUTDIR / "summary.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    lines=["# ASTA 10 SQL Background Test", "", f"- started: `{started}`", f"- completed: `{final['completed_at']}`", "", "| # | id | HTTP | status | advisor | run_id | flags |", "|---:|---|---:|---|---|---|---|"]
    for r in all_results:
        s=r["summary"]
        flags=[]
        for k in ["visible_has_ora03150","visible_has_source_direct","raw_has_source_direct"]:
            if s.get(k): flags.append(k)
        lines.append(f"| {r['seq']} | {r['id']} | {r['http_status']} | {s.get('status')} | {s.get('advisor_status')} | {s.get('run_id')} | {', '.join(flags) or '-'} |")
    (OUTDIR / "summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")

if __name__ == "__main__":
    main()
