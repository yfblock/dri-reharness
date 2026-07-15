"""Shared C-emission helpers for all backends."""
from __future__ import annotations
import re
from extractor.formal import expr_to_c, walk_leaf_ops, walk_all_ops

_VAR_ID = re.compile(r"^[A-Za-z_]\w*$")
_C_KEYWORDS = {
    "auto", "char", "const", "double", "enum", "extern", "float", "for",
    "int", "long", "register", "restrict", "short", "signed", "static",
    "struct", "typedef", "union", "unsigned", "void", "volatile", "while",
}


def _vars_in_expr(e) -> set[str]:
    if e is None:
        return set()
    out: set[str] = set()
    if "Var" in e:
        v = e["Var"]
        if _VAR_ID.match(v):
            out.add(v)
        else:
            for m in re.finditer(r"\b[A-Za-z_]\w*\b", v):
                before = v[:m.start()].rstrip()
                after = v[m.end():].lstrip()
                if (after.startswith(("(", "->", "."))
                        or before.endswith(("->", "."))):
                    continue
                out.add(m.group(0))
    if "BinOp" in e:
        out |= _vars_in_expr(e["BinOp"]["left"])
        out |= _vars_in_expr(e["BinOp"]["right"])
    if "Ite" in e:
        out |= _vars_in_expr(e["Ite"]["guard"])
        out |= _vars_in_expr(e["Ite"]["then"])
        out |= _vars_in_expr(e["Ite"]["else"])
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"]["expr"])
    return out


def value_var_names(ops) -> set[str]:
    """Identifiers referenced in values, guards, or computed addresses."""
    names: set[str] = set()
    for op in walk_all_ops(ops):
        if "Cond" in op:
            names |= _vars_in_expr(op["Cond"]["guard"])
        elif "Loop" in op:
            names |= _vars_in_expr(op["Loop"].get("guard"))
            for loop_text in (op["Loop"].get("init", ""),
                              op["Loop"].get("step", "")):
                names |= {
                    name for name in re.findall(r"\b[A-Za-z_]\w*\b", loop_text)
                    if name not in _C_KEYWORDS
                }
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body and "Computed" in body.get("addr", {}):
            names |= _vars_in_expr(body["addr"]["Computed"])
        if "Write" in op:
            names |= _vars_in_expr(op["Write"].get("value"))
        elif "ReadModifyWrite" in op:
            names |= _vars_in_expr(op["ReadModifyWrite"].get("transform"))
    return names


def _is_simple_id(name: str) -> bool:
    return bool(_VAR_ID.match(name))


def local_decls(ops, already_declared: set[str], regs: dict, indent: int = 1,
                ctype: str = "uint32_t") -> str:
    """Emit declarations for read vars + value-referenced locals not already
    declared (params / read vars) and not register macros. Member-access read
    targets (e.g. `edu->revision`) are NOT declared as locals — they are
    discarded at the read site (see ops_to_c)."""
    pad = "    " * indent
    lines: list[str] = []
    declared = set(already_declared)
    read_vars = sorted({o["Read"]["var"] for o in walk_leaf_ops(ops)
                        if "Read" in o and _is_simple_id(o["Read"]["var"])})
    declared |= set(read_vars)
    for v in read_vars:
        lines.append(f"{pad}{ctype} {v} = 0;")
    extra = sorted(value_var_names(ops) - declared - set(regs.keys()))
    for v in extra:
        # Upper-case identifiers are C/kernel constants, not locals.  Declaring
        # them would collide with macros such as PCI_VENDOR_ID_INTEL.
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v):
            continue
        lines.append(f"{pad}{ctype} {v} = 0;")
    return "\n".join(lines)


def _width_suffix(width: str) -> str:
    return {"B1": "8", "B2": "16", "B4": "32", "B8": "64"}.get(width, "32")


def _replace_expr_var(expr, name: str | None, replacement: str):
    if not isinstance(expr, dict) or not name:
        return expr
    if expr.get("Var") == name:
        return {"Var": replacement}
    out = dict(expr)
    if "BinOp" in expr:
        b = dict(expr["BinOp"])
        b["left"] = _replace_expr_var(b.get("left"), name, replacement)
        b["right"] = _replace_expr_var(b.get("right"), name, replacement)
        out["BinOp"] = b
    elif "Ite" in expr:
        i = dict(expr["Ite"])
        i["guard"] = _replace_expr_var(i.get("guard"), name, replacement)
        i["then"] = _replace_expr_var(i.get("then"), name, replacement)
        i["else"] = _replace_expr_var(i.get("else"), name, replacement)
        out["Ite"] = i
    elif "Bits" in expr:
        b = dict(expr["Bits"])
        b["expr"] = _replace_expr_var(b.get("expr"), name, replacement)
        out["Bits"] = b
    return out


