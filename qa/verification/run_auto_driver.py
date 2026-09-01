#!/usr/bin/env python3
"""Run the one-path automatic driver generation and validation workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _bootstrap_import_paths() -> None:
    """Make the CLI independent of the caller's PYTHONPATH."""
    for path in (ROOT / "src", ROOT / "qa", ROOT / "qa" / "verification"):
        rendered = str(path)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)


_bootstrap_import_paths()

from auto_driver import AutoDriverError, normalize_input  # noqa: E402
from driver_profiles import (  # noqa: E402
    build_default_registry,
    load_profile_plugins,
)


def _emit(payload: dict[str, Any], path: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def _workflow_result(normalized: dict[str, Any], *, backend: str,
                     request: str, output_dir: str | None,
                     profile_registry: Any) -> dict[str, Any]:
    from langgraph_workflow.graph import run_workflow

    source = normalized["source"]["path"]
    workflow_request: dict[str, Any] = {
        "request": request,
        "source": source,
        "backend": backend,
        "mode": "experiment" if normalized.get("manifest") else "generation",
        "output_dir": output_dir,
    }
    if normalized.get("manifest"):
        workflow_request["experiment_manifest"] = normalized["manifest"]
    workflow = run_workflow(
        workflow_request, repo_root=ROOT, profile_registry=profile_registry)
    workflow_status = workflow.get("status")
    if workflow_status == "completed":
        status = "accepted"
        exit_code = 0
    elif workflow_status == "inconclusive":
        status = "inconclusive"
        exit_code = 3
    elif workflow_status in {"blocked", "failed"}:
        status = "failed"
        exit_code = 1
    else:
        status = "failed"
        exit_code = 1
    return {
        "status": status,
        "exit_code": exit_code,
        "normalized": normalized,
        "workflow": workflow,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", help="C source, multi-source descriptor, or schema-2 manifest")
    parser.add_argument("--profile", default=None, help="explicit runtime profile id")
    parser.add_argument("--profile-plugin", action="append", default=[],
                        help="Python module exposing register_profiles(registry); repeatable")
    parser.add_argument("--backend", default="linux")
    parser.add_argument("--request", default="generate and validate the driver")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="only normalize and write the manifest")
    args = parser.parse_args(argv)

    try:
        profile_registry = build_default_registry()
        load_profile_plugins(tuple(args.profile_plugin), profile_registry)
        normalized = normalize_input(
            args.driver, repo_root=ROOT, profile=args.profile,
            output_dir=args.output_dir, profile_registry=profile_registry)
    except (AutoDriverError, OSError, TypeError, ValueError, ImportError) as exc:
        payload = {"status": "invalid", "error": str(exc), "exit_code": 2}
        _emit(payload, args.json_output)
        return 2

    if args.dry_run:
        ready = normalized["status"] == "ready"
        payload = {"status": "ready" if ready else "inconclusive",
                   "exit_code": 0 if ready else 3, **normalized}
        _emit(payload, args.json_output)
        return int(payload["exit_code"])

    try:
        payload = _workflow_result(
            normalized, backend=args.backend, request=args.request,
            output_dir=args.output_dir, profile_registry=profile_registry)
    except Exception as exc:
        payload = {
            "status": "failed", "exit_code": 2,
            "normalized": normalized,
            "error": {"exception": type(exc).__name__, "message": str(exc)},
        }
    _emit(payload, args.json_output)
    return int(payload["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
