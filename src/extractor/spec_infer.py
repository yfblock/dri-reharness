"""Semantic inference: RIS modules → FunctionSpec → DeviceSpec (plan M3/M4).

Enriches extracted RIS with backend-independent semantics:
  - role/context from callback-table field binding (bindings_linux), falling
    back to function-name hints
  - signature: C param types → abstract types (LogicalIRQ, DeviceState, UInt...)
  - binds: MMIO base + device state from the address expressions used in the RIS
  - effects: writes_register(REG) and typed non-MMIO transactions, plus a
    role-derived event effect (e.g. interrupt_ack → clears_interrupt(line))
  - requires/ensures: role-derived Hoare-style skeletons
"""
from __future__ import annotations
import re
import os
from typing import Optional
import clang.cindex as _cx


from .spec import (FunctionSpec, DeviceSpec, Signature, Param, Binding,
                   RegisterDesc, StateField, Resource, Effect, reg_effect,
                   event_effect, PUBLIC_CALLBACK_TYPES)
from .ast_model import Func, function_symbol_id
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
    seen_transactions: set[tuple[str, str, str]] = set()
    for op in walk_leaf_ops(module["ops"]):
        addr = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite") or {}).get("addr", {})
        if "Symbolic" in addr:
            reg = addr["Symbolic"]["register"]
            if reg not in seen_regs and ("Write" in op or "ReadModifyWrite" in op):
                seen_regs.add(reg)
                effects.append(reg_effect(reg))
        transaction_kind = next((kind for kind in (
            "TransactionRead", "TransactionWrite", "TransactionUpdate")
            if kind in op), None)
        if transaction_kind:
            body = op[transaction_kind]
            transport = body.get("transport", "unknown")
            selector = body.get("selector")
            key = (transaction_kind, transport, repr(selector))
            if key not in seen_transactions:
                seen_transactions.add(key)
                verb = {"TransactionRead": "reads",
                        "TransactionWrite": "writes",
                        "TransactionUpdate": "updates"}[transaction_kind]
                effects.append(Effect(
                    "transaction",
                    f"{verb}_transaction({transport})",
                    {"operation": transaction_kind,
                     "transport": transport,
                     "selector": selector}))
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
                         callback_entries: set[str],
                         callback_bindings: dict[str, dict] | None = None,
                         callback_signatures: dict[str, dict] | None = None
                         ) -> tuple[list[FunctionSpec], dict]:
    cb_bindings = dict(callback_bindings or {})
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
                "function": fn.name,
                "binding_kind": "synthetic",
            }
            signature = (callback_signatures or {}).get(
                f"{cb['table']}.{cb['field']}")
            if signature is not None:
                cb["signature"] = signature
            cb_bindings[fn.symbol_id or fn.name] = cb
        else:
            cb = cb_bindings.get(fn.symbol_id or fn.name)
        if cb:
            role, context = cb["role"], cb["context"]
            table = f"{cb['table']}.{cb['field']}"
            # Binding and semantic-role evidence are orthogonal.  An
            # AST-proven owner/field with no FIELD_ROLE contract must not
            # erase an independently inferred generic lifecycle role.
            if role == "unknown":
                hint = name_role_hints(fn.name)
                if hint:
                    role = hint
                    context = ("irq" if hint.startswith("interrupt")
                               or hint == "set_irq_type" else "thread")
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

