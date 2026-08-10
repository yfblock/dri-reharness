"""Rust bare-metal backend.

Generates portable Rust register-programming code: device struct with
``base: usize``, read/write wrappers using ``core::ptr::read_volatile``,
per-function RIS bodies. No OS framework glue. Compiles with ``rustc``
on ``no_std`` targets.
"""
from __future__ import annotations
import re
from extractor.formal import walk_leaf_ops, walk_all_ops
from .common import (lowering_recipes, value_var_names,
                     detect_transaction_transports,
                     _is_simple_id, _replace_expr_var)
from .linux import (_bound_resource_probe_ops, _normalize_ops,
                    _portable_function_macros)


def _expr_to_rust(e):
    """Render a formal expression as Rust code."""
    if e is None:
        return "0"
    if "Const" in e:
        return "0x%x" % e["Const"]
    if "Var" in e:
        return _rust_ident(e["Var"])
    if "Top" in e:
        return "0 /* TODO: unknown */"
    if "BinOp" in e:
        b = e["BinOp"]
        op = _rust_binop(b["op"])
        left = _expr_to_rust(b["left"])
        right = _expr_to_rust(b["right"])
        if op == "^" and "Const" in b["right"] and b["right"]["Const"] == 0xFFFFFFFF:
            return "(!%s)" % left
        return "(%s %s %s)" % (left, op, right)
    if "Ite" in e:
        i = e["Ite"]
        return "(if %s { %s } else { %s })" % (
            _expr_to_rust(i["guard"]),
            _expr_to_rust(i["then"]),
            _expr_to_rust(i["else"]))
    if "Bits" in e:
        b = e["Bits"]
        inner = _expr_to_rust(b["expr"])
        width = b["hi"] - b["lo"] + 1
        return "((%s >> %d) & ((1u32 << %d) - 1))" % (inner, b["lo"], width)
    return "0"


_RUST_BINOP = {
    "Eq": "==", "Ne": "!=", "Le": "<=", "Ge": ">=", "Lt": "<", "Gt": ">",
    "And": "&&", "Or": "||", "Shl": "<<", "Shr": ">>",
    "BitOr": "|", "BitXor": "^", "BitAnd": "&", "Add": "+", "Sub": "-",
    "Mul": "*", "Div": "/", "Mod": "%",
}


def _rust_binop(op):
    return _RUST_BINOP.get(op, op)


_RUST_KEYWORDS = {"type", "fn", "ref", "match", "move", "as", "box",
                  "break", "continue", "crate", "dyn", "else", "enum",
                  "extern", "false", "for", "if", "impl", "in", "let",
                  "loop", "mod", "mut", "pub", "return", "self", "Self",
                  "static", "struct", "super", "trait", "true",
                  "unsafe", "use", "where", "while", "async", "await"}


def _rust_ident(name):
    if name in _RUST_KEYWORDS:
        return "r#%s" % name
    return name


def _rust_type(abstract, bind):
    t = bind.type_of(abstract) if bind else None
    if not t:
        return "u32"
    type_map = {
        "uint32_t": "u32", "uint16_t": "u16", "uint8_t": "u8",
        "uint64_t": "u64", "uintptr_t": "usize", "int32_t": "i32",
        "int16_t": "i16", "int8_t": "i8", "int64_t": "i64",
        "unsigned int": "u32", "unsigned long": "usize", "void": "()",
    }
    return type_map.get(t, "u32")


def _rust_width_type(width):
    return {"B1": "u8", "B2": "u16", "B4": "u32", "B8": "u64"}.get(width, "u32")


def _addr_to_rust(addr, base_expr, register_consts, state_expr="dev"):
    if "Symbolic" in addr:
        reg = addr["Symbolic"]["register"]
        return "%s + %s" % (base_expr, reg)
    if "Fixed" in addr:
        off = addr["Fixed"]["offset"]
        source_base = addr["Fixed"].get("base", "")
        actual_base = base_expr
        if (state_expr and source_base and source_base != "base"
                and re.fullmatch(r"[A-Za-z_]\w*", source_base)):
            actual_base = "%s.%s" % (state_expr, source_base)
        return "%s + 0x%x" % (actual_base, off) if actual_base else "0x%x" % off
    if "Computed" in addr:
        return _expr_to_rust(addr["Computed"])
    return base_expr


def _rust_mmio_primitive(operation, body):
    byte_order = body.get("evidence", {}).get("byte_order", "native")
    write_semantics = body.get("evidence", {}).get("write_semantics")
    width = body["width"]
    w = {"B1": "8", "B2": "16", "B4": "32"}.get(width, "32")
    if operation == "MmioRead":
        suffix = "_be" if byte_order == "big" else ""
        return "mmio_read%s%s" % (w, suffix)
    else:
        if write_semantics == "w1c":
            return "mmio_write_w1c%s" % w
        suffix = "_be" if byte_order == "big" else ""
        return "mmio_write%s%s" % (w, suffix)


