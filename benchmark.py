#!/usr/bin/env python3
"""CPC-1 deterministic contract benchmark and figure generator.

This is deliberately *not* a claim about production-model performance.  The
fixtures are designed, provenance-tagged stress cases that verify whether a
policy honors CPC-1's action-time certificate contract.  Real deployment work
must replace these fixtures with held-out, independently labeled examples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

import cpc1


TASK_LABELS = {
    "entity_resolution": "Q1 Entity resolution",
    "normalization": "Q2 Normalization",
    "metric_mapping": "Q3 Metric mapping",
}
COLORS = {"CPC-1": "#0072B2", "Blind act": "#D55E00", "safe": "#009E73", "unsafe": "#D55E00", "ask": "#E69F00", "reject": "#CC79A7"}


def stress_cases(replicates: int = 20) -> list[cpc1.Record]:
    """Expand the nine vertical-slice cases into deterministic test strata.

    Replication varies only a non-decisive provenance key.  This makes it
    unsuitable for significance claims but useful for testing policy invariants
    across all Q1--Q3 / safe--ask--reject partitions.
    """
    cases: list[cpc1.Record] = []
    for base in cpc1.fixture_cases():
        for replicate in range(replicates):
            fields = dict(base.fields)
            fields["source_snapshot"] = f"s{replicate:02d}"
            cases.append(cpc1.Record(
                case_id=f"{base.case_id}-r{replicate:02d}", task_type=base.task_type,
                candidate_action=base.candidate_action, outcome=base.outcome,
                negative_type=None, fields=fields, near_miss_group=f"eval-{base.case_id}-{replicate:02d}",
                provenance="synthetic:contract-v1",
            ))
    return cases


def expanded_archive() -> list[cpc1.Record]:
    """Use same semantics with a snapshot field so similarity remains explicit."""
    records = []
    for record in cpc1.fixture_archive():
        fields = dict(record.fields)
        fields["source_snapshot"] = "s00"
        records.append(cpc1.Record(record.case_id, record.task_type, record.candidate_action,
            record.outcome, record.negative_type, fields, record.near_miss_group, "synthetic:contract-v1"))
    return records


def blind_act(case: cpc1.Record) -> str:
    return f"ACT({case.candidate_action})"


def classify(decision: str) -> str:
    return decision.split("(", 1)[0]


def expected(case: cpc1.Record) -> str:
    return cpc1.expected_decision(case)


def evaluate(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    archive = expanded_archive()
    rows: list[dict[str, object]] = []
    for case in stress_cases():
        # The snapshot is non-decisive but must be comparable across the pair.
        # Rebind the case snapshot to the archive snapshot to test CPC logic,
        # then retain an explicit record of that controlled fixture choice.
        fields = dict(case.fields)
        fields["source_snapshot"] = "s00"
        bound = cpc1.Record(case.case_id, case.task_type, case.candidate_action, case.outcome,
            None, fields, case.near_miss_group, "synthetic:contract-v1")
        cpc_decision = cpc1.decide(bound, archive)
        for policy, decision, validator_pass in (
            ("CPC-1", cpc_decision["decision"], bool(cpc_decision["validator_pass"])),
            ("Blind act", blind_act(bound), False),
        ):
            kind = classify(str(decision))
            rows.append({
                "fixture_scope": "synthetic:contract-v1", "case_id": bound.case_id,
                "task": bound.task_type, "truth": expected(bound), "policy": policy,
                "decision": kind, "validator_pass": validator_pass,
                "unsafe_autonomy": int(kind == "ACT" and expected(bound) != "ACT"),
                "unnecessary_abstention": int(kind != "ACT" and expected(bound) == "ACT"),
                "unnecessary_question": int(kind == "ASK" and expected(bound) != "ASK"),
                "latency_units": 2 if policy == "CPC-1" else 1,
            })

    mutation_rows = []
    archive_base, cases_base = cpc1.fixture_archive(), cpc1.fixture_cases()
    for case in cases_base:
        cert = cpc1.decide(case, archive_base)
        for mutation in ("cross_task_pair", "wrong_provenance", "forged_observation", "wrong_action", "invalid_decision"):
            forged = json.loads(json.dumps(cert))
            if mutation == "cross_task_pair":
                forged["negative_precedent"] = "archive-2-unsafe" if case.task_type != "normalization" else "archive-1-unsafe"
            elif mutation == "wrong_provenance":
                forged["literals"][0]["provenance"] = "untrusted:forged"
            elif mutation == "forged_observation":
                # Always flip the recorded fact relative to the bound case;
                # assigning True would be a no-op on safe fixtures.
                forged["literals"][0]["observed_value"] = not bool(case.fields[forged["literals"][0]["field"]])
                forged["literals"][0]["status"] = "mismatched"
            elif mutation == "wrong_action":
                # A valid safe proof must not authorize a different action.
                forged["decision"] = "ACT(drop_everything)"
            else:
                # Pick a decision that contradicts this certificate's literal
                # state (rather than accidentally retaining ACT on a safe case).
                forged["decision"] = "REJECT(mismatched_literal)" if str(cert["decision"]).startswith("ACT(") else f"ACT({case.candidate_action})"
            mutation_rows.append({"task": case.task_type, "case_id": case.case_id, "mutation": mutation,
                                  "accepted": cpc1.validate_certificate(forged, archive_base, case)})

    metrics = []
    for policy in ("CPC-1", "Blind act"):
        subset = [row for row in rows if row["policy"] == policy]
        metrics.append({"fixture_scope": "synthetic:contract-v1", "policy": policy, "n": len(subset),
                        "unsafe_autonomy_rate": sum(int(row["unsafe_autonomy"]) for row in subset) / len(subset),
                        "correct_decision_rate": sum(row["truth"] == row["decision"] for row in subset) / len(subset),
                        "validator_pass_rate": sum(bool(row["validator_pass"]) for row in subset) / len(subset),
                        "mean_latency_units": sum(int(row["latency_units"]) for row in subset) / len(subset)})
    write_csv(root / "results" / "contract_evaluation.csv", rows)
    write_csv(root / "results" / "adversarial_mutations.csv", mutation_rows)
    write_csv(root / "results" / "contract_metrics.csv", metrics)
    return rows, mutation_rows, metrics


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    """Return a content hash for the small, versioned benchmark inputs."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=7)


