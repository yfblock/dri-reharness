"""Convert the flat extraction into a FormalRIS (formal language).

- Nests ops under Cond{guard, then_ops} according to each op's cond_stack
  (path-insensitive: a maximal run of ops sharing a branch predicate becomes
  a Cond block).
- Parses value/condition strings into the Expr algebra.
- Builds register_map from the resolved macro table.
"""
from __future__ import annotations
import copy
import re
from typing import Optional

from .dataflow import FuncExtraction, Op
from .ast_model import Func
from .intent import annotate
from . import formal as F
from .formal import walk_leaf_ops
from .macros import _eval_int_expr


def _expr_has_top(expr) -> bool:
    if not isinstance(expr, dict):
        return False
    if "Top" in expr:
        return True
    return any(_expr_has_top(value) for value in expr.values())


def _common_fields(op: Op, op_id: str, addr: dict, value=None) -> dict:
    if "Symbolic" in addr:
        address_precision = "symbolic"
    elif "Fixed" in addr:
        address_precision = "fixed"
    elif "Computed" in addr:
        address_precision = ("unknown" if _expr_has_top(addr["Computed"])
                             else "computed")
    else:
        address_precision = "unknown"
    value_precision = "unknown" if _expr_has_top(value) else "exact"
    path_precision = "syntactic" if op.cond_stack else "unconditional"
    domain = (op.evidence or {}).get("access_domain", "mmio")
    reliability = ("Unsupported" if domain != "mmio"
                   else "Unknown" if "unknown" in {address_precision, value_precision}
                   else "Conservative" if path_precision == "syntactic"
                   else "Exact")
    return {
        "op_id": op_id,
        "evidence": dict(op.evidence),
        "reliability": reliability,
        "address_precision": address_precision,
        "value_precision": value_precision,
        "path_precision": path_precision,
        "access_domain": domain,
    }


def _semantic_fields(op: Op, op_id: str, value=None) -> dict:
    value_precision = "unknown" if _expr_has_top(value) else "exact"
    path_precision = "syntactic" if op.cond_stack else "unconditional"
    domain = (op.evidence or {}).get("access_domain", "source_state")
    reliability = ("Unsupported" if domain.startswith("unsupported")
                   else "Unknown" if value_precision == "unknown"
                   else "Conservative" if path_precision == "syntactic"
                   else "Exact")
    return {
        "op_id": op_id,
        "evidence": dict(op.evidence),
        "reliability": reliability,
        "value_precision": value_precision,
        "path_precision": path_precision,
        "access_domain": domain,
    }


def _to_risop(op: Op, id_counter: list[int]) -> dict:
    addr = F.formal_addr(op.addr, op.reg_name)
    width = F.width_of(op.width)
    op_id = f"op_{id_counter[0]}"
    if op.kind == "Read":
        var = op.var or f"r{id_counter[0]}"
        body = {"addr": addr, "width": width, "var": var, "intent": op.intent}
        body.update(_common_fields(op, op_id, addr))
        return {"Read": body}
    if op.kind == "Write":
        value = F.parse_expr(op.value)
        body = {"addr": addr, "width": width,
                "value": value, "intent": op.intent}
        body.update(_common_fields(op, op_id, addr, value))
        return {"Write": body}
    if op.kind == "ReadModifyWrite":
        transform = F.parse_expr(op.value)
        body = {"addr": addr, "width": width,
                "transform": transform, "read_var": op.var,
                "intent": op.intent}
        body.update(_common_fields(op, op_id, addr, transform))
        return {"ReadModifyWrite": body}
    if op.kind == "StateRead":
        body = {"field": op.state_field, "var": op.var or f"s{id_counter[0]}",
                "width": width}
        body.update(_semantic_fields(op, op_id))
        return {"StateRead": body}
    if op.kind == "StateWrite":
        value = F.parse_expr(op.value)
        body = {"field": op.state_field, "value": value, "width": width}
        body.update(_semantic_fields(op, op_id, value))
        return {"StateWrite": body}
    if op.kind == "OutputWrite":
        value = F.parse_expr(op.value)
        body = {"target": op.var, "value": value}
        body.update(_semantic_fields(op, op_id, value))
        return {"OutputWrite": body}
    if op.kind == "Return":
        value = F.parse_expr(op.value)
        body = {"value": value}
        body.update(_semantic_fields(op, op_id, value))
        return {"Return": body}
    if op.kind == "Delay":
        ns = getattr(op, "_delay_ns", 0)
        return {"Delay": {"cycles": F.parse_expr(str(ns))}}
    return {"Seq": {"ops": []}}