# Some public callback ABIs reuse field names whose meaning is only
# unambiguous in the owning table.  Keep these contracts owner-qualified so
# new drivers can inherit the semantics without basename, compatible-string,
# or private-prefix rules.  Unknown/private owners remain evidence-only.
OWNER_FIELD_ROLE: dict[str, dict[str, tuple[str, str]]] = {
    "clk_ops": {
        "is_prepared": ("get_status", "thread"),
    },
    "sdhci_ops": {
        "voltage_switch": ("write_config", "thread"),
        "set_clock": ("write_config", "thread"),
        "set_bus_width": ("write_config", "thread"),
        "set_uhs_signaling": ("write_config", "thread"),
        "set_power": ("write_config", "thread"),
        "hw_reset": ("reset", "thread"),
    },
    "mmc_host_ops": {
        "start_signal_voltage_switch": ("write_config", "thread"),
        "execute_tuning": ("write_config", "thread"),
        "prepare_hs400_tuning": ("write_config", "thread"),
        "execute_hs400_tuning": ("write_config", "thread"),
        "prepare_sd_hs_tuning": ("write_config", "thread"),
        "execute_sd_hs_tuning": ("write_config", "thread"),
        "hs400_enhanced_strobe": ("write_config", "thread"),
        "request": ("setup_queue", "thread"),
        "request_atomic": ("setup_queue", "atomic"),
    },
    "spi_controller": {
        "setup": ("init", "thread"),
        "cleanup": ("remove", "thread"),
        "prepare_transfer_hardware": ("init", "thread"),
        "unprepare_transfer_hardware": ("remove", "thread"),
        "transfer_one": ("setup_queue", "thread"),
        "transfer_one_message": ("setup_queue", "thread"),
        "handle_err": ("reset", "thread"),
        "set_cs": ("write_config", "thread"),
        "target_abort": ("reset", "thread"),
    },
    "spi_controller_mem_ops": {
        "adjust_op_size": ("write_config", "thread"),
        "supports_op": ("read_config", "thread"),
        "exec_op": ("write_config", "thread"),
    },
}


def _callback_field_role(owner: str, field: str) -> tuple[str, str]:
    owner_roles = OWNER_FIELD_ROLE.get(owner)
    if owner_roles and field in owner_roles:
        return owner_roles[field]
    return FIELD_ROLE.get(field, ("unknown", "thread"))

_CALLBACK_TYPE_ROLES: dict[str, tuple[str, str]] = {
    "irq_handler_t": ("interrupt_handler", "irq"),
}

# Public callback ABI types may attach the existing field-level semantic role.
# Every other struct still receives owner/field binding evidence, but its role
# remains unknown so a source-private field named ``reset`` or ``write`` cannot
# accidentally become executable backend intent.
_ROLE_BEARING_CALLBACK_TYPES = PUBLIC_CALLBACK_TYPES


def _is_function_pointer(ctype) -> bool:
    try:
        canonical = ctype.get_canonical()
        if canonical.kind != _cx.TypeKind.POINTER:
            return False
        pointee = canonical.get_pointee().get_canonical()
        return pointee.kind in {
            _cx.TypeKind.FUNCTIONPROTO, _cx.TypeKind.FUNCTIONNOPROTO}
    except Exception:
        return False


def _function_pointer_signature(ctype) -> dict | None:
    """Return the canonical C ABI represented by a function-pointer type."""
    try:
        canonical = ctype.get_canonical()
        if canonical.kind != _cx.TypeKind.POINTER:
            return None
        function_type = canonical.get_pointee().get_canonical()
        if function_type.kind not in {
                _cx.TypeKind.FUNCTIONPROTO, _cx.TypeKind.FUNCTIONNOPROTO}:
            return None
        params = []
        arguments = (function_type.argument_types()
                     if callable(function_type.argument_types)
                     else function_type.argument_types)
        for argument in arguments:
            param_type = argument.get_canonical()
            params.append({"type": param_type.spelling})
        return {
            "type": canonical.spelling,
            "return_type": function_type.get_result().get_canonical().spelling,
            "params": params,
            "variadic": bool(function_type.is_function_variadic()),
        }
    except Exception:
        return None


