#!/usr/bin/env python3
"""Run experiment manifests through the V2 LangGraph closed loop.

Usage:
  run_v2_experiment.py MANIFEST.json [--output-root DIR] [--max-repair N]
  (单驱动单实验；多驱动用 shell 循环组合)

Each manifest is executed by ``langgraph_workflow.experiment_v2_graph``:
the original module is built with [rhcov] probes, booted in QEMU (baseline),
a candidate is synthesized by the LangChain bridge, compiled, booted
again (candidate), and the outcome plus whole-driver function coverage is
written to ``<output-root>/<name>/experiment.json``.

Exit code is 0 only when every experiment is accepted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _manifest_document(manifest: Path) -> dict:
    with open(manifest, encoding="utf-8") as fh:
        return json.load(fh)


def run_one(manifest: Path, *, output_root: Path, max_repair: int,
            llm_bridge_factory) -> dict:
    from langgraph_workflow.experiment_v2_graph import (
        build_experiment_v2, _reset_rc)

    document = _manifest_document(manifest)
    name = str(document.get("name") or manifest.stem)
    source = str((document.get("source") or {}).get("path") or "")
    if not source:
        return {"name": name, "status": "failed",
                "error": "manifest has no source.path"}
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    if not source_path.is_file():
        return {"name": name, "status": "failed",
                "error": f"source not found: {source_path}"}

    out = output_root / name
    _reset_rc()
    graph = build_experiment_v2(
        driver_source=str(source_path),
        driver_name=name,
        manifest_path=str(manifest),
        llm_bridge=llm_bridge_factory(source_path),
        output_root=str(out),
        max_repair=max_repair)
    final = graph.invoke({}, config={"recursion_limit": 50})

    record_path = out / "experiment.json"
    record = json.loads(record_path.read_text()) if record_path.is_file() else {}
    result = {
        "name": name,
        "status": final.get("status") if final else "failed",
        "accepted": bool(final.get("accepted")) if final else False,
        "baseline_coverage": record.get("baseline_coverage"),
        "candidate_coverage": record.get("candidate_coverage"),
        "repair_count": record.get("repair_count"),
        "output_dir": str(out),
    }
    if final is None:
        result["error"] = "graph returned no final state"
    return result



def main(argv: list[str] | None = None) -> int:
    """One manifest, one closed-loop experiment; exit 0 iff accepted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path,
                        default=ROOT / "artifacts/experiments-v2")
    parser.add_argument("--max-repair", type=int, default=3)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))
    from langchain_bridge import LangChainBridge, load_langchain_settings
    if not load_langchain_settings(repo_root=ROOT).api_key:
        raise SystemExit("config.toml [llm] api_key 未设置（LLM-only，无降级桥）")

    output_root = (args.output_root if args.output_root.is_absolute()
                   else (ROOT / args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = (args.manifest if args.manifest.is_absolute()
                else ROOT / args.manifest)
    if not manifest.is_file():
        raise SystemExit(f"manifest not found: {manifest}")

    result = run_one(manifest, output_root=output_root,
                     max_repair=args.max_repair,
                     llm_bridge_factory=lambda src: LangChainBridge(
                         repo_root=ROOT))
    cov_b = (result.get("baseline_coverage") or {})
    cov_c = (result.get("candidate_coverage") or {})
    print(f"{result['name']:14} {result['status']:9} "
          f"baseline_cov={cov_b.get('covered_count')}/{cov_b.get('total')} "
          f"candidate_cov={cov_c.get('covered_count')}/{cov_c.get('total')} "
          f"repairs={result.get('repair_count')}")
    return 0 if result.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
