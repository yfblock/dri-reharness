#!/usr/bin/env python3
"""Compare original and candidate traces using the shared trace protocol.

This is intentionally a small adapter: loading files and reporting a stable
JSON result are the only policy here.  The manifest (or its ``trace`` section)
defines normalization, including any value mask.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from trace_protocol import (  # noqa: E402
    TraceProtocolError,
    compare_runs,
    load_trace,
)


def _config(path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TraceProtocolError("trace config must be a JSON object")
    trace = document.get("trace", document)
    if not isinstance(trace, dict):
        raise TraceProtocolError("trace config must be a JSON object")
    return trace


def compare_files(original_path: str | Path, candidate_path: str | Path,
                  *, config: dict[str, Any] | None = None,
                  context: int = 3) -> dict[str, Any]:
    original = load_trace(original_path, config=config)
    candidate = load_trace(candidate_path, config=config)
    result = compare_runs(original, candidate, context=context)
    return {
        "schema": 1,
        "equal": result.equal,
        "original": {
            "events": len(original.events),
            "return_code": original.return_code,
            "error": original.error,
        },
        "candidate": {
            "events": len(candidate.events),
            "return_code": candidate.return_code,
            "error": candidate.error,
        },
        "comparison": result.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", help="original-driver trace/run artifact")
    parser.add_argument("candidate", help="candidate-driver trace/run artifact")
    parser.add_argument(
        "--manifest", "--config", dest="config",
        help="manifest JSON or trace-section JSON defining normalization rules",
    )
    parser.add_argument("--context", type=int, default=3,
                        help="number of events retained around the first mismatch")
    args = parser.parse_args(argv)
    try:
        report = compare_files(args.original, args.candidate,
                               config=_config(args.config), context=args.context)
    except (OSError, ValueError, json.JSONDecodeError, TraceProtocolError) as error:
        report = {
            "schema": 1,
            "equal": False,
            "comparison": {
                "equal": False,
                "reason": "infrastructure_error",
                "error": str(error),
            },
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("equal") else 1


if __name__ == "__main__":
    sys.exit(main())
