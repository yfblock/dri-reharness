#!/usr/bin/env python3
"""Executable arithmetic oracle for generated clk-highbank callbacks.

The verifier compiles the callback bodies taken from the generated Linux C
against a tiny userspace MMIO shim, then compares their outputs with an
independent Python reference model.  Mutation checks deliberately corrupt
three distinct formulas and require the oracle to observe a mismatch.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HB_PLL_LOCK_500 = 0x20000000
HB_PLL_LOCK = 0x10000000
HB_PLL_DIVF_SHIFT = 20
HB_PLL_DIVF_MASK = 0x0FF00000
HB_PLL_DIVQ_SHIFT = 16
HB_PLL_DIVQ_MASK = 0x00070000
HB_PLL_EXT_BYPASS = 0x2
HB_PLL_EXT_ENA = 0x1
HB_PLL_VCO_MIN_FREQ = 2_133_000_000
HB_PLL_MAX_FREQ = HB_PLL_VCO_MIN_FREQ
HB_PLL_MIN_FREQ = HB_PLL_VCO_MIN_FREQ // 64
HB_A9_BCLK_DIV_MASK = 0x6
HB_A9_BCLK_DIV_SHIFT = 1
HB_A9_PCLK_DIV = 0x1
EINVAL = 22


def generated_highbank_code() -> str:
    from extractor import ExtractorConfig, extract_ris
    from extractor.spec import default_bind
    from generator import linux as linux_gen

    source = os.path.join(ROOT, "drivers", "test", "clk-highbank.c")
    result = extract_ris(ExtractorConfig(source=source))
    return linux_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "linux"), result.facts)


def _extract_function(code: str, name: str) -> str:
    from generator.linux import _source_function

    function = _source_function(code, name)
    if function is None:
        raise AssertionError(f"generated callback missing: {name}")
    return function["text"]


def _hb_macros(code: str) -> str:
    lines = []
    for line in code.splitlines():
        if line.startswith("#define HB_"):
            lines.append(line)
    if not lines:
        raise AssertionError("generated Highbank constants are missing")
    return "\n".join(lines)


_CALLBACKS = (
    "clk_pll_calc",
    "clk_pll_recalc_rate",
    "clk_cpu_periphclk_recalc_rate",
    "clk_cpu_a9bclk_recalc_rate",
    "clk_periclk_recalc_rate",
    "clk_pll_determine_rate",
    "clk_periclk_determine_rate",
    "clk_periclk_set_rate",
    "clk_pll_set_rate",
)


def _standalone_source(code: str) -> str:
    callbacks = "\n\n".join(_extract_function(code, name) for name in _CALLBACKS)
    return f"""
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint32_t u32;
#define __iomem
#define EINVAL 22
#define container_of(ptr, type, member) \\
    ((type *)((char *)(ptr) - offsetof(type, member)))

struct clk_hw {{ int unused; }};
struct clk_rate_request {{
    unsigned long rate;
    unsigned long best_parent_rate;
}};
struct clk_highbank_priv {{
    void *base;
    struct clk_hw hw;
}};

static inline u32 readl(const void *address)
{{
    return *(const u32 *)address;
}}

static inline void writel(u32 value, void *address)
{{
    *(u32 *)address = value;
}}

{_hb_macros(code)}

{callbacks}