def infer_callback_signatures(
        tu, fields: set[str] | None = None,
        bindings: dict[str, dict] | None = None) -> dict[str, dict]:
    """Collect public framework callback field ABIs from the parsed AST."""
    requested = set(fields) if fields is not None else None
    signatures: dict[str, dict] = {}
    if bindings is not None:
        for primary in bindings.values():
            for info in [primary, *primary.get("alternates", [])]:
                table = info.get("table")
                field = info.get("field")
                signature = info.get("signature")
                key = f"{table}.{field}"
                if (isinstance(table, str) and isinstance(field, str)
                        and isinstance(signature, dict)
                        and (requested is None or key in requested)):
                    signatures[key] = signature
        missing = (requested - set(signatures)) if requested is not None else set()
        if not missing:
            return signatures
        requested = missing
    for cursor in tu.cursor.walk_preorder():
        if cursor.kind != _cx.CursorKind.FIELD_DECL:
            continue
        owner = _record_type_name(cursor)
        if owner not in PUBLIC_CALLBACK_TYPES:
            continue
        key = f"{owner}.{cursor.spelling}"
        if requested is not None and key not in requested:
            continue
        signature = _function_pointer_signature(cursor.type)
        if signature is not None:
            signatures[key] = signature
    return signatures


def _record_type_name(field_cursor) -> str | None:
    parent = field_cursor.semantic_parent or field_cursor.lexical_parent
    if parent is not None and parent.kind in {
            _cx.CursorKind.STRUCT_DECL, _cx.CursorKind.UNION_DECL}:
        return parent.spelling or None
    return None


def _named_callback_type(ctype) -> str | None:
    """Return an AST-declared callback typedef, never a guessed C signature."""
    spelling = (ctype.spelling or "").strip()
    if ctype.kind == _cx.TypeKind.TYPEDEF and spelling:
        return spelling
    declaration = ctype.get_declaration()
    if declaration is not None and declaration.kind == _cx.CursorKind.TYPEDEF_DECL:
        return declaration.spelling or None
    return None


def _record_declaration(ctype):
    try:
        current = ctype.get_canonical()
        while current.kind in {
                _cx.TypeKind.CONSTANTARRAY, _cx.TypeKind.INCOMPLETEARRAY,
                _cx.TypeKind.VARIABLEARRAY, _cx.TypeKind.DEPENDENTSIZEDARRAY}:
            current = current.element_type.get_canonical()
        if current.kind == _cx.TypeKind.POINTER:
            current = current.get_pointee().get_canonical()
        declaration = current.get_declaration()
        if declaration is not None and declaration.kind in {
                _cx.CursorKind.STRUCT_DECL, _cx.CursorKind.UNION_DECL}:
            return declaration
    except Exception:
        pass
    return None


def _target_function_refs(cursor, targets: dict[str, Func]) -> list[str]:
    found: list[str] = []
    for node in cursor.walk_preorder():
        ref = node.referenced
        symbol = function_symbol_id(ref)
        if symbol in targets and symbol not in found:
            found.append(symbol)
    return found


def _walk_preorder(cursor, target_files: set[str] | None = None):
    """Walk AST nodes, optionally pruning declarations outside target files.

    References from a target-file expression still resolve to declarations in
    included headers, so the scoped walk retains type/field provenance while
    avoiding a second traversal of every unrelated kernel header declaration.
    """
    if target_files:
        location = cursor.location
        file_cursor = location.file if location is not None else None
        if file_cursor is not None and os.path.abspath(file_cursor.name) not in target_files:
            return
    yield cursor
    for child in cursor.get_children():
        yield from _walk_preorder(child, target_files)


def _function_pointer_fields(cursor) -> list[object]:
    found = []
    seen: set[str] = set()
    for node in cursor.walk_preorder():
        ref = node.referenced
        if (ref is None or ref.kind != _cx.CursorKind.FIELD_DECL
                or not _is_function_pointer(ref.type)):
            continue
        key = ref.get_usr() or f"{_record_type_name(ref)}.{ref.spelling}"
        if key not in seen:
            found.append(ref)
            seen.add(key)
    return found


def _designated_fields(cursor) -> list[object]:
    """Return field declarations named by designated initializer/member refs."""
    found = []
    seen: set[str] = set()
    for node in cursor.walk_preorder():
        if node.kind not in {_cx.CursorKind.MEMBER_REF,
                             _cx.CursorKind.DECL_REF_EXPR}:
            continue
        ref = node.referenced
        if ref is None or ref.kind != _cx.CursorKind.FIELD_DECL:
            continue
        key = ref.get_usr() or f"{_record_type_name(ref)}.{ref.spelling}"
        if key not in seen:
            found.append(ref)
            seen.add(key)
    return found


