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


def _transaction_fields(op: Op, op_id: str, expressions: list[dict]) -> dict:
    contract = op.transaction
    unknown_value = any(_expr_has_top(expr) for expr in expressions)
    width_known = contract.get("element_width") in {1, 2, 4, 8}
    path_precision = "syntactic" if op.cond_stack else "unconditional"
    reliability = ("Unknown" if unknown_value
                   else "Conservative" if not width_known or op.cond_stack
                   else "Exact")
    return {
        "op_id": op_id,
        "evidence": dict(op.evidence),
        "reliability": reliability,
        "path_precision": path_precision,
        "access_domain": contract.get("transport", "unknown_transaction"),
        "transport": contract.get("transport", "unknown"),
    }


def _transaction_endpoint(contract: dict) -> dict:
    return {
        "target": F.parse_expr(contract.get("target")),
        "selector": (F.parse_expr(contract.get("selector"))
                     if contract.get("selector") is not None else None),
    }


def _transaction_payload(contract: dict, *, read: bool = False) -> dict:
    width = F.width_of(contract.get("element_width", 0)) \
        if contract.get("element_width") in {1, 2, 4, 8} else "Unknown"
    if contract.get("payload_kind") == "buffer":
        body = {
            "element_width": width,
            "buffer": F.parse_expr(contract.get("buffer")),
            "count": F.parse_expr(contract.get("count", "1")),
            "count_unit": contract.get("count_unit", "elements"),
        }
        if contract.get("protocol"):
            body["protocol"] = contract["protocol"]
        return {"Buffer": body}
    body = {"width": width}
    if read:
        body["var"] = contract.get("result") or "transaction_result"
    else:
        body["value"] = F.parse_expr(contract.get("value"))
    if contract.get("byte_order"):
        body["byte_order"] = contract["byte_order"]
    return {"Scalar": body}


def _parse_expr_c(text, constants=None):
    return F.parse_expr(text, constants)


