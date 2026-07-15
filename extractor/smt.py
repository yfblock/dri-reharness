"""Bounded SMT validation for FormalRIS path predicates.

The solver is used to detect contradictory lexical paths and validate switch
case exclusivity. It does not claim whole-program reachability: unconstrained
source values remain symbolic bit-vectors.
"""
from __future__ import annotations

import hashlib


class UnsupportedExpr(Exception):
    pass


def _symbol_name(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"v_{digest}"


def _translator():
    import z3

    symbols = {}

    def bv(value):
        if z3.is_bool(value):
            return z3.If(value, z3.BitVecVal(1, 64), z3.BitVecVal(0, 64))
        return value

    def boolean(value):
        if z3.is_bool(value):
            return value
        return value != z3.BitVecVal(0, 64)

    def translate(expr):
        if not isinstance(expr, dict) or "Top" in expr:
            raise UnsupportedExpr("Top/non-expression path term")
        if "Const" in expr:
            return z3.BitVecVal(int(expr["Const"]) & ((1 << 64) - 1), 64)
        if "Var" in expr:
            text = str(expr["Var"])
            symbols.setdefault(text, z3.BitVec(_symbol_name(text), 64))
            return symbols[text]
        if "Bits" in expr:
            bits = expr["Bits"]
            value = bv(translate(bits["expr"]))
            return z3.Extract(int(bits["hi"]), int(bits["lo"]), value)
        if "Ite" in expr:
            ite = expr["Ite"]
            guard = boolean(translate(ite["guard"]))
            then = translate(ite["then"])
            other = translate(ite["else"])
            if z3.is_bool(then) != z3.is_bool(other):
                then, other = bv(then), bv(other)
            return z3.If(guard, then, other)
        if "BinOp" not in expr:
            raise UnsupportedExpr("unknown expression variant")
        node = expr["BinOp"]
        op = node["op"]
        left = translate(node["left"])
        right = translate(node["right"])
        if op == "And":
            return z3.And(boolean(left), boolean(right))
        if op == "Or":
            return z3.Or(boolean(left), boolean(right))
        if op in {"Eq", "Ne", "Lt", "Gt", "Le", "Ge"}:
            left, right = bv(left), bv(right)
            return {
                "Eq": left == right, "Ne": left != right,
                "Lt": z3.ULT(left, right), "Gt": z3.UGT(left, right),
                "Le": z3.ULE(left, right), "Ge": z3.UGE(left, right),
            }[op]
        left, right = bv(left), bv(right)
        if op == "Add": return left + right
        if op == "Sub": return left - right
        if op == "Mul": return left * right
        if op == "Div": return z3.UDiv(left, right)
        if op == "Mod": return z3.URem(left, right)
        if op == "BitAnd": return left & right
        if op == "BitOr": return left | right
        if op == "BitXor": return left ^ right
        if op == "Shl": return left << right
        if op == "Shr": return z3.LShR(left, right)
        raise UnsupportedExpr(f"unsupported operator: {op}")

    return z3, translate, boolean


def validate_formal_paths(formal: dict, timeout_ms: int = 100) -> dict:
    condition_nodes = []
    for module in formal.get("modules", []):
        stack = list(module.get("ops", []))
        while stack:
            op = stack.pop()
            if "Cond" in op:
                condition_nodes.append(op["Cond"])
                stack.extend(op["Cond"].get("then_ops", []))
                stack.extend(op["Cond"].get("else_ops") or [])
            elif "Loop" in op:
                condition_nodes.append(op["Loop"])
                stack.extend(op["Loop"].get("body", []))
            elif "Seq" in op:
                stack.extend(op["Seq"].get("ops", []))
    if not condition_nodes:
        return {
            "solver": "not-needed", "complete": True, "paths": [],
            "satisfiable": 0, "infeasible": 0, "unknown": 0,
            "switch_pairs": [],
        }

    try:
        z3, translate, boolean = _translator()
        solver_name = f"Z3 {z3.get_version_string()}"
    except Exception as exc:
        return {
            "solver": "unavailable", "complete": False, "paths": [],
            "satisfiable": 0, "infeasible": 0,
            "unknown": len(condition_nodes), "switch_pairs": [],
            "diagnostics": [str(exc)],
        }

    records = []
    switch_pairs = []
    next_id = [0]

    def check(constraints):
        solver = z3.Solver()
        solver.set(timeout=timeout_ms)
        solver.add(*constraints)
        result = solver.check()
        if result == z3.sat:
            return "satisfiable"
        if result == z3.unsat:
            return "infeasible"
        return "unknown"

    def walk(ops, constraints, module_name):
        switch_groups = {}
        for op in ops:
            if "Cond" in op:
                node = op["Cond"]
                next_id[0] += 1
                path_id = f"path_{next_id[0]}"
                control = node.get("control") or {}
                intentionally_unreachable = (
                    control.get("branch") == "unreachable"
                    and control.get("source") == "early-exit")
                if intentionally_unreachable:
                    guard = None
                    status = "intentionally_unreachable"
                else:
                    try:
                        guard = boolean(translate(node["guard"]))
                        status = check(constraints + [guard])
                    except Exception as exc:
                        guard = None
                        status = "unknown"
                        node["validation_error"] = str(exc)
                node["path_id"] = path_id
                node["validation"] = status
                records.append({
                    "path_id": path_id, "module": module_name,
                    "status": status, "control": node.get("control", {}),
                })
                if control.get("switch"):
                    switch_groups.setdefault(control["switch"], []).append(node)
                if not intentionally_unreachable:
                    walk(node.get("then_ops", []),
                         constraints + ([guard] if guard is not None else []),
                         module_name)
                walk(node.get("else_ops") or [], constraints, module_name)
            elif "Loop" in op:
                node = op["Loop"]
                next_id[0] += 1
                path_id = f"path_{next_id[0]}"
                try:
                    guard = boolean(translate(node["guard"]))
                    status = check(constraints + [guard])
                except Exception as exc:
                    guard = None
                    status = "unknown"
                    node["validation_error"] = str(exc)
                node["path_id"] = path_id
                node["validation"] = status
                records.append({"path_id": path_id, "module": module_name,
                                "status": status, "control": "loop"})
                walk(node.get("body", []),
                     constraints + ([guard] if guard is not None else []),
                     module_name)
            elif "Seq" in op:
                walk(op["Seq"].get("ops", []), constraints, module_name)

        for switch, nodes in switch_groups.items():
            for index, left in enumerate(nodes):
                for right in nodes[index + 1:]:
                    try:
                        pair_status = check(constraints + [
                            boolean(translate(left["guard"])),
                            boolean(translate(right["guard"])),
                        ])
                    except Exception:
                        pair_status = "unknown"
                    switch_pairs.append({
                        "switch": switch,
                        "left": left.get("path_id"),
                        "right": right.get("path_id"),
                        "exclusive": pair_status == "infeasible",
                        "status": pair_status,
                    })

    for module in formal.get("modules", []):
        walk(module.get("ops", []), [], module["name"])

    counts = {status: sum(record["status"] == status for record in records)
              for status in ("satisfiable", "infeasible", "unknown",
                             "intentionally_unreachable")}
    return {
        "solver": solver_name,
        "timeout_ms": timeout_ms,
        "complete": counts["unknown"] == 0,
        "paths": records,
        **counts,
        "switch_pairs": switch_pairs,
    }
