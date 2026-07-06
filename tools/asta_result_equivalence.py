#!/usr/bin/env python3
"""ASTA 단계 6 전체 결과 동등성 증거를 생성하고 검증하는 순수 함수 모듈."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any


ORDERED_MODE = "ORDERED_ROWS"
MULTISET_MODE = "UNORDERED_MULTISET"
FULL_SCOPE = "FULL_RESULT"
ALGORITHM = "SHA256_TYPED_ROW_STREAM_V2"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sql_tokens(sql_text: str) -> list[tuple[str, int]]:
    """문자열/comment를 건너뛰고 token과 괄호 depth를 반환한다."""
    tokens: list[tuple[str, int]] = []
    index = 0
    depth = 0
    length = len(sql_text)
    while index < length:
        char = sql_text[index]
        if char.isspace():
            index += 1
            continue
        if sql_text.startswith("--", index):
            newline = sql_text.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if sql_text.startswith("/*", index):
            closing = sql_text.find("*/", index + 2)
            index = length if closing < 0 else closing + 2
            continue
        if char == "'":
            index += 1
            while index < length:
                if sql_text[index] == "'":
                    if index + 1 < length and sql_text[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == '"':
            index += 1
            while index < length:
                if sql_text[index] == '"':
                    if index + 1 < length and sql_text[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "(":
            tokens.append((char, depth))
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            tokens.append((char, depth))
            index += 1
            continue
        if char.isalpha() or char in "_$#":
            end = index + 1
            while end < length and (sql_text[end].isalnum() or sql_text[end] in "_$#"):
                end += 1
            tokens.append((sql_text[index:end].upper(), depth))
            index = end
            continue
        tokens.append((char, depth))
        index += 1
    return tokens


def detect_result_order_mode(sql_text: str) -> str:
    """최종 query의 top-level ORDER BY만 결과 순서 의미로 인정한다."""
    tokens = _sql_tokens(sql_text)
    for index, (token, depth) in enumerate(tokens[:-1]):
        next_token, next_depth = tokens[index + 1]
        if token == "ORDER" and next_token == "BY" and depth == 0 and next_depth == 0:
            return ORDERED_MODE
    return MULTISET_MODE


def _metadata_document(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not columns:
        raise ValueError("RESULT_METADATA_REQUIRED")
    normalized: list[dict[str, Any]] = []
    for position, column in enumerate(columns, start=1):
        oracle_type = str(column.get("oracle_type") or "").upper()
        name = str(column.get("name") or "")
        if not name or not oracle_type:
            raise ValueError("RESULT_METADATA_INCOMPLETE")
        normalized.append({
            "position": position,
            "name": name,
            "oracle_type": oracle_type,
            "precision": column.get("precision"),
            "scale": column.get("scale"),
            "max_length": column.get("max_length"),
            "charset_id": column.get("charset_id"),
            "charset_form": column.get("charset_form"),
        })
    return normalized


def _decimal_text(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("INVALID_NUMBER_VALUE") from exc
    if not number.is_finite():
        raise ValueError("NON_FINITE_NUMBER_UNSUPPORTED")
    if number == 0:
        return "0"
    text = format(number.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical_cell(value: Any, column: dict[str, Any]) -> bytes:
    if value is None:
        return b"N;"
    oracle_type = column["oracle_type"]
    if oracle_type in {"NUMBER", "DECIMAL", "NUMERIC", "INTEGER"}:
        payload = _decimal_text(value).encode("ascii")
        tag = b"D"
    elif oracle_type in {"BINARY_FLOAT", "BINARY_DOUBLE", "FLOAT"}:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("NON_FINITE_FLOAT_UNSUPPORTED")
        payload = number.hex().encode("ascii")
        tag = b"F"
    elif oracle_type == "DATE":
        if not isinstance(value, (dt.date, dt.datetime)):
            raise ValueError("TEMPORAL_VALUE_REQUIRES_TYPED_INPUT")
        payload = value.isoformat().encode("utf-8")
        tag = b"A"
    elif oracle_type.startswith("TIMESTAMP"):
        if not isinstance(value, dt.datetime):
            raise ValueError("TEMPORAL_VALUE_REQUIRES_TYPED_INPUT")
        payload = value.isoformat().encode("utf-8")
        tag = b"T"
    elif oracle_type in {"RAW", "LONG RAW"}:
        payload = bytes(value).hex().encode("ascii") if isinstance(value, (bytes, bytearray)) else str(value).upper().encode("ascii")
        tag = b"R"
    elif oracle_type in {"CHAR", "NCHAR", "VARCHAR2", "NVARCHAR2", "CLOB", "NCLOB", "LONG"}:
        payload = str(value).encode("utf-8")
        tag = b"S"
    else:
        raise ValueError(f"UNSUPPORTED_RESULT_DATATYPE:{oracle_type}")
    return tag + str(len(payload)).encode("ascii") + b":" + payload + b";"


def _canonical_row(row: list[Any] | tuple[Any, ...], columns: list[dict[str, Any]]) -> bytes:
    if len(row) != len(columns):
        raise ValueError("RESULT_COLUMN_COUNT_MISMATCH")
    cells = [_canonical_cell(value, columns[index]) for index, value in enumerate(row)]
    return b"ROW:" + str(len(cells)).encode("ascii") + b":" + b"".join(cells)


def build_full_result_evidence(
    sql_text: str,
    columns: list[dict[str, Any]],
    rows: list[list[Any] | tuple[Any, ...]],
    *,
    max_rows: int | None = None,
    max_bytes: int | None = None,
    chunk_rows: int = 1000,
) -> dict[str, Any]:
    """전체 typed rows를 ordered stream 또는 duplicate-preserving multiset으로 digest한다."""
    metadata = _metadata_document(columns)
    metadata_bytes = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    metadata_digest = _sha256(metadata_bytes)
    mode = detect_result_order_mode(sql_text)
    if max_rows is not None and len(rows) > max_rows:
        return {
            "result_digest_status": "BLOCKED",
            "result_digest_error": "EQUIVALENCE_BUDGET_EXCEEDED",
            "result_digest": None,
            "result_digest_scope": FULL_SCOPE,
            "result_digest_mode": mode,
            "result_digest_algorithm": ALGORITHM,
            "result_metadata_digest": metadata_digest,
            "result_total_rows": len(rows),
            "result_digest_rows": 0,
            "result_canonical_bytes": None,
            "result_evidence_complete": False,
            "result_truncated": False,
        }
    try:
        canonical_rows = [_canonical_row(row, metadata) for row in rows]
    except ValueError as exc:
        return {
            "result_digest_status": "BLOCKED",
            "result_digest_error": str(exc),
            "result_digest": None,
            "result_digest_scope": FULL_SCOPE,
            "result_digest_mode": mode,
            "result_digest_algorithm": ALGORITHM,
            "result_metadata_digest": metadata_digest,
            "result_total_rows": len(rows),
            "result_digest_rows": 0,
            "result_canonical_bytes": None,
            "result_chunk_count": 0,
            "result_chunks_complete": False,
            "result_evidence_complete": False,
            "result_truncated": False,
        }
    canonical_bytes = sum(len(row) for row in canonical_rows)
    if max_bytes is not None and canonical_bytes > max_bytes:
        return {
            "result_digest_status": "BLOCKED",
            "result_digest_error": "EQUIVALENCE_BUDGET_EXCEEDED",
            "result_digest": None,
            "result_digest_scope": FULL_SCOPE,
            "result_digest_mode": mode,
            "result_digest_algorithm": ALGORITHM,
            "result_metadata_digest": metadata_digest,
            "result_total_rows": len(rows),
            "result_digest_rows": 0,
            "result_canonical_bytes": canonical_bytes,
            "result_chunk_count": 0,
            "result_chunks_complete": False,
            "result_evidence_complete": False,
            "result_truncated": False,
        }
    if mode == MULTISET_MODE:
        # 각 row hash를 정렬하되 같은 hash를 모두 유지해 duplicate multiplicity를 보존한다.
        stream_rows = [digest.encode("ascii") for digest in sorted(_sha256(row) for row in canonical_rows)]
    else:
        stream_rows = canonical_rows
    chunk_size = max(1, int(chunk_rows))
    chunks = [stream_rows[index:index + chunk_size] for index in range(0, len(stream_rows), chunk_size)]
    chunk_digests = [
        _sha256(b"".join(str(len(row)).encode("ascii") + b":" + row for row in chunk))
        for chunk in chunks
    ]
    root_hash = hashlib.sha256()
    root_hash.update(
        (ALGORITHM + "|" + mode + "|" + metadata_digest + "|rows=" + str(len(rows)) + "|").encode("ascii")
    )
    for row in stream_rows:
        root_hash.update(str(len(row)).encode("ascii") + b":" + row)
    root = root_hash.hexdigest()
    return {
        "result_digest_status": "COMPLETED",
        "result_digest_error": None,
        "result_digest": root,
        "result_digest_scope": FULL_SCOPE,
        "result_digest_mode": mode,
        "result_digest_algorithm": ALGORITHM,
        "result_metadata_digest": metadata_digest,
        "result_total_rows": len(rows),
        "result_digest_rows": len(rows),
        "result_canonical_bytes": canonical_bytes,
        "result_chunk_count": len(chunks),
        "result_chunks_complete": True,
        "result_evidence_complete": True,
        "result_truncated": False,
    }


def _equivalence_result(
    status: str,
    reason_code: str,
    mode: str,
    *,
    semantic_equivalent: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "semantic_equivalent": semantic_equivalent,
        "equivalence_strength": "FULL_RESULT_DIGEST" if semantic_equivalent else "NONE",
        "result_digest_scope": FULL_SCOPE,
        "result_digest_mode": mode,
        "allow_performance_measurement": semantic_equivalent,
        "evidence": evidence or {},
    }


def _validate_evidence(run: dict[str, Any], expected_mode: str) -> str | None:
    if run.get("result_digest_scope") != FULL_SCOPE:
        return "FULL_RESULT_EVIDENCE_REQUIRED"
    if run.get("result_truncated") is True:
        return "RESULT_EVIDENCE_TRUNCATED"
    if str(run.get("result_digest_error") or "").upper() == "EQUIVALENCE_BUDGET_EXCEEDED":
        return "EQUIVALENCE_BUDGET_EXCEEDED"
    if run.get("result_digest_mode") != expected_mode:
        return "RESULT_DIGEST_MODE_MISMATCH"
    if (
        str(run.get("status") or "").upper() != "COMPLETED"
        or str(run.get("result_digest_status") or "").upper() != "COMPLETED"
        or run.get("result_evidence_complete") is not True
        or run.get("result_chunks_complete") is not True
        or not run.get("result_digest")
        or not run.get("result_metadata_digest")
        or run.get("result_digest_algorithm") != ALGORITHM
        or not isinstance(run.get("result_total_rows"), int)
        or run.get("result_total_rows") < 0
        or run.get("result_digest_rows") != run.get("result_total_rows")
    ):
        return "RESULT_EVIDENCE_INCOMPLETE"
    return None


def _stable_signature(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run.get("result_digest"),
        run.get("result_total_rows"),
        run.get("result_metadata_digest"),
        run.get("result_digest_mode"),
        run.get("result_digest_algorithm"),
    )


def verify_result_equivalence(
    sql_text: str,
    before_runs: list[dict[str, Any]],
    after_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """완전한 전체 결과 증거만 SQL의 ordered/multiset 의미에 따라 비교한다."""
    mode = detect_result_order_mode(sql_text)
    if not before_runs or not after_runs:
        return _equivalence_result("BLOCKED", "RESULT_EVIDENCE_INCOMPLETE", mode)
    for side, runs in (("BEFORE", before_runs), ("AFTER", after_runs)):
        for index, run in enumerate(runs):
            reason = _validate_evidence(run, mode)
            if reason:
                return _equivalence_result(
                    "BLOCKED", reason, mode,
                    evidence={"side": side, "run_index": index},
                )
        if len({_stable_signature(run) for run in runs}) != 1:
            return _equivalence_result(
                "BLOCKED", "RESULT_EVIDENCE_UNSTABLE", mode,
                evidence={"side": side, "run_count": len(runs)},
            )
    before = before_runs[0]
    after = after_runs[0]
    comparison_evidence = {
        "before_total_rows": before["result_total_rows"],
        "after_total_rows": after["result_total_rows"],
        "before_metadata_digest": before["result_metadata_digest"],
        "after_metadata_digest": after["result_metadata_digest"],
        "before_result_digest": before["result_digest"],
        "after_result_digest": after["result_digest"],
    }
    if before["result_metadata_digest"] != after["result_metadata_digest"]:
        return _equivalence_result(
            "NON_EQUIVALENT", "RESULT_METADATA_MISMATCH", mode, evidence=comparison_evidence,
        )
    if before["result_total_rows"] != after["result_total_rows"]:
        return _equivalence_result(
            "NON_EQUIVALENT", "RESULT_ROW_COUNT_MISMATCH", mode, evidence=comparison_evidence,
        )
    if before["result_digest"] != after["result_digest"]:
        return _equivalence_result(
            "NON_EQUIVALENT", "RESULT_DIGEST_MISMATCH", mode, evidence=comparison_evidence,
        )
    return _equivalence_result(
        "VERIFIED", "RESULT_EQUIVALENCE_VERIFIED", mode,
        semantic_equivalent=True, evidence=comparison_evidence,
    )
