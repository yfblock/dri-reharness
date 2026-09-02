#!/usr/bin/env python3
"""Record machine-checkable metadata for an LLM generation run.

Writes research/experiments/results/llm-run-metadata.json describing the
model, sampling parameters, and per-artifact digests for the DesignWare
APB SSI regeneration, so the paper's LLM-case metadata claim is backed by
a versioned record rather than prose.  API keys are never recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

OUT = (ROOT / "research" / "experiments" / "results"
       / "llm-run-metadata.json")
DW = ROOT / "examples" / "dw-apb-ssi"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--temperature", type=float, required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--artifacts", nargs="*", default=[
        "dw_spi_harness.c", "dw_spi_harness.h", "dw_spi_baremetal.c",
        "dw_spi_baremetal.h", "dw_apb_ssi_linux.c", "dw_apb_ssi_linux.h",
        "dw_spi_rust_baremetal.rs"])
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    from langchain_bridge import load_langchain_settings
    settings = load_langchain_settings()

    artifacts = {}
    for name in args.artifacts:
        p = DW / name
        if p.is_file():
            artifacts[name] = {"sha256": _sha(p), "bytes": p.stat().st_size}
    report = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": args.purpose,
        "model": args.model,
        "model_from_settings": settings.model,
        "temperature": args.temperature,
        "base_url_host": (settings.base_url or ""
                          ).split("//")[-1].split("/")[0],
        "timeout_s": settings.timeout,
        "note": args.note,
        "artifacts": artifacts,
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
