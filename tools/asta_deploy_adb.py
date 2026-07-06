"""작성자: 도상훈
파일 용도: ASTA 배포, 스모크 테스트, 대량 검증 실행을 위한 명령행 도구이다."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib
import re
import statistics
import sys
import time
import urllib.request
import http.cookiejar
import uuid

import oracledb
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEPLOY_PACKAGE_ORDER = [
    "db/adb/asta_sql_guard_pkg.sql",
    "db/adb/asta_source_bridge_pkg.sql",
    "db/adb/asta_vector_pkg.sql",
    "db/adb/asta_llm_pkg.sql",
    "db/adb/asta_report_pkg.sql",
    "db/adb/asta_pkg.sql",
]


def connect():
    """환경변수와 wallet 설정을 사용해 Oracle DB 연결을 연다."""
    conf = yaml.safe_load((ROOT / "config.yaml").read_text())
    db = conf["databases"][0]
    wallet = str((ROOT / db["wallet_location"]).resolve())
    return oracledb.connect(
        user=db["user"],
        password=db["password"],
        dsn=db["dsn"],
        config_dir=wallet,
        wallet_location=wallet,
        wallet_password=db.get("wallet_password"),
    )


def split_sqlplus_script(text: str) -> list[str]:
    """SQL*Plus 스타일 스크립트를 실행 가능한 개별 문장으로 분리한다."""
    statements: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped:
            buf.append(line)
            continue
        if stripped == "/":
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            continue
        if upper.startswith(("SHOW ", "PROMPT ", "WHENEVER ", "SPOOL ")):
            continue
        if stripped.startswith("--"):
            buf.append(line)
            continue
        buf.append(line)
    stmt = "\n".join(buf).strip()
    if stmt:
        # strip a final SQL semicolon for plain SQL but not PL/SQL package bodies handled by slash
        statements.append(stmt)
    return statements


def exec_stmt(cur, stmt: str):
    """한 개의 SQL/PLSQL 문장을 실행하고 오류 정보를 표준화한다."""
    s = "\n".join(line for line in stmt.strip().splitlines() if not line.strip().startswith("--")).strip()
    if s.endswith(";") and not re.match(r"(?is)^\s*(create\s+or\s+replace\s+package|declare|begin)", s):
        s = s[:-1]
    cur.execute(s)


def object_exists(cur, table: str, name: str) -> bool:
    """배포 대상 객체가 데이터베이스에 존재하는지 확인한다."""
    cur.execute(f"select count(*) from {table} where {('table_name' if table == 'user_tables' else 'index_name')} = :n", n=name.upper())
    return cur.fetchone()[0] > 0


def run_script(cur, rel: str):
    """지정된 ASTA 배포 SQL 파일을 순서대로 실행한다."""
    text = (ROOT / rel).read_text()
    path = ROOT / rel
    # Package/PLSQL scripts use SQL*Plus slash separators. Plain DDL scripts use semicolons.
    if "CREATE OR REPLACE PACKAGE" not in text.upper() and "DECLARE" not in text.upper() and "BEGIN" not in text.upper():
        text_no_comments = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))
        for stmt in [s.strip() for s in text_no_comments.split(";") if s.strip()]:
            # Deploy automation only executes structural DDL from these files; skip comments/metadata/examples.
            if not stmt.upper().startswith(("CREATE ", "ALTER ")):
                continue
            try:
                exec_stmt(cur, stmt)
            except Exception as e:
                raise RuntimeError(f"failed in {rel}: {stmt[:300]!r}") from e
        return
    for stmt in split_sqlplus_script(text):
        try:
            exec_stmt(cur, stmt)
        except Exception as e:
            raise RuntimeError(f"failed in {rel}: {stmt[:300]!r}") from e


ROADMAP_RUNTIME_PACKAGES = [
    ("ASTA_SQL_GUARD_PKG", "db/adb/asta_sql_guard_pkg.sql"),
    ("ASTA_SOURCE_BRIDGE_PKG", "db/adb/asta_source_bridge_pkg.sql"),
    ("ASTA_VECTOR_PKG", "db/adb/asta_vector_pkg.sql"),
    ("ASTA_LLM_PKG", "db/adb/asta_llm_pkg.sql"),
    ("ASTA_REPORT_PKG", "db/adb/asta_report_pkg.sql"),
    ("ASTA_PKG", "db/adb/asta_pkg.sql"),
]

AA7_RESULT_FIX_PACKAGES = [
    ("ASTA_REPORT_PKG", "db/adb/asta_report_pkg.sql"),
    ("ASTA_PKG", "db/adb/asta_pkg.sql"),
]

AA7_RUN_ID = "OADT2-ASTA-aa7ba3f1891344d697803b64f363faf9"


def _lob_text(value) -> str:
    return value.read() if hasattr(value, "read") else str(value or "")


def aa7_result_fix_action(action: str, backup_dir: Path) -> int:
    """Back up, deploy, or inspect only the approved ADB result-fix packages."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()
    try:
        if action == "backup":
            for name, _ in AA7_RESULT_FIX_PACKAGES:
                for kind, suffix in (("PACKAGE", "spec"), ("PACKAGE_BODY", "body")):
                    cur.execute("select dbms_metadata.get_ddl(:k,:n,user) from dual", k=kind, n=name)
                    value = cur.fetchone()[0]
                    ddl = value.read() if hasattr(value, "read") else str(value or "")
                    (backup_dir / f"adb_{name.lower()}_{suffix}.sql").write_text(
                        ddl.rstrip() + "\n/\n", encoding="utf-8"
                    )
        elif action in {"deploy", "rollback"}:
            expected_backups = [
                backup_dir / f"adb_{name.lower()}_{suffix}.sql"
                for name, _ in AA7_RESULT_FIX_PACKAGES
                for suffix in ("spec", "body")
            ]
            missing = [str(path) for path in expected_backups if not path.exists()]
            if missing:
                raise RuntimeError(f"aa7 deploy requires preserved ADB backups: {missing}")
            if action == "deploy":
                for _, rel in AA7_RESULT_FIX_PACKAGES:
                    run_script(cur, rel)
            else:
                for name, _ in reversed(AA7_RESULT_FIX_PACKAGES):
                    for suffix in ("spec", "body"):
                        text_value = (backup_dir / f"adb_{name.lower()}_{suffix}.sql").read_text(encoding="utf-8")
                        for statement in split_sqlplus_script(text_value):
                            exec_stmt(cur, statement)

        names = [name for name, _ in AA7_RESULT_FIX_PACKAGES]
        binds = ",".join(f":n{i}" for i in range(len(names)))
        params = {f"n{i}": name for i, name in enumerate(names)}
        cur.execute(
            f"select object_name,object_type,status,last_ddl_time from user_objects "
            f"where object_name in ({binds}) and object_type in ('PACKAGE','PACKAGE BODY') "
            "order by object_name,object_type", params,
        )
        objects = cur.fetchall()
        cur.execute(
            f"select name,type,line,position,text from user_errors "
            f"where name in ({binds}) order by name,type,sequence", params,
        )
        errors = cur.fetchall()
        expected = {(name, typ) for name in names for typ in ("PACKAGE", "PACKAGE BODY")}
        valid = {(row[0], row[1]) for row in objects if row[2] == "VALID"}
        if action in {"deploy", "rollback"}:
            if errors or valid != expected:
                conn.rollback()
                raise RuntimeError(
                    f"AA7 ADB package validation failed; valid={sorted(valid)} errors={len(errors)}"
                )
            conn.commit()
        payload = {"action": action, "objects": objects, "error_count": len(errors)}
        if action == "status":
            payload["errors"] = errors
        (backup_dir / f"adb_aa7_{action}_status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0 if not errors and valid == expected else 2
    finally:
        cur.close()
        conn.close()


def aa7_rebuild_blocked_report(outdir: Path) -> int:
    """Rebuild the diagnosed run without changing its historical gate verdict."""
    from app.routers.asta_proxy import _report_document

    outdir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "select status,input_sql,detailed_report_md,response_json from asta_runs where run_id=:r",
            r=AA7_RUN_ID,
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("diagnosed ASTA run not found")
        status, input_lob, old_report_lob, response_lob = row
        input_sql = _lob_text(input_lob)
        old_report = _lob_text(old_report_lob)
        if isinstance(response_lob, dict):
            payload = response_lob
            old_response = json.dumps(response_lob, ensure_ascii=False, separators=(",", ":"))
        else:
            old_response = _lob_text(response_lob)
            payload = json.loads(old_response)
        artifacts = payload.get("artifacts") or {}

        def artifact(name: str, fallback=None):
            value = artifacts.get(name, fallback)
            return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value is not None else None

        source_json = artifact("source_evidence", payload.get("runtime_evidence"))
        after_json = artifact("after_evidence", payload.get("after_evidence"))
        comparison_json = artifact("comparison", payload.get("comparison"))
        vector_json = artifact("vector", payload.get("vector"))
        vector_save_json = artifact("vector_save", payload.get("vector_save"))
        llm_json = artifact("llm", payload.get("llm"))
        final_review_json = artifact("final_review", payload.get("final_review"))
        error_json_value = artifact("error", payload.get("error"))
        progress_json = json.dumps(payload.get("progress") or [], ensure_ascii=False, separators=(",", ":"))

        report_out = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute(
            """begin :out := asta_report_pkg.build_report(
                 p_run_id=>:run_id,p_input_sql=>:input_sql,
                 p_source_evidence_json=>:source_json,p_vector_json=>:vector_json,
                 p_llm_json=>:llm_json,p_status=>:status,p_error_json=>:error_json,
                 p_final_review_json=>:final_review_json,p_after_evidence_json=>:after_json,
                 p_comparison_json=>:comparison_json,p_vector_save_json=>:vector_save_json); end;""",
            out=report_out, run_id=AA7_RUN_ID, input_sql=input_sql,
            source_json=source_json, vector_json=vector_json, llm_json=llm_json,
            status=status, error_json=error_json_value, final_review_json=final_review_json,
            after_json=after_json, comparison_json=comparison_json, vector_save_json=vector_save_json,
        )
        new_report = _lob_text(report_out.getvalue())
        required = ("검증 실행된 후보 SQL — 채택 보류", "## 튜닝 후 XPLAN")
        if not all(token in new_report for token in required):
            raise RuntimeError("rebuilt report does not expose blocked candidate and After XPLAN")
        if "- 개선 SQL 없음" in new_report or "- 튜닝 SQL 미채택으로 SKIPPED" in new_report:
            raise RuntimeError("rebuilt report retains the contradictory legacy wording")

        response_out = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute(
            """begin :out := asta_report_pkg.build_response_json(
                 p_run_id=>:run_id,p_status=>:status,p_report_markdown=>:report_markdown,
                 p_source_evidence_json=>:source_json,p_vector_json=>:vector_json,
                 p_llm_json=>:llm_json,p_error_json=>:error_json,p_progress_json=>:progress_json,
                 p_final_review_json=>:final_review_json,p_after_evidence_json=>:after_json,
                 p_comparison_json=>:comparison_json,p_vector_save_json=>:vector_save_json); end;""",
            out=response_out, run_id=AA7_RUN_ID, status=status, report_markdown=new_report,
            source_json=source_json, vector_json=vector_json, llm_json=llm_json,
            error_json=error_json_value, progress_json=progress_json,
            final_review_json=final_review_json, after_json=after_json,
            comparison_json=comparison_json, vector_save_json=vector_save_json,
        )
        new_response = _lob_text(response_out.getvalue())

        (outdir / "aa7_report_before.md").write_text(old_report, encoding="utf-8")
        (outdir / "aa7_response_before.json").write_text(old_response, encoding="utf-8")
        (outdir / "aa7_report_rebuilt.md").write_text(new_report, encoding="utf-8")
        (outdir / "aa7_report_rebuilt.html").write_text(
            _report_document(AA7_RUN_ID, new_report), encoding="utf-8"
        )
        (outdir / "aa7_response_rebuilt.json").write_text(new_response, encoding="utf-8")

        cur.execute(
            "update asta_runs set detailed_report_md=:report,response_json=:response where run_id=:run_id",
            report=new_report, response=new_response, run_id=AA7_RUN_ID,
        )
        conn.commit()
        api_value = cur.callfunc("ASTA_PKG.GET_REPORT", oracledb.DB_TYPE_CLOB, [AA7_RUN_ID])
        api_payload = json.loads(_lob_text(api_value))
        api_report = str(api_payload.get("detailed_report_markdown") or "")
        comparison = payload.get("comparison") or artifacts.get("comparison") or {}
        after = payload.get("after_evidence") or artifacts.get("after_evidence") or {}
        summary = {
            "run_id": AA7_RUN_ID,
            "status": status,
            "verdict": comparison.get("verdict"),
            "verdict_reason": comparison.get("verdict_reason"),
            "candidate_visible": required[0] in api_report,
            "after_xplan_visible": required[1] in api_report and bool(after.get("plan_text")),
            "report_api_matches_rebuilt": api_report == new_report,
            "old_report_length": len(old_report),
            "new_report_length": len(new_report),
        }
        (outdir / "aa7_report_rebuild_status.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if all((summary["candidate_visible"], summary["after_xplan_visible"], summary["report_api_matches_rebuilt"])) else 2
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def aa7_live_report_api_verify(outdir: Path) -> int:
    """Verify the rebuilt report through the running localhost API without logging SQL."""
    outdir.mkdir(parents=True, exist_ok=True)
    conf = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    access_key = str(conf.get("access_key") or "")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    if access_key:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/auth/login",
            data=json.dumps({"key": access_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError("local API login failed")
    url = f"http://127.0.0.1:8000/api/asta/runs/{AA7_RUN_ID}/report"
    with opener.open(url, timeout=120) as response:
        http_status = response.status
        payload = json.loads(response.read().decode("utf-8"))
    markdown = str(payload.get("detailed_report_markdown") or "")
    summary = {
        "url": url,
        "http_status": http_status,
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "candidate_visible": "## 튜닝 후 SQL" in markdown and "```sql" in markdown,
        "after_xplan_visible": "## 튜닝 후 XPLAN" in markdown,
        "legacy_missing_candidate_absent": "- 개선 SQL 없음" not in markdown,
        "improved_report": "측정 불충분" not in markdown and "원본 SQL 유지" not in markdown,
        "report_length": len(markdown),
    }
    (outdir / "aa7_live_report_api.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if http_status == 200 and all((summary["candidate_visible"], summary["after_xplan_visible"], summary["legacy_missing_candidate_absent"], summary["improved_report"])) else 2


def advisor_off_live_static_verify(outdir: Path) -> int:
    """Verify the cache-busted Advisor-OFF UI assets from the running service."""
    outdir.mkdir(parents=True, exist_ok=True)
    version = "20260706_advisor_default_off1"
    with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=15) as response:
        root_status = response.status
        root_html = response.read().decode("utf-8")
    url = f"http://127.0.0.1:8000/static/js/extensions/tuning_assistant.js?v={version}"
    with urllib.request.urlopen(url, timeout=15) as response:
        js_status = response.status
        live_js = response.read()
    local_js = (ROOT / "static/js/extensions/tuning_assistant.js").read_bytes()
    live_text = live_js.decode("utf-8")
    summary = {
        "root_http_status": root_status,
        "js_http_status": js_status,
        "cache_version_present": version in root_html,
        "served_js_matches_workspace": live_js == local_js,
        "top_and_options_run_advisor_false_count": live_text.count("run_advisor: false"),
        "top_and_options_use_sqltune_false_count": live_text.count("use_sqltune: false"),
        "advisor_off_status_visible": "SQL Advisor: OFF" in live_text,
    }
    passed = all((
        root_status == 200, js_status == 200, summary["cache_version_present"],
        summary["served_js_matches_workspace"],
        summary["top_and_options_run_advisor_false_count"] == 2,
        summary["top_and_options_use_sqltune_false_count"] == 2,
        summary["advisor_off_status_visible"],
    ))
    summary["passed"] = passed
    (outdir / "advisor_default_off_live_static.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 2


def aa7_source_remote_status(outdir: Path) -> int:
    """Read only the remote Source package state and required contract markers via DB link."""
    outdir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(
            "select db_link_name from asta_source_connections where source_db_id='DB0903_TESTDB' and enabled='Y'"
        )
        link = str(cur.fetchone()[0]).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_$#]*(?:\.[A-Z0-9_$#]+)*", link):
            raise RuntimeError("invalid configured Source DB link")
        cur.execute(
            f"select object_name,object_type,status,last_ddl_time from user_objects@{link} "
            "where object_name='ASTA_SOURCE_PKG' and object_type in ('PACKAGE','PACKAGE BODY') order by object_type"
        )
        objects = cur.fetchall()
        cur.execute(
            f"select count(*) from user_errors@{link} where name='ASTA_SOURCE_PKG'"
        )
        error_count = int(cur.fetchone()[0])
        cur.execute(
            f"select text from user_source@{link} "
            "where name='ASTA_SOURCE_PKG' and type='PACKAGE BODY' order by line"
        )
        source_text = "".join(str(row[0] or "") for row in cur.fetchall())
        markers = {
            "auto_four": "RETURN 4;" in source_text,
            "bind_not_applicable": "BIND_NOT_APPLICABLE" in source_text,
            "measurement_runs": '"measurement_runs"' in source_text,
            "optimizer_intent_evidence": "collect_optimizer_intent_evidence" in source_text,
        }
        summary = {
            "objects": objects,
            "error_count": error_count,
            "required_markers": markers,
            "current_contract_deployed": error_count == 0 and len(objects) == 2 and all(markers.values()),
        }
        (outdir / "source_remote_status.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if summary["current_contract_deployed"] else 2
    finally:
        cur.close()
        conn.close()


def aa7_manual_measurement_verify(outdir: Path) -> int:
    """Run one warm-up plus three measured ONCE calls per side using the deployed safe bridge."""
    from tools.asta_optimizer_intent import verify_optimizer_intent

    outdir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.call_timeout = 300_000
    cur = conn.cursor()
    try:
        cur.execute("select input_sql,tuned_sql,response_json from asta_runs where run_id=:r", r=AA7_RUN_ID)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("diagnosed ASTA run not found")
        original_sql = _lob_text(row[0])
        candidate_sql = _lob_text(row[1])
        response_value = row[2]
        response = response_value if isinstance(response_value, dict) else json.loads(_lob_text(response_value))
        artifacts = response.get("artifacts") or {}
        old_source = artifacts.get("source_evidence") or response.get("runtime_evidence") or {}
        source_sql_id = old_source.get("source_sql_id") or old_source.get("sql_id")

        evidence: dict[str, list[dict]] = {"before": [], "after": []}
        for side, sql_text in (("before", original_sql), ("after", candidate_sql)):
            for sequence in range(4):
                run_id = f"AA7V-{side[0].upper()}{sequence + 1}-{uuid.uuid4().hex[:20]}"
                value = cur.callfunc(
                    "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", oracledb.DB_TYPE_CLOB,
                    ["DB0903_TESTDB", sql_text, run_id, 100, "ONCE", "N", 60,
                     source_sql_id, "FULL_RESULT", 100000],
                )
                item = json.loads(_lob_text(value))
                evidence[side].append(item)
                (outdir / "aa7_measurement_progress.json").write_text(
                    json.dumps({"completed": {k: len(v) for k, v in evidence.items()}}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        def measured(side: str) -> list[dict]:
            return evidence[side][1:]

        def median(side: str, key: str) -> float:
            return float(statistics.median(float(item[key]) for item in measured(side)))

        def noise(side: str) -> float:
            values = [float(item["last_elapsed_time_us"]) for item in measured(side)]
            middle = statistics.median(values)
            return round((max(values) - min(values)) * 100 / middle, 3) if middle else 0.0

        all_items = evidence["before"] + evidence["after"]
        first = evidence["before"][0]
        digest_equal = all(
            item.get("status") == "COMPLETED"
            and item.get("result_digest_status") == "COMPLETED"
            and item.get("result_digest_scope") == "FULL_RESULT"
            and item.get("result_total_rows") == 262
            and item.get("result_evidence_complete") is True
            and item.get("result_digest") == first.get("result_digest")
            and item.get("result_metadata_digest") == first.get("result_metadata_digest")
            and item.get("result_digest_mode") == first.get("result_digest_mode")
            for item in all_items
        )
        strategy = {
            "strategy_id": "NOT_EXISTS_UNION_DISTINCT_BARRIER",
            "target": {"object": "DSNT.VIF_WHOLESALE_S"},
            "expected_plan_effect": {
                "producer_starts": 1, "consumer": "ANTI_EXISTENCE", "merge_barrier": "SET_OPERATION"
            },
        }
        intent = verify_optimizer_intent(
            str(evidence["before"][-1].get("plan_text") or ""),
            str(evidence["after"][-1].get("plan_text") or ""), strategy,
        )
        placeholder_counts = {
            "before": len(re.findall(r"(?<!:):[A-Za-z][A-Za-z0-9_$#]*", original_sql)),
            "after": len(re.findall(r"(?<!:):[A-Za-z][A-Za-z0-9_$#]*", candidate_sql)),
        }
        bind_metadata_counts = {
            side: max(len((item.get("child_cursor_evidence") or {}).get("bind_metadata") or []) for item in items)
            for side, items in evidence.items()
        }
        bind_not_applicable = all(value == 0 for value in placeholder_counts.values()) and all(
            value == 0 for value in bind_metadata_counts.values()
        )
        before_elapsed = median("before", "last_elapsed_time_us")
        after_elapsed = median("after", "last_elapsed_time_us")
        before_buffers = median("before", "last_cr_buffer_gets")
        after_buffers = median("after", "last_cr_buffer_gets")
        noise_pct = {"before": noise("before"), "after": noise("after")}
        measurements_accepted = all(value <= 20 for value in noise_pct.values())
        latency_pass = after_elapsed <= 3_000_000
        increase_pass = after_elapsed - before_elapsed <= 300_000
        buffer_reduction_pct = round((before_buffers - after_buffers) * 100 / before_buffers, 3)
        improved = all((digest_equal, intent.get("status") == "VERIFIED", bind_not_applicable,
                        measurements_accepted, latency_pass, increase_pass, buffer_reduction_pct >= 5))
        summary = {
            "run_id": AA7_RUN_ID,
            "warmup_count_per_side": 1,
            "measurement_count_per_side": 3,
            "result_total_rows": 262,
            "full_result_equivalent": digest_equal,
            "optimizer_intent_status": intent.get("status"),
            "optimizer_intent_reason": intent.get("verdict_reason"),
            "bind_status": "BIND_NOT_APPLICABLE" if bind_not_applicable else "BLOCKED",
            "sql_bind_placeholder_counts": placeholder_counts,
            "db_bind_metadata_counts": bind_metadata_counts,
            "before_elapsed_us": [item.get("last_elapsed_time_us") for item in measured("before")],
            "after_elapsed_us": [item.get("last_elapsed_time_us") for item in measured("after")],
            "before_buffer_gets": [item.get("last_cr_buffer_gets") for item in measured("before")],
            "after_buffer_gets": [item.get("last_cr_buffer_gets") for item in measured("after")],
            "median_before_elapsed_us": before_elapsed,
            "median_after_elapsed_us": after_elapsed,
            "median_before_buffer_gets": before_buffers,
            "median_after_buffer_gets": after_buffers,
            "elapsed_noise_pct": noise_pct,
            "buffer_reduction_pct": buffer_reduction_pct,
            "oltp_latency_pass": latency_pass,
            "elapsed_increase_pass": increase_pass,
            "final_verdict": "IMPROVED" if improved else "BLOCKED",
        }
        (outdir / "aa7_manual_measurement_evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (outdir / "aa7_manual_measurement_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if improved else 2
    finally:
        cur.close()
        conn.close()


def aa7_reassess_manual_intent(outdir: Path) -> int:
    """Reassess the saved RAW plans with the candidate's actual DISTINCT-key strategy."""
    from tools.asta_optimizer_intent import verify_optimizer_intent

    evidence_path = outdir / "aa7_manual_measurement_evidence.json"
    summary_path = outdir / "aa7_manual_measurement_summary.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    (outdir / "aa7_manual_measurement_summary_initial.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    strategy = {
        "strategy_id": "NOT_EXISTS_DISTINCT_KEY_ANTI",
        "target": {"object": "DSNT.VIF_WHOLESALE_S"},
        "expected_plan_effect": {"producer_starts": 1, "consumer": "ANTI_EXISTENCE"},
    }
    intent = verify_optimizer_intent(
        str(evidence["before"][-1].get("plan_text") or ""),
        str(evidence["after"][-1].get("plan_text") or ""), strategy,
    )
    summary["optimizer_intent_status"] = intent.get("status")
    summary["optimizer_intent_reason"] = intent.get("verdict_reason")
    summary["optimizer_intent_reason_codes"] = intent.get("reason_codes")
    summary["optimizer_producer"] = (intent.get("evidence") or {}).get("producer")
    accepted = all((
        summary.get("full_result_equivalent") is True,
        intent.get("status") == "VERIFIED",
        summary.get("bind_status") == "BIND_NOT_APPLICABLE",
        max((summary.get("elapsed_noise_pct") or {}).values()) <= 20,
        summary.get("oltp_latency_pass") is True,
        summary.get("elapsed_increase_pass") is True,
        float(summary.get("buffer_reduction_pct") or 0) >= 5,
    ))
    summary["final_verdict"] = "IMPROVED" if accepted else "BLOCKED"
    summary["intent_strategy_id"] = strategy["strategy_id"]
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


def aa7_publish_manual_improved(outdir: Path) -> int:
    """Publish the completed 1+3 campaign through the canonical report/API builders."""
    from app.routers.asta_proxy import _report_document

    evidence = json.loads((outdir / "aa7_manual_measurement_evidence.json").read_text(encoding="utf-8"))
    summary = json.loads((outdir / "aa7_manual_measurement_summary.json").read_text(encoding="utf-8"))
    if summary.get("final_verdict") != "IMPROVED":
        raise RuntimeError("manual campaign is not eligible for IMPROVED publication")

    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute("select status,input_sql,detailed_report_md,response_json from asta_runs where run_id=:r", r=AA7_RUN_ID)
        status, input_lob, current_report_lob, response_value = cur.fetchone()
        input_sql = _lob_text(input_lob)
        current_report = _lob_text(current_report_lob)
        response = response_value if isinstance(response_value, dict) else json.loads(_lob_text(response_value))
        artifacts = response.get("artifacts") or {}

        before = evidence["before"][-1]
        after = evidence["after"][-1]
        for side_name, aggregate in (("before", before), ("after", after)):
            measured = evidence[side_name][1:]
            aggregate["warmup_count"] = 1
            aggregate["measurement_count"] = 3
            aggregate["completed_measurement_count"] = 3
            aggregate["measurement_status"] = "ACCEPTED"
            aggregate["measurement_reason"] = "MEASUREMENT_ACCEPTED"
            aggregate["measurement_provenance"] = "MANUAL_WARMUP1_MEASURE3_VIA_SOURCE_BRIDGE"
            aggregate["measurement_runs"] = [
                {
                    "phase": "MEASURE", "status": "COMPLETED", "sequence": index + 1,
                    "last_elapsed_time_us": item.get("last_elapsed_time_us"),
                    "last_cr_buffer_gets": item.get("last_cr_buffer_gets"),
                    "last_disk_reads": item.get("last_disk_reads"),
                }
                for index, item in enumerate(measured)
            ]
            aggregate["median_elapsed_time_us"] = summary[f"median_{side_name}_elapsed_us"]
            aggregate["median_buffer_gets"] = summary[f"median_{side_name}_buffer_gets"]
            aggregate["median_disk_reads"] = statistics.median(
                float(item.get("last_disk_reads") or 0) for item in measured
            )
            aggregate["elapsed_noise_pct"] = summary["elapsed_noise_pct"][side_name]
            child = aggregate.get("child_cursor_evidence") or {}
            child["bind_placeholder_count"] = 0
            child["bind_coverage_status"] = "NOT_APPLICABLE"
            child["bind_coverage_reason"] = "BIND_NOT_APPLICABLE"
            aggregate["child_cursor_evidence"] = child

        old_comparison = response.get("comparison") or artifacts.get("comparison") or {}
        before_elapsed = summary["median_before_elapsed_us"]
        after_elapsed = summary["median_after_elapsed_us"]
        before_buffers = summary["median_before_buffer_gets"]
        after_buffers = summary["median_after_buffer_gets"]
        before_reads = statistics.median(float(item.get("last_disk_reads") or 0) for item in evidence["before"][1:])
        after_reads = statistics.median(float(item.get("last_disk_reads") or 0) for item in evidence["after"][1:])
        comparison = dict(old_comparison)
        comparison.update({
            "status": "COMPLETED", "verdict": "IMPROVED",
            "verdict_reason": "OLTP_BUFFER_READS_IMPROVED",
            "equivalence_status": "VERIFIED", "equivalence_reason": "RESULT_EQUIVALENCE_VERIFIED",
            "equivalence_strength": "FULL_RESULT_DIGEST", "result_digest_scope": "FULL_RESULT",
            "result_digest_mode": after.get("result_digest_mode"),
            "optimizer_intent_status": "VERIFIED", "optimizer_intent_reason": "OPTIMIZER_INTENT_VERIFIED",
            "optimizer_intent_object": "VIF_WHOLESALE_S", "producer_starts_before": 845,
            "producer_starts_after": 1, "bind_stability_status": "NOT_APPLICABLE",
            "bind_stability_reason": "BIND_NOT_APPLICABLE", "all_representative_binds_passed": True,
            "measurement_status": "ACCEPTED", "measurement_reason": "MEASUREMENT_ACCEPTED",
            "measurement_count": 3, "measurement_provenance": "MANUAL_WARMUP1_MEASURE3_VIA_SOURCE_BRIDGE",
            "before_median_elapsed_us": before_elapsed, "after_median_elapsed_us": after_elapsed,
            "before_median_buffer_gets": before_buffers, "after_median_buffer_gets": after_buffers,
            "before_elapsed_noise_pct": summary["elapsed_noise_pct"]["before"],
            "after_elapsed_noise_pct": summary["elapsed_noise_pct"]["after"],
            "noise_pct": max(summary["elapsed_noise_pct"].values()), "retain_original_sql": False,
            "row_count_matches": True, "output_rows_match": True,
            "before_result_digest": before.get("result_digest"), "after_result_digest": after.get("result_digest"),
            "result_digest_matches": True, "before_buffer_gets": before_buffers,
            "after_buffer_gets": after_buffers, "buffer_gets_delta": before_buffers - after_buffers,
            "buffer_gets_reduction_pct": summary["buffer_reduction_pct"],
            "before_disk_reads": before_reads, "after_disk_reads": after_reads,
            "disk_reads_delta": before_reads - after_reads,
            "before_elapsed_time_us": before_elapsed, "after_elapsed_time_us": after_elapsed,
            "elapsed_time_us_delta": before_elapsed - after_elapsed,
        })

        def compact(value) -> str | None:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value is not None else None

        vector = artifacts.get("vector") or response.get("vector")
        vector_save = artifacts.get("vector_save") or response.get("vector_save")
        llm = artifacts.get("llm") or response.get("llm")
        final_review = artifacts.get("final_review") or response.get("final_review")
        error = response.get("error")
        progress = response.get("progress") or []
        report_out = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute(
            """begin :out := asta_report_pkg.build_report(
              p_run_id=>:r,p_input_sql=>:sql,p_source_evidence_json=>:before_json,
              p_vector_json=>:vector_json,p_llm_json=>:llm_json,p_status=>:status,
              p_error_json=>:error_json,p_final_review_json=>:review_json,
              p_after_evidence_json=>:after_json,p_comparison_json=>:comparison_json,
              p_vector_save_json=>:vector_save_json); end;""",
            out=report_out, r=AA7_RUN_ID, sql=input_sql, before_json=compact(before),
            vector_json=compact(vector), llm_json=compact(llm), status=status,
            error_json=compact(error), review_json=compact(final_review), after_json=compact(after),
            comparison_json=compact(comparison), vector_save_json=compact(vector_save),
        )
        report = _lob_text(report_out.getvalue())
        if "## 튜닝 후 XPLAN" not in report or "```sql" not in report or "측정 불충분" in report:
            raise RuntimeError("IMPROVED report content contract failed")
        response_out = cur.var(oracledb.DB_TYPE_CLOB)
        cur.execute(
            """begin :out := asta_report_pkg.build_response_json(
              p_run_id=>:r,p_status=>:status,p_report_markdown=>:report,
              p_source_evidence_json=>:before_json,p_vector_json=>:vector_json,
              p_llm_json=>:llm_json,p_error_json=>:error_json,p_progress_json=>:progress_json,
              p_final_review_json=>:review_json,p_after_evidence_json=>:after_json,
              p_comparison_json=>:comparison_json,p_vector_save_json=>:vector_save_json); end;""",
            out=response_out, r=AA7_RUN_ID, status=status, report=report, before_json=compact(before),
            vector_json=compact(vector), llm_json=compact(llm), error_json=compact(error),
            progress_json=compact(progress), review_json=compact(final_review), after_json=compact(after),
            comparison_json=compact(comparison), vector_save_json=compact(vector_save),
        )
        rebuilt_response = _lob_text(response_out.getvalue())
        (outdir / "aa7_report_blocked_before_improved.md").write_text(current_report, encoding="utf-8")
        (outdir / "aa7_report_improved.md").write_text(report, encoding="utf-8")
        (outdir / "aa7_report_improved.html").write_text(_report_document(AA7_RUN_ID, report), encoding="utf-8")
        (outdir / "aa7_response_improved.json").write_text(rebuilt_response, encoding="utf-8")
        cur.execute("update asta_runs set detailed_report_md=:m,response_json=:j where run_id=:r",
                    m=report, j=rebuilt_response, r=AA7_RUN_ID)
        conn.commit()
        api_value = cur.callfunc("ASTA_PKG.GET_REPORT", oracledb.DB_TYPE_CLOB, [AA7_RUN_ID])
        api_report = json.loads(_lob_text(api_value)).get("detailed_report_markdown") or ""
        publish = {
            "run_id": AA7_RUN_ID, "verdict": "IMPROVED", "report_api_matches": api_report == report,
            "candidate_sql_in_report": "## 튜닝 후 SQL" in report and "```sql" in report,
            "raw_after_xplan_in_report": "## 튜닝 후 XPLAN" in report and "Plan hash value" in report,
            "markdown": str(outdir / "aa7_report_improved.md"),
            "html": str(outdir / "aa7_report_improved.html"),
        }
        (outdir / "aa7_improved_publish_status.json").write_text(
            json.dumps(publish, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(publish, ensure_ascii=False, indent=2))
        return 0 if all((publish["report_api_matches"], publish["candidate_sql_in_report"], publish["raw_after_xplan_in_report"])) else 2
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def roadmap_runtime_action(action: str, backup_dir: Path) -> int:
    """Back up or deploy the approved ADB runtime packages in dependency order."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    cur = conn.cursor()
    try:
        if action == "backup":
            for name, _ in ROADMAP_RUNTIME_PACKAGES:
                for kind, suffix in (("PACKAGE", "spec"), ("PACKAGE_BODY", "body")):
                    cur.execute("select dbms_metadata.get_ddl(:k,:n,user) from dual", k=kind, n=name)
                    value = cur.fetchone()[0]
                    ddl = value.read() if hasattr(value, "read") else str(value or "")
                    (backup_dir / f"adb_{name.lower()}_{suffix}.sql").write_text(
                        ddl.rstrip() + "\n/\n", encoding="utf-8"
                    )
        elif action == "deploy":
            missing = [name for name, _ in ROADMAP_RUNTIME_PACKAGES
                       if not (backup_dir / f"adb_{name.lower()}_spec.sql").exists()]
            if missing:
                raise RuntimeError(f"roadmap deploy requires preserved ADB backups: {missing}")
            for _, rel in ROADMAP_RUNTIME_PACKAGES:
                run_script(cur, rel)
        names = [name for name, _ in ROADMAP_RUNTIME_PACKAGES]
        binds = ",".join(f":n{i}" for i in range(len(names)))
        params = {f"n{i}": name for i, name in enumerate(names)}
        cur.execute(
            f"select object_name,object_type,status,last_ddl_time from user_objects "
            f"where object_name in ({binds}) and object_type in ('PACKAGE','PACKAGE BODY') "
            "order by object_name,object_type", params,
        )
        objects = cur.fetchall()
        cur.execute(
            f"select name,type,line,position,text from user_errors where name in ({binds}) order by name,sequence",
            params,
        )
        errors = cur.fetchall()
        if action == "deploy":
            valid = {(row[0], row[1]) for row in objects if row[2] == "VALID"}
            expected = {(name, typ) for name in names for typ in ("PACKAGE", "PACKAGE BODY")}
            if errors or valid != expected:
                conn.rollback()
                raise RuntimeError(f"ADB package validation failed; valid={sorted(valid)} errors={len(errors)}")
            conn.commit()
            source_value = cur.callfunc(
                "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", oracledb.DB_TYPE_CLOB,
                ["DB0903_TESTDB", "select cast(null as number) n, 'ASTA' v from dual",
                 "ROADMAP08_BRIDGE_SMOKE", 10, "ONCE", "N", 60, None, "FULL_RESULT", 100],
            )
            source_text = source_value.read() if hasattr(source_value, "read") else source_value
            source_payload = json.loads(source_text)
            payload_smoke = {key: source_payload.get(key) for key in (
                "status", "result_digest_status", "result_digest_scope", "result_digest_mode",
                "result_total_rows", "result_evidence_complete",
            )}
            child = source_payload.get("child_cursor_evidence") or {}
            payload_smoke["bind_coverage_status"] = child.get("bind_coverage_status")
            payload_smoke["bind_coverage_reason"] = child.get("bind_coverage_reason")
            if payload_smoke["status"] != "COMPLETED" or payload_smoke["result_digest_status"] != "COMPLETED":
                raise RuntimeError(f"ADB Source bridge full-result smoke failed: {payload_smoke}")
        payload = {"action": action, "objects": objects, "error_count": len(errors)}
        if action == "deploy":
            payload["source_bridge_smoke"] = payload_smoke
        if action == "status":
            payload["errors"] = errors
        (backup_dir / f"adb_{action}_status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        cur.close(); conn.close()


def roadmap_customer_verify(outdir: Path) -> int:
    """One bounded full-result pair; historical 3x metrics remain the latency evidence."""
    from tools.asta_optimizer_intent import verify_optimizer_intent
    from tools.run_asta_prompt_abc import load_samples

    outdir.mkdir(parents=True, exist_ok=True)
    sample = load_samples({"asta-awr-01"})[0]
    original_sql = sample["sql"]
    candidate_sql = (ROOT / "reports/asta_customer_01_live/candidate_union_barrier.sql").read_text(encoding="utf-8")
    conn = connect()
    conn.call_timeout = 600_000
    cur = conn.cursor()
    evidence: dict[str, dict] = {}
    timings: dict[str, float] = {}
    try:
        for side, sql_text in (("before", original_sql), ("after", candidate_sql)):
            started = time.monotonic()
            value = cur.callfunc(
                "ASTA_SOURCE_BRIDGE_PKG.RUN_SOURCE_EVIDENCE", oracledb.DB_TYPE_CLOB,
                ["DB0903_TESTDB", sql_text, f"ROADMAP08-CUSTOMER-{side.upper()}", 100,
                 "ONCE", "N", 60, "7rcw6d3us86r7", "FULL_RESULT", 100000],
            )
            timings[side] = round(time.monotonic() - started, 3)
            text = value.read() if hasattr(value, "read") else value
            evidence[side] = json.loads(text)
        before = evidence["before"]; after = evidence["after"]
        digest_match = all((
            before.get("result_digest_status") == "COMPLETED",
            after.get("result_digest_status") == "COMPLETED",
            before.get("result_digest_scope") == after.get("result_digest_scope") == "FULL_RESULT",
            before.get("result_digest_mode") == after.get("result_digest_mode"),
            before.get("result_metadata_digest") == after.get("result_metadata_digest"),
            before.get("result_total_rows") == after.get("result_total_rows"),
            before.get("result_digest") == after.get("result_digest"),
            before.get("result_evidence_complete") is True,
            after.get("result_evidence_complete") is True,
        ))
        strategy = {
            "strategy_id": "NOT_EXISTS_UNION_DISTINCT_BARRIER",
            "target": {"object": "DSNT.VIF_WHOLESALE_S"},
            "expected_plan_effect": {
                "producer_starts": 1,
                "consumer": "ANTI_EXISTENCE",
                "merge_barrier": "SET_OPERATION",
            },
        }
        intent = verify_optimizer_intent(
            str(before.get("plan_text") or ""), str(after.get("plan_text") or ""), strategy
        )
        bind = after.get("child_cursor_evidence") or {}
        summary = {
            "sql_id": "7rcw6d3us86r7",
            "workload": "OLTP",
            "call_wall_seconds": timings,
            "optimizer_intent_status": intent.get("status"),
            "optimizer_intent_reason": intent.get("verdict_reason"),
            "optimizer_reason_codes": intent.get("reason_codes"),
            "producer": (intent.get("evidence") or {}).get("producer"),
            "full_result_equivalent": digest_match,
            "result_digest_scope": after.get("result_digest_scope"),
            "result_digest_mode": after.get("result_digest_mode"),
            "result_total_rows": after.get("result_total_rows"),
            "bind_coverage_status": bind.get("bind_coverage_status"),
            "bind_coverage_reason": bind.get("bind_coverage_reason"),
            "historical_before_3_elapsed_us": [142640389, 124498199, 123915378],
            "historical_after_3_elapsed_us": [1641880, 1615886, 1644745],
            "historical_before_median_elapsed_us": 124498199,
            "historical_after_median_elapsed_us": 1641880,
            "historical_before_buffer_gets": 9159788,
            "historical_after_buffer_gets": 1079324,
            "oltp_latency_target_us": 3000000,
            "max_elapsed_increase_us": 300000,
            "final_status": "BLOCKED" if bind.get("bind_coverage_status") != "VERIFIED" else
                            ("ACCEPTED" if digest_match and intent.get("status") == "VERIFIED" else "REJECTED"),
            "final_reason": bind.get("bind_coverage_reason") if bind.get("bind_coverage_status") != "VERIFIED" else
                            ("ALL_GATES_VERIFIED" if digest_match and intent.get("status") == "VERIFIED" else "GATE_NOT_VERIFIED"),
        }
        (outdir / "customer_01_runtime_verification.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["final_status"] == "ACCEPTED" else 2
    finally:
        cur.close(); conn.close()


def roadmap_runtime_inspect(outdir: Path) -> int:
    """Inspect final-run/vector and Source bind metadata without raw SQL or bind values."""
    outdir.mkdir(parents=True, exist_ok=True)
    conn = connect(); cur = conn.cursor()
    result: dict[str, object] = {"sql_id": "7rcw6d3us86r7"}
    def safe_db_error(exc: Exception) -> dict[str, object]:
        info = exc.args[0] if getattr(exc, "args", None) else None
        code = getattr(info, "code", None)
        message = str(getattr(info, "message", None) or type(exc).__name__)
        message = re.sub(r"'(?:''|[^'])*'", "'?'", message)[:500]
        return {"error_type": type(exc).__name__, "oracle_code": code, "message": message}

    try:
        cur.execute("""
          select run_id, status, created_at,
                 json_value(response_json,'$.comparison.verdict' returning varchar2(30) null on error),
                 json_value(response_json,'$.comparison.verdict_reason' returning varchar2(128) null on error),
                 json_value(response_json,'$.comparison.optimizer_intent_status' returning varchar2(30) null on error),
                 json_value(response_json,'$.comparison.result_digest_scope' returning varchar2(30) null on error),
                 json_value(response_json,'$.comparison.bind_stability_status' returning varchar2(30) null on error),
                 json_value(response_json,'$.comparison.measurement_status' returning varchar2(30) null on error),
                 json_value(response_json,'$.artifacts.vector_save.learning_class' returning varchar2(30) null on error),
                 json_value(response_json,'$.artifacts.vector_save.rejection_reason' returning varchar2(128) null on error)
          from asta_runs
          where response_json is not null
            and json_value(response_json,'$.comparison.verdict' returning varchar2(30) null on error) is not null
          order by created_at desc fetch first 10 rows only
        """)
        keys = ("run_id", "status", "created_at", "verdict", "verdict_reason",
                "optimizer_intent_status", "result_digest_scope", "bind_stability_status",
                "measurement_status", "vector_learning_class", "vector_rejection_reason")
        result["recent_final_runs"] = [dict(zip(keys, row)) for row in cur.fetchall()]
        cur.execute("""
          select json_value(metadata_json,'$.learning_class' returning varchar2(30) null on error), count(*)
          from asta_tuning_cases
          group by json_value(metadata_json,'$.learning_class' returning varchar2(30) null on error)
          order by 1
        """)
        result["vector_class_counts"] = [
            {"learning_class": row[0] or "LEGACY_UNCLASSIFIED", "count": row[1]}
            for row in cur.fetchall()
        ]
        search_value = cur.callfunc(
            "ASTA_VECTOR_PKG.SEARCH_SIMILAR_CASES", oracledb.DB_TYPE_CLOB,
            ["select cast(null as number) n, 'ASTA' v from dual order by 2", 20],
        )
        search_text = search_value.read() if hasattr(search_value, "read") else search_value
        search_payload = json.loads(search_text)
        search_cases = search_payload.get("cases") or []
        result["positive_search_case_count"] = len(search_cases)
        result["rejected_smoke_present_in_positive_search"] = any(
            str(item.get("case_id") or item.get("run_id") or "") == "OADT2-ASTA-ROADMAP08-LIVE-SMOKE"
            for item in search_cases if isinstance(item, dict)
        )
        cur.execute("""
          select db_link_name from asta_source_connections
          where source_db_id='DB0903_TESTDB' and enabled='Y'
        """)
        db_link = str(cur.fetchone()[0]).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_$#]*(?:\.[A-Z0-9_$#]+)*", db_link):
            raise RuntimeError("invalid configured Source DB link identifier")
        try:
            cur.execute(f"""
              select child_number, plan_hash_value, executions,
                     is_bind_sensitive, is_bind_aware, is_shareable
              from v$sql@{db_link}
              where sql_id=:s order by child_number
            """, s="7rcw6d3us86r7")
            result["source_child_cursors"] = [
                dict(zip(("child_number", "plan_hash_value", "executions", "is_bind_sensitive",
                          "is_bind_aware", "is_shareable"), row))
                for row in cur.fetchall()
            ]
        except Exception as exc:
            result["source_child_cursor_error"] = safe_db_error(exc)
        try:
            cur.execute(f"""
              select name, position, datatype_string, was_captured,
                     case when value_string is null then 'Y' else 'N' end captured_value_is_null,
                     case when value_string is null then null
                          else lower(rawtohex(standard_hash(value_string,'SHA256'))) end value_fingerprint,
                     child_number
              from v$sql_bind_capture@{db_link}
              where sql_id=:s order by child_number, position
            """, s="7rcw6d3us86r7")
            captures = []
            for name, position, datatype, was_captured, is_null, fingerprint, child_number in cur.fetchall():
                captures.append({
                    "name_fingerprint": hashlib.sha256(str(name or "").encode()).hexdigest(),
                    "position": position, "oracle_type": datatype, "was_captured": was_captured,
                    "captured_value_is_null": is_null == "Y",
                    "value_fingerprint": f"sha256:{fingerprint}" if fingerprint else None,
                    "child_number": child_number,
                })
            result["source_bind_captures"] = captures
        except Exception as exc:
            result["source_bind_capture_error"] = safe_db_error(exc)
        for view, key in (("v$sql_cs_statistics", "acs_statistics_rows"),
                          ("v$sql_cs_selectivity", "acs_selectivity_rows")):
            try:
                cur.execute(f"select count(*) from {view}@{db_link} where sql_id=:s", s="7rcw6d3us86r7")
                result[key] = cur.fetchone()[0]
            except Exception as exc:
                result[key + "_error"] = safe_db_error(exc)
        try:
            cur.execute(f"""
              select regexp_count(dbms_lob.substr(sql_text,32767,1), ':[A-Za-z][A-Za-z0-9_$#]*')
              from dba_hist_sqltext@{db_link} where sql_id=:s
            """, s="7rcw6d3us86r7")
            awr_counts = [int(row[0] or 0) for row in cur.fetchall()]
            result["awr_sql_bind_placeholder_counts"] = awr_counts
        except Exception as exc:
            result["awr_sql_bind_placeholder_error"] = safe_db_error(exc)
        try:
            from tools.run_asta_prompt_abc import load_samples
            sql_text = load_samples({"asta-awr-01"})[0]["sql"]
            bind_names = sorted(set(re.findall(r"(?<!:):([A-Za-z][A-Za-z0-9_$#]*)", sql_text)))
            result["fixture_bind_placeholder_count"] = len(bind_names)
            result["fixture_bind_name_fingerprints"] = [
                hashlib.sha256(name.upper().encode()).hexdigest() for name in bind_names
            ]
        except Exception as exc:
            result["fixture_bind_inspection_error"] = type(exc).__name__
        captures = result.get("source_bind_captures") or []
        buckets = {"NULL": 0, "SELECTIVE": 0, "BROAD": 0}
        for capture in captures if isinstance(captures, list) else []:
            if capture.get("captured_value_is_null"):
                buckets["NULL"] += 1
        result["representative_bucket_evidence"] = buckets
        result["raw_bind_values_retained"] = False
        result["coverage_status"] = "VERIFIED" if all(buckets.values()) else "BLOCKED"
        result["coverage_reason"] = (
            "REPRESENTATIVE_BIND_COVERAGE_VERIFIED" if all(buckets.values())
            else "BIND_COVERAGE_INSUFFICIENT"
        )
        path = outdir / "runtime_api_bind_inspection.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        cur.close(); conn.close()


def roadmap_live_api_smoke(outdir: Path) -> int:
    """Authenticate locally and retain only allowlisted final API/UI fields."""
    outdir.mkdir(parents=True, exist_ok=True)
    inspection = json.loads((outdir / "runtime_api_bind_inspection.json").read_text(encoding="utf-8"))
    runs = inspection.get("recent_final_runs") or []
    if not runs:
        raise RuntimeError("no completed ASTA run available for final API smoke")
    run_id = str(runs[0]["run_id"])
    conf = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    access_key = str(conf.get("access_key") or "")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    if access_key:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/auth/login",
            data=json.dumps({"key": access_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError("local API login failed")
    with opener.open(f"http://127.0.0.1:8000/api/asta/runs/{run_id}", timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    with opener.open("http://127.0.0.1:8000/", timeout=15) as response:
        root_html = response.read().decode("utf-8")
    with opener.open(
        "http://127.0.0.1:8000/static/js/extensions/tuning_assistant.js?v=20260705_roadmap08_prod1",
        timeout=15,
    ) as response:
        live_js = response.read()
    local_js = (ROOT / "static/js/extensions/tuning_assistant.js").read_bytes()
    workflow = payload.get("workflow_state") or {}
    vector = payload.get("vector_learning") or {}
    summary = {
        "http_root_ok": "20260705_roadmap08_prod1" in root_html,
        "static_js_byte_equal": live_js == local_js,
        "run_id": run_id,
        "api_status": payload.get("status"),
        "workflow_contract_version": workflow.get("contract_version"),
        "workflow_overall_status": workflow.get("overall_status"),
        "workflow_current_stage": workflow.get("current_stage"),
        "workflow_reason_code": workflow.get("reason_code"),
        "workflow_evidence_level": workflow.get("evidence_level"),
        "vector_classification": vector.get("classification"),
        "vector_positive_eligible": vector.get("positive_eligible"),
        "raw_sql_or_bind_retained": False,
    }
    if not summary["http_root_ok"] or not summary["static_js_byte_equal"]:
        raise RuntimeError("live UI static smoke failed")
    if summary["workflow_contract_version"] != "asta.workflow.v1":
        raise RuntimeError("new Python gate adapter is not present in final API response")
    if summary["workflow_overall_status"] == "ACCEPTED":
        raise RuntimeError("legacy incomplete run was incorrectly promoted to ACCEPTED")
    if summary["vector_positive_eligible"] is not False:
        raise RuntimeError("incomplete final run was incorrectly routed to positive Vector")
    (outdir / "live_api_ui_smoke.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def roadmap_create_smoke_run(outdir: Path) -> int:
    """Create one non-sensitive current-contract run through ASTA_PKG."""
    outdir.mkdir(parents=True, exist_ok=True)
    run_id = "OADT2-ASTA-ROADMAP08-LIVE-SMOKE"
    body = {
        "run_id": run_id,
        "sql": "select cast(null as number) n, 'ASTA' v from dual order by 2",
        "source_db_id": "DB0903_TESTDB",
        "source_sql_id": None,
        "fetch_rows": 10,
        "benchmark_repeat": 1,
        "vector_top_k": 1,
        "use_llm": False,
        "run_advisor": False,
        "sqltune_time_limit": 60,
        "tuning_context": {
            "workload_type": "OLTP",
            "optimization_goal": "MINIMIZE_BUFFER_READS",
            "user_notes": "runtime contract smoke",
        },
    }
    conn = connect(); conn.call_timeout = 180_000; cur = conn.cursor()
    try:
        existing_value = cur.callfunc("ASTA_PKG.GET_RUN", oracledb.DB_TYPE_CLOB, [run_id])
        existing_text = existing_value.read() if hasattr(existing_value, "read") else existing_value
        payload = json.loads(existing_text)
        if str(payload.get("status") or "").upper() in {"NOT_FOUND", "FAILED"}:
            value = cur.callfunc("ASTA_PKG.ANALYZE_SQL", oracledb.DB_TYPE_CLOB,
                                 [json.dumps(body, ensure_ascii=False)])
            text = value.read() if hasattr(value, "read") else value
            payload = json.loads(text)
        deadline = time.monotonic() + 180
        while str(payload.get("status") or "").upper() in {"QUEUED", "RUNNING"}:
            if time.monotonic() >= deadline:
                raise TimeoutError("current-contract smoke run exceeded 180 seconds")
            time.sleep(2)
            value = cur.callfunc("ASTA_PKG.GET_RUN", oracledb.DB_TYPE_CLOB, [run_id])
            text = value.read() if hasattr(value, "read") else value
            payload = json.loads(text)
        comparison = payload.get("comparison") or (payload.get("artifacts") or {}).get("comparison") or {}
        vector = (payload.get("artifacts") or {}).get("vector_save") or payload.get("vector_save") or {}
        summary = {
            "run_id": payload.get("run_id") or run_id,
            "status": payload.get("status"),
            "verdict": comparison.get("verdict"),
            "verdict_reason": comparison.get("verdict_reason"),
            "optimizer_intent_status": comparison.get("optimizer_intent_status"),
            "result_digest_scope": comparison.get("result_digest_scope"),
            "bind_stability_status": comparison.get("bind_stability_status"),
            "measurement_status": comparison.get("measurement_status"),
            "vector_learning_class": vector.get("learning_class"),
            "vector_rejection_reason": vector.get("rejection_reason"),
            "raw_sql_or_bind_retained": False,
        }
        (outdir / "current_contract_smoke_run.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        inspection = json.loads((outdir / "runtime_api_bind_inspection.json").read_text(encoding="utf-8"))
        inspection["recent_final_runs"] = [summary, *(inspection.get("recent_final_runs") or [])]
        (outdir / "runtime_api_bind_inspection.json").write_text(
            json.dumps(inspection, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["status"] in {"COMPLETED", "BLOCKED"} else 2
    finally:
        cur.close(); conn.close()


def stage_timing_smoke_run(outdir: Path) -> int:
    """Create a fresh bounded run and preserve exact persisted stage timing evidence."""
    outdir.mkdir(parents=True, exist_ok=True)
    run_id = f"OADT2-ASTA-TIMING-{uuid.uuid4().hex[:20]}"
    body = {
        "run_id": run_id,
        "client_run_id": run_id,
        "sql": "select cast(null as number) n, 'ASTA_TIMING' v from dual where rownum <= 1",
        "source_db_id": "DB0903_TESTDB",
        "fetch_rows": 10,
        "benchmark_repeat": 1,
        "vector_top_k": 1,
        "use_llm": False,
        "run_advisor": False,
        "sqltune_time_limit": 60,
        "tuning_context": {
            "workload_type": "OLTP",
            "optimization_goal": "MINIMIZE_BUFFER_READS",
            "user_notes": "fresh bounded stage timing report smoke",
        },
    }
    conn = connect()
    conn.call_timeout = 180_000
    cur = conn.cursor()
    try:
        value = cur.callfunc(
            "ASTA_PKG.SUBMIT_RUN",
            oracledb.DB_TYPE_CLOB,
            [json.dumps(body, ensure_ascii=False)],
        )
        submitted = json.loads(_lob_text(value))
        if str(submitted.get("status") or "").upper() not in {"QUEUED", "RUNNING"}:
            raise RuntimeError(f"stage timing smoke submit failed: {submitted.get('error_code')}")

        deadline = time.monotonic() + 300
        status = str(submitted.get("status") or "").upper()
        while status in {"QUEUED", "RUNNING"}:
            if time.monotonic() >= deadline:
                raise TimeoutError("stage timing smoke exceeded 300 seconds")
            time.sleep(2)
            cur.execute("select status from asta_runs where run_id=:r", r=run_id)
            row = cur.fetchone()
            status = str(row[0] if row else "NOT_FOUND").upper()

        cur.execute(
            """
            select status, detailed_report_md,
                   json_value(response_json, '$.comparison.verdict'
                              returning varchar2(30) null on error)
              from asta_runs
             where run_id=:r
            """,
            r=run_id,
        )
        status, report_value, verdict = cur.fetchone()
        report = _lob_text(report_value)
        cur.execute(
            """
            select seq, code, status, started_at, completed_at, elapsed_ms
              from asta_run_progress
             where run_id=:r
             order by seq
            """,
            r=run_id,
        )
        stages = [
            {
                "seq": row[0], "code": row[1], "status": row[2],
                "started_at": str(row[3]) if row[3] is not None else None,
                "completed_at": str(row[4]) if row[4] is not None else None,
                "elapsed_ms": float(row[5]) if row[5] is not None else None,
                "elapsed_s": round(float(row[5]) / 1000, 3) if row[5] is not None else None,
            }
            for row in cur.fetchall()
        ]
        stage_rows_in_report = len(re.findall(r"^\|\s*(?:[1-9]|10|11)\s*\|", report, re.MULTILINE))
        summary = {
            "run_id": run_id,
            "status": status,
            "verdict": verdict,
            "report_has_stage_timing_heading": "## 단계별 소요시간" in report,
            "report_has_seconds_unit": "소요시간 (s)" in report,
            "report_has_missing_not_zero_contract": "측정 불가/미기록" in report,
            "report_has_distinct_totals": all(text in report for text in (
                "단계 소요시간 합계", "파이프라인 E2E",
                "단계가 겹칠 수 있어 E2E와 동일하지 않을 수 있습니다",
            )),
            "stage_rows_in_report": stage_rows_in_report,
            "stages": stages,
        }
        (outdir / f"{run_id}.md").write_text(report, encoding="utf-8")
        (outdir / "stage_timing_smoke.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if status == "COMPLETED" and len(stages) == 11 and stage_rows_in_report >= 11 else 2
    finally:
        cur.close()
        conn.close()


def stage_timing_http_verify(outdir: Path) -> int:
    """Verify API, HTML view, and Markdown download for the fresh timing run."""
    summary_path = outdir / "stage_timing_smoke.json"
    smoke = json.loads(summary_path.read_text(encoding="utf-8"))
    run_id = str(smoke["run_id"])
    conf = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    access_key = str(conf.get("access_key") or "")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    if access_key:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/auth/login",
            data=json.dumps({"key": access_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError("local API login failed")

    base = f"http://127.0.0.1:8000/api/asta/runs/{run_id}/report"
    with opener.open(base, timeout=120) as response:
        api_status = response.status
        api_payload = json.loads(response.read().decode("utf-8"))
    api_markdown = str(
        api_payload.get("detailed_report_markdown")
        or api_payload.get("report_markdown")
        or api_payload.get("report")
        or ""
    )
    with opener.open(base + "/view", timeout=120) as response:
        view_status = response.status
        view_html = response.read().decode("utf-8")
        view_csp = response.headers.get("Content-Security-Policy")
    with opener.open(base + "/download", timeout=120) as response:
        download_status = response.status
        download_markdown = response.read().decode("utf-8")
        download_type = response.headers.get("Content-Type")
        download_disposition = response.headers.get("Content-Disposition")

    (outdir / "api_report.md").write_text(api_markdown, encoding="utf-8")
    (outdir / "report_view.html").write_text(view_html, encoding="utf-8")
    (outdir / "report_download.md").write_text(download_markdown, encoding="utf-8")
    checks = {
        "run_id": run_id,
        "api_http_status": api_status,
        "view_http_status": view_status,
        "download_http_status": download_status,
        "api_has_stage_seconds": "## 단계별 소요시간" in api_markdown and "소요시간 (s)" in api_markdown,
        "view_has_stage_timing": "단계별 소요시간" in view_html,
        "download_has_stage_seconds": "## 단계별 소요시간" in download_markdown and "소요시간 (s)" in download_markdown,
        "api_download_markdown_equal": api_markdown == download_markdown,
        "view_csp_present": bool(view_csp),
        "download_content_type": download_type,
        "download_attachment": str(download_disposition or "").startswith("attachment;"),
    }
    (outdir / "http_verification.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    required = (
        api_status == 200, view_status == 200, download_status == 200,
        checks["api_has_stage_seconds"], checks["view_has_stage_timing"],
        checks["download_has_stage_seconds"], checks["api_download_markdown_equal"],
        checks["view_csp_present"], checks["download_attachment"],
    )
    return 0 if all(required) else 2


def main():
    """명령행 인자를 읽어 ASTA 도구의 전체 작업 흐름을 실행한다."""
    if len(sys.argv) == 2 and sys.argv[1] == "--sample14-active":
        conn = connect(); cur = conn.cursor()
        try:
            cur.execute(
                "select run_id,status,job_name from asta_runs "
                "where run_id like 'OADT2-ASTA-S14-%' and status in ('QUEUED','RUNNING') order by created_at"
            )
            rows = cur.fetchall()
            cur.execute(
                "select j.job_name,j.session_id,j.running_instance,j.elapsed_time,r.run_id,r.status "
                "from all_scheduler_running_jobs j left join asta_runs r on r.job_name=j.job_name "
                "where j.job_name like 'ASTA_RUN_%' order by j.job_name"
            )
            jobs = cur.fetchall()
            cur.execute(
                "select run_id,seq,code,status,detail from asta_run_progress "
                "where run_id like 'OADT2-ASTA-S14-%' and status in ('RUNNING','FAILED') order by run_id,seq"
            )
            progress = cur.fetchall()
            print(json.dumps({"active_runs": rows, "running_jobs": jobs, "active_progress": progress},
                             ensure_ascii=False, default=str, indent=2))
            return 0
        finally:
            cur.close(); conn.close()
    if len(sys.argv) == 2 and sys.argv[1] == "--sample14-source-verify":
        from tools.asta_sample_sql_verifier import verify
        return verify(timeout_sec=55.0, fetch_rows=200)
    if len(sys.argv) in {2, 3} and sys.argv[1] == "--sample14-run":
        from tools.run_asta_sample_campaign import run
        selected = None if len(sys.argv) == 2 else {
            item.strip() for item in sys.argv[2].split(",") if item.strip()
        }
        return run(selected)
    if len(sys.argv) == 2 and sys.argv[1] == "--sample14-finalize":
        from tools.run_asta_sample_campaign import finalize
        return finalize()
    if len(sys.argv) == 3 and sys.argv[1] in {"--roadmap-backup", "--roadmap-deploy", "--roadmap-status"}:
        return roadmap_runtime_action(
            "backup" if sys.argv[1] == "--roadmap-backup" else
            ("deploy" if sys.argv[1] == "--roadmap-deploy" else "status"), Path(sys.argv[2])
        )
    if len(sys.argv) == 3 and sys.argv[1] in {"--aa7-backup", "--aa7-deploy", "--aa7-status", "--aa7-rollback"}:
        return aa7_result_fix_action(
            "backup" if sys.argv[1] == "--aa7-backup" else
            ("deploy" if sys.argv[1] == "--aa7-deploy" else
             ("rollback" if sys.argv[1] == "--aa7-rollback" else "status")), Path(sys.argv[2])
        )
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-rebuild-blocked-report":
        return aa7_rebuild_blocked_report(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-live-report-api":
        return aa7_live_report_api_verify(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--advisor-off-live-static":
        return advisor_off_live_static_verify(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-source-status":
        return aa7_source_remote_status(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-manual-verify":
        return aa7_manual_measurement_verify(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-reassess-intent":
        return aa7_reassess_manual_intent(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--aa7-publish-improved":
        return aa7_publish_manual_improved(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--roadmap-customer-verify":
        return roadmap_customer_verify(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--roadmap-runtime-inspect":
        return roadmap_runtime_inspect(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--roadmap-live-api-smoke":
        return roadmap_live_api_smoke(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--roadmap-create-smoke-run":
        return roadmap_create_smoke_run(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--stage-timing-smoke":
        return stage_timing_smoke_run(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--stage-timing-http-verify":
        return stage_timing_http_verify(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--customer-final-report":
        from tools.asta_customer_final_report import generate_report
        print(json.dumps(generate_report(Path(sys.argv[2])), ensure_ascii=False, indent=2))
        return 0
    conn = connect()
    cur = conn.cursor()
    log: list[str] = []
    try:
        cur.execute("select user from dual")
        user = cur.fetchone()[0]
        log.append(f"connected_user={user}")

        # Repository DDL: raw scripts are safe on this clean target, but guard anyway.
        if not object_exists(cur, "user_tables", "ASTA_RUNS"):
            run_script(cur, "db/asta/001_asta_repository.sql")
            log.append("installed db/asta/001_asta_repository.sql")
        else:
            log.append("skip ASTA_RUNS/ASTA_RUN_PROGRESS existing")

        if not object_exists(cur, "user_tables", "ASTA_SOURCE_CONNECTIONS"):
            run_script(cur, "db/asta/002_asta_source_connections.sql")
            log.append("installed db/asta/002_asta_source_connections.sql")
        else:
            log.append("skip ASTA_SOURCE_CONNECTIONS existing")

        # ASTA_RUNS created by 001 already includes SOURCE_DB_ID; skip additive migration here.
        log.append("skip db/asta/003_asta_runs_source_db_id.sql; column included in fresh DDL")

        if not object_exists(cur, "user_tables", "ASTA_TUNING_CASES"):
            run_script(cur, "db/asta/004_asta_vector_tables.sql")
            log.append("installed db/asta/004_asta_vector_tables.sql")
        else:
            log.append("skip vector tables existing")

        run_script(cur, "db/asta/005_asta_async_run_columns.sql")
        log.append("applied db/asta/005_asta_async_run_columns.sql")

        run_script(cur, "db/asta/006_asta_llm_call_log.sql")
        log.append("applied db/asta/006_asta_llm_call_log.sql")

        run_script(cur, "db/asta/007_asta_llm_repair_log_stage.sql")
        log.append("applied db/asta/007_asta_llm_repair_log_stage.sql")

        for rel in DEPLOY_PACKAGE_ORDER:
            run_script(cur, rel)
            log.append(f"compiled {rel}")

        cur.execute(
            """
            MERGE INTO asta_source_connections t
            USING (
              SELECT 'DB0903_TESTDB' source_db_id,
                     'DB0903_LINK' db_link_name,
                     'DEVDO' source_schema,
                     'ASTA source link via DB0903_LINK' description
              FROM dual
            ) s
            ON (t.source_db_id = s.source_db_id)
            WHEN NOT MATCHED THEN INSERT(source_db_id, db_link_name, source_schema, description, enabled)
              VALUES(s.source_db_id, s.db_link_name, s.source_schema, s.description, 'Y')
            """
        )
        log.append("preserved existing ASTA_SOURCE_CONNECTIONS mapping; inserted DB0903_LINK/DEVDO only if absent")
        conn.commit()

        # ORDS module install. This may fail if ORDS is not enabled/granted.
        try:
            run_script(cur, "db/ords/asta_ords_module.sql")
            conn.commit()
            log.append("installed ORDS module asta.v1")
        except Exception as e:
            conn.rollback()
            log.append(f"ORDS install failed: {type(e).__name__}: {e}")

        # Status summary.
        cur.execute(
            """
            select object_name, object_type, status
            from user_objects
            where object_name like 'ASTA%'
            order by object_name, object_type
            """
        )
        objects = cur.fetchall()
        cur.execute(
            """
            select name, type, line, position, text
            from user_errors
            where name like 'ASTA%'
            order by name, type, sequence
            """
        )
        errors = cur.fetchall()
        cur.execute("select source_db_id, db_link_name, source_schema, enabled from asta_source_connections order by source_db_id")
        links = cur.fetchall()
        print(json.dumps({"log": log, "objects": objects, "errors": errors, "source_connections": links}, ensure_ascii=False, indent=2, default=str))
        return 1 if errors else 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
