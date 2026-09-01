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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from backends.common import lowering_recipes  # noqa: E402
from trace_protocol import (  # noqa: E402
    TraceComparison,
    TraceRun,
    compare_runs,
    load_trace,
)


TraceOp = tuple[str, int]
FormalVariants = list[list[TraceOp]]


@dataclass
class RuntimeSegment:
    function: str
    ops: list[TraceOp]


def compare_runtime_traces(original_path: str, candidate_path: str,
                           *, config: dict | None = None,
                           context: int = 3) -> TraceComparison:
    """Compare original and candidate runtime artifacts.

    This is the primary runtime invariant for the data-driven experiment
    runner.  The RIS matcher below remains available as a secondary static
    contract check for existing experiments.
    """
    original: TraceRun = load_trace(original_path, config=config)
    candidate: TraceRun = load_trace(candidate_path, config=config)
    return compare_runs(original, candidate, context=context)


def _offset(addr: dict, registers: dict[str, int]) -> int | None:
    if "Symbolic" in addr:
        return registers.get(addr["Symbolic"]["register"])
    if "Fixed" in addr:
        return int(addr["Fixed"]["offset"])
    return None


def _formal_variants(ops: list[dict],
                     registers: dict[str, int],
                     recipes: dict[str, dict] | None = None
                     ) -> tuple[FormalVariants, bool]:
    """Return branch-sensitive MMIO sequences and address traceability."""
    variants: FormalVariants = [[]]
    traceable = True
    for op in ops:
        node_variants: FormalVariants = [[]]
        if "Cond" in op:
            cond = op["Cond"]
            then_variants, then_complete = _formal_variants(
                cond.get("then_ops", []), registers, recipes)
            else_ops = cond.get("else_ops", [])
            if else_ops:
                else_variants, else_complete = _formal_variants(
                    else_ops, registers, recipes)
            else:
                else_variants, else_complete = [[]], True
            node_variants = then_variants + else_variants
            traceable = traceable and then_complete and else_complete
        elif "Seq" in op:
            node_variants, complete = _formal_variants(
                op["Seq"].get("ops", []), registers, recipes)
            traceable = traceable and complete
        elif "Loop" in op:
            # Runtime iteration counts need a dedicated loop oracle.  The
            # structured call matcher does not guess how many bodies execute.
            node_variants = [[]]
        else:
            body = op.get("Read")
            kind = "R"
            if body is None:
                body = op.get("Write")
                kind = "W"
            if body is None:
                body = op.get("ReadModifyWrite")
                kind = "RMW"
            if body is not None:
                off = _offset(body.get("addr", {}), registers)
                if off is None:
                    traceable = False
                    node_variants = [[]]
                elif kind == "RMW":
                    recipe = (recipes or {}).get(body.get("op_id"), {})
                    if recipe.get("kind") == "write_from_read":
                        node_variants = [[("W", off)]]
                    else:
                        node_variants = [[("R", off), ("W", off)]]
                else:
                    node_variants = [[(kind, off)]]
        variants = [prefix + suffix
                    for prefix in variants for suffix in node_variants]

    unique: FormalVariants = []
    for variant in variants:
        if variant not in unique:
            unique.append(variant)
    return unique, traceable


def _formal_ops(ops: list[dict], registers: dict[str, int]) -> tuple[list[TraceOp], bool]:
    """Compatibility helper for callers expecting one unconditional sequence."""
    variants, traceable = _formal_variants(
        ops, registers, lowering_recipes(ops))
    result = variants[0] if len(variants) == 1 else []
    return result, traceable


def load_formal_modules(path: str) -> tuple[dict[str, FormalVariants], set[str]]:
    with open(path, encoding="utf-8") as handle:
        formal = json.load(handle)
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    modules: dict[str, FormalVariants] = {}
    untraceable: set[str] = set()
    for module in formal.get("modules", []):
        ops = module.get("ops", [])
        variants, complete = _formal_variants(
            ops, registers, lowering_recipes(ops))
        nonempty = [variant for variant in variants if variant]
        if nonempty:
            modules[module["name"]] = nonempty
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


def _trace_op_dict(op: TraceOp) -> dict[str, int | str]:
    return {"kind": op[0], "address": op[1]}


def _segment_dict(segment: RuntimeSegment) -> dict[str, object]:
    return {
        "function": segment.function,
        "ops": [_trace_op_dict(op) for op in segment.ops],
    }


