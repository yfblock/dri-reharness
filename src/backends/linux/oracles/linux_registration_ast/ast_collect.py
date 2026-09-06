"""Single-pass libclang collection of the generated-C registration AST."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from gate.generated_c_ast_oracle import (  # noqa: E402
    ANCHOR_PREFIX,
    _load_clang,
)
from .support import (
    CONTROL_KINDS,
    WRAPPER_KINDS,
    _assignment_operator,
    _canonical_type,
    _children,
    _decl_scope,
    _function_refs,
    _in_source,
    _location,
    _object_path,
    _path_key,
    _signature,
    _signature_matches,
    _table_for_type,
    _unwrap,
    _variable_paths,
)


def _collect_ast(source: Path, clang_args: list[str], clang_library: str | None,
                 registration_policy: Mapping[str, Any]):
    cindex = _load_clang(clang_library)
    translation_unit = cindex.Index.create().parse(
        str(source), args=["-std=gnu11", "-Wno-everything", *clang_args])
    diagnostics = [{
        "severity": item.severity,
        "spelling": item.spelling,
        "location": {
            "file": str(item.location.file) if item.location.file else None,
            "line": item.location.line,
            "column": item.location.column,
        },
    } for item in translation_unit.diagnostics]

    definitions: dict[str, dict[str, Any]] = {}
    anchors: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    identity_bindings: list[dict[str, Any]] = []
    pointer_edges: list[dict[str, Any]] = []
    call_results: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    module_init_targets: set[str] = set()

    def visit(cursor, function=None, control_depth: int = 0) -> None:
        current_function = function
        if (cursor.kind.name == "FUNCTION_DECL" and cursor.is_definition()
                and _in_source(cursor, source)):
            current_function = cursor
            definitions[cursor.get_usr()] = {
                "usr": cursor.get_usr(),
                "name": cursor.spelling,
                "signature": _signature(cursor),
                "location": _location(cursor),
            }

        next_depth = control_depth + (1 if cursor.kind.name in CONTROL_KINDS else 0)

        if (cursor.kind.name == "LABEL_STMT"
                and cursor.spelling.startswith(ANCHOR_PREFIX)
                and current_function is not None):
            children = _children(cursor)
            anchors.append({
                "op_id": cursor.spelling[len(ANCHOR_PREFIX):],
                "function_usr": current_function.get_usr(),
                "function": current_function.spelling,
                "direct_compound": (
                    len(children) == 1
                    and children[0].kind.name == "COMPOUND_STMT"),
                "location": _location(cursor),
            })

        if (cursor.kind.name == "VAR_DECL" and current_function is not None
                and cursor.get_usr()):
            initializer_calls = [
                unwrapped for child in _children(cursor)
                if (unwrapped := _unwrap(child)).kind.name == "CALL_EXPR"
            ]
            if len(initializer_calls) == 1:
                initializer = initializer_calls[0]
                ref = initializer.referenced
                call_results.append({
                    "callee": (ref.spelling if ref is not None
                               else initializer.spelling),
                    "callee_usr": ref.get_usr() if ref is not None else None,
                    "callee_in_source": bool(ref and _in_source(ref, source)),
                    "dst": {
                        "root_usr": cursor.get_usr(),
                        "root": cursor.spelling,
                        "scope": _decl_scope(
                            cursor, current_function.get_usr()),
                        "fields": [],
                        "type": _canonical_type(cursor.type),
                    },
                    "function_usr": current_function.get_usr(),
                    "control_depth": control_depth,
                    "location": _location(initializer),
                })

        if (cursor.kind.name == "BINARY_OPERATOR"
                and current_function is not None
                and _assignment_operator(cursor)):
            children = _children(cursor)
            if len(children) == 2:
                left, right = children
                left_unwrapped = _unwrap(left)
                left_path = _object_path(left, current_function.get_usr())
                function_refs = _function_refs(right)
                if (left_path is not None
                        and left_unwrapped.kind.name == "MEMBER_REF_EXPR"
                        and len(function_refs) == 1):
                    field = left_unwrapped.referenced
                    base_children = _children(left_unwrapped)
                    base_type = (base_children[0].type if base_children
                                 else None)
                    table = (_table_for_type(base_type, registration_policy)
                             if base_type is not None else None)
                    target = function_refs[0]
                    bindings.append({
                        "kind": "assignment",
                        "table": table,
                        "field": left_unwrapped.spelling,
                        "field_usr": field.get_usr() if field else None,
                        "owner": {**left_path,
                                  "fields": left_path["fields"][:-1]},
                        "target_usr": target.get_usr(),
                        "target": target.spelling,
                        "target_signature": _signature(target),
                        "signature_matches": bool(
                            field and _signature_matches(field, target)),
                        "function_usr": current_function.get_usr(),
                        "function": current_function.spelling,
                        "control_depth": control_depth,
                        "location": _location(cursor),
                    })
                right_call = _unwrap(right)
                right_path = _object_path(
                    right, current_function.get_usr())
                if right_path is None:
                    right_paths = _variable_paths(
                        right, current_function.get_usr())
                    if len(right_paths) == 1:
                        right_path = right_paths[0]
                if (left_path is not None and right_path is not None
                        and right_call.kind.name != "CALL_EXPR"):
                    pointer_edges.append({
                        "kind": "assignment",
                        "dst": left_path,
                        "src": right_path,
                        "field": (left_unwrapped.spelling
                                  if left_unwrapped.kind.name
                                  == "MEMBER_REF_EXPR" else None),
                        "function_usr": current_function.get_usr(),
                        "control_depth": control_depth,
                        "location": _location(cursor),
                    })
                if (left_path is not None
                        and right_call.kind.name == "CALL_EXPR"):
                    ref = right_call.referenced
                    call_results.append({
                        "callee": (ref.spelling if ref is not None
                                   else right_call.spelling),
                        "callee_usr": ref.get_usr() if ref is not None else None,
                        "callee_in_source": bool(
                            ref and _in_source(ref, source)),
                        "dst": left_path,
                        "function_usr": current_function.get_usr(),
                        "control_depth": control_depth,
                        "location": _location(right_call),
                    })

        if cursor.kind.name == "CALL_EXPR" and current_function is not None:
            ref = cursor.referenced
            arguments = list(cursor.get_arguments())
            call = {
                "callee": ref.spelling if ref is not None else cursor.spelling,
                "callee_usr": ref.get_usr() if ref is not None else None,
                "callee_signature": (_canonical_type(ref.type)
                                     if ref is not None else None),
                "callee_in_source": bool(ref and _in_source(ref, source)),
                "function_usr": current_function.get_usr(),
                "function": current_function.spelling,
                "control_depth": control_depth,
                "arguments": [
                    _object_path(arg, current_function.get_usr())
                    for arg in arguments],
                "argument_types": [_canonical_type(arg.type)
                                   for arg in arguments],
                "argument_functions": [
                    [{"usr": item.get_usr(), "name": item.spelling,
                      "signature": _signature(item)}
                     for item in _function_refs(arg)]
                    for arg in arguments],
                "location": _location(cursor),
            }
            calls.append(call)

        for child in _children(cursor):
            visit(child, current_function, next_depth)

    top_level_vars = []
    for top in translation_unit.cursor.get_children():
        if not _in_source(top, source):
            continue
        if top.kind.name == "VAR_DECL":
            top_level_vars.append(top)
        visit(top)

    # Designated initializers are represented by MEMBER_REF cursors and RHS
    # references on the same source line.  Generated tables deliberately emit
    # one field per line, so line pairing remains AST-identity based while
    # avoiding source-text parsing.
    for variable in top_level_vars:
        table = _table_for_type(variable.type, registration_policy)
        if table is None:
            continue
        owner = {
            "root_usr": variable.get_usr(),
            "root": variable.spelling,
            "scope": "global",
            "fields": [],
            "type": _canonical_type(variable.type),
        }
        descendants: list[Any] = []

        def gather(node) -> None:
            descendants.append(node)
            for child in _children(node):
                gather(child)

        gather(variable)
        if table in registration_policy["device_id_tables"]:
            for literal in descendants:
                if literal.kind.name != "STRING_LITERAL":
                    continue
                value = literal.spelling
                if (len(value) >= 2 and value[0] == value[-1]
                        and value[0] in {"\"", "'"}):
                    value = value[1:-1]
                identity_bindings.append({
                    "table": table,
                    "field": "name",
                    "owner": owner,
                    "value": value,
                    "location": _location(literal),
                })
        refs_by_line: dict[int, list[Any]] = defaultdict(list)
        vars_by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for node in descendants:
            if node.kind.name == "DECL_REF_EXPR" and node.referenced is not None:
                if node.referenced.kind.name == "FUNCTION_DECL":
                    refs_by_line[node.location.line].append(node.referenced)
                else:
                    path = _object_path(node, None)
                    if path is not None and _path_key(path) != _path_key(owner):
                        vars_by_line[node.location.line].append(path)
        for node in descendants:
            if node.kind.name != "MEMBER_REF" or node.referenced is None:
                continue
            if (table in (registration_policy["root_tables"]
                          | registration_policy["device_id_tables"])
                    and node.spelling == "name"):
                literals = [item for item in descendants
                            if item.kind.name == "STRING_LITERAL"
                            and item.location.line == node.location.line]
                if len(literals) == 1:
                    value = literals[0].spelling
                    if (len(value) >= 2 and value[0] == value[-1]
                            and value[0] in {"\"", "'"}):
                        value = value[1:-1]
                    identity_bindings.append({
                        "table": table,
                        "field": "name",
                        "owner": owner,
                        "value": value,
                        "location": _location(node),
                    })
            functions = {
                item.get_usr(): item for item in refs_by_line[node.location.line]
                if item.get_usr()
            }
            if len(functions) == 1:
                target = next(iter(functions.values()))
                bindings.append({
                    "kind": "initializer",
                    "table": table,
                    "field": node.spelling,
                    "field_usr": node.referenced.get_usr(),
                    "owner": owner,
                    "target_usr": target.get_usr(),
                    "target": target.spelling,
                    "target_signature": _signature(target),
                    "signature_matches": _signature_matches(
                        node.referenced, target),
                    "function_usr": None,
                    "function": None,
                    "control_depth": 0,
                    "location": _location(node),
                })
            variables = {
                _path_key(item): item for item in vars_by_line[node.location.line]
            }
            if len(variables) == 1 and node.spelling in {
                    "pm", "ops", "fops", "init", "of_match_table", "data",
                    "ep0"}:
                pointer_edges.append({
                    "kind": "initializer",
                    "dst": owner,
                    "src": next(iter(variables.values())),
                    "field": node.spelling,
                    "function_usr": None,
                    "control_depth": 0,
                    "location": _location(node),
                })

    # The module_init macro expands to __inittest referencing the exact init
    # function.  Keep only source-local target definitions.
    for top in translation_unit.cursor.get_children():
        if not _in_source(top, source) or top.kind.name != "FUNCTION_DECL":
            continue
        if top.spelling != "__inittest":
            continue
        for ref in _function_refs(top):
            if ref.get_usr() in definitions:
                module_init_targets.add(ref.get_usr())

    return {
        "diagnostics": diagnostics,
        "definitions": definitions,
        "anchors": anchors,
        "bindings": bindings,
        "identity_bindings": identity_bindings,
        "pointer_edges": pointer_edges,
        "call_results": call_results,
        "calls": calls,
        "module_init_targets": sorted(module_init_targets),
    }
