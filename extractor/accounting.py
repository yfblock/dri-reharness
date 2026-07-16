"""Auditable source-MMIO to RIS operation accounting.

Every recognized source MMIO primitive must either map to one or more emitted
RIS operations or carry an explicit non-emission reason. This is deliberately
separate from address precision: an unresolved address is still an accounted
operation and must never disappear silently.
"""
from __future__ import annotations

import os
import re

import clang.cindex as cx

from . import mmio
from .ast_model import function_calls
from .formal import walk_leaf_ops


def access_site_id(source: str, call) -> str:
    loc = getattr(call.cursor, "location", None)
    line = getattr(loc, "line", 0) or call.line or 0
    column = getattr(loc, "column", 0) or 0
    offset = getattr(loc, "offset", 0) or 0
    return f"{os.path.abspath(source)}:{line}:{column}:{offset}:{call.name}"


def _cursor_site_id(source: str, cursor, kind: str) -> str:
    loc = getattr(cursor, "location", None)
    return (f"{os.path.abspath(source)}:{getattr(loc, 'line', 0) or 0}:"
            f"{getattr(loc, 'column', 0) or 0}:"
            f"{getattr(loc, 'offset', 0) or 0}:{kind}")


def callsite_evidence(func, call, access_kind: str,
                      effective_name: str | None = None) -> dict:
    loc = getattr(call.cursor, "location", None)
    source = (os.path.abspath(loc.file.name)
              if loc is not None and loc.file is not None
              else os.path.abspath(func.source_path))
    access_name = effective_name or call.name
    evidence = {
        "site_id": access_site_id(source, call),
        "source": source,
        "line": getattr(loc, "line", 0) or call.line or 0,
        "column": getattr(loc, "column", 0) or 0,
        "offset": getattr(loc, "offset", 0) or 0,
        "function": func.name,
        "symbol": func.symbol_id or func.name,
        "callee": call.name,
        "ast_kind": "CALL_EXPR",
        "access_kind": access_kind,
        "width_bytes": mmio.infer_call_width(access_name, call),
        "origin": "direct",
        "access_domain": mmio.access_domain(access_name),
    }
    summary = mmio.summary_kind(access_name)
    if summary:
        evidence["origin"] = "subsystem_summary"
        evidence["subsystem_summary"] = summary
        evidence["effective_callee"] = access_name
    return evidence


def _is_volatile_lvalue(cursor) -> bool:
    try:
        return bool(cursor.type.is_volatile_qualified())
    except Exception:
        return "volatile" in (cursor.type.spelling if cursor.type else "")


_ASSIGNMENT = re.compile(r"^\s*(.+?)\s*(=|\+=|-=|\|=|&=|\^=|<<=|>>=)\s*(?!=)", re.S)


def _volatile_access_kind(cursor, ancestors, tu) -> str:
    """Classify a volatile dereference as a read or write conservatively."""
    from .ast_model import source_text

    expression = source_text(tu, cursor).strip()
    for parent in reversed(ancestors):
        if parent.kind != cx.CursorKind.BINARY_OPERATOR:
            continue
        match = _ASSIGNMENT.match(source_text(tu, parent).strip())
        if match and match.group(1).strip().strip("()") == expression.strip("()"):
            return "write"
    # Increment/decrement and other compound unary uses both read and write;
    # marking them as an opaque RMW is safer than claiming a pure read.
    for parent in reversed(ancestors[-2:]):
        text = source_text(tu, parent)
        if "++" in text or "--" in text:
            return "rmw"
    return "read"


