#!/usr/bin/env python3
"""Verify that callback binding improves without claiming role semantics."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path


from repo_paths import REPO_ROOT as ROOT
DEFAULT_BASELINE = (
    ROOT / "research" / "experiments" / "results" /
    "zero-shot-v2-matrix.json")
DEFAULT_CANDIDATE = (
    ROOT / "research" / "experiments" / "results" /
    "zero-shot-v2-callback-binding.json")


def compare_reports(baseline: dict, candidate: dict) -> list[str]:
    errors: list[str] = []
    baseline_rows = {row["driver"]: row for row in baseline.get("drivers", [])}
    candidate_rows = {row["driver"]: row for row in candidate.get("drivers", [])}
    if set(baseline_rows) != set(candidate_rows):
        errors.append("candidate driver set differs from frozen baseline")
        return errors

    # The callback-binding and missing_role chapters are closed: the fix
    # landed and current matrices carry neither blocker.  The oracle now
    # pins the structural invariant that matters going forward — no driver
    # regresses to callback_binding and the frozen cluster shape is stable.
    selected = baseline.get("blocker_clustering", {}).get(
        "first_common_semantic_blocker") or {}
    selected_drivers = set(selected.get("drivers", []))

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

    # Role evidence stability now spans every driver (the callback_binding
    # cluster that used to narrow this is gone).
    for driver in sorted(baseline_rows):
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
    if next_blocker != selected:
        errors.append("candidate first common blocker differs from frozen "
                      f"baseline: {selected!r} -> {next_blocker!r}")
    return errors


def mutation_self_test(baseline: dict, candidate: dict) -> list[str]:
    errors: list[str] = []
    clusters = baseline["blocker_clustering"].get("clusters") or []
    selected = baseline["blocker_clustering"].get(
        "first_common_semantic_blocker")
    if selected:
        driver = selected["drivers"][0]
    elif clusters:
        driver = clusters[0]["drivers"][0]
    else:
        # No common blocker remains: mutate the first driver directly —
        # the oracle must still catch per-driver regressions.
        driver = baseline["drivers"][0]["driver"]

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
    if any(item.startswith("missing role for:")
           for item in row["blockers"]):
        row["blockers"] = [item for item in row["blockers"]
                           if not item.startswith("missing role for:")]
    else:
        # regression direction: reintroduce a missing role the matrix
        # no longer carries — the oracle must flag role evidence drift
        row["blockers"].append("missing role for: mutation_probe_fn")
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
