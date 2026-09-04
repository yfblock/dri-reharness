#!/usr/bin/env python3
"""Merge the bare-metal/Linux rerun record into the main cadence record.

The harness trials of the first run and the bare-metal/Linux trials of the
second run (new prompt, deterministic normalizations, corrected
runtime-trace semantics) are per-backend k=5 samples on the same pinned
extraction; this merges them into one record whose trials carry all three
backends, keeping each backend's own sample provenance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "research" / "experiments" / "results"
        / "gpio-cadence-repeated-trials.json")
BL = (ROOT / "research" / "experiments" / "results"
      / "gpio-cadence-bl-repeated-trials.json")


def main() -> int:
    main_d = json.loads(MAIN.read_text(encoding="utf-8"))
    bl_d = json.loads(BL.read_text(encoding="utf-8"))
    bl_by_trial = {t["trial"]: t for t in bl_d.get("trials", [])}
    for t in main_d.get("trials", []):
        bl_t = bl_by_trial.get(t["trial"])
        if not bl_t:
            continue
        for backend, row in bl_t.get("backends", {}).items():
            # the rerun replaces the first run's bare-metal/Linux rows: it
            # measured the same protocol plus three deterministic
            # normalizations, under the corrected runtime-trace semantics
            t["backends"][backend] = row
    main_d["description"] = (
        "Repeated constrained-pipeline trials on gpio-cadence; per backend, "
        "first pass (compile repair disabled), post compile-repair, and "
        "post receipt-repair gate check states on the same candidate. "
        "Harness trials from the 2026-09-03 run; bare-metal and Linux "
        "trials from the 2026-09-04 rerun (runner-format prompt, "
        "windowed-stub / driver-main / MODULE_LICENSE deterministic "
        "normalizations, runtime-trace field populated for all backends); "
        "per-backend k=5 samples on the same pinned extraction.")
    main_d["runs"] = [
        {"date": "2026-09-03", "backends": ["harness"],
         "record": "gpio-cadence-repeated-trials.json (pre-merge)"},
        {"date": "2026-09-04", "backends": ["baremetal", "linux"],
         "record": "gpio-cadence-bl-repeated-trials.json"},
    ]
    MAIN.write_text(json.dumps(main_d, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(f"merged {len(bl_d.get('trials', []))} rerun trials -> {MAIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