def _to_risop(op: Op, id_counter: list[int],
              constants: dict[str, int] | None = None) -> dict:
    addr = F.formal_addr(op.addr, op.reg_name)
    width = F.width_of(op.width)
    op_id = f"op_{id_counter[0]}"
    if op.kind == "Read":
        var = op.var or f"r{id_counter[0]}"
        body = {"addr": addr, "width": width, "var": var, "intent": op.intent}
        body.update(_common_fields(op, op_id, addr))
        return {"Read": body}
    if op.kind == "Write":
        value = _parse_expr_c(op.value, constants)
        body = {"addr": addr, "width": width,
                "value": value, "intent": op.intent}
        body.update(_common_fields(op, op_id, addr, value))
        return {"Write": body}
    if op.kind == "ReadModifyWrite":
        transform = _parse_expr_c(op.value, constants)
        body = {"addr": addr, "width": width,
                "transform": transform, "read_var": op.var,
                "intent": op.intent}
        body.update(_common_fields(op, op_id, addr, transform))
        return {"ReadModifyWrite": body}
    if op.kind == "TransactionRead":
        endpoint = _transaction_endpoint(op.transaction)
        payload = _transaction_payload(op.transaction, read=True)
        body = {**endpoint, "payload": payload}
        if op.transaction.get("protocol"):
            body["protocol"] = op.transaction["protocol"]
        if op.transaction.get("result"):
            body["result"] = op.transaction["result"]
            body["result_convention"] = op.transaction.get(
                "result_convention", "return_value")
        expressions = [endpoint["target"], endpoint.get("selector")]
        if "Buffer" in payload:
            expressions.extend([payload["Buffer"]["buffer"],
                                payload["Buffer"]["count"]])
        body.update(_transaction_fields(
            op, op_id, [expr for expr in expressions if expr is not None]))
        return {"TransactionRead": body}
    if op.kind == "TransactionWrite":
        endpoint = _transaction_endpoint(op.transaction)
        payload = _transaction_payload(op.transaction)
        body = {**endpoint, "payload": payload}
        if op.transaction.get("protocol"):
            body["protocol"] = op.transaction["protocol"]
        if op.transaction.get("result"):
            body["result"] = op.transaction["result"]
            body["result_convention"] = op.transaction.get(
                "result_convention", "return_value")
        expressions = [endpoint["target"], endpoint.get("selector")]
        if "Scalar" in payload:
            expressions.append(payload["Scalar"]["value"])
        else:
            expressions.extend([payload["Buffer"]["buffer"],
                                payload["Buffer"]["count"]])
        body.update(_transaction_fields(
            op, op_id, [expr for expr in expressions if expr is not None]))
        return {"TransactionWrite": body}
    if op.kind == "TransactionUpdate":
        endpoint = _transaction_endpoint(op.transaction)
        mask = _parse_expr_c(op.transaction.get("update_mask", constants))
        value = _parse_expr_c(op.transaction.get("update_value", constants))
        width = (F.width_of(op.transaction.get("element_width", 0))
                 if op.transaction.get("element_width") in {1, 2, 4, 8}
                 else "Unknown")
        body = {**endpoint, "width": width, "mask": mask, "value": value,
                "semantics": op.transaction.get(
                    "update_semantics", "masked_replace")}
        if op.transaction.get("helper_contract"):
            body["helper_contract"] = op.transaction["helper_contract"]
        if (op.transaction.get("transport") == "mfd"
                and (op.evidence or {}).get("callee")):
            body["helper_symbol"] = op.evidence["callee"]
        if op.transaction.get("changed_result"):
            body["changed_result"] = op.transaction["changed_result"]
        body.update(_transaction_fields(
            op, op_id, [endpoint["target"], mask, value]
            + ([endpoint["selector"]] if endpoint["selector"] else [])))
        return {"TransactionUpdate": body}
    if op.kind == "StateRead":
        body = {"field": op.state_field, "var": op.var or f"s{id_counter[0]}",
                "width": width}
        body.update(_semantic_fields(op, op_id))
        return {"StateRead": body}
    if op.kind == "StateWrite":
        value = _parse_expr_c(op.value, constants)
        body = {"field": op.state_field, "value": value, "width": width}
        body.update(_semantic_fields(op, op_id, value))
        return {"StateWrite": body}
    if op.kind == "OutputWrite":
        value = _parse_expr_c(op.value, constants)
        body = {"target": op.var, "value": value}
        body.update(_semantic_fields(op, op_id, value))
        return {"OutputWrite": body}
    if op.kind == "ValueBind":
        value = _parse_expr_c(op.value, constants)
        body = {"var": op.var, "value": value}
        body.update(_semantic_fields(op, op_id, value))
        return {"ValueBind": body}
    if op.kind == "Return":
        value = _parse_expr_c(op.value, constants)
        body = {"value": value}
        body.update(_semantic_fields(op, op_id, value))
        return {"Return": body}
    if op.kind == "Delay":
        ns = getattr(op, "_delay_ns", 0)
        return {"Delay": {"cycles": _parse_expr_c(str(ns))}}
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
    elif re.fullmatch(
            rf"(?:[A-Za-z_]\w*\+\+|\+\+[A-Za-z_]\w*)"
            rf"(?:\s*,\s*(?:[A-Za-z_]\w*\+\+|\+\+[A-Za-z_]\w*))*", step) \
            and re.search(rf"(?:^|\s|,)\s*{re.escape(var)}\+\+", f" {step}"):
        # induction var increments by 1; companions are independent pointer
        # cursors that do not affect the bound
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
    # Constant bounds prove without unrolling (the RIS Loop node carries the
    # count; backends decide execution strategy), so allow large constants —
    # the sanity cap only guards against malformed/huge literals.
    if count > 10_000_000:
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
    """Prove a monotonic loop whose finite upper bound is runtime state."""
    if frame.get("loop_kind") != "for":
        return None
    init = (frame.get("init") or "").strip().rstrip(";")
    guard = (frame.get("guard") or "").strip()
    step = (frame.get("step") or "").strip().rstrip(";")
    init_match = re.fullmatch(
        r"(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*(0|1)", init)
    if not init_match:
        return None
    var, start_text = init_match.groups()
    start = int(start_text)
    guard_match = re.fullmatch(
        rf"{re.escape(var)}\s*<\s*"
        r"([A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*)", guard)
    step_ok = re.fullmatch(
        rf"(?:{re.escape(var)}\+\+|\+\+{re.escape(var)})", step) or (
        re.fullmatch(
            rf"(?:[A-Za-z_]\w*\+\+|\+\+[A-Za-z_]\w*)"
            rf"(?:\s*,\s*(?:[A-Za-z_]\w*\+\+|\+\+[A-Za-z_]\w*))*", step)
        and re.search(rf"(?:^|\s|,)\s*{re.escape(var)}\+\+", f" {step}"))
    if not guard_match or not step_ok:
        return None
    bound_text = guard_match.group(1)
    bound_root = re.match(r"[A-Za-z_]\w*", bound_text).group(0)
    declaration_kind = (frame.get("guard_declarations") or {}).get(bound_root)
    bound_field = re.search(r"(?:->|\.)\s*([A-Za-z_]\w*)$", bound_text)
    modeled_bound_fields = {
        "nr_ports", "max_ports", "num_channels", "num_eps", "fifo_count",
        "word_count", "dword_count", "desc_count", "fifo_size",
    }
    def integer_scalar(type_name: str) -> bool:
        normalized = re.sub(r"\s+", " ", type_name or "").strip()
        if (not normalized or "*" in normalized
                or re.search(r"\b(?:float|double|long double)\b", normalized)
                or re.search(r"\b(?:struct|union)\b", normalized)):
            return False
        return bool(re.search(
            r"\b(?:_Bool|bool|char|short|int|long|signed|unsigned|"
            r"size_t|u?int(?:8|16|32|64)?_t|__u(?:8|16|32|64)|"
            r"__s(?:8|16|32|64))\b", normalized))

    guard_types = frame.get("guard_types") or {}
    if declaration_kind == "PARM_DECL":
        pass
    elif declaration_kind == "VAR_DECL":
        field_name = bound_field.group(1) if bound_field else None
        if (field_name not in modeled_bound_fields
                and not integer_scalar(guard_types.get(bound_root, ""))):
            return None
    else:
        return None
    bound = F.parse_expr(bound_text)
    if "Top" in bound:
        return None
    count = bound if start == 0 else {
        "Ite": {
            "guard": {
                "BinOp": {
                    "op": "Lt", "left": {"Const": start},
                    "right": copy.deepcopy(bound),
                },
            },
            "then": {
                "BinOp": {
                    "op": "Sub", "left": copy.deepcopy(bound),
                    "right": {"Const": start},
                },
            },
            "else": {"Const": 0},
        },
    }
    return {
        "count": count,
        "bound_expr": bound,
        "relation": "<",
        "reliability": "Exact",
        "bounded": True,
        "dynamic_bound": True,
        "induction_var": var,
        "start": start,
        "stride": 1,
        "proof": "affine monotonic loop bounded by runtime scalar/state",
    }


