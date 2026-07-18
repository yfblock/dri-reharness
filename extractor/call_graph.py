"""Call graph + wrapper-function inlining.

Pass 1: extract each target function's own (direct) MMIO ops.
Pass 2: build the call graph; for each function, inline callees that are
themselves target functions with MMIO ops (depth-limited, recursion-safe).
"""
from __future__ import annotations
from .ast_model import (
    Func, callback_entry_symbols, function_calls, source_text,
    walk_with_control,
)
from .dataflow import extract_function, FuncExtraction
from .wrappers import infer_wrapper_summaries
from .indirect import infer_indirect_targets, resolve_indirect_call


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


def _formal_calls(funcs: list[Func], indirect_targets: dict[str, str]) -> list[dict]:
    """Build versioned, AST-authoritative source-local call evidence."""
    by_symbol = {_func_id(func): func for func in funcs}
    rows = []
    for caller in funcs:
        parents = _cursor_parents(caller.cursor)
        controls: dict[int, list[dict]] = {}
        for node, stack in walk_with_control(caller.cursor):
            if node.kind.name == "CALL_EXPR":
                controls[node.location.offset] = [dict(frame) for frame in stack]
        order = 0
        for call in function_calls(caller.cursor):
            callee_symbol = _resolved_callee_id(call, indirect_targets)
            callee = by_symbol.get(callee_symbol)
            if callee is None:
                continue
            order += 1
            location = call.cursor.location
            arguments = []
            for index, expression in enumerate(call.arg_text):
                parameter = callee.params[index] if index < len(callee.params) \
                    else (None, None)
                arguments.append({
                    "index": index,
                    "expression": expression.strip(),
                    "parameter": parameter[0],
                    "parameter_type": parameter[1],
                    "argument_type": (
                        call.args[index].type.get_canonical().spelling),
                })
            direct_symbol = _callee_id(call)
            rows.append({
                "schema": 1,
                "caller_usr": _func_id(caller),
                "caller_module": caller.module_name or caller.name,
                "callee_usr": callee_symbol,
                "callee_module": callee.module_name or callee.name,
                "callsite": {
                    "source": (location.file.name
                               if location and location.file else None),
                    "line": location.line if location else 0,
                    "column": location.column if location else 0,
                    "offset": location.offset if location else 0,
                    "order": order,
                },
                "argument_mapping": arguments,
                "return_binding": _return_binding(call.cursor, parents),
                "control": controls.get(
                    location.offset if location else 0, []),
                "resolution_authority": (
                    "direct_function_declaration"
                    if direct_symbol == callee_symbol
                    else "static_indirect_target"),
                "multiplicity": {
                    "kind": "syntactic_callsite",
                    "per_caller_invocation": 1,
                    "runtime_count_proven": False,
                },
            })
    rows.sort(key=lambda row: (
        row["caller_module"], row["callsite"]["source"] or "",
        row["callsite"]["offset"], row["callee_module"]))
    return rows


def _op_fingerprint(extraction: FuncExtraction) -> tuple:
    """Stable-enough convergence key for iterative summary expansion.

    Counts alone can converge before argument substitution has propagated
    through a same-sized wrapper chain, so include the semantic fields.
    """
    return tuple(
        (op.kind, repr(op.addr), op.width, op.value, op.condition,
         tuple(op.cond_stack), repr(op.control_stack), op.reg_name, op.var,
         (op.evidence or {}).get("symbol"),
         (op.evidence or {}).get("site_id"),
         repr((op.evidence or {}).get("inlined_at", [])))
        for op in extraction.ops) + ((
            "return", extraction.return_expr, extraction.return_read_var),)


def _evidence_sites(
        extraction: FuncExtraction | None,
        owner_filter: str | None = None
        ) -> tuple[set[tuple[str, str]], int]:
    """Return definition-owned source sites and unproven register op count."""
    if extraction is None:
        return set(), 0
    sites: set[tuple[str, str]] = set()
    without_evidence = 0
    for op in extraction.ops:
        if op.kind not in {"Read", "Write", "ReadModifyWrite"}:
            continue
        site_id = (op.evidence or {}).get("site_id")
        owner = (op.evidence or {}).get("symbol")
        # Missing identity can never be proven covered by another module.
        # Count it before applying the owner filter; otherwise an empty
        # evidence object is silently skipped as if it belonged elsewhere.
        if not site_id or not owner:
            without_evidence += 1
            continue
        if owner_filter is not None and owner != owner_filter:
            continue
        sites.add((owner, site_id))
    return sites, without_evidence


def _direct_evidence_frontier(
        extraction: FuncExtraction, symbol: str,
        already_covered: set[tuple[str, str]]) -> FuncExtraction:
    """Keep only unproved definition-owned register evidence.

    A rescued module is an accounting frontier, not a reconstructed call.
    Wrapper-summary descendants, non-register effects and already-covered
    sites must not be copied into it because that would manufacture duplicate
    semantics while merely trying to close lexical source coverage.
    """
    ops = []
    for op in extraction.ops:
        if op.kind not in {"Read", "Write", "ReadModifyWrite"}:
            continue
        evidence = op.evidence or {}
        site_id = evidence.get("site_id")
        owner = evidence.get("symbol")
        if not site_id or not owner:
            ops.append(op)
            continue
        if owner == symbol and (owner, site_id) not in already_covered:
            ops.append(op)
    return FuncExtraction(
        name=extraction.name,
        params=list(extraction.params),
        ops=ops,
        warnings=list(extraction.warnings),
    )


