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
                         callback_entries: set[str]) -> tuple[list[FunctionSpec], dict]:
    names = {f.name for f in funcs}
    cb_bindings =  parse_callback_bindings(source_text, names)
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
            hint =  name_role_hints(m["name"])
            role = hint or ("helper" if m["name"] not in callback_entries else "unknown")
            context = "irq" if role.startswith("interrupt") or role == "set_irq_type" else "thread"
            table = None
        is_entry = m["name"] in callback_entries
        specs.append(infer_function_spec(fn, m, role, context, is_entry, table, source_path))
    return specs, cb_bindings


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
    "set": ("write_config", "thread"),
    "generation": ("get_status", "thread"),
    "get_status": ("get_status", "thread"),
    "set_status": ("set_status", "thread"),
    "reset": ("reset", "thread"),
    "find_vqs": ("setup_queue", "thread"),
    "del_vqs": ("remove", "thread"),
    "get_shm_region": ("read_config", "thread"),
    "notify_vq": ("notify", "thread"),
    "notify": ("notify", "thread"),
    # gpio_chip (beyond irq)
    "get_direction": ("read_config", "thread"),
    "direction_input": ("write_config", "thread"),
    "direction_output": ("write_config", "thread"),
    "get": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_config": ("write_config", "thread"),
    "request": ("init", "thread"),
    "free": ("remove", "thread"),
    # generic
    "init": ("init", "boot"),
    "exit": ("remove", "thread"),
}

# which struct type a field likely belongs to (for callback_table label)
FIELD_TABLE = {
    "irq_ack": "irq_chip", "irq_mask": "irq_chip", "irq_unmask": "irq_chip",
    "irq_mask_ack": "irq_chip", "irq_eoi": "irq_chip", "irq_enable": "irq_chip",
    "irq_disable": "irq_chip", "irq_set_type": "irq_chip", "handle_irq": "irq_chip",
    "probe": "platform_driver", "remove": "platform_driver", "shutdown": "platform_driver",
    "suspend": "dev_pm_ops", "resume": "dev_pm_ops", "freeze": "dev_pm_ops",
    "thaw": "dev_pm_ops", "poweroff": "dev_pm_ops", "restore": "dev_pm_ops",
    "find_vqs": "virtio_config_ops", "del_vqs": "virtio_config_ops",
    "get_status": "virtio_config_ops", "set_status": "virtio_config_ops",
    "reset": "virtio_config_ops", "generation": "virtio_config_ops",
    "get_shm_region": "virtio_config_ops", "notify_vq": "virtio_config_ops",
}


_DESIGNATED_INIT = re.compile(
    r"\.\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*[,}]"
)


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
    for m in _DESIGNATED_INIT.finditer(src):
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
            "table": FIELD_TABLE.get(field, "ops"),
        }
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
        if call in source_text:
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
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"].get("expr"))
    return out
