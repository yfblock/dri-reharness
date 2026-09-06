"""AST-authoritative call rows, edge eligibility, and loop provenance."""
from __future__ import annotations
import re
from collections import defaultdict

from .. import mmio
from ast_analyzer import Func, function_calls, walk_with_control
from ..dataflow import FuncExtraction
from .ids import _callee_id, _cursor_parents, _func_id, _resolved_callee_id, _return_binding


def _formal_calls(funcs: list[Func],
                  indirect_targets: dict[str, str]
                  ) -> tuple[list[dict], list[dict]]:
    """Build versioned, AST-authoritative source-local call evidence.

    Returns ``(internal_rows, external_rows)``.  Internal rows cover callees
    with a definition in the analyzed set and feed the call-context proofs.
    External rows record every other CallExpr whose callee name is not
    already modeled as an operation (see ``mmio.is_semantically_modeled_call``)
    so that external dependencies become reviewable RIS data instead of
    vanishing at the dataflow dispatch fallthrough.
    """
    by_symbol = {_func_id(func): func for func in funcs}
    rows: list[dict] = []
    external_rows: list[dict] = []
    for caller in funcs:
        parents = _cursor_parents(caller.cursor)
        controls: dict[int, list[dict]] = {}
        for node, stack in walk_with_control(caller.cursor):
            if node.kind.name == "CALL_EXPR":
                controls[node.location.offset] = [dict(frame) for frame in stack]
        order = 0
        for call in function_calls(caller.cursor):
            callee_symbol = _resolved_callee_id(call, indirect_targets)
            callee = by_symbol.get(callee_symbol)
            location = call.cursor.location
            if callee is None:
                row = _external_call_row(
                    caller, call, callee_symbol, location, parents, controls)
                if row is not None:
                    external_rows.append(row)
                continue
            order += 1
            arguments = []
            parameter_cursors = []
            if callee.cursor is not None:
                parameter_cursors = [
                    child for child in callee.cursor.get_children()
                    if child.kind.name == "PARM_DECL"]
            for index, expression in enumerate(call.arg_text):
                parameter = callee.params[index] if index < len(callee.params) \
                    else (None, None)
                parameter_cursor = (
                    parameter_cursors[index]
                    if index < len(parameter_cursors) else None)
                parameter_canonical_type = (
                    parameter_cursor.type.get_canonical().spelling
                    if parameter_cursor is not None and parameter_cursor.type
                    else parameter[1])
                argument_canonical_type = (
                    call.args[index].type.get_canonical().spelling
                    if index < len(call.args) and call.args[index].type
                    else "")
                arguments.append({
                    "index": index,
                    "expression": expression.strip(),
                    "parameter": parameter[0],
                    "parameter_type": parameter[1],
                    "parameter_canonical_type": parameter_canonical_type,
                    "argument_type": (
                        call.args[index].type.get_canonical().spelling),
                    "argument_canonical_type": argument_canonical_type,
                })
            direct_symbol = _callee_id(call)
            rows.append({
                "schema": 1,
                "caller_usr": _func_id(caller),
                "caller_module": caller.module_name or caller.name,
                "callee_usr": callee_symbol,
                "callee_module": callee.module_name or callee.name,
                "callsite": {
                    "source": (location.file.name
                               if location and location.file else None),
                    "line": location.line if location else 0,
                    "column": location.column if location else 0,
                    "offset": location.offset if location else 0,
                    "order": order,
                },
                "argument_mapping": arguments,
                "return_binding": _return_binding(call.cursor, parents),
                "control": controls.get(
                    location.offset if location else 0, []),
                "resolution_authority": (
                    "direct_function_declaration"
                    if direct_symbol == callee_symbol
                    else "static_indirect_target"),
                "multiplicity": {
                    "kind": "syntactic_callsite",
                    "per_caller_invocation": 1,
                    "runtime_count_proven": False,
                },
            })
    rows.sort(key=lambda row: (
        row["caller_module"], row["callsite"]["source"] or "",
        row["callsite"]["offset"], row["callee_module"]))
    external_rows.sort(key=lambda row: (
        row["caller_module"], row["callsite"]["source"] or "",
        row["callsite"]["offset"], row["callee"]))
    return rows, external_rows


