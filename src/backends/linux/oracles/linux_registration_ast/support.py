"""Cursor, path, signature, and alias utilities for the registration AST oracle.

Pure helpers over libclang cursors and the collected object-path dicts; no
policy or verification logic lives here.  Split out of the original single
file oracle; behavior is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


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
