"""Inline cache construction and single/multi-TU inlined extraction."""
from __future__ import annotations

from ..ast_model import Func, callback_entry_symbols, function_calls
from ..dataflow import extract_function, FuncExtraction
from ..wrappers import infer_wrapper_summaries, _candidate_functions
from ..indirect import infer_indirect_targets, resolve_indirect_call
from .ids import _callee_id, _func_id, _resolved_callee_id
from .call_rows import _formal_calls
from .evidence import _coverage_aware_inlined_names, _op_fingerprint
from .inlining import _prove_inlined_call_context, _selective_frontier_call_closure


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


def _adaptive_inline_depth(
        edges: set[tuple[str, str]], symbols: set[str]) -> int:
    """Return the longest finite call path after collapsing recursive SCCs.

    Inline expansion is an implementation detail; its default bound should
    follow the input call graph rather than a driver-specific constant.  SCCs
    are collapsed first so recursive helpers remain bounded and continue to
    fail closed in the call-context proof.
    """
    nodes = set(symbols)
    forward: dict[str, set[str]] = {node: set() for node in nodes}
    reverse: dict[str, set[str]] = {node: set() for node in nodes}
    for caller, callee in edges:
        if caller not in nodes or callee not in nodes:
            continue
        forward[caller].add(callee)
        reverse[callee].add(caller)

    # Iterative Kosaraju avoids making Python recursion depth part of the
    # extractor's behavior for large Linux translation units.
    order: list[str] = []
    visited: set[str] = set()
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                order.append(node)
                continue
            stack.append((node, True))
            for child in sorted(forward[node], reverse=True):
                if child not in visited:
                    visited.add(child)
                    stack.append((child, False))

    components: list[set[str]] = []
    assigned: set[str] = set()
    for start in reversed(order):
        if start in assigned:
            continue
        component: set[str] = set()
        stack = [start]
        assigned.add(start)
        while stack:
            node = stack.pop()
            component.add(node)
            for parent in sorted(reverse[node], reverse=True):
                if parent not in assigned:
                    assigned.add(parent)
                    stack.append(parent)
        components.append(component)

    component_of = {
        node: index
        for index, component in enumerate(components)
        for node in component
    }
    condensed: dict[int, set[int]] = {
        index: set() for index in range(len(components))}
    for caller, callees in forward.items():
        source = component_of[caller]
        for callee in callees:
            target = component_of[callee]
            if source != target:
                condensed[source].add(target)

    indegree = {index: 0 for index in condensed}
    for targets in condensed.values():
        for target in targets:
            indegree[target] += 1
    ready = sorted(index for index, degree in indegree.items() if degree == 0)
    topological: list[int] = []
    while ready:
        current = ready.pop(0)
        topological.append(current)
        for target in sorted(condensed[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()

    distances = {index: 0 for index in condensed}
    for source in topological:
        for target in condensed[source]:
            distances[target] = max(distances[target], distances[source] + 1)
    return max(distances.values(), default=0)


def extract_with_inlining(funcs: list[Func], macros, tu, source_lines,
                          mmio_globals=None, max_depth: int | None = None,
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
    if max_depth is None:
        max_depth = _adaptive_inline_depth(
            {(caller, callee)
             for caller, callees in call_graph(funcs).items()
             for callee in callees}, symbols)
    # Compute entry-point identity before direct extraction so wrapper
    # summaries cannot accidentally inline registered callbacks.
    callback_entries = callback_entry_symbols(tu, symbols)
    # Candidate expansion adds header-defined inline helpers to the
    # function universe; call rows must cover them or every flattened op
    # originating from a header helper fails its citation check.
    call_funcs = _candidate_functions(funcs)
    base = build_inline_cache(
        call_funcs, macros, tu, source_lines, mmio_globals, mmio_alias_facts,
        wrapper_summaries,
        indirect_targets,
        callback_entries,
        include_framework, extra_blacklist)

    # Iterative bounded expansion to a fixpoint (mirrors the multi-TU
    # path): each round re-extracts with the previous round's summaries as
    # the inline cache, so register effects propagate through helper chains
    # one call level per round.  A single one-shot pass would flatten only
    # direct callees and silently drop deeper contexts — exactly the class
    # of gap the call-context proof then reports as an occurrence mismatch.
    expanded = dict(base)
    propagation_by_depth = [{
        "depth": 0,
        "new_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
        "total_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
    }]
    for depth in range(1, max(0, max_depth) + 1):
        inline_cache = {
            name: ex for name, ex in expanded.items()
            if ex.ops or ex.return_expr}
        next_expanded: dict[str, FuncExtraction] = {}
        for f in call_funcs:
            symbol = _func_id(f)
            cache = {name: ex for name, ex in inline_cache.items()
                     if name != symbol}
            next_expanded[symbol] = extract_function(
                f, macros, tu,
                source_lines=source_lines,
                inline_cache=cache,
                mmio_globals=mmio_globals,
                mmio_alias_facts=mmio_alias_facts,
                wrapper_summaries=wrapper_summaries,
                indirect_targets=indirect_targets,
                callback_entries=callback_entries,
                max_depth=1,
                include_framework=include_framework,
                extra_blacklist=extra_blacklist,
            )
        before = {name: _op_fingerprint(ex) for name, ex in expanded.items()}
        after = {name: _op_fingerprint(ex)
                 for name, ex in next_expanded.items()}
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
    result = expanded

    # pure helpers (inlined into a caller, never callback-referenced) are dedup'd
    inlineable = {name for name, ex in expanded.items()
                  if ex.ops or ex.return_expr}
    inlined_into_caller: set[str] = set()
    for f in call_funcs:
        for cs in function_calls(f.cursor):
            callee = _resolved_callee_id(cs, indirect_targets)
            if (callee in inlineable
                    and callee != _func_id(f)):
                inlined_into_caller.add(callee)
    (inlined_names, rescue_stats, rescue_frontiers) = (
        _coverage_aware_inlined_names(
            base, result, inlined_into_caller - callback_entries))
    func_by_symbol = {_func_id(f): f for f in call_funcs}
    formal_calls = _formal_calls(call_funcs, indirect_targets)
    call_context = _prove_inlined_call_context(
        base, result, inlined_names, formal_calls)
    rescue_stats = dict(rescue_stats)
    rescue_stats["call_semantics_proven"] = bool(call_context["proven"])
    rescue_stats["call_context_proof"] = call_context
    rescue_stats["propagation_by_depth"] = propagation_by_depth

    def extract_one(symbol: str, inline_cache=None) -> FuncExtraction:
        f = func_by_symbol[symbol]
        cache = inline_cache
        if cache and symbol in cache:
            cache = {name: ex for name, ex in cache.items()
                     if name != symbol}
        return extract_function(
            f, macros, tu,
            source_lines=source_lines,
            inline_cache=cache,
            mmio_globals=mmio_globals,
            mmio_alias_facts=mmio_alias_facts,
            wrapper_summaries=wrapper_summaries,
            indirect_targets=indirect_targets,
            callback_entries=callback_entries,
            max_depth=1,
            include_framework=include_framework,
            extra_blacklist=extra_blacklist,
        )

    (result, call_closed, closure_stats,
     closure_overlays) = _selective_frontier_call_closure(
        funcs, result, rescue_frontiers, callback_entries, formal_calls,
        extract_one)
    for symbol, frontier in rescue_frontiers.items():
        result[symbol] = frontier
    rescue_stats = dict(rescue_stats)
    rescue_stats["call_closure_accepted_symbols"] = sorted(call_closed)
    rescue_stats["call_closure_accepted_sites"] = closure_stats[
        "accepted_sites"]
    unique_summaries = {
        summary["symbol"]: summary for summary in wrapper_summaries.values()}
    return result, inlined_names, callback_entries, {
        "wrapper_summaries": sorted(unique_summaries),
        "wrapper_summary_count": len(unique_summaries),
        "indirect_call_targets": dict(sorted(indirect_targets.items())),
        "resolved_indirect_calls": sum(
            resolve_indirect_call(call, indirect_targets) is not None
            for func in funcs for call in function_calls(func.cursor)),
        "callee_rescue": rescue_stats,
        "formal_calls": formal_calls,
        "selective_call_closure": closure_stats,
        "_call_closure_overlays": closure_overlays,
    }


def extract_multi_with_inlining(units: list[dict], max_depth: int | None = None,
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
    # Expand to include header-defined inline functions called by targets
    funcs = _candidate_functions(funcs)
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
    # Header-defined inline functions belong to the unit of the caller.
    # Assign them to the first unit that references them.
    for f in funcs:
        fid = _func_id(f)
        if fid not in owner:
            for unit in units:
                if any(_func_id(f) == fid for f in unit["funcs"]):
                    owner[fid] = unit
                    break
            else:
                owner[fid] = units[0]
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

    effective_depth = (max_depth if max_depth is not None else
                       _adaptive_inline_depth(edges, symbols))

    def extract_one(symbol: str, inline_cache=None) -> FuncExtraction:
        f = func_by_id[symbol]
        unit = owner[symbol]
        cache = inline_cache
        if cache and symbol in cache:
            cache = {name: ex for name, ex in cache.items()
                     if name != symbol}
        return extract_function(
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

    def extract_all(inline_cache=None) -> dict[str, FuncExtraction]:
        result: dict[str, FuncExtraction] = {}
        for f in funcs:
            symbol = _func_id(f)
            result[symbol] = extract_one(symbol, inline_cache)
        return result

    direct = extract_all()
    expanded = direct
    propagation_by_depth = [{
        "depth": 0,
        "new_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
        "total_mmio_ops": sum(len(ex.ops) for ex in expanded.values()),
    }]
    for depth in range(1, max(0, effective_depth) + 1):
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
    (inlined_names, rescue_stats, rescue_frontiers) = (
        _coverage_aware_inlined_names(
            direct, expanded, inlined_into_caller - callback_entries))
    formal_calls = _formal_calls(funcs, indirect_targets)
    call_context = _prove_inlined_call_context(
        direct, expanded, inlined_names, formal_calls)
    rescue_stats = dict(rescue_stats)
    rescue_stats["call_semantics_proven"] = bool(call_context["proven"])
    rescue_stats["call_context_proof"] = call_context
    (expanded, call_closed, closure_stats,
     closure_overlays) = _selective_frontier_call_closure(
        funcs, expanded, rescue_frontiers, callback_entries, formal_calls,
        extract_one)
    for symbol, frontier in rescue_frontiers.items():
        expanded[symbol] = frontier
    rescue_stats = dict(rescue_stats)
    rescue_stats["call_closure_accepted_symbols"] = sorted(call_closed)
    rescue_stats["call_closure_accepted_sites"] = closure_stats[
        "accepted_sites"]
    stats = {
        "call_edges": len(edges),
        "cross_tu_call_edges": len(cross_tu_edges),
        "resolved_cross_tu_call_edges": len(cross_tu_edges),
        "propagated_mmio_edges": len(propagated_edges),
        "propagation_by_depth": propagation_by_depth,
        "inline_depth": {
            "configured": max_depth,
            "effective": effective_depth,
            "adaptive": max_depth is None,
        },
        "unresolved_internal_calls": len(unresolved_internal),
        "wrapper_summaries": sorted({
            summary["symbol"] for summary in wrapper_summaries.values()}),
        "wrapper_summary_count": len({
            summary["symbol"] for summary in wrapper_summaries.values()}),
        "indirect_call_targets": dict(sorted(indirect_targets.items())),
        "resolved_indirect_calls": sum(
            resolve_indirect_call(call, indirect_targets) is not None
            for func in funcs for call in function_calls(func.cursor)),
        "callee_rescue": rescue_stats,
        "formal_calls": formal_calls,
        "selective_call_closure": closure_stats,
        "_call_closure_overlays": closure_overlays,
    }
    return (expanded, inlined_names,
            callback_entries, stats)