def _runtime_post_decrement_loop(frame: dict) -> dict | None:
    """Prove ``while (v--)`` / ``while (g && (v-- >= 0))`` loops.

    The induction variable is consumed by the guard itself, so the trip
    count equals the variable's initial runtime value (plus the final
    failing test): a finite dynamic bound.
    """
    if frame.get("loop_kind") not in ("while", "do"):
        return None
    guard = (frame.get("guard") or "").strip()
    comparison = False
    # strip an optional leading pure-predicate conjunct: g && v--  /  g && (v-- >= 0)
    core = guard
    if "&&" in core:
        head, _, tail = core.rpartition("&&")
        core = tail.strip()
        if core.endswith(")") and not core.startswith("("):
            core = core[:-1].strip()
        comparison = True
    m = re.fullmatch(r"([A-Za-z_]\w*)--", core)
    if m is None:
        m = re.fullmatch(
            r"\(?\s*([A-Za-z_]\w*)--\s*(?:>=|>|<=|<|==|!=)\s*[^)]*\)?", core)
        comparison = True
    if m is None:
        return None
    var = m.group(1)
    declarations = frame.get("guard_declarations") or {}
    declared = declarations.get(var)
    if declared not in (None, "PARM_DECL", "VAR_DECL"):
        return None
    guard_types = frame.get("guard_types") or {}
    type_name = guard_types.get(var, "")
    if re.search(r"\b(?:float|double)\b", type_name or ""):
        return None
    return {
        "count": {"Var": var},
        "bound_expr": {"Var": var},
        "relation": "post-decrement",
        "reliability": "Exact",
        "bounded": True,
        "dynamic_bound": True,
        "induction_var": var,
        "start": 0,
        "stride": 1,
        "proof": ("guarded post-decrement while-loop"
                  if comparison else "post-decrement while-loop"),
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


def _nest(ops: list[Op], depth: int, id_counter: list[int], macros,
          _memo: dict | None = None) -> list[dict]:
    """Build nested Cond/Loop nodes from structured lexical control frames."""
    result = []
    i = 0
    n = len(ops)
    # Identical guard text resolves its macros once per MODULE (shared
    # across recursion levels): the macro table may be consulted for
    # enum/register constants.
    if _memo is None:
        _memo = {"guards": {}, "constants": None}
    _guard_cache: dict[str, dict] = _memo["guards"]
    _constants_cache: dict[str, int] | None = None

    def _set_constants(value):
        _memo["constants"] = value

    def _constants() -> dict[str, int]:
        if _memo["constants"] is None:
            table: dict[str, int] = {}
            resolve = getattr(macros, "resolve", None)
            if callable(resolve):
                for name in getattr(macros, "names", lambda: [])():
                    value = resolve(name)
                    if isinstance(value, int):
                        table[name] = value
            _memo["constants"] = table
        return _memo["constants"]

    def _parse_guard(text: str | None) -> dict:
        if text not in _guard_cache:
            _guard_cache[text] = F.parse_expr(text, _constants())
        return _guard_cache[text]
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
            body = _nest(run, depth + 1, id_counter, macros, _memo)
            if frame.get("kind") == "loop":
                # Delay macros (mdelay/udelay/ndelay via statement-expression
                # expansion) surface as an opaque loop whose guard text is
                # the macro call itself: fold to a single Delay op instead
                # of an unprovable Conservative loop.
                delay_m = re.fullmatch(
                    r"\s*(m|u|n)delay\s*\(\s*(\d+|0x[0-9a-fA-F]+)\s*\)\s*;?\s*",
                    (frame.get("guard") or "")
                    + ";" + (frame.get("source") or "").strip().rstrip(";"))
                delay_guard = re.fullmatch(
                    r"\s*(m|u|n)delay\s*\(\s*(\d+|0x[0-9a-fA-F]+)\s*\)\s*",
                    frame.get("guard") or "")
                dm = delay_guard or delay_m
                if dm is not None:
                    unit, amount = dm.group(1), int(dm.group(2), 0)
                    ns = {"m": amount * 1_000_000,
                          "u": amount * 1_000,
                          "n": amount}[unit]
                    id_counter[0] += 1
                    result.append({"Delay": {
                        "cycles": {"Const": ns},
                        "op_id": f"op_{id_counter[0]}",
                        "evidence": {"origin": "delay_macro_expansion",
                                     "macro": f"{dm.group(1)}delay"}}})
                    continue
                loop = {
                    "count": {"Top": None},
                    "guard": _parse_guard(frame.get("guard")),
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
                    proof = _runtime_post_decrement_loop(frame)
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
                    "guard": _parse_guard(frame.get("guard")),
                    "control": dict(frame),
                    "then_ops": body, "else_ops": None}})
        else:
            id_counter[0] += 1
            result.append(_to_risop(op, id_counter, _constants()))
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


