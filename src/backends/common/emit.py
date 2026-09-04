"""ops_to_c: the shared RIS-to-C statement emitter."""
from __future__ import annotations

import re

from extractor.formal import expr_to_c

from .anchors import begin_operation
from .decls import mmio_primitive
from .idents import is_simple_id, replace_expr_var
from .receipts import lowering_recipes, transaction_kind
from .transactions import transaction_lowering


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
        if transaction_kind(op) is not None:
            transaction_lowering(op, pad, out, _anchor_ids, bind)
            continue
        leaf = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite"))
        if leaf is not None and leaf.get("reliability") == "Unsupported":
            begin_operation(out, pad, op, "rejected", _anchor_ids)
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
            r = mmio_primitive(bind, "MmioRead", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            var = o["var"]
            begin_operation(out, pad, op, "lowered", _anchor_ids)
            if (is_simple_id(var)
                    or re.fullmatch(r"(?:g|dev)->[A-Za-z_]\w*", var)):
                out.append(f"{pad}    {var} = {r}({a});")
                if is_simple_id(var):
                    out.append(f"{pad}    (void){var};")
            else:
                # member-access target (e.g. edu->revision) — discard the read
                # result (the field isn't in the generated harness struct)
                out.append(f"{pad}    (void){r}({a});")
            out.append(f"{pad}}}")
        elif "Write" in op:
            o = op["Write"]
            w = mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            v = expr_to_c(o["value"])
            begin_operation(out, pad, op, "lowered", _anchor_ids)
            out.append(f"{pad}    {w}({v}, {a});")
            out.append(f"{pad}}}")
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            r = mmio_primitive(bind, "MmioRead", o)
            w = mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            recipe = (o.get("_backend_lowering_recipe")
                      or _lowering_recipes.get(o.get("op_id"), {}))
            begin_operation(out, pad, op, "lowered", _anchor_ids)
            if recipe.get("kind") == "write_from_read":
                out.append(
                    f"{pad}    {w}({expr_to_c(o.get('transform'))}, {a});")
            else:
                t = replace_expr_var(
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
