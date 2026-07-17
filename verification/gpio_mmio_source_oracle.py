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
from extractor.formal import parse_expr
from verification.subsystem_callback_oracle import _eval, _execute


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
    summary_groups = analysis.get("summaries", {})
    summaries = (summary_groups.get("gpio_generic", [])
                 if isinstance(summary_groups, dict) else [])
    if not summaries:
        return None, []
    errors = []
    if len(summaries) != 1:
        errors.append(f"expected one gpio-mmio config, observed {len(summaries)}")
        return None, errors
    summary = copy.deepcopy(summaries[0])
    variant_model = summary.get("variant_model")
    if summary.get("variant") and not variant_model:
        errors.append("path-variant gpio-mmio config lacks a single source model")
    resolved = summary.get("resolved_fields", {})
    offsets = {}
    offset_specs = {}
    for field in ("dat", "set", "clr", "dirout", "dirin"):
        entries = resolved.get(field, [])
        if len(entries) > 1:
            errors.append(f"{field} has {len(entries)} source variants")
        if entries:
            offset = entries[0].get("offset")
            dynamic_expr = entries[0].get("dynamic_expr")
            if offset is None and not dynamic_expr:
                errors.append(f"{field} source address is unresolved")
            else:
                resource_index = entries[0].get("resource_index")
                offset_specs[field] = {
                    "offset": int(offset) if offset is not None else None,
                    "dynamic_expr": dynamic_expr,
                    "resource_offset": (
                        int(resource_index) * 0x100
                        if resource_index is not None else 0),
                }
                if offset is not None:
                    offsets[field] = int(offset) + offset_specs[field][
                        "resource_offset"]
    if "dat" not in offset_specs:
        errors.append("gpio-mmio dat register is unresolved")
    summary["offsets"] = offsets
    summary["offset_specs"] = offset_specs
    base_variants = [summary]
    if variant_model:
        common = {key: value for key, value in offset_specs.items()
                  if key not in {"dirin", "dirout"}}
        base_variants = [
            {**copy.deepcopy(summary), "variant_value": 0,
             "offset_specs": {**common, "dirout": offset_specs["dirout"]}},
            {**copy.deepcopy(summary), "variant_value": 1,
             "offset_specs": {**common, "dirin": offset_specs["dirin"]}},
        ]
    bank_model = summary.get("bank_model")
    materialized = []
    bank_values = range(int(bank_model.get("max_count") or 0)) if bank_model else [0]
    if bank_model and not bank_model.get("max_count"):
        errors.append("banked gpio-mmio config lacks a finite selector bound")
    for active in base_variants:
        for bank_value in bank_values:
            active = copy.deepcopy(active)
            active["bank_value"] = int(bank_value)
            active_offsets = {}
            for field, spec in active["offset_specs"].items():
                value = spec["offset"]
                if spec.get("dynamic_expr"):
                    value = _eval(parse_expr(spec["dynamic_expr"]), {
                        bank_model["selector"]: int(bank_value)})
                active_offsets[field] = int(value) + int(
                    spec["resource_offset"])
            active["offsets"] = active_offsets
            materialized.append(active)
    summary["variants"] = materialized
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


def _summary_probe_ops(ops: list[dict]) -> list[dict]:
    filtered = []
    for op in ops:
        if "Cond" in op:
            body = copy.deepcopy(op["Cond"])
            body["then_ops"] = _summary_probe_ops(body.get("then_ops", []))
            body["else_ops"] = _summary_probe_ops(body.get("else_ops") or [])
            if body["then_ops"] or body["else_ops"]:
                filtered.append({"Cond": body})
            continue
        if "Seq" in op:
            nested = _summary_probe_ops(op["Seq"].get("ops", []))
            if nested:
                filtered.append({"Seq": {"ops": nested}})
            continue
        body = (op.get("Read") or op.get("Write") or op.get("StateRead")
                or op.get("StateWrite"))
        evidence = body.get("evidence", {}) if body else {}
        if evidence.get("summary_contract") == "linux.gpio_generic_chip_config":
            filtered.append(copy.deepcopy(op))
    return filtered


