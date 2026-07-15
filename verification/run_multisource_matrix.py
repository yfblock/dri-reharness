#!/usr/bin/env python3
"""Run real multi-translation-unit Linux driver experiments.

Every case is a versioned manifest whose sources belong to one Kbuild module.
The compact JSON result records scale, provenance, extraction quality, and all
three generated-backend compile outcomes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from run_matrix import _git_rev, _parse_metrics, _parse_score, _sha256  # noqa: E402


def _run(args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _load_manifest(path: str) -> tuple[dict, list[str], str]:
    with open(path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("schema") != 1 or not manifest.get("name"):
        raise ValueError(f"invalid multi-source manifest: {path}")
    base = os.path.dirname(path)
    sources = [os.path.abspath(os.path.join(base, source))
               for source in manifest.get("sources", [])]
    if len(sources) < 4:
        raise ValueError(f"multi-source case requires at least 4 C files: {path}")
    if not all(source.endswith(".c") and os.path.isfile(source) for source in sources):
        raise ValueError(f"manifest contains a missing/non-C source: {path}")
    kbuild = os.path.abspath(os.path.join(base, manifest.get("kbuild", "")))
    if not os.path.isfile(kbuild):
        raise ValueError(f"manifest Kbuild file missing: {path}")
    return manifest, sources, kbuild


def _kbuild_contains_sources(kbuild: str, sources: list[str]) -> bool:
    with open(kbuild, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return all(os.path.splitext(os.path.basename(source))[0] + ".o" in text
               for source in sources)


def _line_count(path: str) -> int:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifests", default=os.path.join(ROOT, "drivers", "multisource"))
    parser.add_argument(
        "--workdir", default=os.path.join(ROOT, "output", "experiment-multisource"))
    parser.add_argument(
        "--output", default=os.path.join(
            ROOT, "experiments", "results", "multisource-matrix.json"))
    args = parser.parse_args()

    manifests = sorted(
        os.path.join(args.manifests, name) for name in os.listdir(args.manifests)
        if name.endswith(".json"))
    if not manifests:
        raise SystemExit("no multi-source manifests found")
    os.makedirs(args.workdir, exist_ok=True)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    rows = []
    for manifest_path in manifests:
        manifest, sources, kbuild = _load_manifest(manifest_path)
        name = manifest["name"]
        outdir = os.path.join(args.workdir, name)
        shutil.rmtree(outdir, ignore_errors=True)
        started = time.monotonic()
        run = _run([
            sys.executable, "-m", "extractor", "driver",
            "-s", manifest_path, "-o", outdir, "--alias-mode", "off",
        ])
        score_path = os.path.join(outdir, "verify", "score.txt")
        metrics_path = os.path.join(outdir, "verify", "metrics.txt")
        analysis_path = os.path.join(outdir, "verify", "analysis.json")
        score = (_parse_score(open(score_path, encoding="utf-8").read())
                 if os.path.isfile(score_path) else {})
        metrics = (_parse_metrics(open(metrics_path, encoding="utf-8").read())
                   if os.path.isfile(metrics_path) else {})
        analysis = (json.load(open(analysis_path, encoding="utf-8"))
                    if os.path.isfile(analysis_path) else {"stats": {}})
        row = {
            "driver": name,
            "manifest": os.path.relpath(manifest_path, ROOT),
            "description": manifest.get("description", ""),
            "kbuild": os.path.relpath(kbuild, ROOT),
            "kbuild_verified": _kbuild_contains_sources(kbuild, sources),
            "source_count": len(sources),
            "source_lines": sum(_line_count(source) for source in sources),
            "functions_analyzed": analysis.get("stats", {}).get(
                "functions_analyzed", 0),
            "source_sha256": {
                os.path.relpath(source, ROOT): _sha256(source) for source in sources
            },
            "seconds": round(time.monotonic() - started, 3),
            "pipeline_exit": run.returncode,
            "metrics": metrics,
            "readiness": score,
            "backends": {
                "harness_compile": not os.path.exists(os.path.join(
                    outdir, "verify", "harness.compile.log")),
                "harness_trace": os.path.exists(os.path.join(
                    outdir, "verify", "harness.trace.txt")),
                "baremetal_compile": not os.path.exists(os.path.join(
                    outdir, "verify", "baremetal.compile.log")),
                "linux_compile": not os.path.exists(os.path.join(
                    outdir, "verify", "linux.compile.log")),
            },
        }
        rows.append(row)
        state = "/".join(
            "Y" if row["backends"][key] else "N"
            for key in ("harness_compile", "baremetal_compile", "linux_compile"))
        print(f"{name:<18} sources={len(sources):>2} lines={row['source_lines']:>5} "
              f"ops={metrics.get('ops', '?'):>3} backends={state} {row['seconds']:>6.2f}s")

    result = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {
            "reharness_commit": _git_rev(ROOT),
            "linux_commit": _git_rev(os.path.join(ROOT, "linux")),
            "kernel_release": _run([
                "make", "-s", "-C", os.path.join(ROOT, "kernel", "build"),
                "kernelrelease"]).stdout.strip(),
        },
        "aggregate": {
            "drivers": len(rows),
            "translation_units": sum(row["source_count"] for row in rows),
            "source_lines": sum(row["source_lines"] for row in rows),
            "ops": sum(row["metrics"].get("ops", 0) for row in rows),
            "rmw": sum(row["metrics"].get("rmw", 0) for row in rows),
            "registers": sum(row["metrics"].get("registers", 0) for row in rows),
        },
        "drivers": rows,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.output}")

    valid = all(
        row["pipeline_exit"] == 0 and row["kbuild_verified"]
        and all(row["backends"][key] for key in (
            "harness_compile", "baremetal_compile", "linux_compile"))
        for row in rows)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
