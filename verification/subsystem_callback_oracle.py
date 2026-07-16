"""Value-and-trace oracle for portable synthesized GPIO callback runners."""
from __future__ import annotations

import re

from generator.subsystem_runner import gpio_callback_plan


def _eval(expr: dict | None, env: dict[str, int]) -> int:
    if not expr:
        return 0
    if "Const" in expr:
        return int(expr["Const"])
    if "Var" in expr:
        return int(env.get(expr["Var"], 0))
    if "Top" in expr:
        raise ValueError("Top expression in callback oracle")
    if "Bits" in expr:
        body = expr["Bits"]
        width = body["hi"] - body["lo"] + 1
        return (_eval(body["expr"], env) >> body["lo"]) & ((1 << width) - 1)
    if "Ite" in expr:
        body = expr["Ite"]
        branch = body["then"] if _eval(body["guard"], env) else body["else"]
        return _eval(branch, env)
    if "BinOp" in expr:
        body = expr["BinOp"]
        left = _eval(body["left"], env)
        right = _eval(body["right"], env)
        op = body["op"]
        operations = {
            "Add": lambda: left + right, "Sub": lambda: left - right,
            "Mul": lambda: left * right, "Div": lambda: left // right,
            "Mod": lambda: left % right, "BitAnd": lambda: left & right,
            "BitOr": lambda: left | right, "BitXor": lambda: left ^ right,
            "Shl": lambda: left << right, "Shr": lambda: left >> right,
            "Eq": lambda: int(left == right), "Ne": lambda: int(left != right),
            "Lt": lambda: int(left < right), "Le": lambda: int(left <= right),
            "Gt": lambda: int(left > right), "Ge": lambda: int(left >= right),
            "And": lambda: int(bool(left) and bool(right)),
            "Or": lambda: int(bool(left) or bool(right)),
        }
        if op not in operations:
            raise ValueError(f"unsupported callback expression operator {op}")
        return operations[op]() & 0xFFFFFFFFFFFFFFFF
    raise ValueError(f"unsupported callback expression {expr}")


def _width(body: dict) -> int:
    return {"B1": 1, "B2": 2, "B4": 4, "B8": 8}.get(body["width"], 4)


def _offset(addr: dict, registers: dict[str, int]) -> int:
    if "Symbolic" in addr:
        return int(registers[addr["Symbolic"]["register"]])
    if "Fixed" in addr:
        return int(addr["Fixed"]["offset"])
    raise ValueError("computed callback address is outside portable oracle scope")


def _read(memory: bytearray, offset: int, width: int, big_endian: bool) -> int:
    value = 0
    for index in range(width):
        shift = 8 * (width - index - 1 if big_endian else index)
        value |= memory[offset + index] << shift
    return value


def _write(memory: bytearray, offset: int, width: int,
           big_endian: bool, value: int) -> None:
    for index in range(width):
        shift = 8 * (width - index - 1 if big_endian else index)
        memory[offset + index] = (value >> shift) & 0xFF


def _execute(ops: list[dict], env: dict[str, int], memory: bytearray,
             registers: dict[str, int]) -> list[tuple[str, int, int]]:
    trace: list[tuple[str, int, int]] = []
    for op in ops:
        if "Cond" in op:
            body = op["Cond"]
            branch = body["then_ops"] if _eval(body["guard"], env) else (
                body.get("else_ops") or [])
            trace.extend(_execute(branch, env, memory, registers))
            continue
        if "Seq" in op:
            trace.extend(_execute(op["Seq"]["ops"], env, memory, registers))
            continue
        if "Loop" in op:
            raise ValueError("loop is outside portable callback oracle scope")
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body is None:
            continue
        width = _width(body)
        offset = _offset(body["addr"], registers)
        big_endian = body.get("evidence", {}).get("byte_order") == "big"
        mask = (1 << (8 * width)) - 1
        if "Read" in op:
            value = _read(memory, offset, width, big_endian) & mask
            env[body["var"]] = value
            trace.append(("R", offset, value))
        elif "Write" in op:
            value = _eval(body["value"], env) & mask
            trace.append(("W", offset, value))
            _write(memory, offset, width, big_endian, value)
        else:
            old = _read(memory, offset, width, big_endian) & mask
            trace.append(("R", offset, old))
            env[body.get("read_var") or "__old"] = old
            value = _eval(body["transform"], env) & mask
            trace.append(("W", offset, value))
            _write(memory, offset, width, big_endian, value)
    return trace