def _formal_calls(formal: dict, device_spec, plan: list[dict], *,
                  variant_value: int = 0,
                  bank_value: int = 0) -> tuple[dict, list]:
    modules = {module["name"]: module for module in formal.get("modules", [])}
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    state = {"gpio_sdata": 0, "gpio_sdir": 0,
             "gpio_config_variant": variant_value,
             "gpio_bank_index": bank_value}
    base_offsets = {
        resource.bind: index * 0x100
        for index, resource in enumerate(
            item for item in device_spec.resources
            if item.type == "MmioResource")
        if resource.bind
    }
    memory = _seed()
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    summaries = (summary_groups.get("gpio_generic", [])
                 if isinstance(summary_groups, dict) else [])
    init_name = summaries[0].get("function") if len(summaries) == 1 else None
    if init_name in modules:
        init_ops = _summary_probe_ops(modules[init_name]["ops"])
        _execute(init_ops, {"base": 0,
                            (summaries[0].get("bank_model") or {}).get(
                                "selector", "gpio_bank_index"): bank_value},
                 memory, registers, state, {}, base_offsets)
    initial = {field: state[field] for field in ("gpio_sdata", "gpio_sdir")}
    memory = _seed()
    calls = []
    for entry in plan:
        env = dict(entry["args"])
        env["base"] = 0
        outputs = {
            param.name: int(entry["args"].get(param.name, 1))
            for param in entry["function"].signature.params
            if param.type == "UIntPtr"
        }
        env.update({f"*{name}": value for name, value in outputs.items()})
        trace, result = _execute(
            modules[entry["module"]]["ops"], env, memory, registers,
            state, outputs, base_offsets)
        calls.append({
            "table": entry["table"], "trace": trace, "result": result,
            "outputs": dict(outputs), "state": {
                field: state[field] for field in ("gpio_sdata", "gpio_sdir")},
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
    configs = config.get("variants") or [config]
    initial_states = {}
    total_calls = 0
    for active in configs:
        variant_value = int(active.get("variant_value", 0))
        bank_value = int(active.get("bank_value", 0))
        label = f"variant={variant_value},bank={bank_value}"
        source_initial = _source_init(active)
        initial_states[label] = source_initial
        source_state = dict(source_initial)
        source_memory = _seed()
        source_calls = [
            _source_call(entry["table"], entry["args"], active,
                         source_memory, source_state)
            for entry in plan
        ]
        total_calls += len(source_calls)
        try:
            formal_initial, formal_calls = _formal_calls(
                formal, device_spec, plan, variant_value=variant_value,
                bank_value=bank_value)
        except (KeyError, ValueError, ZeroDivisionError) as error:
            errors.append(f"{label} Formal RIS interpreter failed: {error}")
            formal_initial, formal_calls = {}, []
        if formal_initial != source_initial:
            errors.append(
                f"{label} initial shadow state {formal_initial} != source "
                f"{source_initial}")
        for index, (actual, expected) in enumerate(
                zip(formal_calls, source_calls, strict=False), 1):
            if actual != expected:
                errors.append(
                    f"{label} call#{index} {expected['table']} Formal RIS "
                    f"{actual} != source {expected}")
        if len(formal_calls) != len(source_calls):
            errors.append(
                f"{label} Formal/source call count "
                f"{len(formal_calls)}/{len(source_calls)}")
    return {
        "gpio_mmio_source_oracle_required": True,
        "gpio_mmio_source_oracle_passed": not errors,
        "gpio_mmio_source_oracle_errors": errors,
        "gpio_mmio_source_oracle_calls": total_calls,
        "gpio_mmio_source_initial_state": (
            next(iter(initial_states.values())) if len(initial_states) == 1
            else initial_states),
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
        "clps711x": "linux/drivers/gpio/gpio-clps711x.c",
        "dwapb": "linux/drivers/gpio/gpio-dwapb.c",
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

    clps = extracted["clps711x"]
    mutated = copy.deepcopy(clps.formal)
    probe = next(m for m in mutated["modules"]
                 if "__gpio_generic_" not in m["name"])
    direction_init = next(
        op["StateWrite"] for op in walk_leaf_ops(probe["ops"])
        if "StateWrite" in op and op["StateWrite"]["field"] == "gpio_sdir")
    polarity = direction_init["value"]["Ite"]
    polarity["then"], polarity["else"] = polarity["else"], polarity["then"]
    check("variant_direction_polarity", mutated, clps.device_spec)

    mutated = copy.deepcopy(clps.formal)
    collapsed = 0
    for module in mutated["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            fixed = (body or {}).get("addr", {}).get("Fixed")
            if fixed and fixed.get("base") == "dir":
                fixed["base"] = "dat"
                collapsed += 1
    if not collapsed:
        raise AssertionError("CLPS direction resource mutation found no addresses")
    check("direction_resource_collapsed", mutated, clps.device_spec)

    dwapb = extracted["dwapb"]
    mutated = copy.deepcopy(dwapb.formal)
    module = next(m for m in mutated["modules"]
                  if m["name"].endswith("__gpio_generic_get"))
    computed = next(
        op["Read"]["addr"]["Computed"] for op in walk_leaf_ops(module["ops"])
        if "Read" in op and "Computed" in op["Read"].get("addr", {}))
    stride = computed["BinOp"]["right"]["BinOp"]["right"]["BinOp"]["right"]
    stride["Const"] *= 2
    check("bank_stride", mutated, dwapb.device_spec)

    mutated = copy.deepcopy(dwapb.formal)
    for module in mutated["modules"]:
        if "__gpio_generic_" not in module["name"]:
            continue
        selector = next(
            (op["StateRead"] for op in walk_leaf_ops(module["ops"])
             if "StateRead" in op
             and op["StateRead"]["field"] == "gpio_bank_index"), None)
        if selector:
            selector["field"] = "gpio_config_variant"
    check("bank_selector_state", mutated, dwapb.device_spec)

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
