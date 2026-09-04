"""DeviceSpec inference: device class, state, resources, registers."""
from __future__ import annotations
import re

from ..spec import (DeviceSpec, FunctionSpec, RegisterDesc, StateField,
                    Resource)
from ..ast_model import Func
from ..formal import walk_leaf_ops, walk_all_ops
from .func_specs import _bound_mmio_resources


_DEVICE_CLASS_HINTS = [
    ("gpio", "gpio_controller"), ("clk", "clock"), ("pll", "clock"),
    ("virtio", "virtio_mmio"), ("ahci", "ahci"), ("sdhci", "sdhci"),
    ("rtc", "rtc"), ("i2c", "i2c"), ("spi", "spi"),
]

_MODELED_STATE_FIELDS = {
    "bypass_orig": "UInt",
    "mask_cache": "UInt",
    "skip_init": "Bool",
    "ngpio": "UInt",
    "gpio_dir": "UInt",
    "gpio_is": "UInt",
    "gpio_ibe": "UInt",
    "gpio_iev": "UInt",
    "gpio_ie": "UInt",
    "version": "UInt",
    "features": "UInt64",
    "ready": "Bool",
    "idev": "Bool",
    "evbit": "UInt64",
    "absbit": "UInt64",
    "virtio_evt_available": "UInt",
    "virtio_evt_completed": "UInt",
    "virtio_evt_outstanding": "UInt",
    "virtio_evt_queue_depth": "UInt",
    "virtio_evt_notified": "Bool",
    "virtio_sts_available": "UInt",
    "virtio_sts_completed": "UInt",
    "virtio_sts_outstanding": "UInt",
    "virtio_sts_queue_depth": "UInt",
    "virtio_sts_notified": "Bool",
    "xfer_mode_shadow": "UInt",
    # Common USB controller / endpoint private state.
    "enabled": "Bool",
    "suspended": "Bool",
    "connected": "Bool",
    "remote_wakeup_allowed": "Bool",
    "halted": "Bool",
    "wedged": "Bool",
    "dir_in": "Bool",
    "periodic": "Bool",
    "isochronous": "Bool",
    "num_eps": "UInt",
    "num_channels": "UInt",
    "op_state": "UInt",
    "lx_state": "UInt",
    "fifo_size": "UInt",
    "fifo_load": "UInt",
    "desc_count": "UInt",
    "next_desc": "UInt",
    "compl_desc": "UInt",
    "total_data": "UInt",
    "target_frame": "UInt",
    "frame_number": "UInt",
    "dma": "UInt64",
    "hpi_regstep": "UInt",
    "sie_num": "UInt",
    "gpio_sdata": "UInt",
    "gpio_sdir": "UInt",
    "flags": "UInt",
    "nr_ports": "UInt",
    "max_ports": "UInt",
}


def _modeled_state_fields(formal: dict) -> dict[str, str]:
    found: dict[str, str] = {}

    def inspect(expr):
        if not isinstance(expr, dict):
            return
        if "Var" in expr:
            text = expr["Var"]
            for field, field_type in _MODELED_STATE_FIELDS.items():
                if re.search(rf"(?:->|\.){re.escape(field)}\b", text):
                    found[field] = field_type
            if re.search(r"\bnum_gpios\b", text):
                found["ngpio"] = "UInt"
            if re.search(r"(?:->|\.)hpi(?:->|\.)regstep\b", text):
                found["hpi_regstep"] = "UInt"
            if re.search(r"(?:->|\.)sie_num\b", text):
                found["sie_num"] = "UInt"
        elif "BinOp" in expr:
            inspect(expr["BinOp"].get("left"))
            inspect(expr["BinOp"].get("right"))
        elif "Ite" in expr:
            inspect(expr["Ite"].get("guard"))
            inspect(expr["Ite"].get("then"))
            inspect(expr["Ite"].get("else"))
        elif "Bits" in expr:
            inspect(expr["Bits"].get("expr"))

    for module in formal["modules"]:
        for op in walk_all_ops(module["ops"]):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if body:
                var = body.get("var")
                if var:
                    inspect({"Var": var})
                if "Computed" in body.get("addr", {}):
                    inspect(body["addr"]["Computed"])
                inspect(body.get("value") or body.get("transform"))
            if "StateRead" in op:
                found[op["StateRead"]["field"]] = (
                    "UIntArray" if op["StateRead"].get("index") else "UInt")
            elif "StateWrite" in op:
                found[op["StateWrite"]["field"]] = (
                    "UIntArray" if op["StateWrite"].get("index") else "UInt")
                inspect(op["StateWrite"].get("value"))
            elif "OutputWrite" in op:
                inspect(op["OutputWrite"].get("value"))
            elif "Return" in op:
                inspect(op["Return"].get("value"))
            if "Cond" in op:
                inspect(op["Cond"].get("guard"))
            if "Loop" in op:
                inspect(op["Loop"].get("count"))
                inspect(op["Loop"].get("guard"))
    return found