def _call_dict(index: int, formal: str, runtime: str,
               expected_variants: FormalVariants,
               observed: RuntimeSegment | None,
               status: str) -> dict[str, object]:
    observed_ops = observed.ops if observed is not None else []
    selected = (observed_ops if status == "passed"
                else min(expected_variants, key=len))
    return {
        "index": index,
        "formal": formal,
        "runtime": runtime,
        "status": status,
        "expected_variants": [
            [_trace_op_dict(op) for op in variant]
            for variant in expected_variants
        ],
        "expected_ops": [_trace_op_dict(op) for op in selected],
        "observed": (_segment_dict(observed) if observed is not None else None),
        "observed_ops": [_trace_op_dict(op) for op in observed_ops],
    }


_PRIVATE_CONTEXT_HELPER_RE = re.compile(
    r"(?:[A-Za-z_]\w*_)?priv_from_(?:gc|irq|desc)$")


def _fold_private_context_helpers(
        modules: dict[str, FormalVariants],
        segments: list[RuntimeSegment],
        ) -> tuple[list[RuntimeSegment], list[dict[str, object]]]:
    """Attach known context-only helper traces to their callback segment.

    Function-entry tracing has no return markers, so an accessor such as
    ``priv_from_gc()`` becomes the active segment while its caller's MMIO
    operation executes.  Only the narrowly named private-context helpers are
    folded, and only after a declared formal function; unknown callbacks stay
    visible and fail closed below.
    """
    folded: list[RuntimeSegment] = []
    helpers: list[dict[str, object]] = []
    for segment in segments:
        if (_PRIVATE_CONTEXT_HELPER_RE.fullmatch(segment.function)
                and folded and folded[-1].function in modules):
            folded[-1].ops.extend(segment.ops)
            helpers.append({"function": segment.function,
                            "ops": [_trace_op_dict(op) for op in segment.ops],
                            "attached_to": folded[-1].function})
            continue
        folded.append(RuntimeSegment(segment.function, list(segment.ops)))
    return folded, helpers


def exact_call_analysis(modules: dict[str, FormalVariants], untraceable: set[str],
                        calls: list[tuple[str, str]], segments: list[RuntimeSegment],
                        traced_count: int) -> dict[str, object]:
    """Return a fail-closed, structured report for declared callback calls.

    Each declaration consumes one runtime function segment.  Unmatched
    segments and operations are retained in the report instead of being
    silently skipped, which makes the report useful as repair feedback.
    """
    report: dict[str, object] = {
        "ok": False,
        "traced_count": traced_count,
        "expected_call_count": len(calls),
        "observed_segment_count": len(segments),
        "calls": [],
        "unexpected_segments": [],
        "missing_modules": [],
        "untraceable_modules": [],
        "helper_segments": [],
    }
    missing_modules = sorted({formal for formal, _ in calls if formal not in modules})
    if missing_modules:
        report["missing_modules"] = missing_modules
        report["reason"] = "missing_formal_modules"
        return report
    selected_untraceable = sorted({formal for formal, _ in calls if formal in untraceable})
    if selected_untraceable:
        report["untraceable_modules"] = selected_untraceable
        report["reason"] = "untraceable_formal_modules"
        return report
    if not segments:
        report["reason"] = "missing_function_segments"
        return report

    normalized_segments, helper_segments = _fold_private_context_helpers(
        modules, segments)
    report["helper_segments"] = helper_segments

    cursor = 0
    consumed_indices: set[int] = set()
    call_reports: list[dict[str, object]] = []
    runtime_modules: dict[str, set[str]] = {}
    for formal, runtime in calls:
        runtime_modules.setdefault(runtime, set()).add(formal)
    for index, (formal, runtime) in enumerate(calls, 1):
        expected_variants = modules[formal]
        found = None
        for segment_index in range(cursor, len(normalized_segments)):
            if normalized_segments[segment_index].function == runtime:
                found = segment_index
                break
        if found is None:
            call_reports.append(_call_dict(
                index, formal, runtime, expected_variants, None,
                "missing_segment"))
            continue
        observed = normalized_segments[found]
        status = "passed" if any(observed.ops == variant
                                  for variant in expected_variants) \
            else "operation_mismatch"
        call_reports.append(_call_dict(
            index, formal, runtime, expected_variants, observed, status))
        consumed_indices.add(found)
        cursor = found + 1

    additional: list[dict[str, object]] = []
    unexpected: list[dict[str, object]] = []
    for index, segment in enumerate(normalized_segments):
        if index in consumed_indices:
            continue
        formal_candidates = runtime_modules.get(segment.function, set())
        if not formal_candidates and segment.function in modules:
            formal_candidates = {segment.function}
        if len(formal_candidates) == 1:
            formal = next(iter(formal_candidates))
            variants = modules[formal]
            if any(segment.ops == variant for variant in variants):
                additional.append({
                    "index": index,
                    "formal": formal,
                    "status": "validated",
                    **_segment_dict(segment),
                })
                continue
            unexpected.append({
                "index": index,
                "formal": formal,
                "status": "operation_mismatch",
                **_segment_dict(segment),
            })
            continue
        unexpected.append({
            "index": index,
            "status": "unknown_function",
            **_segment_dict(segment),
        })
    report["calls"] = call_reports
    report["additional_segments"] = additional
    report["unexpected_segments"] = unexpected
    report["ok"] = (
        all(item["status"] == "passed" for item in call_reports)
        and not unexpected
    )
    report["reason"] = None if report["ok"] else "callback_trace_mismatch"
    return report


