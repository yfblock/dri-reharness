"""Portable execution plans for synthesized subsystem callbacks.

Plans are selected by public callback-table contracts and RIS evidence, never
by driver names.  The same plan drives harness emission, the bare-metal host
oracle, and the independent trace verifier.
"""
from __future__ import annotations

import os
import re

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
        body = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
                or op.get("StateRead") or op.get("StateWrite")
                or op.get("OutputWrite") or op.get("Return"))
        if body is None:
            return False
        evidence = body.get("evidence", {})
        if (evidence.get("origin") != "subsystem_summary"
                or evidence.get("summary_contract")
                != "linux.gpio_generic_chip_config"
                or body.get("reliability") == "Unsupported"):
            return False
        if (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")) and not (
                {"Symbolic", "Fixed"} & set(body.get("addr", {}))):
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


def _initializer_bodies(text: str, struct_name: str):
    pattern = re.compile(
        rf"\bstruct\s+{re.escape(struct_name)}\s+[A-Za-z_]\w*\s*=\s*\{{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start + 1:index]
                    break


def _sdhci_direct_dispatch_proven(formal: dict) -> bool:
    source = formal.get("metadata", {}).get("source")
    if not source or not os.path.isfile(source):
        return False
    text = open(source, encoding="utf-8", errors="replace").read()
    if not re.search(r"\bsdhci_pltfm_init\s*\(", text):
        return False
    pdata = list(_initializer_bodies(text, "sdhci_pltfm_data"))
    if not pdata or any(re.search(r"\.\s*ops\s*=", body) for body in pdata):
        return False
    marker = f"{os.sep}linux{os.sep}"
    if marker not in source:
        return False
    linux_root = source.split(marker, 1)[0] + marker.rstrip(os.sep)
    helper_path = os.path.join(
        linux_root, "drivers", "mmc", "host", "sdhci-pltfm.c")
    try:
        helper = open(helper_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    default_ops = list(_initializer_bodies(helper, "sdhci_ops"))
    return bool(default_ops) and not any(re.search(
        r"\.\s*(?:read_[lwb]|write_[lwb])\s*=", body)
        for body in default_ops)


def portable_sdhci_accessor_only(formal: dict, device_spec) -> bool:
    """Accept an SDHCI case only when its whole RIS is public accessor MMIO."""
    if device_spec.cls != "sdhci":
        return False
    if not _sdhci_direct_dispatch_proven(formal):
        return False
    subsystem = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    if subsystem.get("unmodeled_callbacks"):
        return False
    leaves = []
    for module in formal.get("modules", []):
        if any("Loop" in op for op in walk_all_ops(module.get("ops", []))):
            return False
        leaves.extend(walk_leaf_ops(module.get("ops", [])))
    if not leaves:
        return False
    for op in leaves:
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body is None:
            return False
        evidence = body.get("evidence", {})
        if (evidence.get("origin") != "subsystem_summary"
                or evidence.get("subsystem_summary") != "sdhci_accessor"
                or body.get("reliability") != "Exact"):
            return False
        if not ({"Symbolic", "Fixed"} & set(body.get("addr", {}))):
            return False
    return True


def w1c_drain_plan(formal: dict, device_spec) -> list[dict]:
    functions = {function.ris_ref: function for function in device_spec.functions}
    plan = []
    for module in formal.get("modules", []):
        proofs = [op["Loop"] for op in walk_all_ops(module.get("ops", []))
                  if "Loop" in op
                  and op["Loop"].get("proof_kind") == "masked_w1c_drain"]
        function = functions.get(module["name"])
        if len(proofs) != 1 or function is None:
            continue
        plan.append({
            "module": module["name"], "function": function,
            "loop": proofs[0],
        })
    return plan


def emit_w1c_drain_runner(formal: dict, device_spec, priv: str,
                          *, static: bool) -> list[str]:
    plan = w1c_drain_plan(formal, device_spec)
    if not plan:
        return []
    storage = "static " if static else ""
    lines = [
        f"{storage}void reharness_run_w1c_drains({priv} *dev) {{",
        f"    REHARNESS_W1C_BEGIN({len(plan)});",
    ]
    for entry in plan:
        arguments = ["0" for param in entry["function"].signature.params
                     if param.type != "DeviceState"]
        arguments.append("dev")
        lines.append(f'    REHARNESS_W1C_MARKER("{entry["module"]}");')
        lines.append(
            f"    {entry['function'].name}({', '.join(arguments)});")
    lines += ["    REHARNESS_W1C_END();", "}", ""]
    return lines


def _call_arguments(entry: dict, device_expr: str) -> str:
    function = entry["function"]
    values = []
    for param in function.signature.params:
        if param.type == "DeviceState":
            continue
        value = param.name if param.type == "UIntPtr" else str(
            entry["args"].get(param.name, 1))
        values.append(f"&{value}" if param.type == "UIntPtr" else value)
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
        lines.append("    {")
        pointer_params = [
            param for param in entry["function"].signature.params
            if param.type == "UIntPtr"]
        for param in pointer_params:
            lines.append(
                f"        uint32_t {param.name} = "
                f"{entry['args'].get(param.name, 1)}u;")
        lines.append(
            f"        uint32_t result = {entry['function'].name}("
            f"{_call_arguments(entry, 'dev')});")
        lines.append("        REHARNESS_CALLBACK_RESULT(result);")
        for param in pointer_params:
            lines.append(
                f'        REHARNESS_CALLBACK_OUTPUT("{param.name}", '
                f"{param.name});")
        lines.append(
            "        REHARNESS_CALLBACK_STATE(dev->gpio_sdata, dev->gpio_sdir);")
        lines.append("    }")
    lines += ["    REHARNESS_CALLBACK_END();", "}", ""]
    return lines
