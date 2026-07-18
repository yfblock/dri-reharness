"""Shared C-emission helpers for all backends."""
from __future__ import annotations
import copy
import hashlib
import json
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
        elif "StateWrite" in op:
            names |= _vars_in_expr(op["StateWrite"].get("value"))
        elif "OutputWrite" in op:
            names |= _vars_in_expr(op["OutputWrite"].get("value"))
        elif "Return" in op:
            names |= _vars_in_expr(op["Return"].get("value"))
    return names


def lowering_recipes(ops: list) -> dict[str, dict]:
    """Describe which physical primitives each Formal leaf owns.

    Dataflow-derived ``ReadModifyWrite`` leaves represent a source *write*
    whose transform depends on a preceding source Read.  Re-reading inside the
    RMW lowering duplicates a hardware access.  Intrinsic update-bits style
    operations have no preceding producer and legitimately own both a read and
    a write.
    """
    recipes: dict[str, dict] = {}

    def visit(items: list | None,
              producers: dict[str, tuple[str, dict]]) -> None:
        for op in items or []:
            if "Cond" in op:
                visit(op["Cond"].get("then_ops"), dict(producers))
                visit(op["Cond"].get("else_ops"), dict(producers))
                continue
            if "Loop" in op:
                local = dict(producers)
                visit(op["Loop"].get("guard_ops"), local)
                visit(op["Loop"].get("body"), local)
                continue
            if "Seq" in op:
                visit(op["Seq"].get("ops"), producers)
                continue
            if "Read" in op:
                body = op["Read"]
                op_id = body.get("op_id")
                if op_id:
                    recipes[op_id] = {
                        "kind": "read", "primitives": ["Read"]}
                if body.get("var") and op_id:
                    producers[body["var"]] = (op_id, body.get("addr", {}))
                continue
            if "Write" in op:
                body = op["Write"]
                if body.get("op_id"):
                    recipes[body["op_id"]] = {
                        "kind": "write", "primitives": ["Write"]}
                continue
            if "ReadModifyWrite" in op:
                body = op["ReadModifyWrite"]
                op_id = body.get("op_id")
                if not op_id:
                    continue
                producer = producers.get(body.get("read_var"))
                if producer and producer[1] == body.get("addr", {}):
                    recipes[op_id] = {
                        "kind": "write_from_read",
                        "primitives": ["Write"],
                        "read_op_id": producer[0],
                    }
                else:
                    recipes[op_id] = {
                        "kind": "intrinsic_rmw",
                        "primitives": ["Read", "Write"],
                    }

    visit(ops, {})
    return recipes


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
                        if "Read" in o and _is_simple_id(o["Read"]["var"])
                        and o["Read"]["var"] not in declared})
    read_vars += sorted({o["StateRead"]["var"] for o in walk_leaf_ops(ops)
                         if "StateRead" in o
                         and _is_simple_id(o["StateRead"]["var"])
                         and o["StateRead"]["var"] not in declared
                         and o["StateRead"]["var"] not in read_vars})
    declared |= set(read_vars)
    for v in read_vars:
        lines.append(f"{pad}{ctype} {v} = 0;")
    rmw_read_vars = {
        o["ReadModifyWrite"].get("read_var")
        for o in walk_leaf_ops(ops) if "ReadModifyWrite" in o
    }
    extra = sorted(value_var_names(ops) - declared - set(regs.keys())
                   - {name for name in rmw_read_vars if name})
    for v in extra:
        # Upper-case identifiers are C/kernel constants, not locals.  Declaring
        # them would collide with macros such as PCI_VENDOR_ID_INTEL.
        if v in _C_KEYWORDS or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v):
            continue
        lines.append(f"{pad}{ctype} {v} = 0;")
    return "\n".join(lines)


def _width_suffix(width: str) -> str:
    return {"B1": "8", "B2": "16", "B4": "32", "B8": "64"}.get(width, "32")


def _mmio_primitive(bind, operation: str, body: dict) -> str:
    byte_order = body.get("evidence", {}).get("byte_order", "native")
    write_semantics = body.get("evidence", {}).get("write_semantics")
    semantic = operation + ("W1C" if write_semantics == "w1c" else "")
    semantic += "BE" if byte_order == "big" else ""
    primitive = bind.prim(semantic, body["width"])
    if primitive:
        return primitive
    native = {
        ("MmioRead", "B1"): "readb", ("MmioRead", "B2"): "readw",
        ("MmioRead", "B4"): "readl", ("MmioRead", "B8"): "readl",
        ("MmioWrite", "B1"): "writeb", ("MmioWrite", "B2"): "writew",
        ("MmioWrite", "B4"): "writel", ("MmioWrite", "B8"): "writel",
    }
    return native.get((operation, body["width"]),
                      "readl" if operation == "MmioRead" else "writel")


