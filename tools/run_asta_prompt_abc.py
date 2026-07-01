#!/usr/bin/env python3
"""ASTA A/B/C LLM 입력량 비교를 동일 실행 경로에서 수행한다."""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports" / "asta_prompt_abc_latest"


def load_samples(sample_ids: set[str]) -> list[dict]:
    js = ROOT / "static/js/extensions/tuning_assistant.js"
    script = f"""
const fs=require('fs'); const src=fs.readFileSync({json.dumps(str(js))},'utf8');
const start=src.indexOf('const ASTA_SAMPLE_SQLS ='); const a=src.indexOf('[',start);
let d=0,e=-1,s=false,q='',x=false;
for(let i=a;i<src.length;i++){{const c=src[i];if(s){{if(x)x=false;else if(c==='\\\\')x=true;else if(c===q)s=false;continue;}}if(c==='\"'||c==="'"){{s=true;q=c;continue;}}if(c==='[')d++;if(c===']'&&--d===0){{e=i+1;break;}}}}
console.log(JSON.stringify(eval(src.slice(a,e))));
"""
    data = json.loads(subprocess.check_output(["node", "-e", script], text=True, cwd=ROOT))
    return [item for item in data if item.get("id") in sample_ids]


def ords_url() -> str:
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    db = cfg["databases"][0]
    base = str(db["asta"]["ords_base_url"]).rstrip("/")
    return base + str(db["asta"].get("analyze_path") or "/analyze")


def post(url: str, payload: dict, timeout: int) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"status": "HTTP_ERROR", "message": raw[:4000]}
    except Exception as exc:
        return 0, {"status": "CLIENT_ERROR", "message": f"{type(exc).__name__}: {exc}"}


def summarize(sample: dict, mode: str, http_status: int, elapsed_sec: float, result: dict) -> dict:
    comparison_obj = result.get("comparison")
    comparison: dict = comparison_obj if isinstance(comparison_obj, dict) else {}
    artifacts_obj = result.get("artifacts")
    artifacts: dict = artifacts_obj if isinstance(artifacts_obj, dict) else {}
    llm_obj = artifacts.get("llm")
    llm: dict = llm_obj if isinstance(llm_obj, dict) else {}
    candidate = result.get("candidate_sql") or llm.get("candidate_sql")
    candidate_error = llm.get("candidate_error")
    before = comparison.get("before_buffer_gets")
    after = comparison.get("after_buffer_gets")
    changed = bool(candidate and str(candidate).strip() and not candidate_error)
    equivalent = comparison.get("row_count_matches") is True and comparison.get("output_rows_match") is True
    return {
        "sample_id": sample.get("id"),
        "label": sample.get("label"),
        "mode": mode,
        "http_status": http_status,
        "wall_elapsed_sec": elapsed_sec,
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "llm_prompt_mode": llm.get("prompt_mode"),
        "prompt_chars": llm.get("prompt_chars"),
        "llm_call_count": llm.get("llm_call_count"),
        "candidate_generated": changed,
        "candidate_error": candidate_error,
        "equivalent": equivalent,
        "before_buffer_gets": before,
        "after_buffer_gets": after,
        "buffer_gets_reduction_pct": comparison.get("buffer_gets_reduction_pct"),
        "before_disk_reads": comparison.get("before_disk_reads"),
        "after_disk_reads": comparison.get("after_disk_reads"),
        "before_elapsed_time_us": comparison.get("before_elapsed_time_us"),
        "after_elapsed_time_us": comparison.get("after_elapsed_time_us"),
        "improved_buffer_gets": equivalent and isinstance(before, (int, float)) and isinstance(after, (int, float)) and after < before,
    }


def write_summary(outdir: pathlib.Path, rows: list[dict], started_at: str) -> None:
    payload = {"started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(), "results": rows}
    (outdir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# ASTA Prompt A/B/C 비교",
        "",
        "- A: SQL + 사용자 목표",
        "- B: SQL + 핵심 실행 메트릭",
        "- C: 현재 ASTA compact full evidence",
        "",
        "| SQL | 모드 | 상태 | 후보 | 동등 | Buffer Gets | 감소율 | Elapsed(us) | Run ID |",
        "|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        bg = f"{row.get('before_buffer_gets')} → {row.get('after_buffer_gets')}"
        et = f"{row.get('before_elapsed_time_us')} → {row.get('after_elapsed_time_us')}"
        lines.append(
            f"| {row['sample_id']} | {row['mode']} | {row.get('status')} | {row.get('candidate_generated')} | "
            f"{row.get('equivalent')} | {bg} | {row.get('buffer_gets_reduction_pct')} | {et} | {row.get('run_id')} |"
        )
    (outdir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default="asta-ui-01,asta-ui-02,asta-ui-08")
    parser.add_argument("--modes", default="A,B,C")
    parser.add_argument("--profile", default="ASTA_GPT5_PROFILE")
    parser.add_argument("--timeout", type=int, default=2100)
    parser.add_argument("--outdir", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    modes = [value.strip().upper() for value in args.modes.split(",") if value.strip()]
    if any(mode not in {"A", "B", "C"} for mode in modes):
        raise SystemExit("--modes는 A,B,C만 허용합니다")
    ids = {value.strip() for value in args.samples.split(",") if value.strip()}
    samples = load_samples(ids)
    if len(samples) != len(ids):
        raise SystemExit(f"샘플을 찾지 못했습니다: requested={sorted(ids)}, found={[s.get('id') for s in samples]}")

    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    url = ords_url()
    started_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    for sample in samples:
        for mode in modes:
            payload = {
                "sql": sample["sql"],
                "source_db_id": "DB0903_TESTDB",
                "use_llm": True,
                "run_advisor": False,
                "use_sqltune": False,
                "llm_profile": args.profile,
                "ai_profile": args.profile,
                "fetch_rows": 100,
                "benchmark_repeat": 1,
                "vector_top_k": 3,
                "tuning_context": {
                    "prompt_mode": mode,
                    "source": "ASTA_PROMPT_ABC_EXPERIMENT",
                    "user_notes": "SQL 의미와 결과를 유지하면서 반복 fact-table 접근과 불필요한 재계산을 줄이세요.",
                },
            }
            t0 = time.monotonic()
            http_status, result = post(url, payload, args.timeout)
            elapsed = round(time.monotonic() - t0, 3)
            stem = f"{sample['id']}_{mode}"
            (outdir / f"{stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            report = result.get("detailed_report_markdown") or result.get("report_markdown")
            if report:
                (outdir / f"{stem}.md").write_text(str(report), encoding="utf-8")
            row = summarize(sample, mode, http_status, elapsed, result)
            rows.append(row)
            write_summary(outdir, rows, started_at)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
