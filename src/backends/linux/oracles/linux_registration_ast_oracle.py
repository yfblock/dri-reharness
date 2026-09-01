#!/usr/bin/env python3
"""Prove Linux callback registration from generated-C AST structure.

This oracle deliberately does not infer runtime reachability from a callback
name, a DeviceSpec field, a lowering receipt, or a function definition alone.
For the supported v1 shapes it requires an exact operation anchor, the
enclosing generated function, a type-correct callback-field binding, the same
framework object at a recognized registration call, and a registered
platform/PCI probe root.  Unsupported object/dataflow shapes remain explicit
and fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from extractor.compile_context import (  # noqa: E402
    _sanitize_arguments,
    read_kbuild_command,
)
from extractor.spec import device_spec_from_dict  # noqa: E402
from linux_registration_contracts import (  # noqa: E402
    LinuxRegistrationContractError,
    resolve_linux_registration_policy,
)
from generated_c_ast_oracle import (  # noqa: E402
    ANCHOR_PREFIX,
    _load_clang,
)


SCHEMA = 1
ORACLE = "linux-registration-ast-v1"
CONTROL_KINDS = {
    "IF_STMT", "FOR_STMT", "WHILE_STMT", "DO_STMT", "SWITCH_STMT",
    "CASE_STMT", "DEFAULT_STMT", "CONDITIONAL_OPERATOR",
}
WRAPPER_KINDS = {
    "UNEXPOSED_EXPR", "PAREN_EXPR", "CSTYLE_CAST_EXPR", "UNARY_OPERATOR",
}

def _location(cursor) -> dict[str, Any]:
    location = cursor.location
    return {
        "file": str(location.file) if location.file else None,
        "line": location.line,
        "column": location.column,
        "offset": location.offset,
    }


def _stable_chain(chain: Any) -> Any:
    """Remove workspace-specific paths from a route identity chain."""
    if not isinstance(chain, list):
        return chain
    normalized = []
    for item in chain:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        row = dict(item)
        location = row.get("location")
        if isinstance(location, dict):
            row["location"] = {
                key: location.get(key) for key in (
                    "line", "column", "offset")
            }
        normalized.append(row)
    return normalized


def registration_route_fingerprint(route: dict) -> str:
    binding = route.get("binding") or {}
    identity = {
        "callback": route.get("callback"),
        "target_usr": route.get("target_usr"),
        "binding": {
            "kind": binding.get("kind"),
            "field_usr": binding.get("field_usr"),
            "owner": _path_key(binding.get("owner")),
        },
        "registration": _stable_chain(
            (route.get("registration") or {}).get("chain")),
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _in_source(cursor, source: Path) -> bool:
    if not cursor.location.file:
        return False
    try:
        return Path(str(cursor.location.file)).resolve() == source
    except OSError:
        return False


def _canonical_type(value) -> str:
    try:
        return value.get_canonical().spelling
    except Exception:
        return value.spelling


def _record_name(type_spelling: str) -> str | None:
    match = re.search(r"\bstruct\s+([A-Za-z_]\w*)", type_spelling)
    return match.group(1) if match else None


def _table_for_type(type_value, registration_policy: Mapping[str, Any]) -> str | None:
    name = _record_name(_canonical_type(type_value))
    return registration_policy["struct_tables"].get(name or "")


def _children(cursor) -> list[Any]:
    return list(cursor.get_children())


def _unwrap(cursor):
    current = cursor
    while current.kind.name in WRAPPER_KINDS:
        children = [child for child in _children(current)
                    if child.kind.name not in {"TYPE_REF"}]
        if len(children) != 1:
            break
        current = children[0]
    return current


def _decl_scope(ref, function_usr: str | None) -> str:
    parent = ref.semantic_parent
    if parent is not None and parent.kind.name == "TRANSLATION_UNIT":
        return "global"
    return f"function:{function_usr or '<none>'}"


def _path_key(path: dict[str, Any] | None) -> tuple | None:
    if not path:
        return None
    return (path["root_usr"], tuple(field["field_usr"]
                                    for field in path["fields"]))


def _path_parent_key(path: dict[str, Any] | None) -> tuple | None:
    key = _path_key(path)
    if key is None or not key[1]:
        return None
    return (key[0], key[1][:-1])


def _path_table(path: dict[str, Any] | None,
                registration_policy: Mapping[str, Any]) -> str | None:
    if not path:
        return None
    name = _record_name(path.get("type") or "")
    return registration_policy["struct_tables"].get(name or "")


def _object_path(cursor, function_usr: str | None) -> dict[str, Any] | None:
    current = _unwrap(cursor)
    kind = current.kind.name
    if kind == "DECL_REF_EXPR":
        ref = current.referenced
        if ref is None or ref.kind.name not in {"VAR_DECL", "PARM_DECL"}:
            return None
        usr = ref.get_usr()
        if not usr:
            return None
        return {
            "root_usr": usr,
            "root": ref.spelling,
            "scope": _decl_scope(ref, function_usr),
            "fields": [],
            "type": _canonical_type(ref.type),
        }
    if kind == "MEMBER_REF_EXPR":
        candidates = [child for child in _children(current)
                      if child.kind.name not in {"TYPE_REF"}]
        base = next((_object_path(child, function_usr)
                     for child in candidates
                     if _object_path(child, function_usr) is not None), None)
        if base is None or current.referenced is None:
            return None
        field = current.referenced
        base = json.loads(json.dumps(base))
        base["fields"].append({
            "field_usr": field.get_usr(),
            "field": field.spelling,
            "owner_usr": (field.semantic_parent.get_usr()
                          if field.semantic_parent else None),
            "owner_type": (field.semantic_parent.spelling
                           if field.semantic_parent else None),
        })
        base["type"] = _canonical_type(current.type)
        return base
    return None


def _function_refs(cursor) -> list[Any]:
    refs: dict[str, Any] = {}

    def visit(node) -> None:
        if node.kind.name == "DECL_REF_EXPR" and node.referenced is not None:
            ref = node.referenced
            if ref.kind.name == "FUNCTION_DECL" and ref.get_usr():
                refs[ref.get_usr()] = ref
        for child in _children(node):
            visit(child)

    visit(cursor)
    return list(refs.values())


def _variable_paths(cursor, function_usr: str | None) -> list[dict[str, Any]]:
    found: dict[tuple, dict[str, Any]] = {}

    def visit(node) -> None:
        path = _object_path(node, function_usr)
        key = _path_key(path)
        if key is not None:
            found[key] = path
        for child in _children(node):
            visit(child)

    visit(cursor)
    return list(found.values())


def _resolve_local_alias(
        path: dict[str, Any] | None, pointer_edges: list[dict[str, Any]],
        function_usr: str | None, before_offset: int) -> dict[str, Any] | None:
    """Resolve a straight-line local pointer alias to its object path.

    Linux drivers commonly assign nested framework objects to a short-lived
    local such as ``girq`` before filling callback fields.  The AST oracle
    must retain the object identity while refusing aliases whose assignment
    is conditional or occurs after the use being proven.
    """
    def resolve(current: dict[str, Any] | None,
                seen: set[tuple]) -> dict[str, Any] | None:
        if current is None:
            return None
        root = json.loads(json.dumps(current))
        suffix = list(root.get("fields") or [])
        root["fields"] = []
        key = _path_key(root)
        if key is None:
            return current
        if key in seen:
            return None
        seen = {*seen, key}
        assignments = [
            edge for edge in pointer_edges
            if edge.get("kind") == "assignment"
            and edge.get("function_usr") == function_usr
            and _path_key(edge.get("dst")) == key
            and edge.get("location", {}).get("offset", -1) < before_offset
        ]
        if not assignments:
            return current
        if any(edge.get("control_depth") for edge in assignments):
            return None
        selected = max(
            assignments,
            key=lambda edge: edge.get("location", {}).get("offset", -1),
        )
        resolved = resolve(selected.get("src"), seen)
        if resolved is None:
            return None
        merged = json.loads(json.dumps(resolved))
        merged["fields"] = [*(resolved.get("fields") or []), *suffix]
        if suffix:
            merged["type"] = current.get("type")
        return merged

    return resolve(path, set())


def _resolve_local_aliases(ast: dict[str, Any]) -> None:
    """Canonicalize paths used by bindings and calls before route analysis."""
    pointer_edges = ast.get("pointer_edges") or []

    for binding in ast.get("bindings") or []:
        function_usr = binding.get("function_usr")
        offset = binding.get("location", {}).get("offset", -1)
        resolved = _resolve_local_alias(
            binding.get("owner"), pointer_edges, function_usr, offset)
        if resolved is not None:
            binding["owner"] = resolved

    for call in ast.get("calls") or []:
        function_usr = call.get("function_usr")
        offset = call.get("location", {}).get("offset", -1)
        arguments = []
        for argument in call.get("arguments") or []:
            resolved = _resolve_local_alias(
                argument, pointer_edges, function_usr, offset)
            arguments.append(resolved if resolved is not None else argument)
        call["arguments"] = arguments

    for result in ast.get("call_results") or []:
        function_usr = result.get("function_usr")
        offset = result.get("location", {}).get("offset", -1)
        resolved = _resolve_local_alias(
            result.get("dst"), pointer_edges, function_usr, offset)
        if resolved is not None:
            result["dst"] = resolved


def _signature(function) -> dict[str, Any]:
    function_type = function.type
    kind = getattr(getattr(function_type, "kind", None), "name", None)
    variadic = False
    if kind == "FUNCTIONPROTO":
        try:
            variadic = bool(function_type.is_function_variadic())
        except (AssertionError, AttributeError):
            # Some builtin declarations expose a function-like spelling but
            # do not support clang's variadic query through cindex.
            variadic = False
    return {
        "canonical": _canonical_type(function_type),
        "result": _canonical_type(function.result_type),
        "params": [_canonical_type(arg.type) for arg in function.get_arguments()],
        "variadic": variadic,
    }


def _signature_matches(field, function) -> bool:
    try:
        field_type = field.type.get_canonical()
        pointee = field_type.get_pointee()
        return _canonical_type(pointee) == _canonical_type(function.type)
    except Exception:
        return False


def _assignment_operator(cursor) -> bool:
    tokens = [token.spelling for token in cursor.get_tokens()]
    return tokens.count("=") == 1


def linux_kbuild_compile_context(
        source: Path, command_file: Path) -> tuple[list[str], dict]:
    raw = read_kbuild_command(str(command_file))
    if not raw:
        raise ValueError(f"no saved Kbuild command in {command_file}")
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"invalid saved Kbuild command: {exc}") from exc
    args = list(_sanitize_arguments(
        tokens, str(command_file.parent.resolve()), str(source)))
    encoded = "\0".join(args).encode("utf-8")
    return args, {
        "origin": "kbuild-cmd",
        "provenance": str(command_file.resolve()),
        "raw_command_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "arguments_sha256": hashlib.sha256(encoded).hexdigest(),
        "argument_count": len(args),
    }


# Compatibility for the initial C20 tests and any local callers written
# before the exact Kbuild context helper became part of the public interface.
_compile_context = linux_kbuild_compile_context


def _device_routes(device_spec: Any) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for function in device_spec.functions:
        module = function.ris_ref or function.name
        if module in routes:
            raise ValueError(f"ambiguous DeviceSpec route for {module!r}")
        routes[module] = {
            "function": function.name,
            "ris_ref": function.ris_ref,
            "role": function.role,
            "callback": function.callback_table,
        }
    return routes


def _call_policy(call: dict, source: Path,
                 registration_policy: Mapping[str, Any]
                 ) -> tuple[dict | None, list[str]]:
    callee = call["callee"]
    policy = registration_policy["registration_apis"].get(callee)
    errors: list[str] = []
    if policy is None:
        return None, errors
    if call["callee_in_source"]:
        errors.append("registration callee is shadowed in generated source")
    index = policy["arg"]
    if index >= len(call["arguments"]):
        errors.append("registration call has too few arguments")
    else:
        observed = call["argument_types"][index]
        if observed != policy["type"]:
            errors.append(
                f"registration object type mismatch: {observed!r} != "
                f"{policy['type']!r}")
        if call["arguments"][index] is None:
            errors.append("registration object has no exact AST identity")
    if call["control_depth"]:
        errors.append("registration call is under unsupported control flow")
    return policy, errors


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


def _registered_routes(
        ast: dict, source: Path,
        registration_policy: Mapping[str, Any]
        ) -> tuple[list[dict], list[dict]]:
    _resolve_local_aliases(ast)
    bindings = ast["bindings"]
    call_results = ast["call_results"]
    calls = ast["calls"]
    module_init_targets = set(ast["module_init_targets"])
    errors: list[dict] = []
    object_proofs: dict[tuple, dict] = {}
    routes: list[dict] = []

    root_calls = []
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] not in {"driver_root", "object_root"}:
            continue
        if call["function_usr"] not in module_init_targets:
            problems.append("driver registration is not referenced by module_init")
        if problems:
            errors.append({"kind": "invalid_root_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        key = _path_key(owner)
        proof = {
            "object": owner,
            "kind": policy["kind"],
            "table": policy["table"],
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[key] = proof
        root_calls.append((policy, owner, call, proof))

    # Root-table callback targets (notably probe) become registered only when
    # the exact table object is the module_init registration argument.
    registered_probe_usrs: set[str] = set()
    registered_remove_usrs: set[str] = set()
    for binding in bindings:
        key = _path_key(binding["owner"])
        proof = object_proofs.get(key)
        if (proof and binding["kind"] == "initializer"
                and binding["table"] == proof["table"]
                and binding["signature_matches"]):
            route = {
                "callback": f"{binding['table']}.{binding['field']}",
                "target_usr": binding["target_usr"],
                "target": binding["target"],
                "binding": binding,
                "registration": proof,
                "runtime_entry_registered": True,
            }
            routes.append(route)
            if (proof["kind"] == "driver_root"
                    and binding["field"] == "probe"):
                registered_probe_usrs.add(binding["target_usr"])
            if (proof["kind"] == "driver_root"
                    and binding["field"] == "remove"):
                registered_remove_usrs.add(binding["target_usr"])

    # Straight-line GPIO registration is accepted only from a probe already
    # proven by the root driver chain.
    gpio_sinks: list[tuple[dict, dict, dict]] = []
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] != "gpio_chip":
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append("GPIO registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_gpio_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": "gpio_chip",
            "table": "gpio_chip",
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof
        gpio_sinks.append((owner, call, proof))

    # A misc device is a public registration sink for file_operations.  Keep
    # the proof tied to a registered probe and the exact miscdevice identity;
    # the fops callback table is linked below through its typed field.
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] != "miscdevice":
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append("miscdevice registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_misc_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": "miscdevice",
            "table": "miscdevice",
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof

    # Other framework objects can be registered from a proven probe and then
    # lead through typed pointer fields to their callback table.  Clock v1 is
    # the first such sink; SDHCI/USB reuse the same typed object-flow below.
    for call in calls:
        policy, problems = _call_policy(call, source, registration_policy)
        if policy is None or policy["kind"] not in {"clk_hw"}:
            continue
        if call["function_usr"] not in registered_probe_usrs:
            problems.append(
                f"{policy['kind']} registration is outside a registered probe")
        if problems:
            errors.append({"kind": "invalid_framework_registration",
                           "call": call, "errors": problems})
            continue
        owner = call["arguments"][policy["arg"]]
        proof = {
            "object": owner,
            "kind": policy["kind"],
            "table": policy["table"],
            "function_usr": call["function_usr"],
            "registration_offset": call["location"]["offset"],
            "chain": [{"kind": "registered_probe",
                       "function_usr": call["function_usr"]},
                      {"kind": "registration_call", "call": call["callee"],
                       "location": call["location"]}],
        }
        object_proofs[_path_key(owner)] = proof

    link_tables = registration_policy["link_tables"]
    changed = True
    while changed:
        changed = False
        for edge in ast["pointer_edges"]:
            dst_key = _path_key(edge.get("dst"))
            proof = object_proofs.get(dst_key)
            if proof is None:
                proof = object_proofs.get(_path_parent_key(edge.get("dst")))
            if proof is None:
                continue
            expected_table = link_tables.get(
                (proof.get("table"), edge.get("field")))
            if expected_table is None or _path_table(
                    edge.get("src"), registration_policy) != \
                    expected_table:
                continue
            if edge.get("kind") == "assignment" and (
                    edge.get("function_usr") != proof.get("function_usr")
                    or edge.get("control_depth")
                    or edge["location"]["offset"] >=
                    proof["registration_offset"]):
                continue
            src_key = _path_key(edge.get("src"))
            if src_key in object_proofs:
                continue
            object_proofs[src_key] = {
                "object": edge["src"],
                "kind": "typed_object_link",
                "table": expected_table,
                "function_usr": proof.get("function_usr"),
                "registration_offset": proof["registration_offset"],
                "chain": [*proof["chain"], {
                    "kind": "typed_object_link",
                    "field": edge.get("field"),
                    "location": edge.get("location"),
                }],
            }
            changed = True

    # SDHCI callbacks become live only after the exact pdata object is passed
    # to sdhci_pltfm_init(), the returned host identity is preserved, and that
    # same host is handed to sdhci_add_host().  device_get_match_data() is
    # accepted only when it is backed by the exact OF table on the registered
    # driver; straight-line and controlled fallback assignments may add only
    # statically typed pdata objects to that finite set.
    calls_by_location = {
        (call["function_usr"], call["location"]["offset"]): call
        for call in calls
    }
    proven_match_tables = [
        proof for proof in object_proofs.values()
        if proof.get("table") == "of_device_id"
    ]
    for add_call in calls:
        if add_call["callee"] not in {"sdhci_add_host", "__sdhci_add_host"}:
            continue
        problems: list[str] = []
        if add_call["callee_in_source"]:
            problems.append("SDHCI add-host callee is shadowed")
        if add_call["function_usr"] not in registered_probe_usrs:
            problems.append("SDHCI add-host is outside a registered probe")
        if add_call["control_depth"]:
            problems.append("SDHCI add-host is under unsupported control flow")
        if (not add_call["arguments"] or add_call["arguments"][0] is None
                or add_call["argument_types"][0] != "struct sdhci_host *"):
            problems.append("SDHCI add-host has no exact host identity")
        if problems:
            errors.append({"kind": "invalid_sdhci_lifecycle",
                           "call": add_call, "errors": problems})
            continue

        host_key = _path_key(add_call["arguments"][0])
        init_results = [
            result for result in call_results
            if result["callee"] == "sdhci_pltfm_init"
            and result["function_usr"] == add_call["function_usr"]
            and _path_key(result["dst"]) == host_key
            and result["location"]["offset"] < add_call["location"]["offset"]
        ]
        if len(init_results) != 1:
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI host does not have one exact init result"],
            })
            continue
        init_result = init_results[0]
        init_call = calls_by_location.get((
            init_result["function_usr"], init_result["location"]["offset"]))
        if (init_call is None or init_call["callee_in_source"]
                or init_call["control_depth"]
                or len(init_call["arguments"]) < 2
                or init_call["arguments"][1] is None
                or init_call["argument_types"][1]
                != "const struct sdhci_pltfm_data *"):
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI init call has no exact pdata identity"],
            })
            continue
        intervening_host_writes = [
            item for item in [*call_results, *ast["pointer_edges"]]
            if _path_key(item.get("dst")) == host_key
            and init_result["location"]["offset"]
            < item["location"]["offset"] < add_call["location"]["offset"]
        ]
        if intervening_host_writes:
            errors.append({
                "kind": "invalid_sdhci_lifecycle", "call": add_call,
                "errors": ["SDHCI host identity is overwritten before add"],
            })
            continue

        pdata = init_call["arguments"][1]
        pdata_key = _path_key(pdata)
        pdata_objects: dict[tuple, tuple[dict, list[dict]]] = {}
        if (pdata.get("scope") == "global"
                and _path_table(pdata, registration_policy) == "sdhci_pltfm_data"):
            pdata_objects[pdata_key] = (pdata, [{
                "kind": "direct_pdata_argument",
                "location": init_call["location"],
            }])
        else:
            match_results = [
                result for result in call_results
                if result["callee"] == "device_get_match_data"
                and result["function_usr"] == init_call["function_usr"]
                and _path_key(result["dst"]) == pdata_key
                and result["location"]["offset"]
                < init_call["location"]["offset"]
            ]
            if len(match_results) != 1 or not proven_match_tables:
                problems.append(
                    "SDHCI pdata has no exact registered match-data source")
            else:
                match_result = match_results[0]
                match_call = calls_by_location.get((
                    match_result["function_usr"],
                    match_result["location"]["offset"]))
                if (match_call is None or match_call["callee_in_source"]
                        or match_call["control_depth"]
                        or not match_call["arguments"]
                        or match_call["argument_types"][0]
                        != "const struct device *"):
                    problems.append("invalid device_get_match_data call")
                else:
                    for proof in proven_match_tables:
                        match_key = _path_key(proof["object"])
                        for edge in ast["pointer_edges"]:
                            if (_path_key(edge.get("dst")) != match_key
                                    or edge.get("field") != "data"):
                                continue
                            source_object = edge.get("src")
                            if (_path_table(source_object, registration_policy) !=
                                    "sdhci_pltfm_data"):
                                problems.append(
                                    "OF match data is not SDHCI pdata")
                                continue
                            pdata_objects[_path_key(source_object)] = (
                                source_object,
                                [*proof["chain"], {
                                    "kind": "match_data_edge",
                                    "location": edge["location"],
                                }],
                            )

                    pdata_assignments = [
                        edge for edge in ast["pointer_edges"]
                        if edge.get("kind") == "assignment"
                        and edge.get("function_usr")
                        == init_call["function_usr"]
                        and _path_key(edge.get("dst")) == pdata_key
                        and match_result["location"]["offset"]
                        < edge["location"]["offset"]
                        < init_call["location"]["offset"]
                    ]
                    for edge in pdata_assignments:
                        source_object = edge.get("src")
                        if (source_object.get("scope") != "global"
                                or _path_table(source_object, registration_policy)
                                != "sdhci_pltfm_data"):
                            problems.append(
                                "SDHCI fallback is not static typed pdata")
                            continue
                        pdata_objects[_path_key(source_object)] = (
                            source_object, [{
                                "kind": "finite_pdata_fallback",
                                "location": edge["location"],
                            }])
                    other_pdata_results = [
                        result for result in call_results
                        if result is not match_result
                        and result["function_usr"] == init_call["function_usr"]
                        and _path_key(result.get("dst")) == pdata_key
                        and result["location"]["offset"]
                        < init_call["location"]["offset"]
                    ]
                    if other_pdata_results:
                        problems.append(
                            "SDHCI pdata has an unsupported call-result source")
            if not pdata_objects:
                problems.append("SDHCI pdata finite set is empty")

        if problems:
            errors.append({"kind": "invalid_sdhci_lifecycle",
                           "call": add_call, "errors": problems})
            continue

        lifecycle_tail = [{
            "kind": "sdhci_pltfm_init",
            "location": init_call["location"],
        }, {
            "kind": "sdhci_host_result",
            "object": init_result["dst"],
            "location": init_result["location"],
        }, {
            "kind": "sdhci_add_host",
            "call": add_call["callee"],
            "location": add_call["location"],
        }]
        for source_object, origin_chain in pdata_objects.values():
            object_proofs[_path_key(source_object)] = {
                "object": source_object,
                "kind": "sdhci_lifecycle",
                "table": "sdhci_pltfm_data",
                "function_usr": init_call["function_usr"],
                "registration_offset": add_call["location"]["offset"],
                "chain": [{"kind": "registered_probe",
                           "function_usr": init_call["function_usr"]},
                          *origin_chain, *lifecycle_tail],
            }

    # Propagate lifecycle-proven pdata to its exact ops table.  This pass is
    # separate from the general fixed point because pdata must never become
    # authoritative from match-table reachability alone.
    for edge in ast["pointer_edges"]:
        proof = object_proofs.get(_path_key(edge.get("dst")))
        if (not proof or proof.get("table") != "sdhci_pltfm_data"
                or edge.get("field") != "ops"
                                or _path_table(
                                    edge.get("src"), registration_policy)
                                != "sdhci_ops"):
            continue
        object_proofs[_path_key(edge["src"])] = {
            "object": edge["src"],
            "kind": "typed_object_link",
            "table": "sdhci_ops",
            "function_usr": proof.get("function_usr"),
            "registration_offset": proof["registration_offset"],
            "chain": [*proof["chain"], {
                "kind": "typed_object_link", "field": "ops",
                "location": edge["location"],
            }],
        }

    # Conservative single-instance USB host lifecycle.  The exact hc_driver
    # table must enter usb_create_hcd(), its returned hcd must be stored as the
    # platform drvdata and passed unchanged to usb_add_hcd().  A registered
    # remove callback must recover that drvdata and pass the same local hcd to
    # usb_remove_hcd() followed by usb_put_hcd().
    for add_call in calls:
        if add_call["callee"] != "usb_add_hcd":
            continue
        problems = []
        if (add_call["callee_in_source"] or add_call["control_depth"]
                or add_call["function_usr"] not in registered_probe_usrs
                or not add_call["arguments"]
                or add_call["arguments"][0] is None
                or add_call["argument_types"][0] != "struct usb_hcd *"):
            problems.append("invalid USB HCD add call")
        if problems:
            errors.append({"kind": "invalid_usb_hcd_lifecycle",
                           "call": add_call, "errors": problems})
            continue
        hcd_key = _path_key(add_call["arguments"][0])
        create_results = [
            result for result in call_results
            if result["callee"] in {"usb_create_hcd", "usb_create_shared_hcd"}
            and result["function_usr"] == add_call["function_usr"]
            and _path_key(result["dst"]) == hcd_key
            and result["location"]["offset"] < add_call["location"]["offset"]
        ]
        if len(create_results) != 1:
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD has no unique create result"],
            })
            continue
        create_result = create_results[0]
        create_call = calls_by_location.get((
            create_result["function_usr"],
            create_result["location"]["offset"]))
        if (create_call is None or create_call["callee_in_source"]
                or create_call["control_depth"]
                or not create_call["arguments"]
                or create_call["arguments"][0] is None
                or _path_table(
                    create_call["arguments"][0], registration_policy)
                != "hc_driver"
                or create_call["arguments"][0].get("scope") != "global"):
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD create has no exact static hc_driver"],
            })
            continue
        host_writes = [
            item for item in [*call_results, *ast["pointer_edges"]]
            if _path_key(item.get("dst")) == hcd_key
            and create_result["location"]["offset"]
            < item["location"]["offset"] < add_call["location"]["offset"]
        ]
        set_drvdata = [
            call for call in calls
            if call["callee"] == "platform_set_drvdata"
            and not call["callee_in_source"] and not call["control_depth"]
            and call["function_usr"] == add_call["function_usr"]
            and len(call["arguments"]) >= 2
            and _path_key(call["arguments"][1]) == hcd_key
            and create_result["location"]["offset"]
            < call["location"]["offset"] < add_call["location"]["offset"]
        ]
        teardown = None
        for remove_usr in registered_remove_usrs:
            get_results = [
                result for result in call_results
                if result["callee"] == "platform_get_drvdata"
                and not result["callee_in_source"]
                and result["function_usr"] == remove_usr
                and not result["control_depth"]
            ]
            for get_result in get_results:
                remove_hcd = [
                    call for call in calls
                    if call["callee"] == "usb_remove_hcd"
                    and not call["callee_in_source"]
                    and not call["control_depth"]
                    and call["function_usr"] == remove_usr
                    and call["arguments"]
                    and _path_key(call["arguments"][0])
                    == _path_key(get_result["dst"])
                    and get_result["location"]["offset"]
                    < call["location"]["offset"]
                ]
                put_hcd = [
                    call for call in calls
                    if call["callee"] == "usb_put_hcd"
                    and not call["callee_in_source"]
                    and not call["control_depth"]
                    and call["function_usr"] == remove_usr
                    and call["arguments"]
                    and _path_key(call["arguments"][0])
                    == _path_key(get_result["dst"])
                    and remove_hcd
                    and remove_hcd[0]["location"]["offset"]
                    < call["location"]["offset"]
                ]
                if len(remove_hcd) == 1 and len(put_hcd) == 1:
                    teardown = (get_result, remove_hcd[0], put_hcd[0])
                    break
            if teardown:
                break
        if host_writes or len(set_drvdata) != 1 or teardown is None:
            errors.append({
                "kind": "invalid_usb_hcd_lifecycle", "call": add_call,
                "errors": ["USB HCD identity/storage/teardown proof failed"],
            })
            continue
        get_result, remove_call, put_call = teardown
        table = create_call["arguments"][0]
        object_proofs[_path_key(table)] = {
            "object": table,
            "kind": "usb_hcd_lifecycle",
            "table": "hc_driver",
            "function_usr": add_call["function_usr"],
            "registration_offset": add_call["location"]["offset"],
            "chain": [
                {"kind": "registered_probe",
                 "function_usr": add_call["function_usr"]},
                {"kind": "usb_create_hcd", "location": create_call["location"]},
                {"kind": "platform_set_drvdata",
                 "location": set_drvdata[0]["location"]},
                {"kind": "usb_add_hcd", "location": add_call["location"]},
                {"kind": "registered_remove",
                 "function_usr": remove_call["function_usr"]},
                {"kind": "platform_get_drvdata",
                 "location": get_result["location"]},
                {"kind": "usb_remove_hcd",
                 "location": remove_call["location"]},
                {"kind": "usb_put_hcd", "location": put_call["location"]},
            ],
        }

    # Conservative gadget lifecycle: only a single statically identifiable
    # gadget object is accepted.  It must be added in the registered probe and
    # deleted by the registered remove callback.  An endpoint table is exposed
    # only when an exact ep0 pointer proves that endpoint belongs to the gadget.
    for add_call in calls:
        if add_call["callee"] != "usb_add_gadget_udc":
            continue
        problems = []
        gadget = (add_call["arguments"][1]
                  if len(add_call["arguments"]) > 1 else None)
        if (add_call["callee_in_source"] or add_call["control_depth"]
                or add_call["function_usr"] not in registered_probe_usrs
                or gadget is None
                or _path_table(gadget, registration_policy) != "usb_gadget"
                or gadget.get("scope") != "global"):
            problems.append("invalid or non-static USB gadget add call")
        delete_calls = [
            call for call in calls
            if call["callee"] == "usb_del_gadget_udc"
            and not call["callee_in_source"] and not call["control_depth"]
            and call["function_usr"] in registered_remove_usrs
            and call["arguments"]
            and _path_key(call["arguments"][0]) == _path_key(gadget)
        ] if gadget else []
        if len(delete_calls) != 1:
            problems.append("USB gadget has no exact registered delete")
        if problems:
            errors.append({"kind": "invalid_usb_gadget_lifecycle",
                           "call": add_call, "errors": problems})
            continue
        gadget_proof = {
            "object": gadget,
            "kind": "usb_gadget_lifecycle",
            "table": "usb_gadget",
            "function_usr": add_call["function_usr"],
            "registration_offset": add_call["location"]["offset"],
            "chain": [
                {"kind": "registered_probe",
                 "function_usr": add_call["function_usr"]},
                {"kind": "usb_add_gadget_udc",
                 "location": add_call["location"]},
                {"kind": "registered_remove",
                 "function_usr": delete_calls[0]["function_usr"]},
                {"kind": "usb_del_gadget_udc",
                 "location": delete_calls[0]["location"]},
            ],
        }
        object_proofs[_path_key(gadget)] = gadget_proof
        for edge in ast["pointer_edges"]:
            edge_owner = (_path_key(edge.get("dst"))
                          if edge.get("kind") == "initializer"
                          else _path_parent_key(edge.get("dst")))
            if (edge_owner != _path_key(gadget)
                    or edge.get("field") != "ep0"
                    or _path_table(edge.get("src"), registration_policy)
                    != "usb_ep"):
                continue
            if (edge.get("kind") == "assignment" and (
                    edge.get("function_usr") != add_call["function_usr"]
                    or edge.get("control_depth")
                    or edge["location"]["offset"]
                    >= add_call["location"]["offset"])):
                continue
            object_proofs[_path_key(edge["src"])] = {
                "object": edge["src"], "kind": "usb_gadget_ep0",
                "table": "usb_ep",
                "function_usr": add_call["function_usr"],
                "registration_offset": add_call["location"]["offset"],
                "chain": [*gadget_proof["chain"], {
                    "kind": "usb_gadget_ep0",
                    "location": edge["location"],
                }],
            }

    # USB gadget/endpoint ops links are lifecycle-authoritative only after the
    # add/delete and ownership proofs above have succeeded.
    for edge in ast["pointer_edges"]:
        proof = object_proofs.get(_path_key(edge.get("dst")))
        expected = {
            ("usb_gadget", "ops"): "usb_gadget_ops",
            ("usb_ep", "ops"): "usb_ep_ops",
        }.get((proof.get("table") if proof else None, edge.get("field")))
        if (expected is None
                or _path_table(edge.get("src"), registration_policy) != expected):
            continue
        if edge.get("kind") == "assignment" and (
                edge.get("function_usr") != proof.get("function_usr")
                or edge.get("control_depth")
                or edge["location"]["offset"] >= proof["registration_offset"]):
            continue
        object_proofs[_path_key(edge["src"])] = {
            "object": edge["src"], "kind": "typed_object_link",
            "table": expected,
            "function_usr": proof.get("function_usr"),
            "registration_offset": proof["registration_offset"],
            "chain": [*proof["chain"], {
                "kind": "typed_object_link", "field": edge.get("field"),
                "location": edge["location"],
            }],
        }

    # Static callback tables reached through the typed framework-object graph
    # (PM and clock in v1) are runtime registered just like root tables.
    for binding in bindings:
        proof = object_proofs.get(_path_key(binding.get("owner")))
        if (proof and binding["kind"] == "initializer"
                and binding["table"] == proof.get("table")
                and binding["signature_matches"]):
            routes.append({
                "callback": f"{binding['table']}.{binding['field']}",
                "target_usr": binding["target_usr"],
                "target": binding["target"],
                "binding": binding,
                "registration": proof,
                "runtime_entry_registered": True,
            })

    # Attach an irq_chip to the exact gpio_irq_chip nested in a registered
    # gpio_chip.  Both calls must be straight-line and ordered before the sink.
    for call in calls:
        policy = registration_policy["irq_attach_apis"].get(call["callee"])
        if policy is None or call["function_usr"] not in registered_probe_usrs:
            continue
        if call["callee_in_source"] or call["control_depth"]:
            errors.append({"kind": "invalid_irq_attach", "call": call,
                           "errors": ["shadowed or controlled attach call"]})
            continue
        if max(policy.values()) >= len(call["arguments"]):
            continue
        parent = call["arguments"][policy["parent_arg"]]
        child = call["arguments"][policy["child_arg"]]
        if parent is None or child is None:
            continue
        parent_parent = _path_parent_key(parent)
        sink = next((proof for owner, sink_call, proof in gpio_sinks
                     if _path_key(owner) == parent_parent
                     and sink_call["function_usr"] == call["function_usr"]
                     and call["location"]["offset"]
                     < sink_call["location"]["offset"]), None)
        if sink:
            object_proofs[_path_key(child)] = {
                "object": child,
                "kind": "irq_chip",
                "table": "irq_chip",
                "function_usr": call["function_usr"],
                "registration_offset": sink["registration_offset"],
                "chain": [*sink["chain"], {
                    "kind": "irq_chip_attach", "call": call["callee"],
                    "location": call["location"],
                }],
            }

    # Dynamic callback slots must be the final straight-line assignment before
    # registration of the exact owner object.  Nested gpio_irq_chip fields are
    # owned by the registered gpio_chip object.
    candidates: dict[tuple, list[dict]] = defaultdict(list)
    for binding in bindings:
        if (binding["kind"] not in {"assignment", "initializer"}
                or not binding["signature_matches"]):
            continue
        owner_key = _path_key(binding["owner"])
        proof = object_proofs.get(owner_key)
        if proof is None and binding["table"] == "gpio_irq_chip":
            parent_key = _path_parent_key(binding["owner"])
            proof = object_proofs.get(parent_key)
        if proof is None:
            continue
        if binding["kind"] == "initializer":
            valid_binding_context = binding["owner"].get("scope") == "global"
        else:
            valid_binding_context = (
                binding["function_usr"] == proof["function_usr"])
        if (not valid_binding_context or binding["control_depth"]
                or binding["location"]["offset"]
                >= proof["registration_offset"]):
            continue
        slot = (owner_key, binding["field"], proof["registration_offset"])
        candidates[slot].append({"binding": binding, "proof": proof})
    for rows in candidates.values():
        selected = max(rows, key=lambda item: item["binding"]["location"]["offset"])
        binding, proof = selected["binding"], selected["proof"]
        routes.append({
            "callback": f"{binding['table']}.{binding['field']}",
            "target_usr": binding["target_usr"],
            "target": binding["target"],
            "binding": binding,
            "registration": proof,
            "runtime_entry_registered": True,
        })

    # Direct IRQ registration binds a function argument rather than an owner
    # field.  v1 accepts it only inside a registered probe and from a real
    # external kernel declaration.
    for call in calls:
        policy = registration_policy["direct_irq_apis"].get(call["callee"])
        if policy is None or call["function_usr"] not in registered_probe_usrs:
            continue
        if call["callee_in_source"] or call["control_depth"]:
            continue
        for index in policy["handler_args"]:
            if index >= len(call["argument_functions"]):
                continue
            functions = call["argument_functions"][index]
            if len(functions) != 1:
                continue
            function = functions[0]
            routes.append({
                "callback": "irq_handler.handler",
                "target_usr": function["usr"],
                "target": function["name"],
                "binding": {"kind": "call_argument", "call": call["callee"],
                            "argument": index, "location": call["location"],
                            "signature_matches": True},
                "registration": {
                    "kind": "direct_irq", "function_usr": call["function_usr"],
                    "registration_offset": call["location"]["offset"],
                    "chain": [{"kind": "registered_probe",
                               "function_usr": call["function_usr"]},
                              {"kind": "registration_call",
                               "call": call["callee"],
                               "location": call["location"]}],
                },
                "runtime_entry_registered": True,
            })

    unique_routes: dict[tuple, dict] = {}
    for route in routes:
        key = (
            route.get("callback"), route.get("target_usr"),
            _path_key((route.get("binding") or {}).get("owner")),
            (route.get("registration") or {}).get("kind"),
        )
        unique_routes.setdefault(key, route)
    routes = list(unique_routes.values())
    for route in routes:
        route["route_id"] = registration_route_fingerprint(route)
    return routes, errors


def _runtime_identity_contract(
        ast: dict, routes: list[dict], runtime_identity: Mapping[str, Any] | None
        ) -> tuple[list[str], list[dict[str, Any]]]:
    """Compare manifest runtime identity with the registered root object."""
    if not isinstance(runtime_identity, Mapping):
        return [], []
    declared = runtime_identity.get("registration")
    if isinstance(declared, Mapping):
        root_table = declared.get("root_table")
        identity_field = declared.get("identity_field", "driver_name")
        device_id_tables = declared.get("device_id_tables", [])
        if (not isinstance(root_table, str)
                or not isinstance(identity_field, str)
                or not isinstance(device_id_tables, list)):
            return [], []
    else:
        # Compatibility for schema-2 manifests written before registration
        # contracts became profile-owned data.
        bus = runtime_identity.get("bus")
        legacy_contracts = resolve_linux_registration_policy().get(
            "legacy_runtime_contracts", {})
        legacy = (legacy_contracts.get(bus)
                  if isinstance(bus, str)
                  and isinstance(legacy_contracts, Mapping) else None)
        if not isinstance(legacy, Mapping):
            return [], []
        root_table = legacy.get("root_table")
        identity_field = legacy.get("identity_field", "driver_name")
        device_id_tables = legacy.get("device_id_tables", [])
    if identity_field == "none":
        return [], []
    expected_name = runtime_identity.get(identity_field)
    identity_error = ("registrar_name" if identity_field == "registrar"
                      else "driver_name")
    if not isinstance(expected_name, str) or not expected_name:
        return [], []

    root_usrs = {
        (route.get("registration") or {}).get("object", {}).get("root_usr")
        for route in routes
        if route.get("callback") == f"{root_table}.probe"
        and (route.get("registration") or {}).get("kind") == "driver_root"
    }
    observed = [
        dict(item) for item in ast.get("identity_bindings", [])
        if item.get("table") == root_table
        and item.get("owner", {}).get("root_usr") in root_usrs
    ]
    errors: list[str] = []
    names = sorted({item.get("value") for item in observed
                    if isinstance(item.get("value"), str)})
    if not names:
        errors.append(f"{identity_error}_missing")
    elif expected_name not in names:
        errors.append(f"{identity_error}_mismatch")
    for id_table in device_id_tables:
        if not isinstance(id_table, str) or not id_table:
            continue
        id_names = sorted({item.get("value") for item in ast.get(
            "identity_bindings", [])
            if item.get("table") == id_table
            and isinstance(item.get("value"), str)})
        if not id_names:
            errors.append(f"{id_table.removesuffix('_device_id')}_id_name_missing")
        elif expected_name not in id_names:
            errors.append(f"{id_table.removesuffix('_device_id')}_id_name_mismatch")
    return errors, observed


def verify_linux_registration_ast(
        contract: dict, device_spec: Any,
        generated: str | Path | list[str | Path] | tuple[str | Path, ...],
        lowering_plan: dict, *, kbuild_cmd: str | Path,
        clang_library: str | None = None,
        runtime_identity: Mapping[str, Any] | None = None) -> dict:
    if isinstance(generated, (str, Path)):
        sources = [Path(generated).resolve()]
    elif isinstance(generated, (list, tuple)):
        sources = [Path(item).resolve() for item in generated]
    else:
        raise TypeError("generated must be a source path or a list of source paths")
    if not sources:
        raise ValueError("generated source list must not be empty")
    command_file = Path(kbuild_cmd).resolve()
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "generated C source does not exist: " + ", ".join(missing))
    if not command_file.is_file():
        raise FileNotFoundError(f"Kbuild command file does not exist: {command_file}")
    if contract.get("driver") != device_spec.name:
        raise ValueError("contract and DeviceSpec driver identities differ")
    if lowering_plan.get("driver") != contract.get("driver"):
        raise ValueError("lowering plan driver identity differs from contract")
    if lowering_plan.get("backend") != "linux":
        raise ValueError("registration oracle requires a Linux lowering plan")
    if (lowering_plan.get("schema") != 3
            or lowering_plan.get("oracle") != "backend-lowering-plan-v3"):
        raise ValueError(
            "registration oracle requires backend-lowering-plan-v3")

    declared_registration = (
        runtime_identity.get("registration")
        if isinstance(runtime_identity, Mapping) else None)
    registration_policy_errors: list[str] = []
    try:
        registration_policy = resolve_linux_registration_policy(
            declared_registration)
    except LinuxRegistrationContractError as exc:
        registration_policy_errors.append(str(exc))
        registration_policy = {
            "root_tables": frozenset(),
            "device_id_tables": frozenset(),
            "supported_callback_tables": frozenset(),
            "struct_tables": {},
            "registration_apis": {},
            "link_tables": {},
            "irq_attach_apis": {},
            "direct_irq_apis": {},
        }

    contexts: list[dict] = []
    ast = {
        "diagnostics": [], "definitions": {}, "anchors": [],
        "bindings": [], "identity_bindings": [], "pointer_edges": [],
        "call_results": [],
        "calls": [], "module_init_targets": [],
    }
    for source in sources:
        clang_args, context = linux_kbuild_compile_context(source, command_file)
        contexts.append(context)
        part = _collect_ast(
            source, clang_args, clang_library, registration_policy)
        ast["diagnostics"].extend(part["diagnostics"])
        ast["definitions"].update(part["definitions"])
        for field in ("anchors", "bindings", "identity_bindings", "pointer_edges",
                      "call_results", "calls"):
            ast[field].extend(part[field])
        ast["module_init_targets"].extend(part["module_init_targets"])
    ast["module_init_targets"] = sorted(set(ast["module_init_targets"]))
    context = contexts[0]
    parse_errors = [item for item in ast["diagnostics"]
                    if item["severity"] >= 3]
    routes, route_errors = _registered_routes(
        ast, sources[0], registration_policy)
    runtime_identity_errors, runtime_identity_observed = (
        _runtime_identity_contract(ast, routes, runtime_identity))
    route_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for route in routes:
        route_index[(route["callback"], route["target_usr"])].append(route)

    anchor_counts = Counter(item["op_id"] for item in ast["anchors"])
    anchor_by_id = {
        item["op_id"]: item for item in ast["anchors"]
        if anchor_counts[item["op_id"]] == 1
    }
    contract_rows = contract.get("register_operations")
    if not isinstance(contract_rows, list):
        raise ValueError("generation contract has no register_operations list")
    contract_counts = Counter(
        row.get("op_id") for row in contract_rows if isinstance(row, dict))
    if (any(not isinstance(op_id, str) or not op_id or count != 1
            for op_id, count in contract_counts.items())
            or len(contract_counts) != len(contract_rows)):
        raise ValueError(
            "generation contract operation IDs must be unique and nonempty")
    contract_by_id = {row.get("op_id"): row for row in contract_rows
                      if isinstance(row.get("op_id"), str)}
    plan_entries = lowering_plan.get("entries")
    if not isinstance(plan_entries, list):
        raise ValueError("lowering plan has no entries list")
    plan_counts = Counter(
        entry.get("op_id") for entry in plan_entries
        if isinstance(entry, dict))
    if (any(not isinstance(op_id, str) or not op_id or count != 1
            for op_id, count in plan_counts.items())
            or len(plan_counts) != len(plan_entries)):
        raise ValueError(
            "lowering plan operation IDs must be unique and nonempty")
    for entry in plan_entries:
        strict_eligible = entry.get("strict_eligible")
        if type(strict_eligible) is not bool:
            raise ValueError(
                "lowering plan strict eligibility must be boolean")
        if (strict_eligible
                and entry.get("disposition") != "candidate_definition_emit"):
            raise ValueError(
                "only candidate_definition_emit operations may be strict")
    plan_by_id = {entry.get("op_id"): entry for entry in plan_entries
                  if isinstance(entry.get("op_id"), str)}
    routes_by_module = _device_routes(device_spec)

    operation_rows = []
    proven_ids = []
    for op_id in sorted(contract_by_id):
        contract_row = contract_by_id[op_id]
        plan_entry = plan_by_id.get(op_id) or {}
        strict_eligible = plan_entry.get("strict_eligible") is True
        module = contract_row.get("module")
        # For verified call closure the contract operation remains owned by
        # its helper module, while its unique AST anchor is emitted in the
        # registered root callback named by the lowering-plan route.  Ordinary
        # entries retain the independent DeviceSpec callback authority.
        plan_route = plan_entry.get("route") or {}
        authority = (plan_route
                     if plan_route.get("kind") == "verified_call_closure"
                     else routes_by_module.get(module) or {})
        expected_callback = authority.get("callback")
        expected_function = authority.get("function")
        anchor = anchor_by_id.get(op_id)
        actual_function = anchor.get("function") if anchor else None
        expected_registered_functions = sorted({
            route.get("target") for route in routes
            if route.get("callback") == expected_callback
            and isinstance(route.get("target"), str)
        }) if expected_callback else []
        matching = []
        errors = []
        if strict_eligible:
            if expected_callback is None:
                errors.append("lowering plan route has no callback owner")
            if expected_callback and expected_callback.split(".", 1)[0] not in \
                    registration_policy["supported_callback_tables"]:
                errors.append("unsupported_registration_shape")
            if anchor is None:
                errors.append("missing unique operation AST anchor")
            elif not anchor["direct_compound"]:
                errors.append("operation AST anchor has no direct compound")
            if (expected_registered_functions and actual_function
                    and actual_function not in expected_registered_functions):
                errors.append("operation_callback_ownership_mismatch")
            if anchor and expected_callback:
                matching = route_index.get(
                    (expected_callback, anchor["function_usr"]), [])
                if not matching:
                    errors.append("no exact registered callback route")
                elif len(matching) != 1:
                    errors.append("ambiguous registered callback route")
        proven = bool(strict_eligible and not errors and len(matching) == 1)
        if proven:
            proven_ids.append(op_id)
        operation_rows.append({
            "op_id": op_id,
            "module": module,
            "strict_eligible": strict_eligible,
            "expected_callback": expected_callback,
            "expected_function": expected_function,
            "expected_registered_functions": expected_registered_functions,
            "actual_function": actual_function,
            "anchor": anchor,
            "route": matching[0] if len(matching) == 1 else None,
            "runtime_registration_proven": proven,
            "errors": errors,
        })

    strict_ids = sorted(entry["op_id"] for entry in plan_entries
                        if entry.get("strict_eligible") is True
                        and isinstance(entry.get("op_id"), str))
    missing_plan_ids = sorted(set(contract_by_id) - set(plan_by_id))
    unknown_plan_ids = sorted(set(plan_by_id) - set(contract_by_id))
    duplicate_anchors = sorted(op_id for op_id, count in anchor_counts.items()
                               if count != 1)
    complete = not any((
        parse_errors, route_errors, missing_plan_ids, unknown_plan_ids,
        duplicate_anchors, set(strict_ids) - set(proven_ids),
        runtime_identity_errors, registration_policy_errors,
    ))
    # The generated artifact hash is content authority.  Do not include the
    # workspace path: the C AST oracle and backend authority use the same
    # content hash, and paths are intentionally unstable across staging roots.
    generated_bytes = b"".join(source.read_bytes() for source in sources)
    generated_value: str | list[str] = (
        str(sources[0]) if len(sources) == 1
        else [str(source) for source in sources])
    report = {
        "schema": SCHEMA,
        "oracle": ORACLE,
        "driver": contract.get("driver"),
        "complete": complete,
        "claim_scope": {
            "proves": [
                "exact_kbuild_parse_context",
                "unique_operation_anchor_to_generated_function",
                "callback_field_and_signature_identity",
                "framework_object_identity",
                "straight_line_assignment_before_registration",
                "module_or_object_root_registration",
                "straight_line_gpio_and_irq_registration",
                "runtime_named_identity_when_requested",
                "misc_file_operations_registration",
                "typed_pm_and_static_clock_object_graph",
                "sdhci_pdata_init_add_host_identity",
                "single_instance_usb_hcd_create_add_remove_put",
                "single_instance_usb_gadget_ep0_add_delete",
            ],
            "does_not_prove": [
                "callback_invocation_by_the_kernel",
                "guard_or_path_semantics_inside_callback",
                "banked_or_aliasing_object_dataflow",
                "clock_match_data_fanout",
                "sdhci_wrapper_or_path_dependent_pdata",
                "multi_instance_or_mode_split_usb_lifecycle",
            ],
        },
        "generated": generated_value,
        "generated_sha256": hashlib.sha256(generated_bytes).hexdigest(),
        "contract_driver": contract.get("driver"),
        "device_spec_driver": device_spec.name,
        "compile_context": context,
        "compile_contexts": contexts,
        "diagnostics": ast["diagnostics"],
        "parse_errors": parse_errors,
        "definitions": sorted(ast["definitions"].values(),
                              key=lambda item: item["name"]),
        "anchors": ast["anchors"],
        "bindings": ast["bindings"],
        "identity_bindings": ast["identity_bindings"],
        "pointer_edges": ast["pointer_edges"],
        "call_results": ast["call_results"],
        "calls": ast["calls"],
        "module_init_targets": ast["module_init_targets"],
        "registration_routes": routes,
        "route_errors": route_errors,
        "runtime_identity_requested": (
            dict(runtime_identity) if isinstance(runtime_identity, Mapping)
            else None),
        "runtime_identity_errors": runtime_identity_errors,
        "runtime_identity_observed": runtime_identity_observed,
        "registration_policy_errors": registration_policy_errors,
        "operations": operation_rows,
        "strict_eligible_ops": len(strict_ids),
        "runtime_registered_ops": len(proven_ids),
        "runtime_registered_op_ids": sorted(proven_ids),
        "runtime_unregistered_op_ids": sorted(set(strict_ids) - set(proven_ids)),
        "missing_plan_ids": missing_plan_ids,
        "unknown_plan_ids": unknown_plan_ids,
        "duplicate_anchors": duplicate_anchors,
    }
    return report


def _write_report(report: dict, output: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Linux generated-C callback registration by AST")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--device-spec-json", required=True)
    parser.add_argument("--lowering-plan", required=True)
    parser.add_argument("--generated", required=True)
    parser.add_argument("--kbuild-cmd", required=True)
    parser.add_argument("--clang-library")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        device_spec = device_spec_from_dict(json.loads(
            Path(args.device_spec_json).read_text(encoding="utf-8")))
        plan = json.loads(Path(args.lowering_plan).read_text(encoding="utf-8"))
        report = verify_linux_registration_ast(
            contract, device_spec, args.generated, plan,
            kbuild_cmd=args.kbuild_cmd, clang_library=args.clang_library)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "oracle": ORACLE,
            "complete": False,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
        }
        _write_report(report, args.output)
        return 3
    _write_report(report, args.output)
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
