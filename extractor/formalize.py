"""Convert the flat extraction into a FormalRIS (formal language).

- Nests ops under Cond{guard, then_ops} according to each op's cond_stack
  (path-insensitive: a maximal run of ops sharing a branch predicate becomes
  a Cond block).
- Parses value/condition strings into the Expr algebra.
- Builds register_map from the resolved macro table.
"""
from __future__ import annotations
from typing import Optional

from .dataflow import FuncExtraction, Op
from .ast_model import Func
from .intent import annotate
from . import formal as F


def _to_risop(op: Op, id_counter: list[int]) -> dict:
    addr = F.formal_addr(op.addr, op.reg_name)
    width = F.width_of(op.width)
    if op.kind == "Read":
        var = op.var or f"r{id_counter[0]}"
        return {"Read": {"addr": addr, "width": width, "var": var, "intent": op.intent}}
    if op.kind == "Write":
        return {"Write": {"addr": addr, "width": width,
                          "value": F.parse_expr(op.value), "intent": op.intent}}
    if op.kind == "ReadModifyWrite":
        return {"ReadModifyWrite": {"addr": addr, "width": width,
                                    "transform": F.parse_expr(op.value),
                                    "read_var": op.var,
                                    "intent": op.intent}}
    if op.kind == "Delay":
        ns = getattr(op, "_delay_ns", 0)
        return {"Delay": {"cycles": F.parse_expr(str(ns))}}
    return {"Seq": {"ops": []}}


def _nest(ops: list[Op], depth: int, id_counter: list[int]) -> list[dict]:
    """Build a nested RISOp list: ops whose cond_stack is deeper than `depth`
    become Cond{guard, then_ops} blocks."""
    result = []
    i = 0
    n = len(ops)
    while i < n:
        op = ops[i]
        st = op.cond_stack or []
        if len(st) > depth:
            guard = st[depth]
            run = []
            while (i < n and len(ops[i].cond_stack) > depth
                   and ops[i].cond_stack[depth] == guard):
                run.append(ops[i])
                i += 1
            then_ops = _nest(run, depth + 1, id_counter)
            result.append({"Cond": {"guard": F.parse_expr(guard),
                                     "then_ops": then_ops, "else_ops": None}})
        else:
            id_counter[0] += 1
            result.append(_to_risop(op, id_counter))
            i += 1
    return result


def _module(func: Func, ex: FuncExtraction, id_counter: list[int]) -> dict:
    # annotate intents first (uses reg_name + addr + func name)
    for op in ex.ops:
        annotate(op, func.name)
    ops = _nest(list(ex.ops), 0, id_counter)
    src = func.cursor.location
    source = None
    if src and src.file:
        source = [src.file.name, func.line, func.line]
    return {"name": func.name, "ops": ops, "source": source}


def _register_map(funcs, extractions, macros) -> list[dict]:
    """Register map = the device registers actually accessed by the driver
    (reg_name values appearing in extracted ops), resolved to their offsets."""
    seen: dict[str, int] = {}   # name -> width (bits)
    for f in funcs:
        ex = extractions.get(f.name)
        if not ex:
            continue
        for op in ex.ops:
            name = op.reg_name
            if not name or name in seen:
                continue
            off = macros.offset(name)
            if off is None:
                continue
            seen[name] = op.width or 4
    out = []
    for name, w in seen.items():
        out.append({"name": name, "offset": int(macros.offset(name)),
                    "width": F.width_of(w), "description": ""})
    out.sort(key=lambda r: r["offset"])
    return out


def build_formal_ris(driver_name: str, source_path: str,
                     funcs: list[Func],
                     extractions: dict[str, FuncExtraction],
                     macros, stats: dict,
                     inlined_names: set | None = None) -> dict:
    """Build the FormalRIS dict. Functions in `inlined_names` are skipped —
    their ops already appear (inlined) inside their callers, so emitting them
    again would duplicate the RIS."""
    inlined_names = inlined_names or set()
    id_counter = [0]
    modules = []
    for f in funcs:
        if f.name in inlined_names:
            continue   # inlined into a caller — avoid duplicate module
        ex = extractions.get(f.name)
        if not ex or not ex.ops:
            continue
        modules.append(_module(f, ex, id_counter))

    return {
        "driver": driver_name,
        "version": "0.1.0",
        "modules": modules,
        "register_map": _register_map(funcs, extractions, macros),
        "metadata": {
            "source": source_path,
            "extracted_at": stats.get("extracted_at", ""),
            "verified": False,
            "runtime_trace": None,
            "tool": "reharness",
        },
    }


def save_formal_text(formal: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(F.formal_display(formal))
        fh.write("\n")
