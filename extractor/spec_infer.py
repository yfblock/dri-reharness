"""Semantic inference: RIS modules → FunctionSpec → DeviceSpec (plan M3/M4).

Enriches extracted RIS with backend-independent semantics:
  - role/context from callback-table field binding (bindings_linux), falling
    back to function-name hints
  - signature: C param types → abstract types (LogicalIRQ, DeviceState, UInt...)
  - binds: MMIO base + device state from the address expressions used in the RIS
  - effects: writes_register(REG) for each accessed Symbolic register, plus a
    role-derived event effect (e.g. interrupt_ack → clears_interrupt(line))
  - requires/ensures: role-derived Hoare-style skeletons
"""
from __future__ import annotations
import re
import os
from typing import Optional


from .spec import (FunctionSpec, DeviceSpec, Signature, Param, Binding,
                   RegisterDesc, StateField, Resource, Effect, reg_effect,
                   event_effect)
from .ast_model import Func
from .formal import walk_leaf_ops, walk_all_ops

_MEMBER_BASE = re.compile(r"^([A-Za-z_]\w*)->\w+$")
_VAR_BASE = re.compile(r"^[A-Za-z_]\w+$")

# role → (event effect text, ensure text, require text)
ROLE_SEMANTICS = {
    "interrupt_ack":    ("clears_interrupt(line)",   "interrupt_pending[line] == false", None),
    "interrupt_mask":   ("masks_interrupt(line)",    "interrupt_enabled[line] == false", None),
    "interrupt_unmask": ("unmasks_interrupt(line)",  "interrupt_enabled[line] == true",  None),
    "set_irq_type":     ("sets_irq_type(line)",      "irq_type[line] == configured",     None),
    "interrupt_handler":("handles_interrupt()",      "interrupt_serviced",               None),
    "reset":            ("resets_device()",          "device_state == RESET",            None),
    "init":             ("initializes_device()",     "device_state == READY",            None),
    "probe":            ("initializes_device()",     "device_state == READY",            "resources_available"),
    "remove":           ("releases_device()",        "device_state == OFF",              None),
    "suspend":          ("suspends_device()",        "device_state == SUSPENDED",        None),
    "resume":           ("resumes_device()",         "device_state == READY",            None),
    "setup_queue":      ("configures_queue(queue)",  "queue_ready[queue] == true",       None),
    "notify":           ("notifies_queue(queue)",    "queue_notified[queue]",            None),
    "get_status":       ("reads_status()",           None, None),
    "set_status":       ("writes_status()",          None, None),
    "read_config":      ("reads_config(offset)",     None, None),
    "write_config":     ("writes_config(offset)",    None, None),
}


def _abstract_param_type(ctype: str, role: str) -> str:
    c = (ctype or "").strip()
    cl = c.lower()
    if "irq_data" in cl or "irq" in cl and "*" in c:
        return "LogicalIRQ"
    if "platform_device" in cl or "device" in cl and "*" in c:
        return "DeviceState"
    if "virtio_device" in cl:
        return "DeviceState"
    if "*" in c:
        return "DeviceState"
    if any(k in cl for k in ("u8", "u16", "u32", "u64", "int", "unsigned", "long",
                             "size_t", "bool", "_t")):
        return "UInt"
    if c in ("void", ""):
        return "Void"
    return "UInt"


def _abstract_return_type(ctype: str) -> str:
    c = (ctype or "").strip().lower()
    if not c or c == "void":
        return "Void"
    if any(k in c for k in ("int", "long", "u8", "u16", "u32", "u64", "size_t")):
        return "UInt"
    return "UInt"


def _base_exprs_of_module(module: dict) -> tuple[list[str], list[str]]:
    """Return (base_exprs, struct_vars) used by this module's addresses."""
    bases: list[str] = []
    for op in walk_leaf_ops(module["ops"]):
        addr = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite") or {}).get("addr", {})
        dev = addr.get("Symbolic", {}).get("device") if "Symbolic" in addr else None
        if dev:
            bases.append(dev)
            m = _MEMBER_BASE.match(dev)
            if m:
                bases.append(m.group(1))  # struct var
    return bases, []


