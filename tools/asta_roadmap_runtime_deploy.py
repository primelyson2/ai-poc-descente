"""Minimal, rollback-first deployment for ASTA roadmap runtime packages.

No repository DDL, allowlist, ORDS metadata, or unrelated package is touched.
The command prints only object/status summaries; credentials and package DDL
remain in the local backup directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from tools.asta_deploy_adb import connect as connect_adb
    from tools.asta_deploy_adb import run_script
    from tools.asta_deploy_source import exec_stmt, source_config, split_sqlplus_script
except ModuleNotFoundError:  # direct ``python tools/...py`` execution
    from asta_deploy_adb import connect as connect_adb
    from asta_deploy_adb import run_script
    from asta_deploy_source import exec_stmt, source_config, split_sqlplus_script

import oracledb


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGES = {"ASTA_SOURCE_PKG": "db/source/asta_source_pkg.sql"}
ADB_PACKAGES = {
    "ASTA_SOURCE_BRIDGE_PKG": "db/adb/asta_source_bridge_pkg.sql",
    "ASTA_VECTOR_PKG": "db/adb/asta_vector_pkg.sql",
    "ASTA_PKG": "db/adb/asta_pkg.sql",
}


def connect_source():
    user, password, dsn = source_config()
    return oracledb.connect(user=user, password=password, dsn=dsn)


def _read_lob(value: Any) -> str:
    return value.read() if hasattr(value, "read") else str(value or "")


def object_state(conn, names: list[str]) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        binds = ",".join(f":n{i}" for i in range(len(names)))
        params = {f"n{i}": name.upper() for i, name in enumerate(names)}
        cur.execute(
            f"select object_name, object_type, status, last_ddl_time from user_objects "
            f"where object_name in ({binds}) and object_type in ('PACKAGE','PACKAGE BODY') "
            "order by object_name, object_type",
            params,
        )
        objects = [dict(zip([d[0].lower() for d in cur.description], row)) for row in cur.fetchall()]
        cur.execute(
            f"select name, type, line, position, text from user_errors "
            f"where name in ({binds}) order by name, sequence",
            params,
        )
        errors = [dict(zip([d[0].lower() for d in cur.description], row)) for row in cur.fetchall()]
        return {"objects": objects, "errors": errors}
    finally:
        cur.close()


def backup_packages(conn, packages: dict[str, str], target: Path, label: str) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    saved: list[str] = []
    try:
        for name in packages:
            for object_type, suffix in (("PACKAGE", "spec"), ("PACKAGE_BODY", "body")):
                cur.execute("select dbms_metadata.get_ddl(:t,:n,user) from dual", t=object_type, n=name)
                ddl = _read_lob(cur.fetchone()[0]).rstrip()
                path = target / f"{label}_{name.lower()}_{suffix}.sql"
                path.write_text(ddl + "\n/\n", encoding="utf-8")
                saved.append(path.name)
        state = object_state(conn, list(packages))
        (target / f"{label}_status_before.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return {"saved": saved, "status": state}
    finally:
        cur.close()


def _assert_valid(conn, package_names: list[str]) -> dict[str, Any]:
    state = object_state(conn, package_names)
    expected = {(name, typ) for name in package_names for typ in ("PACKAGE", "PACKAGE BODY")}
    actual = {
        (row["object_name"], row["object_type"])
        for row in state["objects"] if row["status"] == "VALID"
    }
    if state["errors"] or actual != expected:
        raise RuntimeError(f"package validation failed: valid={sorted(actual)}, errors={len(state['errors'])}")
    return state


def deploy_source(conn) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        text = (ROOT / SOURCE_PACKAGES["ASTA_SOURCE_PKG"]).read_text(encoding="utf-8")
        for statement in split_sqlplus_script(text):
            exec_stmt(cur, statement)
        state = _assert_valid(conn, ["ASTA_SOURCE_PKG"])
        cur.execute(
            """select asta_source_pkg.run_evidence(
                 p_sql => 'select cast(null as number) n, ''ASTA'' v from dual',
                 p_run_id => 'ROADMAP08_SOURCE_SMOKE', p_fetch_rows => 10,
                 p_repeat_policy => 'ONCE', p_run_advisor => 'N',
                 p_sqltune_time_sec => 60, p_result_evidence_mode => 'FULL_RESULT',
                 p_result_max_rows => 100) from dual"""
        )
        smoke = json.loads(_read_lob(cur.fetchone()[0]))
        allowed = {
            "status": smoke.get("status"),
            "result_digest_status": smoke.get("result_digest_status"),
            "result_digest_scope": smoke.get("result_digest_scope"),
            "result_digest_mode": smoke.get("result_digest_mode"),
            "result_total_rows": smoke.get("result_total_rows"),
            "result_evidence_complete": smoke.get("result_evidence_complete"),
            "bind_coverage_status": (smoke.get("child_cursor_evidence") or {}).get("bind_coverage_status"),
            "bind_coverage_reason": (smoke.get("child_cursor_evidence") or {}).get("bind_coverage_reason"),
        }
        if allowed["status"] != "COMPLETED" or allowed["result_digest_status"] != "COMPLETED":
            raise RuntimeError(f"source full-result smoke failed: {allowed}")
        return {"state": state, "smoke": allowed}
    finally:
        cur.close()


def deploy_adb(conn) -> dict[str, Any]:
    deployed: list[str] = []
    for name, rel_path in ADB_PACKAGES.items():
        run_script(conn.cursor(), rel_path)
        _assert_valid(conn, [name])
        deployed.append(name)
    conn.commit()
    return {"deployed": deployed, "state": _assert_valid(conn, list(ADB_PACKAGES))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "deploy-source", "deploy-adb", "status"))
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()
    out: dict[str, Any] = {"action": args.action, "backup_dir": str(args.backup_dir)}
    if args.action == "backup":
        source = connect_source()
        adb = connect_adb()
        try:
            out["source"] = backup_packages(source, SOURCE_PACKAGES, args.backup_dir, "source")
            out["adb"] = backup_packages(adb, ADB_PACKAGES, args.backup_dir, "adb")
        finally:
            source.close(); adb.close()
    elif args.action == "deploy-source":
        conn = connect_source()
        try: out["source"] = deploy_source(conn)
        finally: conn.close()
    elif args.action == "deploy-adb":
        conn = connect_adb()
        try: out["adb"] = deploy_adb(conn)
        finally: conn.close()
    else:
        source = connect_source(); adb = connect_adb()
        try:
            out["source"] = object_state(source, list(SOURCE_PACKAGES))
            out["adb"] = object_state(adb, list(ADB_PACKAGES))
        finally:
            source.close(); adb.close()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
