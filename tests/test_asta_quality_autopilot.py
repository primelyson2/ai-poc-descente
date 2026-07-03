"""ASTA quality autopilot의 회귀 판정 테스트."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.asta_quality_autopilot import ROOT, codex_command, deployment_commands, failed_tests, is_allowed


def test_failed_tests_extracts_pytest_node_ids():
    output = "FAILED tests/test_a.py::test_one - AssertionError\nFAILED tests/test_b.py::test_two\n2 failed"
    assert failed_tests(output) == {"tests/test_a.py::test_one", "tests/test_b.py::test_two"}


def test_only_quality_source_paths_are_allowed():
    assert is_allowed("db/adb/asta_llm_pkg.sql")
    assert is_allowed("db/source/asta_source_pkg.sql")
    assert is_allowed("tests/test_new.py")
    assert not is_allowed("config.yaml")
    assert not is_allowed("wallets/secret.pem")


def test_codex_runs_non_interactively_inside_workspace_sandbox():
    command = codex_command("improve it")
    assert command == [
        "codex", "--ask-for-approval", "never", "exec",
        "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), "improve it",
    ]


def test_changed_packages_are_deployed_and_adb_is_smoke_tested():
    commands = deployment_commands({"db/source/asta_source_pkg.sql", "db/adb/asta_llm_pkg.sql"})
    assert [name for name, _, _ in commands] == ["source_deploy", "adb_deploy", "adb_smoke"]


def test_non_database_changes_do_not_trigger_deployment():
    assert deployment_commands({"tests/test_new.py", "docs/note.md"}) == []
