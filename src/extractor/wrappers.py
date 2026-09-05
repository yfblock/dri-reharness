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


def _control_stack(func: Func, call) -> list[dict]:
    for cursor, stack in walk_with_control(func.cursor):
        if cursor == call.cursor:
            return [dict(frame) for frame in stack]
    return []


def _normalized_template(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _substitute_template(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    names = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name)
                                               for name in names) + r")\b")

    def replace(match):
        before = text[:match.start()].rstrip()
        if before.endswith(("->", ".")):
            return match.group(0)
        return mapping.get(match.group(0), match.group(0))

    return pattern.sub(replace, text)


def _access_variant(call, summaries: dict[str, dict]) -> dict | None:
    """Return a normalized direct or already-inferred wrapper access."""
    if mmio.is_mmio_read(call.name):
        return {
            "kind": "Read",
            "width": mmio.infer_call_width(call.name, call),
            "address": mmio.read_addr_expr(call.name, call.arg_text),
            "value": None,
            "accessor": call.name,
            "summary_depth": 0,
        }
    if mmio.is_mmio_write(call.name):
        value, address = mmio.write_value_addr(call.name, call.arg_text)
        return {
            "kind": "Write",
            "width": mmio.infer_call_width(call.name, call),
            "address": address,
            "value": value,
            "accessor": call.name,
            "summary_depth": 0,
        }
    summary = (summaries.get(call.symbol_id)
               or summaries.get(call.name))
    if summary is None:
        return None
    mapping = {
        parameter: argument
        for parameter, argument in zip(summary.get("params", []), call.arg_text)
        if parameter and argument
    }
    return {
        "kind": summary["kind"],
        "width": summary["width"],
        "address": _substitute_template(summary.get("address", ""), mapping),
        "value": _substitute_template(summary.get("value", "") or "", mapping),
        "accessor": call.name,
        "summary_depth": summary.get("summary_depth", 0) + 1,
    }


_BENIGN_WRAPPER_CALLS = {
    "spinlock_check", "likely", "unlikely", "barrier", "cpu_relax",
}


def _is_benign_wrapper_call(call) -> bool:
    """Recognize calls whose framework semantics cannot hide an access."""
    name = call.name or ""
    if (mmio.is_framework(name) or mmio.is_delay(name)
            or name.startswith("__builtin_")
            or name in _BENIGN_WRAPPER_CALLS):
        return True
    # Linux lock macros often expand to _raw_* declarations while the source
    # call still names a framework primitive.
    source_name = re.match(r"\s*([A-Za-z_]\w*)\s*\(",
                           call.callee_text or "")
    return bool(source_name and (
        mmio.is_framework(source_name.group(1))
        or mmio.is_delay(source_name.group(1))))


def _function_contains_access(cursor, seen: set[int] | None = None) -> bool:
    """Conservatively detect hidden register accesses below an unknown call."""
    if cursor is None or not cursor.is_definition():
        return True
    seen = seen or set()
    key = cursor.hash
    if key in seen:
        return False
    seen.add(key)
    for call in function_calls(cursor):
        access_name = mmio.effective_access_name(
            call.name, call.callee_text)
        if (mmio.is_mmio_read(access_name)
                or mmio.is_mmio_write(access_name)
                or mmio.is_mmio_rmw(access_name)
                or mmio.is_unsupported_register_access(access_name)):
            return True
        if _is_benign_wrapper_call(call):
            continue
        if _function_contains_access(call.cursor.referenced, seen):
            return True
    return False


def _function_contains_delay(cursor, seen: set[int] | None = None) -> bool:
    """Detect timing effects that a scalar access summary cannot represent."""
    if cursor is None or not cursor.is_definition():
        return False
    seen = seen or set()
    key = cursor.hash
    if key in seen:
        return False
    seen.add(key)
    for call in function_calls(cursor):
        if mmio.is_delay(call.name):
            return True
        if _is_benign_wrapper_call(call):
            continue
        if _function_contains_delay(call.cursor.referenced, seen):
            return True
    return False


def _has_unmodeled_access(func, variants: list[tuple[object, dict]],
                           summaries: dict[str, dict],
                           inline_cache: dict[str, object] | None = None) -> bool:
    """Reject summaries that silently discard another access-bearing call."""
    modeled = {id(call) for call, _variant in variants}
    for call in function_calls(func.cursor):
        if id(call) in modeled or _is_benign_wrapper_call(call):
            continue
        if _access_variant(call, summaries) is not None:
            continue
        callee_key = call.symbol_id or call.name
        inlined = ((inline_cache or {}).get(callee_key)
                   or (inline_cache or {}).get(call.name))
        if inlined is not None and getattr(inlined, "ops", None):
            continue
        if _function_contains_access(call.cursor.referenced):
            return True
    return False


