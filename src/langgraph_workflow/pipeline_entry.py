"""Pipeline entry: the LangGraph paths are the only execution backend.

Generation runs through the shared backend pipeline; experiments run
through the V2 closed-loop graph (``experiment_v2_graph``) via the manifest runner.
Both return the JSON contract consumed by the workflow's ``finalize``
node: ``accepted/status/output_dir`` (plus per-experiment coverage in the
record written to ``<output_dir>/<name>/experiment.json``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping


from backends.pipeline import _transaction_source_paths, run_backend_pipeline
from .tools import _pipeline_failure


def run_pipeline_backend(request: Mapping[str, Any],
                         analysis: Mapping[str, Any], *,
                         repo_root: str | Path) -> dict[str, Any]:
    """Dispatch the pipeline run to the LangGraph execution graphs."""
    mode = request["mode"]
    if mode == "generation":
        return _run_generation_via_graph(request, analysis, repo_root=repo_root)
    if mode == "experiment":
        return _run_experiment_via_v2(request, repo_root=repo_root)
    output_dir = Path(request["output_dir"]) / "pipeline"
    output_dir.mkdir(parents=True, exist_ok=True)
    return {"accepted": True, "status": "analysis_only",
            "output_dir": str(output_dir)}


def _run_experiment_via_v2(request: Mapping[str, Any], *,
                           repo_root: str | Path) -> dict[str, Any]:
    """Experiment mode on the V2 closed-loop graph."""
    root = Path(repo_root).resolve()
    output_dir = Path(request["output_dir"]) / "pipeline"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = request.get("experiment_manifest")
    if not manifest_path:
        raise ValueError("experiment mode requires experiment_manifest")
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = root / manifest
    if not manifest.is_file():
        return _pipeline_failure(
            FileNotFoundError(f"experiment manifest not found: {manifest}"),
            stage="manifest",
        )

    for entry in (str(root / "src"), str(root / "qa"),
                  str(root / "qa" / "verification")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    try:
        try:
            from verification.run_v2_experiment import run_one
        except ImportError:
            from langchain_bridge import LangChainBridge
        from run_v2_experiment import run_one

        with open(manifest, encoding="utf-8") as fh:
            name = str(json.load(fh).get("name") or manifest.stem)
        result = run_one(manifest, output_root=output_dir.parent,
                         max_repair=3,
                         llm_bridge_factory=lambda source: LangChainBridge(repo_root=root))
        record = {"accepted": result.get("accepted", False),
                  "status": result.get("status", "failed"),
                  "output_dir": result.get("output_dir", str(output_dir)),
                  "baseline_coverage": result.get("baseline_coverage"),
                  "candidate_coverage": result.get("candidate_coverage"),
                  "repair_count": result.get("repair_count")}
        if result.get("error"):
            record["failure"] = _pipeline_failure(
                RuntimeError(result["error"]), stage="experiment")
        return record
    except Exception as exc:
        return _pipeline_failure(exc, stage="experiment")


def _run_generation_via_graph(request, analysis, *, repo_root):
    """Generation via the shared backend pipeline (four backends + full verification)."""
    root = Path(repo_root).resolve()
    output_dir = Path(request["output_dir"]) / "pipeline"
    output_dir.mkdir(parents=True, exist_ok=True)

    for entry in (str(root / "src"), str(root / "qa"),
                  str(root / "qa" / "verification")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from extractor import ExtractorConfig, extract_ris

    try:
        result = extract_ris(ExtractorConfig(
            source=request["source"], driver_name=analysis["driver"]))
        formal = getattr(result, "formal", None)
        if isinstance(formal, dict):
            _attach_transaction_validation(root, formal, request, analysis)
    except Exception as exc:
        return {"accepted": False, "status": "failed",
                "output_dir": str(output_dir),
                "failure": _pipeline_failure(exc, stage="extraction")}

    try:
        payload = run_backend_pipeline(result, str(output_dir),
                                       request["source"])
    except Exception as exc:
        return {"accepted": False, "status": "failed",
                "output_dir": str(output_dir),
                "failure": _pipeline_failure(exc, stage="generation")}
    return {
        "accepted": payload["accepted"],
        "status": payload["status"],
        "output_dir": str(output_dir),
        "result": payload,
    }



def _attach_transaction_validation(root: Path, formal: dict[str, Any],
                                   request: Mapping[str, Any],
                                   analysis: Mapping[str, Any]) -> None:
    """Mirror the legacy transaction-IR oracle embedding step."""
    from backends.oracles.transaction_ir_oracle import verify_transaction_sources

    source_files = [Path(item) for item in
                     _transaction_source_paths(request["source"])]
    formal.setdefault("metadata", {})["transaction_validation"] = \
        verify_transaction_sources(
            formal, [str(item) for item in source_files])


