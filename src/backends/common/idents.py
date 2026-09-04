"""Identifier analysis over formal expressions and op lists."""
from __future__ import annotations

import re

from extractor.formal import walk_all_ops

_VAR_ID = re.compile(r"^[A-Za-z_]\w*$")

_C_KEYWORDS = {
    "auto", "char", "const", "double", "enum", "extern", "float", "for",
    "int", "long", "register", "restrict", "short", "signed", "static",
    "struct", "typedef", "union", "unsigned", "void", "volatile", "while",
}


def called_names_in_text(text: str) -> set[str]:
    names = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text or ""))
    # Linux polling macros take the read accessor as their first argument and
    # invoke it internally.  That identifier is a function, not a scalar
    # local, even though source syntax does not place `(` immediately after it.
    for match in re.finditer(
            r"\bread_poll_timeout(?:_atomic)?\s*\(\s*([A-Za-z_]\w*)",
            text or ""):
        names.add(match.group(1))
    return names


def vars_in_expr(e) -> set[str]:
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
        out -= called_names_in_text(v)
    if "BinOp" in e:
        out |= vars_in_expr(e["BinOp"]["left"])
        out |= vars_in_expr(e["BinOp"]["right"])
    if "Ite" in e:
        out |= vars_in_expr(e["Ite"]["guard"])
        out |= vars_in_expr(e["Ite"]["then"])
        out |= vars_in_expr(e["Ite"]["else"])
    if "Bits" in e:
        out |= vars_in_expr(e["Bits"]["expr"])
    return out

def value_var_names(ops) -> set[str]:
    """Identifiers referenced in values, guards, or computed addresses."""
    names: set[str] = set()
    for op in walk_all_ops(ops):
        if "Cond" in op:
            names |= vars_in_expr(op["Cond"]["guard"])
        elif "Loop" in op:
            names |= vars_in_expr(op["Loop"].get("guard"))
            for loop_text in (op["Loop"].get("init", ""),
                              op["Loop"].get("step", "")):
                loop_names = {
                    name for name in re.findall(r"\b[A-Za-z_]\w*\b", loop_text)
                    if name not in _C_KEYWORDS
                }
                names |= loop_names - called_names_in_text(loop_text)
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body and "Computed" in body.get("addr", {}):
            names |= vars_in_expr(body["addr"]["Computed"])
        if "Write" in op:
            names |= vars_in_expr(op["Write"].get("value"))
        elif "ReadModifyWrite" in op:
            names |= vars_in_expr(op["ReadModifyWrite"].get("transform"))
        elif "StateWrite" in op:
            names |= vars_in_expr(op["StateWrite"].get("value"))
        elif "OutputWrite" in op:
            names |= vars_in_expr(op["OutputWrite"].get("value"))
        elif "Return" in op:
            names |= vars_in_expr(op["Return"].get("value"))
    return names

def is_simple_id(name: str) -> bool:
    return bool(_VAR_ID.match(name))

def replace_expr_var(expr, name: str | None, replacement: str):
    if not isinstance(expr, dict) or not name:
        return expr
    if expr.get("Var") == name:
        return {"Var": replacement}
    out = dict(expr)
    if "BinOp" in expr:
        b = dict(expr["BinOp"])
        b["left"] = replace_expr_var(b.get("left"), name, replacement)
        b["right"] = replace_expr_var(b.get("right"), name, replacement)
        out["BinOp"] = b
    elif "Ite" in expr:
        i = dict(expr["Ite"])
        i["guard"] = replace_expr_var(i.get("guard"), name, replacement)
        i["then"] = replace_expr_var(i.get("then"), name, replacement)
        i["else"] = replace_expr_var(i.get("else"), name, replacement)
        out["Ite"] = i
    elif "Bits" in expr:
        b = dict(expr["Bits"])
        b["expr"] = replace_expr_var(b.get("expr"), name, replacement)
        out["Bits"] = b
    return out
