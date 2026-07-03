#!/usr/bin/env python3
"""ASTA 품질을 반복 측정하고 안전하게 개선 명령을 실행하는 loop agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    passed: bool
    required: bool
    weight: float
    elapsed_sec: float
    returncode: int
    command: list[str]
    log_path: str


@dataclass
class Evaluation:
    score: float
    max_score: float
    required_passed: bool
    checks: list[CheckResult]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: pathlib.Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config 최상위 값은 object여야 합니다")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("config.checks에 하나 이상의 검증 명령이 필요합니다")
    for index, check in enumerate(checks, 1):
        if not isinstance(check, dict) or not check.get("name") or not check.get("command"):
            raise ValueError(f"checks[{index}]에는 name과 command가 필요합니다")
        if not isinstance(check["command"], list) or not all(isinstance(x, str) for x in check["command"]):
            raise ValueError(f"checks[{index}].command는 문자열 배열이어야 합니다")
    return data


def run_command(command: list[str], cwd: pathlib.Path, timeout: int, log_path: pathlib.Path) -> tuple[int, float]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            check=False,
        )
        output = completed.stdout or ""
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        output = (partial.decode(errors="replace") if isinstance(partial, bytes) else partial)
        output += f"\nTIMEOUT after {timeout}s\n"
        returncode = 124
    elapsed = round(time.monotonic() - started, 3)
    log_path.write_text(output, encoding="utf-8")
    return returncode, elapsed


def evaluate(config: dict[str, Any], run_dir: pathlib.Path, label: str) -> Evaluation:
    result_dir = run_dir / label
    result_dir.mkdir(parents=True, exist_ok=True)
    results: list[CheckResult] = []
    for index, check in enumerate(config["checks"], 1):
        name = str(check["name"])
        command = list(check["command"])
        required = bool(check.get("required", True))
        weight = float(check.get("weight", 1.0))
        timeout = int(check.get("timeout_sec", 600))
        log_path = result_dir / f"{index:02d}_{safe_name(name)}.log"
        print(f"[{label}] {name}: {shlex.join(command)}", flush=True)
        returncode, elapsed = run_command(command, ROOT, timeout, log_path)
        results.append(CheckResult(name, returncode == 0, required, weight, elapsed, returncode, command, str(log_path)))
    max_score = sum(item.weight for item in results)
    score = sum(item.weight for item in results if item.passed)
    required_passed = all(item.passed for item in results if item.required)
    evaluation = Evaluation(round(score, 4), round(max_score, 4), required_passed, results)
    (result_dir / "evaluation.json").write_text(
        json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return evaluation


def safe_name(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "check"


def evaluation_to_dict(value: Evaluation) -> dict[str, Any]:
    return {"score": value.score, "max_score": value.max_score, "required_passed": value.required_passed,
            "checks": [asdict(item) for item in value.checks]}


def git_output(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} 실패")
    return completed.stdout


def workspace_paths() -> set[str]:
    lines = git_output("status", "--porcelain=v1", "--untracked-files=all").splitlines()
    return {line[3:] for line in lines if len(line) > 3}


def changed_paths() -> set[str]:
    return workspace_paths()


def is_tracked(path: str) -> bool:
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def allowed_changes(paths: set[str], prefixes: list[str]) -> tuple[bool, list[str]]:
    denied = sorted(path for path in paths if not any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes))
    return not denied, denied


def capture_patch(path: pathlib.Path) -> None:
    path.write_bytes(subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff"], cwd=ROOT))


def apply_patch_file(path: pathlib.Path, reverse: bool = False) -> None:
    if not path.exists() or not path.stat().st_size:
        return
    command = ["git", "apply"]
    if reverse:
        command.append("--reverse")
    command.extend(["--whitespace=nowarn", str(path)])
    completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(f"변경 복구 실패: {completed.stderr.strip()}")


def backup_untracked(paths: set[str], backup_dir: pathlib.Path) -> None:
    for relative in paths:
        source = (ROOT / relative).resolve()
        if ROOT in source.parents and source.is_file():
            destination = backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def workspace_fingerprint() -> str:
    diff = subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff"], cwd=ROOT)
    digest = hashlib.sha256(diff)
    for relative in sorted(path for path in workspace_paths() if not is_tracked(path)):
        digest.update(relative.encode("utf-8"))
        target = ROOT / relative
        if target.is_file():
            digest.update(target.read_bytes())
    return digest.hexdigest()


def rollback_changes(candidate_patch: pathlib.Path, previous_patch: pathlib.Path,
                     previous_untracked: set[str], backup_dir: pathlib.Path,
                     new_untracked: set[str]) -> None:
    apply_patch_file(candidate_patch, reverse=True)
    apply_patch_file(previous_patch)
    for relative in sorted(new_untracked, reverse=True):
        target = (ROOT / relative).resolve()
        if ROOT not in target.parents or not target.is_file():
            continue
        target.unlink()
        parent = target.parent
        while parent != ROOT and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    for relative in previous_untracked:
        backup = backup_dir / relative
        if backup.is_file():
            destination = ROOT / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, destination)


def make_improvement_brief(path: pathlib.Path, iteration: int, baseline: Evaluation,
                           config: dict[str, Any]) -> None:
    failures = [item for item in baseline.checks if not item.passed]
    policy = config.get("policy", {})
    lines = [
        "# ASTA Loop Agent 개선 작업",
        "",
        f"반복 회차: {iteration}",
        f"현재 점수: {baseline.score}/{baseline.max_score}",
        "",
        "## 목표",
        "",
        "ASTA의 정확성, SQL 결과 동등성, 실측 성능 판정, 보고서 일관성을 개선한다.",
        "필수 검증을 모두 통과시키고 기존 통과 검증을 회귀시키지 않는다.",
        "",
        "## 실패 검증",
        "",
    ]
    if failures:
        lines.extend(f"- {item.name}: `{item.log_path}` (exit={item.returncode})" for item in failures)
    else:
        lines.append("- 실패 검증 없음. 낮은 가중치 검증이나 ASTA 품질을 한 가지 측정 가능한 방식으로 개선한다.")
    lines.extend([
        "",
        "## 변경 정책",
        "",
        f"- 허용 경로: {', '.join(policy.get('allowed_paths', []))}",
        "- 운영 DB DDL, 배포, credential 변경, git commit/push를 수행하지 않는다.",
        "- 한 회차에는 원인이 명확한 작은 변경 하나만 수행한다.",
        "- 변경 후 검증은 loop agent가 실행하므로 여기서는 코드를 수정하고 필요한 테스트만 추가한다.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def render_command(parts: list[str], brief: pathlib.Path, iteration_dir: pathlib.Path) -> list[str]:
    values = {"brief": str(brief), "iteration_dir": str(iteration_dir), "root": str(ROOT)}
    return [part.format(**values) for part in parts]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="asta-loop.yaml")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()

    config = load_config((ROOT / args.config).resolve())
    policy = config.get("policy", {})
    initial_paths = workspace_paths()
    if initial_paths and bool(policy.get("require_clean_worktree", True)):
        raise SystemExit("작업 트리가 깨끗하지 않습니다: " + ", ".join(sorted(initial_paths)))

    run_root = ROOT / str(config.get("report_dir", "reports/asta_loop"))
    run_dir = run_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    baseline = evaluate(config, run_dir, "baseline")
    summary: dict[str, Any] = {"started_at": utc_now(), "baseline": evaluation_to_dict(baseline), "iterations": []}

    target = float(policy.get("target_score", baseline.max_score))
    max_iterations = args.max_iterations if args.max_iterations is not None else int(policy.get("max_iterations", 3))
    improve_command = config.get("improve_command")
    if args.evaluate_only or not improve_command or baseline.score >= target:
        summary.update({"completed_at": utc_now(), "final": evaluation_to_dict(baseline),
                        "stop_reason": "evaluate_only" if args.evaluate_only or not improve_command else "target_reached"})
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ASTA score: {baseline.score}/{baseline.max_score}; report={run_dir}")
        return 0 if baseline.required_passed else 1

    allowed = list(policy.get("allowed_paths", ["app", "db", "static", "tests", "tools", "docs"]))
    min_gain = float(policy.get("min_score_gain", 0.01))
    current = baseline
    for iteration in range(1, max_iterations + 1):
        iteration_dir = run_dir / f"iteration_{iteration:02d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        brief = iteration_dir / "improvement_brief.md"
        make_improvement_brief(brief, iteration, current, config)
        before_untracked = {p for p in workspace_paths() if not is_tracked(p)}
        before_patch = iteration_dir / "before.patch"
        before_backup = iteration_dir / "before_untracked"
        capture_patch(before_patch)
        backup_untracked(before_untracked, before_backup)
        before_fingerprint = workspace_fingerprint()
        command = render_command(list(improve_command), brief, iteration_dir)
        rc, elapsed = run_command(command, ROOT, int(policy.get("improve_timeout_sec", 1800)), iteration_dir / "improver.log")
        paths = changed_paths()
        new_untracked = {p for p in paths if p not in before_untracked and not is_tracked(p)}
        patch_path = iteration_dir / "candidate.patch"
        capture_patch(patch_path)
        has_new_changes = workspace_fingerprint() != before_fingerprint
        permitted, denied = allowed_changes(paths, allowed)
        candidate = evaluate(config, iteration_dir, "candidate") if rc == 0 and has_new_changes and permitted else None
        accepted = bool(candidate and candidate.required_passed and candidate.score >= current.score + min_gain)
        reason = "accepted" if accepted else (
            "improver_failed" if rc else "no_changes" if not has_new_changes else "disallowed_paths" if denied
            else "required_check_failed" if candidate and not candidate.required_passed else "score_not_improved"
        )
        record = {"iteration": iteration, "improver_returncode": rc, "improver_elapsed_sec": elapsed,
                  "changed_paths": sorted(paths), "denied_paths": denied, "accepted": accepted, "reason": reason,
                  "evaluation": evaluation_to_dict(candidate) if candidate else None}
        summary["iterations"].append(record)
        if accepted:
            current = candidate  # type: ignore[assignment]
        else:
            rollback_changes(patch_path, before_patch, before_untracked, before_backup, new_untracked)
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if current.score >= target:
            break

    summary.update({"completed_at": utc_now(), "final": evaluation_to_dict(current),
                    "stop_reason": "target_reached" if current.score >= target else "iteration_limit"})
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ASTA score: {current.score}/{current.max_score}; report={run_dir}")
    return 0 if current.required_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