def _register_leaf(op: dict) -> tuple[str, dict] | tuple[None, None]:
    kind = next((name for name in (
                 "Read", "Write", "ReadModifyWrite", "TransactionRead",
                 "TransactionWrite", "TransactionUpdate") if name in op), None)
    return (kind, op[kind]) if kind is not None else (None, None)


def _formal_occurrence_identity(op: dict) -> tuple | None:
    """Return a fail-closed identity for one already-formalized register op."""
    kind, body = _register_leaf(op)
    if kind is None:
        return None
    evidence = body.get("evidence") or {}
    symbol = evidence.get("symbol")
    site_id = evidence.get("site_id")
    if not isinstance(symbol, str) or not isinstance(site_id, str):
        return None
    path = tuple(
        (item.get("function"), item.get("line"), item.get("callee"),
         item.get("indirect_expression"))
        for item in evidence.get("inlined_at", [])
        if isinstance(item, dict)
    )
    return kind, symbol, site_id, path


def _formalize_call_closure_overlays(
        funcs: list[Func], modules: list[dict], overlays: dict,
        closure: dict, macros) -> tuple[dict[str, list[dict]], dict]:
    """Build callback views while retaining canonical module/op identity.

    Selective closure is only enabled for a callback when every register leaf
    in its alternate view maps to exactly one canonical operation.  Original
    callback leaves use their complete formal occurrence identity; propagated
    leaves use their definition-owned ``(symbol, site_id)`` source identity.
    """
    if not isinstance(overlays, dict) or not overlays:
        disabled = copy.deepcopy(closure)
        disabled.update({
            "accepted_symbols": [], "accepted_modules": [],
            "accepted_sites": 0, "callback_modules": [],
            "routes": [], "overlays": {}, "overlay_register_ops": 0,
        })
        return {}, disabled

    func_by_symbol = {func.symbol_id or func.name: func for func in funcs}
    closure_module_by_symbol = {
        route.get("symbol"): route.get("module")
        for route in closure.get("routes") or []
        if isinstance(route, dict)
        and isinstance(route.get("symbol"), str)
        and isinstance(route.get("module"), str)
    }
    occurrence_index: dict[tuple[str, tuple], list[str]] = {}
    site_index: dict[tuple[str, str, str], list[str]] = {}
    canonical_by_id: dict[str, dict] = {}
    for module in modules:
        module_name = module.get("name")
        for op in walk_leaf_ops(module.get("ops", [])):
            kind, body = _register_leaf(op)
            if kind is None:
                continue
            op_id = body.get("op_id")
            if isinstance(op_id, str) and op_id:
                canonical_by_id[op_id] = op
            identity = _formal_occurrence_identity(op)
            if isinstance(module_name, str) and identity is not None:
                occurrence_index.setdefault(
                    (module_name, identity), []).append(op_id)
            evidence = body.get("evidence") or {}
            symbol = evidence.get("symbol")
            site_id = evidence.get("site_id")
            if (isinstance(symbol, str) and symbol
                    and isinstance(site_id, str) and site_id):
                site_index.setdefault(
                    (module_name, symbol, site_id), []).append(op_id)

    successful: dict[str, list[dict]] = {}
    successful_callbacks: set[str] = set()
    accepted_site_keys: set[tuple[str, str]] = set()
    overlay_register_ops = 0
    for callback_symbol, extraction in overlays.items():
        func = func_by_symbol.get(callback_symbol)
        if func is None or not isinstance(extraction, FuncExtraction):
            continue
        callback_module = func.module_name or func.name
        alternate = _module(func, extraction, [0], macros)
        used_ids: set[str] = set()
        used_callback_ids: set[str] = set()
        occurrence_positions: dict[tuple, int] = {}
        callback_site_keys: set[tuple[str, str]] = set()
        mapped = 0
        valid = True
        for op in walk_leaf_ops(alternate.get("ops", [])):
            kind, body = _register_leaf(op)
            if kind is None:
                continue
            evidence = body.get("evidence") or {}
            call_closure = evidence.get("call_closure") or {}
            if call_closure.get("oracle") == "selective-call-frontier-v1":
                source_symbol = call_closure.get("source_symbol")
                site_id = evidence.get("site_id")
                source_module = closure_module_by_symbol.get(source_symbol)
                candidates = site_index.get(
                    (source_module, source_symbol, site_id), [])
                site_key = (source_symbol, site_id)
            else:
                identity = _formal_occurrence_identity(op)
                candidates = occurrence_index.get(
                    (callback_module, identity), [])
                site_key = None
            candidates = [op_id for op_id in candidates
                          if isinstance(op_id, str) and op_id]
            if site_key is not None:
                selected = candidates[0] if len(candidates) == 1 else None
            else:
                occurrence_key = (callback_module, identity)
                position = occurrence_positions.get(occurrence_key, 0)
                selected = (candidates[position]
                            if position < len(candidates) else None)
                occurrence_positions[occurrence_key] = position + 1
            if selected is None or selected in used_ids:
                valid = False
                break
            body["op_id"] = selected
            used_ids.add(selected)
            if site_key is None:
                used_callback_ids.add(selected)
                # The deeper propagation pass is used only to position new
                # closure leaves.  Preserve every pre-existing callback leaf
                # byte-for-byte from canonical Formal so no incidental
                # re-extraction refinement changes its semantic contract.
                op.clear()
                op.update(copy.deepcopy(canonical_by_id[selected]))
            mapped += 1
            if site_key is not None:
                callback_site_keys.add(site_key)
        expected_callback_ids = {
            op_id for (module_name, _identity), op_ids
            in occurrence_index.items() if module_name == callback_module
            for op_id in op_ids if isinstance(op_id, str) and op_id
        }
        if not valid or used_callback_ids != expected_callback_ids:
            continue
        successful[callback_module] = alternate["ops"]
        successful_callbacks.add(callback_module)
        accepted_site_keys.update(callback_site_keys)
        overlay_register_ops += mapped

    requested_routes = closure.get("routes") or []
    routes = [copy.deepcopy(route) for route in requested_routes
              if isinstance(route, dict)
              and route.get("callback_module") in successful_callbacks]
    accepted_symbols = sorted({route.get("symbol") for route in routes
                               if isinstance(route.get("symbol"), str)})
    accepted_modules = sorted({route.get("module") for route in routes
                               if isinstance(route.get("module"), str)})
    rejected = set(closure.get("rejected_symbols") or [])
    rejected.update(
        route.get("symbol") for route in requested_routes
        if isinstance(route, dict)
        and route.get("callback_module") not in successful_callbacks
        and isinstance(route.get("symbol"), str))
    finalized = copy.deepcopy(closure)
    finalized.update({
        "accepted_symbols": accepted_symbols,
        "accepted_modules": accepted_modules,
        "accepted_sites": len(accepted_site_keys),
        "callback_modules": sorted(successful_callbacks),
        "routes": routes,
        "overlays": successful,
        "overlay_register_ops": overlay_register_ops,
        "rejected_symbols": sorted(rejected),
    })
    return successful, finalized


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


