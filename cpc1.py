#!/usr/bin/env python3
"""Deterministic vertical slice for the CPC-1 specification.

This program is intentionally a fixture, not an empirical benchmark. It
implements the contract in 题目分析报告.md on nine provenance-backed, synthetic
cases: three clear actions, three missing-evidence asks, and three unsafe
rejections. It produces auditable certificates and raises on any invalid one.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


ACTION_BY_TASK = {
    "entity_resolution": "merge",
    "normalization": "apply_transform",
    "metric_mapping": "map_metric",
}
CRITICAL_FIELD_BY_TASK = {
    "entity_resolution": "verified_identifier",
    "normalization": "unit_confirmed",
    "metric_mapping": "denominator_confirmed",
}
TAU_NEAR = 0.50
MAX_DIFFERING_FIELDS = 1


@dataclass(frozen=True)
class Record:
    case_id: str
    task_type: str
    candidate_action: str
    outcome: str
    negative_type: str | None
    fields: dict[str, Any]
    near_miss_group: str
    provenance: str


def fixture_archive() -> list[Record]:
    records: list[Record] = []
    for index, (task, action) in enumerate(ACTION_BY_TASK.items(), start=1):
        critical = CRITICAL_FIELD_BY_TASK[task]
        common = {"task": task, "source_quality": "trusted"}
        records.extend(
            [
                Record(f"archive-{index}-safe", task, action, "safe", None,
                       {**common, critical: True}, f"archive-{index}-safe", "fixture:v1"),
                Record(f"archive-{index}-unsafe", task, action, "unsafe", "unsafe_boundary",
                       {**common, critical: False}, f"archive-{index}-unsafe", "fixture:v1"),
                Record(f"archive-{index}-missing", task, action, "insufficient_evidence", "evidence_boundary",
                       {**common, critical: None}, f"archive-{index}-missing", "fixture:v1"),
            ]
        )
    return records


def fixture_cases() -> list[Record]:
    cases: list[Record] = []
    for index, (task, action) in enumerate(ACTION_BY_TASK.items(), start=1):
        critical = CRITICAL_FIELD_BY_TASK[task]
        common = {"task": task, "source_quality": "trusted"}
        cases.extend(
            [
                Record(f"q{index}-safe", task, action, "safe", None,
                       {**common, critical: True}, f"test-{index}-safe", "fixture:v1"),
                Record(f"q{index}-ask", task, action, "insufficient_evidence", None,
                       {**common, critical: None}, f"test-{index}-ask", "fixture:v1"),
                Record(f"q{index}-reject", task, action, "unsafe", None,
                       {**common, critical: False}, f"test-{index}-reject", "fixture:v1"),
            ]
        )
    return cases


def similarity(case: Record, precedent: Record) -> float:
    if case.task_type != precedent.task_type or case.candidate_action != precedent.candidate_action:
        return -1.0
    keys = sorted(set(case.fields) | set(precedent.fields))
    return sum(case.fields.get(k) == precedent.fields.get(k) for k in keys) / len(keys)


def safe_literals(positive: Record, negative: Record) -> list[tuple[str, Any]]:
    return [(key, positive.fields[key]) for key in sorted(positive.fields)
            if positive.fields.get(key) != negative.fields.get(key)]


def select_boundary(case: Record, archive: list[Record]) -> tuple[Record, Record, list[tuple[str, Any]]]:
    candidates = [p for p in archive if p.task_type == case.task_type and p.candidate_action == case.candidate_action]
    positives = [p for p in candidates if p.outcome == "safe"]
    unsafe = [p for p in candidates if p.negative_type == "unsafe_boundary"]
    if not positives or not unsafe:
        raise ValueError("no admissible unsafe-boundary pair")
    positive = max(positives, key=lambda p: (similarity(case, p), p.case_id))
    negative = max(unsafe, key=lambda p: (similarity(case, p), p.case_id))
    literals = safe_literals(positive, negative)
    if not literals:
        raise ValueError("no distinguishing safe-value literal")
    # Fixture has one decisive literal. Enumeration preserves the report's
    # minimum-cardinality rule and is extensible once larger data exists.
    boundary = min((list(combo) for width in range(1, len(literals) + 1)
                    for combo in itertools.combinations(literals, width)), key=lambda s: (len(s), s))
    return positive, negative, boundary


def status(observed: Any, required: Any) -> str:
    if observed is None:
        return "unknown"
    return "matched" if observed == required else "mismatched"


def decide(case: Record, archive: list[Record]) -> dict[str, Any]:
    positive, negative, boundary = select_boundary(case, archive)
    literals = []
    for field, required in boundary:
        observed = case.fields.get(field)
        literals.append({"field": field, "required_safe_value": required, "observed_value": observed,
                         "status": status(observed, required), "provenance": case.provenance})
    states = {literal["status"] for literal in literals}
    if states == {"matched"}:
        decision, reason = f"ACT({case.candidate_action})", None
    elif "unknown" in states:
        decision, reason = f"ASK({next(l['field'] for l in literals if l['status'] == 'unknown')})", "missing_literal"
    else:
        decision, reason = "REJECT(mismatched_literal)", "mismatched_literal"
    certificate = {
        "case_id": case.case_id,
        "decision": decision,
        "positive_precedent": positive.case_id,
        "negative_precedent": negative.case_id,
        "negative_type": negative.negative_type,
        "literals": literals,
        "reason": reason,
    }
    certificate["validator_pass"] = validate_certificate(certificate, archive, case)
    if not certificate["validator_pass"]:
        raise AssertionError(f"invalid certificate for {case.case_id}")
    return certificate


def validate_certificate(certificate: dict[str, Any], archive: list[Record], case: Record) -> bool:
    """Validate a certificate against its bound case and archive.

    Case binding is mandatory: validating only a fluent-looking pair of
    precedents would permit a cross-task certificate to authorize an action.
    """
    lookup = {record.case_id: record for record in archive}
    positive = lookup.get(certificate["positive_precedent"])
    negative = lookup.get(certificate["negative_precedent"])
    literals = certificate.get("literals", [])
    if certificate.get("case_id") != case.case_id or not positive or not negative or not literals:
        return False
    if (positive.outcome != "safe" or negative.negative_type != "unsafe_boundary" or
            certificate.get("negative_type") != negative.negative_type):
        return False
    if (case.task_type != positive.task_type or case.task_type != negative.task_type or
            case.candidate_action != positive.candidate_action or case.candidate_action != negative.candidate_action):
        return False
    if case.near_miss_group in {positive.near_miss_group, negative.near_miss_group}:
        return False
    differences = safe_literals(positive, negative)
    if (similarity(case, positive) < TAU_NEAR or similarity(case, negative) < TAU_NEAR or
            len(differences) > MAX_DIFFERING_FIELDS):
        return False
    permitted_literals = set(differences)
    for literal in literals:
        if (literal["field"], literal["required_safe_value"]) not in permitted_literals:
            return False
        if literal["required_safe_value"] != positive.fields.get(literal["field"]):
            return False
        observed = case.fields.get(literal["field"])
        if literal.get("observed_value") != observed or literal.get("status") != status(observed, literal["required_safe_value"]):
            return False
        if literal.get("provenance") != case.provenance:
            return False
        if literal["status"] not in {"matched", "mismatched", "unknown", "contradicted"}:
            return False
    decision = certificate["decision"]
    states = {literal["status"] for literal in literals}
    # Bind authorization to the case's declared action, not just an arbitrary
    # syntactically valid ACT(...) string.
    return ((decision == f"ACT({case.candidate_action})" and states == {"matched"}) or
            (decision.startswith("ASK(") and "unknown" in states) or
            (decision.startswith("REJECT(") and bool(states & {"mismatched", "contradicted"})))


def expected_decision(case: Record) -> str:
    return {"safe": "ACT", "insufficient_evidence": "ASK", "unsafe": "REJECT"}[case.outcome]


def run(project_root: Path) -> list[dict[str, Any]]:
    archive, cases = fixture_archive(), fixture_cases()
    decisions = [decide(case, archive) for case in cases]
    for case, certificate in zip(cases, decisions, strict=True):
        if not certificate["decision"].startswith(expected_decision(case)):
            raise AssertionError(f"decision mismatch: {case.case_id}")
    results = project_root / "results"
    results.mkdir(exist_ok=True)
    with (results / "p1_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "decision", "positive_precedent", "negative_precedent", "negative_type", "validator_pass"])
        writer.writeheader()
        writer.writerows({key: decision[key] for key in writer.fieldnames} for decision in decisions)
    (results / "p1_smoke.json").write_text(json.dumps({"fixture_version": "v1", "case_count": len(cases), "certificates": decisions}, indent=2) + "\n", encoding="utf-8")
    return decisions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent)
    arguments = parser.parse_args()
    output = run(arguments.project_root)
    print(json.dumps({"status": "PASS", "cases": len(output), "validator_passes": sum(d["validator_pass"] for d in output)}))