def _external_call_row(caller: Func, call, callee_symbol: str, location,
                       parents: dict[int, object],
                       controls: dict[int, list[dict]]) -> dict | None:
    """One AST callsite to a callee without an analyzed definition.

    Direct calls carry clang's resolved declaration provenance; unresolved
    indirect calls keep the callee expression text and are marked
    ``unresolved_indirect`` so porting consumers know the target is unknown
    rather than external-but-declared.  Calls whose callee name is modeled
    as an operation elsewhere (register accessors, delays, ioremap,
    explicitly unsupported register accesses) are skipped to keep each
    callsite accounted exactly once.
    """
    name = call.name or callee_symbol
    if not name or mmio.is_semantically_modeled_call(name):
        return None
    # Compiler intrinsics fold at codegen and are not porting-relevant
    # external API surface (__builtin_expect wraps conditions everywhere).
    if name.startswith("__builtin"):
        return None
    arguments = []
    for index, expression in enumerate(call.arg_text):
        parameter_type = (
            call.callee_param_types[index]
            if index < len(call.callee_param_types) else "")
        parameter = (
            call.callee_param_names[index]
            if index < len(call.callee_param_names) else "")
        argument_type = (
            call.args[index].type.get_canonical().spelling
            if index < len(call.args) and call.args[index].type else "")
        arguments.append({
            "index": index,
            "expression": expression.strip(),
            "parameter": parameter or None,
            "parameter_type": parameter_type,
            "argument_type": argument_type,
        })
    # function_symbol_id returns the bare name for global declarations, so
    # the declaration path is the reliable external provenance and the
    # direct-vs-indirect discriminator: clang resolves a reference to a
    # FUNCTION_DECL precisely when the callsite names a declared function.
    decl_path = call.callee_decl_path or None
    if decl_path is not None:
        callee_usr = f"{decl_path}::{name}"
    else:
        callee_usr = None
    return {
        "schema": 1,
        "caller_usr": _func_id(caller),
        "caller_module": caller.module_name or caller.name,
        "callee": name,
        "callee_usr": callee_usr,
        "callee_decl_path": decl_path,
        "callee_result_type": call.callee_result_type or None,
        "callsite": {
            "source": (location.file.name
                       if location and location.file else None),
            "line": location.line if location else 0,
            "column": location.column if location else 0,
            "offset": location.offset if location else 0,
        },
        "argument_mapping": arguments,
        "return_binding": _return_binding(call.cursor, parents),
        "control": controls.get(location.offset if location else 0, []),
        "resolution_authority": (
            "external_declaration" if decl_path is not None
            else "unresolved_indirect"),
        "multiplicity": {
            "kind": "syntactic_callsite",
            "per_caller_invocation": 1,
            "runtime_count_proven": False,
        },
    }


def _op_site(op) -> tuple[str, str] | None:
    evidence = op.evidence or {}
    owner = evidence.get("symbol")
    site_id = evidence.get("site_id")
    if not isinstance(owner, str) or not owner:
        return None
    if not isinstance(site_id, str) or not site_id:
        return None
    return owner, site_id


def _op_occurrence(op) -> tuple:
    evidence = op.evidence or {}
    path = tuple(
        (item.get("function"), item.get("line"), item.get("callee"),
         item.get("indirect_expression"))
        for item in evidence.get("inlined_at", [])
        if isinstance(item, dict)
    )
    return (
        _op_site(op), path, op.kind, repr(op.addr), op.width, op.value,
        op.condition, tuple(op.cond_stack), repr(op.control_stack), op.var,
    )


def _with_ops(extraction: FuncExtraction, ops: list) -> FuncExtraction:
    return FuncExtraction(
        name=extraction.name,
        params=list(extraction.params),
        return_expr=extraction.return_expr,
        return_read_var=extraction.return_read_var,
        ops=list(ops),
        calls=list(extraction.calls),
        warnings=list(extraction.warnings),
    )