def addr_to_c(addr: dict, base_expr: str, register_macros: dict[str, int]) -> str:
    """Render a formal RegAddr as a C address expression.

    Symbolic registers render as `base_expr + REG_MACRO` (macro #defined in the
    header); Fixed as `base_expr + 0xOFF`; Computed as the expression."""
    if "Symbolic" in addr:
        reg = addr["Symbolic"]["register"]
        off = register_macros.get(reg)
        if off is not None:
            return f"{base_expr} + {reg}"
        return f"{base_expr} + 0x{off:x}" if off is not None else base_expr
    if "Fixed" in addr:
        off = addr["Fixed"]["offset"]
        return f"{base_expr} + 0x{off:x}" if base_expr else f"0x{off:x}"
    if "Computed" in addr:
        return expr_to_c(addr["Computed"])
    return base_expr


def ops_to_c(ops: list, bind, base_expr: str, register_macros: dict[str, int],
             indent: int = 1, word_type: str = "uint32_t") -> str:
    """Translate a list of formal RISOps to C statements."""
    pad = "    " * indent
    out: list[str] = []
    for op in ops:
        leaf = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite"))
        if leaf is not None and leaf.get("reliability") == "Unsupported":
            out.append(
                f"{pad}/* REHARNESS_UNSUPPORTED_ACCESS_DOMAIN: "
                f"{leaf.get('access_domain', 'unknown')} {leaf.get('op_id', '?')} */")
            continue
        if "Cond" in op:
            guard = expr_to_c(op["Cond"]["guard"])
            out.append(f"{pad}if ({guard}) {{")
            out.append(ops_to_c(op["Cond"]["then_ops"], bind, base_expr,
                                register_macros, indent + 1, word_type))
            if op["Cond"].get("else_ops"):
                out.append(f"{pad}}} else {{")
                out.append(ops_to_c(op["Cond"]["else_ops"], bind, base_expr,
                                    register_macros, indent + 1, word_type))
            out.append(f"{pad}}}")
        elif "Loop" in op:
            loop = op["Loop"]
            guard = expr_to_c(loop.get("guard", {"Top": None}))
            if (loop.get("reliability") == "Exact"
                    and loop.get("bounded")
                    and loop.get("loop_kind") == "for"):
                init = loop.get("init", "").strip().rstrip(";")
                step = loop.get("step", "").strip().rstrip(";")
                out.append(f"{pad}for ({init}; {guard}; {step}) {{")
                out.append(ops_to_c(loop.get("body", []), bind, base_expr,
                                    register_macros, indent + 1, word_type))
                out.append(f"{pad}}}")
            else:
                out.append(
                    f"{pad}/* REHARNESS_UNSUPPORTED_LOOP: "
                    f"{loop.get('loop_kind', 'loop')} guard={guard} */")
        elif "Seq" in op:
            out.append(ops_to_c(op["Seq"]["ops"], bind, base_expr,
                                register_macros, indent, word_type))
        elif "Read" in op:
            o = op["Read"]
            r = bind.prim("MmioRead", o["width"]) or "readl"
            a = addr_to_c(o["addr"], base_expr, register_macros)
            var = o["var"]
            if (_is_simple_id(var)
                    or re.fullmatch(r"(?:g|dev)->[A-Za-z_]\w*", var)):
                out.append(f"{pad}{var} = {r}({a});")
            else:
                # member-access target (e.g. edu->revision) — discard the read
                # result (the field isn't in the generated harness struct)
                out.append(f"{pad}(void){r}({a});")
        elif "Write" in op:
            o = op["Write"]
            w = bind.prim("MmioWrite", o["width"]) or "writel"
            a = addr_to_c(o["addr"], base_expr, register_macros)
            v = expr_to_c(o["value"])
            out.append(f"{pad}{w}({v}, {a});")
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            r = bind.prim("MmioRead", o["width"]) or "readl"
            w = bind.prim("MmioWrite", o["width"]) or "writel"
            a = addr_to_c(o["addr"], base_expr, register_macros)
            t = _replace_expr_var(o.get("transform"), o.get("read_var"), "v")
            t_c = "v" if isinstance(t, dict) and "Top" in t else expr_to_c(t)
            out.append(f"{pad}{{ {word_type} v = {r}({a}); {w}({t_c}, {a}); }}")
        elif "Delay" in op:
            out.append(f"{pad}/* delay {expr_to_c(op['Delay']['cycles'])} ns */")
    return "\n".join(s for s in out if s)