def infer_device_spec(formal: dict, funcs: list[Func],
                      fn_specs: list[FunctionSpec], source_path: str,
                      source_text: str) -> DeviceSpec:
    name = formal["driver"]
    cls = "generic_mmio"
    low = name.lower()
    for kw, c in _DEVICE_CLASS_HINTS:
        if kw in low:
            cls = c
            break

    # State models resources owned by this generated device.  A clock provider
    # has clk_ops/clk_hw callbacks but does not necessarily consume a struct
    # clk; require an actual acquisition call or source field before adding the
    # consumer-side Clock state.
    has_hpi_state = bool(re.search(
        r"(?:->|\.)hpi(?:->|\.)base\b", source_text))
    state: list[StateField] = [StateField(
        "base", "MmioBase", bind="hpi.base" if has_hpi_state else None)]
    fixed_bases = _bound_mmio_resources(formal)
    for base in sorted(fixed_bases, key=lambda item: (
            fixed_bases[item] is None,
            fixed_bases[item] if fixed_bases[item] is not None else 0,
            item)):
        if base != "base":
            state.append(StateField(base, "MmioBase", bind=base))
    has_irq = any(fs.role.startswith("interrupt") or fs.role == "set_irq_type" for fs in fn_specs)
    has_clk = bool(re.search(
        r"\b(?:(?:devm_)?clk_get(?:_optional)?(?:_enabled)?|"
        r"devm_clk_get_optional_enabled)\s*\(", source_text))
    has_clk |= bool(re.search(r"\bstruct\s+clk\s*\*", source_text))
    if has_clk:
        state.append(StateField("clk", "Clock"))
    if has_irq:
        state.append(StateField("num_irqs", "UInt"))
    existing = {s.name for s in state}
    for field, field_type in _modeled_state_fields(formal).items():
        if field not in existing:
            state.append(StateField(
                field, field_type,
                bind=("hpi.regstep" if field == "hpi_regstep"
                      else "sie.sie_num" if field == "sie_num" else None)))
            existing.add(field)

    # resources
    transaction_transports = sorted({
        (op.get("TransactionRead") or op.get("TransactionWrite")
         or op.get("TransactionUpdate") or {}).get("transport")
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", []))
        if (op.get("TransactionRead") or op.get("TransactionWrite")
            or op.get("TransactionUpdate"))
    } - {None})
    if fixed_bases and all(index is not None for index in fixed_bases.values()):
        resources = [
            Resource(f"mmio{index}", "MmioResource", True, base)
            for base, index in sorted(
                fixed_bases.items(), key=lambda item: (int(item[1]), item[0]))
        ]
    elif not transaction_transports:
        resources = [Resource("mmio0", "MmioResource", True, "base")]
    else:
        resources = []
    resources.extend(
        Resource(f"transaction{index}", "TransactionResource", True,
                 transport)
        for index, transport in enumerate(transaction_transports))
    if has_clk:
        resources.append(Resource("clk0", "ClockResource", True, "clk"))
    if has_irq:
        resources.append(Resource("irq0", "IrqResource", True))

    # registers from register_map
    registers = [RegisterDesc(name=r["name"], width=r["width"], offset=r["offset"])
                 for r in formal.get("register_map", [])]

    # invariants: minimal
    invariants = []
    if has_irq:
        invariants.append("forall line: UInt. line < num_irqs -> valid_interrupt_line(line)")

    return DeviceSpec(
        name=name, cls=cls, state=state, resources=resources,
        registers=registers, functions=fn_specs, invariants=invariants,
        source=source_path,
    )
