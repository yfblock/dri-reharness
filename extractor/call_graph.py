"""Call graph + wrapper-function inlining.

Pass 1: extract each target function's own (direct) MMIO ops.
Pass 2: build the call graph; for each function, inline callees that are
themselves target functions with MMIO ops (depth-limited, recursion-safe).
"""
from __future__ import annotations
from .ast_model import (Func, function_calls, callback_entry_symbols)
from .dataflow import extract_function, FuncExtraction
from .wrappers import infer_wrapper_summaries
from .indirect import infer_indirect_targets, resolve_indirect_call


def _func_id(func: Func) -> str:
    return func.symbol_id or func.name


def _callee_id(call) -> str:
    return call.symbol_id or call.name


def _resolved_callee_id(call, indirect_targets: dict[str, str]) -> str:
    return resolve_indirect_call(call, indirect_targets) or _callee_id(call)


def _op_fingerprint(extraction: FuncExtraction) -> tuple:
    """Stable-enough convergence key for iterative summary expansion.

    Counts alone can converge before argument substitution has propagated
    through a same-sized wrapper chain, so include the semantic fields.
    """
    return tuple(
        (op.kind, repr(op.addr), op.width, op.value, op.condition,
         tuple(op.cond_stack), repr(op.control_stack), op.reg_name, op.var)
        for op in extraction.ops) + (("return", extraction.return_expr),)


def build_inline_cache(funcs: list[Func], macros, tu, source_lines,
                       mmio_globals=None, mmio_alias_facts=None,
                       wrapper_summaries=None,
                       indirect_targets=None,
                       callback_entries=None,
                       include_framework: bool = False,
                       extra_blacklist: set[str] | None = None) -> dict[str, FuncExtraction]:
    """Pass 1: per-function direct extraction (no inlining yet)."""
    cache: dict[str, FuncExtraction] = {}
    for f in funcs:
        cache[_func_id(f)] = extract_function(
            f, macros, tu, source_lines=source_lines,
            mmio_globals=mmio_globals,
            mmio_alias_facts=mmio_alias_facts,
            wrapper_summaries=wrapper_summaries,
            indirect_targets=indirect_targets,
            callback_entries=callback_entries,
            include_framework=include_framework,
            extra_blacklist=extra_blacklist)
    return cache


def call_graph(funcs: list[Func]) -> dict[str, set[str]]:
    """symbol identity -> target-function callee identities."""
    symbols = {_func_id(f) for f in funcs}
    g: dict[str, set[str]] = {}
    for f in funcs:
        callees = set()
        for cs in function_calls(f.cursor):
            callee = _callee_id(cs)
            if callee in symbols:
                callees.add(callee)
        g[_func_id(f)] = callees
    return g


def extract_with_inlining(funcs: list[Func], macros, tu, source_lines,
                          mmio_globals=None, max_depth: int = 3,
                          mmio_alias_facts=None,
                          include_framework: bool = False,
                          extra_blacklist: set[str] | None = None
                          ) -> tuple[dict, set, set, dict]:
    """Final extraction with wrapper inlining enabled.

    Returns (extractions, inlined_names, callback_entries, summary_stats) where:
      - inlined_names: pure-helper functions inlined into a caller (dedup'd)
      - callback_entries: functions referenced as function-pointer values
        (kept as own modules, not inlined)
    """
    wrapper_summaries, _wrapper_funcs = infer_wrapper_summaries(funcs)
    indirect_targets = infer_indirect_targets(
        "\n".join(source_lines), {func.name for func in funcs})
    symbols = {_func_id(f) for f in funcs}
    # Compute entry-point identity before direct extraction so wrapper
    # summaries cannot accidentally inline registered callbacks.
    callback_entries = callback_entry_symbols(tu, symbols)
    base = build_inline_cache(
        funcs, macros, tu, source_lines, mmio_globals, mmio_alias_facts,
        wrapper_summaries,
        indirect_targets,
        callback_entries,
        include_framework, extra_blacklist)
    inline_cache = {n: e for n, e in base.items() if e.ops or e.return_expr}

    # pure helpers (inlined into a caller, never callback-referenced) are dedup'd
    inlined_into_caller: set[str] = set()
    for f in funcs:
        for cs in function_calls(f.cursor):
            callee = _resolved_callee_id(cs, indirect_targets)
            if (callee in inline_cache and callee in symbols
                    and callee != _func_id(f)):
                inlined_into_caller.add(callee)
    inlined_names = inlined_into_caller - callback_entries

    result: dict[str, FuncExtraction] = {}
    for f in funcs:
        result[_func_id(f)] = extract_function(
            f, macros, tu,
            source_lines=source_lines,
            inline_cache=inline_cache,
            mmio_globals=mmio_globals,
            mmio_alias_facts=mmio_alias_facts,
            wrapper_summaries=wrapper_summaries,
            indirect_targets=indirect_targets,
            callback_entries=callback_entries,
            max_depth=max_depth,
            include_framework=include_framework,
            extra_blacklist=extra_blacklist,
        )
    unique_summaries = {
        summary["symbol"]: summary for summary in wrapper_summaries.values()}
    return result, inlined_names, callback_entries, {
        "wrapper_summaries": sorted(unique_summaries),
        "wrapper_summary_count": len(unique_summaries),
        "indirect_call_targets": dict(sorted(indirect_targets.items())),
        "resolved_indirect_calls": sum(
            resolve_indirect_call(call, indirect_targets) is not None
            for func in funcs for call in function_calls(func.cursor)),
    }


