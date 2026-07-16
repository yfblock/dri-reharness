"""Differential oracle between Linux gpio-mmio semantics and Formal RIS."""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.formal import walk_leaf_ops
from generator.subsystem_runner import gpio_callback_plan
from verification.subsystem_callback_oracle import _execute


def _seed() -> bytearray:
    return bytearray((0x5A + 37 * index) & 0xFF for index in range(0x1000))


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


def _config(formal: dict) -> tuple[dict | None, list[str]]:
    analysis = formal.get("metadata", {}).get("subsystem_summary_analysis", {})
    summaries = analysis.get("summaries", {}).get("gpio_generic", [])
    if not summaries:
        return None, []
    errors = []
    if len(summaries) != 1:
        errors.append(f"expected one gpio-mmio config, observed {len(summaries)}")
        return None, errors
    summary = copy.deepcopy(summaries[0])
    if summary.get("variant"):
        errors.append("path-variant gpio-mmio config lacks a single source model")
    resolved = summary.get("resolved_fields", {})
    offsets = {}
    for field in ("dat", "set", "clr", "dirout", "dirin"):
        entries = resolved.get(field, [])
        if len(entries) > 1:
            errors.append(f"{field} has {len(entries)} source variants")
        if entries:
            offset = entries[0].get("offset")
            if offset is None:
                errors.append(f"{field} source address is unresolved")
            else:
                offsets[field] = int(offset)
    if "dat" not in offsets:
        errors.append("gpio-mmio dat register is unresolved")
    summary["offsets"] = offsets
    return summary, errors


def _source_init(config: dict) -> dict[str, int]:
    memory = _seed()
    offsets = config["offsets"]
    width = int(config["width_bytes"])
    be = config.get("byte_order") == "big"
    full = (1 << (8 * width)) - 1
    state = {
        "gpio_sdata": _read(memory, offsets["dat"], width, be),
        "gpio_sdir": 0,
    }
    if "set" in offsets and "clr" not in offsets and not config.get("unreadable_set"):
        state["gpio_sdata"] = _read(memory, offsets["set"], width, be)
    if not config.get("unreadable_dir"):
        if "dirout" in offsets:
            state["gpio_sdir"] = _read(memory, offsets["dirout"], width, be)
        elif "dirin" in offsets:
            state["gpio_sdir"] = (~_read(
                memory, offsets["dirin"], width, be)) & full
    return state


def _source_write(memory: bytearray, trace: list, config: dict,
                  field: str, value: int) -> None:
    offset = config["offsets"][field]
    width = int(config["width_bytes"])
    full = (1 << (8 * width)) - 1
    value &= full
    trace.append(("W", offset, value))
    _write(memory, offset, width, config.get("byte_order") == "big", value)


def _source_read(memory: bytearray, trace: list, config: dict,
                 field: str) -> int:
    offset = config["offsets"][field]
    value = _read(
        memory, offset, int(config["width_bytes"]),
        config.get("byte_order") == "big")
    trace.append(("R", offset, value))
    return value


def _source_call(table: str, args: dict[str, int], config: dict,
                 memory: bytearray, state: dict[str, int]) -> dict:
    trace = []
    outputs = {
        name: int(args[name]) for name in ("mask", "bits") if name in args
    }
    offset = int(args.get("offset", 0))
    value = int(args.get("value", 0))
    line = 1 << offset
    full = (1 << (8 * int(config["width_bytes"]))) - 1
    registers = config["offsets"]
    result = 0

    def set_value() -> None:
        if "set" in registers and "clr" in registers:
            _source_write(
                memory, trace, config, "set" if value else "clr", line)
            return
        state["gpio_sdata"] = (
            state["gpio_sdata"] | line if value
            else state["gpio_sdata"] & ~line) & full
        _source_write(
            memory, trace, config,
            "set" if "set" in registers else "dat", state["gpio_sdata"])

    def set_direction(output: bool) -> None:
        state["gpio_sdir"] = (
            state["gpio_sdir"] | line if output
            else state["gpio_sdir"] & ~line) & full
        if "dirin" in registers:
            _source_write(
                memory, trace, config, "dirin", (~state["gpio_sdir"]) & full)
        if "dirout" in registers:
            _source_write(
                memory, trace, config, "dirout", state["gpio_sdir"])

    if table == "gpio_chip.get":
        field = "set" if config.get("read_output_set") else "dat"
        result = int(bool(_source_read(memory, trace, config, field) & line))
    elif table == "gpio_chip.get_multiple":
        field = "set" if config.get("read_output_set") else "dat"
        current = _source_read(memory, trace, config, field)
        mask = outputs["mask"]
        outputs["bits"] = (outputs["bits"] & ~mask) | (current & mask)
    elif table == "gpio_chip.set":
        set_value()
    elif table == "gpio_chip.set_multiple":
        mask, bits = outputs["mask"], outputs["bits"]
        if "set" in registers and "clr" in registers:
            set_mask = bits & mask
            clear_mask = (~bits) & mask & full
            if set_mask:
                _source_write(memory, trace, config, "set", set_mask)
            if clear_mask:
                _source_write(memory, trace, config, "clr", clear_mask)
        else:
            state["gpio_sdata"] = (
                (state["gpio_sdata"] & ~mask) | (bits & mask)) & full
            _source_write(
                memory, trace, config,
                "set" if "set" in registers else "dat", state["gpio_sdata"])
    elif table == "gpio_chip.direction_input":
        set_direction(False)
    elif table == "gpio_chip.direction_output":
        if config.get("no_set_on_input"):
            set_direction(True)
            set_value()
        else:
            set_value()
            set_direction(True)
    elif table == "gpio_chip.get_direction":
        if config.get("unreadable_dir"):
            direction = state["gpio_sdir"]
            result = 0 if direction & line else 1
        elif "dirout" in registers:
            direction = _source_read(memory, trace, config, "dirout")
            result = 0 if direction & line else 1
        else:
            direction = _source_read(memory, trace, config, "dirin")
            result = 1 if direction & line else 0
    else:
        raise ValueError(f"unsupported gpio-mmio callback {table}")
    return {
        "table": table, "trace": trace, "result": result,
        "outputs": outputs, "state": dict(state),
    }


