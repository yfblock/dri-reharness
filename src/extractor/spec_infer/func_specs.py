"""FunctionSpec inference: abstract signatures, binds, effects, role hints."""
from __future__ import annotations
import re
import os
from typing import Optional

from ..spec import (FunctionSpec, Signature, Param, Binding,
                    Effect, reg_effect, event_effect)
from ..ast_model import Func
from ..formal import walk_leaf_ops


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