def _loop_int(text: str, macros) -> int | None:
    value = _eval_int_expr(text)
    if value is not None:
        return value
    token = text.strip()
    if macros is None:
        return None
    direct = macros.offset(token)
    if direct is not None:
        return direct
    raw = macros.raw(token)
    if not raw:
        count = re.fullmatch(r"([A-Za-z_]\w*)_CNT", token)
        if count:
            maximum = macros.offset(count.group(1) + "_MAX")
            if maximum is not None:
                return maximum + 1
        return None
    expanded = raw
    for _round in range(8):
        changed = False
        for name in set(re.findall(r"\b[A-Za-z_]\w*\b", expanded)):
            value = macros.offset(name)
            if value is None:
                continue
            replaced = re.sub(rf"\b{re.escape(name)}\b", str(value), expanded)
            changed |= replaced != expanded
            expanded = replaced
        if not changed:
            break
    return _eval_int_expr(expanded)


def _bounded_loop(frame: dict, macros) -> dict | None:
    """Prove a simple monotonic for-loop bound, capped for safe lowering."""
    if frame.get("loop_kind") != "for":
        return None
    init = (frame.get("init") or "").strip().rstrip(";")
    guard = (frame.get("guard") or "").strip()
    step = (frame.get("step") or "").strip().rstrip(";")
    init_match = re.fullmatch(
        r"(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*(.+)", init)
    if not init_match:
        return None
    var, start_text = init_match.groups()
    guard_match = re.fullmatch(
        rf"{re.escape(var)}\s*(<|<=)\s*(.+)", guard)
    if not guard_match:
        return None
    relation, bound_text = guard_match.groups()
    if re.fullmatch(rf"(?:{re.escape(var)}\+\+|\+\+{re.escape(var)})", step):
        stride = 1
    else:
        step_match = re.fullmatch(
            rf"{re.escape(var)}\s*\+=\s*(.+)", step)
        stride = _loop_int(step_match.group(1), macros) if step_match else None
    start = _loop_int(start_text, macros)
    bound = _loop_int(bound_text, macros)
    if start is None or bound is None or stride is None or stride <= 0:
        return None
    distance = bound - start + (1 if relation == "<=" else 0)
    count = 0 if distance <= 0 else (distance + stride - 1) // stride
    if count > 256:
        return None
    return {
        "count": {"Const": count},
        "reliability": "Exact",
        "bounded": True,
        "induction_var": var,
        "start": start,
        "bound": bound,
        "stride": stride,
        "proof": "canonical monotonic for-loop",
    }


def _runtime_bounded_loop(frame: dict) -> dict | None:
    """Prove a canonical loop whose finite count is device state."""
    if frame.get("loop_kind") != "for":
        return None
    init = (frame.get("init") or "").strip().rstrip(";")
    guard = (frame.get("guard") or "").strip()
    step = (frame.get("step") or "").strip().rstrip(";")
    init_match = re.fullmatch(
        r"(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*0", init)
    if not init_match:
        return None
    var = init_match.group(1)
    guard_match = re.fullmatch(
        rf"{re.escape(var)}\s*<\s*"
        r"([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+)", guard)
    if not guard_match or not re.fullmatch(
            rf"(?:{re.escape(var)}\+\+|\+\+{re.escape(var)})", step):
        return None
    bound = guard_match.group(1)
    return {
        "count": F.parse_expr(bound),
        "reliability": "Exact",
        "bounded": True,
        "dynamic_bound": True,
        "induction_var": var,
        "start": 0,
        "stride": 1,
        "proof": "canonical monotonic loop bounded by device state",
    }


