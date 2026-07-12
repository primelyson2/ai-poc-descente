"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

import asyncio
import sys
from pathlib import Path

import pytest

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
    """FastAPI는 ADB submit 응답을 그대로 전달하고 자체 worker를 만들지 않는다."""
    deps.set_config(_cfg())
    posted = []

    async def fake_post(url, payload, timeout):
        posted.append({"url": url, "payload": payload, "timeout": timeout})
        return {"run_id": payload["run_id"], "status": "QUEUED", "execution_mode": "ADB_SCHEDULER"}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)
    result = asyncio.run(asta_proxy.analyze(DummyRequest({"sql": "select * from dual", "llm_profile": "ASTA_LOCAL"}), asta_proxy.BackgroundTasks(), database="devdoADB"))

    assert result["proxy"]["source"] == "ADB_ORDS"
    assert result["status"] == "QUEUED"
    assert result["run_id"].startswith("OADT2-ASTA-")
    assert len(posted) == 1
    assert posted[0]["payload"]["run_id"] == result["run_id"]


def test_asta_analyze_does_not_perform_python_sql_guard_or_source_db_calls(monkeypatch):
    """analyze는 Python에서 SQL 가드나 Source DB 직접 호출을 수행하지 않는다.

    ORDS(ADB)가 SQL 가드 거절을 반환하면, 프록시는 자체 재판단이나 Source 직접 우회 없이
    그 실패를 그대로 HTTP 오류로 승격한다. 로컬 Source 실행 경로(_source_runtime_xplan)는 부재한다."""
    deps.set_config(_cfg())

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        return {"status": "FAILED", "error": {"code": "SQL_GUARD", "message": "Only SELECT"}}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)
    assert not hasattr(asta_proxy, "_source_runtime_xplan")

    with pytest.raises(asta_proxy.HTTPException) as exc_info:
        asyncio.run(asta_proxy.analyze(DummyRequest({"sql": "drop table t"}), asta_proxy.BackgroundTasks(), database="devdoADB"))

    # ORDS/ADB 경계에서 온 실패이며(4xx/5xx 승격), Python 로컬 가드가 개입하지 않았다.
    assert exc_info.value.status_code in (422, 502)
    assert "Only SELECT" in str(exc_info.value.detail)


