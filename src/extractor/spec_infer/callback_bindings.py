"""AST-proven callback ownership: initializers, assignments, call arguments."""
from __future__ import annotations
import os
import clang.cindex as _cx

from ..ast_model import Func, function_symbol_id
from .callback_tables import (
    _CALLBACK_TYPE_ROLES, _ROLE_BEARING_CALLBACK_TYPES,
    _callback_field_role, _function_pointer_signature,
    _is_function_pointer, _named_callback_type, _record_declaration,
    _record_type_name,
)


def _target_function_refs(cursor, targets: dict[str, Func]) -> list[str]:
    found: list[str] = []
    for node in cursor.walk_preorder():
        ref = node.referenced
        symbol = function_symbol_id(ref)
        if symbol in targets and symbol not in found:
            found.append(symbol)
    return found


def _walk_preorder(cursor, target_files: set[str] | None = None):
    """Walk AST nodes, optionally pruning declarations outside target files.

    References from a target-file expression still resolve to declarations in
    included headers, so the scoped walk retains type/field provenance while
    avoiding a second traversal of every unrelated kernel header declaration.
    """
    if target_files:
        location = cursor.location
        file_cursor = location.file if location is not None else None
        if file_cursor is not None and os.path.abspath(file_cursor.name) not in target_files:
            return
    yield cursor
    for child in cursor.get_children():
        yield from _walk_preorder(child, target_files)


def _function_pointer_fields(cursor) -> list[object]:
    found = []
    seen: set[str] = set()
    for node in cursor.walk_preorder():
        ref = node.referenced
        if (ref is None or ref.kind != _cx.CursorKind.FIELD_DECL
                or not _is_function_pointer(ref.type)):
            continue
        key = ref.get_usr() or f"{_record_type_name(ref)}.{ref.spelling}"
        if key not in seen:
            found.append(ref)
            seen.add(key)
    return found


def _designated_fields(cursor) -> list[object]:
    """Return field declarations named by designated initializer/member refs."""
    found = []
    seen: set[str] = set()
    for node in cursor.walk_preorder():
        if node.kind not in {_cx.CursorKind.MEMBER_REF,
                             _cx.CursorKind.DECL_REF_EXPR}:
            continue
        ref = node.referenced
        if ref is None or ref.kind != _cx.CursorKind.FIELD_DECL:
            continue
        key = ref.get_usr() or f"{_record_type_name(ref)}.{ref.spelling}"
        if key not in seen:
            found.append(ref)
            seen.add(key)
    return found


def _public_field_transfer_roles(tu, target_files: set[str] | None = None
                                 ) -> dict[tuple[str, str], tuple[str, str, str]]:
    """Infer private-field roles from assignments into public callback fields."""
    roles: dict[tuple[str, str], tuple[str, str, str]] = {}
    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind != _cx.CursorKind.BINARY_OPERATOR:
            continue
        tokens = [token.spelling for token in cursor.get_tokens()]
        if "=" not in tokens:
            continue
        children = list(cursor.get_children())
        if len(children) != 2:
            continue
        left_fields = _function_pointer_fields(children[0])
        right_fields = _function_pointer_fields(children[1])
        if not left_fields or not right_fields:
            continue
        for left in left_fields:
            owner = _record_type_name(left)
            if owner not in _ROLE_BEARING_CALLBACK_TYPES:
                continue
            role, context = _callback_field_role(owner, left.spelling)
            if role == "unknown":
                continue
            for right in right_fields:
                right_owner = _record_type_name(right)
                if right_owner and right.spelling:
                    roles.setdefault(
                        (right_owner, right.spelling),
                        (role, context, f"{owner}.{left.spelling}"))
    return roles