def _replace_expr_vars(expr: dict, mapping: dict[str, str]) -> dict:
    if not isinstance(expr, dict):
        return expr
    if "Var" in expr and expr["Var"] in mapping:
        return {"Var": mapping[expr["Var"]]}
    out = copy.deepcopy(expr)
    if "BinOp" in out:
        out["BinOp"]["left"] = _replace_expr_vars(
            out["BinOp"].get("left"), mapping)
        out["BinOp"]["right"] = _replace_expr_vars(
            out["BinOp"].get("right"), mapping)
    elif "Ite" in out:
        for key in ("guard", "then", "else"):
            out["Ite"][key] = _replace_expr_vars(
                out["Ite"].get(key), mapping)
    elif "Bits" in out:
        out["Bits"]["expr"] = _replace_expr_vars(
            out["Bits"].get("expr"), mapping)
    return out


def _array_state_op(kind: str, template: dict, field: str, index: str,
                    id_counter: list[int], *, var: str | None = None,
                    value: dict | None = None) -> dict:
    id_counter[0] += 1
    evidence = copy.deepcopy(template.get("evidence", {}))
    evidence["access_domain"] = "source_state"
    body = {
        "field": field, "index": {"Var": index}, "width": "B4",
        "op_id": f"op_{id_counter[0]}", "evidence": evidence,
        "reliability": template.get("reliability", "Exact"),
        "value_precision": "exact",
        "path_precision": template.get("path_precision", "syntactic"),
        "access_domain": "source_state",
    }
    if kind == "StateRead":
        body["var"] = var or field
    else:
        body["value"] = value or {"Const": 0}
    return {kind: body}