def _public_field_transfer_roles(tu, target_files: set[str] | None = None
                                 ) -> dict[tuple[str, str], tuple[str, str, str]]:
    """Infer private-field roles from assignments into public callback fields."""
    roles: dict[tuple[str, str], tuple[str, str, str]] = {}
    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind != _cx.CursorKind.BINARY_OPERATOR:
            continue
        tokens = [token.spelling for token in cursor.get_tokens()]
        if "=" not in tokens:
            continue
        children = list(cursor.get_children())
        if len(children) != 2:
            continue
        left_fields = _function_pointer_fields(children[0])
        right_fields = _function_pointer_fields(children[1])
        if not left_fields or not right_fields:
            continue
        for left in left_fields:
            owner = _record_type_name(left)
            if owner not in _ROLE_BEARING_CALLBACK_TYPES:
                continue
            role, context = _callback_field_role(owner, left.spelling)
            if role == "unknown":
                continue
            for right in right_fields:
                right_owner = _record_type_name(right)
                if right_owner and right.spelling:
                    roles.setdefault(
                        (right_owner, right.spelling),
                        (role, context, f"{owner}.{left.spelling}"))
    return roles


def _binding_info(func: Func, field_cursor, kind: str, evidence_cursor,
                  *, table: str | None = None) -> dict | None:
    field = field_cursor.spelling
    owner = table or _record_type_name(field_cursor)
    if not field or not owner:
        return None
    role, context = (
        _callback_field_role(owner, field)
        if owner in _ROLE_BEARING_CALLBACK_TYPES
        else ("unknown", "thread"))
    loc = evidence_cursor.location
    info = {
        "function": func.name,
        "field": field,
        "table": owner,
        "role": role,
        "context": context,
        "binding_kind": kind,
        "public_callback_type": owner in _ROLE_BEARING_CALLBACK_TYPES,
        "source": loc.file.name if loc and loc.file else func.source_path,
        "line": loc.line if loc else func.line,
        "column": loc.column if loc else 0,
    }
    signature = _function_pointer_signature(getattr(field_cursor, "type", None))
    if signature is not None:
        info["signature"] = signature
    return info


