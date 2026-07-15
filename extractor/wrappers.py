"""Conservative inference of simple MMIO wrapper summaries."""
from __future__ import annotations

import os
import re

import clang.cindex as cx

from . import mmio
from .accounting import callsite_evidence
from .ast_model import (Func, function_calls, function_symbol_id,
                        source_text, walk_with_control)


_MMIO_PARAM_NAMES = {
    "base", "regs", "reg_base", "mmio", "mmio_base", "ioaddr", "io_base",
}


def _address_has_mmio_provenance(func: Func, address: str) -> bool:
    """Require conservative type/name evidence for a wrapper address.

    A cast to ``__iomem`` at the primitive is not sufficient: Linux also uses
    raw reads as ordering barriers over ordinary DMA memory.  Accept explicit
    iomem parameters, conventional MMIO-base parameters, and aggregate base
    fields; reject an otherwise generic ``void *addr``.
    """
    compact = re.sub(r"\s+", "", address or "")
    params = {name: ctype for name, ctype in func.params if name}
    for name, ctype in params.items():
        if not re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                address or ""):
            continue
        if "__iomem" in ctype or name.lower() in _MMIO_PARAM_NAMES:
            return True
        if re.search(
                rf"\b{re.escape(name)}(?:->|\.).*"
                rf"(?:base|regs|reg_base|mmio|mmio_base|ioaddr|io_base)\b",
                compact):
            return True
    # A wrapper over a file-scope MMIO object may have no address parameter.
    return not any(re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
        address or "") for name in params)


def _func_from_cursor(cursor) -> Func | None:
    if (cursor is None or cursor.kind != cx.CursorKind.FUNCTION_DECL
            or not cursor.is_definition()):
        return None
    params = []
    for child in cursor.get_children():
        if child.kind == cx.CursorKind.PARM_DECL:
            params.append((child.spelling, child.type.spelling if child.type else ""))
    loc = cursor.location
    source = os.path.abspath(loc.file.name) if loc and loc.file else ""
    return Func(
        name=cursor.spelling, line=loc.line if loc else 0, cursor=cursor,
        params=params, source_path=source,
        symbol_id=function_symbol_id(cursor), module_name=cursor.spelling,
        is_static=cursor.storage_class == cx.StorageClass.STATIC)


def _candidate_functions(funcs: list[Func]) -> list[Func]:
    candidates = list(funcs)
    seen = {func.symbol_id or func.name for func in candidates}
    for caller in funcs:
        for call in function_calls(caller.cursor):
            ref = call.cursor.referenced
            candidate = _func_from_cursor(ref)
            if candidate is None:
                continue
            symbol = candidate.symbol_id or candidate.name
            if symbol in seen:
                continue
            seen.add(symbol)
            candidates.append(candidate)
    return candidates


def infer_wrapper_summaries(funcs: list[Func]) -> tuple[dict[str, dict], list[Func]]:
    summaries: dict[str, dict] = {}
    candidates = _candidate_functions(funcs)
    for func in candidates:
        calls = [call for call in function_calls(func.cursor)
                 if mmio.is_mmio_read(call.name) or mmio.is_mmio_write(call.name)]
        if len(calls) != 1:
            continue
        call = calls[0]
        control = []
        for cursor, stack in walk_with_control(func.cursor):
            if cursor == call.cursor:
                control = stack
                break
        if control:
            continue
        params = [name for name, _ctype in func.params if name]
        if mmio.is_mmio_read(call.name):
            address = mmio.read_addr_expr(call.name, call.arg_text)
            if not _address_has_mmio_provenance(func, address):
                continue
            summary = {
                "kind": "Read", "width": mmio.infer_width(call.name),
                "params": params, "address": address,
                "value": None,
            }
            access_kind = "read"
        else:
            value, address = mmio.write_value_addr(call.name, call.arg_text)
            if not _address_has_mmio_provenance(func, address):
                continue
            summary = {
                "kind": "Write", "width": mmio.infer_width(call.name),
                "params": params, "address": address, "value": value,
            }
            access_kind = "write"
        summary.update({
            "function": func.name,
            "symbol": func.symbol_id or func.name,
            "source": func.source_path,
            "evidence": callsite_evidence(func, call, access_kind),
            "reliability": "Exact",
        })
        summaries[func.symbol_id or func.name] = summary
        summaries.setdefault(func.name, summary)
    return summaries, candidates
