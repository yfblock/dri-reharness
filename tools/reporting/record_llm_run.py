#!/usr/bin/env python3
"""Record LLM-run metadata for the generated backend artifacts.

The paper's verification story requires that the emission model, endpoint
(host only, never credentials), sampling parameters, and per-artifact repair
effort are recorded rather than left as "project configuration".  This tool
reads the active LangChain settings plus the versioned repair log and writes
``research/experiments/results/llm-run-metadata.json``.  API keys are
deliberately never read into the output.

Usage: record_llm_run.py [--model M] [--temperature T] [--trial N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parents[2]
ROOT = HERE
sys.path.insert(0, str(ROOT / "src"))

OUT = (ROOT / "research" / "experiments" / "results"
       / "llm-run-metadata.json")
REPAIR_LOG = (ROOT / "research" / "experiments" / "results"
              / "artifact-repair-log.json")

ARTIFACTS = {
    "harness": "examples/dw-apb-ssi/dw_spi_harness.c",
    "baremetal": "examples/dw-apb-ssi/dw_spi_baremetal.c",
    "linux": "examples/dw-apb-ssi/dw_apb_ssi_linux.c",
    "rust": "examples/dw-apb-ssi/dw_spi_rust_baremetal.rs",
}


def _host(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return urlparse(base_url).hostname


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None,
                    help="override the configured model identifier")
    ap.add_argument("--temperature", type=float, default=None,
                    help="override the configured sampling temperature")
    ap.add_argument("--trial", type=int, default=1,
                    help="trial index for this regeneration cycle")
    args = ap.parse_args()

    from langchain_bridge import load_langchain_settings
    settings = load_langchain_settings()
    model = args.model or settings.model
    temperature = (args.temperature if args.temperature is not None
                   else settings.temperature)

    backends = {}
    for backend, rel in ARTIFACTS.items():
        path = ROOT / rel
        row = {"artifact": rel,
               "sha256_16": (hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                            if path.is_file() else None)}
        if REPAIR_LOG.is_file():
            log = json.loads(REPAIR_LOG.read_text(encoding="utf-8"))
            runs = [r for r in log.get("runs", [])
                    if r.get("backend") == backend]
            last = runs[-1] if runs else None
            if last:
                row["repair_rounds"] = len(last.get("rounds", [])) - 1
                row["repair_compile_ok"] = bool(last.get("compile_ok"))
                row["repair_model"] = last.get("model")
            lowering = [r for r in runs if r.get("mode") == "lowering"]
            if lowering:
                lrow = lowering[-1]
                row["lowering_rounds"] = len(lrow.get("rounds", [])) - 1
                row["lowering_complete"] = bool(lrow.get("lowering_complete"))
        backends[backend] = row

    document = {
        "schema": 1,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model,
        "model_family": model.split("-")[0] if model else None,
        "endpoint_host": _host(settings.base_url),
        "temperature": temperature,
        "api_key_recorded": False,
        "generation_command": "python3 -m extractor gen -s <manifest> -b "
                              "<backend> --pair",
        "trial": args.trial,
        "backends": backends,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"recorded {model} @{temperature} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