def infer_callback_bindings(
        tu, funcs: list[Func], *, target_files: set[str] | None = None
        ) -> dict[str, dict]:
    """Recover typed callback ownership from the AST.

    Bindings are accepted only when libclang proves a function flows into a
    function-pointer struct field (initializer or assignment), or into a named
    callback-typed call parameter.  Function names, driver names, compatible
    strings, Kconfig symbols, and source-private prefixes are not consulted.
    Unknown fields remain role ``unknown`` while retaining owner/field binding.
    """
    targets = {func.symbol_id or func.name: func for func in funcs}
    grouped: dict[str, list[dict]] = {}

    def record(symbol: str, field_cursor, kind: str, evidence_cursor,
               table: str | None = None):
        info = _binding_info(
            targets[symbol], field_cursor, kind, evidence_cursor, table=table)
        if info is None:
            return
        entries = grouped.setdefault(symbol, [])
        identity = (info["table"], info["field"], info["binding_kind"],
                    info["source"], info["line"], info["column"])
        if not any((item["table"], item["field"], item["binding_kind"],
                    item["source"], item["line"], item["column"]) == identity
                   for item in entries):
            entries.append(info)

    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind == _cx.CursorKind.VAR_DECL:
            initializers = [node for node in cursor.get_children()
                            if node.kind == _cx.CursorKind.INIT_LIST_EXPR]
            for initializer in initializers:
                expressions = list(initializer.get_children())
                has_designators = any(
                    _function_pointer_fields(expr) for expr in expressions)
                for expr in expressions:
                    fields = _function_pointer_fields(expr)
                    symbols = _target_function_refs(expr, targets)
                    if len(fields) == 1 and len(symbols) == 1:
                        record(symbols[0], fields[0], "initializer", expr)
                    elif len(symbols) == 1:
                        designated = []
                        for child in expr.get_children():
                            child_symbols = _target_function_refs(child, targets)
                            child_fields = _designated_fields(child)
                            if (len(child_symbols) == 1
                                    and child_symbols[0] == symbols[0]
                                    and len(child_fields) == 1):
                                designated.append(child_fields[0])
                        if not designated:
                            designated = [field for field in
                                          _designated_fields(expr)
                                          if field.spelling == "data"]
                        if len(designated) == 1:
                            kind = ("data_initializer"
                                    if designated[0].spelling == "data"
                                    else "initializer")
                            record(symbols[0], designated[0], kind, expr)
                if has_designators:
                    continue
                declaration = _record_declaration(initializer.type)
                if declaration is None:
                    continue
                fields = [node for node in declaration.get_children()
                          if node.kind == _cx.CursorKind.FIELD_DECL]
                record_initializers = (
                    [expr for expr in expressions
                     if expr.kind == _cx.CursorKind.INIT_LIST_EXPR]
                    if initializer.type.get_canonical().kind in {
                        _cx.TypeKind.CONSTANTARRAY,
                        _cx.TypeKind.INCOMPLETEARRAY,
                        _cx.TypeKind.VARIABLEARRAY,
                        _cx.TypeKind.DEPENDENTSIZEDARRAY}
                    else [initializer])
                for record_initializer in record_initializers:
                    values = list(record_initializer.get_children())
                    for field_cursor, expr in zip(fields, values):
                        symbols = _target_function_refs(expr, targets)
                        if (_is_function_pointer(field_cursor.type)
                                and len(symbols) == 1):
                            record(symbols[0], field_cursor,
                                   "positional_initializer", expr)

        elif cursor.kind == _cx.CursorKind.BINARY_OPERATOR:
            tokens = [token.spelling for token in cursor.get_tokens()]
            if "=" not in tokens:
                continue
            children = list(cursor.get_children())
            if len(children) != 2:
                continue
            fields = _function_pointer_fields(children[0])
            symbols = _target_function_refs(children[1], targets)
            if len(fields) == 1 and len(symbols) == 1:
                record(symbols[0], fields[0], "assignment", cursor)

        elif cursor.kind == _cx.CursorKind.CALL_EXPR:
            callee = cursor.referenced
            if callee is None or callee.kind != _cx.CursorKind.FUNCTION_DECL:
                continue
            params = [node for node in callee.get_children()
                      if node.kind == _cx.CursorKind.PARM_DECL]
            args = list(cursor.get_arguments())
            for param, arg in zip(params, args):
                if not _is_function_pointer(param.type):
                    continue
                callback_type = _named_callback_type(param.type)
                symbols = _target_function_refs(arg, targets)
                if len(symbols) != 1:
                    continue
                if not callback_type:
                    candidate_fields = []
                    for owner_param in params:
                        declaration = _record_declaration(owner_param.type)
                        if declaration is None:
                            continue
                        for field_cursor in declaration.get_children():
                            if (field_cursor.kind == _cx.CursorKind.FIELD_DECL
                                    and field_cursor.spelling == param.spelling
                                    and _is_function_pointer(field_cursor.type)):
                                candidate_fields.append(field_cursor)
                    if len(candidate_fields) == 1:
                        record(symbols[0], candidate_fields[0],
                               "call_assignment", arg)
                    continue
                role, context = _CALLBACK_TYPE_ROLES.get(
                    callback_type, ("unknown", "thread"))
                field = param.spelling or "callback"
                synthetic_field = type("CallbackField", (), {
                    "spelling": field,
                    "semantic_parent": None,
                    "lexical_parent": None,
                })()
                info = _binding_info(
                    targets[symbols[0]], synthetic_field, "call_argument",
                    arg, table=callback_type.removesuffix("_t"))
                if info is not None:
                    info["role"], info["context"] = role, context
                    grouped.setdefault(symbols[0], []).append(info)

    # A private callback field can be dispatched from a public callback.  The
    # dispatcher's already-proven role is stronger evidence than the private
    # field name, and remains valid when the field owner is source-private.
    role_by_symbol: dict[str, tuple[str, str]] = {}
    for symbol, entries in grouped.items():
        for info in entries:
            role = info.get("role", "unknown")
            if role != "unknown":
                role_by_symbol[symbol] = (role, info.get("context", "thread"))
                break
    field_dispatch_roles: dict[tuple[str, str], tuple[str, str, str]] = \
        _public_field_transfer_roles(tu, target_files=target_files)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind != _cx.CursorKind.FUNCTION_DECL:
            continue
        dispatcher = function_symbol_id(cursor)
        role_info = role_by_symbol.get(dispatcher)
        if role_info is None:
            continue
        for call in cursor.walk_preorder():
            if call.kind != _cx.CursorKind.CALL_EXPR:
                continue
            for field in _function_pointer_fields(call):
                owner = _record_type_name(field)
                if owner and field.spelling:
                    field_dispatch_roles.setdefault(
                        (owner, field.spelling),
                        (role_info[0], role_info[1], dispatcher))
    for entries in grouped.values():
        for info in entries:
            if info.get("role") != "unknown":
                continue
            propagated = field_dispatch_roles.get(
                (info.get("table"), info.get("field")))
            if propagated is None:
                continue
            info["role"], info["context"], dispatcher = propagated
            info["role_evidence"] = {
                "kind": ("proven_public_field_transfer"
                          if "::" not in dispatcher and "." in dispatcher
                          else "proven_dispatcher_field"),
                "dispatcher": dispatcher,
                "field": f"{info['table']}.{info['field']}",
            }

    result: dict[str, dict] = {}
    for symbol, entries in grouped.items():
        entries.sort(key=lambda item: (
            item["role"] == "unknown",
            item["field"] != item["role"],
            item["table"], item["field"],
            item["source"], item["line"], item["column"]))
        primary = dict(entries[0])
        if len(entries) > 1:
            primary["alternates"] = entries[1:]
        result[symbol] = primary
    return result


