#!/usr/bin/env python3
"""Compare instrumented MMIO traces with RIS operations.

The reliable mode consumes structured Formal RIS JSON and an ordered list of
``formal_module=runtime_function`` calls.  ``[rhfn]`` events delimit runtime
functions, so one MMIO event cannot be credited to several callbacks.

The historical text-RIS mode remains available for old artifacts, but new
experiments should use ``--formal-json`` and ``--exercised-calls``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass


TraceOp = tuple[str, int]


@dataclass
class RuntimeSegment:
    function: str
    ops: list[TraceOp]


def _offset(addr: dict, registers: dict[str, int]) -> int | None:
    if "Symbolic" in addr:
        return registers.get(addr["Symbolic"]["register"])
    if "Fixed" in addr:
        return int(addr["Fixed"]["offset"])
    return None


def _formal_ops(ops: list[dict], registers: dict[str, int]) -> tuple[list[TraceOp], bool]:
    """Return unconditional top-level MMIO ops and whether all were traceable."""
    result: list[TraceOp] = []
    traceable = True
    for op in ops:
        body = op.get("Read")
        kind = "R"
        if body is None:
            body = op.get("Write")
            kind = "W"
        if body is None:
            body = op.get("ReadModifyWrite")
            kind = "RMW"
        if body is None:
            # Conditional/loop bodies are path dependent.  Exact call oracles
            # validate the unconditional contract and leave path validation to
            # the dedicated CFG/mutation checks.
            continue
        off = _offset(body.get("addr", {}), registers)
        if off is None:
            traceable = False
            continue
        if kind == "RMW":
            result.extend((("R", off), ("W", off)))
        else:
            result.append((kind, off))
    return result, traceable


def load_formal_modules(path: str) -> tuple[dict[str, list[TraceOp]], set[str]]:
    with open(path, encoding="utf-8") as handle:
        formal = json.load(handle)
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    modules: dict[str, list[TraceOp]] = {}
    untraceable: set[str] = set()
    for module in formal.get("modules", []):
        ops, complete = _formal_ops(module.get("ops", []), registers)
        if ops:
            modules[module["name"]] = ops
        if not complete:
            untraceable.add(module["name"])
    return modules, untraceable


def load_legacy_modules(ris_path: str, dspec_path: str) -> dict[str, list[TraceOp]]:
    """Best-effort compatibility parser for pre-structured artifacts."""
    with open(ris_path, encoding="utf-8") as handle:
        ris = handle.read()
    with open(dspec_path, encoding="utf-8") as handle:
        dspec = handle.read()
    registers = {
        match.group(1): int(match.group(2), 16)
        for match in re.finditer(
            r"register\s+(\w+):\s*B\d+\s+at\s+base\s+\+\s+(0x[0-9a-fA-F]+)",
            dspec)
    }
    modules: dict[str, list[TraceOp]] = {}
    for match in re.finditer(r"module\s+(\w+)\s*\{(.*?)\n  \}", ris, re.S):
        name, body = match.groups()
        ops: list[TraceOp] = []
        for raw_line in body.splitlines():
            line = re.sub(r"--.*$", "", raw_line).strip()
            symbolic = re.search(
                r"\b(R|W|RMW)\(B\d+,\s*.*?\.(\w+)\)", line)
            fixed = re.search(
                r"\b(R|W|RMW)\(B\d+,\s*.*?\[(0x[0-9a-fA-F]+)\]", line)
            if symbolic:
                kind, reg = symbolic.groups()
                off = registers.get(reg)
            elif fixed:
                kind, raw_off = fixed.groups()
                off = int(raw_off, 16)
            else:
                continue
            if off is None:
                continue
            if kind == "RMW":
                ops.extend((("R", off), ("W", off)))
            else:
                ops.append((kind, off))
        if ops:
            modules[name] = ops
    return modules


def parse_trace(log: str) -> tuple[list[TraceOp], list[RuntimeSegment]]:
    traced: list[TraceOp] = []
    segments: list[RuntimeSegment] = []
    current: RuntimeSegment | None = None
    for line in log.splitlines():
        function = re.search(r"\[rhfn\]\s+([A-Za-z_]\w*)", line)
        if function:
            current = RuntimeSegment(function.group(1), [])
            segments.append(current)
            continue
        operation = re.search(r"\[rh\]\s+(R|W)\s+0x([0-9a-fA-F]+)", line)
        if operation:
            op = (operation.group(1), int(operation.group(2), 16))
            traced.append(op)
            if current is not None:
                current.ops.append(op)
    return traced, segments


def subsequence_match(expected: list[TraceOp], actual: list[TraceOp]) -> tuple[int, list[TraceOp]]:
    cursor = 0
    matched = 0
    missing: list[TraceOp] = []
    for item in expected:
        while cursor < len(actual) and actual[cursor] != item:
            cursor += 1
        if cursor == len(actual):
            missing.append(item)
        else:
            matched += 1
            cursor += 1
    return matched, missing


def parse_calls(text: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        formal, separator, runtime = item.partition("=")
        calls.append((formal.strip(), runtime.strip() if separator else formal.strip()))
    return calls


def exact_call_report(modules: dict[str, list[TraceOp]], untraceable: set[str],
                      calls: list[tuple[str, str]], segments: list[RuntimeSegment],
                      traced_count: int) -> int:
    missing_modules = sorted({formal for formal, _ in calls if formal not in modules})
    if missing_modules:
        print("TRACE_MATCH_FAIL: Formal RIS 缺少模块: " + ", ".join(missing_modules))
        return 1
    selected_untraceable = sorted({formal for formal, _ in calls if formal in untraceable})
    if selected_untraceable:
        print("TRACE_MATCH_FAIL: 模块含不可追踪地址: " + ", ".join(selected_untraceable))
        return 1
    if not segments:
        print("TRACE_MATCH_FAIL: trace 缺少 [rhfn] 函数边界")
        return 1

    cursor = 0
    results: list[tuple[str, str, list[TraceOp], int, list[TraceOp]]] = []
    for formal, runtime in calls:
        while cursor < len(segments) and segments[cursor].function != runtime:
            cursor += 1
        expected = modules[formal]
        if cursor == len(segments):
            results.append((formal, runtime, expected, 0, list(expected)))
            continue
        matched, missing = subsequence_match(expected, segments[cursor].ops)
        results.append((formal, runtime, expected, matched, missing))
        cursor += 1

    passed_calls = sum(not missing for _, _, _, _, missing in results)
    expected_ops = sum(len(expected) for _, _, expected, _, _ in results)
    matched_ops = sum(matched for _, _, _, matched, _ in results)
    expected_offsets = {off for _, _, expected, _, _ in results for _, off in expected}
    matched_offsets = {
        off for _, _, expected, matched, missing in results
        if matched and not missing for _, off in expected
    }
    unique_modules = {formal for formal, _ in calls}
    failed_modules = {formal for formal, _, _, _, missing in results if missing}
    passed_modules = len(unique_modules - failed_modules)

    print(f"[trace_match] {len(calls)} 个精确调用 / {len(unique_modules)} 个模块 "
          f"({passed_calls} call pass, {len(calls) - passed_calls} call fail), "
          f"traced={traced_count} ops", file=sys.stderr)
    failures: list[str] = []
    for index, (formal, runtime, expected, _, missing) in enumerate(results, 1):
        status = "✓" if not missing else "✗"
        print(f"  {status} call#{index} {formal} => {runtime}: "
              f"{len(expected)} ops {expected}", file=sys.stderr)
        if missing:
            failures.append(f"call#{index} {formal}=>{runtime}: 缺失 {missing}")

    print("", file=sys.stderr)
    print(f"[coverage] 模块覆盖: {passed_modules}/{len(unique_modules)} 精确模块通过", file=sys.stderr)
    print(f"[coverage] 调用覆盖: {passed_calls}/{len(calls)} 预期调用通过", file=sys.stderr)
    print(f"[coverage] op 覆盖: {matched_ops}/{expected_ops} ops 命中", file=sys.stderr)
    print(f"[coverage] 寄存器覆盖: {len(matched_offsets)}/{len(expected_offsets)} "
          "寄存器偏移被验证", file=sys.stderr)
    print("[coverage] trace 级别: 函数边界+偏移级+exerciser", file=sys.stderr)
    if failures:
        print("TRACE_MATCH_FAIL: " + "; ".join(failures))
        return 1
    print("TRACE_MATCH_OK")
    return 0


def legacy_report(modules: dict[str, list[TraceOp]], traced: list[TraceOp],
                  exercised: list[str] | None) -> int:
    irq_keywords = ("irq", "ack", "mask", "unmask", "handler", "interrupt")
    def checkable(name: str) -> bool:
        if any(keyword in name.lower() for keyword in irq_keywords):
            return False
        return not exercised or any(keyword in name for keyword in exercised)

    selected = {name: ops for name, ops in modules.items() if checkable(name)}
    if not selected:
        print(f"[trace_match] 0 个可校验模块 (共 {len(modules)}) — vacuous pass",
              file=sys.stderr)
        print("TRACE_MATCH_OK")
        return 0
    if not traced:
        print("TRACE_MATCH_FAIL: trace 为空 (检查 instrument_mmio 是否生效)")
        return 1
    failures = []
    matched_total = 0
    expected_total = 0
    for name, expected in selected.items():
        matched, missing = subsequence_match(expected, traced)
        matched_total += matched
        expected_total += len(expected)
        if missing:
            failures.append(f"{name}: 缺失 {missing}")
    passed = len(selected) - len(failures)
    print(f"[trace_match] {len(selected)} 个兼容模式模块 "
          f"({passed} pass, {len(failures)} fail), traced={len(traced)} ops",
          file=sys.stderr)
    print(f"[coverage] 模块覆盖: {passed}/{len(selected)} 可校验模块通过", file=sys.stderr)
    print(f"[coverage] op 覆盖: {matched_total}/{expected_total} ops 命中", file=sys.stderr)
    if failures:
        print("TRACE_MATCH_FAIL: " + "; ".join(failures))
        return 1
    print("TRACE_MATCH_OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial_log")
    parser.add_argument("ris_file", nargs="?")
    parser.add_argument("dspec_file", nargs="?")
    parser.add_argument("--formal-json")
    parser.add_argument("--exercised", help="legacy module-name keyword filter")
    parser.add_argument(
        "--exercised-calls",
        help="ordered formal_module=runtime_function calls; duplicates are allowed")
    args = parser.parse_args(argv)

    try:
        with open(args.serial_log, encoding="utf-8") as handle:
            log = handle.read()
        if args.formal_json:
            modules, untraceable = load_formal_modules(args.formal_json)
        else:
            if not args.ris_file or not args.dspec_file:
                parser.error("text mode requires ris_file and dspec_file")
            modules = load_legacy_modules(args.ris_file, args.dspec_file)
            untraceable = set()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"TRACE_MATCH_FAIL: 无法读取 oracle 输入: {error}")
        return 1

    traced, segments = parse_trace(log)
    if args.exercised_calls:
        if not args.formal_json:
            print("TRACE_MATCH_FAIL: --exercised-calls 要求 --formal-json")
            return 1
        return exact_call_report(
            modules, untraceable, parse_calls(args.exercised_calls), segments, len(traced))
    exercised = ([item.strip() for item in args.exercised.split(",") if item.strip()]
                 if args.exercised else None)
    return legacy_report(modules, traced, exercised)


if __name__ == "__main__":
    sys.exit(main())
