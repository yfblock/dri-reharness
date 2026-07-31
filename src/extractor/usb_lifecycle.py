"""Source-derived USB HCD lifecycle evidence.

This module deliberately proves only the small object-flow fact needed by the
Linux backend: one source-local ``hc_driver`` table is passed to one
``usb_create_hcd`` result, that result reaches ``usb_add_hcd``, and a
source-local remove path performs ``usb_remove_hcd`` followed by
``usb_put_hcd``.  It does not infer kernel callback invocation or erase
dual-role/mode conditions; those remain explicit metadata boundaries.
"""
from __future__ import annotations

from collections import defaultdict, deque
import re

from .ast_model import Func, function_calls, source_text, walk_with_control
from .call_graph import _cursor_parents, _func_id, _return_binding


_CREATE = {"usb_create_hcd", "usb_create_shared_hcd"}
_LIFECYCLE_CALLS = _CREATE | {
    "usb_add_hcd", "usb_remove_hcd", "usb_put_hcd",
}
_LIFECYCLE_CALL_RE = re.compile(
    r"\b(?:" + "|".join(sorted(map(re.escape, _LIFECYCLE_CALLS))) +
    r")\s*\(")


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _call_row(func: Func, call, parents: dict) -> dict:
    location = call.cursor.location
    controls = []
    for node, stack in walk_with_control(func.cursor):
        if (node.kind.name == "CALL_EXPR"
                and node.location.offset == location.offset):
            controls = [dict(frame) for frame in stack]
            break
    return {
        "callee": call.name,
        "function": func.name,
        "function_usr": _func_id(func),
        "location": {
            "source": (location.file.name
                        if location and location.file else None),
            "line": location.line if location else 0,
            "column": location.column if location else 0,
            "offset": location.offset if location else 0,
        },
        "arguments": [source_text(call.cursor.translation_unit, arg).strip()
                      for arg in call.args],
        "argument_types": [
            arg.type.get_canonical().spelling if arg.type else ""
            for arg in call.args
        ],
        "control": controls,
        "return_binding": _return_binding(call.cursor, parents),
        "callee_in_source": bool(call.cursor.referenced and
                                  call.cursor.referenced.location.file and
                                  call.cursor.referenced.location.file.name ==
                                  func.source_path),
        "call": call,
    }


def _is_loop(row: dict) -> bool:
    return any((frame or {}).get("kind") == "loop"
               for frame in row.get("control") or [])


def _lifecycle_rows(funcs: list[Func]) -> list[dict]:
    """Collect AST evidence only from functions containing USB calls.

    USB lifecycle inference is attached to every extraction, including
    ordinary GPIO/clock drivers.  Avoid walking every function's control tree
    twice in those common cases; the fast name filter also keeps this oracle
    linear in the number of call sites rather than in all AST nodes.
    """
    source_paths = sorted({func.source_path for func in funcs
                           if func.cursor is not None and func.source_path})
    mentions_lifecycle = False
    for path in source_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        if _LIFECYCLE_CALL_RE.search(text):
            mentions_lifecycle = True
            break
    if not mentions_lifecycle:
        return []

    rows: list[dict] = []
    for func in funcs:
        if func.cursor is None:
            continue
        calls = function_calls(func.cursor)
        interesting = [call for call in calls
                       if call.name in _LIFECYCLE_CALLS]
        if not interesting:
            continue
        parents = _cursor_parents(func.cursor)
        rows.extend(_call_row(func, call, parents) for call in interesting)
    return rows


def _static_hc_driver(arg, source_path: str) -> dict | None:
    for node in arg.walk_preorder():
        ref = getattr(node, "referenced", None)
        if ref is None or ref.kind.name != "VAR_DECL":
            continue
        type_name = ref.type.get_canonical().spelling if ref.type else ""
        if "hc_driver" not in type_name:
            continue
        loc = ref.location
        if (loc is None or loc.file is None
                or loc.file.name != source_path):
            continue
        parent = ref.semantic_parent
        if parent is None or parent.kind.name != "TRANSLATION_UNIT":
            continue
        return {
            "name": ref.spelling,
            "usr": ref.get_usr() or None,
            "type": type_name,
            "source": loc.file.name,
            "line": loc.line,
            "offset": loc.offset,
        }
    return None