int main(int argc, char **argv)
{{
    unsigned long mode, reg_value, arg1, arg2;
    struct clk_highbank_priv priv;
    struct clk_rate_request req;
    u32 reg;
    unsigned long result = 0;
    long rc = 0;

    if (argc != 5)
        return 2;
    mode = strtoul(argv[1], NULL, 0);
    reg_value = strtoul(argv[2], NULL, 0);
    arg1 = strtoul(argv[3], NULL, 0);
    arg2 = strtoul(argv[4], NULL, 0);
    reg = (u32)reg_value;
    priv.base = &reg;

    switch (mode) {{
    case 1:
        result = clk_pll_recalc_rate(&priv.hw, arg1);
        break;
    case 2:
        result = clk_cpu_periphclk_recalc_rate(&priv.hw, arg1);
        break;
    case 3:
        result = clk_cpu_a9bclk_recalc_rate(&priv.hw, arg1);
        break;
    case 4:
        result = clk_periclk_recalc_rate(&priv.hw, arg1);
        break;
    case 5:
        req.rate = arg1;
        req.best_parent_rate = arg2;
        rc = clk_pll_determine_rate(&priv.hw, &req);
        result = req.rate;
        break;
    case 6:
        req.rate = arg1;
        req.best_parent_rate = arg2;
        rc = clk_periclk_determine_rate(&priv.hw, &req);
        result = req.rate;
        break;
    case 7:
        rc = clk_periclk_set_rate(&priv.hw, arg1, arg2);
        break;
    case 8:
        rc = clk_pll_set_rate(&priv.hw, arg1, arg2);
        break;
    default:
        return 3;
    }}
    printf("%ld %lu %u\\n", rc, result, reg);
    return 0;
}}
"""


def _compile(code: str, directory: str, name: str) -> str:
    cc = shutil.which("cc")
    if not cc:
        raise RuntimeError("C compiler not found")
    source = os.path.join(directory, f"{name}.c")
    binary = os.path.join(directory, name)
    with open(source, "w", encoding="utf-8") as handle:
        handle.write(_standalone_source(code))
    run = subprocess.run(
        [cc, "-std=gnu11", "-Wall", "-Werror", "-Wno-unused-parameter",
         "-o", binary, source], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return binary


def _run(binary: str, mode: int, reg: int, arg1: int, arg2: int = 0
         ) -> tuple[int, int, int]:
    run = subprocess.run(
        [binary, str(mode), str(reg), str(arg1), str(arg2)],
        capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    rc, result, final_reg = run.stdout.strip().split()
    return int(rc), int(result), int(final_reg)


def _pll_calc(rate: int, reference: int) -> tuple[int, int]:
    rate = max(HB_PLL_MIN_FREQ, min(rate, HB_PLL_MAX_FREQ))
    divq = 1
    while divq <= 6 and rate * (1 << divq) < HB_PLL_VCO_MIN_FREQ:
        divq += 1
    vco = rate * (1 << divq)
    divf = (vco + reference // 2) // reference
    return divq, divf - 1


def _expected(case: tuple[int, int, int, int]) -> tuple[int, int, int]:
    mode, reg, arg1, arg2 = case
    if mode == 1:
        if reg & HB_PLL_EXT_BYPASS:
            return 0, arg1, reg
        divf = (reg & HB_PLL_DIVF_MASK) >> HB_PLL_DIVF_SHIFT
        divq = (reg & HB_PLL_DIVQ_MASK) >> HB_PLL_DIVQ_SHIFT
        return 0, arg1 * (divf + 1) // (1 << divq), reg
    if mode == 2:
        divisor = 8 if reg & HB_A9_PCLK_DIV else 4
        return 0, arg1 // divisor, reg
    if mode == 3:
        divisor = ((reg & HB_A9_BCLK_DIV_MASK) >> HB_A9_BCLK_DIV_SHIFT) + 2
        return 0, arg1 // divisor, reg
    if mode == 4:
        divisor = ((reg & 0x1F) + 1) * 2
        return 0, arg1 // divisor, reg
    if mode == 5:
        divq, divf = _pll_calc(arg1, arg2)
        return 0, arg2 * (divf + 1) // (1 << divq), reg
    if mode == 6:
        divisor = arg2 // arg1
        divisor = (divisor + 1) & ~1
        return 0, arg2 // divisor, reg
    if mode == 7:
        divisor = arg2 // arg1
        if divisor & 1:
            return -EINVAL, 0, reg
        return 0, 0, (divisor >> 1) & 0xFFFFFFFF
    if mode == 8:
        divq, divf = _pll_calc(arg1, arg2)
        current_divf = (reg & HB_PLL_DIVF_MASK) >> HB_PLL_DIVF_SHIFT
        value = reg
        if divf != current_divf:
            value |= HB_PLL_EXT_BYPASS
            value &= ~(HB_PLL_DIVF_MASK | HB_PLL_DIVQ_MASK)
            value |= divf << HB_PLL_DIVF_SHIFT
            value |= divq << HB_PLL_DIVQ_SHIFT
            value |= HB_PLL_EXT_ENA
            value &= ~HB_PLL_EXT_BYPASS
        else:
            value &= ~HB_PLL_DIVQ_MASK
            value |= divq << HB_PLL_DIVQ_SHIFT
        return 0, 0, value & 0xFFFFFFFF
    raise AssertionError(f"unknown oracle mode: {mode}")


def _cases() -> list[tuple[int, int, int, int]]:
    lock = HB_PLL_LOCK | HB_PLL_LOCK_500
    return [
        (1, HB_PLL_EXT_BYPASS, 100_000_000, 0),
        (1, (9 << HB_PLL_DIVF_SHIFT) | (2 << HB_PLL_DIVQ_SHIFT),
         100_000_000, 0),
        (1, (31 << HB_PLL_DIVF_SHIFT) | (5 << HB_PLL_DIVQ_SHIFT),
         25_000_000, 0),
        (2, 0, 800_000_000, 0),
        (2, HB_A9_PCLK_DIV, 800_000_000, 0),
        *((3, value << HB_A9_BCLK_DIV_SHIFT, 600_000_000, 0)
          for value in range(4)),
        *((4, value, 480_000_000, 0) for value in (0, 1, 7, 31)),
        (5, 0, 25_000_000, 24_000_000),
        (5, 0, 500_000_000, 24_000_000),
        (5, 0, 3_000_000_000, 24_000_000),
        (6, 0, 80_000_000, 480_000_000),
        (6, 0, 70_000_000, 480_000_000),
        (7, 0xA5A5A5A5, 120_000_000, 480_000_000),
        (7, 0xA5A5A5A5, 96_000_000, 480_000_000),
        (8, lock, 500_000_000, 24_000_000),
        (8, lock | (7 << HB_PLL_DIVF_SHIFT), 96_000_000, 24_000_000),
    ]


_MUTATIONS = {
    "pll_divq": (
        "return vco_freq / (1 << divq);",
        "return vco_freq / (1 << (divq + 1));",
    ),
    "a9b_shift": (
        ">> HB_A9_BCLK_DIV_SHIFT;",
        ">> (HB_A9_BCLK_DIV_SHIFT + 1);",
    ),
    "periclk_increment": ("\tdiv++;", "\tdiv += 2;"),
}


def verify_highbank(code: str | None = None, mutations: bool = True) -> dict:
    code = code or generated_highbank_code()
    cases = _cases()
    with tempfile.TemporaryDirectory(prefix="reharness-clock-oracle-") as directory:
        baseline = _compile(code, directory, "baseline")
        mismatches = []
        for case in cases:
            actual = _run(baseline, *case)
            expected = _expected(case)
            if actual != expected:
                mismatches.append({
                    "case": case, "expected": expected, "actual": actual,
                })
        if mismatches:
            raise AssertionError(f"Highbank arithmetic mismatch: {mismatches}")

        mutation_results = {}
        if mutations:
            for name, (old, new) in _MUTATIONS.items():
                if old not in code:
                    raise AssertionError(f"mutation anchor missing: {name}")
                mutated = code.replace(old, new, 1)
                binary = _compile(mutated, directory, f"mutated_{name}")
                caught = 0
                for case in cases:
                    if _run(binary, *case) != _expected(case):
                        caught += 1
                if not caught:
                    raise AssertionError(f"mutation escaped oracle: {name}")
                mutation_results[name] = {"caught_cases": caught}

    return {
        "schema": 1,
        "baseline_cases": len(cases),
        "baseline_passed": True,
        "mutations": mutation_results,
        "mutations_caught": len(mutation_results),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--no-mutations", action="store_true")
    args = parser.parse_args()
    result = verify_highbank(mutations=not args.no_mutations)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