def callback_binding_analysis(bindings: dict[str, dict], funcs: list[Func],
                              callback_entries: set[str]) -> dict:
    func_by_symbol = {func.symbol_id or func.name: func for func in funcs}
    rows = []
    for symbol, primary in bindings.items():
        for info in [primary] + primary.get("alternates", []):
            rows.append({key: info.get(key) for key in (
                "function", "table", "field", "role", "context",
                "binding_kind", "public_callback_type", "source", "line",
                "column", "signature")})
    rows.sort(key=lambda item: (
        item["function"], item["table"], item["field"], item["line"] or 0))
    bound = set(bindings)
    return {
        "bindings": rows,
        "bound_entries": sorted(
            func_by_symbol[symbol].name for symbol in callback_entries & bound
            if symbol in func_by_symbol),
        "unbound_entries": sorted(
            func_by_symbol[symbol].name for symbol in callback_entries - bound
            if symbol in func_by_symbol),
    }


def propagate_callback_dispatch_roles(
        bindings: dict[str, dict], tus,
        *, target_files: set[str] | None = None) -> dict[str, dict]:
    """Propagate proven public dispatch roles across translation units."""
    role_by_symbol: dict[str, tuple[str, str]] = {}
    for symbol, primary in bindings.items():
        for info in [primary] + primary.get("alternates", []):
            role = info.get("role", "unknown")
            if role != "unknown":
                role_by_symbol[symbol] = (role, info.get("context", "thread"))
                break
    field_dispatch_roles: dict[tuple[str, str], tuple[str, str, str]] = {}
    for tu in tus:
        field_dispatch_roles.update(
            _public_field_transfer_roles(tu, target_files=target_files))
    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for tu in tus:
        for cursor in _walk_preorder(tu.cursor, scoped_files):
            if cursor.kind != _cx.CursorKind.FUNCTION_DECL:
                continue
            dispatcher = function_symbol_id(cursor)
            role_info = role_by_symbol.get(dispatcher)
            if role_info is None:
                continue
            for call in cursor.walk_preorder():
                if call.kind != _cx.CursorKind.CALL_EXPR:
                    continue
                for field in _function_pointer_fields(call):
                    owner = _record_type_name(field)
                    if owner and field.spelling:
                        field_dispatch_roles.setdefault(
                            (owner, field.spelling),
                            (role_info[0], role_info[1], dispatcher))
    for primary in bindings.values():
        for info in [primary] + primary.get("alternates", []):
            if info.get("role") != "unknown":
                continue
            propagated = field_dispatch_roles.get(
                (info.get("table"), info.get("field")))
            if propagated is None:
                continue
            info["role"], info["context"], dispatcher = propagated
            info["role_evidence"] = {
                "kind": "proven_dispatcher_field",
                "dispatcher": dispatcher,
                "field": f"{info['table']}.{info['field']}",
            }
    return bindings


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
    "gpio_generic_chip_init", "gpio_irq_chip_set_chip",
    "platform_driver_register", "platform_driver_unregister",
    "virtio_device_ready", "register_virtio_device", "virtio_add_status",
    "virtio_finalize_features", "devm_regmap_init_mmio",
    "clk_prepare_enable", "clk_disable_unprepare",
}