def _coverage_aware_inlined_names(
        direct: dict[str, FuncExtraction],
        expanded: dict[str, FuncExtraction],
        candidates: set[str]) -> tuple[set[str], dict, dict[str, FuncExtraction]]:
    """Drop an inlined helper only when retained modules cover its sites.

    Call-graph reachability alone is insufficient: depth limits, unresolved
    substitutions or unsupported calls may prevent a callee's direct MMIO
    sites from appearing in any caller.  Keep a small set of helper modules
    whose expanded summaries cover every direct candidate site.  A pruning
    pass avoids retaining both a wrapper and the helper sites it already
    carries.
    """
    candidates = set(candidates)
    if not candidates:
        return set(), {
            "candidates": 0, "rescued": 0, "retained_inlined": 0,
            "required_sites": 0, "base_covered_sites": 0,
            "rescue_mode": "direct-evidence-frontier",
            "rescued_direct_ops": 0,
            "call_semantics_proven": True,
            "rescued_symbols": [], "unproven_symbols": [],
        }, {}

    direct_sites: dict[str, set[tuple[str, str]]] = {}
    unproven: set[str] = set()
    for symbol in candidates:
        sites, missing = _evidence_sites(
            direct.get(symbol), owner_filter=symbol)
        direct_sites[symbol] = sites
        if missing:
            unproven.add(symbol)

    base_covered: set[tuple[str, str]] = set()
    for symbol, extraction in expanded.items():
        if symbol not in candidates:
            base_covered |= _evidence_sites(extraction)[0]
    required = set().union(*direct_sites.values()) if direct_sites else set()

    rescued = {
        symbol for symbol in candidates
        if symbol in unproven or not direct_sites[symbol] <= base_covered
    }

    # Remove redundant rescues while preserving coverage of every direct site.
    # Evidence-less operations remain forced because no other module can prove
    # that it represents the same source operation.
    changed = True
    while changed:
        changed = False
        for symbol in sorted(rescued):
            if symbol in unproven:
                continue
            coverage = set(base_covered)
            for other in rescued - {symbol}:
                coverage |= direct_sites[other]
            if required <= coverage:
                rescued.remove(symbol)
                changed = True

    final_coverage = set(base_covered)
    for symbol in rescued:
        final_coverage |= direct_sites[symbol]
    # Fail closed if a malformed extraction still leaves a direct site absent.
    for symbol in sorted(candidates):
        if not direct_sites[symbol] <= final_coverage:
            rescued.add(symbol)
            final_coverage |= direct_sites[symbol]

    frontiers: dict[str, FuncExtraction] = {}
    frontier_covered = set(base_covered)
    for symbol in sorted(rescued):
        extraction = direct.get(symbol)
        if extraction is None:
            continue
        frontier = _direct_evidence_frontier(
            extraction, symbol, frontier_covered)
        frontiers[symbol] = frontier
        frontier_covered |= direct_sites[symbol]

    inlined_names = candidates - rescued
    return inlined_names, {
        "candidates": len(candidates),
        "rescued": len(rescued),
        "retained_inlined": len(inlined_names),
        "required_sites": len(required),
        "base_covered_sites": len(required & base_covered),
        "rescue_mode": "direct-evidence-frontier",
        "rescued_direct_ops": sum(
            len(frontier.ops) for frontier in frontiers.values()),
        # Bounded helper flattening currently has no independent callsite,
        # argument, guard, fanout or recursion proof.  Even when no lexical
        # rescue is needed, candidates > 0 must therefore remain fail-closed
        # until Formal RIS Call and its verifier exist.
        "call_semantics_proven": False,
        "rescued_symbols": sorted(rescued),
        "unproven_symbols": sorted(unproven),
    }, frontiers


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
    (inlined_names, rescue_stats, rescue_frontiers) = (
        _coverage_aware_inlined_names(
            base, result, inlined_into_caller - callback_entries))
    for symbol, frontier in rescue_frontiers.items():
        result[symbol] = frontier
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
        "formal_calls": _formal_calls(funcs, indirect_targets),
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

    direct = extract_all()
    expanded = direct
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
    (inlined_names, rescue_stats, rescue_frontiers) = (
        _coverage_aware_inlined_names(
            direct, expanded, inlined_into_caller - callback_entries))
    for symbol, frontier in rescue_frontiers.items():
        expanded[symbol] = frontier
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
        "callee_rescue": rescue_stats,
        "formal_calls": _formal_calls(funcs, indirect_targets),
    }
    return (expanded, inlined_names,
            callback_entries, stats)