def _bound_mmio_resources(formal: dict) -> dict[str, int | None]:
    bases: dict[str, int | None] = {}
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    # Multi-translation-unit extraction predates subsystem materialization and
    # records the empty default as a list.  Treat that representation as no
    # summaries rather than imposing the single-TU dictionary schema on it.
    summaries = (summary_groups.get("gpio_generic", [])
                 if isinstance(summary_groups, dict) else [])
    for summary in summaries:
        for entries in summary.get("resolved_fields", {}).values():
            for entry in entries:
                base = entry.get("base")
                if base and re.fullmatch(r"[A-Za-z_]\w*", base):
                    bases.setdefault(base, entry.get("resource_index"))
    return bases


def infer_function_spec(func: Func, module: dict, role: str, context: str,
                        is_callback_entry: bool, callback_table: Optional[str],
                        source_path: str) -> FunctionSpec:
    # signature
    params = [Param(
        name=p[0],
        type=func.synthetic_param_types.get(
            p[0], _abstract_param_type(p[1], role)))
              for p in func.params if p[0]]
    result_type = func.synthetic_return_type
    if func.cursor is not None and func.cursor.result_type:
        result_type = func.cursor.result_type.spelling
    sig = Signature(params=params, return_type=_abstract_return_type(result_type))

    # binds: dev + base from the address expressions
    binds: list[Binding] = []
    base_exprs = [b for b in _base_exprs_of_module(module)[0]
                  if _MEMBER_BASE.match(b) or _VAR_BASE.match(b)]
    base_field = next((b for b in base_exprs if "->" in b or b.endswith("base")), None)
    struct_var = None
    if base_field:
        mm = _MEMBER_BASE.match(base_field)
        if mm:
            struct_var = mm.group(1)
            binds.append(Binding("dev", "DeviceState", struct_var))
        binds.append(Binding("base", "MmioBase", base_field))
    elif base_exprs:
        binds.append(Binding("base", "MmioBase", base_exprs[0]))

    # effects: writes_register for each Symbolic register touched
    effects: list[Effect] = []
    seen_regs: set[str] = set()
    for op in walk_leaf_ops(module["ops"]):
        addr = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite") or {}).get("addr", {})
        if "Symbolic" in addr:
            reg = addr["Symbolic"]["register"]
            if reg not in seen_regs and ("Write" in op or "ReadModifyWrite" in op):
                seen_regs.add(reg)
                effects.append(reg_effect(reg))
    # role event effect
    sem = ROLE_SEMANTICS.get(role)
    if sem and sem[0]:
        effects.append(event_effect(sem[0]))

    requires = []
    ensures = []
    if sem:
        if sem[2]:
            requires.append(sem[2])
        if sem[1]:
            ensures.append(sem[1])

    loc = func.cursor.location if func.cursor is not None else None
    actual_source = (loc.file.name if loc and loc.file else source_path)
    return FunctionSpec(
        name=module["name"], signature=sig, role=role, context=context,
        source=f"{os.path.basename(actual_source)}:{func.line}",
        binds=binds, requires=requires, ensures=ensures, effects=effects,
        ris_ref=module["name"], is_callback_entry=is_callback_entry,
        callback_table=callback_table,
    )


