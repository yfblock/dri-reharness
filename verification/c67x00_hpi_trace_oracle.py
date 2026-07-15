#!/usr/bin/env python3
"""Differential and mutation oracle for the C67x00 HPI access protocol."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HPI_DATA = 0
HPI_MAILBOX = 1
HPI_ADDR = 2
HPI_STATUS = 3
HPI_IRQ_ROUTING_REG = 0x0142


def _helper_source() -> str:
    from generator.linux import _source_function

    path = os.path.join(
        ROOT, "linux", "drivers", "usb", "c67x00", "c67x00-ll-hpi.c")
    source = open(path, "r", encoding="utf-8", errors="replace").read()
    names = (
        "hpi_read_reg", "hpi_write_reg", "hpi_read_word_nolock",
        "hpi_write_word_nolock", "hpi_set_bits",
    )
    functions = []
    for name in names:
        found = _source_function(source, name)
        if found is None:
            raise AssertionError(f"C67 HPI helper missing: {name}")
        functions.append(found["text"])
    return "\n\n".join(functions)


def _standalone_source() -> str:
    helpers = _helper_source()
    return f'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint16_t u16;
#define HPI_DATA {HPI_DATA}
#define HPI_MAILBOX {HPI_MAILBOX}
#define HPI_ADDR {HPI_ADDR}
#define HPI_STATUS {HPI_STATUS}
#define HPI_T_CYC_NS 125
#define ndelay(value) ((void)(value))
#define spin_lock_irqsave(lock, flags) ((void)(lock), (flags) = 0)
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))

struct c67x00_hpi {{ unsigned char *base; unsigned int regstep; int lock; }};
struct c67x00_device {{ struct c67x00_hpi hpi; }};
static unsigned char memory[64];
static unsigned int regstep;
static u16 data_value;

static u16 __raw_readw(const void *address)
{{
    long offset = (const unsigned char *)address - memory;
    u16 value = data_value;
    printf("R %ld %u\\n", offset, value);
    return value;
}}

static void __raw_writew(u16 value, void *address)
{{
    long offset = (unsigned char *)address - memory;
    printf("W %ld %u\\n", offset, value);
}}

{helpers}

int main(int argc, char **argv)
{{
    struct c67x00_device dev = {{ .hpi = {{ memory, 0, 0 }} }};
    unsigned long mode, reg, value;
    if (argc != 6) return 2;
    mode = strtoul(argv[1], 0, 0);
    regstep = (unsigned int)strtoul(argv[2], 0, 0);
    reg = strtoul(argv[3], 0, 0);
    value = strtoul(argv[4], 0, 0);
    dev.hpi.regstep = regstep;
    data_value = (u16)strtoul(argv[5], 0, 0);
    switch (mode) {{
    case 1: (void)hpi_read_reg(&dev, (int)reg); break;
    case 2: hpi_write_reg(&dev, (int)reg, (u16)value); break;
    case 3: (void)hpi_read_word_nolock(&dev, (u16)reg); break;
    case 4: hpi_write_word_nolock(&dev, (u16)reg, (u16)value); break;
    case 5: hpi_set_bits(&dev, (u16)reg, (u16)value); break;
    default: return 3;
    }}
    return 0;
}}
'''


def _compile(directory: str) -> str:
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("C compiler unavailable")
    source = os.path.join(directory, "c67_hpi_original.c")
    binary = os.path.join(directory, "c67_hpi_original")
    with open(source, "w", encoding="utf-8") as handle:
        handle.write(_standalone_source())
    run = subprocess.run(
        [compiler, "-std=gnu11", "-Wall", "-Werror", source, "-o", binary],
        capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return binary


def _original_trace(binary: str, mode: int, regstep: int,
                    reg: int, value: int, data: int | None = None
                    ) -> list[tuple[str, int, int]]:
    data = value if data is None else data
    run = subprocess.run(
        [binary, str(mode), str(regstep), str(reg), str(value), str(data)],
        capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return [(kind, int(offset), int(item))
            for kind, offset, item in
            (line.split() for line in run.stdout.splitlines() if line.strip())]


def _eval(expr: dict, env: dict[str, int]) -> int:
    if "Const" in expr:
        return int(expr["Const"])
    if "Var" in expr:
        value = expr["Var"].strip()
        if value in env:
            return int(env[value])
        match = re.fullmatch(r"SOFEOP_TO_HPI_EN\((.+)\)", value)
        if match:
            index = int(env.get(match.group(1).strip(), 0))
            return 0x2000 if index else 0x0800
        raise AssertionError(f"unbound C67 oracle variable: {value}")
    if "BinOp" in expr:
        node = expr["BinOp"]
        left, right = _eval(node["left"], env), _eval(node["right"], env)
        return {
            "Add": left + right, "Sub": left - right,
            "Mul": left * right, "BitOr": left | right,
            "BitAnd": left & right,
        }[node["op"]]
    raise AssertionError(f"unsupported C67 oracle expression: {expr}")


def _set_bits_ops(formal: dict) -> list[dict]:
    from extractor.formal import walk_leaf_ops

    module = next(item for item in formal["modules"]
                  if item["name"] == "c67x00_urb_enqueue")
    selected = []
    for op in walk_leaf_ops(module["ops"]):
        body = op.get("Read") or op.get("Write")
        evidence = body.get("evidence", {}) if body else {}
        chain = [item.get("callee") for item in evidence.get("inlined_at", [])]
        if "hpi_set_bits" in chain:
            selected.append(copy.deepcopy(op))
    if len(selected) != 4:
        raise AssertionError(f"expected four hpi_set_bits RIS ops, got {len(selected)}")
    return selected


def _ris_trace(ops: list[dict], regstep: int, sie_num: int,
               read_value: int) -> list[tuple[str, int, int]]:
    env = {
        "c67x00->sie->dev->hpi.base": 0,
        "c67x00->sie->dev->hpi.regstep": regstep,
        "c67x00->sie->sie_num": sie_num,
        "HPI_ADDR": HPI_ADDR,
        "HPI_DATA": HPI_DATA,
        "HPI_IRQ_ROUTING_REG": HPI_IRQ_ROUTING_REG,
    }
    trace = []
    for op in ops:
        body = op.get("Read") or op.get("Write")
        address = _eval(body["addr"]["Computed"], env)
        if "Read" in op:
            value = read_value & 0xFFFF
            env[body["var"]] = value
            trace.append(("R", address, value))
        else:
            trace.append(("W", address, _eval(body["value"], env) & 0xFFFF))
    return trace


def _mutations(ops: list[dict]) -> dict[str, list[dict]]:
    register = copy.deepcopy(ops)
    register[0]["Write"]["value"] = {"Const": HPI_IRQ_ROUTING_REG + 1}

    regstep = copy.deepcopy(ops)
    for op in regstep:
        body = op.get("Read") or op.get("Write")
        expr = body["addr"]["Computed"]
        if "BinOp" in expr and "BinOp" in expr["BinOp"].get("right", {}):
            expr["BinOp"]["right"]["BinOp"]["right"] = {"Const": 1}

    target = copy.deepcopy(ops)
    for index in (0, 2):
        expr = target[index]["Write"]["addr"]["Computed"]
        expr["BinOp"]["right"]["BinOp"]["left"] = {"Var": "HPI_DATA"}

    order = copy.deepcopy(ops)
    order[0], order[1] = order[1], order[0]
    return {"register_index": register, "regstep": regstep,
            "wrapper_target": target, "operation_order": order}


def verify_c67x00_hpi() -> dict:
    from extractor import ExtractorConfig, extract_ris

    manifest = os.path.join(ROOT, "drivers", "multisource", "c67x00.json")
    result = extract_ris(ExtractorConfig(source=manifest))
    ops = _set_bits_ops(result.formal)
    cases = []
    primitive_cases = [
        (1, 1, HPI_STATUS, 0x55AA),
        (1, 4, HPI_STATUS, 0x55AA),
        (2, 2, HPI_MAILBOX, 0x1234),
        (3, 4, HPI_IRQ_ROUTING_REG, 0xA55A),
        (4, 2, HPI_IRQ_ROUTING_REG, 0x5AA5),
    ]
    set_bits_cases = [
        (1, 0, 0x0040), (2, 0, 0x0040),
        (2, 1, 0x0040), (4, 1, 0xA000),
    ]
    with tempfile.TemporaryDirectory(prefix="rh_c67_hpi_oracle_") as directory:
        binary = _compile(directory)
        for mode, step, reg, value in primitive_cases:
            original = _original_trace(binary, mode, step, reg, value)
            expected_addresses = {
                1: [("R", reg * step, value)],
                2: [("W", reg * step, value & 0xFFFF)],
                3: [("W", HPI_ADDR * step, reg),
                    ("R", HPI_DATA * step, value)],
                4: [("W", HPI_ADDR * step, reg),
                    ("W", HPI_DATA * step, value & 0xFFFF)],
            }[mode]
            if original != expected_addresses:
                raise AssertionError(
                    f"original HPI helper mismatch: {original} != {expected_addresses}")
            cases.append({"kind": f"primitive-{mode}", "regstep": step,
                          "matched": True})

        differential = []
        for step, sie_num, initial in set_bits_cases:
            mask = 0x2000 if sie_num else 0x0800
            original = _original_trace(
                binary, 5, step, HPI_IRQ_ROUTING_REG, mask, initial)
            ris = _ris_trace(ops, step, sie_num, initial)
            if ris != original:
                raise AssertionError(
                    f"C67 HPI differential mismatch: ris={ris}, original={original}")
            differential.append({"regstep": step, "sie_num": sie_num,
                                 "trace": ris, "matched": True})

        mutation_results = {}
        baseline_case = (4, 1, 0x0040)
        baseline = _ris_trace(ops, *baseline_case)
        for name, mutated in _mutations(ops).items():
            caught = _ris_trace(mutated, *baseline_case) != baseline
            if not caught:
                raise AssertionError(f"C67 HPI mutation escaped oracle: {name}")
            mutation_results[name] = {"caught": True}

    return {
        "schema": 1,
        "source": "linux/drivers/usb/c67x00/c67x00-ll-hpi.c",
        "primitive_cases": cases,
        "differential_cases": differential,
        "baseline_passed": True,
        "mutations": mutation_results,
        "mutations_caught": len(mutation_results),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    result = verify_c67x00_hpi()
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
