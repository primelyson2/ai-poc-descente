"""실환경 최종 gate를 통과한 ASTA 화면 샘플만 노출하는 계약."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_sample_ids() -> list[str]:
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
    js_path = ROOT / "static/js/extensions/tuning_assistant.js"
    return json.loads(subprocess.check_output(["node", "-e", script, str(js_path)], text=True, cwd=ROOT))


EXPECTED_RETAINED_SAMPLE_IDS = [f"asta-awr-{index:02d}" for index in range(1, 16)]
ARTIFACT = ROOT / "reports/asta_sample_gate_validation_20260706/summary.json"
CURRENT_CAMPAIGN = ROOT / "reports/asta_new_samples_20260706/campaign_summary.json"


def test_ui_exposes_only_samples_with_final_improved_evidence():
    assert load_sample_ids() == EXPECTED_RETAINED_SAMPLE_IDS
    campaign = json.loads(CURRENT_CAMPAIGN.read_text(encoding="utf-8"))
    assert campaign["status"] == "COMPLETED"
    assert ["asta-awr-01", *campaign["added_sample_ids"]] == EXPECTED_RETAINED_SAMPLE_IDS
    assert all(item["final_verdict"] == "IMPROVED" for item in campaign["candidates"])


def test_final_gate_artifact_has_a_terminal_decision_for_every_original_sample():
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    records = {record["sample_id"]: record for record in artifact["samples"]}
    assert sorted(records) == [f"asta-awr-{index:02d}" for index in range(1, 16)]
    assert artifact["retained_sample_ids"] == ["asta-awr-01"]
    assert artifact["removed_sample_ids"] == [f"asta-awr-{index:02d}" for index in range(2, 16)]
    assert records["asta-awr-01"]["verdict"] == "IMPROVED"
    for sample_id in artifact["removed_sample_ids"]:
        assert records[sample_id]["verdict"] in {
            "BLOCKED", "FAILED", "NO_REWRITE", "NOT_IMPROVED",
            "NON_EQUIVALENT", "INSUFFICIENT_EVIDENCE",
        }
        assert records[sample_id]["action"] == "REMOVE"
