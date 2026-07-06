#!/usr/bin/env python3
"""ASTA evidence 실험을 집계하고 사람이 승인할 변경 제안서를 만드는 read-only agent."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import math
import re
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
DEFAULT_OLTP_MAX_ELAPSED_US = 3_000_000
DEFAULT_OLTP_MAX_ELAPSED_INCREASE_US = 300_000
XPLAN_METRIC_SOURCE = "DBMS_XPLAN_ALLSTATS_LAST"


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


def _xplan_number(value: str) -> int | None:
    """Oracle XPLAN의 K/M/G 축약 숫자를 정수로 변환한다."""
    text = value.strip().replace(",", "")
    if not text:
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMG]?)", text, re.IGNORECASE)
    if not match:
        return None
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "G": 1_000_000_000}[match.group(2).upper()]
    return int(float(match.group(1)) * multiplier)


def _xplan_time_us(value: str) -> int | None:
    """ALLSTATS A-Time(HH:MM:SS.ff)를 microseconds로 변환한다."""
    text = value.strip()
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})(?:\.(\d+))?", text)
    if not match:
        return None
    hours, minutes, seconds = (int(match.group(index)) for index in range(1, 4))
    fraction = (match.group(4) or "")[:6].ljust(6, "0")
    return ((hours * 60 + minutes) * 60 + seconds) * 1_000_000 + int(fraction or 0)


def parse_xplan_operations(plan_text: str) -> list[dict[str, Any]]:
    """DBMS_XPLAN ALLSTATS 표를 metric과 부모-자식 관계가 있는 node 목록으로 만든다."""
    header: list[str] | None = None
    parsed: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    required = {"Id", "Operation", "Starts", "E-Rows", "A-Rows", "A-Time", "Buffers"}
    for line in plan_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("|")[1:-1]
        stripped = [cell.strip() for cell in cells]
        if required.issubset(set(stripped)):
            header = stripped
            continue
        if not header or len(cells) != len(header):
            continue
        values = dict(zip(header, cells))
        id_match = re.search(r"\d+", values.get("Id", ""))
        if not id_match:
            continue
        operation_cell = values.get("Operation", "")
        leading_spaces = len(operation_cell) - len(operation_cell.lstrip(" "))
        depth = max(0, leading_spaces - 1)
        while stack and stack[-1]["depth"] >= depth:
            stack.pop()
        parent_id = stack[-1]["id"] if stack else None
        node = {
            "id": int(id_match.group()),
            "depth": depth,
            "parent_id": parent_id,
            "child_ids": [],
            "operation": operation_cell.strip(),
            "object_name": values.get("Name", "").strip() or None,
            "starts": _xplan_number(values.get("Starts", "")),
            "estimated_rows": _xplan_number(values.get("E-Rows", "")),
            "actual_rows": _xplan_number(values.get("A-Rows", "")),
            "a_time_us": _xplan_time_us(values.get("A-Time", "")),
            "buffers": _xplan_number(values.get("Buffers", "")),
        }
        if stack:
            stack[-1]["child_ids"].append(node["id"])
        parsed.append(node)
        stack.append(node)
    return parsed


def rank_xplan_bottlenecks(plan_text: str, limit: int = 10) -> dict[str, Any]:
    """실측 metric과 tree 경계를 이용해 결정론적인 지배 병목 후보를 반환한다."""
    nodes = parse_xplan_operations(plan_text)
    if not nodes:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reason_code": "XPLAN_ALLSTATS_ROWS_NOT_FOUND",
            "metric_source": XPLAN_METRIC_SOURCE,
            "rankings": [],
            "dominant": None,
        }

    by_id = {node["id"]: node for node in nodes}
    total_buffers = max((node["buffers"] or 0 for node in nodes), default=0)
    total_time = max((node["a_time_us"] or 0 for node in nodes), default=0)

    def subtree_max(node_id: int, field: str) -> int:
        node = by_id[node_id]
        return max(
            [node[field] or 0]
            + [subtree_max(child_id, field) for child_id in node["child_ids"] if child_id in by_id]
        )

    candidates: list[tuple[tuple[float, int, int, int, int], dict[str, Any]]] = []
    for node in nodes:
        starts = node["starts"] or 0
        buffers = node["buffers"] or 0
        a_time_us = node["a_time_us"] or 0
        actual_rows = node["actual_rows"] or 0
        estimated_rows = node["estimated_rows"] or 0
        parent = by_id.get(node["parent_id"])
        parent_starts = (parent or {}).get("starts") or 0
        repeated = starts > 1
        repeated_root = repeated and parent_starts <= 1
        buffer_share = buffers / total_buffers if total_buffers else 0.0
        time_share = a_time_us / total_time if total_time else 0.0
        subtree_rows = subtree_max(node["id"], "actual_rows")
        cardinality_ratio = actual_rows / estimated_rows if estimated_rows > 0 else None
        row_amplification = subtree_rows >= 100_000 and subtree_rows >= max(actual_rows, estimated_rows, 1) * 10

        reason_codes: list[str] = []
        if repeated:
            reason_codes.append("REPEATED_WORK")
        if repeated_root:
            reason_codes.append("REPEATED_SUBTREE_ROOT")
        if buffer_share >= 0.20:
            reason_codes.append("DOMINANT_BUFFERS")
        if time_share >= 0.20:
            reason_codes.append("DOMINANT_A_TIME")
        if cardinality_ratio is not None and cardinality_ratio >= 10:
            reason_codes.append("CARDINALITY_UNDERESTIMATE")
        if row_amplification:
            reason_codes.append("SUBTREE_ROW_AMPLIFICATION")

        repeat_score = min(math.log10(max(starts, 1)) / 6.0, 1.0) if repeated else 0.0
        repeated_root_bonus = 0.45 if repeated_root and max(buffer_share, time_share) >= 0.05 else (
            0.05 if repeated_root else 0.0
        )
        score = (
            buffer_share * 0.40
            + time_share * 0.35
            + repeat_score * 0.20
            + repeated_root_bonus
            + (0.10 if row_amplification else 0.0)
        )
        evidence = {
            "starts": node["starts"],
            "estimated_rows": node["estimated_rows"],
            "actual_rows": node["actual_rows"],
            "a_time_us": node["a_time_us"],
            "buffers": node["buffers"],
            "buffer_share_pct": round(buffer_share * 100, 4),
            "a_time_share_pct": round(time_share * 100, 4),
            "cardinality_ratio": round(cardinality_ratio, 4) if cardinality_ratio is not None else None,
            "subtree_max_actual_rows": subtree_rows,
        }
        ranked = {
            "rank": 0,
            "node_id": node["id"],
            "parent_id": node["parent_id"],
            "child_ids": node["child_ids"],
            "operation": node["operation"],
            "object_name": node["object_name"],
            "score": round(score, 6),
            "reason_codes": reason_codes or ["MEASURED_OPERATION"],
            "evidence": evidence,
        }
        sort_key = (-score, -buffers, -a_time_us, -starts, node["id"])
        candidates.append((sort_key, ranked))

    rankings = [item for _, item in sorted(candidates, key=lambda pair: pair[0])[:max(1, limit)]]
    for rank, item in enumerate(rankings, start=1):
        item["rank"] = rank
    return {
        "status": "COMPLETED",
        "metric_source": XPLAN_METRIC_SOURCE,
        "node_count": len(nodes),
        "rankings": rankings,
        "dominant": rankings[0],
    }


_SQL_RESERVED_WORDS = {
    "AND", "AS", "BY", "CONNECT", "CROSS", "ELSE", "END", "EXISTS", "FROM", "FULL",
    "GROUP", "HAVING", "INNER", "INTERSECT", "JOIN", "LEFT", "MINUS", "NOT", "ON", "OR",
    "ORDER", "OUTER", "RIGHT", "SELECT", "START", "THEN", "UNION", "WHEN", "WHERE", "WITH",
}


def _sql_tokens(sql_text: str) -> list[dict[str, Any]]:
    """문자열/comment를 제외하고 위치를 보존하는 작은 Oracle SQL tokenizer."""
    tokens: list[dict[str, Any]] = []
    index = 0
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
            close = sql_text.find("*/", index + 2)
            index = length if close < 0 else close + 2
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
            start = index
            index += 1
            value: list[str] = []
            while index < length:
                if sql_text[index] == '"':
                    if index + 1 < length and sql_text[index + 1] == '"':
                        value.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                value.append(sql_text[index])
                index += 1
            text = "".join(value)
            tokens.append({"text": text, "upper": text.upper(), "kind": "QUOTED_IDENTIFIER", "start": start, "end": index})
            continue
        if char.isalpha() or char in "_$#_":
            start = index
            index += 1
            while index < length and (sql_text[index].isalnum() or sql_text[index] in "_$#_"):
                index += 1
            text = sql_text[start:index]
            tokens.append({"text": text, "upper": text.upper(), "kind": "WORD", "start": start, "end": index})
            continue
        if char.isdigit():
            start = index
            index += 1
            while index < length and (sql_text[index].isdigit() or sql_text[index] == "."):
                index += 1
            text = sql_text[start:index]
            tokens.append({"text": text, "upper": text.upper(), "kind": "NUMBER", "start": start, "end": index})
            continue
        tokens.append({"text": char, "upper": char, "kind": "SYMBOL", "start": index, "end": index + 1})
        index += 1
    return tokens


def _is_keyword(token: dict[str, Any], keyword: str) -> bool:
    return token["kind"] == "WORD" and token["upper"] == keyword


def _is_identifier(token: dict[str, Any]) -> bool:
    return token["kind"] in {"WORD", "QUOTED_IDENTIFIER"}


def _parenthesis_pairs(tokens: list[dict[str, Any]]) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for index, token in enumerate(tokens):
        if token["text"] == "(":
            stack.append(index)
        elif token["text"] == ")" and stack:
            opening = stack.pop()
            pairs[opening] = index
    return pairs


def _cte_scopes(tokens: list[dict[str, Any]], pairs: dict[int, int]) -> list[dict[str, Any]]:
    if not tokens or not _is_keyword(tokens[0], "WITH"):
        return []
    scopes: list[dict[str, Any]] = []
    index = 1
    while index < len(tokens) and _is_identifier(tokens[index]):
        name = tokens[index]["text"]
        index += 1
        if index < len(tokens) and tokens[index]["text"] == "(":
            index = pairs.get(index, index) + 1
        if index >= len(tokens) or not _is_keyword(tokens[index], "AS"):
            break
        index += 1
        if index >= len(tokens) or tokens[index]["text"] != "(" or index not in pairs:
            break
        opening = index
        closing = pairs[opening]
        scopes.append({
            "name": name.upper(),
            "opening_index": opening,
            "closing_index": closing,
            "start_offset": tokens[opening]["end"],
            "end_offset": tokens[closing]["start"],
        })
        index = closing + 1
        if index >= len(tokens) or tokens[index]["text"] != ",":
            break
        index += 1
    return scopes


def _smallest_containing_scope(scopes: list[dict[str, Any]], token_index: int) -> dict[str, Any] | None:
    containing = [
        scope for scope in scopes
        if scope["opening_index"] < token_index < scope["closing_index"]
    ]
    return min(containing, key=lambda item: item["closing_index"] - item["opening_index"]) if containing else None


def _subquery_scopes(
    tokens: list[dict[str, Any]], pairs: dict[int, int], ctes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    for opening, closing in sorted(pairs.items()):
        if opening + 1 >= closing or not (
            _is_keyword(tokens[opening + 1], "SELECT") or _is_keyword(tokens[opening + 1], "WITH")
        ):
            continue
        construct = "SCALAR_SUBQUERY"
        source_index = opening
        previous = opening - 1
        if previous >= 0 and _is_keyword(tokens[previous], "EXISTS"):
            construct = "EXISTS"
            source_index = previous
            if previous > 0 and _is_keyword(tokens[previous - 1], "NOT"):
                construct = "NOT EXISTS"
                source_index = previous - 1
        elif previous >= 0 and (
            _is_keyword(tokens[previous], "FROM") or _is_keyword(tokens[previous], "JOIN")
        ):
            construct = "INLINE_VIEW"
        cte = _smallest_containing_scope(ctes, opening)
        scopes.append({
            "opening_index": opening,
            "closing_index": closing,
            "source_index": source_index,
            "construct": construct,
            "query_block": cte["name"] if cte else "MAIN",
            "cte_name": cte["name"] if cte else None,
        })
    return scopes


def _object_references(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens) - 1:
        if not (_is_keyword(tokens[index], "FROM") or _is_keyword(tokens[index], "JOIN")):
            index += 1
            continue
        cursor = index + 1
        if cursor >= len(tokens) or not _is_identifier(tokens[cursor]):
            index += 1
            continue
        parts = [tokens[cursor]["text"]]
        first_index = cursor
        cursor += 1
        while cursor + 1 < len(tokens) and tokens[cursor]["text"] == "." and _is_identifier(tokens[cursor + 1]):
            parts.append(tokens[cursor + 1]["text"])
            cursor += 2
        alias = None
        if cursor < len(tokens) and _is_keyword(tokens[cursor], "AS"):
            cursor += 1
            if cursor < len(tokens) and _is_identifier(tokens[cursor]):
                alias = tokens[cursor]["text"]
        elif cursor < len(tokens) and _is_identifier(tokens[cursor]) and (
            tokens[cursor]["kind"] == "QUOTED_IDENTIFIER" or tokens[cursor]["upper"] not in _SQL_RESERVED_WORDS
        ):
            alias = tokens[cursor]["text"]
        references.append({
            "object": ".".join(part.upper() for part in parts),
            "base_object": parts[-1].upper(),
            "schema": parts[-2].upper() if len(parts) > 1 else None,
            "alias": alias.upper() if alias else None,
            "token_index": first_index,
            "start_offset": tokens[first_index]["start"],
            "end_offset": tokens[cursor - 1]["end"] if cursor > first_index else tokens[first_index]["end"],
        })
        index = max(index + 1, cursor)
    return references


def _predicate_evidence(plan_text: str, node_id: int) -> dict[str, Any]:
    lines = plan_text.splitlines()
    collected: list[str] = []
    active = False
    for line in lines:
        match = re.match(r"^\s*(\d+)\s*-\s*(.*)$", line)
        if match:
            active = int(match.group(1)) == node_id
            if active:
                collected.append(match.group(2).strip())
            continue
        if active:
            if not line.strip() or re.match(r"^[A-Za-z][A-Za-z ]+:?\s*$", line.strip()):
                break
            collected.append(line.strip())
    text = " ".join(part for part in collected if part)
    aliases = sorted({value.replace('""', '"').upper() for value in re.findall(r'"((?:[^"]|"")+)"\s*\.', text)})
    return {"text": text or None, "aliases": aliases}


def _line_column(sql_text: str, offset: int) -> tuple[int, int]:
    line = sql_text.count("\n", 0, offset) + 1
    previous_newline = sql_text.rfind("\n", 0, offset)
    return line, offset - previous_newline


def _source_span(sql_text: str, start_offset: int, end_offset: int) -> dict[str, int]:
    start_line, start_column = _line_column(sql_text, start_offset)
    end_line, end_column = _line_column(sql_text, end_offset)
    return {
        "start_offset": start_offset,
        "end_offset": end_offset,
        "start_line": start_line,
        "start_column": start_column,
        "end_line": end_line,
        "end_column": end_column,
    }


def _blocked_plan_link(
    dominant: dict[str, Any] | None, reason_code: str, candidate_count: int = 0,
    confidence: float = 0.0, extra_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "dominant_plan_node": dominant,
        "query_block": None,
        "cte_name": None,
        "construct": None,
        "referenced_object": dominant.get("object_name") if dominant else None,
        "referenced_alias": None,
        "source_span": None,
        "confidence": confidence,
        "reason_codes": [reason_code, *(extra_reasons or [])],
        "candidate_count": candidate_count,
        "rewrite_allowed": False,
    }


def link_dominant_plan_node_to_sql(sql_text: str, plan_text: str) -> dict[str, Any]:
    """단계 1 dominant node를 유일한 SQL construct에 연결하되 불확실하면 rewrite를 차단한다."""
    ranking = rank_xplan_bottlenecks(plan_text)
    dominant = ranking.get("dominant")
    if ranking.get("status") != "COMPLETED" or not dominant:
        return _blocked_plan_link(dominant, "DOMINANT_PLAN_NODE_UNAVAILABLE")
    target_object = str(dominant.get("object_name") or "").upper()
    if not target_object:
        return _blocked_plan_link(dominant, "PLAN_OBJECT_EVIDENCE_MISSING")

    tokens = _sql_tokens(sql_text)
    pairs = _parenthesis_pairs(tokens)
    ctes = _cte_scopes(tokens, pairs)
    subqueries = _subquery_scopes(tokens, pairs, ctes)
    references = _object_references(tokens)
    matching = [reference for reference in references if reference["base_object"] == target_object]
    if not matching:
        return _blocked_plan_link(dominant, "PLAN_OBJECT_NOT_FOUND_IN_SQL")
    if len(matching) != 1:
        return _blocked_plan_link(dominant, "AMBIGUOUS_SQL_FRAGMENT", candidate_count=len(matching))

    reference = matching[0]
    scope = _smallest_containing_scope(subqueries, reference["token_index"])
    if not scope:
        return _blocked_plan_link(dominant, "SQL_CONSTRUCT_NOT_IDENTIFIED", candidate_count=1)

    scope_tokens = tokens[scope["opening_index"] + 1:scope["closing_index"]]
    alias_prefixes = {
        scope_tokens[index]["upper"]
        for index in range(len(scope_tokens) - 2)
        if _is_identifier(scope_tokens[index]) and scope_tokens[index + 1]["text"] == "."
        and _is_identifier(scope_tokens[index + 2])
    }
    cte = next((item for item in ctes if item["name"] == scope["cte_name"]), None)
    outer_aliases = {
        item["alias"] for item in references
        if item["alias"] and cte
        and cte["opening_index"] < item["token_index"] < cte["closing_index"]
        and not (scope["opening_index"] < item["token_index"] < scope["closing_index"])
    }
    correlated = sorted(alias_prefixes.intersection(outer_aliases))
    predicate = _predicate_evidence(plan_text, dominant["node_id"])
    sql_aliases = {value for value in [reference["alias"], *correlated] if value}

    reason_codes = ["DOMINANT_PLAN_NODE_SELECTED", "UNIQUE_OBJECT_STRUCTURE_MATCH"]
    confidence = 0.85
    rewrite_allowed = True
    if scope["cte_name"]:
        reason_codes.append("CTE_SCOPE_MATCH")
    if correlated:
        reason_codes.append("CORRELATED_SUBQUERY")
    if predicate["aliases"]:
        if reference["alias"] in predicate["aliases"] and predicate["aliases"] and set(predicate["aliases"]).intersection(sql_aliases):
            confidence = 0.99
            reason_codes.append("XPLAN_PREDICATE_ALIAS_MATCH")
        else:
            confidence = 0.4
            rewrite_allowed = False
            reason_codes.append("XPLAN_ALIAS_MISMATCH")
    else:
        reason_codes.append("XPLAN_PREDICATE_UNAVAILABLE")

    start_offset = tokens[scope["source_index"]]["start"]
    end_offset = tokens[scope["closing_index"]]["end"]
    consumer_construct = {
        "NOT EXISTS": "CTE_FILTER" if scope["cte_name"] else "QUERY_FILTER",
        "EXISTS": "CTE_FILTER" if scope["cte_name"] else "QUERY_FILTER",
        "INLINE_VIEW": "FROM_SOURCE",
        "SCALAR_SUBQUERY": "SELECT_EXPRESSION",
    }[scope["construct"]]
    return {
        "status": "LINKED" if rewrite_allowed else "BLOCKED",
        "dominant_plan_node": dominant,
        "query_block": scope["query_block"],
        "cte_name": scope["cte_name"],
        "construct": scope["construct"],
        "referenced_object": reference["object"],
        "referenced_alias": reference["alias"],
        "source_span": _source_span(sql_text, start_offset, end_offset),
        "immediate_consumer": {"construct": consumer_construct, "query_block": scope["query_block"]},
        "correlated_outer_aliases": correlated,
        "predicate_evidence": predicate,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "candidate_count": 1,
        "rewrite_allowed": rewrite_allowed,
    }


def classify_failure(row: dict[str, Any]) -> str:
    """Classify one candidate attempt into the customer-facing failure taxonomy."""
    optimizer_reason = str(row.get("verdict_reason") or row.get("optimizer_intent_verdict") or "").upper()
    if optimizer_reason == "OPTIMIZER_INTENT_NOT_MET":
        return "OPTIMIZER_INTENT_NOT_MET"
    if optimizer_reason == "INSUFFICIENT_PLAN_EVIDENCE":
        return "INSUFFICIENT_PLAN_EVIDENCE"
    equivalence_reason = str(row.get("equivalence_verdict") or "").upper()
    if equivalence_reason == "EQUIVALENCE_BUDGET_EXCEEDED":
        return "EQUIVALENCE_BUDGET_EXCEEDED"
    if equivalence_reason in {
        "FULL_RESULT_EVIDENCE_REQUIRED", "RESULT_EVIDENCE_TRUNCATED",
        "RESULT_DIGEST_MODE_MISMATCH", "RESULT_DIGEST_ALGORITHM_MISMATCH",
        "RESULT_EVIDENCE_INCOMPLETE", "RESULT_EVIDENCE_UNSTABLE",
    }:
        return "INSUFFICIENT_EQUIVALENCE_EVIDENCE"
    if equivalence_reason in {
        "RESULT_METADATA_MISMATCH", "RESULT_ROW_COUNT_MISMATCH", "RESULT_DIGEST_MISMATCH",
    }:
        return "SEMANTIC_EQUIVALENCE_FAILURE"
    bind_reason = str(row.get("bind_stability_reason") or row.get("reason_code") or "").upper()
    if bind_reason in {
        "BIND_COVERAGE_INSUFFICIENT", "BIND_METADATA_MISMATCH", "BIND_METADATA_INCOMPLETE",
        "BIND_NULL_SEMANTICS_INVALID", "BEFORE_AFTER_BIND_SET_MISMATCH",
        "RAW_BIND_VALUE_FORBIDDEN", "BIND_FINGERPRINT_MISSING",
    }:
        return "BIND_COVERAGE_FAILURE"
    if bind_reason in {
        "PLAN_FLIP_DETECTED", "PLAN_SHAPE_UNSTABLE", "STARTS_SUBTREE_UNSTABLE",
        "BEFORE_PLAN_UNSTABLE", "UNEXPECTED_PLAN_FAMILY", "INSUFFICIENT_BIND_PLAN_EVIDENCE",
        "INSUFFICIENT_BEFORE_BIND_PLAN_EVIDENCE", "BIND_OPTIMIZER_INTENT_NOT_VERIFIED",
    }:
        return "BIND_PLAN_INSTABILITY"
    if bind_reason == "BIND_EQUIVALENCE_NOT_VERIFIED" or bind_reason == "BIND_CASE_EQUIVALENCE_FAILED":
        return "SEMANTIC_EQUIVALENCE_FAILURE"
    if bind_reason in {
        "BIND_CASE_LATENCY_REGRESSION", "BIND_CASE_PERFORMANCE_REGRESSION",
        "BIND_CASE_MEASUREMENT_UNSTABLE",
    }:
        return "BIND_PERFORMANCE_REGRESSION"
    if bind_reason == "BIND_EXECUTION_BUDGET_EXCEEDED":
        return "EXECUTION_BUDGET_EXCEEDED"
    measurement_reason = str(row.get("measurement_reason_code") or row.get("reason_code") or "").upper()
    if measurement_reason in {
        "TOTAL_RUN_BUDGET_EXCEEDED", "TOTAL_TIME_BUDGET_EXCEEDED",
        "CANDIDATE_RUN_BUDGET_EXCEEDED", "CANDIDATE_TIME_BUDGET_EXCEEDED",
        "CANDIDATE_BUDGET_EXCEEDED", "BUDGET_EVIDENCE_INCOMPLETE",
    }:
        return "EXECUTION_BUDGET_EXCEEDED"
    if measurement_reason == "RUN_TIMEOUT":
        return "EXECUTION_TIMEOUT"
    if measurement_reason == "RUNAWAY_EXECUTION_DETECTED":
        return "RUNAWAY_EXECUTION"
    if measurement_reason == "CANDIDATE_TERMINAL_FAILURE":
        return "CANDIDATE_TERMINAL_FAILURE"
    if measurement_reason == "MEASUREMENT_INCOMPLETE":
        return "MEASUREMENT_INCOMPLETE"
    if measurement_reason == "MEASUREMENT_NOISE_TOO_HIGH":
        return "MEASUREMENT_NOISE"
    error = str(row.get("candidate_error") or row.get("execution_error") or "")
    if "ORA-" in error.upper():
        return "ORACLE_SYNTAX_OR_EXECUTION_ERROR"
    if not row.get("candidate_generated"):
        return "CANDIDATE_GENERATION_FAILURE"
    semantic = row.get("semantic_equivalent") is True
    legacy_shape_claim = row.get("equivalent") is True and "semantic_equivalent" not in row
    if (row.get("reported_equivalent") is True or legacy_shape_claim) and not semantic:
        return "REPORT_DECISION_ERROR"
    if not semantic:
        return "SEMANTIC_EQUIVALENCE_FAILURE"
    if row.get("measurement_noisy") is True:
        return "MEASUREMENT_NOISE"
    if row.get("latency_guard_passed") is False:
        return "PERFORMANCE_NOT_IMPROVED"
    if not isinstance(row.get("primary_reduction_pct"), (int, float)) or row["primary_reduction_pct"] < 5:
        return "PERFORMANCE_NOT_IMPROVED"
    return "IMPROVED"


def normalize_result(row: dict[str, Any], workloads: dict[str, str], cycle_id: str) -> dict[str, Any]:
    comparison = row.get("comparison") or {}
    sample_id = str(row.get("sample_id") or "")
    workload = str(workloads.get(sample_id, row.get("workload") or "OLTP")).upper()
    reported_equivalent = comparison.get("reported_equivalent") is True or comparison.get("runtime_shape_equivalent") is True or (
        comparison.get("row_count_matches") is True and comparison.get("output_rows_match") is True
    )
    equivalent = comparison.get("semantic_equivalent") is True
    buffer_pct = comparison.get("buffer_gets_reduction_pct")
    if not isinstance(buffer_pct, (int, float)):
        buffer_pct = pct_reduction(comparison.get("before_buffer_gets"), comparison.get("after_buffer_gets"))
    elapsed_pct = pct_reduction(comparison.get("before_elapsed_time_us"), comparison.get("after_elapsed_time_us"))
    primary_pct = elapsed_pct if workload == "BATCH" else buffer_pct
    before_elapsed = comparison.get("before_elapsed_time_us")
    after_elapsed = comparison.get("after_elapsed_time_us")
    if workload == "OLTP":
        latency_guard_passed = (
            isinstance(after_elapsed, (int, float))
            and after_elapsed <= DEFAULT_OLTP_MAX_ELAPSED_US
            and (
                not isinstance(before_elapsed, (int, float))
                or after_elapsed - before_elapsed <= DEFAULT_OLTP_MAX_ELAPSED_INCREASE_US
            )
        )
    else:
        latency_guard_passed = True
    normalized = {
        "cycle_id": cycle_id,
        "sample_id": sample_id,
        "variant_id": str(row.get("mode") or row.get("variant_id") or ""),
        "workload": workload,
        "candidate_generated": row.get("candidate_generated") is True,
        "candidate_error": row.get("candidate_error"),
        "equivalent": equivalent,
        "semantic_equivalent": equivalent,
        "reported_equivalent": reported_equivalent,
        "equivalence_strength": comparison.get("equivalence_strength") or ("SHAPE_ONLY" if reported_equivalent else "NONE"),
        "measurement_noisy": comparison.get("measurement_noisy") is True,
        "latency_guard_passed": comparison.get("latency_guard_passed", latency_guard_passed) is True,
        "optimizer_intent_status": comparison.get("optimizer_intent_status"),
        "optimizer_intent_verdict": comparison.get("optimizer_intent_verdict") or comparison.get("verdict_reason"),
        "optimizer_intent_reason_codes": comparison.get("optimizer_intent_reason_codes") or [],
        "equivalence_status": comparison.get("equivalence_status"),
        "equivalence_verdict": comparison.get("equivalence_verdict"),
        "equivalence_evidence": comparison.get("equivalence_evidence"),
        "result_digest_scope": comparison.get("result_digest_scope"),
        "result_digest_mode": comparison.get("result_digest_mode"),
        "bind_stability_status": comparison.get("status") if (
            comparison.get("bind_results") is not None
            or comparison.get("all_representative_binds_passed") is not None
        ) else None,
        "bind_stability_reason": comparison.get("reason_code") if (
            comparison.get("bind_results") is not None
            or comparison.get("all_representative_binds_passed") is not None
        ) else None,
        "all_representative_binds_passed": comparison.get("all_representative_binds_passed"),
        "bind_case_count": comparison.get("bind_case_count"),
        "successful_bind_count": comparison.get("successful_bind_count"),
        "failed_bind_case_id": comparison.get("failed_bind_case_id"),
        "worst_bind_elapsed_us": comparison.get("worst_after_elapsed_us"),
        "bind_results": comparison.get("bind_results"),
        "candidate_evaluation_allowed": comparison.get("candidate_evaluation_allowed"),
        "digest_evaluated": comparison.get("digest_evaluated"),
        "performance_evaluated": comparison.get("performance_evaluated"),
        "verdict_reason": comparison.get("verdict_reason"),
        "measurement_status": comparison.get("status"),
        "measurement_reason_code": comparison.get("reason_code"),
        "processed_run_count": comparison.get("processed_run_count"),
        "budget": comparison.get("budget"),
        "before_measurement_summary": comparison.get("before_summary"),
        "after_measurement_summary": comparison.get("after_summary"),
        "buffer_reduction_pct": buffer_pct,
        "elapsed_reduction_pct": elapsed_pct,
        "primary_reduction_pct": primary_pct,
        "prompt_chars": row.get("prompt_chars"),
        "llm_call_count": row.get("llm_call_count"),
        "execution_order": row.get("execution_order"),
        "before_buffer_gets": comparison.get("before_buffer_gets", row.get("baseline_buffer_gets")),
        "after_buffer_gets": comparison.get("after_buffer_gets"),
        "before_elapsed_time_us": comparison.get("before_elapsed_time_us", row.get("baseline_elapsed_time_us")),
        "after_elapsed_time_us": comparison.get("after_elapsed_time_us"),
    }
    normalized["failure_category"] = classify_failure(normalized)
    return normalized


def row_improved(row: dict[str, Any], quality: dict[str, Any]) -> bool:
    if not row.get("candidate_generated") or not row.get("equivalent"):
        return False
    if row.get("workload") == "BATCH":
        value = row.get("elapsed_reduction_pct")
        threshold = float(quality.get("min_batch_elapsed_reduction_pct", 5.0))
    else:
        value = row.get("buffer_reduction_pct")
        threshold = float(quality.get("min_oltp_buffer_reduction_pct", 5.0))
        before_elapsed = row.get("before_elapsed_time_us")
        after_elapsed = row.get("after_elapsed_time_us")
        max_elapsed = float(quality.get("max_oltp_elapsed_time_us", DEFAULT_OLTP_MAX_ELAPSED_US))
        max_increase = float(quality.get("max_oltp_elapsed_increase_us", DEFAULT_OLTP_MAX_ELAPSED_INCREASE_US))
        if not isinstance(after_elapsed, (int, float)) or after_elapsed > max_elapsed:
            return False
        if isinstance(before_elapsed, (int, float)) and after_elapsed - before_elapsed > max_increase:
            return False
    return isinstance(value, (int, float)) and value >= threshold


def apply_workload_overrides(
    rows: list[dict[str, Any]], workloads: dict[str, str], quality: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reinterpret historical measurements with corrected canonical workload metadata."""
    corrected: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        workload = str(workloads.get(str(row.get("sample_id") or ""), row.get("workload") or "OLTP")).upper()
        row["workload"] = workload
        row["primary_reduction_pct"] = (
            row.get("elapsed_reduction_pct") if workload == "BATCH" else row.get("buffer_reduction_pct")
        )
        if workload == "OLTP":
            before_elapsed = row.get("before_elapsed_time_us")
            after_elapsed = row.get("after_elapsed_time_us")
            max_elapsed = float(quality.get("max_oltp_elapsed_time_us", DEFAULT_OLTP_MAX_ELAPSED_US))
            max_increase = float(quality.get("max_oltp_elapsed_increase_us", DEFAULT_OLTP_MAX_ELAPSED_INCREASE_US))
            row["latency_guard_passed"] = (
                isinstance(after_elapsed, (int, float))
                and after_elapsed <= max_elapsed
                and (
                    not isinstance(before_elapsed, (int, float))
                    or after_elapsed - before_elapsed <= max_increase
                )
            )
        row["failure_category"] = classify_failure(row)
        corrected.append(row)
    return corrected


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
    customer_workload = str((config.get("sample_workloads") or {}).get(customer_id, "OLTP")).upper()
    decision = "DEPLOY_REVIEW_READY" if chosen else "EXPERIMENT_MORE"
    lines = [
        "# ASTA 결과 품질 실험 보고서",
        "",
        f"- 생성 시각(UTC): `{utc_now()}`",
        f"- 회차: `{cycle_id}`",
        f"- 판정: **{decision}**",
        f"- 필수 고객 SQL: `{customer_id}`",
        f"- 필수 고객 Workload: `{customer_workload}`",
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
        f"성공률 `{float(quality.get('customer_min_success_rate', 0.67)) * 100:.0f}%` 이상. " + (
            f"OLTP 1차 지표 buffer gets `{quality.get('min_oltp_buffer_reduction_pct', 5)}%` 이상 개선, 결과 digest 동등, "
            f"elapsed `{int(quality.get('max_oltp_elapsed_time_us', DEFAULT_OLTP_MAX_ELAPSED_US)) / 1000000:g}초` 이하, "
            f"기존 대비 증가 `{int(quality.get('max_oltp_elapsed_increase_us', DEFAULT_OLTP_MAX_ELAPSED_INCREASE_US)) / 1000:g}ms` 이하가 모두 필요합니다."
            if customer_workload == "OLTP" else
            f"BATCH elapsed `{quality.get('min_batch_elapsed_reduction_pct', 5)}%` 이상 개선과 결과 digest 동등이 모두 필요합니다."
        ),
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
    customer_rows = [row for row in rows if row.get("sample_id") == customer_id]
    failure_names = [
        "CANDIDATE_GENERATION_FAILURE",
        "ORACLE_SYNTAX_OR_EXECUTION_ERROR",
        "INSUFFICIENT_PLAN_EVIDENCE",
        "OPTIMIZER_INTENT_NOT_MET",
        "INSUFFICIENT_EQUIVALENCE_EVIDENCE",
        "EQUIVALENCE_BUDGET_EXCEEDED",
        "BIND_COVERAGE_FAILURE",
        "BIND_PLAN_INSTABILITY",
        "BIND_PERFORMANCE_REGRESSION",
        "EXECUTION_BUDGET_EXCEEDED",
        "EXECUTION_TIMEOUT",
        "RUNAWAY_EXECUTION",
        "CANDIDATE_TERMINAL_FAILURE",
        "MEASUREMENT_INCOMPLETE",
        "SEMANTIC_EQUIVALENCE_FAILURE",
        "PERFORMANCE_NOT_IMPROVED",
        "MEASUREMENT_NOISE",
        "REPORT_DECISION_ERROR",
        "IMPROVED",
    ]
    failure_counts = {name: 0 for name in failure_names}
    for row in customer_rows:
        failure_counts[classify_failure(row)] += 1
    lines.extend([
        "",
        "## 고객 SQL 실패 분류",
        "",
        "| 분류 | 횟수 |",
        "|---|---:|",
        *[f"| {name} | {failure_counts[name]} |" for name in failure_names],
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
        history = apply_workload_overrides(history, workloads, config["quality"])
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
