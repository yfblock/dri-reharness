"""Portable execution plans for synthesized subsystem callbacks.

Plans are selected by public callback-table contracts and RIS evidence, never
by driver names.  The same plan drives harness emission, the bare-metal host
oracle, and the independent trace verifier.
"""
from __future__ import annotations

import os
import re

from extractor.formal import walk_all_ops, walk_leaf_ops
from extractor.metrics import _computed_is_lowerable


GPIO_CALLBACK_ORDER = (
    "gpio_chip.get",
    "gpio_chip.get_multiple",
    "gpio_chip.set",
    "gpio_chip.set_multiple",
    "gpio_chip.direction_input",
    "gpio_chip.direction_output",
    "gpio_chip.get_direction",
)

SDHCI_CALLBACK_ORDER = (
    "sdhci_ops.read_l", "sdhci_ops.read_w", "sdhci_ops.read_b",
    "sdhci_ops.write_l", "sdhci_ops.write_w", "sdhci_ops.write_b",
)

VIRTIO_CALLBACK_TABLES = {
    "virtqueue_info.callback", "input_dev.event",
    "virtio_driver.probe", "virtio_driver.remove",
    "virtio_driver.freeze", "virtio_driver.restore",
}


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
        if op.get("Read") or op.get("Write") or op.get("ReadModifyWrite"):
            addr = body.get("addr", {})
            if not ({"Symbolic", "Fixed"} & set(addr)):
                if ("Computed" not in addr
                        or not _computed_is_lowerable(addr["Computed"])):
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
                "kind": "gpio",
                "table": table,
                "module": function.ris_ref,
                "function": function,
                "args": _arguments(function, value=value),
            })
    return plan


def _portable_sdhci_module(module: dict) -> bool:
    leaves = list(walk_leaf_ops(module.get("ops", [])))
    if not leaves:
        return False
    for op in leaves:
        if "Delay" in op:
            continue
        body = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite") or op.get("StateRead")
                or op.get("StateWrite") or op.get("Return"))
        if body is None:
            return False
        evidence = body.get("evidence", {})
        if (evidence.get("summary_contract") != "linux.sdhci_ops"
                or body.get("reliability") in {"Unsupported", "Unknown"}):
            return False
        if op.get("Read") or op.get("Write") or op.get("ReadModifyWrite"):
            addr = body.get("addr", {})
            if not ({"Symbolic", "Fixed"} & set(addr)):
                if ("Computed" not in addr
                        or not _computed_is_lowerable(addr["Computed"])):
                    return False
    return not any("Loop" in op for op in walk_all_ops(module.get("ops", [])))


def sdhci_callback_plan(formal: dict, device_spec) -> list[dict]:
    if device_spec.cls != "sdhci":
        return []
    modules = {module["name"]: module for module in formal.get("modules", [])}
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    functions = {
        function.callback_table: function
        for function in device_spec.functions
        if function.callback_table in SDHCI_CALLBACK_ORDER
        and function.ris_ref in modules
        and _portable_sdhci_module(modules[function.ris_ref])
    }
    cases = {
        "sdhci_ops.read_l": [
            {"reg": registers.get("SDHCI_CAPABILITIES", 0x40)},
            {"reg": registers.get("SDHCI_PRESENT_STATE", 0x24)},
        ],
        "sdhci_ops.read_w": [
            {"reg": registers.get("SDHCI_HOST_VERSION", 0xfe)},
            {"reg": registers.get("SDHCI_SLOT_INT_STATUS", 0xfc)},
            {"reg": registers.get("SDHCI_CLOCK_CONTROL", 0x2c)},
        ],
        "sdhci_ops.read_b": [
            {"reg": registers.get("SDHCI_POWER_CONTROL", 0x29)},
        ],
        "sdhci_ops.write_l": [
            {"reg": registers.get("SDHCI_BUFFER", 0x20),
             "val": 0x11223344, "value": 0x11223344},
        ],
        "sdhci_ops.write_w": [
            {"reg": registers.get("SDHCI_TRANSFER_MODE", 0x0c),
             "val": 0x1234, "value": 0x1234},
            {"reg": registers.get("SDHCI_COMMAND", 0x0e),
             "val": 0x5678, "value": 0x5678},
            {"reg": registers.get("SDHCI_CLOCK_CONTROL", 0x2c),
             "val": 0xabcd, "value": 0xabcd},
        ],
        "sdhci_ops.write_b": [
            {"reg": registers.get("SDHCI_POWER_CONTROL", 0x29),
             "val": 0xa5, "value": 0xa5},
        ],
    }
    plan = []
    for table in SDHCI_CALLBACK_ORDER:
        function = functions.get(table)
        if function is None:
            continue
        for values in cases[table]:
            args = {
                param.name: int(values.get(param.name, 1))
                for param in function.signature.params
                if param.type != "DeviceState"
            }
            plan.append({
                "kind": "sdhci", "table": table,
                "module": function.ris_ref, "function": function,
                "args": args,
            })
    return plan


