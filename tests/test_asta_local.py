"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import deps
from app.config import AppConfig, DatabaseConfig
from app.routers import asta_proxy


class DummyRequest:
    """ASTA 처리 흐름에서 DummyRequest 작업을 수행한다."""
    def __init__(self, payload):
        """ASTA 내부 처리 보조 함수: init."""
        self._payload = payload

    async def json(self):
        """ASTA 처리 흐름에서 json 작업을 수행한다."""
        return self._payload


def _cfg():
    """ASTA 내부 처리 보조 함수: cfg."""
    return AppConfig(
        default_database="devdoADB",
        databases=[
            DatabaseConfig(
                name="devdoADB",
                label="DEVDO ADB",
                user="u",
                password="p",
                dsn="dsn",
                wallet_location="",
                wallet_password="",
                config_dir="",
                asta={
                    "ords_base_url": "https://ords.example/ords/asta",
                    "analyze_path": "/analyze",
                    "profiles_path": "/profiles",
                },
            )
        ],
    )


def test_asta_profiles_are_loaded_from_ords(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: asta profiles are loaded from ords."""
    deps.set_config(_cfg())
    calls = []

    async def fake_get(url, timeout):
        """ASTA 처리 흐름에서 fake get 작업을 수행한다."""
        calls.append((url, timeout))
        return {
            "asta_default": "ASTA_LOCAL",
            "profiles": [
                {"name": "ASTA_LOCAL", "status": "ENABLED", "display_name": "local ASTA"},
                {"name": "OPENAI_CHAT", "status": "ENABLED", "display_name": "not asta"},
            ],
        }

    monkeypatch.setattr(asta_proxy, "_get_json_from_ords", fake_get)

    data = asyncio.run(asta_proxy.profiles(database="devdoADB"))

    assert data["source"] == "ADB_ORDS"
    assert data["asta_default"] == "ASTA_LOCAL"
    assert [p["name"] for p in data["profiles"]] == ["ASTA_LOCAL"]
    assert calls == [("https://ords.example/ords/asta/profiles", 2100)]


def test_asta_analyze_uses_ords_first_proxy(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: asta analyze uses ords first proxy."""
    deps.set_config(_cfg())
    posted = []

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        posted.append({"url": url, "payload": payload, "timeout": timeout})
        return {
            "run_id": "OADT2-ASTA-abc123",
            "status": "COMPLETED",
            "progress": [{"code": "SQL_GUARD", "status": "DONE"}],
            "detailed_report_markdown": "# AI SQL Tuning Assistant Report",
        }

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)

    result = asyncio.run(
        asta_proxy.analyze(DummyRequest({"sql": "select * from dual", "llm_profile": "ASTA_LOCAL"}), database="devdoADB")
    )

    assert result["proxy"]["source"] == "ADB_ORDS"
    assert result["detailed_report_markdown"].startswith("# AI SQL")
    assert posted[0]["url"] == "https://ords.example/ords/asta/analyze"
    assert posted[0]["payload"]["sql"] == "select * from dual"
    assert posted[0]["payload"]["llm_profile"] == "ASTA_LOCAL"


def test_asta_analyze_does_not_perform_python_sql_guard_or_source_db_calls(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: asta analyze does not perform python sql guard or source db calls."""
    deps.set_config(_cfg())

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        return {"status": "FAILED", "error": {"code": "SQL_GUARD", "message": "Only SELECT"}}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)
    assert not hasattr(asta_proxy, "db")
    assert not hasattr(asta_proxy, "_source_runtime_xplan")

    result = asyncio.run(asta_proxy.analyze(DummyRequest({"sql": "drop table t"}), database="devdoADB"))

    assert result["proxy"]["source"] == "ADB_ORDS"
    assert result["status"] == "FAILED"