def infer_function_specs(formal: dict, funcs: list[Func], source_text: str,
                         source_path: str,
                         callback_entries: set[str]) -> tuple[list[FunctionSpec], dict]:
    names = {f.name for f in funcs}
    cb_bindings = parse_callback_bindings(source_text, names)
    name_counts: dict[str, int] = {}
    for func in funcs:
        name_counts[func.name] = name_counts.get(func.name, 0) + 1
    func_by_module = {(f.module_name or f.name): f for f in funcs}

    specs: list[FunctionSpec] = []
    for m in formal["modules"]:
        fn = func_by_module.get(m["name"])
        if fn is None:
            continue
        # Name-only callback parsing is authoritative only when the original C
        # function name is unique across the selected translation units.
        if fn.synthetic_role:
            cb = {
                "role": fn.synthetic_role,
                "context": fn.synthetic_context or "thread",
                "table": fn.synthetic_callback_table.split(".", 1)[0],
                "field": (fn.synthetic_callback_table.split(".", 1)[1]
                          if "." in fn.synthetic_callback_table else fn.name),
            }
            cb_bindings[fn.name] = cb
        else:
            cb = (cb_bindings.get(fn.name)
              if name_counts.get(fn.name, 0) == 1 else None)
        if cb:
            role, context = cb["role"], cb["context"]
            table = f"{cb['table']}.{cb['field']}"
        else:
            hint = name_role_hints(fn.name)
            symbol = fn.symbol_id or fn.name
            role = hint or ("helper" if symbol not in callback_entries else "unknown")
            context = "irq" if role.startswith("interrupt") or role == "set_irq_type" else "thread"
            table = None
        is_entry = bool(fn.synthetic_role) or (
            (fn.symbol_id or fn.name) in callback_entries)
        specs.append(infer_function_spec(fn, m, role, context, is_entry, table, source_path))
    return specs, cb_bindings


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
    if fixed_bases and all(index is not None for index in fixed_bases.values()):
        resources = [
            Resource(f"mmio{index}", "MmioResource", True, base)
            for base, index in sorted(
                fixed_bases.items(), key=lambda item: (int(item[1]), item[0]))
        ]
    else:
        resources = [Resource("mmio0", "MmioResource", True, "base")]
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


# ═══════════════════════════════════════════════════════════════════
# Linux callback-table recognition (consolidated from bindings_linux.py)
# ═══════════════════════════════════════════════════════════════════
FIELD_ROLE: dict[str, tuple[str, str]] = {
    # irq_chip
    "irq_ack": ("interrupt_ack", "irq"),
    "irq_mask": ("interrupt_mask", "irq"),
    "irq_unmask": ("interrupt_unmask", "irq"),
    "irq_mask_ack": ("interrupt_mask", "irq"),
    "irq_eoi": ("interrupt_ack", "irq"),
    "irq_enable": ("interrupt_unmask", "irq"),
    "irq_disable": ("interrupt_mask", "irq"),
    "irq_set_type": ("set_irq_type", "irq"),
    "irq_set_affinity": ("set_irq_type", "irq"),
    "irq_set_wake": ("set_irq_type", "irq"),
    "handle_irq": ("interrupt_handler", "irq"),
    "irq_handler": ("interrupt_handler", "irq"),
    "parent_handler": ("interrupt_handler", "irq"),
    "init_hw": ("init", "boot"),
    # platform_driver / pci_driver / etc.
    "probe": ("probe", "boot"),
    "remove": ("remove", "thread"),
    "shutdown": ("remove", "thread"),
    "suspend": ("suspend", "sleepable"),
    "resume": ("resume", "sleepable"),
    "freeze": ("suspend", "sleepable"),
    "thaw": ("resume", "sleepable"),
    "poweroff": ("suspend", "sleepable"),
    "restore": ("resume", "sleepable"),
    # virtio_config_ops
    "get": ("read_config", "thread"),
    "get_multiple": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_multiple": ("write_config", "thread"),
    "generation": ("get_status", "thread"),
    "get_status": ("get_status", "thread"),
    "set_status": ("set_status", "thread"),
    "reset": ("reset", "thread"),
    "find_vqs": ("setup_queue", "thread"),
    "del_vqs": ("remove", "thread"),
    "get_shm_region": ("read_config", "thread"),
    "notify_vq": ("notify", "thread"),
    "notify": ("notify", "thread"),
    "callback": ("interrupt_handler", "irq"),
    "event": ("write_config", "thread"),
    # sdhci_ops logical register accessors
    "read_l": ("read_config", "thread"),
    "read_w": ("read_config", "thread"),
    "read_b": ("read_config", "thread"),
    "write_l": ("write_config", "thread"),
    "write_w": ("write_config", "thread"),
    "write_b": ("write_config", "thread"),
    # clk_ops
    "prepare": ("init", "thread"),
    "unprepare": ("remove", "thread"),
    "enable": ("init", "thread"),
    "disable": ("remove", "thread"),
    "is_enabled": ("get_status", "thread"),
    "recalc_rate": ("read_config", "thread"),
    "determine_rate": ("read_config", "thread"),
    "round_rate": ("read_config", "thread"),
    "set_rate": ("write_config", "thread"),
    # usb_ep_ops
    "alloc_request": ("init", "thread"),
    "free_request": ("remove", "thread"),
    "queue": ("setup_queue", "thread"),
    "dequeue": ("remove", "thread"),
    "set_halt": ("write_config", "thread"),
    "set_wedge": ("write_config", "thread"),
    "fifo_status": ("get_status", "thread"),
    "fifo_flush": ("write_config", "thread"),
    # usb_gadget_ops
    "get_frame": ("get_status", "thread"),
    "wakeup": ("resume", "thread"),
    "func_wakeup": ("resume", "thread"),
    "set_remote_wakeup": ("write_config", "thread"),
    "set_selfpowered": ("write_config", "thread"),
    "vbus_session": ("write_config", "thread"),
    "vbus_draw": ("write_config", "thread"),
    "pullup": ("write_config", "thread"),
    "udc_start": ("init", "thread"),
    "udc_stop": ("remove", "thread"),
    "udc_set_speed": ("write_config", "thread"),
    "match_ep": ("read_config", "thread"),
    # hc_driver
    "irq": ("interrupt_handler", "irq"),
    "start": ("init", "thread"),
    "stop": ("remove", "thread"),
    "urb_enqueue": ("setup_queue", "thread"),
    "urb_dequeue": ("remove", "thread"),
    "endpoint_disable": ("remove", "thread"),
    "endpoint_reset": ("reset", "thread"),
    "get_frame_number": ("get_status", "thread"),
    "hub_status_data": ("get_status", "thread"),
    "hub_control": ("write_config", "thread"),
    "clear_tt_buffer_complete": ("remove", "thread"),
    "bus_suspend": ("suspend", "sleepable"),
    "bus_resume": ("resume", "sleepable"),
    "map_urb_for_dma": ("setup_queue", "thread"),
    "unmap_urb_for_dma": ("remove", "thread"),
    "free_dev": ("remove", "thread"),
    "reset_device": ("reset", "thread"),
    # gpio_chip (beyond irq)
    "get_direction": ("read_config", "thread"),
    "direction_input": ("write_config", "thread"),
    "direction_output": ("write_config", "thread"),
    "get": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_config": ("write_config", "thread"),
    "request": ("init", "thread"),
    "free": ("remove", "thread"),
    # file_operations
    "open": ("init", "thread"),
    "read": ("read_config", "thread"),
    "write": ("write_config", "thread"),
    # generic
    "init": ("init", "boot"),
    "exit": ("remove", "thread"),
}

