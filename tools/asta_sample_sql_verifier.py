#!/usr/bin/env python3
"""Sequential, bounded Source DB verification for ASTA UI sample SQLs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import oracledb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.asta_deploy_adb import connect as connect_adb
from tools import asta_quality_agent


CONTRACT_PATH = ROOT / "tests/fixtures/asta_sample_01_contract.json"
OUTPUT_PATH = ROOT / "reports/asta_sample_sqls_under_60s/verification.json"


def load_samples() -> list[dict]:
    js_path = ROOT / "static/js/extensions/tuning_assistant.js"
    script = r"""
const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');
const start=src.indexOf('const ASTA_SAMPLE_SQLS =');const a=src.indexOf('[',start);
let d=0,e=-1,s=false,q='',x=false;
for(let i=a;i<src.length;i++){const c=src[i];if(s){if(x)x=false;else if(c==='\\')x=true;else if(c===q)s=false;continue;}if(c==='"'||c==="'"){s=true;q=c;continue;}if(c==='[')d++;if(c===']'&&--d===0){e=i+1;break;}}
console.log(JSON.stringify(eval(src.slice(a,e))));
"""
    return json.loads(subprocess.check_output(["node", "-e", script, str(js_path)], text=True, cwd=ROOT))


def referenced_objects(sql: str) -> set[str]:
    tokens = asta_quality_agent._sql_tokens(sql)
    pairs = asta_quality_agent._parenthesis_pairs(tokens)
    ctes = {item["name"] for item in asta_quality_agent._cte_scopes(tokens, pairs)}
    return {
        ref["object"]
        for ref in asta_quality_agent._object_references(tokens)
        if not (ref["schema"] is None and ref["base_object"] in ctes)
    }


def describe_allowlist() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    print(json.dumps({"object_allowlist": contract["object_allowlist"]}, ensure_ascii=False, indent=2))
    return 0


def verify(timeout_sec: float = 55.0, fetch_rows: int = 200) -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    allowlist = set(contract["object_allowlist"])
    samples = load_samples()[1:]
    if len(samples) != 14:
        raise RuntimeError(f"expected 14 new samples, found {len(samples)}")
    output = {
        "verified_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "source_db_id": "DB0903_TESTDB",
        "sample_01_contract_sha256": contract["sql_sha256"],
        "object_allowlist": sorted(allowlist),
        "timeout_limit_sec": timeout_sec,
        "fetch_limit": fetch_rows,
        "samples": [],
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_adb()
    conn.call_timeout = int(timeout_sec * 1000)
    try:
        for sample in samples:
            cur = conn.cursor()
            cur.arraysize = min(fetch_rows, 100)
            objects = referenced_objects(sample["sql"])
            record = {
                "sample_id": sample["id"],
                "label": sample["label"],
                "pattern": sample.get("pattern"),
                "sql_sha256": hashlib.sha256(sample["sql"].encode("utf-8")).hexdigest(),
                "objects": sorted(objects),
                "outside_allowlist": sorted(objects - allowlist),
                "status": "FAILED",
                "elapsed_sec": 0.0,
                "fetched_rows": 0,
                "timeout": False,
                "session_usable_after": False,
            }
            if record["outside_allowlist"]:
                output["samples"].append(record)
                continue
            started = time.monotonic()
            timer = threading.Timer(max(0.1, timeout_sec - 0.25), conn.cancel)
            timer.daemon = True
            timer.start()
            try:
                run_id = f"ASTA-SAMPLE-{sample['id']}-{int(time.time())}"[:64]
                value = cur.callfunc(
                    "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE",
                    oracledb.DB_TYPE_CLOB,
                    ["DB0903_TESTDB", sample["sql"], run_id, fetch_rows, "ONCE", "N",
                     min(55, int(timeout_sec)), None, "BOUNDED", fetch_rows],
                )
                evidence = json.loads(value.read() if hasattr(value, "read") else str(value or "{}"))
                record["fetched_rows"] = int(evidence.get("row_count") or evidence.get("last_output_rows") or 0)
                record["source_elapsed_us"] = evidence.get("last_elapsed_time_us")
                record["status"] = str(evidence.get("status") or "FAILED").upper()
                if record["status"] != "COMPLETED":
                    error = evidence.get("error") if isinstance(evidence.get("error"), dict) else {}
                    record["error_code"] = error.get("code") or "SOURCE_EVIDENCE_FAILED"
            except oracledb.Error as exc:
                error = exc.args[0] if exc.args else None
                code = getattr(error, "code", None)
                record["error_code"] = f"ORA-{int(code):05d}" if isinstance(code, int) else type(exc).__name__
                record["timeout"] = time.monotonic() - started >= timeout_sec - 1 or code in {1013, 3136}
                try:
                    conn.rollback()
                except oracledb.Error:
                    pass
            finally:
                timer.cancel()
                record["elapsed_sec"] = round(time.monotonic() - started, 6)
                cur.close()
            try:
                ping = conn.cursor()
                ping.execute("select 1 from dual")
                record["session_usable_after"] = ping.fetchone()[0] == 1
                ping.close()
            except oracledb.Error:
                record["session_usable_after"] = False
            output["samples"].append(record)
            OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: record[key] for key in ("sample_id", "status", "elapsed_sec", "fetched_rows", "timeout", "session_usable_after")}, ensure_ascii=False), flush=True)
    finally:
        conn.close()
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    success = all(
        item["status"] == "COMPLETED"
        and item["elapsed_sec"] < 60
        and item["timeout"] is False
        and item["outside_allowlist"] == []
        and item["session_usable_after"] is True
        for item in output["samples"]
    )
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("describe", "verify"))
    parser.add_argument("--timeout-sec", type=float, default=55.0)
    parser.add_argument("--fetch-rows", type=int, default=200)
    args = parser.parse_args()
    return describe_allowlist() if args.action == "describe" else verify(args.timeout_sec, args.fetch_rows)


if __name__ == "__main__":
    raise SystemExit(main())
