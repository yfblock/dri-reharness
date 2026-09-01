from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run the reharness LangGraph workflow")
    parser.add_argument("source", help="C source or multi-source driver manifest")
    parser.add_argument("--experiment-manifest", default=None)
    parser.add_argument("--backend", default="linux")
    parser.add_argument("--mode", choices=["analysis", "generation", "experiment"],
                        default=None)
    parser.add_argument("--request", default="analyze and run the driver pipeline")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    request = {
        "request": args.request,
        "source": args.source,
        "experiment_manifest": args.experiment_manifest,
        "backend": args.backend,
        "mode": args.mode,
    }
    if args.output_dir is not None:
        request["output_dir"] = args.output_dir
    try:
        from .graph import run_workflow
    except ModuleNotFoundError as exc:
        if exc.name == "langgraph":
            parser.error(
                "LangGraph is not installed; run: "
                "python3 -m pip install -r requirements-langgraph.txt")
        raise
    result = run_workflow(request, repo_root=root)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("status") in {"completed", "analysis_complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