def extract_multi_with_inlining(units: list[dict], max_depth: int = 3,
                                include_framework: bool = False,
                                extra_blacklist: set[str] | None = None
                                ) -> tuple[dict, set, set, dict]:
    """Extract and inline across multiple C translation units.

    Each unit supplies ``funcs``, ``macros``, ``tu``, ``source_lines``, and
    ``mmio_globals``.  Direct per-function summaries are expanded iteratively,
    allowing a callback in one C file to inherit MMIO operations through
    helpers defined in other files. Static functions are keyed by their
    source-qualified identity; externally visible definitions retain their
    linker symbol.
    """
    funcs = [f for unit in units for f in unit["funcs"]]
    wrapper_summaries, _wrapper_funcs = infer_wrapper_summaries(funcs)
    indirect_targets = {}
    for unit in units:
        inferred = infer_indirect_targets(
            unit.get("source_text", ""), {func.name for func in funcs})
        for key, target in inferred.items():
            if key not in indirect_targets:
                indirect_targets[key] = target
            elif indirect_targets[key] != target:
                indirect_targets.pop(key, None)
    symbols = {_func_id(f) for f in funcs}
    names = {f.name for f in funcs}
    owner = {_func_id(f): unit for unit in units for f in unit["funcs"]}
    func_by_id = {_func_id(f): f for f in funcs}

    callback_entries: set[str] = set()
    for unit in units:
        callback_entries |= callback_entry_symbols(unit["tu"], symbols)

    edges: set[tuple[str, str]] = set()
    cross_tu_edges: set[tuple[str, str]] = set()
    unresolved_internal: set[tuple[str, str]] = set()
    for f in funcs:
        caller = _func_id(f)
        for cs in function_calls(f.cursor):
            callee = _resolved_callee_id(cs, indirect_targets)
            if callee in symbols:
                edge = (caller, callee)
                edges.add(edge)
                if func_by_id[callee].source_path != f.source_path:
                    cross_tu_edges.add(edge)
            elif cs.name in names:
                unresolved_internal.add((caller, cs.name))

    def extract_all(inline_cache=None) -> dict[str, FuncExtraction]:
        result: dict[str, FuncExtraction] = {}
        for f in funcs:
            symbol = _func_id(f)
            unit = owner[symbol]
            cache = inline_cache
            if cache and symbol in cache:
                cache = {name: ex for name, ex in cache.items()
                         if name != symbol}
            result[symbol] = extract_function(
                f, unit["macros"], unit["tu"],
                source_lines=unit["source_lines"],
                inline_cache=cache,
                mmio_globals=unit["mmio_globals"],
                mmio_alias_facts=unit.get("mmio_alias_facts"),
                wrapper_summaries=wrapper_summaries,
                indirect_targets=indirect_targets,
                callback_entries=callback_entries,
                max_depth=1,
                include_framework=include_framework,
                extra_blacklist=extra_blacklist,
            )
        return result

    expanded = extract_all()
    propagation_by_depth = [{
        "depth": 0,
        "new_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
        "total_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
    }]
    for depth in range(1, max(0, max_depth) + 1):
        inline_cache = {
            name: ex for name, ex in expanded.items()
            if ex.ops or ex.return_expr}
        next_expanded = extract_all(inline_cache)
        before = {name: _op_fingerprint(ex) for name, ex in expanded.items()}
        after = {name: _op_fingerprint(ex) for name, ex in next_expanded.items()}
        old_total = sum(len(ex.ops) for ex in expanded.values())
        new_total = sum(len(ex.ops) for ex in next_expanded.values())
        propagation_by_depth.append({
            "depth": depth,
            "new_mmio_ops": max(0, new_total - old_total),
            "total_mmio_ops": new_total,
        })
        expanded = next_expanded
        if after == before:
            break

    inlineable = {name for name, ex in expanded.items()
                  if ex.ops and name not in callback_entries}
    inlined_into_caller: set[str] = set()
    for f in funcs:
        for cs in function_calls(f.cursor):
            callee = _resolved_callee_id(cs, indirect_targets)
            if callee in inlineable and callee != _func_id(f):
                inlined_into_caller.add(callee)

    propagated_edges = {
        edge for edge in edges if expanded.get(edge[1])
        and expanded[edge[1]].ops
    }
    stats = {
        "call_edges": len(edges),
        "cross_tu_call_edges": len(cross_tu_edges),
        "resolved_cross_tu_call_edges": len(cross_tu_edges),
        "propagated_mmio_edges": len(propagated_edges),
        "propagation_by_depth": propagation_by_depth,
        "unresolved_internal_calls": len(unresolved_internal),
        "wrapper_summaries": sorted({
            summary["symbol"] for summary in wrapper_summaries.values()}),
        "wrapper_summary_count": len({
            summary["symbol"] for summary in wrapper_summaries.values()}),
        "indirect_call_targets": dict(sorted(indirect_targets.items())),
        "resolved_indirect_calls": sum(
            resolve_indirect_call(call, indirect_targets) is not None
            for func in funcs for call in function_calls(func.cursor)),
    }
    return (expanded, inlined_into_caller - callback_entries,
            callback_entries, stats)