def _binding_info(func: Func, field_cursor, kind: str, evidence_cursor,
                  *, table: str | None = None) -> dict | None:
    field = field_cursor.spelling
    owner = table or _record_type_name(field_cursor)
    if not field or not owner:
        return None
    role, context = (
        _callback_field_role(owner, field)
        if owner in _ROLE_BEARING_CALLBACK_TYPES
        else ("unknown", "thread"))
    loc = evidence_cursor.location
    info = {
        "function": func.name,
        "field": field,
        "table": owner,
        "role": role,
        "context": context,
        "binding_kind": kind,
        "public_callback_type": owner in _ROLE_BEARING_CALLBACK_TYPES,
        "source": loc.file.name if loc and loc.file else func.source_path,
        "line": loc.line if loc else func.line,
        "column": loc.column if loc else 0,
    }
    signature = _function_pointer_signature(getattr(field_cursor, "type", None))
    if signature is not None:
        info["signature"] = signature
    return info


def infer_callback_bindings(
        tu, funcs: list[Func], *, target_files: set[str] | None = None
        ) -> dict[str, dict]:
    """Recover typed callback ownership from the AST.

    Bindings are accepted only when libclang proves a function flows into a
    function-pointer struct field (initializer or assignment), or into a named
    callback-typed call parameter.  Function names, driver names, compatible
    strings, Kconfig symbols, and source-private prefixes are not consulted.
    Unknown fields remain role ``unknown`` while retaining owner/field binding.
    """
    targets = {func.symbol_id or func.name: func for func in funcs}
    grouped: dict[str, list[dict]] = {}

    def record(symbol: str, field_cursor, kind: str, evidence_cursor,
               table: str | None = None):
        info = _binding_info(
            targets[symbol], field_cursor, kind, evidence_cursor, table=table)
        if info is None:
            return
        entries = grouped.setdefault(symbol, [])
        identity = (info["table"], info["field"], info["binding_kind"],
                    info["source"], info["line"], info["column"])
        if not any((item["table"], item["field"], item["binding_kind"],
                    item["source"], item["line"], item["column"]) == identity
                   for item in entries):
            entries.append(info)

    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind == _cx.CursorKind.VAR_DECL:
            initializers = [node for node in cursor.get_children()
                            if node.kind == _cx.CursorKind.INIT_LIST_EXPR]
            for initializer in initializers:
                expressions = list(initializer.get_children())
                has_designators = any(
                    _function_pointer_fields(expr) for expr in expressions)
                for expr in expressions:
                    fields = _function_pointer_fields(expr)
                    symbols = _target_function_refs(expr, targets)
                    if len(fields) == 1 and len(symbols) == 1:
                        record(symbols[0], fields[0], "initializer", expr)
                    elif len(symbols) == 1:
                        designated = []
                        for child in expr.get_children():
                            child_symbols = _target_function_refs(child, targets)
                            child_fields = _designated_fields(child)
                            if (len(child_symbols) == 1
                                    and child_symbols[0] == symbols[0]
                                    and len(child_fields) == 1):
                                designated.append(child_fields[0])
                        if not designated:
                            designated = [field for field in
                                          _designated_fields(expr)
                                          if field.spelling == "data"]
                        if len(designated) == 1:
                            kind = ("data_initializer"
                                    if designated[0].spelling == "data"
                                    else "initializer")
                            record(symbols[0], designated[0], kind, expr)
                if has_designators:
                    continue
                declaration = _record_declaration(initializer.type)
                if declaration is None:
                    continue
                fields = [node for node in declaration.get_children()
                          if node.kind == _cx.CursorKind.FIELD_DECL]
                record_initializers = (
                    [expr for expr in expressions
                     if expr.kind == _cx.CursorKind.INIT_LIST_EXPR]
                    if initializer.type.get_canonical().kind in {
                        _cx.TypeKind.CONSTANTARRAY,
                        _cx.TypeKind.INCOMPLETEARRAY,
                        _cx.TypeKind.VARIABLEARRAY,
                        _cx.TypeKind.DEPENDENTSIZEDARRAY}
                    else [initializer])
                for record_initializer in record_initializers:
                    values = list(record_initializer.get_children())
                    for field_cursor, expr in zip(fields, values):
                        symbols = _target_function_refs(expr, targets)
                        if (_is_function_pointer(field_cursor.type)
                                and len(symbols) == 1):
                            record(symbols[0], field_cursor,
                                   "positional_initializer", expr)

        elif cursor.kind == _cx.CursorKind.BINARY_OPERATOR:
            tokens = [token.spelling for token in cursor.get_tokens()]
            if "=" not in tokens:
                continue
            children = list(cursor.get_children())
            if len(children) != 2:
                continue
            fields = _function_pointer_fields(children[0])
            symbols = _target_function_refs(children[1], targets)
            if len(fields) == 1 and len(symbols) == 1:
                record(symbols[0], fields[0], "assignment", cursor)

        elif cursor.kind == _cx.CursorKind.CALL_EXPR:
            callee = cursor.referenced
            if callee is None or callee.kind != _cx.CursorKind.FUNCTION_DECL:
                continue
            params = [node for node in callee.get_children()
                      if node.kind == _cx.CursorKind.PARM_DECL]
            args = list(cursor.get_arguments())
            for param, arg in zip(params, args):
                if not _is_function_pointer(param.type):
                    continue
                callback_type = _named_callback_type(param.type)
                symbols = _target_function_refs(arg, targets)
                if len(symbols) != 1:
                    continue
                if not callback_type:
                    candidate_fields = []
                    for owner_param in params:
                        declaration = _record_declaration(owner_param.type)
                        if declaration is None:
                            continue
                        for field_cursor in declaration.get_children():
                            if (field_cursor.kind == _cx.CursorKind.FIELD_DECL
                                    and field_cursor.spelling == param.spelling
                                    and _is_function_pointer(field_cursor.type)):
                                candidate_fields.append(field_cursor)
                    if len(candidate_fields) == 1:
                        record(symbols[0], candidate_fields[0],
                               "call_assignment", arg)
                    continue
                role, context = _CALLBACK_TYPE_ROLES.get(
                    callback_type, ("unknown", "thread"))
                field = param.spelling or "callback"
                synthetic_field = type("CallbackField", (), {
                    "spelling": field,
                    "semantic_parent": None,
                    "lexical_parent": None,
                })()
                info = _binding_info(
                    targets[symbols[0]], synthetic_field, "call_argument",
                    arg, table=callback_type.removesuffix("_t"))
                if info is not None:
                    info["role"], info["context"] = role, context
                    grouped.setdefault(symbols[0], []).append(info)

    # A private callback field can be dispatched from a public callback.  The
    # dispatcher's already-proven role is stronger evidence than the private
    # field name, and remains valid when the field owner is source-private.
    role_by_symbol: dict[str, tuple[str, str]] = {}
    for symbol, entries in grouped.items():
        for info in entries:
            role = info.get("role", "unknown")
            if role != "unknown":
                role_by_symbol[symbol] = (role, info.get("context", "thread"))
                break
    field_dispatch_roles: dict[tuple[str, str], tuple[str, str, str]] = \
        _public_field_transfer_roles(tu, target_files=target_files)
    for cursor in _walk_preorder(tu.cursor, scoped_files):
        if cursor.kind != _cx.CursorKind.FUNCTION_DECL:
            continue
        dispatcher = function_symbol_id(cursor)
        role_info = role_by_symbol.get(dispatcher)
        if role_info is None:
            continue
        for call in cursor.walk_preorder():
            if call.kind != _cx.CursorKind.CALL_EXPR:
                continue
            for field in _function_pointer_fields(call):
                owner = _record_type_name(field)
                if owner and field.spelling:
                    field_dispatch_roles.setdefault(
                        (owner, field.spelling),
                        (role_info[0], role_info[1], dispatcher))
    for entries in grouped.values():
        for info in entries:
            if info.get("role") != "unknown":
                continue
            propagated = field_dispatch_roles.get(
                (info.get("table"), info.get("field")))
            if propagated is None:
                continue
            info["role"], info["context"], dispatcher = propagated
            info["role_evidence"] = {
                "kind": ("proven_public_field_transfer"
                          if "::" not in dispatcher and "." in dispatcher
                          else "proven_dispatcher_field"),
                "dispatcher": dispatcher,
                "field": f"{info['table']}.{info['field']}",
            }

    result: dict[str, dict] = {}
    for symbol, entries in grouped.items():
        entries.sort(key=lambda item: (
            item["role"] == "unknown",
            item["field"] != item["role"],
            item["table"], item["field"],
            item["source"], item["line"], item["column"]))
        primary = dict(entries[0])
        if len(entries) > 1:
            primary["alternates"] = entries[1:]
        result[symbol] = primary
    return result


