"""Function-identity helpers and cursor-parent/return-binding queries."""
from __future__ import annotations

from ast_analyzer import Func, source_text
from ..indirect import resolve_indirect_call


def _func_id(func: Func) -> str:
    return func.symbol_id or func.name


def _callee_id(call) -> str:
    return call.symbol_id or call.name


def _resolved_callee_id(call, indirect_targets: dict[str, str]) -> str:
    return resolve_indirect_call(call, indirect_targets) or _callee_id(call)


def _cursor_parents(root) -> dict[int, object]:
    parents: dict[int, object] = {}

    def visit(node) -> None:
        for child in node.get_children():
            parents[child.hash] = node
            visit(child)

    visit(root)
    return parents


def _return_binding(call_cursor, parents: dict[int, object]) -> dict:
    current = call_cursor
    while current.hash in parents:
        current = parents[current.hash]
        kind = current.kind.name
        if kind == "VAR_DECL":
            return {
                "status": "exact", "kind": "declaration_initializer",
                "destination": current.spelling,
                "destination_usr": current.get_usr() or None,
                "destination_type": current.type.get_canonical().spelling,
            }
        if kind == "BINARY_OPERATOR":
            children = list(current.get_children())
            tokens = [token.spelling for token in current.get_tokens()]
            if len(children) == 2 and tokens.count("=") == 1:
                return {
                    "status": "exact", "kind": "assignment",
                    "destination": source_text(
                        current.translation_unit, children[0]).strip(),
                    "destination_type": (
                        children[0].type.get_canonical().spelling),
                }
        if kind == "RETURN_STMT":
            return {"status": "exact", "kind": "return"}
        if kind in {"COMPOUND_STMT", "FUNCTION_DECL"}:
            break
    return {"status": "exact", "kind": "discarded"}