def ris_op_digest(op: dict) -> str:
    """Stable semantic digest used by backend lowering receipts.

    Source paths and other provenance are deliberately excluded: the digest
    describes the operation the backend must lower, while the canonical
    Formal RIS remains the authority for provenance.  The digest is always
    derived from the current operation; callers must not cache it in Formal
    RIS, because doing so would hide later semantic mutations.
    """
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = copy.deepcopy(op.get(kind, {}))
    body.pop("op_id", None)
    body.pop("contract_digest", None)
    body.pop("_backend_contract_digest", None)
    body.pop("_backend_lowering_recipe", None)
    evidence = body.pop("evidence", {})
    # Most evidence locates the source operation and is intentionally outside
    # the semantic contract.  These fields, however, select different backend
    # MMIO primitives and therefore must participate in the digest.
    lowering_evidence = {
        name: evidence[name]
        for name in ("byte_order", "write_semantics")
        if name in evidence
    }
    semantic = {"kind": kind, "body": body}
    if lowering_evidence:
        semantic["lowering_evidence"] = lowering_evidence
    encoded = json.dumps(
        semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def lowering_receipt(op: dict, disposition: str = "lowered") -> str:
    """Machine-readable receipt for one register RIS operation."""
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = op.get(kind, {})
    digest = body.get("_backend_contract_digest") or ris_op_digest(op)
    return ("/* REHARNESS_RIS_OP "
            f"id={body.get('op_id', '?')} kind={kind} "
            f"status={disposition} digest={digest} */")


def _operation_anchor(op: dict, seen: set[str]) -> str:
    """Return the source-level label that owns one register lowering.

    Formal RIS assigns C-identifier-safe, globally unique ``op_<n>`` IDs.  Do
    not silently sanitize malformed IDs here: an altered label would sever the
    exact operation-to-C relation that the anchor is intended to expose to
    independent AST and mutation oracles.
    """
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), None)
    body = op.get(kind, {}) if kind else {}
    op_id = body.get("op_id")
    if not isinstance(op_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", op_id):
        raise ValueError(f"register RIS operation has invalid op_id: {op_id!r}")
    if op_id in seen:
        raise ValueError(f"duplicate register RIS operation id: {op_id}")
    seen.add(op_id)
    return f"__rh_op_{op_id}"


def _begin_operation(out: list[str], pad: str, op: dict,
                     disposition: str, seen: set[str]) -> None:
    """Start a receipt-bound compound statement owned by a unique label."""
    out.append(f"{pad}{lowering_receipt(op, disposition)}")
    out.append(f"{pad}{_operation_anchor(op, seen)}: {{")


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


def addr_to_c(addr: dict, base_expr: str, register_macros: dict[str, int],
              state_expr: str = "") -> str:
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
        source_base = addr["Fixed"].get("base", "")
        actual_base = base_expr
        if (state_expr and source_base and source_base != "base"
                and re.fullmatch(r"[A-Za-z_]\w*", source_base)):
            actual_base = f"{state_expr}->{source_base}"
        return f"{actual_base} + 0x{off:x}" if actual_base else f"0x{off:x}"
    if "Computed" in addr:
        return expr_to_c(addr["Computed"])
    return base_expr


def ops_to_c(ops: list, bind, base_expr: str, register_macros: dict[str, int],
             indent: int = 1, word_type: str = "uint32_t",
             state_expr: str = "dev", _anchor_ids: set[str] | None = None,
             _lowering_recipes: dict[str, dict] | None = None) -> str:
    """Translate a list of formal RISOps to C statements."""
    if _anchor_ids is None:
        _anchor_ids = set()
    if _lowering_recipes is None:
        _lowering_recipes = lowering_recipes(ops)
    pad = "    " * indent
    out: list[str] = []
    for op in ops:
        leaf = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite"))
        if leaf is not None and leaf.get("reliability") == "Unsupported":
            _begin_operation(out, pad, op, "rejected", _anchor_ids)
            out.append(
                f"{pad}    /* REHARNESS_UNSUPPORTED_ACCESS_DOMAIN: "
                f"{leaf.get('access_domain', 'unknown')} {leaf.get('op_id', '?')} */")
            out.append(f"{pad}}}")
            continue
        if "Cond" in op:
            guard = expr_to_c(op["Cond"]["guard"])
            out.append(f"{pad}if ({guard}) {{")
            out.append(ops_to_c(op["Cond"]["then_ops"], bind, base_expr,
                                register_macros, indent + 1, word_type,
                                state_expr, _anchor_ids,
                                _lowering_recipes))
            if op["Cond"].get("else_ops"):
                out.append(f"{pad}}} else {{")
                out.append(ops_to_c(op["Cond"]["else_ops"], bind, base_expr,
                                    register_macros, indent + 1, word_type,
                                    state_expr, _anchor_ids,
                                    _lowering_recipes))
            out.append(f"{pad}}}")
        elif "Loop" in op:
            loop = op["Loop"]
            guard = expr_to_c(loop.get("guard", {"Top": None}))
            if (loop.get("reliability") == "Exact"
                    and loop.get("bounded")
                    and loop.get("loop_kind") == "for"):
                if loop.get("dynamic_bound"):
                    induction = loop.get("induction_var", "__reharness_i")
                    bound = expr_to_c(
                        loop.get("bound_expr") or loop.get("count"))
                    relation = loop.get("relation", "<")
                    start = int(loop.get("start", 0))
                    stride = int(loop.get("stride", 1))
                    step = (f"{induction}++" if stride == 1
                            else f"{induction} += {stride}")
                    out.append(
                        f"{pad}for (uint32_t {induction} = {start}, "
                        f"__reharness_limit = {bound}; "
                        f"{induction} {relation} __reharness_limit; {step}) {{")
                else:
                    init = loop.get("init", "").strip().rstrip(";")
                    step = loop.get("step", "").strip().rstrip(";")
                    out.append(f"{pad}for ({init}; {guard}; {step}) {{")
                out.append(ops_to_c(loop.get("body", []), bind, base_expr,
                                    register_macros, indent + 1, word_type,
                                    state_expr, _anchor_ids,
                                    _lowering_recipes))
                out.append(f"{pad}}}")
            elif (loop.get("reliability") == "Exact"
                  and loop.get("proof_kind") == "masked_w1c_drain"):
                out.append(f"{pad}for (;;) {{")
                out.append(ops_to_c(
                    loop.get("guard_ops", []), bind, base_expr,
                    register_macros, indent + 1, word_type, state_expr,
                    _anchor_ids, _lowering_recipes))
                guard_var = loop.get("guard_var", "guard")
                guard_value = expr_to_c(loop.get("guard_value"))
                out.append(f"{pad}    {guard_var} = {guard_value};")
                out.append(f"{pad}    if (!{guard_var})")
                out.append(f"{pad}        break;")
                out.append(ops_to_c(
                    loop.get("body", []), bind, base_expr,
                    register_macros, indent + 1, word_type, state_expr,
                    _anchor_ids, _lowering_recipes))
                out.append(f"{pad}}}")
            else:
                out.append(
                    f"{pad}/* REHARNESS_UNSUPPORTED_LOOP: "
                    f"{loop.get('loop_kind', 'loop')} guard={guard} */")
        elif "Seq" in op:
            out.append(ops_to_c(op["Seq"]["ops"], bind, base_expr,
                                register_macros, indent, word_type, state_expr,
                                _anchor_ids, _lowering_recipes))
        elif "Read" in op:
            o = op["Read"]
            r = _mmio_primitive(bind, "MmioRead", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            var = o["var"]
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            if (_is_simple_id(var)
                    or re.fullmatch(r"(?:g|dev)->[A-Za-z_]\w*", var)):
                out.append(f"{pad}    {var} = {r}({a});")
                if _is_simple_id(var):
                    out.append(f"{pad}    (void){var};")
            else:
                # member-access target (e.g. edu->revision) — discard the read
                # result (the field isn't in the generated harness struct)
                out.append(f"{pad}    (void){r}({a});")
            out.append(f"{pad}}}")
        elif "Write" in op:
            o = op["Write"]
            w = _mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            v = expr_to_c(o["value"])
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            out.append(f"{pad}    {w}({v}, {a});")
            out.append(f"{pad}}}")
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            r = _mmio_primitive(bind, "MmioRead", o)
            w = _mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            recipe = (o.get("_backend_lowering_recipe")
                      or _lowering_recipes.get(o.get("op_id"), {}))
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            if recipe.get("kind") == "write_from_read":
                out.append(
                    f"{pad}    {w}({expr_to_c(o.get('transform'))}, {a});")
            else:
                t = _replace_expr_var(
                    o.get("transform"), o.get("read_var"), "v")
                t_c = ("v" if isinstance(t, dict) and "Top" in t
                       else expr_to_c(t))
                out.append(f"{pad}    {word_type} v = {r}({a});")
                out.append(f"{pad}    {w}({t_c}, {a});")
            out.append(f"{pad}}}")
        elif "StateRead" in op:
            o = op["StateRead"]
            index = (f"[{expr_to_c(o['index'])}]"
                     if o.get("index") else "")
            out.append(
                f"{pad}{o['var']} = {state_expr}->{o['field']}{index};")
        elif "StateWrite" in op:
            o = op["StateWrite"]
            index = (f"[{expr_to_c(o['index'])}]"
                     if o.get("index") else "")
            out.append(
                f"{pad}{state_expr}->{o['field']}{index} = "
                f"{expr_to_c(o['value'])};")
        elif "OutputWrite" in op:
            o = op["OutputWrite"]
            out.append(f"{pad}*{o['target']} = {expr_to_c(o['value'])};")
        elif "Return" in op:
            out.append(f"{pad}return {expr_to_c(op['Return']['value'])};")
        elif "Delay" in op:
            out.append(
                f"{pad}reharness_delay_ns({expr_to_c(op['Delay']['cycles'])});")
    return "\n".join(s for s in out if s)
