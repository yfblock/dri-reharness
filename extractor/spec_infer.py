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

from . import bindings_linux as BL
from .spec import (FunctionSpec, DeviceSpec, Signature, Param, Binding,
                   RegisterDesc, StateField, Resource, Effect, reg_effect,
                   event_effect)
from .ast_model import Func
from .formal import walk_leaf_ops

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


def infer_function_spec(func: Func, module: dict, role: str, context: str,
                        is_callback_entry: bool, callback_table: Optional[str],
                        source_path: str) -> FunctionSpec:
    # signature
    params = [Param(name=p[0], type=_abstract_param_type(p[1], role))
              for p in func.params if p[0]]
    sig = Signature(params=params, return_type=_abstract_return_type(
        func.cursor.result_type.spelling if func.cursor.result_type else "void"))

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

    return FunctionSpec(
        name=func.name, signature=sig, role=role, context=context,
        source=f"{os.path.basename(source_path)}:{func.line}",
        binds=binds, requires=requires, ensures=ensures, effects=effects,
        ris_ref=module["name"], is_callback_entry=is_callback_entry,
        callback_table=callback_table,
    )


def infer_function_specs(formal: dict, funcs: list[Func], source_text: str,
                         source_path: str,
                         callback_entries: set[str]) -> list[FunctionSpec]:
    names = {f.name for f in funcs}
    cb_bindings = BL.parse_callback_bindings(source_text, names)
    module_by_name = {m["name"]: m for m in formal["modules"]}
    func_by_name = {f.name: f for f in funcs}

    specs: list[FunctionSpec] = []
    for m in formal["modules"]:
        fn = func_by_name.get(m["name"])
        if fn is None:
            continue
        cb = cb_bindings.get(m["name"])
        if cb:
            role, context, table = cb["role"], cb["context"], cb["table"]
        else:
            hint = BL.name_role_hints(m["name"])
            role = hint or ("helper" if m["name"] not in callback_entries else "unknown")
            context = "irq" if role.startswith("interrupt") or role == "set_irq_type" else "thread"
            table = None
        is_entry = m["name"] in callback_entries
        specs.append(infer_function_spec(fn, m, role, context, is_entry, table, source_path))
    return specs


_DEVICE_CLASS_HINTS = [
    ("gpio", "gpio_controller"), ("clk", "clock"), ("pll", "clock"),
    ("virtio", "virtio_mmio"), ("ahci", "ahci"), ("sdhci", "sdhci"),
    ("rtc", "rtc"), ("i2c", "i2c"), ("spi", "spi"),
]


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

    # state: base + (clk if clk ops present) + num_irqs if irq callbacks
    state: list[StateField] = [StateField("base", "MmioBase")]
    has_irq = any(fs.role.startswith("interrupt") or fs.role == "set_irq_type" for fs in fn_specs)
    has_clk = "clk" in source_text.lower() or any("clk" in fs.name.lower() for fs in fn_specs)
    if has_clk:
        state.append(StateField("clk", "Clock"))
    if has_irq:
        state.append(StateField("num_irqs", "UInt"))

    # resources
    resources: list[Resource] = [Resource("mmio0", "MmioResource", True, "base")]
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
