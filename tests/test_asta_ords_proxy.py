"""작성자: 도상훈
파일 용도: ASTA ORDS/ADB 마이그레이션 계약과 회귀 조건을 정적/단위 테스트로 검증한다."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import deps
from app import asta_audit
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


def _cfg(ords_base_url="https://example.com/ords/asta"):
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
                asta={"ords_base_url": ords_base_url, "analyze_path": "/analyze", "timeout_seconds": 2100},
            )
        ],
    )


def _run_analyze_background(payload, database="devdoADB"):
    """ASTA 내부 처리 보조 함수: run analyze background."""
    background = BackgroundTasks()
    initial = asyncio.run(asta_proxy.analyze(DummyRequest(payload), background, database=database))
    for task in background.tasks:
        asyncio.run(task.func(*task.args, **task.kwargs))
    final = asyncio.run(asta_proxy.get_run_report(initial["run_id"], database=database))
    return initial, final



def test_sql_only_llm_uses_oracle_tuning_prompt(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: sql only llm uses oracle tuning prompt."""
    deps.set_config(_cfg())
    captured = {}

    class DummyCursor:
        """ASTA 처리 흐름에서 DummyCursor 작업을 수행한다."""
        def __enter__(self):
            """ASTA 내부 처리 보조 함수: enter."""
            return self

        def __exit__(self, exc_type, exc, tb):
            """ASTA 내부 처리 보조 함수: exit."""
            return False

        async def execute(self, sql, params):
            """ASTA 처리 흐름에서 execute 작업을 수행한다."""
            captured["sql"] = sql
            captured["params"] = params

        async def fetchone(self):
            """ASTA 처리 흐름에서 fetchone 작업을 수행한다."""
            return ["튜닝 결과"]

    class DummyConnection:
        """ASTA 처리 흐름에서 DummyConnection 작업을 수행한다."""
        def cursor(self):
            """ASTA 처리 흐름에서 cursor 작업을 수행한다."""
            return DummyCursor()

    class DummyAcquire:
        """ASTA 처리 흐름에서 DummyAcquire 작업을 수행한다."""
        async def __aenter__(self):
            """ASTA 내부 처리 보조 함수: aenter."""
            return DummyConnection()

        async def __aexit__(self, exc_type, exc, tb):
            """ASTA 내부 처리 보조 함수: aexit."""
            return False

    class DummyPool:
        """ASTA 처리 흐름에서 DummyPool 작업을 수행한다."""
        def acquire(self):
            """ASTA 처리 흐름에서 acquire 작업을 수행한다."""
            return DummyAcquire()

    monkeypatch.setattr(asta_proxy.db, "get_pool", lambda database: DummyPool())

    result = asyncio.run(
        asta_proxy.llm_sql_only(
            DummyRequest({"sql": "select * from sales", "llm_profile": "ASTA_GPT5_PROFILE"}),
            database="devdoADB",
        )
    )

    prompt = captured["params"]["prompt"]
    assert result["status"] == "COMPLETED"
    assert result["raw_response_empty"] is False
    assert "Oracle Database 기준으로 SQL 튜닝을 요청합니다." in prompt
    assert "Oracle 옵티마이저 관점" in prompt
    assert "SELECT/WITH 단일문" in prompt
    assert "select * from sales" in prompt
    assert captured["params"]["profile"] == "ASTA_GPT5_PROFILE"