def _ops_to_rust(ops, bind, base_expr, register_consts, indent=1,
                 state_expr="dev", _anchor_ids=None, _lowering_recipes=None):
    if _anchor_ids is None:
        _anchor_ids = set()
    if _lowering_recipes is None:
        _lowering_recipes = lowering_recipes(ops)
    pad = "    " * indent
    out = []
    for op in ops:
        leaf = (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite"))
        if leaf is not None and leaf.get("reliability") == "Unsupported":
            out.append("%s/* REHARNESS_UNSUPPORTED: %s */" % (pad, leaf.get("op_id", "?")))
            continue
        if "Cond" in op:
            guard = _expr_to_rust(op["Cond"]["guard"])
            out.append("%sif %s {" % (pad, guard))
            out.append(_ops_to_rust(op["Cond"]["then_ops"], bind, base_expr,
                                    register_consts, indent + 1, state_expr,
                                    _anchor_ids, _lowering_recipes))
            if op["Cond"].get("else_ops"):
                out.append("%s} else {" % pad)
                out.append(_ops_to_rust(op["Cond"]["else_ops"], bind, base_expr,
                                        register_consts, indent + 1, state_expr,
                                        _anchor_ids, _lowering_recipes))
            out.append("%s}" % pad)
        elif "Loop" in op:
            loop = op["Loop"]
            if (loop.get("reliability") == "Exact" and loop.get("bounded")
                    and loop.get("loop_kind") == "for"):
                out.append("%s/* REHARNESS_LOOP */" % pad)
                out.append(_ops_to_rust(loop.get("body", []), bind, base_expr,
                                        register_consts, indent + 1, state_expr,
                                        _anchor_ids, _lowering_recipes))
            elif (loop.get("reliability") == "Exact"
                  and loop.get("proof_kind") == "masked_w1c_drain"):
                out.append("%sloop {" % pad)
                out.append(_ops_to_rust(loop.get("guard_ops", []), bind, base_expr,
                                        register_consts, indent + 1, state_expr,
                                        _anchor_ids, _lowering_recipes))
                guard_var = loop.get("guard_var", "guard")
                guard_value = _expr_to_rust(loop.get("guard_value"))
                out.append("%s    %s = %s;" % (pad, guard_var, guard_value))
                out.append("%s    if %s == 0 {" % (pad, guard_var))
                out.append("%s        break;" % pad)
                out.append("%s    }" % pad)
                out.append(_ops_to_rust(loop.get("body", []), bind, base_expr,
                                        register_consts, indent + 1, state_expr,
                                        _anchor_ids, _lowering_recipes))
                out.append("%s}" % pad)
            else:
                out.append("%s/* REHARNESS_UNSUPPORTED_LOOP */" % pad)
        elif "Seq" in op:
            out.append(_ops_to_rust(op["Seq"]["ops"], bind, base_expr,
                                    register_consts, indent, state_expr,
                                    _anchor_ids, _lowering_recipes))
        elif "Read" in op:
            o = op["Read"]
            r = _rust_mmio_primitive("MmioRead", o)
            a = _addr_to_rust(o["addr"], base_expr, register_consts, state_expr)
            var = o["var"]
            wtype = _rust_width_type(o["width"])
            out.append("%s/* REHARNESS_RIS_OP id=%s kind=Read */" % (pad, o.get("op_id", "?")))
            if _is_simple_id(var):
                rv = _rust_ident(var)
                out.append("%slet %s: %s = unsafe { %s(%s) };" % (pad, rv, wtype, r, a))
                out.append("%slet _ = %s;" % (pad, rv))
            else:
                out.append("%sunsafe { let _ = %s(%s); }" % (pad, r, a))
        elif "Write" in op:
            o = op["Write"]
            w = _rust_mmio_primitive("MmioWrite", o)
            a = _addr_to_rust(o["addr"], base_expr, register_consts, state_expr)
            v = _expr_to_rust(o["value"])
            out.append("%s/* REHARNESS_RIS_OP id=%s kind=Write */" % (pad, o.get("op_id", "?")))
            out.append("%sunsafe { %s(%s, %s); }" % (pad, w, v, a))
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            r = _rust_mmio_primitive("MmioRead", o)
            w = _rust_mmio_primitive("MmioWrite", o)
            a = _addr_to_rust(o["addr"], base_expr, register_consts, state_expr)
            wtype = _rust_width_type(o["width"])
            recipe = (o.get("_backend_lowering_recipe")
                      or _lowering_recipes.get(o.get("op_id"), {}))
            out.append("%s/* REHARNESS_RIS_OP id=%s kind=RMW */" % (pad, o.get("op_id", "?")))
            if recipe.get("kind") == "write_from_read":
                v = _expr_to_rust(o.get("transform"))
                out.append("%sunsafe { %s(%s, %s); }" % (pad, w, v, a))
            else:
                t = _replace_expr_var(o.get("transform"), o.get("read_var"), "v")
                t_rust = ("v" if isinstance(t, dict) and "Top" in t
                          else _expr_to_rust(t))
                out.append("%sunsafe {" % pad)
                out.append("%s    let v: %s = %s(%s);" % (pad, wtype, r, a))
                out.append("%s    %s(%s, %s);" % (pad, w, t_rust, a))
                out.append("%s}" % pad)
        elif "StateRead" in op:
            o = op["StateRead"]
            index = ("[%s]" % _expr_to_rust(o["index"]) if o.get("index") else "")
            out.append("%slet %s = %s.%s%s;" % (pad, o["var"], state_expr, o["field"], index))
        elif "StateWrite" in op:
            o = op["StateWrite"]
            index = ("[%s]" % _expr_to_rust(o["index"]) if o.get("index") else "")
            out.append("%s%s.%s%s = %s;" % (pad, state_expr, o["field"], index, _expr_to_rust(o["value"])))
        elif "Return" in op:
            out.append("%sreturn %s;" % (pad, _expr_to_rust(op["Return"]["value"])))
        elif "Delay" in op:
            out.append("%sreharness_delay_ns(%s);" % (pad, _expr_to_rust(op["Delay"]["cycles"])))
    NL = chr(10)
    return NL.join(s for s in out if s)


def _rust_local_decls(ops, already_declared, regs, indent=1):
    pad = "    " * indent
    lines = []
    declared = set(already_declared)
    read_vars = sorted({o["Read"]["var"] for o in walk_leaf_ops(ops)
                        if "Read" in o and _is_simple_id(o["Read"]["var"])
                        and o["Read"]["var"] not in declared})
    declared |= set(read_vars)
    for v in read_vars:
        lines.append("%slet mut %s: u32 = 0;" % (pad, _rust_ident(v)))
    extra = sorted(value_var_names(ops) - declared - set(regs.keys()))
    for v in extra:
        if v in {"if", "else", "for", "while", "return", "base"}:
            continue
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v):
            continue
        lines.append("%slet %s: u32 = 0;" % (pad, _rust_ident(v)))
    NL = chr(10)
    return NL.join(lines)


