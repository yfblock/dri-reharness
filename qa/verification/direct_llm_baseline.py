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
    ap.add_argument("--compile-repair-rounds", type=int, default=0,
                    help="compile-diagnostic repair budget for the "
                         "baseline candidate, matching the constrained "
                         "pipeline's own budget (default 0: none, the "
                         "original protocol)")
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
            # the private endpoint intermittently returns empty or
            # fenceless bodies on long prompts; retry the ENDPOINT
            # bounded times before recording the round as failed
            code = None
            raw = ""
            for _gen_attempt in range(4):
                try:
                    raw = call_langchain(prompt, timeout=600)
                    code = _extract_c_block(raw)
                    break
                except RuntimeError:
                    continue
            gen_seconds = time.time() - t0
            if code is None:
                rounds.append({
                    "sample": i,
                    "error": ("no fenced C block in response after "
                              "bounded retries"),
                    "response_chars": len(raw),
                    "gen_seconds": round(gen_seconds, 1)})
                continue
            raw_len = len(raw)
        rounds.append(_evaluate(code, args, gate, checklist,
                                sample=i, prompt_chars=len(PROMPT)
                                + len(source_text),
                                response_chars=raw_len,
                                gen_seconds=(time.time() - t0)))
        r = rounds[-1]
        if args.compile_repair_rounds and \
                r["gate"]["first_failing_check"] == "compile":
            workdir = (ROOT / "artifacts" / "cache" / "direct-llm"
                       / f"sample-{i}")
            workdir.mkdir(parents=True, exist_ok=True)
            fixed, used, ok = _compile_repair(
                code, workdir, args.compile_repair_rounds)
            r["compile_repair_rounds"] = used
            r["compile_repair_compiled"] = ok
            r["gate_pre_repair"] = r["gate"]
            r["gate"] = gate._verdict(gate._run_gate(
                gate._load_extraction(args.manifest), fixed, workdir))
            r["candidate_c"] = fixed
        print(f"round {i}: rejected={r['gate']['rejected']} "
              f"({r['gate'].get('first_failing_check')})")

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
        if "candidate_c" in r:
            (cand_dir / f"candidate-{i}.c").write_text(
                r["candidate_c"], encoding="utf-8")
    print(f"baseline report -> {args.out}")
    return 0


def _failing_regions(code: str, stderr: str, max_regions: int = 3):
    """Top-level (column-0) regions of the file the diagnostics point at.

    Mirrors the constrained pipeline's bounded per-part echo (_repair_compile
    rewrites only the failing PART, not the whole driver): the baseline
    candidate is one file, so the failing top-level definition(s) are the
    echo unit.  Returns [(start_line, end_line)] 0-based, end exclusive.
    """
    import re as _re
    lines = code.split("\n")
    err_lines = [int(m.group(1)) - 1 for m in _re.finditer(
        r"candidate\.c:(\d+):\d+:", stderr)]
    if not err_lines:
        return []
    # top-level boundaries: lines starting at column 0
    tops = [i for i, l in enumerate(lines) if l and not l[0].isspace()]
    tops.append(len(lines))
    regions = []
    for ln in err_lines:
        idx = max(i for i, t in enumerate(tops) if t <= ln)
        lo, hi = tops[idx], tops[idx + 1] if idx + 1 < len(tops) else len(lines)
        if regions and lo <= regions[-1][1]:
            regions[-1] = (regions[-1][0], max(hi, regions[-1][1]))
        elif len(regions) < max_regions:
            regions.append((lo, hi))
    return regions


def _compile_repair(code: str, workdir: Path, max_rounds: int) -> tuple[str, int]:
    """Give the baseline the same compile-diagnostic repair budget the
    constrained pipeline grants its own candidates (_repair_compile in
    backends/pipeline.py): probe-compile, feed the exact cc diagnostics
    back, bounded rounds, and echo ONLY the failing region — the pipeline
    rewrites failing parts, not the whole driver, and a whole-file echo
    exceeds what the endpoint serves."""
    import subprocess
    from langchain_bridge import call_langchain
    cpath = workdir / "candidate.c"
    binp = workdir / "candidate.bin"
    rounds_used = 0
    for r in range(max_rounds):
        cpath.write_text(code, encoding="utf-8")
        p = subprocess.run(["cc", "-o", str(binp), str(cpath)],
                           capture_output=True, text=True)
        if p.returncode == 0:
            break
        rounds_used = r + 1
        regions = _failing_regions(code, p.stderr)
        if not regions:
            break  # no per-line errors (e.g. link-only failure): no region
                   # to echo; the round budget is not spent on a hang
        new_code = code
        changed = False
        # fix regions bottom-up so earlier splices stay valid
        for lo, hi in sorted(regions, reverse=True):
            region = "\n".join(code.split("\n")[lo:hi])
            prompt = (
                "You are fixing compile errors in one region of a host C "
                "program (dialect: userspace program with main()). Fix ONLY "
                "what the compiler reports; keep structure, register "
                "accesses, and behavior. Return the COMPLETE fixed REGION "
                "in a single ```c fenced block, nothing else.\n\n"
                "===== COMPILER DIAGNOSTICS =====\n"
                + p.stderr[-4000:]
                + "\n\n===== REGION (lines "
                + f"{lo + 1}-{hi}) =====\n```c\n" + region + "\n```\n")
            raw = ""
            for _fix_attempt in range(3):
                try:
                    raw = call_langchain(prompt, timeout=600)
                    break
                except Exception:
                    continue
            try:
                fixed = _extract_c_block(raw) if raw else None
            except RuntimeError:
                fixed = None
            if fixed:
                ls = new_code.split("\n")
                new_code = "\n".join(ls[:lo] + fixed.rstrip("\n").split("\n")
                                     + ls[hi:])
                changed = True
        if changed:
            code = new_code
    cpath.write_text(code, encoding="utf-8")
    p = subprocess.run(["cc", "-o", str(binp), str(cpath)],
                       capture_output=True, text=True)
    return code, rounds_used, p.returncode == 0


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
