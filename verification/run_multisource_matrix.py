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
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from run_matrix import _git_rev, _parse_metrics, _parse_score, _sha256  # noqa: E402
from extractor import mmio  # noqa: E402


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


def _strip_comments_strings(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"//[^\n]*", " ", source)
    source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
    source = re.sub(r"'(?:\\.|[^'\\])*'", "''", source)
    return source


def _source_mmio_counts(sources: list[str]) -> dict[str, int]:
    read_names = set(mmio.MMIO_READ_FNS) | set(
        mmio.PRIVATE_MMIO_READ_LAYOUTS)
    write_names = set(mmio.MMIO_WRITE_FNS) | set(
        mmio.PRIVATE_MMIO_WRITE_LAYOUTS)

    def count(names: set[str], text: str) -> int:
        pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(name) for name in sorted(names))
            + r")\s*\(")
        return len(pattern.findall(text))

    reads = writes = 0
    for source in sources:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            text = _strip_comments_strings(fh.read())
        reads += count(read_names, text)
        writes += count(write_names, text)
    return {"reads": reads, "writes": writes, "total": reads + writes}


def _compile_original_kbuild(manifest: dict, kbuild: str, outdir: str) -> dict:
    kernel_build = os.path.join(ROOT, "kernel", "build")
    source_dir = os.path.dirname(kbuild)
    copy_dir = os.path.join(outdir, "original-kbuild-src")
    log_path = os.path.join(outdir, "verify", "original-kbuild.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    shutil.rmtree(copy_dir, ignore_errors=True)
    shutil.copytree(source_dir, copy_dir, ignore=shutil.ignore_patterns(
        "*.o", "*.ko", "*.mod", "*.mod.c", "*.mod.o", ".*.cmd",
        "modules.order", "Module.symvers"))

    kconfig = [str(item) for item in manifest.get("kconfig", [])]
    make_config = []
    flags = []
    for item in kconfig:
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        make_config.append(f"{name}={'' if value == 'n' else value}")
        if value == "y":
            flags.append(f"-D{name}=1")
        elif value == "m":
            flags.append(f"-D{name}_MODULE=1")
    command = ["make", "-C", kernel_build, f"M={copy_dir}", *make_config]
    if flags:
        command.append("KCFLAGS=" + " ".join(flags))
    command.append("modules")
    strict = _run(command)
    combined = strict.stdout + strict.stderr
    unresolved = sorted(set(re.findall(
        r'modpost: "([^"]+)" .* undefined', combined)))
    relaxed = None
    if strict.returncode != 0 and unresolved:
        relaxed_command = command[:-1] + ["KBUILD_MODPOST_WARN=1", "modules"]
        relaxed = _run(relaxed_command)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("strict command: " + " ".join(command) + "\n\n")
        fh.write(strict.stdout)
        fh.write(strict.stderr)
        if relaxed is not None:
            fh.write("\nmodpost-warning retry: "
                     + " ".join(relaxed_command) + "\n\n")
            fh.write(relaxed.stdout)
            fh.write(relaxed.stderr)
    target = manifest.get("kbuild_target", "")
    artifact = os.path.join(copy_dir, target) if target else ""
    final_run = relaxed or strict
    return {
        "attempted": True,
        "success": final_run.returncode == 0 and bool(artifact)
        and os.path.isfile(artifact),
        "strict_success": strict.returncode == 0,
        "modpost_warning_retry": relaxed is not None,
        "unresolved_external_symbols": unresolved,
        "exit": final_run.returncode,
        "target": target,
        "log": os.path.relpath(log_path, ROOT),
    }


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
        analysis_stats = analysis.get("stats", {})
        source_mmio = _source_mmio_counts(sources)
        original_kbuild = _compile_original_kbuild(
            manifest, kbuild, outdir)
        direct_mmio = (analysis_stats.get("propagation_by_depth") or [
            {"total_mmio_ops": 0}])[0].get("total_mmio_ops", 0)
        ris_mmio = analysis_stats.get("total_ops", metrics.get("ops", 0))
        row = {
            "driver": name,
            "manifest": os.path.relpath(manifest_path, ROOT),
            "description": manifest.get("description", ""),
            "kbuild": os.path.relpath(kbuild, ROOT),
            "kbuild_verified": _kbuild_contains_sources(kbuild, sources),
            "source_count": len(sources),
            "source_lines": sum(_line_count(source) for source in sources),
            "functions_analyzed": analysis_stats.get("functions_analyzed", 0),
            "call_edges": analysis_stats.get("call_edges", 0),
            "cross_tu_call_edges": analysis_stats.get(
                "cross_tu_call_edges", 0),
            "resolved_cross_tu_call_edges": analysis_stats.get(
                "resolved_cross_tu_call_edges", 0),
            "propagated_mmio_edges": analysis_stats.get(
                "propagated_mmio_edges", 0),
            "propagation_by_depth": analysis_stats.get(
                "propagation_by_depth", []),
            "duplicate_static_symbols": analysis_stats.get(
                "duplicate_static_symbols", 0),
            "unresolved_internal_calls": analysis_stats.get(
                "unresolved_internal_calls", 0),
            "source_mmio_primitives": source_mmio,
            "direct_mmio_ops": direct_mmio,
            "ris_mmio_ops": ris_mmio,
            "mmio_primitive_coverage": (
                round(min(direct_mmio, source_mmio["total"])
                      / source_mmio["total"], 4)
                if source_mmio["total"] else None),
            "direct_mmio_delta": direct_mmio - source_mmio["total"],
            "propagation_amplification": (
                round(ris_mmio / direct_mmio, 4) if direct_mmio else None),
            "original_kbuild": original_kbuild,
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
                "harness_trace": analysis.get("generation", {}).get(
                    "harness", {}).get("trace_passed", False),
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
              f"ops={metrics.get('ops', '?'):>4} kbuild={'Y' if original_kbuild['success'] else 'N'} "
              f"backends={state} {row['seconds']:>6.2f}s")

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
            "call_edges": sum(row["call_edges"] for row in rows),
            "cross_tu_call_edges": sum(row["cross_tu_call_edges"] for row in rows),
            "resolved_cross_tu_call_edges": sum(
                row["resolved_cross_tu_call_edges"] for row in rows),
            "propagated_mmio_edges": sum(
                row["propagated_mmio_edges"] for row in rows),
            "source_mmio_primitives": sum(
                row["source_mmio_primitives"]["total"] for row in rows),
            "direct_mmio_ops": sum(row["direct_mmio_ops"] for row in rows),
            "ris_mmio_ops": sum(row["ris_mmio_ops"] for row in rows),
        },
        "drivers": rows,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.output}")

    valid = all(
        row["pipeline_exit"] == 0 and row["kbuild_verified"]
        and row["original_kbuild"]["success"]
        and all(row["backends"][key] for key in (
            "harness_compile", "baremetal_compile", "linux_compile"))
        for row in rows)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