def _path_index(formal_calls: list[dict]) -> dict[str, list[dict]]:
    adjacency: dict[str, list[dict]] = defaultdict(list)
    for row in formal_calls or []:
        caller = row.get("caller_usr")
        callee = row.get("callee_usr")
        if isinstance(caller, str) and isinstance(callee, str):
            adjacency[caller].append(row)
    return adjacency


def _unique_call_path(adjacency: dict[str, list[dict]], roots: set[str],
                      target: str) -> tuple[list[dict] | None, str | None]:
    reverse: dict[str, set[str]] = defaultdict(set)
    for caller, edges in adjacency.items():
        for row in edges:
            callee = row.get("callee_usr")
            if isinstance(callee, str):
                reverse[callee].add(caller)
    reaches_target = {target}
    pending = deque([target])
    while pending:
        callee = pending.popleft()
        for caller in reverse.get(callee, set()):
            if caller not in reaches_target:
                reaches_target.add(caller)
                pending.append(caller)

    paths: list[list[dict]] = []
    queue = deque((root, [], frozenset({root}))
                  for root in sorted(roots) if root in reaches_target)
    explored = 0
    while queue and len(paths) < 3:
        caller, path, visited = queue.popleft()
        explored += 1
        if explored > 4096:
            return None, "callback-to-lifecycle path search exceeded bound"
        if caller == target:
            paths.append(path)
            continue
        for row in adjacency.get(caller, []):
            callee = row.get("callee_usr")
            if (not isinstance(callee, str) or callee not in reaches_target
                    or callee in visited):
                continue
            queue.append((callee, [*path, row], visited | {callee}))
    if not paths:
        return None, "no unique callback-to-lifecycle call path"
    if len(paths) != 1:
        return None, "ambiguous callback-to-lifecycle call path"
    path = paths[0]
    if any(any((frame or {}).get("kind") == "loop"
               for frame in row.get("control") or []) for row in path):
        return None, "lifecycle call path is loop-dependent"
    return path, None


