#!/usr/bin/env python3
"""ASTA evidence 실험을 집계하고 사람이 승인할 변경 제안서를 만드는 read-only agent."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: pathlib.Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("설정 최상위 값은 object여야 합니다")
    quality = config.get("quality") or {}
    if not quality.get("customer_sample_id"):
        raise ValueError("quality.customer_sample_id가 필요합니다")
    variants = config.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("variants가 하나 이상 필요합니다")
    for variant in variants:
        if not isinstance(variant, dict) or not variant.get("id") or not variant.get("evidence"):
            raise ValueError("각 variant에는 id와 evidence가 필요합니다")
    return config


def run_experiment(config: dict[str, Any], cycle_dir: pathlib.Path) -> pathlib.Path:
    experiment = config.get("experiment") or {}
    command = experiment.get("command")
    summary_file = experiment.get("summary_file")
    if not command or not summary_file:
        raise ValueError("experiment.command와 experiment.summary_file이 필요합니다")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("experiment.command는 문자열 배열이어야 합니다")
    log_path = cycle_dir / "experiment.log"
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(experiment.get("timeout_sec", 3300)),
            env={**os.environ, "PYTHONUNBUFFERED": "1",
                 "ASTA_EXPERIMENT_ROTATION": str(int(time.time() // 3600))},
            check=False,
        )
        output = completed.stdout or ""
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        output = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        output += "\nEXPERIMENT_TIMEOUT\n"
        returncode = 124
    log_path.write_text(output, encoding="utf-8")
    (cycle_dir / "experiment_run.json").write_text(
        json.dumps({"command": command, "returncode": returncode,
                    "elapsed_sec": round(time.monotonic() - started, 3)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if returncode:
        raise RuntimeError(f"실험 실패(exit={returncode}): {log_path}")
    path = (ROOT / str(summary_file)).resolve()
    if not path.is_file():
        raise RuntimeError(f"실험 summary가 없습니다: {path}")
    return path


def pct_reduction(before: Any, after: Any) -> float | None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)) or before <= 0:
        return None
    return round((before - after) * 100.0 / before, 4)


def normalize_result(row: dict[str, Any], workloads: dict[str, str], cycle_id: str) -> dict[str, Any]:
    comparison = row.get("comparison") or {}
    sample_id = str(row.get("sample_id") or "")
    workload = str(workloads.get(sample_id, row.get("workload") or "OLTP")).upper()
    equivalent = comparison.get("runtime_shape_equivalent") is True or (
        comparison.get("row_count_matches") is True and comparison.get("output_rows_match") is True
    )
    buffer_pct = comparison.get("buffer_gets_reduction_pct")
    if not isinstance(buffer_pct, (int, float)):
        buffer_pct = pct_reduction(comparison.get("before_buffer_gets"), comparison.get("after_buffer_gets"))
    elapsed_pct = pct_reduction(comparison.get("before_elapsed_time_us"), comparison.get("after_elapsed_time_us"))
    return {
        "cycle_id": cycle_id,
        "sample_id": sample_id,
        "variant_id": str(row.get("mode") or row.get("variant_id") or ""),
        "workload": workload,
        "candidate_generated": row.get("candidate_generated") is True,
        "candidate_error": row.get("candidate_error"),
        "equivalent": equivalent,
        "buffer_reduction_pct": buffer_pct,
        "elapsed_reduction_pct": elapsed_pct,
        "prompt_chars": row.get("prompt_chars"),
        "llm_call_count": row.get("llm_call_count"),
        "execution_order": row.get("execution_order"),
        "before_buffer_gets": comparison.get("before_buffer_gets"),
        "after_buffer_gets": comparison.get("after_buffer_gets"),
        "before_elapsed_time_us": comparison.get("before_elapsed_time_us"),
        "after_elapsed_time_us": comparison.get("after_elapsed_time_us"),
    }


def row_improved(row: dict[str, Any], quality: dict[str, Any]) -> bool:
    if not row.get("candidate_generated") or not row.get("equivalent"):
        return False
    if row.get("workload") == "BATCH":
        value = row.get("elapsed_reduction_pct")
        threshold = float(quality.get("min_batch_elapsed_reduction_pct", 5.0))
    else:
        value = row.get("buffer_reduction_pct")
        threshold = float(quality.get("min_oltp_buffer_reduction_pct", 5.0))
    return isinstance(value, (int, float)) and value >= threshold


@dataclass
class VariantStats:
    variant_id: str
    evidence: str
    customer_runs: int
    customer_successes: int
    customer_success_rate: float
    customer_median_primary_reduction_pct: float | None
    all_runs: int
    all_success_rate: float
    equivalence_rate: float
    median_prompt_chars: float | None
    customer_gate_passed: bool


def median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 4) if values else None


def calculate_stats(rows: list[dict[str, Any]], config: dict[str, Any]) -> list[VariantStats]:
    quality = config["quality"]
    customer_id = str(quality["customer_sample_id"])
    min_runs = int(quality.get("customer_min_runs", 3))
    min_success_rate = float(quality.get("customer_min_success_rate", 0.67))
    result: list[VariantStats] = []
    for variant in config["variants"]:
        variant_id = str(variant["id"])
        selected = [row for row in rows if row.get("variant_id") == variant_id]
        customer = [row for row in selected if row.get("sample_id") == customer_id]
        customer_successes = sum(row_improved(row, quality) for row in customer)
        success_count = sum(row_improved(row, quality) for row in selected)
        equivalent_count = sum(bool(row.get("equivalent")) for row in selected)
        primary = [
            float(row["elapsed_reduction_pct"] if row.get("workload") == "BATCH" else row["buffer_reduction_pct"])
            for row in customer
            if isinstance(row.get("elapsed_reduction_pct") if row.get("workload") == "BATCH" else row.get("buffer_reduction_pct"), (int, float))
            and row_improved(row, quality)
        ]
        prompts = [float(row["prompt_chars"]) for row in selected if isinstance(row.get("prompt_chars"), (int, float))]
        customer_rate = customer_successes / len(customer) if customer else 0.0
        result.append(VariantStats(
            variant_id=variant_id,
            evidence=str(variant["evidence"]),
            customer_runs=len(customer),
            customer_successes=customer_successes,
            customer_success_rate=round(customer_rate, 4),
            customer_median_primary_reduction_pct=median(primary),
            all_runs=len(selected),
            all_success_rate=round(success_count / len(selected), 4) if selected else 0.0,
            equivalence_rate=round(equivalent_count / len(selected), 4) if selected else 0.0,
            median_prompt_chars=median(prompts),
            customer_gate_passed=len(customer) >= min_runs and customer_rate >= min_success_rate,
        ))
    return result


def choose_variant(stats: list[VariantStats]) -> VariantStats | None:
    eligible = [item for item in stats if item.customer_gate_passed]
    if not eligible:
        return None
    # variants 순서가 evidence 비용 순서다. 고객 gate를 통과한 가장 싼 단계를 기본값으로 선택한다.
    return eligible[0]


def diagnose_next_action(rows: list[dict[str, Any]], stats: list[VariantStats], config: dict[str, Any]) -> str:
    customer_id = str(config["quality"]["customer_sample_id"])
    customer_rows = [row for row in rows if row.get("sample_id") == customer_id]
    if not customer_rows:
        return "고객 SQL 실험 결과가 없습니다. 다음 회차에서도 고객 SQL을 최우선으로 실행해야 합니다."
    if not any(row.get("candidate_generated") for row in customer_rows):
        return "후보 SQL 생성이 병목입니다. SQL+XPLAN 2단계 진단/생성 프롬프트와 모델 fallback을 우선 비교하십시오."
    if not any(row.get("equivalent") for row in customer_rows):
        return "결과 동등성이 병목입니다. 컬럼/NULL/집계/정렬 계약과 object metadata를 추가하고 의미 보존 검증 지시를 강화하십시오."
    if not any(item.customer_gate_passed for item in stats):
        return "동등한 후보는 생성되지만 성능 개선이 반복 재현되지 않습니다. XPLAN operation, 실제 metrics, Advisor를 순서대로 추가해 병목 목표를 좁히십시오."
    return "고객 SQL gate를 통과한 최소 evidence 단계를 기본값으로 하고, 후보 없음·비동등·미개선일 때만 다음 단계로 escalation 하십시오."


def report_markdown(stats: list[VariantStats], rows: list[dict[str, Any]], config: dict[str, Any], cycle_id: str) -> str:
    chosen = choose_variant(stats)
    quality = config["quality"]
    customer_id = quality["customer_sample_id"]
    decision = "DEPLOY_REVIEW_READY" if chosen else "EXPERIMENT_MORE"
    lines = [
        "# ASTA 결과 품질 실험 보고서",
        "",
        f"- 생성 시각(UTC): `{utc_now()}`",
        f"- 회차: `{cycle_id}`",
        f"- 판정: **{decision}**",
        f"- 필수 고객 SQL: `{customer_id}`",
        "- 자동 적용: **없음** — 이 문서는 사람의 승인과 별도 배포를 위한 제안서입니다.",
        "",
        "## 필수 고객 SQL Gate",
        "",
    ]
    if chosen:
        lines.append(f"통과: `{chosen.variant_id}` ({chosen.evidence})가 최소 evidence 통과 단계입니다.")
    else:
        lines.append("미통과: 아직 어떤 evidence 단계도 반복 실행 기준을 충족하지 못했습니다. 배포하면 안 됩니다.")
    lines.extend([
        "",
        f"기준: 최근 `{quality.get('history_cycles', 5)}`회 중 고객 SQL 최소 `{quality.get('customer_min_runs', 3)}`회, "
        f"성공률 `{float(quality.get('customer_min_success_rate', 0.67)) * 100:.0f}%` 이상. "
        f"BATCH elapsed `{quality.get('min_batch_elapsed_reduction_pct', 5)}%` 또는 OLTP buffer gets "
        f"`{quality.get('min_oltp_buffer_reduction_pct', 5)}%` 이상 개선과 결과 동등성이 모두 필요합니다.",
        "",
        "## Evidence 단계별 계산",
        "",
        "| 단계 | LLM 입력 | 고객 성공/실행 | 고객 성공률 | 고객 중앙 개선률 | 전체 성공률 | 동등성률 | Prompt 중앙값 | Gate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for item in stats:
        lines.append(
            f"| {item.variant_id} | {item.evidence} | {item.customer_successes}/{item.customer_runs} | "
            f"{item.customer_success_rate * 100:.1f}% | {value_text(item.customer_median_primary_reduction_pct, '%')} | "
            f"{item.all_success_rate * 100:.1f}% | {item.equivalence_rate * 100:.1f}% | "
            f"{value_text(item.median_prompt_chars)} | {'PASS' if item.customer_gate_passed else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## 권장 운영 순서",
        "",
        "1. `SQL + focused XPLAN`으로 진단 JSON을 만든다.",
        "2. 같은 단계에서 SQL 전용 응답으로 후보를 생성하고 안전성/구조 변경 여부를 검사한다.",
        "3. 후보 없음이면 실제 실행 metrics와 workload 목표를 추가한다.",
        "4. 비동등이면 object/column/index metadata와 의미 보존 제약을 추가한다.",
        "5. 동등하지만 미개선이면 Advisor와 핵심 XPLAN operation을 추가한다.",
        "6. 마지막 단계에서만 검증된 `IMPROVED` Vector 사례를 추가한다.",
        "7. 각 후보는 Source DB에서 Before/After를 반복 측정하고 deterministic comparison으로 채택한다.",
        "",
        "## 이번 계산에 따른 다음 조치",
        "",
        diagnose_next_action(rows, stats, config),
        "",
        "## 승인 후 변경 대상",
        "",
        "- `db/adb/asta_llm_pkg.sql`: evidence escalation 단계 및 prompt 구성",
        "- `db/adb/asta_pkg.sql`: 실패 사유별 다음 단계 선택과 반복 측정",
        "- `tools/run_asta_prompt_abc_adb.py`: 실험 variant와 반복 횟수",
        "- 관련 계약 테스트와 운영 문서",
        "",
        "이 파일은 변경 방향만 계산합니다. SQL/PLSQL 파일 수정, compile, ORDS 배포, 운영 DB 변경은 수행하지 않습니다.",
        "",
    ])
    return "\n".join(lines)


def value_text(value: float | None, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.2f}{suffix}"


def read_history(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_history(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent_history(rows: list[dict[str, Any]], cycles: int) -> list[dict[str, Any]]:
    cycle_ids: list[str] = []
    for row in reversed(rows):
        cycle_id = str(row.get("cycle_id"))
        if cycle_id not in cycle_ids:
            cycle_ids.append(cycle_id)
        if len(cycle_ids) >= cycles:
            break
    selected = set(cycle_ids)
    return [row for row in rows if str(row.get("cycle_id")) in selected]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="asta-quality-agent.yaml")
    parser.add_argument("--summary", help="DB 실험을 실행하지 않고 기존 summary.json을 집계")
    args = parser.parse_args()
    config = load_config((ROOT / args.config).resolve())
    report_root = ROOT / str(config.get("report_dir", "reports/asta_quality_agent"))
    cycle_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cycle_dir = report_root / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    try:
        summary_path = pathlib.Path(args.summary).resolve() if args.summary else run_experiment(config, cycle_dir)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        raw_rows = summary.get("results") or []
        workloads = config.get("sample_workloads") or {}
        normalized = [normalize_result(row, workloads, cycle_id) for row in raw_rows]
        if not normalized:
            raise RuntimeError("summary에 results가 없습니다")
        (cycle_dir / "normalized_results.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        history_path = report_root / "history.jsonl"
        write_history(history_path, normalized)
        history = recent_history(read_history(history_path), int(config["quality"].get("history_cycles", 5)))
        stats = calculate_stats(history, config)
        report = report_markdown(stats, history, config, cycle_id)
        report_path = cycle_dir / "review.md"
        report_path.write_text(report, encoding="utf-8")
        (report_root / "latest.md").write_text(report, encoding="utf-8")
        decision = "DEPLOY_REVIEW_READY" if choose_variant(stats) else "EXPERIMENT_MORE"
        selected = choose_variant(stats)
        decision_payload = {
            "status": "COMPLETED",
            "decision": decision,
            "cycle_id": cycle_id,
            "customer_sample_id": config["quality"]["customer_sample_id"],
            "customer_gate_passed": selected is not None,
            "selected_minimum_evidence_variant": selected.variant_id if selected else None,
            "next_action": diagnose_next_action(history, stats, config),
            "automatic_code_or_db_changes": False,
            "variants": [asdict(item) for item in stats],
        }
        (cycle_dir / "decision.json").write_text(
            json.dumps(decision_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (report_root / "latest.json").write_text(
            json.dumps(decision_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"status": "COMPLETED", "decision": decision, "report": str(report_path)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        error = {"status": "FAILED", "error_type": type(exc).__name__, "message": str(exc), "cycle_id": cycle_id}
        (cycle_dir / "error.json").write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
