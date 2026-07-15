#!/usr/bin/env python3
"""Differential trace oracle: original C execution versus extracted RIS."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _eval(expr: dict, env: dict[str, int]) -> int:
    if "Const" in expr:
        return int(expr["Const"])
    if "Var" in expr:
        return int(env.get(expr["Var"], 0))
    if "Ite" in expr:
        node = expr["Ite"]
        return _eval(node["then"], env) if _eval(node["guard"], env) \
            else _eval(node["else"], env)
    if "BinOp" in expr:
        node = expr["BinOp"]
        left, right = _eval(node["left"], env), _eval(node["right"], env)
        op = node["op"]
        return {
            "Add": lambda: left + right, "Sub": lambda: left - right,
            "Mul": lambda: left * right, "Div": lambda: left // right,
            "Mod": lambda: left % right, "BitAnd": lambda: left & right,
            "BitOr": lambda: left | right, "BitXor": lambda: left ^ right,
            "Shl": lambda: left << right, "Shr": lambda: left >> right,
            "Eq": lambda: int(left == right), "Ne": lambda: int(left != right),
            "Lt": lambda: int(left < right), "Gt": lambda: int(left > right),
            "Le": lambda: int(left <= right), "Ge": lambda: int(left >= right),
            "And": lambda: int(bool(left) and bool(right)),
            "Or": lambda: int(bool(left) or bool(right)),
        }[op]()
    raise AssertionError(f"unsupported oracle expression: {expr}")


def _ris_trace(formal: dict, module_name: str, env: dict[str, int]
               ) -> list[tuple[str, int, int]]:
    module = next(module for module in formal["modules"]
                  if module["name"] == module_name)
    registers = {reg["name"]: reg["offset"] for reg in formal["register_map"]}
    trace = []

    def address(addr):
        if "Symbolic" in addr:
            return registers[addr["Symbolic"]["register"]]
        if "Fixed" in addr:
            return int(addr["Fixed"]["offset"])
        if "Computed" in addr:
            local = dict(env)
            local.setdefault("base", 0)
            return _eval(addr["Computed"], local)
        raise AssertionError(addr)

    def execute(ops):
        for op in ops:
            if "Cond" in op:
                if _eval(op["Cond"]["guard"], env):
                    execute(op["Cond"]["then_ops"])
                elif op["Cond"].get("else_ops"):
                    execute(op["Cond"]["else_ops"])
            elif "Seq" in op:
                execute(op["Seq"]["ops"])
            elif "Write" in op:
                body = op["Write"]
                trace.append(("W", address(body["addr"]),
                              _eval(body["value"], env) & 0xFFFFFFFF))
            elif "ReadModifyWrite" in op:
                raise AssertionError("trace fixture unexpectedly contains RMW")
            elif "Loop" in op:
                raise AssertionError("unbounded Loop is not executable by oracle")
    execute(module["ops"])
    return trace


def _compile_original(directory: str) -> str:
    source = os.path.join(ROOT, "tests", "fixtures", "path_state.c")
    include = os.path.join(directory, "include", "linux")
    os.makedirs(include, exist_ok=True)
    with open(os.path.join(include, "io.h"), "w", encoding="utf-8") as handle:
        handle.write("""
#include <stdint.h>
typedef uint32_t u32;
#define __iomem
extern unsigned char *rh_base;
extern void rh_trace_write(uint32_t value, void *address);
static inline void writel(uint32_t value, void *address)
{ rh_trace_write(value, address); }
""")
    main = os.path.join(directory, "main.c")
    with open(main, "w", encoding="utf-8") as handle:
        handle.write("""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
unsigned char memory[256];
unsigned char *rh_base = memory;
void path_state(void *base, unsigned int select);
void rh_trace_write(uint32_t value, void *address)
{
    printf("W %ld %u\\n", (long)((unsigned char *)address - rh_base), value);
}
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    path_state(memory, (unsigned int)strtoul(argv[1], 0, 0));
    return 0;
}
""")
    binary = os.path.join(directory, "original")
    cc = shutil.which("cc")
    if not cc:
        raise RuntimeError("C compiler unavailable")
    run = subprocess.run(
        [cc, "-std=gnu11", "-Wall", "-Werror", f"-I{directory}/include",
         source, main, "-o", binary], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return binary


def _original_trace(binary: str, select: int) -> list[tuple[str, int, int]]:
    run = subprocess.run([binary, str(select)], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return [(kind, int(offset), int(value))
            for kind, offset, value in
            (line.split() for line in run.stdout.splitlines() if line.strip())]


def verify_path_state_trace() -> dict:
    from extractor import ExtractorConfig, extract_ris

    source = os.path.join(ROOT, "tests", "fixtures", "path_state.c")
    result = extract_ris(ExtractorConfig(source=source))
    cases = {}
    with tempfile.TemporaryDirectory(prefix="rh_ris_trace_") as directory:
        binary = _compile_original(directory)
        for select in (0, 1):
            original = _original_trace(binary, select)
            ris = _ris_trace(result.formal, "path_state", {"select": select})
            if original != ris:
                raise AssertionError(
                    f"select={select}: original={original}, ris={ris}")
            cases[str(select)] = {"trace": ris, "matched": True}

        mutated = copy.deepcopy(result.formal)
        module = next(module for module in mutated["modules"]
                      if module["name"] == "path_state")
        write = next(op["Write"] for op in module["ops"] if "Write" in op)
        write["value"] = {"Const": 0xDEAD}
        mutation_caught = (_ris_trace(mutated, "path_state", {"select": 1})
                           != _original_trace(binary, 1))
        if not mutation_caught:
            raise AssertionError("trace oracle failed to detect mutated RIS")
    return {"schema": 1, "cases": cases,
            "mutation_caught": mutation_caught}


if __name__ == "__main__":
    print(json.dumps(verify_path_state_trace(), indent=2, sort_keys=True))