def generate(formal, device_spec, bind):
    dev = device_spec.name
    priv = "%sPriv" % dev.capitalize()
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    tx_selectors = {r["name"]: r["value"] for r in formal.get("transaction_map", [])}
    constants = {}
    constants.update(regs)
    constants.update(tx_selectors)
    safe_function_calls = set(_portable_function_macros(formal))
    probe_refs = {fn.ris_ref for fn in device_spec.functions if fn.role == "probe"}
    portable_skip = (device_spec.cls in {"ahci", "virtio_mmio", "sdhci"})

    L = []
    L.append("//! Auto-generated bare-metal Rust driver for %s (reharness)" % dev)
    L.append("#![allow(non_snake_case, non_camel_case_types, non_upper_case_globals, unused_variables, dead_code, unused_assignments)]")
    L.append("#![cfg_attr(not(test), no_std)]")
    L.append("")
    L.append("use core::ptr::{read_volatile, write_volatile};")
    L.append("")

    for w, ty in [("32", "u32"), ("16", "u16"), ("8", "u8")]:
        L.append("#[inline]")
        L.append("pub unsafe fn mmio_read%s(addr: usize) -> %s {" % (w, ty))
        L.append("    read_volatile(addr as *const %s)" % ty)
        L.append("}")
        L.append("#[inline]")
        L.append("pub unsafe fn mmio_write%s(val: %s, addr: usize) {" % (w, ty))
        L.append("    write_volatile(addr as *mut %s, val);" % ty)
        L.append("}")
        L.append("")
    for w, ty in [("16", "u16"), ("32", "u32")]:
        L.append("#[inline]")
        L.append("pub unsafe fn mmio_read%s_be(addr: usize) -> %s {" % (w, ty))
        L.append("    %s::from_be(read_volatile(addr as *const %s))" % (ty, ty))
        L.append("}")
        L.append("#[inline]")
        L.append("pub unsafe fn mmio_write%s_be(val: %s, addr: usize) {" % (w, ty))
        L.append("    write_volatile(addr as *mut %s, %s::to_be(val));" % (ty, ty))
        L.append("}")
    L.append("")
    types_w1c = {"8": "u8", "16": "u16", "32": "u32"}
    for w in ["8", "16", "32"]:
        ty = types_w1c[w]
        L.append("#[inline]")
        L.append("pub unsafe fn mmio_write_w1c%s(val: %s, addr: usize) {" % (w, ty))
        L.append("    mmio_write%s(val, addr);" % w)
        L.append("}")
    L.append("")
    L.append("#[inline]")
    L.append("pub fn reharness_delay_ns(ns: u32) { let _ = ns; }")
    L.append("")

    for name, off in constants.items():
        L.append("pub const %s: usize = 0x%x;" % (name, off))
    L.append("")

    upper_refs = set()
    upper_calls = set()
    for module in formal["modules"]:
        contract_recipes = lowering_recipes(module["ops"])
        raw_ops = (_bound_resource_probe_ops(module["ops"])
                   if module["name"] in probe_refs else module["ops"])
        safe_ops, _ = _normalize_ops(raw_ops, safe_function_calls=safe_function_calls,
                                     contract_recipes=contract_recipes)
        upper_refs |= {v for v in value_var_names(safe_ops)
                       if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v)}
        upper_refs |= set(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", repr(safe_ops)))
        upper_calls |= set(re.findall(r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", repr(safe_ops)))
    for name in sorted((upper_refs | upper_calls) - set(constants) - {"MMIO", "TODO"}):
        L.append("pub const %s: u32 = 0;" % name)
    L.append("")

    state_fields = [s for s in device_spec.state
                    if s.name not in {"base", "clk", "num_irqs"}]
    L.append("#[repr(C)]")
    L.append("pub struct %s {" % priv)
    L.append("    pub base: usize,")
    for state in state_fields:
        if state.type == "UIntArray":
            L.append("    pub %s: [u32; 4]," % state.name)
        elif state.type == "UInt64":
            L.append("    pub %s: u64," % state.name)
        elif state.type == "MmioBase":
            L.append("    pub %s: usize," % state.name)
        else:
            L.append("    pub %s: u32," % state.name)
    L.append("}")
    L.append("")
    L.append("impl %s {" % priv)
    L.append("    pub fn new(base: usize) -> Self {")
    L.append("        Self { base,")
    for state in state_fields:
        if state.type == "UIntArray":
            L.append("            %s: [0; 4]," % state.name)
        else:
            L.append("            %s: 0," % state.name)
    L.append("        }")
    L.append("    }")
    L.append("}")
    L.append("")

    func_by_name = {m["name"]: m for m in formal["modules"]}
    for fn in device_spec.functions:
        m = func_by_name.get(fn.ris_ref)
        if not m:
            continue
        contract_recipes = lowering_recipes(m["ops"])
        raw_ops = (_bound_resource_probe_ops(m["ops"])
                   if fn.role == "probe" else m["ops"])
        safe_ops, _ = _normalize_ops(raw_ops, "dev", safe_function_calls,
                                     contract_recipes=contract_recipes)
        if portable_skip:
            safe_ops = []
        keep = [p for p in fn.signature.params if p.type != "DeviceState"]
        params = ", ".join("%s: %s" % (_rust_ident(p.name), _rust_type(p.type, bind)) for p in keep)
        params = (params + ", ") if params else ""
        params += "dev: &mut %s" % priv
        if portable_skip:
            has_return = fn.signature.return_type != "Void"
        else:
            has_return = any("Return" in op for op in walk_leaf_ops(safe_ops))
        ret = " -> %s" % _rust_type(fn.signature.return_type, bind) if has_return else ""
        L.append("pub fn %s(%s)%s {" % (fn.name, params, ret))
        declared = {_rust_ident(p.name) for p in keep} | {"base"}
        decls = _rust_local_decls(safe_ops, declared, regs, indent=1)
        if decls:
            L.append(decls)
        L.append("    let base = dev.base;")
        body = _ops_to_rust(safe_ops, bind, "base", regs, indent=1,
                            state_expr="dev", _lowering_recipes=contract_recipes)
        if body:
            L.append(body)
        if portable_skip and has_return:
            L.append("    return 0;")
        L.append("}")
        L.append("")

    entry = next((fn for fn in device_spec.functions if fn.role == "probe"), None)
    entry = entry or (device_spec.functions[0] if device_spec.functions else None)
    if entry:
        L.append("#[cfg(test)]")
        L.append("mod tests {")
        L.append("    use super::*;")
        L.append("")
        L.append("    #[test]")
        L.append("    fn test_%s_driver() {" % dev)
        L.append("        let mut dev = %s::new(0x1000_0000);" % priv)
        keep = [p for p in entry.signature.params if p.type != "DeviceState"]
        call_args = ", ".join(["0"] * len(keep))
        call_args = (call_args + ", ") if call_args else ""
        L.append("        unsafe { %s(%s&mut dev); }" % (entry.name, call_args))
        L.append("    }")
        L.append("}")

    NL = chr(10)
    return NL.join(L) + NL

