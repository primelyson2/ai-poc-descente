"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

import asyncio
from datetime import datetime, timedelta, timezone
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


def test_fastapi_default_llm_profile_is_gpt5():
    """ASTA 계약/회귀 조건을 검증한다: fastapi default llm profile is gpt5."""
    assert asta_proxy.DEFAULT_LLM_PROFILE == "ASTA_GPT5_PROFILE"


def test_runtime_observation_fresh_and_stale_heartbeat():
    now = datetime.now(timezone.utc)
    record = {"status": "RUNNING", "heartbeat_at": now.isoformat(), "upstream_request_active": True,
              "progress": [{"code": "BEFORE_EVIDENCE", "status": "RUNNING", "started_at": (now - timedelta(seconds=7)).isoformat()}]}
    fresh = asta_proxy._runtime_fields(record, now=now)
    assert fresh["worker_alive"] is True
    assert fresh["observation_level"] == "PROXY_WORKER_ALIVE"
    assert 6900 <= fresh["stage_elapsed_ms"] <= 7100
    record["heartbeat_at"] = (now - timedelta(seconds=21)).isoformat()
    stale = asta_proxy._runtime_fields(record, now=now)
    assert stale["worker_alive"] is False
    assert stale["stale_warning"] is True
    assert stale["observation_level"] == "STALE_OR_FAILED"


def test_missing_local_worker_is_honestly_unknown():
    fields = asta_proxy._runtime_fields(None)
    assert fields["worker_alive"] is None
    assert fields["observation_level"] == "SOURCE_OBSERVATION_UNAVAILABLE"
    assert fields["source_observation"]["status"] == "UNAVAILABLE"


def test_background_heartbeat_updates_and_stops(monkeypatch):
    asta_proxy.ASYNC_RUNS.clear()
    released = asyncio.Event()

    async def blocked(*_args):
        await released.wait()
        return {"status": "COMPLETED"}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", blocked)
    monkeypatch.setattr(asta_proxy, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(asta_proxy.asta_audit, "write_run_index", lambda *_a, **_k: None)
    monkeypatch.setattr(asta_proxy.asta_audit, "write_event", lambda *_a, **_k: None)

    async def scenario():
        await asta_proxy._store_async_run("r", {"run_id": "r", "status": "RUNNING", "progress": []})
        task = asyncio.create_task(asta_proxy._run_ords_analyze_background("r", "u", {}, 1, {"request_id": "q"}, "db"))
        await asyncio.sleep(.035)
        during = await asta_proxy._get_async_run("r")
        released.set()
        await task
        return during, await asta_proxy._get_async_run("r")

    during, done = asyncio.run(scenario())
    assert during["heartbeat_at"]
    assert during["upstream_request_active"] is True
    assert done["upstream_request_active"] is False
    assert done["worker_alive"] is False


def test_report_viewer_renders_safe_readable_html(monkeypatch):
    markdown = """# ASTA 결과 <script>alert(1)</script>

| 항목 | 값 |
| --- | --- |
| Plan | 개선 |

```sql
select '<script>' from dual;
```

[내부 결과서](/api/asta/runs/OLD/report) [외부](javascript:alert(1))
"""

    calls = []
    async def fake_lookup(*args):
        calls.append(args)
        return {"run_id": "RUN-1", "report_markdown": markdown}

    monkeypatch.setattr(asta_proxy, "_audited_run_lookup", fake_lookup)
    response = asyncio.run(asta_proxy.get_run_report_view("RUN-1", "devdoADB"))
    assert calls == [("RUN-1", "devdoADB", "report_view", "report")]
    body = response.body.decode()
    assert response.media_type == "text/html"
    assert "<h1>ASTA 결과 &lt;script&gt;alert(1)&lt;/script&gt;</h1>" in body
    assert "<table>" in body and "<pre><code class=\"language-sql\">" in body
    assert "<script>" not in body and "javascript:" not in body
    assert "/api/asta/runs/OLD/report/view" in body
    assert "/api/asta/runs/RUN-1/report/download" in body
    assert response.headers["content-security-policy"].startswith("default-src 'none'")


def test_report_markdown_download_keeps_json_api_separate(monkeypatch):
    payload = {"run_id": "RUN-1", "detailed_report_markdown": "# 원본\n\n내용"}

    calls = []
    async def fake_lookup(*args):
        calls.append(args)
        return payload

    monkeypatch.setattr(asta_proxy, "_audited_run_lookup", fake_lookup)
    download = asyncio.run(asta_proxy.download_run_report("RUN-1", "devdoADB"))
    assert calls[-1] == ("RUN-1", "devdoADB", "report_download", "report")
    assert download.media_type == "text/markdown"
    assert download.body.decode() == "# 원본\n\n내용"
    assert download.headers["content-disposition"] == 'attachment; filename="asta-report-RUN-1.md"'
    assert asyncio.run(asta_proxy.get_run_report("RUN-1", "devdoADB")) == payload
