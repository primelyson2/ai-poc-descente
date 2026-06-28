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
                asta={"ords_base_url": "https://example.com/ords/asta", "profiles_path": "/profiles"},
            )
        ],
    )


def test_asta_profile_filter_keeps_only_asta_profiles():
    """ASTA 계약/회귀 조건을 검증한다: asta profile filter keeps only asta profiles."""
    sample = {
        "asta_default": "ASTA_GPT55_PROFILE",
        "profiles": [
            {"name": "ASTA_GPT55_PROFILE", "provider": "OpenAI", "model": "gpt-5.5", "selectable": True},
            {"name": "ASTA_GROK_REASONING_PROFILE", "provider": "xAI", "model": "xai.grok", "selectable": True},
            {"name": "OPENAI_GPT55_NL2SQL", "provider": "OpenAI", "model": "gpt-5.5", "selectable": True},
            {"name": "ASTA_HIDDEN", "selectable": False},
        ],
    }

    profiles = asta_proxy._filter_asta_profiles(sample)
    names = [p["name"] for p in profiles]

    assert "ASTA_GPT55_PROFILE" in names
    assert "ASTA_GROK_REASONING_PROFILE" in names
    assert "OPENAI_GPT55_NL2SQL" not in names


def test_profiles_loader_uses_ords_not_database(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: profiles loader uses ords not database."""
    deps.set_config(_cfg())
    calls = []

    async def fake_get(url, timeout):
        """ASTA 처리 흐름에서 fake get 작업을 수행한다."""
        calls.append((url, timeout))
        return {
            "asta_default": "ASTA_GPT55_PROFILE",
            "profiles": [
                {"name": "ASTA_GPT55_PROFILE", "provider": "OpenAI", "model": "gpt", "selectable": True},
                {"name": "OPENAI_GPT55_NL2SQL", "provider": "OpenAI", "model": "gpt", "selectable": True},
            ],
        }

    monkeypatch.setattr(asta_proxy, "_get_json_from_ords", fake_get)

    data = asyncio.run(asta_proxy.profiles("devdoADB"))

    assert data["source"] == "ADB_ORDS"
    assert data["asta_default"] == "ASTA_GPT55_PROFILE"
    assert [p["name"] for p in data["profiles"]] == ["ASTA_GPT55_PROFILE"]
    assert calls == [("https://example.com/ords/asta/profiles", 2100)]
    assert not hasattr(asta_proxy, "db")


def test_fastapi_default_llm_profile_is_gpt5():
    """ASTA 계약/회귀 조건을 검증한다: fastapi default llm profile is gpt5."""
    assert asta_proxy.DEFAULT_LLM_PROFILE == "ASTA_GPT5_PROFILE"
