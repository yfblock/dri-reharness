"""Portable execution plans for synthesized subsystem callbacks.

Plans are selected by public callback-table contracts and RIS evidence, never
by driver names.  The same plan drives harness emission, the bare-metal host
oracle, and the independent trace verifier.
"""
from __future__ import annotations

from extractor.formal import walk_all_ops, walk_leaf_ops


GPIO_CALLBACK_ORDER = (
    "gpio_chip.get",
    "gpio_chip.get_multiple",
    "gpio_chip.set",
    "gpio_chip.set_multiple",
    "gpio_chip.direction_input",
    "gpio_chip.direction_output",
    "gpio_chip.get_direction",
)


def _portable_gpio_module(module: dict) -> bool:
    leaves = list(walk_leaf_ops(module.get("ops", [])))
    if not leaves:
        return False
    for op in leaves:
        body = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite"))
        if body is None:
            continue
        evidence = body.get("evidence", {})
        if (evidence.get("origin") != "subsystem_summary"
                or evidence.get("summary_contract")
                != "linux.gpio_generic_chip_config"
                or body.get("reliability") == "Unsupported"):
            return False
        if not ({"Symbolic", "Fixed"} & set(body.get("addr", {}))):
            return False
    return not any("Loop" in op for op in walk_all_ops(module.get("ops", [])))


def _arguments(function, *, value: int = 1) -> dict[str, int]:
    defaults = {"offset": 1, "value": value, "mask": 3, "bits": 1}
    return {
        param.name: defaults.get(param.name, 1)
        for param in function.signature.params
        if param.type != "DeviceState"
    }


def gpio_callback_plan(formal: dict, device_spec) -> list[dict]:
    modules = {module["name"]: module for module in formal.get("modules", [])}
    by_table = {
        function.callback_table: function
        for function in device_spec.functions
        if function.callback_table in GPIO_CALLBACK_ORDER
        and function.ris_ref in modules
        and _portable_gpio_module(modules[function.ris_ref])
    }
    plan: list[dict] = []
    for table in GPIO_CALLBACK_ORDER:
        function = by_table.get(table)
        if function is None:
            continue
        values = (1, 0) if table == "gpio_chip.set" else (1,)
        for value in values:
            plan.append({
                "table": table,
                "module": function.ris_ref,
                "function": function,
                "args": _arguments(function, value=value),
            })
    return plan


def _call_arguments(entry: dict, device_expr: str) -> str:
    function = entry["function"]
    values = []
    for param in function.signature.params:
        if param.type == "DeviceState":
            continue
        values.append(str(entry["args"].get(param.name, 1)))
    values.append(device_expr)
    return ", ".join(values)


def emit_gpio_callback_runner(formal: dict, device_spec, priv: str,
                              *, static: bool) -> list[str]:
    plan = gpio_callback_plan(formal, device_spec)
    if not plan:
        return []
    storage = "static " if static else ""
    lines = [
        f"{storage}void reharness_run_subsystem_callbacks({priv} *dev) {{",
        f"    REHARNESS_CALLBACK_BEGIN({len(plan)});",
    ]
    for entry in plan:
        lines.append(f'    REHARNESS_CALLBACK_MARKER("{entry["module"]}");')
        lines.append(
            f"    {entry['function'].name}({_call_arguments(entry, 'dev')});")
    lines += ["    REHARNESS_CALLBACK_END();", "}", ""]
    return lines