def _formal_calls(formal: dict, device_spec, plan: list[dict]) -> tuple[dict, list]:
    modules = {module["name"]: module for module in formal.get("modules", [])}
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    state = {"gpio_sdata": 0, "gpio_sdir": 0}
    memory = _seed()
    probe = next((function for function in device_spec.functions
                  if function.role == "probe" and function.ris_ref in modules), None)
    if probe is not None:
        init_ops = []
        for op in walk_leaf_ops(modules[probe.ris_ref]["ops"]):
            body = (op.get("Read") or op.get("Write") or op.get("StateRead")
                    or op.get("StateWrite"))
            evidence = body.get("evidence", {}) if body else {}
            if evidence.get("summary_contract") == "linux.gpio_generic_chip_config":
                init_ops.append(op)
        _execute(init_ops, {}, memory, registers, state, {})
    initial = dict(state)
    memory = _seed()
    calls = []
    for entry in plan:
        env = dict(entry["args"])
        outputs = {
            param.name: int(entry["args"].get(param.name, 1))
            for param in entry["function"].signature.params
            if param.type == "UIntPtr"
        }
        env.update({f"*{name}": value for name, value in outputs.items()})
        trace, result = _execute(
            modules[entry["module"]]["ops"], env, memory, registers,
            state, outputs)
        calls.append({
            "table": entry["table"], "trace": trace, "result": result,
            "outputs": dict(outputs), "state": dict(state),
        })
    return initial, calls


def verify_gpio_mmio_source_differential(formal: dict, device_spec) -> dict:
    config, errors = _config(formal)
    if config is None and not errors:
        return {
            "gpio_mmio_source_oracle_required": False,
            "gpio_mmio_source_oracle_passed": True,
            "gpio_mmio_source_oracle_errors": [],
            "gpio_mmio_source_oracle_calls": 0,
        }
    if config is None:
        return {
            "gpio_mmio_source_oracle_required": True,
            "gpio_mmio_source_oracle_passed": False,
            "gpio_mmio_source_oracle_errors": errors,
            "gpio_mmio_source_oracle_calls": 0,
        }
    plan = gpio_callback_plan(formal, device_spec)
    if not plan:
        errors.append("no portable gpio callback plan for source differential")
    source_initial = _source_init(config)
    source_state = dict(source_initial)
    source_memory = _seed()
    source_calls = [
        _source_call(entry["table"], entry["args"], config,
                     source_memory, source_state)
        for entry in plan
    ]
    try:
        formal_initial, formal_calls = _formal_calls(formal, device_spec, plan)
    except (KeyError, ValueError, ZeroDivisionError) as error:
        errors.append(f"Formal RIS interpreter failed: {error}")
        formal_initial, formal_calls = {}, []
    if formal_initial != source_initial:
        errors.append(
            f"initial shadow state {formal_initial} != source {source_initial}")
    for index, (actual, expected) in enumerate(
            zip(formal_calls, source_calls, strict=False), 1):
        if actual != expected:
            errors.append(
                f"call#{index} {expected['table']} Formal RIS {actual} != source {expected}")
    if len(formal_calls) != len(source_calls):
        errors.append(
            f"Formal/source call count {len(formal_calls)}/{len(source_calls)}")
    return {
        "gpio_mmio_source_oracle_required": True,
        "gpio_mmio_source_oracle_passed": not errors,
        "gpio_mmio_source_oracle_errors": errors,
        "gpio_mmio_source_oracle_calls": len(source_calls),
        "gpio_mmio_source_initial_state": source_initial,
    }


