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
        name = expr["Var"]
        genmask = re.fullmatch(r"GENMASK\s*\((.+),\s*(.+)\)", name)
        if genmask:
            from extractor.formal import parse_expr
            high = _eval(parse_expr(genmask.group(1)), env)
            low = _eval(parse_expr(genmask.group(2)), env)
            if not 0 <= low <= high < 64:
                raise ValueError(f"invalid GENMASK bounds {high}:{low}")
            return (((1 << (high - low + 1)) - 1) << low)
        return int(env.get(name, 0))
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
             registers: dict[str, int], state: dict[str, int],
             outputs: dict[str, int]
             ) -> tuple[list[tuple[str, int, int]], int | None]:
    trace: list[tuple[str, int, int]] = []
    for op in ops:
        if "Cond" in op:
            body = op["Cond"]
            branch = body["then_ops"] if _eval(body["guard"], env) else (
                body.get("else_ops") or [])
            branch_trace, result = _execute(
                branch, env, memory, registers, state, outputs)
            trace.extend(branch_trace)
            if result is not None:
                return trace, result
            continue
        if "Seq" in op:
            seq_trace, result = _execute(
                op["Seq"]["ops"], env, memory, registers, state, outputs)
            trace.extend(seq_trace)
            if result is not None:
                return trace, result
            continue
        if "Loop" in op:
            raise ValueError("loop is outside portable callback oracle scope")
        if "StateRead" in op:
            body = op["StateRead"]
            env[body["var"]] = int(state.get(body["field"], 0))
            continue
        if "StateWrite" in op:
            body = op["StateWrite"]
            mask = (1 << (8 * _width(body))) - 1
            state[body["field"]] = _eval(body["value"], env) & mask
            continue
        if "OutputWrite" in op:
            body = op["OutputWrite"]
            value = _eval(body["value"], env) & 0xFFFFFFFFFFFFFFFF
            outputs[body["target"]] = value
            env[body["target"]] = value
            env[f"*{body['target']}"] = value
            continue
        if "Return" in op:
            return trace, _eval(op["Return"]["value"], env)
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
    return trace, None


def _segments(output: str) -> list[dict]:
    active = False
    current: dict | None = None
    segments: list[dict] = []
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
            current = {
                "module": marker.group(1), "trace": [], "result": None,
                "outputs": {}, "state": {},
            }
            segments.append(current)
            continue
        operation = re.search(
            r"\[trace\s+\d+\]\s+(R|W)\s+0x([0-9a-fA-F]+)\s+=\s+0x([0-9a-fA-F]+)",
            line)
        if active and current is not None and operation:
            current["trace"].append((
                operation.group(1), int(operation.group(2), 16),
                int(operation.group(3), 16)))
            continue
        result = re.search(r"\[reharness-result\]\s+0x([0-9a-fA-F]+)", line)
        if active and current is not None and result:
            current["result"] = int(result.group(1), 16)
            continue
        output_value = re.search(
            r"\[reharness-output\]\s+([A-Za-z_]\w*)=0x([0-9a-fA-F]+)", line)
        if active and current is not None and output_value:
            current["outputs"][output_value.group(1)] = int(
                output_value.group(2), 16)
            continue
        state_value = re.search(
            r"\[reharness-state\]\s+sdata=0x([0-9a-fA-F]+)\s+"
            r"sdir=0x([0-9a-fA-F]+)", line)
        if active and current is not None and state_value:
            current["state"] = {
                "gpio_sdata": int(state_value.group(1), 16),
                "gpio_sdir": int(state_value.group(2), 16),
            }
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
    state = {"gpio_sdata": 0, "gpio_sdir": 0}
    errors: list[str] = []
    probe = next((function for function in device_spec.functions
                  if function.role == "probe" and function.ris_ref in modules), None)
    if probe is not None:
        try:
            probe_env = {}
            if any(field.name == "ngpio" for field in device_spec.state):
                # Harness and bare-metal host-oracle initialization use the
                # same public GPIO width when no runtime firmware value exists.
                probe_env.update({"ngpio": 32, "num_gpios": 32})
            _execute(
                modules[probe.ris_ref]["ops"], probe_env, memory, registers,
                state, {})
        except (KeyError, ValueError, ZeroDivisionError) as error:
            errors.append(f"probe state initialization: {error}")
    memory = bytearray((0x5A + 37 * index) & 0xFF for index in range(0x1000))
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
        actual = observed[index]
        actual_module = actual["module"]
        if actual_module != entry["module"]:
            errors.append(
                f"call#{index + 1} expected {entry['module']}, observed {actual_module}")
            continue
        env = dict(entry["args"])
        outputs = {
            param.name: int(entry["args"].get(param.name, 1))
            for param in entry["function"].signature.params
            if param.type == "UIntPtr"
        }
        env.update({f"*{name}": value for name, value in outputs.items()})
        try:
            expected_trace, expected_result = _execute(
                modules[entry["module"]]["ops"], env, memory, registers,
                state, outputs)
        except (KeyError, ValueError, ZeroDivisionError) as error:
            errors.append(f"{entry['module']}: {error}")
            continue
        if actual["trace"] != expected_trace:
            errors.append(
                f"call#{index + 1} {entry['module']} trace "
                f"{actual['trace']} != {expected_trace}")
        if actual["result"] != expected_result:
            errors.append(
                f"call#{index + 1} {entry['module']} result "
                f"{actual['result']} != {expected_result}")
        if actual["outputs"] != outputs:
            errors.append(
                f"call#{index + 1} {entry['module']} outputs "
                f"{actual['outputs']} != {outputs}")
        if actual["state"] != state:
            errors.append(
                f"call#{index + 1} {entry['module']} state "
                f"{actual['state']} != {state}")
    executed = len({entry["module"] for entry in observed})
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
