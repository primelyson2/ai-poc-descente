#!/usr/bin/env python3
"""최신 ASTA 품질 보고서를 근거로 소스를 한 번 개선하고 배포 대기 상태로 둔다."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports" / "asta_quality_agent"
LAST_DEPLOYMENT = REPORT_ROOT / "last_deployment.json"
ALLOWED = ("db/adb", "db/source", "tests", "tools", "docs")
PYTEST = ["uv", "run", "--with", "pytest", "pytest", "-q"]
PYTHON = str(ROOT / ".venv" / "bin" / "python")


def codex_command(prompt: str) -> list[str]:
    """승인 입력 없이 workspace sandbox 안에서 Codex를 실행한다."""
    return [
        "codex", "--ask-for-approval", "never", "exec",
        "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), prompt,
    ]


def deployment_commands(paths: set[str]) -> list[tuple[str, list[str], int]]:
    """변경된 DB 패키지만 의존 순서대로 배포하고 실제 workflow를 확인한다."""
    commands: list[tuple[str, list[str], int]] = []
    if any(path.startswith("db/source/") for path in paths):
        commands.append(("source_deploy", [PYTHON, "tools/asta_deploy_source.py"], 600))
    if any(path.startswith("db/adb/") for path in paths):
        commands.extend([
            ("adb_deploy", [PYTHON, "tools/asta_deploy_adb.py"], 900),
            ("adb_smoke", [PYTHON, "tools/asta_smoke_adb.py", "--deployment-only"], 300),
        ])
    return commands


def deploy(paths: set[str], work_dir: pathlib.Path, prefix: str = "deploy") -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for name, command, timeout in deployment_commands(paths):
        code, _ = run(command, work_dir / f"{prefix}_{name}.log", timeout)
        results.append({"name": name, "command": command, "returncode": code,
                        "log": str(work_dir / f"{prefix}_{name}.log")})
        if code:
            return False, results
    return True, results


def run(command: list[str], log: pathlib.Path, timeout: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=timeout, check=False)
        output = completed.stdout or ""
        code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        output = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        output += "\nTIMEOUT\n"
        code = 124
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(output, encoding="utf-8")
    return code, output


def failed_tests(output: str) -> set[str]:
    return set(re.findall(r"^FAILED\s+([^\s]+)", output, flags=re.MULTILINE))


def status_paths() -> set[str]:
    out = subprocess.check_output(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True)
    return {line[3:] for line in out.splitlines() if len(line) > 3}


def is_allowed(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ALLOWED)


def rollback(patch: pathlib.Path, untracked: set[str]) -> None:
    if patch.is_file() and patch.stat().st_size:
        completed = subprocess.run(["git", "apply", "--reverse", "--whitespace=nowarn", str(patch)],
                                   cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode:
            raise RuntimeError(f"rollback 실패: {completed.stderr}")
    for relative in sorted(untracked, reverse=True):
        target = (ROOT / relative).resolve()
        if ROOT in target.parents and target.is_file():
            target.unlink()


def main() -> int:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    if status_paths():
        print(json.dumps({"status": "SKIPPED", "reason": "DIRTY_WORKTREE"}), file=sys.stderr)
        return 2
    latest_md = REPORT_ROOT / "latest.md"
    latest_json = REPORT_ROOT / "latest.json"
    if not latest_md.is_file() or not latest_json.is_file():
        print(json.dumps({"status": "SKIPPED", "reason": "NO_QUALITY_REPORT"}), file=sys.stderr)
        return 2
    decision = json.loads(latest_json.read_text(encoding="utf-8"))
    if decision.get("decision") == "DEPLOY_REVIEW_READY":
        print(json.dumps({"status": "SKIPPED", "reason": "QUALITY_GATE_ALREADY_PASSED"}))
        return 0

    cycle = str(decision.get("cycle_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    work_dir = REPORT_ROOT / cycle / "autopilot"
    work_dir.mkdir(parents=True, exist_ok=True)
    _, baseline_output = run(PYTEST, work_dir / "baseline_pytest.log", 600)
    baseline_failures = failed_tests(baseline_output)

    prompt = (
        f"{latest_md} 파일을 읽고 ASTA 결과 품질을 높이는 소스 변경을 정확히 한 가지 수행하라. "
        "첫 고객 SQL asta-awr-01의 안전한 구조 재작성 성공률을 최우선으로 하라. "
        "허용 경로는 db/adb, db/source, tests, tools, docs뿐이다. 관련 회귀 테스트를 추가하라. "
        "DB 접속, package compile, 배포, git commit/push, credential 변경은 하지 마라. "
        "패키지 배포와 DB smoke는 이 실행을 호출한 오케스트레이터가 변경 검증 후 수행한다. "
        "한 회차에는 원인이 명확하고 되돌릴 수 있는 작은 변경만 하라."
    )
    codex_code, _ = run(codex_command(prompt), work_dir / "codex.log", 1800)
    paths = status_paths()
    untracked = {path for path in paths if subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode != 0}
    patch = work_dir / "candidate.patch"
    patch.write_bytes(subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff"], cwd=ROOT))

    reject_reason = None
    if codex_code:
        reject_reason = f"CODEX_EXIT_{codex_code}"
    elif not paths:
        reject_reason = "NO_CHANGES"
    elif any(not is_allowed(path) for path in paths):
        reject_reason = "DISALLOWED_PATHS"
    else:
        _, candidate_output = run(PYTEST, work_dir / "candidate_pytest.log", 600)
        candidate_failures = failed_tests(candidate_output)
        new_failures = candidate_failures - baseline_failures
        if new_failures:
            reject_reason = "NEW_TEST_FAILURES: " + ", ".join(sorted(new_failures))

    deploy_results: list[dict[str, Any]] = []
    db_paths = {path for path in paths if path.startswith(("db/adb/", "db/source/"))}
    if not reject_reason and db_paths:
        deployed, deploy_results = deploy(db_paths, work_dir)
        if not deployed:
            reject_reason = "DB_DEPLOYMENT_FAILED"

    if reject_reason:
        rollback(patch, untracked)
        restore_results: list[dict[str, Any]] = []
        restore_ok = True
        if deploy_results:
            restore_ok, restore_results = deploy(db_paths, work_dir, "restore")
        result = {"status": "REJECTED", "reason": reject_reason, "cycle_id": cycle,
                  "deployment": deploy_results, "database_restore_ok": restore_ok,
                  "database_restore": restore_results}
        (work_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1

    subprocess.run(["git", "add", "--", *sorted(paths)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"Improve ASTA quality from experiment {cycle}"], cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = {
        "status": "ACCEPTED_DEPLOYED" if deploy_results else "ACCEPTED",
        "cycle_id": cycle,
        "commit": commit,
        "changed_paths": sorted(paths),
        "automatic_db_deployment": bool(deploy_results),
        "deployment": deploy_results,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    LAST_DEPLOYMENT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