def callback_binding_analysis(bindings: dict[str, dict], funcs: list[Func],
                              callback_entries: set[str]) -> dict:
    func_by_symbol = {func.symbol_id or func.name: func for func in funcs}
    rows = []
    for symbol, primary in bindings.items():
        for info in [primary] + primary.get("alternates", []):
            rows.append({key: info.get(key) for key in (
                "function", "table", "field", "role", "context",
                "binding_kind", "public_callback_type", "source", "line",
                "column", "signature")})
    rows.sort(key=lambda item: (
        item["function"], item["table"], item["field"], item["line"] or 0))
    bound = set(bindings)
    return {
        "bindings": rows,
        "bound_entries": sorted(
            func_by_symbol[symbol].name for symbol in callback_entries & bound
            if symbol in func_by_symbol),
        "unbound_entries": sorted(
            func_by_symbol[symbol].name for symbol in callback_entries - bound
            if symbol in func_by_symbol),
    }


def propagate_callback_dispatch_roles(
        bindings: dict[str, dict], tus,
        *, target_files: set[str] | None = None) -> dict[str, dict]:
    """Propagate proven public dispatch roles across translation units."""
    role_by_symbol: dict[str, tuple[str, str]] = {}
    for symbol, primary in bindings.items():
        for info in [primary] + primary.get("alternates", []):
            role = info.get("role", "unknown")
            if role != "unknown":
                role_by_symbol[symbol] = (role, info.get("context", "thread"))
                break
    field_dispatch_roles: dict[tuple[str, str], tuple[str, str, str]] = {}
    for tu in tus:
        field_dispatch_roles.update(
            _public_field_transfer_roles(tu, target_files=target_files))
    scoped_files = ({os.path.abspath(path) for path in target_files}
                    if target_files else None)
    for tu in tus:
        for cursor in _walk_preorder(tu.cursor, scoped_files):
            if cursor.kind != _cx.CursorKind.FUNCTION_DECL:
                continue
            dispatcher = function_symbol_id(cursor)
            role_info = role_by_symbol.get(dispatcher)
            if role_info is None:
                continue
            for call in cursor.walk_preorder():
                if call.kind != _cx.CursorKind.CALL_EXPR:
                    continue
                for field in _function_pointer_fields(call):
                    owner = _record_type_name(field)
                    if owner and field.spelling:
                        field_dispatch_roles.setdefault(
                            (owner, field.spelling),
                            (role_info[0], role_info[1], dispatcher))
    for primary in bindings.values():
        for info in [primary] + primary.get("alternates", []):
            if info.get("role") != "unknown":
                continue
            propagated = field_dispatch_roles.get(
                (info.get("table"), info.get("field")))
            if propagated is None:
                continue
            info["role"], info["context"], dispatcher = propagated
            info["role_evidence"] = {
                "kind": "proven_dispatcher_field",
                "dispatcher": dispatcher,
                "field": f"{info['table']}.{info['field']}",
            }
    return bindings
