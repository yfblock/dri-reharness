#!/usr/bin/env python3
"""Run the frozen first holdout with and without imported compile context."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from check_generalization_guard import DEFAULT_HOLDOUT, check_guard


ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_rev(path: Path) -> str:
    run = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def _parse_score(path: Path) -> dict:
    result: dict = {}
    blockers: list[str] = []
    in_blockers = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "blockers:":
            in_blockers = True
            continue
        if line == "blockers: []":
            result["blockers"] = []
            continue
        if in_blockers and line.startswith("- "):
            blockers.append(line[2:])
            continue
        if ":" not in line or line == "generation_readiness:":
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if value in {"True", "False"}:
            result[key] = value == "True"
        else:
            try:
                result[key] = float(value)
            except ValueError:
                result[key] = value
    result["blockers"] = blockers
    return result


def _run_case(case: dict, manifest_dir: Path, mode: str,
              work_root: Path) -> dict:
    source = (manifest_dir / case["source"]).resolve()
    outdir = work_root / mode
    shutil.rmtree(outdir, ignore_errors=True)
    context_mode = mode
    command = [
        sys.executable, "-m", "extractor", "driver",
        "-s", str(source), "-o", str(outdir),
        "--compile-context", context_mode,
    ]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    analysis_path = outdir / "verify" / "analysis.json"
    if not analysis_path.is_file():
        return {
            "pipeline_exit": run.returncode,
            "stdout": run.stdout[-4000:],
            "stderr": run.stderr[-4000:],
        }
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    stats = analysis["stats"]
    context = stats["compile_context"]
    source_text = str(source)
    target_diagnostics = [
        warning for warning in analysis.get("warnings", [])
        if warning.startswith("clang diag[") and source_text in warning
    ]
    name = source.stem
    return {
        "pipeline_exit": run.returncode,
        "compile_context": context,
        "functions_analyzed": stats.get("functions_analyzed"),
        "total_ops": stats.get("total_ops"),
        "source_accesses": stats.get("access_accounting", {}).get("source_accesses"),
        "access_accounting_strict": stats.get(
            "access_accounting", {}).get("strict_complete"),
        "target_source_diagnostics": target_diagnostics,
        "target_source_error_count": sum(
            warning.startswith(("clang diag[3]", "clang diag[4]"))
            for warning in target_diagnostics),
        "generation": analysis.get("generation", {}),
        "readiness": _parse_score(outdir / "verify" / "score.txt"),
        "ris_sha256": _sha256(outdir / f"{name}.ris"),
        "device_spec_sha256": _sha256(outdir / f"{name}.dspec"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", default=str(DEFAULT_HOLDOUT))
    parser.add_argument("--case", default=None)
    parser.add_argument(
        "--workdir", default=str(ROOT / "output" / "zero-shot-v1"))
    parser.add_argument(
        "--output", default=str(
            ROOT / "experiments" / "results" / "zero-shot-v1.json"))
    args = parser.parse_args()

    manifest_path = Path(args.holdout).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_id = args.case or manifest["first_run"]
    case = next((item for item in manifest["cases"] if item["id"] == case_id), None)
    if case is None:
        raise SystemExit(f"unknown holdout case: {case_id}")

    guard = check_guard(manifest_path)
    work_root = Path(args.workdir).resolve() / case_id
    baseline = _run_case(case, manifest_path.parent, "off", work_root)
    imported_mode = "required" if case.get("compile_context") != "discover" else "auto"
    imported = _run_case(case, manifest_path.parent, imported_mode, work_root)
    semantic_equal = (
        baseline.get("ris_sha256") == imported.get("ris_sha256")
        and baseline.get("device_spec_sha256") == imported.get("device_spec_sha256")
    )
    report = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "holdout": manifest["name"],
        "case": case_id,
        "source": os.path.relpath(
            (manifest_path.parent / case["source"]).resolve(), ROOT),
        "source_sha256": case["source_sha256"],
        "environment": {
            "reharness_commit": _git_rev(ROOT),
            "linux_commit": _git_rev(ROOT / "linux"),
        },
        "guard": guard,
        "baseline_without_importer": baseline,
        "with_compile_context_importer": imported,
        "semantic_outputs_equal": semantic_equal,
        "acceptance": {
            "guard_passed": guard["passed"],
            "imported_context_found": imported.get(
                "compile_context", {}).get("origin") in {
                    "kbuild-cmd", "compile-commands"},
            "no_target_source_errors": imported.get(
                "target_source_error_count") == 0,
            "access_accounting_strict": imported.get(
                "access_accounting_strict") is True,
            "all_backends_compile": all(
                backend.get("compiled") is True
                for backend in imported.get("generation", {}).values()),
            "semantic_regression_free": semantic_equal,
            "function_inventory_stable": baseline.get(
                "functions_analyzed") == imported.get("functions_analyzed"),
        },
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