def _eligible_call_edges(calls: list[dict]) -> set[tuple[str, str]]:
    """Return exact, non-recursive edges suitable for frontier propagation."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for call in calls:
        caller = call.get("caller_usr")
        callee = call.get("callee_usr")
        if isinstance(caller, str) and isinstance(callee, str):
            grouped[(caller, callee)].append(call)

    candidates = {
        edge for edge, rows in grouped.items()
        if edge[0] != edge[1] and rows
        and all(_call_row_is_proven(row) for row in rows)
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for caller, callee in candidates:
        adjacency[caller].add(callee)

    def reaches(start: str, target: str) -> bool:
        pending = [start]
        seen = set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            pending.extend(adjacency.get(node, ()))
        return False

    return {
        edge for edge in candidates
        if not reaches(edge[1], edge[0])
    }


def _type_is_scalar(type_name: str) -> bool:
    """Recognize C scalar types for which the call conversion is defined."""
    normalized = " ".join(type_name.replace("*", " ").split())
    return bool(re.fullmatch(
        r"(?:(?:const|volatile|restrict|signed|unsigned|short|long|long long|\s)*)"
        r"(?:void|_Bool|char|short|int|long|long long|float|double|long double|"
        r"u(?:8|16|32|64)|s(?:8|16|32|64)|__u(?:8|16|32|64)|"
        r"__le(?:16|32|64)|__be(?:16|32|64)|size_t)",
        normalized))


def _types_compatible(parameter_type: str, argument_type: str) -> bool:
    """Return whether Clang's argument-to-parameter conversion is provable.

    Canonical Clang types are equal for the common case.  C also defines the
    conversion between arithmetic scalar types and between ``void *`` and an
    object pointer; accepting only those standard conversions keeps argument
    substitution precise without pretending that unrelated pointer types or
    opaque aggregates are interchangeable.
    """
    parameter = " ".join(parameter_type.split())
    argument = " ".join(argument_type.split())
    if parameter == argument:
        return True
    parameter_pointer = "*" in parameter
    argument_pointer = "*" in argument
    if parameter_pointer and argument_pointer:
        parameter_base = parameter.replace("*", " ").split()
        argument_base = argument.replace("*", " ").split()
        return "void" in parameter_base or "void" in argument_base
    return (not parameter_pointer and not argument_pointer
            and _type_is_scalar(parameter)
            and _type_is_scalar(argument))


_LOOP_INIT_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*=\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*$")
_LOOP_GUARD_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(<|<=)\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*$")
_LOOP_STEP_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(\+\+|\+=\s*1)\s*$")


def _literal_int(text: str) -> int | None:
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        return None


def _loop_executes_exactly_once(frame: dict) -> bool:
    """Prove the narrow static loop shape that has one invocation."""
    if frame.get("kind") != "loop" or frame.get("loop_kind") != "for":
        return False
    init = _LOOP_INIT_RE.fullmatch(frame.get("init", ""))
    guard = _LOOP_GUARD_RE.fullmatch(frame.get("guard", ""))
    step = _LOOP_STEP_RE.fullmatch(frame.get("step", ""))
    if not init or not guard or not step:
        return False
    variable, start_text = init.groups()
    guard_variable, relation, bound_text = guard.groups()
    step_variable, _step = step.groups()
    if variable != guard_variable or variable != step_variable:
        return False
    start = _literal_int(start_text)
    bound = _literal_int(bound_text)
    if start is None or bound is None:
        return False
    count = bound - start + (1 if relation == "<=" else 0)
    return count == 1


def _call_row_is_proven(call: dict, *, allow_structured_loops: bool = False) -> bool:
    """Check one AST call row before it participates in a proof.

    Frontier propagation needs a runtime-exact call count, so it keeps the
    default strict loop rule.  Call-context ownership is a separate proof:
    an operation inside a preserved structured loop has one static callsite
    even when its runtime iteration count is data-dependent.
    """
    if call.get("resolution_authority") not in {
            "direct_function_declaration", "static_indirect_target"}:
        return False
    if (call.get("return_binding") or {}).get("status") != "exact":
        return False
    multiplicity = call.get("multiplicity") or {}
    if (multiplicity.get("kind") != "syntactic_callsite"
            or multiplicity.get("per_caller_invocation") != 1):
        return False
    if any((frame or {}).get("kind") == "loop"
           and not allow_structured_loops
           and not _loop_executes_exactly_once(frame)
           for frame in call.get("control") or []):
        return False
    arguments = call.get("argument_mapping")
    if not isinstance(arguments, list):
        return False
    for argument in arguments:
        if not isinstance(argument, dict):
            return False
        if not all(isinstance(argument.get(key), str)
                   and bool(argument.get(key))
                   for key in ("parameter", "parameter_type", "argument_type")):
            return False
        parameter_type = (argument.get("parameter_canonical_type")
                          or argument["parameter_type"])
        argument_type = (argument.get("argument_canonical_type")
                         or argument["argument_type"])
        if not _types_compatible(parameter_type, argument_type):
            return False
    return True