def test_sql_only_llm_prefers_payload_prompt(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: sql only llm prefers payload prompt."""
    deps.set_config(_cfg())
    captured = {}

    class DummyCursor:
        """ASTA 처리 흐름에서 DummyCursor 작업을 수행한다."""
        def __enter__(self):
            """ASTA 내부 처리 보조 함수: enter."""
            return self

        def __exit__(self, exc_type, exc, tb):
            """ASTA 내부 처리 보조 함수: exit."""
            return False

        async def execute(self, sql, params):
            """ASTA 처리 흐름에서 execute 작업을 수행한다."""
            captured["params"] = params

        async def fetchone(self):
            """ASTA 처리 흐름에서 fetchone 작업을 수행한다."""
            return [""]

    class DummyConnection:
        """ASTA 처리 흐름에서 DummyConnection 작업을 수행한다."""
        def cursor(self):
            """ASTA 처리 흐름에서 cursor 작업을 수행한다."""
            return DummyCursor()

    class DummyAcquire:
        """ASTA 처리 흐름에서 DummyAcquire 작업을 수행한다."""
        async def __aenter__(self):
            """ASTA 내부 처리 보조 함수: aenter."""
            return DummyConnection()

        async def __aexit__(self, exc_type, exc, tb):
            """ASTA 내부 처리 보조 함수: aexit."""
            return False

    class DummyPool:
        """ASTA 처리 흐름에서 DummyPool 작업을 수행한다."""
        def acquire(self):
            """ASTA 처리 흐름에서 acquire 작업을 수행한다."""
            return DummyAcquire()

    monkeypatch.setattr(asta_proxy.db, "get_pool", lambda database: DummyPool())

    result = asyncio.run(
        asta_proxy.llm_sql_only(
            DummyRequest({"sql": "select 1 from dual", "prompt": "CUSTOM ORACLE TUNING PROMPT"}),
            database="devdoADB",
        )
    )

    assert captured["params"]["prompt"] == "CUSTOM ORACLE TUNING PROMPT"
    assert result["raw_response_empty"] is True
    assert "Oracle SQL 튜닝 요청 prompt" in result["report_markdown"]


def test_analyze_returns_running_immediately_and_passes_proxy_run_id_to_ords(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: analyze returns running immediately and passes proxy run id to ords."""
    deps.set_config(_cfg())
    captured = {}
    background = BackgroundTasks()

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        captured["url"] = url
        captured["payload"] = payload
        return {"run_id": payload["run_id"], "status": "COMPLETED", "progress": [{"seq": 1, "code": "REQUEST_RECEIVED", "status": "DONE"}]}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)
    result = asyncio.run(asta_proxy.analyze(DummyRequest({"sql": "select 1 from dual"}), background, database="devdoADB"))

    assert result["status"] == "RUNNING"
    assert result["run_id"].startswith("OADT2-ASTA-")
    assert result["proxy"]["source"] == "FASTAPI_ASYNC_PROXY"
    assert result["progress"][0]["code"] == "REQUEST_RECEIVED"
    assert len(background.tasks) == 1
    task = background.tasks[0]
    asyncio.run(task.func(*task.args, **task.kwargs))
    assert captured["payload"]["run_id"] == result["run_id"]
    final = asyncio.run(asta_proxy.get_run_report(result["run_id"], database="devdoADB"))
    assert final["status"] == "COMPLETED"