def verify_gpio_mmio_source_suite() -> dict:
    from extractor.extractor import ExtractorConfig, extract_ris

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sources = {
        "ts4800": "linux/drivers/gpio/gpio-ts4800.c",
        "ge": "linux/drivers/gpio/gpio-ge.c",
        "ftgpio": "drivers/test/gpio-ftgpio010.c",
        "cadence": "linux/drivers/gpio/gpio-cadence.c",
        "idt3243x": "linux/drivers/gpio/gpio-idt3243x.c",
        "sodaville": "linux/drivers/gpio/gpio-sodaville.c",
    }
    extracted = {
        name: extract_ris(ExtractorConfig(source=os.path.join(root, source)))
        for name, source in sources.items()
    }
    cases = {
        name: verify_gpio_mmio_source_differential(
            result.formal, result.device_spec)
        for name, result in extracted.items()
    }
    for name, result in cases.items():
        if not result["gpio_mmio_source_oracle_passed"]:
            raise AssertionError(f"{name}: {result['gpio_mmio_source_oracle_errors']}")

    mutations = {}

    def check(name: str, formal: dict, device_spec) -> None:
        result = verify_gpio_mmio_source_differential(formal, device_spec)
        caught = not result["gpio_mmio_source_oracle_passed"]
        mutations[name] = {
            "caught": caught,
            "errors": result["gpio_mmio_source_oracle_errors"],
        }
        if not caught:
            raise AssertionError(f"source oracle missed {name} mutation")

    ts = extracted["ts4800"]
    mutated = copy.deepcopy(ts.formal)
    module = next(m for m in mutated["modules"]
                  if m["name"].endswith("__gpio_generic_set"))
    next(op["StateWrite"] for op in walk_leaf_ops(module["ops"])
         if "StateWrite" in op)["value"] = {"Const": 0}
    check("shadow_state_not_updated", mutated, ts.device_spec)

    mutated = copy.deepcopy(ts.formal)
    module = next(m for m in mutated["modules"]
                  if m["name"].endswith("__gpio_generic_set_multiple"))
    next(op["Write"] for op in walk_leaf_ops(module["ops"])
         if "Write" in op)["value"] = {"Const": 0}
    check("multiple_mask_value", mutated, ts.device_spec)

    mutated = copy.deepcopy(ts.formal)
    module = next(m for m in mutated["modules"]
                  if m["name"].endswith("__gpio_generic_direction_output"))
    write_indexes = [index for index, op in enumerate(module["ops"])
                     if "Write" in op]
    module["ops"][write_indexes[0]], module["ops"][write_indexes[1]] = (
        module["ops"][write_indexes[1]], module["ops"][write_indexes[0]])
    check("direction_set_order", mutated, ts.device_spec)

    ge = extracted["ge"]
    mutated = copy.deepcopy(ge.formal)
    probe = next(m for m in mutated["modules"]
                 if not "__gpio_generic_" in m["name"])
    direction_init = next(
        op["StateWrite"] for op in walk_leaf_ops(probe["ops"])
        if "StateWrite" in op and op["StateWrite"]["field"] == "gpio_sdir")
    direction_init["value"] = {"Var": "gpio_initial_direction"}
    check("dirin_inversion", mutated, ge.device_spec)

    mutated = copy.deepcopy(ge.formal)
    for module in mutated["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if body:
                body.setdefault("evidence", {})["byte_order"] = "native"
    check("byte_order", mutated, ge.device_spec)

    ftgpio = extracted["ftgpio"]
    mutated = copy.deepcopy(ftgpio.formal)
    module = next(m for m in mutated["modules"]
                  if m["name"].endswith("__gpio_generic_set"))
    writes = [op["Write"] for op in walk_leaf_ops(module["ops"])
              if "Write" in op]
    writes[0]["addr"], writes[1]["addr"] = writes[1]["addr"], writes[0]["addr"]
    check("set_clear_swapped", mutated, ftgpio.device_spec)

    return {
        "schema": 1,
        "source": "linux/drivers/gpio/gpio-mmio.c",
        "cases": {name: {
            "source": sources[name],
            "calls": result["gpio_mmio_source_oracle_calls"],
            "passed": result["gpio_mmio_source_oracle_passed"],
        } for name, result in cases.items()},
        "mutations": mutations,
        "mutations_caught": sum(item["caught"] for item in mutations.values()),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    report = verify_gpio_mmio_source_suite()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