def _has_call(source_text: str, name: str) -> bool:
    """Match a helper invocation, not a longer function name containing it."""
    return re.search(rf"\b{re.escape(name)}\s*\(", source_text) is not None


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
                formal: dict | None = None, driver_name: str = "",
                callback_signatures: dict[str, dict] | None = None
                ) -> FactsSpec:
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
        if _has_call(source_text, h):
            referenced.add(h)

    # constants = int macros that are reconstruction-relevant.
    # Drop compiler builtins, kernel-wide config/arch noise, and anything not
    # driver-prefixed or referenced
    # (docs/plans/output-artifact-recommendations.md §"Trim .facts").
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
    for _symbol, info in callback_bindings.items():
        for binding in [info] + info.get("alternates", []):
            callbacks[f"{binding['table']}.{binding['field']}"] = \
                binding["function"]

    # resources: scan for acquisition calls
    resources: list[ResourceFact] = []

    def resource_policy(call: str, binds: str | None) -> tuple[bool, str | None]:
        """Recover source-level probe policy for acquired resources."""
        if call in {"devm_clk_get_optional_enabled", "devm_clk_get_optional",
                    "clk_get_optional"}:
            return False, "optional_api"
        if call != "devm_clk_get_enabled" or not binds:
            return True, None
        target = re.escape(binds)
        defer_only = re.search(
            rf"IS_ERR\s*\(\s*{target}\s*\)\s*&&\s*"
            rf"PTR_ERR\s*\(\s*{target}\s*\)\s*==\s*-EPROBE_DEFER",
            source_text,
        )
        if defer_only:
            return False, "probe_defer_only"
        return True, None

    for i, (call, _kind, binds) in enumerate(_RESOURCE_CALLS):
        if re.search(rf"\b{re.escape(call)}\s*\(", source_text):
            required, failure_policy = resource_policy(call, binds)
            resources.append(ResourceFact(
                f"{_kind.lower()[:4]}{i}", call, binds,
                required=required, failure_policy=failure_policy))
    # dedupe by acquisition, keep first, renumber
    seen = set()
    dedup = []
    for r in resources:
        if r.acquisition in seen:
            continue
        seen.add(r.acquisition)
        dedup.append(r)

    error_paths = sorted(set(_ERROR_RE.findall(source_text)))
    helper_calls = sorted({c for c in _HELPER_CALLS if _has_call(source_text, c)})

    return FactsSpec(
        source=source_path, includes=includes, structs=structs,
        constants=constants, callbacks=callbacks, resources=dedup,
        callback_signatures=dict(callback_signatures or {}),
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
