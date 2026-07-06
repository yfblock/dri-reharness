"""Per-module and driver-level extraction quality metrics (plan Milestone 1).

Counts: total ops, symbolic/fixed/computed address counts, unknown (Top) value
count, condition/loop count, clang diagnostic count. Used by the readiness
scorer (Milestone 8) and the `metrics` CLI.
"""
from __future__ import annotations
from .formal import walk_leaf_ops, walk_all_ops


def _addr_kind(addr: dict) -> str | None:
    if not addr:
        return None
    if "Symbolic" in addr:
        return "symbolic"
    if "Fixed" in addr:
        return "fixed"
    if "Computed" in addr:
        return "computed"
    return None


def _value_is_top(expr: dict | None) -> bool:
    if expr is None:
        return False
    return "Top" in expr


def _expr_has_top(expr: dict | None) -> bool:
    """True if the Expr contains any Top (unknown) sub-term."""
    if expr is None:
        return False
    if "Top" in expr:
        return True
    if "BinOp" in expr:
        b = expr["BinOp"]
        return _expr_has_top(b.get("left")) or _expr_has_top(b.get("right"))
    if "Bits" in expr:
        return _expr_has_top(expr["Bits"].get("expr"))
    return False


def module_metrics(module: dict) -> dict:
    ops = list(walk_leaf_ops(module["ops"]))
    total = len(ops)
    sym = fixed = comp = 0
    unknown_val = 0
    for o in ops:
        addr = (o.get("Read") or o.get("Write") or o.get("ReadModifyWrite") or {}).get("addr")
        k = _addr_kind(addr)
        if k == "symbolic":
            sym += 1
        elif k == "fixed":
            fixed += 1
        elif k == "computed":
            comp += 1
        # unknown value: Write/RMW value or transform is Top or contains Top
        val = None
        if "Write" in o:
            val = o["Write"].get("value")
        elif "ReadModifyWrite" in o:
            val = o["ReadModifyWrite"].get("transform")
        if _value_is_top(val) or _expr_has_top(val):
            unknown_val += 1
    cond = sum(1 for o in walk_all_ops(module["ops"]) if "Cond" in o)
    loop = sum(1 for o in walk_all_ops(module["ops"]) if "Loop" in o)
    addr_total = sym + fixed + comp
    return {
        "module": module["name"],
        "total_ops": total,
        "symbolic": sym,
        "fixed": fixed,
        "computed": comp,
        "unknown_value": unknown_val,
        "cond": cond,
        "loop": loop,
        "pct_symbolic": round(sym / addr_total, 3) if addr_total else None,
    }


def driver_metrics(formal: dict, n_clang_diag: int = 0) -> dict:
    mods = [module_metrics(m) for m in formal["modules"]]
    agg = {k: 0 for k in ("total_ops", "symbolic", "fixed", "computed",
                           "unknown_value", "cond", "loop")}
    for m in mods:
        for k in agg:
            agg[k] += m[k]
    addr_total = agg["symbolic"] + agg["fixed"] + agg["computed"]
    agg["pct_symbolic"] = round(agg["symbolic"] / addr_total, 3) if addr_total else None
    agg["pct_non_top_value"] = round(
        (agg["total_ops"] - agg["unknown_value"]) / agg["total_ops"], 3
    ) if agg["total_ops"] else None
    agg["clang_diag"] = n_clang_diag
    agg["modules"] = mods
    agg["register_map"] = len(formal.get("register_map", []))
    return agg


def format_metrics(metrics: dict) -> str:
    lines = [
        f"driver metrics: {metrics['total_ops']} ops | "
        f"symbolic {metrics['symbolic']} fixed {metrics['fixed']} computed {metrics['computed']} | "
        f"unknown_value {metrics['unknown_value']} | cond {metrics['cond']} loop {metrics['loop']} | "
        f"pct_symbolic {metrics['pct_symbolic']} pct_non_top {metrics['pct_non_top_value']} | "
        f"clang_diag {metrics['clang_diag']} | regs {metrics['register_map']}",
        "",
        f"{'module':<28} {'ops':>4} {'sym':>4} {'fix':>4} {'cmp':>4} {'unk':>4} {'cond':>4} {'loop':>4} {'%sym':>5}",
        "-" * 78,
    ]
    for m in metrics["modules"]:
        lines.append(
            f"{m['module']:<28} {m['total_ops']:>4} {m['symbolic']:>4} {m['fixed']:>4} "
            f"{m['computed']:>4} {m['unknown_value']:>4} {m['cond']:>4} {m['loop']:>4} "
            f"{str(m['pct_symbolic']):>5}"
        )
    return "\n".join(lines)
