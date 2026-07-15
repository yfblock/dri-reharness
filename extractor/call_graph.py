"""Call graph + wrapper-function inlining.

Pass 1: extract each target function's own (direct) MMIO ops.
Pass 2: build the call graph; for each function, inline callees that are
themselves target functions with MMIO ops (depth-limited, recursion-safe).
"""
from __future__ import annotations
from typing import Optional

from .ast_model import Func, function_calls, callback_entry_functions
from .dataflow import extract_function, FuncExtraction


def build_inline_cache(funcs: list[Func], macros, tu, source_lines,
                       mmio_globals=None, include_framework: bool = False,
                       extra_blacklist: set[str] | None = None) -> dict[str, FuncExtraction]:
    """Pass 1: per-function direct extraction (no inlining yet)."""
    cache: dict[str, FuncExtraction] = {}
    for f in funcs:
        cache[f.name] = extract_function(f, macros, tu, source_lines=source_lines,
                                         mmio_globals=mmio_globals,
                                         include_framework=include_framework,
                                         extra_blacklist=extra_blacklist)
    return cache


def call_graph(funcs: list[Func]) -> dict[str, set[str]]:
    """name -> set of callee names that are target-file functions."""
    names = {f.name for f in funcs}
    g: dict[str, set[str]] = {}
    for f in funcs:
        callees = set()
        for cs in function_calls(f.cursor):
            if cs.name in names:
                callees.add(cs.name)
        g[f.name] = callees
    return g


def extract_with_inlining(funcs: list[Func], macros, tu, source_lines,
                          mmio_globals=None, max_depth: int = 3,
                          include_framework: bool = False,
                          extra_blacklist: set[str] | None = None) -> tuple[dict, set, set]:
    """Final extraction with wrapper inlining enabled.

    Returns (extractions, inlined_names, callback_entries) where:
      - inlined_names: pure-helper functions inlined into a caller (dedup'd)
      - callback_entries: functions referenced as function-pointer values
        (kept as own modules, not inlined)
    """
    base = build_inline_cache(funcs, macros, tu, source_lines, mmio_globals,
                              include_framework, extra_blacklist)
    names = {f.name for f in funcs}
    # callback entries (function-pointer references) are standalone entry points
    callback_entries = callback_entry_functions(tu, names)
    inline_cache = {n: e for n, e in base.items()
                    if e.ops and n not in callback_entries}

    # pure helpers (inlined into a caller, never callback-referenced) are dedup'd
    inlined_into_caller: set[str] = set()
    for f in funcs:
        for cs in function_calls(f.cursor):
            if cs.name in inline_cache and cs.name in names and cs.name != f.name:
                inlined_into_caller.add(cs.name)
    inlined_names = inlined_into_caller - callback_entries

    result: dict[str, FuncExtraction] = {}
    for f in funcs:
        result[f.name] = extract_function(
            f, macros, tu,
            source_lines=source_lines,
            inline_cache=inline_cache,
            mmio_globals=mmio_globals,
            max_depth=max_depth,
            include_framework=include_framework,
            extra_blacklist=extra_blacklist,
        )
    return result, inlined_names, callback_entries