def save(fig: plt.Figure, root: Path, stem: str) -> None:
    """Export self-contained, publication-sized delivery and QA artifacts."""
    figures = root / "figures"
    figures.mkdir(exist_ok=True)
    svg = figures / f"{stem}.svg"
    png = figures / f"{stem}.png"
    fig.savefig(svg, format="svg", bbox_inches="tight")
    fig.savefig(png, format="png", dpi=300, bbox_inches="tight")
    # QA previews are deliberately separate from the public SVG+PNG pairs.
    qa = figures / "_qa"
    qa.mkdir(exist_ok=True)
    with Image.open(png) as image:
        image.convert("L").save(qa / f"{stem}_grayscale.png", dpi=(300, 300))
    plt.close(fig)


def make_figures(root: Path, rows: list[dict[str, object]], mutations: list[dict[str, object]], metrics: list[dict[str, object]]) -> None:
    # Contracts: each figure answers exactly one bounded question. The Q labels
    # refer to task families, not independent experimental replications.
    tasks = list(TASK_LABELS)
    state_order = ["ACT", "ASK", "REJECT"]
    for index, task in enumerate(tasks, start=1):
        label = TASK_LABELS[task]
        counts = Counter(row["truth"] for row in rows if row["task"] == task and row["policy"] == "CPC-1")
        fig, ax = plt.subplots(figsize=(3.5, 2.625))
        ax.bar(state_order, [counts[x] for x in state_order], color=[COLORS["safe"], COLORS["ask"], COLORS["reject"]])
        ax.set_ylim(0, max(counts.values()) * 1.18); ax.set_ylabel("Designed fixtures (n)"); ax.set_title(f"{label}: contract fixture composition", fontsize=9); style(ax)
        save(fig, root, f"raw_q{index}_fixture_composition")

        mcounts = Counter(row["mutation"] for row in mutations if row["task"] == task)
        fig, ax = plt.subplots(figsize=(3.5, 2.625))
        ax.scatter(range(len(mcounts)), [int(mcounts[name]) for name in mcounts], color=COLORS["CPC-1"], s=38)
        ax.set_xticks(range(len(mcounts)), [name.replace("_", "\n") for name in mcounts], fontsize=6)
        ax.set_ylim(0, max(mcounts.values()) * 1.20); ax.set_ylabel("Forged certificates tested"); ax.set_title(f"{label}: adversarial mutation coverage", fontsize=9); style(ax)
        save(fig, root, f"process_q{index}_mutation_coverage")

        per_policy = []
        for policy in ("CPC-1", "Blind act"):
            subset = [r for r in rows if r["task"] == task and r["policy"] == policy]
            per_policy.append(sum(r["truth"] == r["decision"] for r in subset) / len(subset))
        fig, ax = plt.subplots(figsize=(3.5, 2.625))
        ax.bar(["CPC-1", "Blind act"], per_policy, color=[COLORS["CPC-1"], COLORS["Blind act"]])
        # Keep the result figure legible at its declared publication size.
        # The prior long y-axis label collided visually with the title.
        ax.set_ylim(0, 1.05); ax.set_ylabel("Agreement rate"); ax.set_title(f"{label}: fixture-rule agreement", fontsize=9); style(ax)
        save(fig, root, f"result_q{index}_decision_agreement")

    write_csv(root / "results" / "figure_source_metrics.csv", metrics)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.project_root.resolve()
    rows, mutations, metrics = evaluate(root)
    if any(row["accepted"] for row in mutations):
        raise AssertionError("an adversarially forged certificate was accepted")
    make_figures(root, rows, mutations, metrics)
    manifest = {
        "fixture_scope": "synthetic:contract-v1",
        "claim_boundary": "Deterministic contract validation only; not evidence of production-model performance or safety gains.",
        "case_count_per_policy": 180,
        "mutation_count": len(mutations),
        "metrics": metrics,
        "random_seed": None,
        "randomness_note": "No randomized operations; fixture construction and evaluation are deterministic.",
        "key_parameters": {"replicates_per_case": 20, "tau_near": cpc1.TAU_NEAR,
                           "max_differing_fields": cpc1.MAX_DIFFERING_FIELDS},
        "input_sha256": {name: sha256(root / name) for name in ("cpc1.py", "benchmark.py", "题目分析报告.md")},
        "tool_versions": {"python": sys.version.split()[0], "matplotlib": plt.matplotlib.__version__,
                          "numpy": np.__version__},
        "command": "python benchmark.py --project-root .",
    }
    payload = json.dumps(manifest, indent=2) + "\n"
    # Preserve an English name for portability and the modeling-skill's
    # canonical Chinese deliverable name for its reproducibility gate.
    for name in ("reproduction_manifest.json", "复现清单.json"):
        (root / "results" / name).write_text(payload, encoding="utf-8")
    print(json.dumps({"status": "PASS", "fixtures": 180, "mutations_rejected": len(mutations), "metrics": metrics}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