# Fallback table when a callback reference is outside a recognizable struct
# initializer.  Initializer-aware parsing below is authoritative.
FIELD_TABLE = {
    "irq_ack": "irq_chip", "irq_mask": "irq_chip", "irq_unmask": "irq_chip",
    "irq_mask_ack": "irq_chip", "irq_eoi": "irq_chip", "irq_enable": "irq_chip",
    "irq_disable": "irq_chip", "irq_set_type": "irq_chip", "handle_irq": "irq_chip",
    "parent_handler": "gpio_irq_chip",
    "init_hw": "gpio_irq_chip",
    "probe": "platform_driver", "remove": "platform_driver", "shutdown": "platform_driver",
    "suspend": "dev_pm_ops", "resume": "dev_pm_ops", "freeze": "dev_pm_ops",
    "thaw": "dev_pm_ops", "poweroff": "dev_pm_ops", "restore": "dev_pm_ops",
    "find_vqs": "virtio_config_ops", "del_vqs": "virtio_config_ops",
    "get_status": "virtio_config_ops", "set_status": "virtio_config_ops",
    "reset": "virtio_config_ops", "generation": "virtio_config_ops",
    "get_shm_region": "virtio_config_ops", "notify_vq": "virtio_config_ops",
    "request": "gpio_chip", "free": "gpio_chip",
    "get_direction": "gpio_chip", "direction_input": "gpio_chip",
    "direction_output": "gpio_chip", "set_config": "gpio_chip",
    "get": "gpio_chip", "set": "gpio_chip",
    "get_multiple": "gpio_chip", "set_multiple": "gpio_chip",
    "alloc_request": "usb_ep_ops", "free_request": "usb_ep_ops",
    "queue": "usb_ep_ops", "dequeue": "usb_ep_ops",
    "set_halt": "usb_ep_ops", "set_wedge": "usb_ep_ops",
    "fifo_status": "usb_ep_ops", "fifo_flush": "usb_ep_ops",
    "get_frame": "usb_gadget_ops", "wakeup": "usb_gadget_ops",
    "set_remote_wakeup": "usb_gadget_ops",
    "set_selfpowered": "usb_gadget_ops", "pullup": "usb_gadget_ops",
    "udc_start": "usb_gadget_ops", "udc_stop": "usb_gadget_ops",
    "match_ep": "usb_gadget_ops",
    "urb_enqueue": "hc_driver", "urb_dequeue": "hc_driver",
    "endpoint_disable": "hc_driver", "endpoint_reset": "hc_driver",
    "get_frame_number": "hc_driver", "hub_status_data": "hc_driver",
    "hub_control": "hc_driver", "bus_suspend": "hc_driver",
    "bus_resume": "hc_driver", "map_urb_for_dma": "hc_driver",
    "unmap_urb_for_dma": "hc_driver", "free_dev": "hc_driver",
    "reset_device": "hc_driver",
    "start": "hc_driver", "stop": "hc_driver", "irq": "hc_driver",
    "read_l": "sdhci_ops", "read_w": "sdhci_ops", "read_b": "sdhci_ops",
    "write_l": "sdhci_ops", "write_w": "sdhci_ops", "write_b": "sdhci_ops",
    "callback": "virtqueue_info", "event": "input_dev",
}


