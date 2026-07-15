"""Formal RIS language — mirrors driver-harness src/ir/formal.rs.

A mathematically-grounded representation of register interaction sequences:
  Expr   = Const | Var | BinOp{op,left,right} | Ite{guard,then,else}
         | Bits{hi,lo,expr} | Top
  RegAddr= Fixed{base,offset} | Symbolic{device,register} | Computed(Expr)
  RISOp  = Read | Write | ReadModifyWrite | Delay | Cond | Seq | Loop
  FormalRIS = {driver, version, modules[], register_map[], metadata}

Emits both:
  - a structured serde-compatible JSON (FormalRIS schema), and
  - a human-readable formal-language text (the Display grammar):
        driver gpio v0.1.0 {
          module probe {
            W(B4, dev.GPIO_INT_EN) = 0x0 -- Init
            status := R(B4, dev.GPIO_INT_STAT) -- Status
            IF (val == deb_div) { 2 ops }
          }
        }
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional, Union

from .dataflow import _split_top, _strip_casts


# ── BinOp / Expr ─────────────────────────────────────────────────────

BINOPS = ["==", "!=", "<=", ">=", "&&", "||", "<<", ">>", "<", ">",
          "|", "&", "+", "-", "*", "/", "%"]
BINOP_NAME = {
    "==": "Eq", "!=": "Ne", "<=": "Le", ">=": "Ge", "<": "Lt", ">": "Gt",
    "&&": "And", "||": "Or", "<<": "Shl", ">>": "Shr",
    "|": "BitOr", "&": "BitAnd", "+": "Add", "-": "Sub",
    "*": "Mul", "/": "Div", "%": "Mod",
}
BINOP_SYM = {v: k for k, v in BINOP_NAME.items()}
BINOP_SYM.update({"Add": "+", "Sub": "-", "BitAnd": "&", "BitOr": "|",
                   "BitXor": "^", "Shl": "<<", "Shr": ">>",
                   "Eq": "==", "Ne": "!=", "Lt": "<", "Gt": ">",
                   "Le": "<=", "Ge": ">=", "And": "&&", "Or": "||",
                   "Mul": "*", "Div": "/", "Mod": "%"})


def parse_expr(text: str) -> dict:
    """Best-effort parse a C value/condition string into an Expr dict."""
    if text is None:
        return {"Top": None}
    t = _strip_casts(str(text)).strip()
    if not t:
        return {"Top": None}

    ternary = _split_ternary(t)
    if ternary is not None:
        guard, then_expr, else_expr = ternary
        return {"Ite": {
            "guard": parse_expr(guard),
            "then": parse_expr(then_expr),
            "else": parse_expr(else_expr),
        }}

    # comparison / logical / bitwise / arithmetic (lowest precedence first)
    for sep in BINOPS:
        parts = _split_top(t, sep)
        if len(parts) > 1:
            op = BINOP_NAME[sep]
            expr = parse_expr(parts[0])
            for p in parts[1:]:
                expr = {"BinOp": {"op": op, "left": expr, "right": parse_expr(p)}}
            return expr

    # unary logical not, represented within the existing BinOp algebra
    if t.startswith("!") and not t.startswith("!="):
        return {"BinOp": {"op": "Eq", "left": parse_expr(t[1:]),
                          "right": {"Const": 0}}}

    # unary ~
    if t.startswith("~"):
        inner = parse_expr(t[1:])
        return {"BinOp": {"op": "BitXor", "left": inner, "right": {"Const": 0xFFFFFFFF}}}

    # BIT(n)
    m = re.fullmatch(r"BIT\s*\((.+)\)", t, re.I)
    if m:
        arg = parse_expr(m.group(1))
        # if arg is a constant, fold
        if "Const" in arg:
            return {"Const": (1 << arg["Const"]) & 0xFFFFFFFFFFFFFFFF}
        return {"BinOp": {"op": "Shl", "left": {"Const": 1}, "right": arg}}

    # bits slice expr[hi:lo] — rare in source; skip

    # parenthesized
    if t.startswith("(") and t.endswith(")"):
        return parse_expr(t[1:-1])

    # hex / dec literal
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", t):
        return {"Const": int(t, 16)}
    if re.fullmatch(r"\d+", t):
        return {"Const": int(t)}

    # identifier / member / call / complex → Var
    return {"Var": t}


def _split_ternary(text: str) -> tuple[str, str, str] | None:
    """Split a top-level C conditional expression, including nested ITEs."""
    depth = 0
    question = -1
    nested = 0
    for i, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and ch == "?":
            if question < 0:
                question = i
            else:
                nested += 1
        elif depth == 0 and ch == ":" and question >= 0:
            if nested:
                nested -= 1
            else:
                return text[:question], text[question + 1:i], text[i + 1:]
    return None


def expr_display(e: dict) -> str:
    if e is None:
        return "⊤"
    if "Const" in e:
        return f"0x{e['Const']:x}"
    if "Var" in e:
        return e["Var"]
    if "Top" in e:
        return "⊤"
    if "BinOp" in e:
        b = e["BinOp"]
        return f"({expr_display(b['left'])} {BINOP_SYM.get(b['op'], b['op'])} {expr_display(b['right'])})"
    if "Ite" in e:
        i = e["Ite"]
        return (f"({expr_display(i['guard'])} ? {expr_display(i['then'])}"
                f" : {expr_display(i['else'])})")
    if "Bits" in e:
        b = e["Bits"]
        return f"{expr_display(b['expr'])}[{b['hi']}:{b['lo']}]"
    return "⊤"


# ── Width / Intent ───────────────────────────────────────────────────

def width_of(n: int) -> str:
    return {1: "B1", 2: "B2", 4: "B4", 8: "B8"}.get(n, "B4")


# ── Expr → C source (inverse of parse_expr, for codegen) ─────────────

_ALL_ONES = 0xFFFFFFFF


def expr_to_c(e: dict | None) -> str:
    if e is None:
        return "0"
    if "Const" in e:
        return f"0x{e['Const']:x}"
    if "Var" in e:
        return e["Var"]
    if "Top" in e:
        return "0 /* TODO: unknown */"
    if "BinOp" in e:
        b = e["BinOp"]
        op = b["op"]
        left = expr_to_c(b["left"])
        right = expr_to_c(b["right"])
        # ~x is encoded as BitXor(x, 0xffffffff)
        if op == "BitXor" and "Const" in b["right"] and b["right"]["Const"] == _ALL_ONES:
            return f"(~{left})"
        sym = BINOP_SYM.get(op, op)
        return f"({left} {sym} {right})"
    if "Ite" in e:
        i = e["Ite"]
        return (f"({expr_to_c(i['guard'])} ? {expr_to_c(i['then'])}"
                f" : {expr_to_c(i['else'])})")
    if "Bits" in e:
        b = e["Bits"]
        inner = expr_to_c(b["expr"])
        width = b["hi"] - b["lo"] + 1
        return f"(({inner}) >> {b['lo']}) & ((1u << {width}) - 1)"
    return "0"


# ── formal RegAddr ───────────────────────────────────────────────────

def formal_addr(flat_addr: dict, reg_name: Optional[str]) -> dict:
    """Convert the flat ir::RegAddr + resolved macro name into a formal RegAddr."""
    if reg_name:
        base = ""
        if "Offset" in flat_addr:
            base = flat_addr["Offset"].get("base", "") or ""
        elif "Indirect" in flat_addr:
            base = flat_addr["Indirect"].get("base_reg", "") or ""
        return {"Symbolic": {"device": base, "register": reg_name}}
    if "Offset" in flat_addr:
        o = flat_addr["Offset"]
        return {"Fixed": {"base": o.get("base", ""), "offset": int(o.get("offset", 0))}}
    if "Indirect" in flat_addr:
        o = flat_addr["Indirect"]
        base_reg = o.get("base_reg", "")
        off = int(o.get("offset", 0))
        expr = {"Var": base_reg}
        dynamic = o.get("expr")
        if dynamic:
            expr = {"BinOp": {
                "op": "Add", "left": expr, "right": parse_expr(dynamic),
            }}
        if off:
            expr = {"BinOp": {
                "op": "Add", "left": expr, "right": {"Const": off},
            }}
        return {"Computed": expr}
    if "Fixed" in flat_addr:
        return {"Fixed": {"base": "", "offset": int(flat_addr["Fixed"])}}
    return {"Computed": {"Top": None}}


def addr_display(a: dict) -> str:
    if "Fixed" in a:
        f = a["Fixed"]
        return f"{f['base']}[0x{f['offset']:x}]" if f["base"] else f"0x{f['offset']:x}"
    if "Symbolic" in a:
        s = a["Symbolic"]
        return f"{s['device']}.{s['register']}" if s["device"] else s["register"]
    if "Computed" in a:
        return f"[{expr_display(a['Computed'])}]"
    return "?"


# ── RISOp ────────────────────────────────────────────────────────────

def op_display(op: dict, indent: int = 0) -> str:
    pad = "  " * indent

    def suffix(body):
        op_id = body.get("op_id")
        reliability = body.get("reliability")
        evidence = body.get("evidence") or {}
        source = evidence.get("source")
        line = evidence.get("line")
        audit = ""
        if op_id or reliability:
            audit += f" @{op_id or '?'} [{reliability or 'Unknown'}]"
        if source and line:
            audit += f" {source}:{line}"
        return audit

    if "Read" in op:
        o = op["Read"]
        return f"{pad}{o['var']} := R({o['width']}, {addr_display(o['addr'])}) -- {o['intent']}{suffix(o)}"
    if "Write" in op:
        o = op["Write"]
        return f"{pad}W({o['width']}, {addr_display(o['addr'])}) = {expr_display(o['value'])} -- {o['intent']}{suffix(o)}"
    if "ReadModifyWrite" in op:
        o = op["ReadModifyWrite"]
        return f"{pad}RMW({o['width']}, {addr_display(o['addr'])}) = {expr_display(o['transform'])} -- {o['intent']}{suffix(o)}"
    if "Delay" in op:
        return f"{pad}DELAY({expr_display(op['Delay']['cycles'])})"
    if "Cond" in op:
        o = op["Cond"]
        lines = [f"{pad}IF {expr_display(o['guard'])} {{"]
        for sub in o["then_ops"]:
            lines.append(op_display(sub, indent + 1))
        if o.get("else_ops"):
            lines.append(f"{pad}}} ELSE {{")
            for sub in o["else_ops"]:
                lines.append(op_display(sub, indent + 1))
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if "Seq" in op:
        lines = [f"{pad}SEQ {{"]
        for sub in op["Seq"]["ops"]:
            lines.append(op_display(sub, indent + 1))
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if "Loop" in op:
        o = op["Loop"]
        guard = o.get("guard")
        detail = expr_display(guard) if guard else expr_display(o["count"])
        lines = [f"{pad}LOOP {o.get('loop_kind', 'loop')} {detail} "
                 f"[{o.get('reliability', 'Unknown')}] {{"]
        for sub in o["body"]:
            lines.append(op_display(sub, indent + 1))
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    return f"{pad}?"


def formal_display(formal: dict) -> str:
    lines = [f"driver {formal['driver']} v{formal['version']} {{"]
    for m in formal["modules"]:
        lines.append(f"  module {m['name']} {{")
        for op in m["ops"]:
            lines.append(op_display(op, indent=2))
        lines.append("  }")
    accounting = formal.get("metadata", {}).get("access_accounting")
    if accounting:
        lines += ["  accounting {",
                  f"    source_accesses {accounting['source_accesses']}",
                  f"    emitted {accounting['emitted']}",
                  f"    filtered {accounting['filtered']}",
                  f"    unsupported {accounting['unsupported']}",
                  f"    unaccounted {accounting['unaccounted']}",
                  f"    ris_ops_without_evidence {accounting['ris_ops_without_evidence']}",
                  f"    strict_complete {str(accounting['strict_complete']).lower()}",
                  "  }"]
    validation = formal.get("metadata", {}).get("path_validation")
    if validation:
        lines += ["  path_validation {",
                  f"    solver \"{validation.get('solver', 'unknown')}\"",
                  f"    satisfiable {validation.get('satisfiable', 0)}",
                  f"    infeasible {validation.get('infeasible', 0)}",
                  f"    unknown {validation.get('unknown', 0)}",
                  f"    intentionally_unreachable {validation.get('intentionally_unreachable', 0)}",
                  f"    complete {str(validation.get('complete', False)).lower()}",
                  "  }"]
    lines.append("}")
    return "\n".join(lines)


def walk_leaf_ops(ops) -> "object":
    """Yield leaf RISOp dicts, recursing into Cond/Seq/Loop."""
    for op in ops:
        if "Cond" in op:
            yield from walk_leaf_ops(op["Cond"]["then_ops"])
            if op["Cond"].get("else_ops"):
                yield from walk_leaf_ops(op["Cond"]["else_ops"])
        elif "Seq" in op:
            yield from walk_leaf_ops(op["Seq"]["ops"])
        elif "Loop" in op:
            yield from walk_leaf_ops(op["Loop"]["body"])
        else:
            yield op


def walk_all_ops(ops) -> "object":
    """Yield every RISOp dict (including Cond/Seq/Loop), recursing into bodies.
    Used to count control-flow nodes at all nesting depths."""
    for op in ops:
        yield op
        if "Cond" in op:
            yield from walk_all_ops(op["Cond"]["then_ops"])
            if op["Cond"].get("else_ops"):
                yield from walk_all_ops(op["Cond"]["else_ops"])
        elif "Seq" in op:
            yield from walk_all_ops(op["Seq"]["ops"])
        elif "Loop" in op:
            yield from walk_all_ops(op["Loop"]["body"])


def emitted_stats(formal: dict) -> dict:
    """Count ops actually emitted in the .ris (only emitted modules' ops),
    excluding inlined-skipped helpers. Cond/Loop counted at all nesting depths."""
    reads = writes = rmw = conds = 0
    for m in formal["modules"]:
        for op in walk_all_ops(m["ops"]):
            if "Cond" in op or "Loop" in op:
                conds += 1
        for op in walk_leaf_ops(m["ops"]):
            if "Read" in op:
                reads += 1
            elif "Write" in op:
                writes += 1
            elif "ReadModifyWrite" in op:
                rmw += 1
    return {"mmio_reads": reads, "mmio_writes": writes, "rmw": rmw,
            "conditions_recorded": conds,
            "total_ops": reads + writes + rmw}