def _discover_opaque_accesses(func) -> list[dict]:
    """Find register-like operations outside recognized API calls.

    Direct volatile dereferences and inline assembly are intentionally not
    lowered yet.  They must still appear in accounting, otherwise a driver can
    receive a false strict-complete result while silently losing hardware
    effects.
    """
    from .ast_model import source_text

    sites: list[dict] = []
    tu = func.cursor.translation_unit

    def visit(cursor, ancestors):
        loc = getattr(cursor, "location", None)
        source = (os.path.abspath(loc.file.name)
                  if loc is not None and loc.file is not None
                  else os.path.abspath(func.source_path))
        if (cursor.kind == cx.CursorKind.UNARY_OPERATOR
                and source_text(tu, cursor).lstrip().startswith("*")
                and _is_volatile_lvalue(cursor)):
            access_kind = _volatile_access_kind(cursor, ancestors, tu)
            kind = f"direct_volatile_{access_kind}"
            sites.append({
                "site_id": _cursor_site_id(source, cursor, kind),
                "source": source,
                "line": getattr(loc, "line", 0) or 0,
                "column": getattr(loc, "column", 0) or 0,
                "offset": getattr(loc, "offset", 0) or 0,
                "function": func.name,
                "symbol": func.symbol_id or func.name,
                "callee": None,
                "ast_kind": cursor.kind.name,
                "access_kind": access_kind,
                "width_bytes": max(1, int(cursor.type.get_size() or 0)),
                "origin": "direct_volatile",
                "access_domain": "direct_volatile",
                "status": "unsupported",
                "reason": "direct volatile dereference lacks RIS lowering",
                "ris_ops": [],
                "source_text": source_text(tu, cursor).strip(),
            })
        elif (cursor.kind in {cx.CursorKind.ASM_STMT, cx.CursorKind.MS_ASM_STMT}
              and re.search(r"\b(?:__asm__|asm)\b", source_text(tu, cursor))):
            kind = "inline_asm"
            sites.append({
                "site_id": _cursor_site_id(source, cursor, kind),
                "source": source,
                "line": getattr(loc, "line", 0) or 0,
                "column": getattr(loc, "column", 0) or 0,
                "offset": getattr(loc, "offset", 0) or 0,
                "function": func.name,
                "symbol": func.symbol_id or func.name,
                "callee": None,
                "ast_kind": cursor.kind.name,
                "access_kind": "opaque",
                "width_bytes": 0,
                "origin": "inline_asm",
                "access_domain": "inline_asm",
                "status": "unsupported",
                "reason": "inline assembly has unmodeled hardware side effects",
                "ris_ops": [],
                "source_text": source_text(tu, cursor).strip(),
            })
        for child in cursor.get_children():
            visit(child, ancestors + [cursor])

    visit(func.cursor, [])
    return sites


def discover_source_accesses(funcs, extra_blacklist: set[str] | None = None
                             ) -> list[dict]:
    blacklist = extra_blacklist or set()
    sites: list[dict] = []
    seen: set[str] = set()
    for func in funcs:
        for call in function_calls(func.cursor):
            access_name = mmio.effective_access_name(
                call.name, call.callee_text)
            if mmio.is_mmio_read(access_name):
                kind = "read"
            elif mmio.is_mmio_write(access_name):
                kind = "write"
            elif mmio.is_mmio_rmw(access_name):
                kind = "rmw"
            elif mmio.is_unsupported_register_access(access_name):
                kind = "unsupported"
            elif mmio.is_library_summary_call(access_name):
                kind = "summary"
            else:
                continue
            evidence = callsite_evidence(
                func, call, kind, effective_name=access_name)
            site_id = evidence["site_id"]
            if site_id in seen:
                continue
            seen.add(site_id)
            evidence.update({
                "status": ("filtered" if call.name in blacklist else
                           "unsupported" if kind == "unsupported" else "pending"),
                "reason": ("explicit extractor blacklist"
                           if call.name in blacklist else
                           "recognized register API lacks scalar RIS model"
                           if kind == "unsupported" else None),
                "ris_ops": [],
            })
            sites.append(evidence)
        for evidence in _discover_opaque_accesses(func):
            site_id = evidence["site_id"]
            if site_id in seen:
                continue
            seen.add(site_id)
            sites.append(evidence)
    return sorted(sites, key=lambda site: (
        site["source"], site["line"], site["column"], site["offset"]))


def build_access_accounting(funcs, formal: dict,
                            extra_blacklist: set[str] | None = None) -> dict:
    sites = discover_source_accesses(funcs, extra_blacklist)
    emitted: dict[str, list[str]] = {}
    ops_without_evidence: list[str] = []
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("Read") or op.get("Write")
                    or op.get("ReadModifyWrite"))
            if body is None:
                continue
            op_id = body.get("op_id", "")
            evidence = body.get("evidence") or {}
            site_id = evidence.get("site_id")
            if not site_id:
                ops_without_evidence.append(op_id or f"{module['name']}:?")
                continue
            emitted.setdefault(site_id, []).append(op_id)

    for site in sites:
        op_ids = emitted.get(site["site_id"], [])
        if op_ids:
            site["status"] = "emitted"
            site["reason"] = None
            site["ris_ops"] = sorted(set(op_ids))
        elif site["status"] == "pending":
            site["status"] = "unaccounted"
            site["reason"] = "recognized source MMIO call produced no RIS op"

    counts = {
        "source_accesses": len(sites),
        "emitted": sum(site["status"] == "emitted" for site in sites),
        "filtered": sum(site["status"] == "filtered" for site in sites),
        "unsupported": sum(site["status"] == "unsupported" for site in sites),
        "unaccounted": sum(site["status"] == "unaccounted" for site in sites),
        "ris_ops_without_evidence": len(ops_without_evidence),
    }
    complete = (counts["unaccounted"] == 0
                and counts["ris_ops_without_evidence"] == 0)
    return {
        **counts,
        "complete": complete,
        "strict_complete": complete and counts["filtered"] == 0
                           and counts["unsupported"] == 0,
        "sites": sites,
        "ops_without_evidence": ops_without_evidence,
    }
