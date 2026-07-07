"""Real ASTA 배치 샘플 5개의 UI 및 실측 근거 계약."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from tools.asta_batch_samples import BATCH_SAMPLES


ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = ROOT / "static/js/extensions/tuning_assistant.js"
ARTIFACT = ROOT / "reports" / "asta_batch_samples_20260707" / "verification.json"


def view_text() -> str:
    return VIEW_PATH.read_text(encoding="utf-8")


def awr_blocks(view: str):
    return re.findall(
        r'\{\s*id: "asta-awr-(\d{2})",(?P<body>.*?)\n\s*\},',
        view,
        flags=re.DOTALL,
    )


def _ui_samples() -> list[dict]:
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
console.log(JSON.stringify(eval(src.slice(a,e))));
"""
    source = ROOT / "static/js/extensions/tuning_assistant.js"
    return json.loads(subprocess.check_output(["node", "-e", script, str(source)], text=True, cwd=ROOT))


def test_customer_sample_and_fourteen_full_gate_samples_are_exposed():
    blocks = awr_blocks(view_text())
    assert [number for number, _ in blocks] == [f"{index:02d}" for index in range(1, 16)]
    for number, body in blocks:
        if number == "01":
            assert 'sqlId: "7rcw6d3us86r7"' in body
            assert 'label: "SESL0640.selectList"' in body
        assert 'workload: "OLTP"' in body
        assert "sql: `" in body


def test_legacy_or_malicious_samples_are_not_restored():
    view = view_text()
    assert 'id: "asta-ui-' not in view
    assert "ASTA_UI_MALICIOUS_" not in view


def test_awr_samples_are_single_read_only_sql_without_sqlplus_binds():
    blocks = awr_blocks(view_text())
    assert len(blocks) == 15
    for _, body in blocks:
        assert re.search(r"sql: `(?:SELECT|WITH|/\*)", body, re.IGNORECASE)
        assert ":v_" not in body
        assert "FOR UPDATE" not in body.upper()
        assert not re.search(r"^\s*(variable|exec)\s", body, re.MULTILINE | re.IGNORECASE)


def test_sample_selection_sets_workload_and_refreshes_description():
    view = view_text()
    apply_sample = view[view.index("function applySampleSql"):view.index("function updateLineNumbers")]
    assert 'const workloadType = sample.workload || "OLTP"' in apply_sample
    assert "workloadSelect.value = workloadType" in apply_sample
    assert "updateWorkloadDescription(workloadType)" in apply_sample
    assert 'id="asta-workload-description"' in view
    assert 'workloadSelect.addEventListener("change"' in view


def test_reset_defaults_to_oltp():
    view = view_text()
    reset = view[view.index("function resetWorkspace"):view.index("function optimizationGoalForWorkload")]
    assert 'workloadSelect.value = "OLTP"' in reset
    assert 'updateWorkloadDescription("OLTP")' in reset


def test_ui_exposes_five_verified_batch_samples_after_existing_samples():
    samples = _ui_samples()
    batch = samples[-5:]

    assert [item["id"] for item in batch] == [f"asta-batch-{index:02d}" for index in range(1, 6)]
    assert all(item["workload"] == "BATCH" for item in batch)
    assert all(item["pattern"] for item in batch)
    assert all(item["sql"].lstrip().upper().startswith(("SELECT", "WITH")) for item in batch)
    assert all(";" not in item["sql"] for item in batch)
    assert all(len(item["sql"].encode()) < 32767 for item in batch)
    assert all(len(item["candidate_sql"].encode()) < 32767 for item in BATCH_SAMPLES)


def test_batch_samples_have_real_runtime_equivalence_and_improvement_evidence():
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    ui_by_id = {item["id"]: item for item in _ui_samples()}
    definitions = {item["id"]: item for item in BATCH_SAMPLES}

    assert payload["status"] == "COMPLETED"
    assert payload["source_db_id"] == "DB0903_TESTDB"
    assert len(payload["samples"]) == 5
    for item in payload["samples"]:
        assert item["workload"] == "BATCH"
        assert item["original"]["status"] == "COMPLETED"
        assert 35 <= item["original"]["elapsed_sec"] <= 75
        assert item["candidate"]["status"] == "COMPLETED"
        assert item["candidate"]["elapsed_sec"] > 0
        assert item["candidate"]["elapsed_sec"] < item["original"]["elapsed_sec"]
        assert item["elapsed_improvement_pct"] >= 20
        assert item["equivalence_status"] == "VERIFIED"
        assert item["result_digest_scope"] == "FULL_RESULT"
        assert item["result_digest_matches"] is True
        assert item["sql_sha256"]
        assert item["candidate_sql_sha256"]
        assert hashlib.sha256(ui_by_id[item["sample_id"]]["sql"].encode()).hexdigest() == item["sql_sha256"]
        assert hashlib.sha256(definitions[item["sample_id"]]["candidate_sql"].encode()).hexdigest() == item["candidate_sql_sha256"]
