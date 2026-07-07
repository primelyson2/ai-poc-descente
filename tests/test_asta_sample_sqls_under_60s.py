import hashlib
import json
import re
import subprocess
from pathlib import Path

from tools import asta_quality_agent


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "tests/fixtures/asta_sample_01_contract.json").read_text(encoding="utf-8"))
VERIFICATION = ROOT / "reports/asta_sample_sqls_under_60s/verification.json"
FINAL_GATE = ROOT / "reports/asta_sample_gate_validation_20260706/summary.json"


def load_samples() -> list[dict]:
    js_path = ROOT / "static/js/extensions/tuning_assistant.js"
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
    output = subprocess.check_output(["node", "-e", script, str(js_path)], text=True, cwd=ROOT)
    return json.loads(output)


def object_references(sql: str) -> set[str]:
    tokens = asta_quality_agent._sql_tokens(sql)
    pairs = asta_quality_agent._parenthesis_pairs(tokens)
    ctes = {item["name"] for item in asta_quality_agent._cte_scopes(tokens, pairs)}
    refs = set()
    for ref in asta_quality_agent._object_references(tokens):
        if ref["schema"] is None and ref["base_object"] in ctes:
            continue
        refs.add(ref["object"])
    return refs


def normalized_words(sql: str) -> list[str]:
    return [token["upper"] for token in asta_quality_agent._sql_tokens(sql) if token["kind"] == "WORD"]


def test_sample_01_id_label_and_sql_bytes_are_immutable():
    sample = load_samples()[0]
    encoded = sample["sql"].encode("utf-8")
    assert sample["id"] == CONTRACT["id"]
    assert sample["label"] == CONTRACT["label"]
    assert len(encoded) == CONTRACT["sql_bytes"]
    assert hashlib.sha256(encoded).hexdigest() == CONTRACT["sql_sha256"]
    assert sorted(object_references(sample["sql"])) == CONTRACT["object_allowlist"]


def test_ui_has_protected_customer_sample_plus_fourteen_current_improved_samples():
    samples = load_samples()
    oltp_samples = samples[:15]
    assert [sample["id"] for sample in oltp_samples] == [f"asta-awr-{index:02d}" for index in range(1, 16)]
    assert len({sample["label"] for sample in oltp_samples}) == 15
    assert len({hashlib.sha256(sample["sql"].encode()).hexdigest() for sample in oltp_samples}) == 15


def test_remaining_samples_are_safe_selects_using_only_sample_01_objects():
    allowlist = set(CONTRACT["object_allowlist"])
    banned = {"INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE", "BEGIN", "DECLARE", "CALL", "EXECUTE"}
    for sample in load_samples():
        sql = sample["sql"].strip()
        words = normalized_words(sql)
        assert words[0] in {"SELECT", "WITH"}
        assert not banned.intersection(words)
        assert not re.search(r"\b(DBMS_LOCK|SLEEP)\b", sql, re.I)
        assert "@" not in sql
        refs = object_references(sql)
        assert refs
        assert refs <= allowlist
        assert all("." in ref for ref in refs)
        assert re.search(r"\b(?:[A-Z][A-Z0-9_$#]*\.)?COMP_CD\s*=\s*'01'", sql, re.I)
        assert re.search(r"\b(BETWEEN|ROWNUM\s*<=|FETCH\s+FIRST|STYLE_CD\s+IN)\b", sql, re.I)


def test_final_gate_artifact_requires_only_improved_samples_to_remain_visible():
    artifact = json.loads(FINAL_GATE.read_text(encoding="utf-8"))
    assert artifact["retained_sample_ids"] == ["asta-awr-01"]
    assert artifact["removed_sample_ids"] == [f"asta-awr-{index:02d}" for index in range(2, 16)]
    records = {item["sample_id"]: item for item in artifact["samples"]}
    assert records["asta-awr-01"]["verdict"] == "IMPROVED"
    for sample_id in artifact["removed_sample_ids"]:
        assert records[sample_id]["verdict"] != "IMPROVED"
        assert records[sample_id]["action"] == "REMOVE"


def test_historical_source_verification_artifact_remains_auditable_after_ui_removal():
    artifact = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    records = artifact["samples"]
    assert artifact["sample_01_contract_sha256"] == CONTRACT["sql_sha256"]
    assert artifact["object_allowlist"] == CONTRACT["object_allowlist"]
    assert len(records) == 14
    assert {item["sample_id"] for item in records} == {f"asta-awr-{index:02d}" for index in range(2, 16)}
    for item in records:
        assert item["status"] == "COMPLETED"
        assert 0 <= item["elapsed_sec"] < 60
        assert item["timeout"] is False
        assert item["session_usable_after"] is True
        assert item["outside_allowlist"] == []
        assert item["sql_sha256"]
        assert item["fetched_rows"] >= 0
        assert "sql" not in item
