#!/usr/bin/env python3
"""Produce a machine-readable RIS reliability audit."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import walk_leaf_ops  # noqa: E402
from extractor.metrics import driver_metrics, score  # noqa: E402


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    run = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def build_driver_report(source: str, alias_mode: str = "off") -> dict:
    source = os.path.abspath(source)
    result = extract_ris(ExtractorConfig(source=source, alias_mode=alias_mode))
    metrics = driver_metrics(result.formal)
    readiness = score(
        result.device_spec, result.formal, result.warnings, result.facts)
    accounting = result.formal.get("metadata", {}).get("access_accounting", {})
    control = result.formal.get("metadata", {}).get("control_accounting", {})
    paths = result.formal.get("metadata", {}).get("path_validation", {})

    op_ids: list[str] = []
    evidence_sites: list[str] = []
    for module in result.formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("Read") or op.get("Write")
                    or op.get("ReadModifyWrite"))
            if body is None:
                continue
            if body.get("op_id"):
                op_ids.append(body["op_id"])
            site_id = (body.get("evidence") or {}).get("site_id")
            if site_id:
                evidence_sites.append(site_id)

    duplicate_op_ids = sorted({value for value in op_ids
                               if op_ids.count(value) > 1})
    site_fanout: dict[str, int] = {}
    for site_id in evidence_sites:
        site_fanout[site_id] = site_fanout.get(site_id, 0) + 1
    audit = {
        "leaf_register_ops": len(op_ids),
        "unique_op_ids": len(set(op_ids)),
        "duplicate_op_ids": duplicate_op_ids,
        "ops_with_evidence": len(evidence_sites),
        "unique_evidence_sites": len(site_fanout),
        "max_site_fanout": max(site_fanout.values(), default=0),
    }
    path_strict = (
        paths.get("complete", False)
        and paths.get("unknown", 0) == 0
        and paths.get("infeasible", 0) == 0
        and all(pair.get("exclusive", False)
                for pair in paths.get("switch_pairs", [])))
    strict = (
        accounting.get("strict_complete", False)
        and control.get("complete", True)
        and path_strict
        and metrics.get("unsafe_computed", 0) == 0
        and metrics.get("unknown_value", 0) == 0
        and metrics.get("conservative_loop", 0) == 0
        and metrics.get("reliability", {}).get("Unsupported", 0) == 0
        and not duplicate_op_ids
        and len(op_ids) == len(evidence_sites))
    return {
        "driver": result.formal.get("driver"),
        "source": source,
        "source_sha256": _sha256(source),
        "strict_reliable": strict,
        "claim_scope": result.formal.get("metadata", {}).get(
            "assurance_scope", {}),
        "audit": audit,
        "access_accounting": accounting,
        "control_accounting": control,
        "path_validation": paths,
        "alias_analysis": result.stats.get("alias_analysis", {}),
        "metrics": metrics,
        "readiness": readiness,
        "warnings": result.warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="*")
    parser.add_argument("--alias-mode", choices=("off", "auto", "required"),
                        default="off")
    parser.add_argument("--output")
    args = parser.parse_args()
    sources = args.sources or sorted(
        os.path.join(ROOT, "drivers", "test", name)
        for name in os.listdir(os.path.join(ROOT, "drivers", "test"))
        if name.endswith(".c"))
    reports = [build_driver_report(source, args.alias_mode) for source in sources]
    document = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reharness_commit": _git_head(),
        "alias_mode": args.alias_mode,
        "aggregate": {
            "drivers": len(reports),
            "strict_reliable": sum(report["strict_reliable"] for report in reports),
            "source_accesses": sum(
                report["access_accounting"].get("source_accesses", 0)
                for report in reports),
            "unsupported_accesses": sum(
                report["access_accounting"].get("unsupported", 0)
                for report in reports),
            "unsupported_control": sum(
                report["control_accounting"].get("unsupported", 0)
                for report in reports),
        },
        "drivers": reports,
    }
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
