"""ASTA loop agent의 점수 및 안전 정책 단위 테스트."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import asta_loop_agent
from tools.asta_loop_agent import allowed_changes, load_config, render_command, safe_name
from tools.run_asta_10_sqls import batch_is_healthy


def test_load_config_requires_list_commands(tmp_path: Path):
    path = tmp_path / "loop.yaml"
    path.write_text("checks:\n  - name: unit\n    command: pytest -q\n", encoding="utf-8")
    with pytest.raises(ValueError, match="문자열 배열"):
        load_config(path)


def test_allowed_changes_rejects_credentials_and_deploy_config():
    ok, denied = allowed_changes(
        {"app/main.py", "tests/test_new.py", "config.yaml"},
        ["app", "tests"],
    )
    assert not ok
    assert denied == ["config.yaml"]


def test_allowed_changes_does_not_accept_similar_prefix():
    ok, denied = allowed_changes({"app-secret/token.txt"}, ["app"])
    assert not ok
    assert denied == ["app-secret/token.txt"]


def test_render_command_expands_only_known_placeholders(tmp_path: Path):
    brief = tmp_path / "brief.md"
    command = render_command(["agent", "--input", "{brief}", "--out", "{iteration_dir}"], brief, tmp_path)
    assert command == ["agent", "--input", str(brief), "--out", str(tmp_path)]


def test_safe_name_is_stable_for_report_paths():
    assert safe_name("ASTA 10-SQL / live") == "asta_10_sql_live"


def test_10_sql_gate_requires_complete_deterministic_results():
    good = [{"http_status": 200, "summary": {"status": "COMPLETED", "verdict": "IMPROVED"}}]
    assert batch_is_healthy(good, expected_count=1)
    good[0]["summary"]["verdict"] = "UNKNOWN"
    assert not batch_is_healthy(good, expected_count=1)


def test_rejected_iteration_preserves_previously_accepted_changes(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=ASTA Test", "-c", "user.email=asta@example.invalid", "commit", "-qm", "base"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.setattr(asta_loop_agent, "ROOT", tmp_path)

    tracked.write_text("accepted\n", encoding="utf-8")
    accepted_new = tmp_path / "accepted_new.txt"
    accepted_new.write_text("accepted new\n", encoding="utf-8")
    before_patch = tmp_path / ".before.patch"
    backup_dir = tmp_path / ".backup"
    asta_loop_agent.capture_patch(before_patch)
    asta_loop_agent.backup_untracked({"accepted_new.txt"}, backup_dir)

    tracked.write_text("rejected\n", encoding="utf-8")
    accepted_new.write_text("rejected edit\n", encoding="utf-8")
    rejected_new = tmp_path / "rejected_new.txt"
    rejected_new.write_text("remove me\n", encoding="utf-8")
    candidate_patch = tmp_path / ".candidate.patch"
    asta_loop_agent.capture_patch(candidate_patch)
    asta_loop_agent.rollback_changes(
        candidate_patch,
        before_patch,
        {"accepted_new.txt"},
        backup_dir,
        {"rejected_new.txt"},
    )

    assert tracked.read_text(encoding="utf-8") == "accepted\n"
    assert accepted_new.read_text(encoding="utf-8") == "accepted new\n"
    assert not rejected_new.exists()
