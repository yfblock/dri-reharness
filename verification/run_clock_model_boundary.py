#!/usr/bin/env python3
"""Record executable Highbank evidence and the Visconti rejection boundary."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor import ExtractorConfig, extract_ris  # noqa: E402
from generator.linux import analyze_clock_source_model  # noqa: E402
from verification.clock_arithmetic_oracle import verify_highbank  # noqa: E402


def _git_rev(path: str) -> str:
    run = subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _analysis(name: str) -> dict:
    source = os.path.join(ROOT, "drivers", "test", f"{name}.c")
    result = extract_ris(ExtractorConfig(source=source))
    analysis = analyze_clock_source_model(
        result.facts, name.replace("-", "_") + "_priv")
    analysis["source_sha256"] = _sha256(source)
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "experiments", "results",
                             "clock-model-boundary.json"))
    args = parser.parse_args()

    highbank = _analysis("clk-highbank")
    visconti = _analysis("pll")
    oracle = verify_highbank()
    if not highbank["supported"]:
        raise AssertionError(f"Highbank unexpectedly rejected: {highbank['reasons']}")
    if visconti["supported"] or not visconti["reasons"]:
        raise AssertionError("Visconti must expose a non-empty conservative boundary")
    required = {"pll_base", "rate_table", "lock"}
    reason_text = " ".join(visconti["reasons"])
    missing = sorted(field for field in required if field not in reason_text)
    if missing:
        raise AssertionError(f"Visconti boundary lost fields: {missing}")

    report = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {
            "reharness_commit": _git_rev(ROOT),
            "linux_commit": _git_rev(os.path.join(ROOT, "linux")),
        },
        "highbank": {
            "source_model": highbank,
            "arithmetic_oracle": oracle,
        },
        "visconti_pll": {
            "source_model": visconti,
            "boundary_expected": True,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print("CLOCK_MODEL_BOUNDARY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
