"""Auditable boundary for control flow not represented by structured RIS."""
from __future__ import annotations

import os
import re

import clang.cindex as cx

from . import mmio
from .ast_model import continuation_guards, function_calls, source_text


def _site(func, cursor, kind: str, reason: str) -> dict:
    loc = cursor.location
    source = (os.path.abspath(loc.file.name) if loc and loc.file
              else os.path.abspath(func.source_path))
    return {
        "site_id": (f"{source}:{getattr(loc, 'line', 0) or 0}:"
                    f"{getattr(loc, 'column', 0) or 0}:"
                    f"{getattr(loc, 'offset', 0) or 0}:{kind}"),
        "source": source,
        "line": getattr(loc, "line", 0) or 0,
        "column": getattr(loc, "column", 0) or 0,
        "offset": getattr(loc, "offset", 0) or 0,
        "function": func.name,
        "symbol": func.symbol_id or func.name,
        "kind": kind,
        "status": "unsupported",
        "reason": reason,
        "source_text": source_text(func.cursor.translation_unit, cursor).strip(),
    }


def build_control_accounting(funcs) -> dict:
    sites: list[dict] = []
    modeled_returns = 0
    assumed_error_gotos = 0
    for func in funcs:
        _transitions, modeled = continuation_guards(func.cursor)
        modeled_returns += len(modeled)
        hardware_offsets = [
            getattr(call.cursor.location, "offset", 0) or 0
            for call in function_calls(func.cursor)
            if (mmio.is_mmio_read(call.name) or mmio.is_mmio_write(call.name)
                or mmio.is_mmio_rmw(call.name)
                or mmio.is_unsupported_register_access(call.name))
        ]
        params = {name for name, _ctype in func.params if name}

        def parameter_guarded_return(ancestors) -> bool:
            parent_if = next((parent for parent in reversed(ancestors)
                              if parent.kind == cx.CursorKind.IF_STMT), None)
            if parent_if is None:
                return True
            parts = list(parent_if.get_children())
            if not parts:
                return True
            condition = source_text(
                func.cursor.translation_unit, parts[0]).strip()
            if (re.search(r"->|\.|\[|\]", condition)
                    or re.search(r"\*\s*[A-Za-z_]\w*", condition)
                    or re.search(r"\b[A-Za-z_]\w*\s*\(", condition)):
                return False
            identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", condition))
            return all(name in params or name.isupper()
                       or name in {"true", "false"}
                       for name in identifiers)

        def loop_has_register_access(ancestors) -> bool:
            loop = next((parent for parent in reversed(ancestors)
                         if parent.kind in {cx.CursorKind.FOR_STMT,
                                            cx.CursorKind.WHILE_STMT,
                                            cx.CursorKind.DO_STMT}), None)
            if loop is None:
                return False
            return any(
                mmio.is_mmio_read(call.name) or mmio.is_mmio_write(call.name)
                or mmio.is_mmio_rmw(call.name)
                or mmio.is_unsupported_register_access(call.name)
                for call in function_calls(loop))

        def visit(cursor, ancestors):
            nonlocal assumed_error_gotos
            offset = getattr(cursor.location, "offset", 0) or 0
            cursor_text = source_text(
                func.cursor.translation_unit, cursor).strip()
            if cursor.kind in {cx.CursorKind.GOTO_STMT,
                               cx.CursorKind.INDIRECT_GOTO_STMT}:
                label_match = re.fullmatch(r"goto\s+([A-Za-z_]\w*)\s*;?", cursor_text)
                label = label_match.group(1) if label_match else ""
                if (not cursor_text or "scoped_guard" in cursor_text
                        or "gpio_generic_lock" in cursor_text):
                    pass
                elif re.match(
                        r"(?:err(?:or)?(?:_|$)|fail(?:_|$)|cleanup(?:_|$)|out_|disable_)",
                        label):
                    assumed_error_gotos += 1
                else:
                    sites.append(_site(
                        func, cursor, "goto",
                        "goto target/state merge is not represented by structured RIS"))
            elif cursor.kind == cx.CursorKind.CONTINUE_STMT:
                if loop_has_register_access(ancestors):
                    sites.append(_site(
                        func, cursor, "continue",
                        "loop continue requires CFG fixpoint semantics"))
            elif cursor.kind == cx.CursorKind.BREAK_STMT:
                nearest = next((parent.kind for parent in reversed(ancestors)
                                if parent.kind in {
                                    cx.CursorKind.SWITCH_STMT,
                                    cx.CursorKind.FOR_STMT,
                                    cx.CursorKind.WHILE_STMT,
                                    cx.CursorKind.DO_STMT}), None)
                if (nearest != cx.CursorKind.SWITCH_STMT
                        and loop_has_register_access(ancestors)
                        and cursor_text
                        and "scoped_guard" not in cursor_text
                        and "gpio_generic_lock" not in cursor_text):
                    sites.append(_site(
                        func, cursor, "break",
                        "loop break requires CFG fixpoint semantics"))
            elif (cursor.kind == cx.CursorKind.RETURN_STMT
                  and offset not in modeled
                  and parameter_guarded_return(ancestors)
                  and any(other > offset for other in hardware_offsets)):
                sites.append(_site(
                    func, cursor, "early_return",
                    "return affecting later register accesses is outside the simple continuation model"))
            for child in cursor.get_children():
                visit(child, ancestors + [cursor])

        visit(func.cursor, [])

    sites.sort(key=lambda site: (
        site["source"], site["line"], site["column"], site["offset"]))
    return {
        "modeled_early_returns": modeled_returns,
        "assumed_framework_error_gotos": assumed_error_gotos,
        "unsupported": len(sites),
        "complete": not sites,
        "sites": sites,
    }