def infer_usb_hcd_lifecycle(
        funcs: list[Func], device_spec, formal: dict) -> dict:
    """Infer a conservative single-instance HCD lifecycle capability."""
    empty = {
        "schema": 1,
        "oracle": "source-ast-usb-hcd-lifecycle-v1",
        "status": "unproven",
        "mode": "none",
        "tables": [],
        "reasons": [],
    }
    callback_functions = getattr(device_spec, "functions", []) or []
    symbol_by_module = {
        (func.module_name or func.name): _func_id(func) for func in funcs
    }
    roots = {
        symbol_by_module.get(function.ris_ref, function.ris_ref)
        for function in callback_functions
        if function.role == "probe" and function.ris_ref
    }
    remove_roots = {
        symbol_by_module.get(function.ris_ref, function.ris_ref)
        for function in callback_functions
        if function.role == "remove" and function.ris_ref
    }
    formal_calls = (formal.get("metadata") or {}).get(
        "call_graph", {}).get("calls", [])
    adjacency = _path_index(formal_calls)
    rows: list[dict] = []
    lifecycle_rows = _lifecycle_rows(funcs)
    if not lifecycle_rows:
        empty["reasons"].append("no USB HCD lifecycle calls in source AST")
        return empty
    by_function: dict[str, list[dict]] = defaultdict(list)
    func_by_id = {
        _func_id(func): func for func in funcs if func.cursor is not None
    }
    for row in lifecycle_rows:
        by_function[row["function_usr"]].append(row)
    for function_rows in by_function.values():
        func = func_by_id.get(function_rows[0]["function_usr"])
        if func is None:
            continue
        creates = [row for row in function_rows if row["callee"] in _CREATE]
        adds = [row for row in function_rows if row["callee"] == "usb_add_hcd"]
        for create in creates:
            binding = create.get("return_binding") or {}
            hcd = binding.get("destination")
            if (binding.get("status") != "exact"
                    or not isinstance(hcd, str) or not hcd):
                continue
            matching_adds = [add for add in adds
                             if len(add["arguments"]) >= 1
                             and _norm(add["arguments"][0]) == _norm(hcd)
                             and create["location"]["offset"]
                             < add["location"]["offset"]
                             and not _is_loop(create) and not _is_loop(add)]
            if len(matching_adds) != 1:
                continue
            table = None
            create_call = create["call"]
            if create_call.args:
                table = _static_hc_driver(
                    create_call.args[0], func.source_path)
            if table is None:
                continue
            add = matching_adds[0]
            rows.append({
                "table": table,
                "create": {k: v for k, v in create.items() if k != "call"},
                "add": {k: v for k, v in add.items() if k != "call"},
                "hcd_expression": hcd,
                "init_function": _func_id(func),
            })

    # A host teardown must use one local HCD expression and preserve remove
    # before put.  Multiple candidates are deliberately ambiguous.
    teardown_rows: list[dict] = []
    for function_rows in by_function.values():
        func = func_by_id.get(function_rows[0]["function_usr"])
        if func is None:
            continue
        removes = [row for row in function_rows
                   if row["callee"] == "usb_remove_hcd"]
        puts = [row for row in function_rows if row["callee"] == "usb_put_hcd"]
        for remove in removes:
            if not remove["arguments"]:
                continue
            expression = remove["arguments"][0]
            matching_puts = [put for put in puts
                             if put["arguments"]
                             and _norm(put["arguments"][0]) == _norm(expression)
                             and remove["location"]["offset"]
                             < put["location"]["offset"]
                             and not _is_loop(remove) and not _is_loop(put)]
            if len(matching_puts) == 1:
                teardown_rows.append({
                    "remove": {k: v for k, v in remove.items() if k != "call"},
                    "put": {k: v for k, v in matching_puts[0].items()
                            if k != "call"},
                    "remove_function": _func_id(func),
                    "hcd_expression": expression,
                })

    if len(rows) != 1:
        empty["reasons"].append(
            f"expected one exact HCD create/add/table path, found {len(rows)}")
        return empty
    if len(teardown_rows) != 1:
        empty["reasons"].append(
            f"expected one exact HCD remove/put path, found {len(teardown_rows)}")
        return empty
    row = rows[0]
    teardown = teardown_rows[0]
    init_path, init_reason = _unique_call_path(
        adjacency, roots, row["init_function"])
    remove_path, remove_reason = _unique_call_path(
        adjacency, remove_roots, teardown["remove_function"])
    if init_reason:
        empty["reasons"].append(f"probe path: {init_reason}")
    if remove_reason:
        empty["reasons"].append(f"remove path: {remove_reason}")
    if init_reason or remove_reason:
        return empty
    table_name = row["table"]["name"]
    callback_fields = sorted({
        binding.get("field") for binding in
        (formal.get("metadata") or {}).get(
            "callback_binding_analysis", {}).get("bindings", [])
        if binding.get("table") == "hc_driver"
        and isinstance(binding.get("field"), str)
    })
    return {
        "schema": 1,
        "oracle": "source-ast-usb-hcd-lifecycle-v1",
        "status": "proven",
        "mode": "single-instance-hcd-projection",
        "tables": [{
            "name": table_name,
            "type": row["table"]["type"],
            "source": row["table"]["source"],
            "init_function": row["init_function"],
            "remove_function": teardown["remove_function"],
            "hcd_expression": row["hcd_expression"],
            "callback_fields": callback_fields,
            "create": row["create"],
            "add": row["add"],
            "remove": teardown["remove"],
            "put": teardown["put"],
            "probe_path": init_path,
            "remove_path": remove_path,
        }],
        "reasons": [],
    }