def _branch_summary(func: Func, variants: list[tuple[object, dict]]) -> dict | None:
    """Infer a summary for mutually exclusive primitive-access branches.

    A wrapper with one primitive call is handled by the exact path below.  A
    common Linux pattern selects read/write width or byte order in an if/switch
    and therefore has several primitive calls.  The shape, not the helper
    name, is the evidence that these calls form one accessor.
    """
    if len(variants) < 2:
        return None
    kinds = {variant["kind"] for _call, variant in variants}
    if len(kinds) != 1:
        return None
    controls = [_control_stack(func, call) for call, _variant in variants]
    # The control walker annotates the taken branch; an unannotated call can
    # be the syntactic else/default arm.  At least one annotated arm plus a
    # single shared access template is sufficient evidence for that shape.
    if not any(controls):
        return None

    params = [name for name, _ctype in func.params if name]
    addresses = [variant["address"] for _call, variant in variants]
    if (len({_normalized_template(address) for address in addresses}) != 1
            or not _address_has_mmio_provenance(func, addresses[0])):
        return None
    widths = [variant["width"] for _call, variant in variants]
    if "Read" in kinds:
        summary = {
            "kind": "Read",
            "width": max(widths),
            "params": params,
            "address": addresses[0],
            "value": None,
        }
        access_kind = "read"
    else:
        summary = {
            "kind": "Write",
            "width": max(widths),
            "params": params,
            "address": addresses[0],
            "value": variants[0][1]["value"],
        }
        access_kind = "write"

    first = variants[0][0]
    summary.update({
        "function": func.name,
        "symbol": func.symbol_id or func.name,
        "source": func.source_path,
        "evidence": callsite_evidence(func, first, access_kind),
        "reliability": "Conservative",
        "variant_count": len(variants),
        "variant_widths": widths,
        "variant_accessors": [variant["accessor"]
                              for _call, variant in variants],
        "control_flow": "mutually_exclusive_access_branches",
        "summary_depth": max(
            variant.get("summary_depth", 0) for _call, variant in variants),
    })
    return summary


def infer_wrapper_summaries(funcs: list[Func]) -> tuple[dict[str, dict], list[Func]]:
    summaries: dict[str, dict] = {}
    candidates = _candidate_functions(funcs)
    # Repeat because an accessor may call another accessor defined in a
    # header.  The fixed point is bounded by the candidate count and remains
    # name-independent: only call shape and source-derived summaries matter.
    for _round in range(len(candidates) + 1):
        changed = False
        for func in candidates:
            symbol = func.symbol_id or func.name
            if symbol in summaries:
                continue
            variants = []
            for call in function_calls(func.cursor):
                variant = _access_variant(call, summaries)
                if variant is not None:
                    variants.append((call, variant))
            if not variants:
                continue
            if _has_unmodeled_access(func, variants, summaries):
                continue
            summary = _branch_summary(func, variants)
            if summary is None and len(variants) == 1:
                call, variant = variants[0]
                if _control_stack(func, call):
                    continue
                if not _address_has_mmio_provenance(func, variant["address"]):
                    continue
                summary = {
                    "kind": variant["kind"],
                    "width": variant["width"],
                    "params": [name for name, _ctype in func.params if name],
                    "address": variant["address"],
                    "value": variant["value"],
                    "function": func.name,
                    "symbol": symbol,
                    "source": func.source_path,
                    "evidence": callsite_evidence(
                        func, call, "read" if variant["kind"] == "Read" else "write"),
                    "reliability": "Exact",
                    "variant_count": 1,
                    "variant_widths": [variant["width"]],
                    "variant_accessors": [variant["accessor"]],
                    "summary_depth": variant.get("summary_depth", 0),
                }
            if (summary is not None
                    and summary.get("summary_depth", 0) > 0
                    and _function_contains_delay(func.cursor)):
                summary = None
            if summary is None:
                continue
            summaries[symbol] = summary
            summaries.setdefault(func.name, summary)
            changed = True
        if not changed:
            break
    return summaries, candidates
