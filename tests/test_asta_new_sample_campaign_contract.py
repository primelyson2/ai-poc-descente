"""새 화면 샘플은 현재 Real ASTA의 최종 IMPROVED 근거가 있을 때만 노출한다."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "reports/asta_new_samples_20260706/campaign_summary.json"


def _ui_sample_ids() -> list[str]:
    script = r"""
const fs=require('fs');
const src=fs.readFileSync(process.argv[1], 'utf8');
const start=src.indexOf('const ASTA_SAMPLE_SQLS =');
const a=src.indexOf('[', start);
let d=0,e=-1,s=false,q='',x=false;
for(let i=a;i<src.length;i++){
  const c=src[i];
  if(s){if(x)x=false;else if(c==='\\')x=true;else if(c===q)s=false;continue;}
  if(c==='"'||c==="'"){s=true;q=c;continue;}
  if(c==='[')d++;
  if(c===']'&&--d===0){e=i+1;break;}
}
console.log(JSON.stringify(eval(src.slice(a,e)).map(sample => sample.id)));
"""
    source = ROOT / "static/js/extensions/tuning_assistant.js"
    return json.loads(subprocess.check_output(["node", "-e", script, str(source)], text=True, cwd=ROOT))


def test_ui_contains_protected_01_plus_only_campaign_final_improved_samples():
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    successful_ids = [
        item["sample_id"]
        for item in campaign["candidates"]
        if item.get("final_verdict") == "IMPROVED"
    ]
    assert campaign["successful_sample_count"] == len(successful_ids)
    assert _ui_sample_ids() == ["asta-awr-01", *successful_ids]


def test_blocked_preflight_never_claims_source_or_final_gate_execution():
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    if campaign["status"] == "BLOCKED_PRECHECK":
        assert campaign["successful_sample_count"] == 0
        assert campaign["source_sql_execution_count"] == 0
        assert campaign["asta_e2e_execution_count"] == 0
        assert all(item["status"] == "NOT_EXECUTED" for item in campaign["candidates"])


def test_completed_campaign_has_fourteen_real_improved_samples_with_full_evidence():
    campaign = json.loads(CAMPAIGN.read_text(encoding="utf-8"))

    assert campaign["target_sample_count"] == 14
    assert campaign["status"] == "COMPLETED"
    assert campaign["successful_sample_count"] == 14
    assert campaign["source_sql_execution_count"] >= 14
    assert campaign["asta_e2e_execution_count"] >= 14
    assert len(campaign["candidates"]) == 14

    for item in campaign["candidates"]:
        assert item["run_id"].startswith("OADT2-ASTA-")
        assert item["source_wall_elapsed_sec"] < 60
        assert item["source_status"] == "COMPLETED"
        assert item["sql_safety"] == "SELECT_WITH_ONLY_BOUNDED"
        assert item["final_verdict"] == "IMPROVED"
        assert item["candidate_status"] == "VALID"
        assert item["equivalence_status"] == "VERIFIED"
        assert item["optimizer_intent_status"] == "VERIFIED"
        assert item["measurement_status"] == "ACCEPTED"
        assert item["bind_status"] in {"VERIFIED", "NOT_APPLICABLE"}
        assert item["before"]["elapsed_us"] > 0
        assert item["after"]["elapsed_us"] > 0
        assert item["before"]["buffer_gets"] >= 0
        assert item["after"]["buffer_gets"] >= 0
        assert item["elapsed_improvement_pct"] > 0
        assert item["sql_sha256"]
