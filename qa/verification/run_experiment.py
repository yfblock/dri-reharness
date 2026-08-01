#!/usr/bin/env python3
"""Run one manifest-driven experiment with explicitly supplied adapters.

The command intentionally does not infer a device or parse subprocess output.
Production integrations provide a Python module exposing ``build_adapters``;
tests can inject deterministic fakes through the same interface.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from experiment_manifest import load_manifest  # noqa: E402
from experiment_runner import ExperimentRunner  # noqa: E402


def run_experiment(manifest_path: str | Path, adapters: Any,
                   *, output_dir: str | Path | None = None) -> Any:
    """Execute a manifest using an object or mapping of five adapters."""
    if isinstance(adapters, dict):
        runner = ExperimentRunner(output_root=output_dir or ROOT / "artifacts/experiments", **adapters)
    else:
        runner = ExperimentRunner(
            extractor=adapters.extractor, pi=adapters.pi,
            compiler=adapters.compiler, runtime=adapters.runtime,
            comparator=adapters.comparator,
            contract=getattr(adapters, "contract", None),
            output_root=output_dir or ROOT / "artifacts/experiments",
        )
    return runner.run(load_manifest(manifest_path, repo_root=ROOT), output_dir=output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, help="experiment artifact directory")
    parser.add_argument("--adapter-module", required=True,
                        help="module exposing build_adapters(manifest) or build_adapters()")
    args = parser.parse_args(argv)
    module = importlib.import_module(args.adapter_module)
    factory = getattr(module, "build_adapters", None)
    if not callable(factory):
        parser.error("adapter module must expose build_adapters")
    try:
        manifest = load_manifest(args.manifest, repo_root=ROOT)
    except Exception as error:
        print(json.dumps({"accepted": False, "status": "manifest_error",
                          "error": str(error)}, sort_keys=True))
        return 1
    try:
        adapters = factory(manifest)
    except TypeError:
        try:
            adapters = factory()
        except Exception as error:
            print(json.dumps({"accepted": False, "status": "infrastructure_error",
                              "error": str(error)}, sort_keys=True))
            return 1
    except Exception as error:
        print(json.dumps({"accepted": False, "status": "manifest_error",
                          "error": str(error)}, sort_keys=True))
        return 1
    result = run_experiment(args.manifest, adapters, output_dir=args.output)
    print(json.dumps({"accepted": result.accepted, "status": result.status,
                      "output_dir": str(result.output_dir),
                      "records": len(result.records)}, sort_keys=True))
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