def exact_call_report(modules: dict[str, FormalVariants], untraceable: set[str],
                      calls: list[tuple[str, str]], segments: list[RuntimeSegment],
                      traced_count: int) -> int:
    analysis = exact_call_analysis(modules, untraceable, calls, segments, traced_count)
    if analysis.get("missing_modules"):
        print("TRACE_MATCH_FAIL: Formal RIS 缺少模块: "
              + ", ".join(analysis["missing_modules"]))
        return 1
    if analysis.get("untraceable_modules"):
        print("TRACE_MATCH_FAIL: 模块含不可追踪地址: "
              + ", ".join(analysis["untraceable_modules"]))
        return 1
    if analysis.get("reason") == "missing_function_segments":
        print("TRACE_MATCH_FAIL: trace 缺少 [rhfn] 函数边界")
        return 1

    call_reports = analysis["calls"]
    passed_calls = sum(item["status"] == "passed" for item in call_reports)
    expected_ops = sum(
        len(item["expected_ops"]) for item in call_reports)
    matched_ops = sum(
        len(item["observed_ops"])
        for item in call_reports if item["status"] == "passed")
    expected_offsets = {
        operation["address"]
        for item in call_reports
        for operation in item["expected_ops"]
    }
    matched_offsets = {
        operation["address"]
        for item in call_reports if item["status"] == "passed"
        for operation in item["observed_ops"]
    }
    unique_modules = {formal for formal, _ in calls}
    failed_modules = {
        item["formal"] for item in call_reports if item["status"] != "passed"
    }
    passed_modules = len(unique_modules - failed_modules)

    print(f"[trace_match] {len(calls)} 个精确调用 / {len(unique_modules)} 个模块 "
          f"({passed_calls} call pass, {len(calls) - passed_calls} call fail), "
          f"traced={traced_count} ops", file=sys.stderr)
    failures: list[str] = []
    for item in call_reports:
        status = "✓" if item["status"] == "passed" else "✗"
        expected = item["expected_ops"]
        print(f"  {status} call#{item['index']} {item['formal']} => {item['runtime']}: "
              f"{len(expected)} ops {expected}", file=sys.stderr)
        if item["status"] == "missing_segment":
            failures.append(f"call#{item['index']} {item['formal']}=>{item['runtime']}: 缺少函数段")
        elif item["status"] != "passed":
            failures.append(f"call#{item['index']} {item['formal']}=>{item['runtime']}: 操作序列不匹配")
    for segment in analysis["unexpected_segments"]:
        failures.append(f"unexpected segment#{segment['index']}: {segment['function']}")

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
    parser.add_argument("serial_log", nargs="?")
    parser.add_argument("ris_file", nargs="?")
    parser.add_argument("dspec_file", nargs="?")
    parser.add_argument("--formal-json")
    parser.add_argument("--exercised", help="legacy module-name keyword filter")
    parser.add_argument(
        "--exercised-calls",
        help="ordered formal_module=runtime_function calls; duplicates are allowed")
    parser.add_argument(
        "--original-trace",
        help="primary runtime comparison: original-driver trace artifact")
    parser.add_argument(
        "--candidate-trace",
        help="primary runtime comparison: candidate-driver trace artifact")
    parser.add_argument(
        "--trace-config",
        help="JSON manifest or trace section used by primary runtime comparison")
    args = parser.parse_args(argv)

    if args.original_trace or args.candidate_trace:
        if not args.original_trace or not args.candidate_trace:
            print("TRACE_MATCH_FAIL: --original-trace and --candidate-trace are both required")
            return 1
        config = None
        if args.trace_config:
            try:
                with open(args.trace_config, encoding="utf-8") as handle:
                    document = json.load(handle)
                config = document.get("trace", document)
                if not isinstance(config, dict):
                    raise ValueError("trace config must be an object")
            except (OSError, ValueError, json.JSONDecodeError) as error:
                print(f"TRACE_MATCH_FAIL: 无法读取 trace config: {error}")
                return 1
        try:
            report = compare_runtime_traces(
                args.original_trace, args.candidate_trace, config=config)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"TRACE_MATCH_FAIL: 无法读取 runtime trace: {error}")
            return 1
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0 if report.equal else 1

    if not args.serial_log:
        parser.error("serial_log is required unless --original-trace/--candidate-trace are used")

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
