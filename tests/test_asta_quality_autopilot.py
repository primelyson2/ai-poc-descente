"""ASTA quality autopilot의 회귀 판정 테스트."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.asta_quality_autopilot import failed_tests, is_allowed


def test_failed_tests_extracts_pytest_node_ids():
    output = "FAILED tests/test_a.py::test_one - AssertionError\nFAILED tests/test_b.py::test_two\n2 failed"
    assert failed_tests(output) == {"tests/test_a.py::test_one", "tests/test_b.py::test_two"}


def test_only_quality_source_paths_are_allowed():
    assert is_allowed("db/adb/asta_llm_pkg.sql")
    assert is_allowed("tests/test_new.py")
    assert not is_allowed("config.yaml")
    assert not is_allowed("wallets/secret.pem")
