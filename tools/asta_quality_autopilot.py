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
PENDING = REPORT_ROOT / "pending_deployment.json"
ALLOWED = ("db/adb", "tests", "tools", "docs")
PYTEST = ["uv", "run", "--with", "pytest", "pytest", "-q"]


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
    if PENDING.exists():
        print(json.dumps({"status": "SKIPPED", "reason": "PENDING_DEPLOYMENT", "marker": str(PENDING)}))
        return 0
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
        "허용 경로는 db/adb, tests, tools, docs뿐이다. 관련 회귀 테스트를 추가하라. "
        "DB 접속, package compile, 배포, git commit/push, credential 변경은 하지 마라. "
        "한 회차에는 원인이 명확하고 되돌릴 수 있는 작은 변경만 하라."
    )
    codex_command = ["codex", "exec", "--ephemeral", "--sandbox", "workspace-write", "-C", str(ROOT), prompt]
    codex_code, _ = run(codex_command, work_dir / "codex.log", 1800)
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

    if reject_reason:
        rollback(patch, untracked)
        result = {"status": "REJECTED", "reason": reject_reason, "cycle_id": cycle}
        (work_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1

    subprocess.run(["git", "add", "--", *sorted(paths)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"Improve ASTA quality from experiment {cycle}"], cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = {
        "status": "ACCEPTED_PENDING_DEPLOYMENT",
        "cycle_id": cycle,
        "commit": commit,
        "changed_paths": sorted(paths),
        "automatic_db_deployment": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    PENDING.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
