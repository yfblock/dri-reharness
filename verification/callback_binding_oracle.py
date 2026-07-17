#!/usr/bin/env python3
"""Verify that callback binding improves without claiming role semantics."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "experiments" / "results" / "zero-shot-v2-matrix.json"
DEFAULT_CANDIDATE = (
    ROOT / "experiments" / "results" / "zero-shot-v2-callback-binding.json")


def compare_reports(baseline: dict, candidate: dict) -> list[str]:
    errors: list[str] = []
    baseline_rows = {row["driver"]: row for row in baseline.get("drivers", [])}
    candidate_rows = {row["driver"]: row for row in candidate.get("drivers", [])}
    if set(baseline_rows) != set(candidate_rows):
        errors.append("candidate driver set differs from frozen baseline")
        return errors

    selected = baseline.get("blocker_clustering", {}).get(
        "first_common_semantic_blocker") or {}
    if selected.get("category") != "callback_binding":
        errors.append("frozen baseline first blocker is not callback_binding")
    selected_drivers = set(selected.get("drivers", []))
    if len(selected_drivers) < 3:
        errors.append("frozen callback_binding cluster is not common")

    stable_aggregate = (
        "access_accounting_strict", "all_backends_compile", "cases",
        "cases_with_hardware_interactions", "exact_compile_contexts",
        "pipeline_completed", "strict_ready", "subsystem_summarized_cases")
    for key in stable_aggregate:
        old = baseline.get("aggregate", {}).get(key)
        new = candidate.get("aggregate", {}).get(key)
        if old != new:
            errors.append(f"aggregate {key} changed: {old!r} -> {new!r}")

    stable_driver = (
        "total_ops", "access_accounting", "backend_compile",
        "strict_readiness")
    for driver in sorted(baseline_rows):
        old = baseline_rows[driver]
        new = candidate_rows[driver]
        for key in stable_driver:
            if old.get(key) != new.get(key):
                errors.append(f"{driver} {key} changed")
        if "callback_binding" in new.get("normalized_blockers", []):
            errors.append(f"{driver} retains callback_binding blocker")

    for driver in sorted(selected_drivers):
        old_missing = sorted(
            item for item in baseline_rows[driver].get("blockers", [])
            if item.startswith("missing role for:"))
        new_missing = sorted(
            item for item in candidate_rows[driver].get("blockers", [])
            if item.startswith("missing role for:"))
        if old_missing != new_missing:
            errors.append(f"{driver} missing_role evidence changed")

    next_blocker = candidate.get("blocker_clustering", {}).get(
        "first_common_semantic_blocker") or {}
    if next_blocker.get("category") != "missing_role":
        errors.append("candidate first blocker is not preserved missing_role")
    if set(next_blocker.get("drivers", [])) != selected_drivers:
        errors.append("candidate missing_role cluster differs from selected cases")
    return errors


def mutation_self_test(baseline: dict, candidate: dict) -> list[str]:
    errors: list[str] = []
    selected = baseline["blocker_clustering"]["first_common_semantic_blocker"]
    driver = selected["drivers"][0]

    blocker_mutation = copy.deepcopy(candidate)
    row = next(item for item in blocker_mutation["drivers"]
               if item["driver"] == driver)
    row["normalized_blockers"].append("callback_binding")
    if not compare_reports(baseline, blocker_mutation):
        errors.append("oracle missed callback blocker mutation")

    compile_mutation = copy.deepcopy(candidate)
    row = next(item for item in compile_mutation["drivers"]
               if item["driver"] == driver)
    row["backend_compile"]["linux"] = not row["backend_compile"]["linux"]
    if not compare_reports(baseline, compile_mutation):
        errors.append("oracle missed backend compile mutation")

    role_mutation = copy.deepcopy(candidate)
    row = next(item for item in role_mutation["drivers"]
               if item["driver"] == driver)
    row["blockers"] = [item for item in row["blockers"]
                       if not item.startswith("missing role for:")]
    if not compare_reports(baseline, role_mutation):
        errors.append("oracle missed missing_role mutation")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--candidate", default=str(DEFAULT_CANDIDATE))
    parser.add_argument("--output")
    args = parser.parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    errors = compare_reports(baseline, candidate)
    mutation_errors = mutation_self_test(baseline, candidate)
    report = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "baseline": str(Path(args.baseline).resolve().relative_to(ROOT)),
        "candidate": str(Path(args.candidate).resolve().relative_to(ROOT)),
        "callback_binding_removed": not errors,
        "missing_role_preserved": not errors,
        "mutation_tests_passed": not mutation_errors,
        "errors": errors,
        "mutation_errors": mutation_errors,
        "passed": not errors and not mutation_errors,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