def portable_virtio_state_only(formal: dict, device_spec) -> bool:
    if device_spec.cls != "virtio_mmio":
        return False
    summaries = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    if not isinstance(summaries, dict) or not summaries.get("virtio_state"):
        return False
    seen = False
    for module in formal.get("modules", []):
        for op in walk_all_ops(module.get("ops", [])):
            if "Loop" in op and not (
                    op["Loop"].get("reliability") == "Exact"
                    and op["Loop"].get("bounded")):
                return False
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("StateRead") or op.get("StateWrite")
                    or op.get("Return"))
            if body is None:
                return False
            if op.get("Return"):
                continue
            seen = True
            if (body.get("evidence", {}).get("summary_contract") not in {
                    "linux.virtio_config", "linux.virtqueue",
                    "linux.virtio.lifecycle"}
                    or body.get("reliability") in {"Unsupported", "Unknown"}):
                return False
    return seen


def virtio_state_plan(formal: dict, device_spec) -> list[dict]:
    if not portable_virtio_state_only(formal, device_spec):
        return []
    modules = {module["name"]: module for module in formal.get("modules", [])}
    functions = {function.ris_ref: function for function in device_spec.functions}
    order = {"probe": 0, "interrupt_handler": 1, "write_config": 2,
             "suspend": 3, "resume": 4, "remove": 5}
    selected = [
        function for function in device_spec.functions
        if function.ris_ref in modules and modules[function.ris_ref].get("ops")]
    selected.sort(key=lambda function: (
        order.get(function.role, 2), function.ris_ref))
    plan = []
    for function in selected:
        args = _arguments(function)
        plan.append({
            "kind": "virtio", "table": function.callback_table or function.role,
            "module": function.ris_ref, "function": function, "args": args,
            "returns": any("Return" in op for op in walk_leaf_ops(
                modules[function.ris_ref]["ops"])),
        })
    return plan


def subsystem_callback_plan(formal: dict, device_spec) -> list[dict]:
    return (gpio_callback_plan(formal, device_spec)
            + sdhci_callback_plan(formal, device_spec)
            + virtio_state_plan(formal, device_spec))


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
    """Accept only source-audited public/private SDHCI accessor contracts."""
    if device_spec.cls != "sdhci":
        return False
    subsystem = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    if (not isinstance(subsystem, dict)
            or subsystem.get("unmodeled_callbacks")):
        return False
    leaves = []
    for module in formal.get("modules", []):
        if any("Loop" in op for op in walk_all_ops(module.get("ops", []))):
            return False
        leaves.extend(walk_leaf_ops(module.get("ops", [])))
    if not leaves:
        return False
    for op in leaves:
        body = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
                or op.get("StateRead") or op.get("StateWrite")
                or op.get("Return"))
        if "Delay" in op:
            continue
        if body is None:
            return False
        evidence = body.get("evidence", {})
        if (evidence.get("origin") != "subsystem_summary"
                or evidence.get("subsystem_summary") != "sdhci_accessor"
                or body.get("reliability") in {"Unsupported", "Unknown"}):
            return False
        if op.get("Read") or op.get("Write") or op.get("ReadModifyWrite"):
            addr = body.get("addr", {})
            if not ({"Symbolic", "Fixed"} & set(addr)):
                if ("Computed" not in addr
                        or not _computed_is_lowerable(addr["Computed"])):
                    return False
    summaries = subsystem.get("sdhci_ops", [])
    if summaries:
        callback_modules = {
            function.ris_ref for function in device_spec.functions
            if function.callback_table in SDHCI_CALLBACK_ORDER}
        planned_modules = {
            entry["module"] for entry in sdhci_callback_plan(
                formal, device_spec)}
        if callback_modules != planned_modules:
            return False
    elif not _sdhci_direct_dispatch_proven(formal):
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
    plan = subsystem_callback_plan(formal, device_spec)
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
        returns = entry.get(
            "returns", entry["function"].signature.return_type != "Void")
        if returns:
            lines.append(
                f"        uint32_t result = {entry['function'].name}("
                f"{_call_arguments(entry, 'dev')});")
            lines.append("        REHARNESS_CALLBACK_RESULT(result);")
        else:
            lines.append(
                f"        {entry['function'].name}("
                f"{_call_arguments(entry, 'dev')});")
        for param in pointer_params:
            lines.append(
                f'        REHARNESS_CALLBACK_OUTPUT("{param.name}", '
                f"{param.name});")
        if entry["kind"] == "gpio":
            lines.append(
                "        REHARNESS_CALLBACK_STATE(dev->gpio_sdata, dev->gpio_sdir);")
        elif entry["kind"] == "virtio":
            lines.append(
                "        REHARNESS_VIRTIO_STATE(dev->virtio_evt_available, "
                "dev->virtio_evt_completed, dev->virtio_sts_outstanding, "
                "dev->virtio_sts_completed, dev->virtio_evt_notified, "
                "dev->virtio_sts_notified, dev->ready);")
        lines.append("    }")
    lines += ["    REHARNESS_CALLBACK_END();", "}", ""]
    return lines