def _lower_loop_private_arrays(frame: dict, body: list[dict],
                               id_counter: list[int]) -> list[dict]:
    """Lower loop-local aggregate aliases to indexed persistent state."""
    source = frame.get("source", "")
    induction = re.search(
        r"for\s*\(\s*([A-Za-z_]\w*)\s*=\s*0\s*;", source)
    if not induction:
        return body
    index = induction.group(1)
    scalar = re.search(
        rf"\b([A-Za-z_]\w*)\s*=\s*"
        rf"([A-Za-z_]\w*->([A-Za-z_]\w*)\[{re.escape(index)}\]\."
        r"([A-Za-z_]\w*))\s*;", source)
    context = re.search(
        rf"\*\s*([A-Za-z_]\w*)\s*=\s*"
        rf"[A-Za-z_]\w*->([A-Za-z_]\w*)\[{re.escape(index)}\]\."
        r"([A-Za-z_]\w*)\s*;", source)
    if not scalar or not context:
        return body
    scalar_var, scalar_expr, array_name, scalar_field = scalar.groups()
    context_var, context_array, context_field = context.groups()
    if array_name != context_array:
        return body
    scalar_state = f"{array_name}_{scalar_field}"
    prefix = f"{context_array}_{context_field}_"

    template = next((
        op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        for op in walk_leaf_ops(body)
        if op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")), {})
    lowered = [_array_state_op(
        "StateRead", template, scalar_state, index, id_counter,
        var=scalar_var)]
    mapping = {scalar_expr: scalar_var}

    def transform(items: list[dict]) -> list[dict]:
        result = []
        for original in items:
            op = copy.deepcopy(original)
            if "Cond" in op:
                op["Cond"]["guard"] = _replace_expr_vars(
                    op["Cond"].get("guard"), mapping)
                op["Cond"]["then_ops"] = transform(
                    op["Cond"].get("then_ops", []))
                op["Cond"]["else_ops"] = transform(
                    op["Cond"].get("else_ops") or []) or None
                result.append(op)
                continue
            if "Seq" in op:
                op["Seq"]["ops"] = transform(op["Seq"].get("ops", []))
                result.append(op)
                continue
            access = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if access and "Computed" in access.get("addr", {}):
                access["addr"]["Computed"] = _replace_expr_vars(
                    access["addr"]["Computed"], mapping)
            if "Read" in op and re.fullmatch(
                    rf"{re.escape(context_var)}->([A-Za-z_]\w*)",
                    op["Read"].get("var", "")):
                field = re.fullmatch(
                    rf"{re.escape(context_var)}->([A-Za-z_]\w*)",
                    op["Read"]["var"]).group(1)
                local = f"loop_state_{field}_value"
                op["Read"]["var"] = local
                result.append(op)
                result.append(_array_state_op(
                    "StateWrite", op["Read"], prefix + field, index,
                    id_counter, value={"Var": local}))
                continue
            expressions = []
            if "Write" in op:
                expressions.append((op["Write"], "value"))
            elif "ReadModifyWrite" in op:
                expressions.append((op["ReadModifyWrite"], "transform"))
            reads = set()
            for holder, key in expressions:
                rendered = repr(holder.get(key, {}))
                reads |= set(re.findall(
                    rf"{re.escape(context_var)}->([A-Za-z_]\w*)", rendered))
            local_mapping = dict(mapping)
            for field in sorted(reads):
                local = f"loop_state_{field}"
                result.append(_array_state_op(
                    "StateRead", access or template, prefix + field, index,
                    id_counter, var=local))
                local_mapping[f"{context_var}->{field}"] = local
            for holder, key in expressions:
                holder[key] = _replace_expr_vars(holder.get(key), local_mapping)
            result.append(op)
        return result

    lowered.extend(transform(body))
    return lowered


def _w1c_drain_loop(frame: dict, body: list[dict]) -> dict | None:
    """Prove a masked W1C drain loop under an explicit quiescence assumption."""
    if frame.get("loop_kind") != "while" or len(body) != 3:
        return None
    first, second, write = body
    if not ("Read" in first and "Read" in second and "Write" in write):
        return None
    pending = first["Read"]
    mask = second["Read"]
    acknowledge = write["Write"]
    value = acknowledge.get("value", {})
    if pending.get("addr") != acknowledge.get("addr") or "Var" not in value:
        return None
    status = value["Var"]
    guard_text = frame.get("guard", "")
    if (not re.search(rf"\b{re.escape(status)}\s*=", guard_text)
            or "&" not in guard_text):
        return None
    acknowledge.setdefault("evidence", {})["write_semantics"] = "w1c"
    return {
        "count": {"Const": 1},
        "reliability": "Exact",
        "bounded": True,
        "proof_kind": "masked_w1c_drain",
        "proof": "pending-and-mask guard acknowledged through W1C register",
        "environment_assumptions": [
            "no new pending bits arrive while the drain handler executes"],
        "max_iterations": 1,
        "guard_var": status,
        "guard_value": {"BinOp": {
            "op": "BitAnd", "left": {"Var": pending["var"]},
            "right": {"Var": mask["var"]},
        }},
        "guard_ops": [first, second],
        "body": [write],
    }


def _nest(ops: list[Op], depth: int, id_counter: list[int], macros) -> list[dict]:
    """Build nested Cond/Loop nodes from structured lexical control frames."""
    result = []
    i = 0
    n = len(ops)
    while i < n:
        op = ops[i]
        st = (op.control_stack or [
            {"kind": "cond", "guard": guard} for guard in (op.cond_stack or [])])
        if len(st) > depth:
            frame = st[depth]
            run = []
            while i < n:
                other_stack = (ops[i].control_stack or [
                    {"kind": "cond", "guard": guard}
                    for guard in (ops[i].cond_stack or [])])
                if len(other_stack) <= depth or other_stack[depth] != frame:
                    break
                run.append(ops[i])
                i += 1
            body = _nest(run, depth + 1, id_counter, macros)
            if frame.get("kind") == "loop":
                loop = {
                    "count": {"Top": None},
                    "guard": F.parse_expr(frame.get("guard")),
                    "loop_kind": frame.get("loop_kind", "loop"),
                    "init": frame.get("init", ""),
                    "step": frame.get("step", ""),
                    "source": frame.get("source", ""),
                    "reliability": "Conservative",
                    "body": body,
                }
                proof = _bounded_loop(frame, macros)
                if proof is None:
                    proof = _runtime_bounded_loop(frame)
                if proof is None:
                    proof = _w1c_drain_loop(frame, body)
                if proof:
                    loop.update(proof)
                    if proof.get("dynamic_bound"):
                        loop["body"] = _lower_loop_private_arrays(
                            frame, body, id_counter)
                result.append({"Loop": loop})
            else:
                result.append({"Cond": {
                    "guard": F.parse_expr(frame.get("guard")),
                    "control": dict(frame),
                    "then_ops": body, "else_ops": None}})
        else:
            id_counter[0] += 1
            result.append(_to_risop(op, id_counter))
            i += 1
    return result


def _module(func: Func, ex: FuncExtraction, id_counter: list[int], macros) -> dict:
    # annotate intents first (uses reg_name + addr + func name)
    for op in ex.ops:
        annotate(op, func.name)
    ops = _nest(list(ex.ops), 0, id_counter, macros)
    src = func.cursor.location if func.cursor is not None else None
    source = None
    if src and src.file:
        source = [src.file.name, func.line, func.line]
    elif func.source_path:
        source = [func.source_path, func.line, func.line]
    return {"name": func.module_name or func.name, "ops": ops, "source": source}


def _register_map(funcs, extractions, macros) -> list[dict]:
    """Register map = the device registers actually accessed by the driver
    (reg_name values appearing in extracted ops), resolved to their offsets."""
    seen: dict[str, int] = {}   # name -> width (bits)
    for f in funcs:
        ex = extractions.get(f.symbol_id or f.name)
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
        symbol = f.symbol_id or f.name
        if symbol in inlined_names:
            continue   # inlined into a caller — avoid duplicate module
        ex = extractions.get(symbol)
        if not ex or not ex.ops:
            continue
        modules.append(_module(f, ex, id_counter, macros))

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
            "alias_analysis": stats.get("alias_analysis", {
                "mode": "off", "status": "off", "facts": {}}),
            "wrapper_analysis": {
                "count": stats.get("wrapper_summary_count", 0),
                "summaries": stats.get("wrapper_summaries", []),
            },
            "subsystem_summary_analysis": {
                "synthetic_functions": stats.get(
                    "synthetic_subsystem_functions", 0),
                "summaries": stats.get("subsystem_summaries", []),
            },
            "function_macros": stats.get("function_macros", {}),
            "assurance_scope": {
                "claim": "recognized register-access and structured-control universe",
                "register_accesses": (
                    "known MMIO/regmap APIs plus direct volatile and inline-asm detection"),
                "control_flow": (
                    "source statement CFG with dominance/joins, structured lexical paths, "
                    "resolved forward-goto guards, switch exclusivity, and bounded loops"),
                "alias_analysis": (
                    "off" if stats.get("alias_analysis", {}).get("mode") == "off"
                    else ("manifest-linked SVF Andersen"
                          if stats.get("alias_analysis", {}).get("scope")
                          == "linked-manifest"
                          else "per-translation-unit SVF Andersen")),
                "indirect_calls": "simple static initializer/assignment targets",
                "whole_program_complete": False,
            },
        },
    }


def save_formal_text(formal: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(F.formal_display(formal))
        fh.write("\n")
