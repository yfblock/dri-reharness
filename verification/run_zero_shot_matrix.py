#!/usr/bin/env python3
"""Run the frozen 12-driver holdout with exact, auditable compile contexts."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verification.check_generalization_guard import (  # noqa: E402
    DEFAULT_HOLDOUT,
    check_guard,
)
from verification.materialize_holdout_contexts import (  # noqa: E402
    DEFAULT_RECIPES,
    validate_recipes,
)
from verification.run_matrix import (  # noqa: E402
    _git_rev,
    _parse_metrics,
    _parse_score,
    _sha256,
)


DEFAULT_DATABASE = ROOT / "output" / "zero-shot-contexts" / "compile_commands.json"
DEFAULT_CONTEXT_REPORT = ROOT / "experiments" / "results" / "zero-shot-contexts.json"

# The order only controls matching when wording could overlap. Selection of the
# first common blocker uses driver count and then the category name, so it is
# deterministic and independent of holdout iteration order.
BLOCKER_RULES: tuple[tuple[str, str], ...] = (
    ("source_access_unaccounted", r"source MMIO access site\(s\) unaccounted"),
    ("ris_evidence_missing", r"RIS operation\(s\) lack source evidence"),
    ("source_access_filtered", r"source MMIO access site\(s\) explicitly filtered"),
    ("unsupported_access", r"(?:source register/opaque access site\(s\) unsupported|"
                           r"register operation\(s\) use unsupported access domain)"),
    ("path_unvalidated", r"path predicate\(s\) not SMT-validated"),
    ("path_infeasible", r"contradictory/infeasible RIS path\(s\)"),
    ("switch_exclusivity", r"switch path pair\(s\) not proven exclusive"),
    ("unsupported_control_flow", r"unsupported control-flow transfer\(s\)"),
    ("subsystem_summary", r"subsystem library callback\(s\) lack semantic summary"),
    ("subsystem_validation", r"synthesized subsystem callback\(s\) "
                              r"lack generic-backend execution oracle"),
    ("unsafe_dynamic_address", r"unsafe dynamic register address\(es\)"),
    ("unknown_value", r"unknown \(Top\) value\(s\)"),
    ("clang_diagnostics", r"clang error diagnostic\(s\)"),
    ("conservative_loop", r"conservative loop summary/summaries require validation"),
    ("missing_role", r"^missing role for:"),
    ("callback_binding", r"^callback entry without table binding:"),
    ("no_register_access", r"^no MMIO register accesses$"),
    ("linux_semantic_binding", r"^linux backend has unsupported semantic bindings$"),
)
UMBRELLA_BLOCKERS = {"linux_semantic_binding"}


def normalize_blocker(blocker: str) -> str:
    for category, pattern in BLOCKER_RULES:
        if re.search(pattern, blocker):
            return category
    return "unclassified"


def cluster_blockers(rows: list[dict]) -> dict:
    clustered: dict[str, dict[str, object]] = {}
    for row in rows:
        per_driver: dict[str, list[str]] = {}
        for blocker in row.get("blockers", []):
            per_driver.setdefault(normalize_blocker(blocker), []).append(blocker)
        for category, raw in per_driver.items():
            cluster = clustered.setdefault(category, {"drivers": [], "evidence": {}})
            cluster["drivers"].append(row["driver"])
            cluster["evidence"][row["driver"]] = raw

    result = []
    for category, cluster in clustered.items():
        drivers = sorted(set(cluster["drivers"]))
        result.append({
            "category": category,
            "driver_count": len(drivers),
            "drivers": drivers,
            "evidence": cluster["evidence"],
            "umbrella": category in UMBRELLA_BLOCKERS,
        })
    result.sort(key=lambda item: (-item["driver_count"], item["category"]))
    eligible = [item for item in result
                if item["driver_count"] >= 3
                and not item["umbrella"]
                and item["category"] != "unclassified"]
    first = None
    if eligible:
        selected = eligible[0]
        first = {
            "category": selected["category"],
            "driver_count": selected["driver_count"],
            "drivers": selected["drivers"],
        }
    return {"clusters": result, "first_common_semantic_blocker": first}


def _relative(path: str) -> str:
    return os.path.relpath(os.path.abspath(path), ROOT)


def _artifact_sha(path: Path) -> str | None:
    return _sha256(str(path)) if path.is_file() else None


def _target_diagnostics(warnings: list[str], source: Path) -> list[str]:
    source_text = str(source)
    return [warning for warning in warnings
            if warning.startswith("clang diag[") and source_text in warning]


def _run_case(case: dict, manifest_dir: Path, database: Path,
              context_row: dict, work_root: Path) -> dict:
    source = (manifest_dir / case["source"]).resolve()
    outdir = work_root / case["id"]
    shutil.rmtree(outdir, ignore_errors=True)
    started = time.monotonic()
    command = [
        sys.executable, "-m", "extractor", "driver",
        "-s", str(source), "-o", str(outdir),
        "--compile-commands", str(database),
        "--compile-context", "required",
    ]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    analysis_path = outdir / "verify" / "analysis.json"
    score_path = outdir / "verify" / "score.txt"
    metrics_path = outdir / "verify" / "metrics.txt"
    if not analysis_path.is_file():
        return {
            "driver": case["id"],
            "subsystem": case["subsystem"],
            "difficulty": case["difficulty"],
            "source": _relative(str(source)),
            "source_sha256": case["source_sha256"],
            "seconds": elapsed,
            "pipeline_exit": run.returncode,
            "pipeline_completed": False,
            "stdout_tail": run.stdout[-4000:],
            "stderr_tail": run.stderr[-4000:],
            "blockers": [],
            "normalized_blockers": [],
        }

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    stats = analysis["stats"]
    context = stats.get("compile_context", {})
    expected_raw_sha = context_row["raw_command_sha256"]
    if context.get("origin") != "compile-commands":
        raise RuntimeError(
            f"{case['id']} used non-exact compile context {context.get('origin')!r}")
    if Path(context.get("provenance", "")).resolve() != database.resolve():
        raise RuntimeError(f"{case['id']} compile-context provenance drift")
    if context.get("raw_command_sha256") != expected_raw_sha:
        raise RuntimeError(f"{case['id']} compile command hash drift")

    score = (_parse_score(score_path.read_text(encoding="utf-8"))
             if score_path.is_file() else {})
    metrics = (_parse_metrics(metrics_path.read_text(encoding="utf-8"))
               if metrics_path.is_file() else {})
    warnings = analysis.get("warnings", [])
    target_diagnostics = _target_diagnostics(warnings, source)
    generation = analysis.get("generation", {})
    blockers = score.get("blockers", [])
    normalized = sorted(set(normalize_blocker(item) for item in blockers))
    readiness = {
        "harness": score.get("backend_harness_ready") is True,
        "baremetal": score.get("backend_bare_metal_ready") is True,
        "linux": score.get("backend_linux_ready") is True,
    }
    readiness["any_backend"] = any(readiness.values())
    readiness["all_backends"] = all(
        readiness[name] for name in ("harness", "baremetal", "linux"))
    backend_compile = {
        backend: generation.get(backend, {}).get("compiled") is True
        for backend in ("harness", "baremetal", "linux")
    }
    access = stats.get("access_accounting", {})
    subsystem_sites = [
        site for site in access.get("sites", [])
        if site.get("origin") == "subsystem_summary"]
    return {
        "driver": case["id"],
        "subsystem": case["subsystem"],
        "difficulty": case["difficulty"],
        "source": _relative(str(source)),
        "source_sha256": case["source_sha256"],
        "seconds": elapsed,
        "pipeline_exit": run.returncode,
        "pipeline_completed": (
            run.returncode == 0 and score_path.is_file() and metrics_path.is_file()),
        "stdout_tail": run.stdout[-4000:] if run.returncode else "",
        "stderr_tail": run.stderr[-4000:] if run.returncode else "",
        "compile_context": {
            "origin": context["origin"],
            "provenance": _relative(context["provenance"]),
            "profile": context_row["profile"],
            "profile_kind": context_row["profile_kind"],
            "arch": context_row["arch"],
            "context_note": context_row.get("context_note"),
            "argument_count": context.get("argument_count"),
            "arguments_sha256": context.get("arguments_sha256"),
            "raw_command_sha256": context.get("raw_command_sha256"),
        },
        "functions_analyzed": stats.get("functions_analyzed"),
        "total_ops": stats.get("total_ops"),
        "subsystem_summary": {
            "synthetic_functions": stats.get(
                "synthetic_subsystem_functions", 0),
            "summaries": stats.get("subsystem_summaries", {}),
            "source_sites": len(subsystem_sites),
            "kinds": sorted({site.get("subsystem_summary")
                             for site in subsystem_sites
                             if site.get("subsystem_summary")}),
        },
        "metrics": metrics,
        "access_accounting": {
            key: access.get(key) for key in (
                "source_accesses", "emitted", "filtered", "unsupported",
                "unaccounted", "ris_ops_without_evidence", "strict_complete")
        },
        "clang_diagnostics": {
            "error_count": metrics.get("clang_diagnostics"),
            "target_source": target_diagnostics,
            "target_source_error_count": sum(
                item.startswith(("clang diag[3]", "clang diag[4]"))
                for item in target_diagnostics),
        },
        "generation": generation,
        "backend_compile": backend_compile,
        "all_backends_compile": all(backend_compile.values()),
        "strict_readiness": readiness,
        "unsupported_or_fallback": {
            "fallback_compile_context": False,
            "unsupported_source_accesses": access.get("unsupported", 0),
            "unsupported_backends": sorted(
                backend for backend, result in generation.items()
                if result.get("unsupported")),
        },
        "readiness_score": {
            key: value for key, value in score.items() if key != "blockers"
        },
        "blockers": blockers,
        "normalized_blockers": normalized,
        "artifacts": {
            "ris_sha256": _artifact_sha(outdir / f"{source.stem}.ris"),
            "device_spec_sha256": _artifact_sha(outdir / f"{source.stem}.dspec"),
            "analysis_sha256": _artifact_sha(analysis_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--recipes", default=str(DEFAULT_RECIPES))
    parser.add_argument("--compile-commands", default=str(DEFAULT_DATABASE))
    parser.add_argument("--context-report", default=str(DEFAULT_CONTEXT_REPORT))
    parser.add_argument(
        "--workdir", default=str(ROOT / "output" / "zero-shot-matrix"))
    parser.add_argument(
        "--output", default=str(
            ROOT / "experiments" / "results" / "zero-shot-matrix.json"))
    args = parser.parse_args()

    holdout_path = Path(args.holdout).resolve()
    recipes_path = Path(args.recipes).resolve()
    database = Path(args.compile_commands).resolve()
    context_report_path = Path(args.context_report).resolve()
    manifest = json.loads(holdout_path.read_text(encoding="utf-8"))
    recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
    guard = check_guard(holdout_path)
    recipe_issues = validate_recipes(manifest, recipes)
    if not guard["passed"] or recipe_issues:
        raise RuntimeError("holdout/context recipe validation failed")
    if not database.is_file() or not context_report_path.is_file():
        raise RuntimeError(
            "materialized contexts missing; run materialize_holdout_contexts.py")
    context_report = json.loads(context_report_path.read_text(encoding="utf-8"))
    if context_report.get("exact_contexts") != len(manifest["cases"]):
        raise RuntimeError("context report does not cover the full holdout")
    if context_report.get("compile_database_sha256") != _sha256(str(database)):
        raise RuntimeError("compile database hash differs from context report")
    contexts = {row["case"]: row for row in context_report["contexts"]}
    if set(contexts) != {case["id"] for case in manifest["cases"]}:
        raise RuntimeError("context report case set differs from frozen holdout")

    work_root = Path(args.workdir).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in manifest["cases"]:
        row = _run_case(
            case, holdout_path.parent, database, contexts[case["id"]], work_root)
        rows.append(row)
        backends = row.get("backend_compile", {})
        state = "/".join("Y" if backends.get(name) else "N"
                         for name in ("harness", "baremetal", "linux"))
        print(f"{case['id']:<18} ops={row.get('total_ops', '?'):>4} "
              f"backends={state} blockers={len(row['blockers']):>2} "
              f"{row['seconds']:>7.2f}s")

    clustering = cluster_blockers(rows)
    strict_counts = {
        backend: sum(row.get("strict_readiness", {}).get(backend) is True
                     for row in rows)
        for backend in ("harness", "baremetal", "linux", "any_backend", "all_backends")
    }
    aggregate = {
        "cases": len(rows),
        "pipeline_completed": sum(row["pipeline_completed"] for row in rows),
        "exact_compile_contexts": sum(
            row.get("compile_context", {}).get("origin") == "compile-commands"
            for row in rows),
        "access_accounting_strict": sum(
            row.get("access_accounting", {}).get("strict_complete") is True
            for row in rows),
        "all_backends_compile": sum(row.get("all_backends_compile") is True
                                    for row in rows),
        "cases_with_hardware_interactions": sum(
            (row.get("total_ops") or 0) > 0 for row in rows),
        "subsystem_summarized_cases": sum(
            row.get("subsystem_summary", {}).get("source_sites", 0) > 0
            or row.get("subsystem_summary", {}).get("synthetic_functions", 0) > 0
            for row in rows),
        "strict_ready": strict_counts,
    }
    acceptance = {
        "guard_passed": guard["passed"],
        "recipe_validation_passed": not recipe_issues,
        "all_cases_completed": aggregate["pipeline_completed"] == len(rows),
        "all_contexts_exact": aggregate["exact_compile_contexts"] == len(rows),
        "all_cases_have_hardware_interactions": (
            aggregate["cases_with_hardware_interactions"] == len(rows)),
        "common_semantic_blocker_found": (
            clustering["first_common_semantic_blocker"] is not None),
    }
    report = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "holdout": manifest["name"],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "reharness_commit": _git_rev(str(ROOT)),
            "linux_commit": _git_rev(str(ROOT / "linux")),
        },
        "compile_context_evidence": {
            "database": _relative(str(database)),
            "database_sha256": _sha256(str(database)),
            "report": _relative(str(context_report_path)),
            "report_sha256": _sha256(str(context_report_path)),
        },
        "guard": guard,
        "aggregate": aggregate,
        "blocker_clustering": clustering,
        "drivers": rows,
        "acceptance": acceptance,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "aggregate": aggregate,
        "first_common_semantic_blocker": clustering[
            "first_common_semantic_blocker"],
        "acceptance": acceptance,
        "output": _relative(str(output)),
    }, indent=2, sort_keys=True))
    return 0 if all(acceptance.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
