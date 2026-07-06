#!/usr/bin/env python3
"""검증된 ASTA 성공과 rejected 관측을 분리하는 Vector 학습 경계."""

from __future__ import annotations

import re
from typing import Any


EXPECTED_STAGE_STATUS = {
    "OPTIMIZER_INTENT": "VERIFIED",
    "FULL_RESULT_EQUIVALENCE": "VERIFIED",
    "BIND_PLAN_STABILITY": "VERIFIED",
    "EXECUTION_MEASUREMENT": "ACCEPTED",
    "FINAL_DECISION": "ACCEPTED",
}


def _valid_fingerprint(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")))


def _safe_identifier(value: Any, limit: int = 100) -> str | None:
    text = str(value or "")
    if not text or not re.fullmatch(r"[A-Za-z0-9_.:-]+", text):
        return None
    return text[:limit]


def _safe_error(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"'(?:''|[^'])*'", "'?'", text)
    text = re.sub(r"(:[A-Za-z][A-Za-z0-9_$#]*)\s*=\s*[^,\s)]+", r"\1=?", text)
    return text[:1000]


def _stage_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("stage") or ""): item
        for item in snapshot.get("stages") or []
        if isinstance(item, dict)
    }


def _positive_gates_complete(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("overall_status") != "ACCEPTED" or snapshot.get("terminal") is not True:
        return False
    if snapshot.get("evidence_level") != "FULL_RESULT_REPRESENTATIVE_BINDS_REPEATED":
        return False
    stages = _stage_map(snapshot)
    return all(
        stages.get(stage, {}).get("status") == expected
        for stage, expected in EXPECTED_STAGE_STATUS.items()
    ) and stages.get("FULL_RESULT_EQUIVALENCE", {}).get("evidence", {}).get("result_digest_scope") == "FULL_RESULT"


def _observed_metadata(observed: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    workload = str(observed.get("workload") or "").upper()
    if workload in {"OLTP", "BATCH"}:
        metadata["workload"] = workload
    strategy = _safe_identifier(observed.get("strategy_id"))
    if strategy:
        metadata["strategy_id"] = strategy
    for key in (
        "primary_reduction_pct", "buffer_reduction_pct", "median_elapsed_us",
        "noise_pct", "bind_case_count", "successful_bind_count",
    ):
        if isinstance(observed.get(key), (int, float)):
            metadata[key] = observed[key]
    return metadata


def classify_vector_learning(
    snapshot: dict[str, Any], observed: dict[str, Any],
) -> dict[str, Any]:
    """Positive search corpus와 rejected observation corpus를 절대 섞지 않는다."""
    fingerprint = observed.get("case_fingerprint")
    fingerprint_valid = _valid_fingerprint(fingerprint)
    gates_complete = _positive_gates_complete(snapshot)
    metadata = _observed_metadata(observed)
    stage_reasons = {
        stage: item.get("reason_code")
        for stage, item in _stage_map(snapshot).items()
        if stage in EXPECTED_STAGE_STATUS
    }
    if fingerprint_valid and gates_complete:
        positive = {
            "case_fingerprint": str(fingerprint).lower(),
            "reason_code": snapshot.get("reason_code"),
            "evidence_level": snapshot.get("evidence_level"),
            "gate_reasons": stage_reasons,
            **metadata,
        }
        return {
            "classification": "POSITIVE_VERIFIED",
            "positive_eligible": True,
            "positive_record": positive,
            "rejected_record": None,
        }
    if not fingerprint_valid:
        reason = "VECTOR_FINGERPRINT_INVALID"
    elif snapshot.get("overall_status") == "ACCEPTED":
        reason = "VECTOR_POSITIVE_GATE_INCOMPLETE"
    else:
        reason = str(snapshot.get("reason_code") or "VECTOR_WORKFLOW_NOT_ACCEPTED")
    rejected = {
        "case_fingerprint": str(fingerprint).lower() if fingerprint_valid else None,
        "reason_code": reason,
        "observed_reason_code": snapshot.get("reason_code"),
        "current_stage": snapshot.get("current_stage"),
        "overall_status": snapshot.get("overall_status"),
        "evidence_level": snapshot.get("evidence_level"),
        "gate_reasons": stage_reasons,
        "original_error": _safe_error(snapshot.get("original_error")),
        **metadata,
    }
    return {
        "classification": "REJECTED_OBSERVATION",
        "positive_eligible": False,
        "positive_record": None,
        "rejected_record": rejected,
    }
