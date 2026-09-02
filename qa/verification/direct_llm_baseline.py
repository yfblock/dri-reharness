#!/usr/bin/env python3
"""Scoped direct-LLM translation baseline for the DesignWare case study.

Feeds the raw pinned Linux driver source (core + header, no evidence
contract, no receipts, no anchors) to the same LLM endpoint/model used by
the constrained pipeline, with a minimal ``translate this driver'' prompt,
then runs the *identical* verification gate and the 18-item artifact
checklist pattern items over the candidate.  This isolates the effect of
the evidence boundary: same model, same gate, different input contract.

Output: research/experiments/results/direct-llm-baseline.json
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "qa"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

SOURCES = [
    ROOT / "vendor" / "linux" / "drivers" / "spi" / "spi-dw-core.c",
    ROOT / "vendor" / "linux" / "drivers" / "spi" / "spi-dw.h",
]
DEFAULT_OUT = (ROOT / "research" / "experiments" / "results"
               / "direct-llm-baseline.json")

PROMPT = """You are translating a Linux kernel driver to a host-runnable C
test harness. Below is the complete driver source. Produce a single C file
that implements the driver's device behavior (register accesses, interrupt
handling, SPI transfers) against these host primitives, which you must also
define:

    uint32_t harness_read32(uintptr_t addr);
    void harness_write32(uint32_t value, uintptr_t addr);

along with 8/16-bit variants, a simple MMIO device model, and a main()
that exercises the driver. Reply with one fenced C code block only.

===== DRIVER SOURCE =====
"""


def _extract_c_block(raw: str) -> str:
    fence = re.search(r"```c(?:\s|\n)(.*?)```", raw, re.S)
    if fence is None:
        fence = re.search(r"```(?:\s|\n)(.*?)```", raw, re.S)
    if fence is None:
        raise RuntimeError("no fenced C block in response")
    return fence.group(1).strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(
        ROOT / "benchmarks" / "drivers" / "multisource" / "dw-apb-ssi.json"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--candidate", default=None,
                    help="reuse a previously generated candidate .c")
    ap.add_argument("--rounds", type=int, default=1,
                    help="independent samples to draw (default 1)")
    args = ap.parse_args()

    from langchain_bridge import load_langchain_settings, call_langchain

    settings = load_langchain_settings()
    source_text = "\n\n".join(
        f"/* ===== {p.name} ===== */\n" + p.read_text(encoding="utf-8")
        for p in SOURCES)

    checklist = importlib.import_module("dw_apb_ssi_checklist")
    gate = importlib.import_module("gate_mutation_study")

    rounds = []
    for i in range(max(1, args.rounds)):
        if args.candidate and i == 0:
            code = Path(args.candidate).read_text(encoding="utf-8")
            raw_len = len(code)
            t0 = 0.0
        else:
            prompt = PROMPT + source_text
            t0 = time.time()
            raw = call_langchain(prompt, timeout=600)
            gen_seconds = time.time() - t0
            code = _extract_c_block(raw)
            raw_len = len(raw)
        rounds.append(_evaluate(code, args, gate, checklist,
                                sample=i, prompt_chars=len(PROMPT)
                                + len(source_text),
                                response_chars=raw_len,
                                gen_seconds=(time.time() - t0)))
        print(f"round {i}: rejected={rounds[-1]['gate']['rejected']} "
              f"({rounds[-1]['gate'].get('first_failing_check')})")

    report = {
        "schema": 1,
        "description": ("Direct-LLM baseline: raw driver source in, same "
                        "gate and checklist applied, no evidence contract"),
        "model": settings.model,
        "temperature": settings.temperature,
        "base_url_host": (settings.base_url or "").split("//")[-1].split("/")[0],
        "prompt_sources": [str(p.relative_to(ROOT)) for p in SOURCES],
        "prompt_source_chars": len(source_text),
        "rounds": rounds,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    cand_dir = Path(args.out).with_suffix("")
    cand_dir.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rounds):
        (cand_dir / f"candidate-{i}.c").write_text(
            r["candidate_c"], encoding="utf-8")
    print(f"baseline report -> {args.out}")
    return 0


def _evaluate(code: str, args, gate, checklist, *, sample: int,
              prompt_chars: int, response_chars: int,
              gen_seconds: float) -> dict:
    print("extracting contract for the gate (cached)...")
    res = gate._load_extraction(args.manifest)
    workdir = ROOT / "artifacts" / "cache" / "direct-llm" / f"sample-{sample}"
    try:
        gr = gate._run_gate(res, code, workdir)
        gate_result = gate._verdict(gr)
    except Exception as exc:
        gate_result = {"rejected": True,
                       "first_failing_check": "gate_exception",
                       "exception": str(exc)[-500:]}
    # 14 pattern items of the 18-item checklist (5..18), harness backend only
    items = {}
    for name, backends, fn in checklist.ITEMS:
        if fn is None or "harness" not in backends:
            continue
        ok, ev = fn("harness")
        items[name] = {"pass": bool(ok), "evidence": ev}
    pattern_passed = sum(1 for v in items.values() if v["pass"])
    return {
        "sample": sample,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
        "generation_seconds": round(gen_seconds, 1),
        "candidate_c": code,
        "gate": gate_result,
        "checklist_patterns_total": len(items),
        "checklist_patterns_passed": pattern_passed,
        "checklist_items": items,
    }


if __name__ == "__main__":
    raise SystemExit(main())