def _transaction_map(funcs, extractions, macros) -> list[dict]:
    """Selectors used by non-MMIO transactions, kept outside register_map."""
    seen: dict[tuple[str, str], dict] = {}
    for func in funcs:
        extraction = extractions.get(func.symbol_id or func.name)
        if not extraction:
            continue
        for op in extraction.ops:
            contract = op.transaction
            selector = contract.get("selector") if contract else None
            if not isinstance(selector, str):
                continue
            selector = selector.strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", selector):
                continue
            value = macros.offset(selector)
            if value is None:
                continue
            transport = contract.get("transport", "unknown")
            key = (transport, selector)
            seen[key] = {
                "transport": transport,
                "name": selector,
                "value": int(value),
                "element_width": (
                    F.width_of(contract["element_width"])
                    if contract.get("element_width") in {1, 2, 4, 8}
                    else "Unknown"),
            }
    return [seen[key] for key in sorted(seen)]


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

    def has_hardware_semantics(ops) -> bool:
        """Keep modules that contain executable hardware/transaction effects."""
        return any(op.kind in {
            "Read", "Write", "ReadModifyWrite",
            "TransactionRead", "TransactionWrite", "TransactionUpdate",
            # subsystem summaries rewrite every hardware call into
            # StateRead/StateWrite — those modules are the whole semantic
            # content of subsystem-only drivers and must stay executable
            "StateRead", "StateWrite",
        } for op in ops)

    for f in funcs:
        symbol = f.symbol_id or f.name
        if symbol in inlined_names:
            continue   # inlined into a caller — avoid duplicate module
        ex = extractions.get(symbol)
        if not ex or not ex.ops or not has_hardware_semantics(ex.ops):
            continue
        modules.append(_module(f, ex, id_counter, macros))

    closure_overlays, selective_closure = _formalize_call_closure_overlays(
        funcs, modules, stats.get("_call_closure_overlays", {}),
        stats.get("selective_call_closure", {
            "schema": 1,
            "oracle": "selective-call-frontier-v1",
            "accepted_symbols": [],
            "accepted_sites": 0,
            "rounds": [],
        }), macros)
    module_names = {module.get("name") for module in modules}
    funcs_by_symbol = {func.symbol_id or func.name: func for func in funcs}
    for route in selective_closure.get("routes", []):
        callback_module = route.get("callback_module")
        callback_symbol = route.get("callback_symbol")
        func = funcs_by_symbol.get(callback_symbol)
        if (func is None or callback_module in module_names
                or callback_module not in closure_overlays):
            continue
        # Preserve a zero-op canonical definition anchor for callbacks whose
        # only register semantics arrive through the alternate closure view.
        modules.append(_module(
            func, FuncExtraction(name=func.name), id_counter, macros))
        module_names.add(callback_module)

    return {
        "driver": driver_name,
        "version": "0.1.0",
        "modules": modules,
        "register_map": _register_map(funcs, extractions, macros),
        "transaction_map": _transaction_map(funcs, extractions, macros),
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
            "callee_rescue": stats.get("callee_rescue", {
                "candidates": 0, "rescued": 0,
                "rescue_mode": "direct-evidence-frontier",
                "call_semantics_proven": False,
                "rescued_symbols": [],
            }),
            "call_graph": {
                "schema": 1,
                "oracle": "source-ast-call-v1",
                "claim": "source-local call identity and callsite dataflow",
                "calls": stats.get("formal_calls", []),
                "lowering_enabled": bool(closure_overlays),
                "selective_closure": selective_closure,
            },
            "subsystem_summary_analysis": {
                "synthetic_functions": stats.get(
                    "synthetic_subsystem_functions", 0),
                "summaries": stats.get("subsystem_summaries", []),
            },
            "function_macros": stats.get("function_macros", {}),
            "assurance_scope": {
                "claim": "recognized hardware-access and structured-control universe",
                "register_accesses": (
                    "typed MMIO, regmap, I2C and public MFD helper transactions "
                    "plus direct volatile and inline-asm detection"),
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
                "call_semantics_proven": (
                    stats.get("callee_rescue", {}).get(
                        "call_semantics_proven") is True),
                "callee_rescue_semantics_complete": (
                    stats.get("callee_rescue", {}).get(
                        "call_semantics_proven") is True),
                "whole_program_complete": False,
            },
        },
    }


def save_formal_text(formal: dict, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(F.formal_display(formal))
        fh.write("\n")