def _segments(output: str) -> list[tuple[str, list[tuple[str, int, int]]]]:
    active = False
    current: tuple[str, list[tuple[str, int, int]]] | None = None
    segments: list[tuple[str, list[tuple[str, int, int]]]] = []
    for line in output.splitlines():
        if "[reharness-callback-begin]" in line:
            active = True
            continue
        if "[reharness-callback-end]" in line:
            active = False
            current = None
            continue
        marker = re.search(r"\[reharness-callback\]\s+([A-Za-z_]\w*)", line)
        if active and marker:
            current = (marker.group(1), [])
            segments.append(current)
            continue
        operation = re.search(
            r"\[trace\s+\d+\]\s+(R|W)\s+0x([0-9a-fA-F]+)\s+=\s+0x([0-9a-fA-F]+)",
            line)
        if active and current is not None and operation:
            current[1].append((
                operation.group(1), int(operation.group(2), 16),
                int(operation.group(3), 16)))
    return segments


def verify_subsystem_callbacks(formal: dict, device_spec, output: str) -> dict:
    total = int(formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("synthetic_functions", 0))
    if total == 0:
        return {
            "subsystem_callbacks_total": 0,
            "subsystem_callbacks_executed": 0,
            "subsystem_callback_oracle_passed": True,
            "subsystem_callback_oracle_errors": [],
        }
    plan = gpio_callback_plan(formal, device_spec)
    modules = {module["name"]: module for module in formal.get("modules", [])}
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    observed = _segments(output)
    memory = bytearray((0x5A + 37 * index) & 0xFF for index in range(0x1000))
    errors: list[str] = []
    begins = re.findall(r"\[reharness-callback-begin\]\s+(\d+)", output)
    ends = output.count("[reharness-callback-end]")
    if len(begins) != 1 or ends != 1:
        errors.append(
            f"expected one callback begin/end marker, observed {len(begins)}/{ends}")
    elif int(begins[0]) != len(plan):
        errors.append(
            f"runner declared {begins[0]} calls, plan requires {len(plan)}")
    if len(observed) != len(plan):
        errors.append(f"expected {len(plan)} callback calls, observed {len(observed)}")
    for index, entry in enumerate(plan):
        if index >= len(observed):
            break
        actual_module, actual_trace = observed[index]
        if actual_module != entry["module"]:
            errors.append(
                f"call#{index + 1} expected {entry['module']}, observed {actual_module}")
            continue
        env = dict(entry["args"])
        try:
            expected = _execute(
                modules[entry["module"]]["ops"], env, memory, registers)
        except (KeyError, ValueError, ZeroDivisionError) as error:
            errors.append(f"{entry['module']}: {error}")
            continue
        if actual_trace != expected:
            errors.append(
                f"call#{index + 1} {entry['module']} trace {actual_trace} != {expected}")
    executed = len({name for name, _trace in observed})
    planned_modules = {entry["module"] for entry in plan}
    if len(planned_modules) != total:
        errors.append(
            f"portable plan covers {len(planned_modules)}/{total} synthesized callbacks")
    return {
        "subsystem_callbacks_total": total,
        "subsystem_callbacks_executed": executed,
        "subsystem_callback_oracle_passed": not errors,
        "subsystem_callback_oracle_errors": errors,
    }