_DESIGNATED_INIT = re.compile(
    r"(?:\.|->)\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)(?=\s*[,};]|\s*$)"
)

_STRUCT_INIT = re.compile(
    r"\bstruct\s+([A-Za-z_]\w*)\s+[A-Za-z_]\w*(?:\s*\[[^]]*\])?\s*=\s*\{"
)

_KNOWN_CALLBACK_TABLES = {
    "irq_chip", "gpio_chip", "platform_driver", "pci_driver", "amba_driver",
    "virtio_config_ops", "virtio_driver", "clk_ops", "dev_pm_ops", "file_operations",
    "gpio_irq_chip",
    "usb_ep_ops", "usb_gadget_ops", "hc_driver", "sdhci_ops",
    "virtqueue_info",
}


def _initializer_blocks(src: str):
    """Yield `(struct_type, initializer_text)` with balanced-brace parsing."""
    for m in _STRUCT_INIT.finditer(src):
        table = m.group(1)
        if table not in _KNOWN_CALLBACK_TABLES:
            continue
        start = m.end() - 1
        depth = 0
        for i in range(start, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    yield table, src[start + 1:i]
                    break


def _strip_comments_strings(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    out = []
    for ln in src.splitlines():
        idx = ln.find("//")
        if idx >= 0:
            ln = ln[:idx]
        out.append(ln)
    src = "\n".join(out)
    # remove string/char literals
    src = re.sub(r'"(\\.|[^"\\])*"', ' "" ', src)
    src = re.sub(r"'(\\.|[^'\\])*'", " ' ' ", src)
    return src


def parse_callback_bindings(source_text: str, target_names: set[str]) -> dict[str, dict]:
    """funcname → {field, role, context, table} for each `.field = funcname`
    where funcname is a target function."""
    src = _strip_comments_strings(source_text)
    out: dict[str, dict] = {}

    def signature_table(fname: str, field: str) -> str | None:
        m = re.search(
            rf"\b{re.escape(fname)}\s*\((.*?)\)\s*\{{", src, flags=re.S)
        params = m.group(1) if m else ""
        # gpio_irq_chip callbacks such as init_hw receive a gpio_chip pointer,
        # so the parameter type alone is ambiguous.  Prefer the field's
        # authoritative table class before applying the broad gpio_chip rule.
        if field in {"init_hw", "parent_handler"}:
            return "gpio_irq_chip"
        if "struct gpio_chip" in params:
            return "gpio_chip"
        if "struct irq_data" in params:
            return "irq_chip"
        if "struct clk_hw" in params:
            return "clk_ops"
        if "struct virtio_device" in params:
            return ("virtio_driver" if field in {
                "probe", "remove", "freeze", "restore"}
                else "virtio_config_ops")
        if "struct virtqueue" in params:
            return "virtqueue_info"
        if "struct input_dev" in params:
            return "input_dev"
        if "struct usb_ep" in params:
            return "usb_ep_ops"
        if "struct usb_gadget" in params:
            return "usb_gadget_ops"
        if "struct usb_hcd" in params:
            return "hc_driver"
        if "struct device" in params and field in {
                "suspend", "resume", "freeze", "thaw", "poweroff", "restore"}:
            return "dev_pm_ops"
        return None
    # Prefer the actual enclosing struct type.  Field names such as `get`,
    # `set`, and `probe` are ambiguous without this context.
    for table, block in _initializer_blocks(src):
        for m in _DESIGNATED_INIT.finditer(block):
            field, fname = m.group(1), m.group(2)
            if fname not in target_names:
                continue
            role_ctx = FIELD_ROLE.get(field)
            if role_ctx is None:
                continue
            role, ctx = role_ctx
            out[fname] = {
                "field": field,
                "role": role,
                "context": ctx,
                "table": table,
            }
        if table == "virtqueue_info":
            for positional in re.finditer(
                    r"\{\s*(?:\"\"|[A-Za-z_]\w*)\s*,\s*"
                    r"([A-Za-z_]\w*)\s*\}", block):
                fname = positional.group(1)
                if fname in target_names:
                    out[fname] = {
                        "field": "callback", "role": "interrupt_handler",
                        "context": "irq", "table": "virtqueue_info",
                    }

    # Fallback for macro-generated or otherwise nonstandard initializers.
    for m in _DESIGNATED_INIT.finditer(src):
        field, fname = m.group(1), m.group(2)
        if fname not in target_names or fname in out:
            continue
        role_ctx = FIELD_ROLE.get(field)
        if role_ctx is None:
            continue
        role, ctx = role_ctx
        table = signature_table(fname, field) or FIELD_TABLE.get(field, "ops")
        out[fname] = {
            "field": field,
            "role": role,
            "context": ctx,
            "table": table,
        }

    # Macro-declared PM tables do not contain designated initializers in the
    # preprocessed source text retained by the artifact corpus.
    for m in re.finditer(
            r"DEFINE_(?:SIMPLE_)?DEV_PM_OPS\s*\(\s*\w+\s*,\s*"
            r"([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)", src):
        for field, fname in (("suspend", m.group(1)), ("resume", m.group(2))):
            if fname in target_names:
                role, ctx = FIELD_ROLE[field]
                out[fname] = {
                    "field": field, "role": role, "context": ctx,
                    "table": "dev_pm_ops",
                }

    # Some platform drivers register the probe callback as a macro argument
    # instead of storing it in ``struct platform_driver.probe``.
    for match in re.finditer(
            r"\bmodule_platform_driver_probe\s*\(\s*[A-Za-z_]\w*\s*,\s*"
            r"([A-Za-z_]\w*)\s*\)", src):
        fname = match.group(1)
        if fname in target_names:
            out[fname] = {
                "field": "probe", "role": "probe", "context": "boot",
                "table": "platform_driver",
            }

    # Direct IRQ registration is a callback binding even though no ops table
    # initializer exists.
    for fname in target_names:
        if re.search(
                rf"\b(?:devm_)?request_irq\s*\([^;]*\b{re.escape(fname)}\b",
                src, flags=re.S):
            out.setdefault(fname, {
                "field": "handler", "role": "interrupt_handler",
                "context": "irq", "table": "irq_handler",
            })
    return out


def name_role_hints(func_name: str) -> str | None:
    """Fallback role inference from function name keywords (weaker than field)."""
    n = func_name.lower()
    hints = [
        ("probe", "probe"), ("remove", "remove"), ("shutdown", "remove"),
        ("suspend", "suspend"), ("resume", "resume"),
        ("ack_irq", "interrupt_ack"), ("mask_irq", "interrupt_mask"),
        ("unmask_irq", "interrupt_unmask"), ("set_irq_type", "set_irq_type"),
        ("irq_handler", "interrupt_handler"), ("handler", "interrupt_handler"),
        ("setup_queue", "setup_queue"), ("init_device", "init"),
        ("notify", "notify"), ("get_status", "get_status"), ("set_status", "set_status"),
        ("reset", "reset"), ("init", "init"),
    ]
    for kw, role in hints:
        if kw in n:
            return role
    return None


# ═══════════════════════════════════════════════════════════════════
# Source facts extraction (.facts) — plan M9
# ═══════════════════════════════════════════════════════════════════
import clang.cindex as _cx
from .spec import FactsSpec, StructDef, StructField, ResourceFact
import os as _os

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.M)
_ERROR_RE = re.compile(r'return\s+(-(?:ENOMEM|ENODEV|ENXIO|EINVAL|ENOTSUPP|EIO|EBUSY|EAGAIN|EFAULT|ENOSYS|ERANGE|ENOSPC)|PTR_ERR\([^)]*\))')

# resource acquisition call patterns → (resource kind, binds_to heuristic)
_RESOURCE_CALLS = [
    ("devm_platform_ioremap_resource", "MmioResource", "g->base"),
    ("devm_ioremap_resource", "MmioResource", "g->base"),
    ("devm_ioremap", "MmioResource", "base"),
    ("devm_request_mem_region", "MmioResource", None),
    ("platform_get_resource", "MmioResource", None),
    ("devm_clk_get_enabled", "ClockResource", "g->clk"),
    ("devm_clk_get", "ClockResource", "g->clk"),
    ("clk_get", "ClockResource", "g->clk"),
    ("platform_get_irq", "IrqResource", None),
    ("devm_request_irq", "IrqResource", None),
]

# notable subsystem helper calls worth surfacing to the LLM
_HELPER_CALLS = {
    "devm_gpiochip_add_data", "gpiochip_add_data", "bgpio_init",
    "platform_driver_register", "platform_driver_unregister",
    "virtio_device_ready", "register_virtio_device", "virtio_add_status",
    "virtio_finalize_features", "devm_regmap_init_mmio",
    "clk_prepare_enable", "clk_disable_unprepare",
}


def _target_structs(tu, target_file: str) -> list[StructDef]:
    tgt = _os.path.abspath(target_file)
    out: list[StructDef] = []
    for c in tu.cursor.walk_preorder():
        if c.kind != _cx.CursorKind.STRUCT_DECL or not c.is_definition():
            continue
        f = c.location.file
        if f is None or _os.path.abspath(f.name) != tgt:
            continue
        if not c.spelling:
            continue   # anonymous struct
        fields = [StructField(ch.spelling, ch.type.spelling if ch.type else "")
                  for ch in c.get_children() if ch.kind == _cx.CursorKind.FIELD_DECL]
        if fields:
            out.append(StructDef(c.spelling, fields))
    return out


def infer_facts(source_text: str, source_path: str, tu, macros,
                callback_bindings: dict, register_names: set[str],
                formal: dict | None = None, driver_name: str = "") -> FactsSpec:
    includes = _INCLUDE_RE.findall(source_text)
    structs = _target_structs(tu, source_path)

    # driver prefix (e.g. GPIO, VIRTIO, AHCI) from register names + driver name
    prefixes: set[str] = set()
    for rn in register_names:
        pfx = rn.split("_")[0]
        if pfx:
            prefixes.add(pfx.upper())
    if driver_name:
        prefixes.add(re.split(r"[^A-Za-z0-9]", driver_name)[0].upper())

    # names referenced by RIS / callbacks / resources / errors / helpers — these
    # constants are reconstruction-relevant even without a driver prefix
    referenced: set[str] = set(register_names)
    # Source-local numeric defines are part of the driver's semantics even
    # when they appear only in pure scalar callback arithmetic (and therefore
    # never enter the MMIO-only RIS).  Header-wide constants remain filtered
    # below; this adds only macros defined by the target source itself.
    referenced |= set(re.findall(
        r"^\s*#\s*define\s+([A-Za-z_]\w*)", source_text, flags=re.M))
    # PCI IDs are reconstruction-critical even when they come from a kernel
    # header (for example PCI_VENDOR_ID_INTEL).  Keep identifiers used as
    # PCI_DEVICE arguments instead of filtering them as header-wide noise.
    for pci_args in re.findall(r"\bPCI_DEVICE\s*\(([^)]*)\)", source_text):
        referenced |= set(re.findall(r"\b[A-Za-z_]\w*\b", pci_args))
    if formal is not None:
        from .formal import walk_all_ops
        for m in formal["modules"]:
            for op in walk_all_ops(m["ops"]):
                if "Cond" in op:
                    referenced |= _vars_in_expr(op["Cond"]["guard"])
                elif "Write" in op:
                    referenced |= _vars_in_expr(op["Write"].get("value"))
                elif "ReadModifyWrite" in op:
                    referenced |= _vars_in_expr(op["ReadModifyWrite"].get("transform"))
    referenced |= set(callback_bindings.keys())
    for h in _HELPER_CALLS:
        if h in source_text:
            referenced.add(h)

    # constants = int macros that are reconstruction-relevant.
    # Drop compiler builtins, kernel-wide config/arch noise, and anything not
    # driver-prefixed or referenced (recom.md §"Trim .facts").
    constants: dict = {}
    for name in macros.names():
        if name.startswith("_") or name in register_names:
            continue
        if _is_noise_constant(name):
            continue
        off = macros.offset(name)
        if off is None:
            continue
        pfx = name.split("_")[0].upper()
        if name in referenced or pfx in prefixes:
            constants[name] = off

    # callbacks: {table.field: fn}
    callbacks: dict = {}
    for fname, info in callback_bindings.items():
        field = info["field"]
        table = info["table"]
        callbacks[f"{table}.{field}"] = fname

    # resources: scan for acquisition calls
    resources: list[ResourceFact] = []
    for i, (call, _kind, binds) in enumerate(_RESOURCE_CALLS):
        if re.search(rf"\b{re.escape(call)}\s*\(", source_text):
            resources.append(ResourceFact(f"{_kind.lower()[:4]}{i}", call, binds))
    # dedupe by acquisition, keep first, renumber
    seen = set()
    dedup = []
    for r in resources:
        if r.acquisition in seen:
            continue
        seen.add(r.acquisition)
        dedup.append(r)

    error_paths = sorted(set(_ERROR_RE.findall(source_text)))
    helper_calls = sorted({c for c in _HELPER_CALLS if c in source_text})

    return FactsSpec(
        source=source_path, includes=includes, structs=structs,
        constants=constants, callbacks=callbacks, resources=dedup,
        error_paths=[f"return {e}" for e in error_paths],
        helper_calls=helper_calls,
    )


# kernel-wide / config / arch constants that are NOT reconstruction-relevant
_NOISE_PREFIXES = (
    "CONFIG_", "KASAN_", "TASK_", "pt_regs_", "CPUINFO_", "BUG_", "TAINT_",
    "BITS_PER_", "PAGE_", "VM_", "SLAB_", "KMALLOC_", "NR_", "MAX_", "MIN_",
    "ULONG", "LONG", "UINT", "INT", "CHAR", "SIZE_", "ALIGNOF", "offsetof",
    "container_of", "READ", "WRITE", "unix", "linux",
)


def _is_noise_constant(name: str) -> bool:
    up = name
    for p in _NOISE_PREFIXES:
        if up.startswith(p):
            return True
    # all-lowercase or single-token generic (unix, linux, etc.) — drop
    if name.islower() and len(name) <= 8:
        return True
    return False


def _vars_in_expr(e) -> set[str]:
    if e is None:
        return set()
    out: set[str] = set()
    if "Var" in e:
        v = e["Var"]
        if re.fullmatch(r"[A-Za-z_]\w*", v):
            out.add(v)
    if "BinOp" in e:
        out |= _vars_in_expr(e["BinOp"].get("left"))
        out |= _vars_in_expr(e["BinOp"].get("right"))
    if "Ite" in e:
        out |= _vars_in_expr(e["Ite"].get("guard"))
        out |= _vars_in_expr(e["Ite"].get("then"))
        out |= _vars_in_expr(e["Ite"].get("else"))
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"].get("expr"))
    return out