def test_run_routes_proxy_to_ords_with_encoded_run_id(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: run routes proxy to ords with encoded run id."""
    deps.set_config(_cfg())
    calls = []

    async def fake_get(url, timeout):
        """ASTA 처리 흐름에서 fake get 작업을 수행한다."""
        calls.append((url, timeout))
        return {"run_id": "OADT2 ASTA/1", "status": "RUNNING"}

    monkeypatch.setattr(asta_proxy, "_get_json_from_ords", fake_get)

    run = asyncio.run(asta_proxy.get_run("OADT2 ASTA/1", database="devdoADB"))
    progress = asyncio.run(asta_proxy.get_run_progress("OADT2 ASTA/1", database="devdoADB"))
    report = asyncio.run(asta_proxy.get_run_report("OADT2 ASTA/1", database="devdoADB"))

    assert run["proxy"]["source"] == "ADB_ORDS"
    assert progress["proxy"]["external_call"] is True
    assert report["proxy"]["external_call"] is True
    assert calls == [
        ("https://example.com/ords/asta/runs/OADT2%20ASTA%2F1", 2100),
        ("https://example.com/ords/asta/runs/OADT2%20ASTA%2F1/progress", 2100),
        ("https://example.com/ords/asta/runs/OADT2%20ASTA%2F1/report", 2100),
    ]


def test_run_lookup_writes_sanitized_audit_for_not_found(monkeypatch, tmp_path):
    """ASTA 계약/회귀 조건을 검증한다: run lookup writes sanitized audit for not found."""
    deps.set_config(_cfg())
    monkeypatch.setenv("ASTA_AUDIT_DIR", str(tmp_path))

    async def fake_get(url, timeout):
        """ASTA 처리 흐름에서 fake get 작업을 수행한다."""
        return {"status": "NOT_FOUND", "error_code": "RUN_NOT_FOUND", "message": "run not found"}

    monkeypatch.setattr(asta_proxy, "_get_json_from_ords", fake_get)

    result = asyncio.run(asta_proxy.get_run_progress("OADT2-ASTA-SECRET-RUN-123456", database="devdoADB"))

    assert result["status"] == "NOT_FOUND"
    record = json.loads((tmp_path / "asta_request_audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "run_lookup_complete"
    assert record["endpoint_kind"] == "progress"
    assert record["queried_run_id_prefix"] == "OADT2-ASTA-SECRE…3456"
    assert record["queried_run_id_hash"]
    assert record["error_code"] == "RUN_NOT_FOUND"
    assert record["body_status"] == "NOT_FOUND"
    assert record["proxy_source"] == "ADB_ORDS"
    assert "OADT2-ASTA-SECRET-RUN-123456" not in json.dumps(record)


def test_run_routes_reject_invalid_run_id_before_proxy(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: run routes reject invalid run id before proxy."""
    deps.set_config(_cfg())

    async def fake_get(url, timeout):  # pragma: no cover - should not be called
        """ASTA 처리 흐름에서 fake get 작업을 수행한다."""
        raise AssertionError("invalid run ids must not be proxied")

    monkeypatch.setattr(asta_proxy, "_get_json_from_ords", fake_get)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(asta_proxy.get_run("../bad", database="devdoADB"))

    assert exc.value.status_code == 400
    assert "invalid run_id" in str(exc.value.detail)


def test_proxy_exposes_all_fetchjson_run_urls_used_by_static_ui():
    """ASTA 계약/회귀 조건을 검증한다: proxy exposes all fetchjson run urls used by static ui."""
    router_src = (ROOT / "app/routers/asta_proxy.py").read_text(encoding="utf-8")
    view = (ROOT / "static/js/extensions/tuning_assistant.js").read_text(encoding="utf-8")

    assert "@router.get(\"/runs/{run_id}\")" in router_src
    assert "encodeURIComponent(runId)" in view
    for suffix in ["progress", "report"]:
        assert f"/runs/${{encodedRunId}}/{suffix}" in view
        assert f"@router.get(\"/runs/{{run_id}}/{suffix}\")" in router_src




def test_program_runtime_has_no_source_db_direct_connection_path():
    """ASTA 계약/회귀 조건을 검증한다: program runtime has no source db direct connection path."""
    router_src = (ROOT / "app/routers/asta_proxy.py").read_text(encoding="utf-8")
    helper_src = (ROOT / "app/asta_source_direct.py").read_text(encoding="utf-8")

    assert "asta_source_direct" not in router_src
    assert "apply_source_direct" not in router_src
    assert "subprocess.run" not in router_src
    assert "oracledb.connect" not in router_src
    assert "SOURCE DIRECT DB ACCESS IS DISABLED" in helper_src
    assert "subprocess.run" not in helper_src
    assert "oracledb.connect" not in helper_src


def test_analyze_proxies_to_ords(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: analyze proxies to ords."""
    deps.set_config(_cfg())
    calls = []

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        calls.append((url, payload, timeout))
        return {
            "run_id": "OADT2-ASTA-1",
            "status": "COMPLETED",
            "progress": [{"code": "SQL_GUARD", "status": "DONE"}],
            "detailed_report_markdown": "# report",
        }

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)

    _, result = _run_analyze_background({"sql_text": "select * from dual", "ai_profile": "ASTA_X"})

    assert result["proxy"]["source"] == "ADB_ORDS"
    assert result["status"] == "COMPLETED"
    assert calls[0][0] == "https://example.com/ords/asta/analyze"
    assert calls[0][2] == 2100
    assert calls[0][1]["sql"] == "select * from dual"
    assert calls[0][1]["llm_profile"] == "ASTA_X"
    assert calls[0][1]["source_db_id"] == "DB0903_TESTDB"
    assert "source_db_link" not in calls[0][1]
    assert "source_schema" not in calls[0][1]


def test_analyze_never_uses_direct_source_fallback_after_ords_failure(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: analyze never uses direct source fallback after ords failure."""
    deps.set_config(_cfg())

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        return {
            "run_id": "OADT2-ASTA-1",
            "status": "FAILED",
            "runtime_evidence": {"status": "FAILED", "message": "ORA-03150 from DB0903_LINK"},
            "error": {"message": "ORA-03150 from DB0903_LINK"},
        }

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)

    _, result = _run_analyze_background({"sql": "select * from dual", "run_advisor": True})

    assert result["status"] == "FAILED"
    assert result["proxy"]["source"] == "ADB_ORDS"
    assert "ords_run_id" not in result


def test_analyze_drops_browser_controlled_source_link_fields(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: analyze drops browser controlled source link fields."""
    deps.set_config(_cfg())
    calls = []

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        calls.append(payload)
        return {"run_id": "OADT2-ASTA-1", "status": "COMPLETED"}

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)

    _run_analyze_background(
        {
            "sql": "select * from dual",
            "source_schema": "SHOULD_NOT_FORWARD",
            "source_db_link": "SHOULD_NOT_FORWARD",
            "use_llm": "false",
            "options": {
                "source_schema": "SHOULD_NOT_FORWARD",
                "source_db_link": "SHOULD_NOT_FORWARD",
            },
        }
    )

    assert "source_schema" not in calls[0]
    assert "source_db_link" not in calls[0]
    assert "source_schema" not in calls[0]["options"]
    assert "source_db_link" not in calls[0]["options"]
    assert calls[0]["source_db_id"] == "DB0903_TESTDB"
    assert calls[0]["use_llm"] is False


def test_ords_json_reader_accepts_long_report_source_and_advisor_text(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: ords json reader accepts long report source and advisor text."""
    long_text = ('한글 "quote" newline\\n' * 1800) + "끝"
    payload = {
        "run_id": "OADT2-ASTA-LONG",
        "status": "COMPLETED",
        "detailed_report_markdown": long_text,
        "runtime_evidence": {"advisor": {"report": long_text}},
        "artifacts": {"source_evidence": {"plan_text": long_text}},
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    class DummyResponse:
        """ASTA 처리 흐름에서 DummyResponse 작업을 수행한다."""
        def __enter__(self):
            """ASTA 내부 처리 보조 함수: enter."""
            return self

        def __exit__(self, *args):
            """ASTA 내부 처리 보조 함수: exit."""
            return False

        def read(self):
            """ASTA 처리 흐름에서 read 작업을 수행한다."""
            return raw

    monkeypatch.setattr(asta_proxy.urllib_request, "urlopen", lambda req, timeout: DummyResponse())

    result = asta_proxy._request_json_sync(asta_proxy.urllib_request.Request("https://example.com"), timeout=30)

    assert result["detailed_report_markdown"].endswith("끝")
    assert result["runtime_evidence"]["advisor"]["report"] == long_text
    assert result["artifacts"]["source_evidence"]["plan_text"] == long_text


def test_analyze_requires_ords_base_url(monkeypatch):
    """ASTA 계약/회귀 조건을 검증한다: analyze requires ords base url."""
    deps.set_config(_cfg(ords_base_url=""))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(asta_proxy.analyze(DummyRequest({"sql": "select * from dual"}), BackgroundTasks(), database="devdoADB"))

    assert exc.value.status_code == 500
    assert "ORDS base URL" in str(exc.value.detail)


def test_analyze_writes_sanitized_request_audit_jsonl(monkeypatch, tmp_path):
    """ASTA 계약/회귀 조건을 검증한다: analyze writes sanitized request audit jsonl."""
    deps.set_config(_cfg())
    monkeypatch.setenv("ASTA_AUDIT_DIR", str(tmp_path))
    monkeypatch.setenv("ASTA_RUN_INDEX_DIR", str(tmp_path / "runs"))

    async def fake_post(url, payload, timeout):
        """ASTA 처리 흐름에서 fake post 작업을 수행한다."""
        return {
            "run_id": "OADT2-ASTA-AUDIT",
            "status": "COMPLETED",
            "progress": [{"code": "FINAL_REPORT", "status": "DONE"}],
            "detailed_report_markdown": "# AI SQL Tuning Assistant Report\n\n## 튜닝 결과\n\nvisible clean",
            "artifacts": {
                "report_path": "reports/asta/OADT2-ASTA-AUDIT.md",
                "vector": {"chunk_text": "old raw artifact with ## 결과 요약 and ORA-03150 preserved"},
            },
        }

    monkeypatch.setattr(asta_proxy, "_post_json_to_ords", fake_post)

    sql_text = "select password, dsn from secret_table where token = 'VERY_SECRET_TOKEN_VALUE'"
    initial, result = _run_analyze_background(
        {
            "sql": sql_text,
            "source_db_id": "DB0903_TESTDB",
            "use_llm": True,
            "run_advisor": True,
            "sqltune_time_limit": 60,
        }
    )

    assert result["run_id"] == "OADT2-ASTA-AUDIT"
    lines = (tmp_path / "asta_request_audit.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    final = records[-1]
    assert final["event"] == "analyze_background_complete"
    assert final["run_id"] == "OADT2-ASTA-AUDIT"
    assert final["request_id"]
    assert final["sql_sha256"]
    assert final["sql_fingerprint"]
    assert final["source_db_id"] == "DB0903_TESTDB"
    assert final["use_llm"] is True
    assert final["run_advisor"] is True
    assert final["sqltune_time_limit"] == 60
    assert final["ords_status"] == "COMPLETED"
    assert final["fallback_attempted"] is False
    assert final["final_status"] == "COMPLETED"
    assert final["final_progress"] == "FINAL_REPORT:DONE"
    assert final["report_path"] == "reports/asta/OADT2-ASTA-AUDIT.md"
    assert final["visible_report_has_tuning_result"] is True
    assert final["visible_report_has_old_result_summary"] is False
    assert final["visible_report_has_ora03150"] is False
    assert final["raw_artifact_has_old_result_summary"] is True
    assert final["raw_artifact_has_ora03150"] is True
    serialized = "\n".join(lines)
    assert sql_text not in serialized
    assert "secret_table" not in serialized
    assert "VERY_SECRET_TOKEN_VALUE" not in serialized
    index_records = [json.loads(line) for line in (tmp_path / "runs" / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert index_records[-1]["request_id"] == final["request_id"]
    assert index_records[-1]["run_id"] == "OADT2-ASTA-AUDIT"
    assert index_records[-1]["source_boundary"] == "ADB_ORDS"
    assert index_records[-1]["progress_summary"] == "FINAL_REPORT:DONE"
    assert index_records[-1]["visible_report_has_tuning_result"] is True
    assert index_records[-1]["visible_report_has_old_result_summary"] is False
    assert index_records[-1]["raw_artifact_has_old_result_summary"] is True


def test_fallback_run_snapshot_roundtrip(monkeypatch, tmp_path):
    """ASTA 계약/회귀 조건을 검증한다: fallback run snapshot roundtrip."""
    monkeypatch.setenv("ASTA_RUN_INDEX_DIR", str(tmp_path))
    result = {
        "run_id": "OADT2-ASTA-SNAPSHOT",
        "status": "COMPLETED",
        "progress": [{"code": "FINAL_REPORT", "status": "DONE"}],
        "detailed_report_markdown": "# final report",
        "proxy": {"source": "ADB_ORDS_WITH_SOURCE_DIRECT_FALLBACK", "external_call": False},
    }
    asta_audit.write_run_index("req-1", result, database="devdoADB", fallback_attempted=True)
    loaded = asta_audit.read_run_snapshot("OADT2-ASTA-SNAPSHOT")
    assert loaded is not None
    assert loaded["status"] == "COMPLETED"
    assert loaded["detailed_report_markdown"] == "# final report"


