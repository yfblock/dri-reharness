"""Call-context proofs and selective frontier call closure."""
from __future__ import annotations
import copy
from collections import Counter, defaultdict
from collections.abc import Callable

from ast_analyzer import Func
from ..dataflow import FuncExtraction
from .ids import _func_id
from .call_rows import (
    _call_row_is_proven, _eligible_call_edges, _op_occurrence, _op_site,
    _with_ops,
)
from .evidence import _definition_site, _evidence_sites, _register_ops


def _verify_inline_citations(
        expanded: dict[str, FuncExtraction],
        formal_calls: list[dict]) -> dict:
    """Check that every flattened op cites an exact AST call row per hop.

    ``_instantiate_op`` copies helper ops into callers; each copied op
    records an ``inlined_at`` hop ``{function, line, callee}`` for every
    call edge it was flattened through.  This check turns that trail into
    a proof obligation: each hop must match one call row (same caller,
    callsite line, resolved callee) and that row must independently pass
    ``_call_row_is_proven``.  A hop with no matching row means the copy
    came from an unevidenced callsite; a matching-but-unproven row means
    the copy is real but its context is not auditable.  Both fail closed.
    Wrapper-summary sites use ``summarized_at`` and are out of scope here.
    """
    row_index: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in formal_calls:
        callsite = row.get("callsite") or {}
        line = callsite.get("line")
        if (isinstance(row.get("caller_module"), str)
                and isinstance(line, int) and line
                and isinstance(row.get("callee_module"), str)):
            row_index[(row["caller_module"], line,
                       row["callee_module"])].append(row)

    violations: list[dict] = []
    checked_hops = 0
    for symbol, extraction in sorted(expanded.items()):
        if extraction is None:
            continue
        for op in extraction.ops:
            evidence = op.evidence or {}
            chain = evidence.get("inlined_at")
            if not isinstance(chain, list):
                continue
            for hop in chain:
                if not isinstance(hop, dict):
                    continue
                checked_hops += 1
                caller = hop.get("function")
                line = hop.get("line")
                callee = hop.get("callee")
                if not (isinstance(caller, str) and isinstance(line, int)
                        and isinstance(callee, str)):
                    violations.append({
                        "symbol": symbol, "hop": hop,
                        "reason": "malformed_hop",
                    })
                    continue
                rows = row_index.get((caller, line, callee))
                if not rows:
                    violations.append({
                        "symbol": symbol,
                        "hop": {"function": caller, "line": line,
                                "callee": callee},
                        "reason": "no_matching_call_row",
                    })
                    continue
                if not any(_call_row_is_proven(row, allow_structured_loops=True)
                           for row in rows):
                    violations.append({
                        "symbol": symbol,
                        "hop": {"function": caller, "line": line,
                                "callee": callee},
                        "reason": "cited_call_row_unproven",
                    })
    return {
        "checked_hops": checked_hops,
        "violations": violations[:32],
        "violation_count": len(violations),
        "complete": not violations,
    }


def _prove_inlined_call_context(
        direct: dict[str, FuncExtraction], expanded: dict[str, FuncExtraction],
        candidates: set[str], formal_calls: list[dict]) -> dict:
    """Prove that every inlined source site has exactly its static contexts.

    A source-site set is not enough: a bounded expansion can cover a site via
    one shallow call while silently dropping another path to the same helper.
    This proof counts static call paths in the AST call graph and compares
    them with occurrences in the emitted (non-inlined) modules. Structured
    loop frames remain attached to those occurrences; their runtime bounds
    are validated by the separate control-flow gate.

    The proof additionally requires every flattened operation to cite, hop
    by hop, an independently proven AST call row (see
    ``_verify_inline_citations``); without that, the copy itself has no
    auditable provenance even when path counts balance.
    """
    citations = _verify_inline_citations(expanded, formal_calls)
    if not citations["complete"]:
        return {
            "proven": False, "reason": "uncited_inline_chain",
            "inline_citations": citations,
        }
    candidates = set(candidates)
    # Candidates without any definition-owned register site are pure value
    # helpers (e.g. header accessors handled at the caller's expression
    # level): nothing was flattened, so there is no register context to
    # prove and they are vacuous for this proof.
    candidates = {
        symbol for symbol in candidates
        if _evidence_sites(direct.get(symbol), owner_filter=symbol)[0]}
    if not candidates:
        return {"proven": True, "reason": "no_inlined_candidates",
                "inline_citations": citations}

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in formal_calls:
        caller = row.get("caller_usr")
        callee = row.get("callee_usr")
        if isinstance(caller, str) and isinstance(callee, str):
            grouped[(caller, callee)].append(row)
    # This proof checks source-site ownership after structured control frames
    # have been retained in the expanded Formal RIS.  It does not need a
    # runtime loop bound; that stricter requirement belongs to frontier
    # propagation in _eligible_call_edges().
    grouped_edges = {
        edge for edge, rows in grouped.items()
        if edge[0] != edge[1] and rows
        and all(_call_row_is_proven(row, allow_structured_loops=True)
                for row in rows)
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for caller, callee in grouped_edges:
        adjacency[caller].add(callee)

    def reaches(start: str, target: str) -> bool:
        pending = [start]
        seen = set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            pending.extend(adjacency.get(node, ()))
        return False

    eligible_edges = {
        edge for edge in grouped_edges
        if not reaches(edge[1], edge[0])
    }

    direct_sites: dict[str, set[tuple[str, str]]] = {
        symbol: _evidence_sites(extraction, owner_filter=symbol)[0]
        for symbol, extraction in direct.items() if symbol in candidates}
    site_owners = {
        symbol for symbol, sites in direct_sites.items() if sites}
    if not site_owners:
        return {"proven": False, "reason": "no_direct_site_owner"}

    # Only calls on a path to a candidate's own source site are part of this
    # proof.  Candidates also contain helpers used for non-register effects;
    # their unrelated framework/lock calls must not poison MMIO call closure.
    relevant_nodes = set(site_owners)
    changed = True
    while changed:
        changed = False
        for caller, callee in grouped:
            if callee in relevant_nodes and caller not in relevant_nodes:
                relevant_nodes.add(caller)
                changed = True

    # Any call touching an inlined candidate must be independently proven.
    # Otherwise a valid shallow path could hide an unresolved or looped path.
    invalid_edges = sorted(
        edge for edge, rows in grouped.items()
        if (edge[1] in relevant_nodes
            or (edge[0] in relevant_nodes and edge[1] in relevant_nodes))
        and edge not in eligible_edges)
    if invalid_edges:
        return {
            "proven": False, "reason": "unproven_call_edge",
            "invalid_edges": [list(edge) for edge in invalid_edges],
        }

    outgoing: dict[str, list[str]] = defaultdict(list)
    for caller, callee in eligible_edges:
        for _ in grouped[(caller, callee)]:
            outgoing[caller].append(callee)

    roots = {
        symbol for symbol, extraction in expanded.items()
        if symbol not in candidates and _register_ops(extraction)
    }
    if not roots:
        return {"proven": False, "reason": "no_emitted_root"}

    def path_count(start: str, target: str, seen: frozenset[str]) -> int | None:
        if start == target:
            return 1
        if start in seen:
            return None
        total = 0
        for child in outgoing.get(start, []):
            nested = path_count(child, target, seen | {start})
            if nested is None:
                return None
            total += nested
        return total

    actual: Counter = Counter()
    # A subsystem-summary op is the caller's audited contract view of a
    # modeled accessor helper; it reproduces that helper's single modeled
    # access at the callsite.  Count it as the observed occurrence of a
    # candidate whose entire body is exactly that one access — multi-site
    # helpers stay fail-closed because one contract op cannot stand for
    # several distinct primitive accesses.
    single_site_by_short: dict[str, tuple] = {}
    for symbol in candidates:
        sites = direct_sites.get(symbol) or set()
        if len(sites) == 1:
            single_site_by_short.setdefault(
                symbol.rsplit("::", 1)[-1], next(iter(sites)))
    for root in roots:
        for op in _register_ops(expanded.get(root)):
            site = _definition_site(op)
            if site is not None and site[0] in candidates:
                actual[site] += 1
                continue
            evidence = op.evidence or {}
            if evidence.get("origin") != "subsystem_summary":
                continue
            short = (evidence.get("site_id") or "").rsplit(":", 1)[-1]
            contract_site = single_site_by_short.get(short)
            if contract_site is not None:
                actual[contract_site] += 1

    mismatches = []
    for symbol in sorted(candidates):
        for site in sorted(direct_sites.get(symbol, set())):
            expected = sum(
                path_count(root, symbol, frozenset()) or 0
                for root in roots)
            observed = actual[site]
            if expected != observed:
                mismatches.append({
                    "symbol": symbol, "site_id": site[1],
                    "expected_contexts": expected,
                    "observed_contexts": observed,
                })
    if mismatches:
        return {
            "proven": False, "reason": "call_path_occurrence_mismatch",
            "mismatches": mismatches,
            "roots": sorted(roots),
        }
    return {
        "proven": True, "reason": "exact_static_call_contexts",
        "eligible_edges": len(eligible_edges),
        "roots": sorted(roots),
        "inline_citations": citations,
    }


def _selective_frontier_call_closure(
        funcs: list[Func], expanded: dict[str, FuncExtraction],
        frontiers: dict[str, FuncExtraction], callback_entries: set[str],
        formal_calls: list[dict],
        extract_one: Callable[[str, dict[str, FuncExtraction]], FuncExtraction],
        *, max_rounds: int = 6,
        ) -> tuple[
            dict[str, FuncExtraction], set[str], dict,
            dict[str, FuncExtraction]]:
    """Propagate only uncovered helper evidence through verified call edges.

    The general depth expansion intentionally remains bounded.  This pass
    carries the small direct-evidence rescue frontier through exact AST call
    edges, then accepts a helper only when each of its source sites appears
    exactly once in one callback entry.  This avoids both dropped helpers and
    the callsite explosion caused by globally increasing inline depth.
    """
    if not frontiers or not callback_entries:
        return expanded, set(), {
            "schema": 1, "oracle": "selective-call-frontier-v1",
            "accepted_symbols": [], "accepted_sites": 0,
            "rounds": [], "rejected_symbols": sorted(frontiers),
        }, {}
    func_by_id = {_func_id(func): func for func in funcs}
    eligible_edges = _eligible_call_edges(formal_calls)
    rows_by_edge: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in formal_calls:
        edge = (row.get("caller_usr"), row.get("callee_usr"))
        if edge in eligible_edges:
            rows_by_edge[edge].append(row)
    direct_callees: dict[str, set[str]] = defaultdict(set)
    for caller, callee in eligible_edges:
        direct_callees[caller].add(callee)

    frontier_sites_by_symbol = {
        symbol: {
            site for op in extraction.ops
            if (site := _op_site(op)) is not None
        }
        for symbol, extraction in frontiers.items()
    }
    all_frontier_sites = set().union(
        *frontier_sites_by_symbol.values()) if frontier_sites_by_symbol else set()
    working = dict(expanded)
    working.update(frontiers)
    round_rows = []
    for depth in range(1, max_rounds + 1):
        carriers = {
            symbol for symbol, extraction in working.items()
            if any(_op_site(op) in all_frontier_sites
                   for op in extraction.ops)
        }
        candidates = sorted(
            caller for caller, callees in direct_callees.items()
            if caller in func_by_id and callees & carriers)
        updates: dict[str, FuncExtraction] = {}
        new_occurrences = 0
        for caller in candidates:
            cache: dict[str, FuncExtraction] = {}
            allowed = direct_callees.get(caller, set())
            for symbol, extraction in working.items():
                if symbol == caller:
                    continue
                if symbol in allowed:
                    cache[symbol] = extraction
                else:
                    cache[symbol] = _with_ops(
                        extraction, [
                            op for op in extraction.ops
                            if _op_site(op) not in all_frontier_sites
                        ])
            candidate = extract_one(caller, cache)
            current = working.get(caller)
            if current is None:
                continue
            existing_keys = Counter(_op_occurrence(op) for op in current.ops)
            candidate_keys = Counter(_op_occurrence(op) for op in candidate.ops)
            if any(candidate_keys[key] < count
                   for key, count in existing_keys.items()):
                continue
            kept = []
            remaining = Counter(existing_keys)
            before_frontier = Counter(
                _op_occurrence(op) for op in current.ops
                if _op_site(op) in all_frontier_sites)
            for op in candidate.ops:
                key = _op_occurrence(op)
                if remaining[key] > 0:
                    kept.append(op)
                    remaining[key] -= 1
                elif _op_site(op) in all_frontier_sites:
                    kept.append(op)
            after_frontier = Counter(
                _op_occurrence(op) for op in kept
                if _op_site(op) in all_frontier_sites)
            added = sum((after_frontier - before_frontier).values())
            if added:
                updates[caller] = _with_ops(candidate, kept)
                new_occurrences += added
        working.update(updates)
        round_rows.append({
            "depth": depth, "updated_functions": len(updates),
            "new_frontier_occurrences": new_occurrences,
        })
        if not updates:
            break

    callback_occurrences: Counter = Counter()
    callback_owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for callback in callback_entries:
        extraction = working.get(callback)
        if extraction is None:
            continue
        for op in extraction.ops:
            site = _op_site(op)
            if site in all_frontier_sites:
                callback_occurrences[site] += 1
                callback_owners[site].add(callback)
    accepted = set()
    accepted_callbacks: dict[str, str] = {}
    for symbol, sites in frontier_sites_by_symbol.items():
        if not sites or any(callback_occurrences[site] != 1 for site in sites):
            continue
        owners = set().union(*(callback_owners[site] for site in sites))
        if len(owners) != 1:
            continue
        accepted.add(symbol)
        accepted_callbacks[symbol] = next(iter(owners))

    accepted_sites = set().union(*(
        frontier_sites_by_symbol[symbol] for symbol in accepted
    )) if accepted else set()
    overlays: dict[str, FuncExtraction] = {}
    invalid_callbacks = set()
    for callback in set(accepted_callbacks.values()):
        proposed = working.get(callback)
        original = expanded.get(callback)
        if proposed is None or original is None:
            continue
        original_keys = Counter(_op_occurrence(op) for op in original.ops)
        remaining = Counter(original_keys)
        kept = []
        for op in proposed.ops:
            key = _op_occurrence(op)
            if remaining[key] > 0:
                kept.append(op)
                remaining[key] -= 1
                continue
            site = _op_site(op)
            if site not in accepted_sites:
                continue
            copied = copy.deepcopy(op)
            copied.evidence = dict(copied.evidence or {})
            copied.evidence["call_closure"] = {
                "schema": 1,
                "oracle": "selective-call-frontier-v1",
                "source_symbol": site[0],
                "callback_symbol": callback,
            }
            kept.append(copied)
        if any(remaining.values()):
            invalid_callbacks.add(callback)
        else:
            overlays[callback] = _with_ops(proposed, kept)
    if invalid_callbacks:
        accepted = {
            symbol for symbol in accepted
            if accepted_callbacks.get(symbol) not in invalid_callbacks
        }
        accepted_sites = set().union(*(
            frontier_sites_by_symbol[symbol] for symbol in accepted
        )) if accepted else set()
        overlays = {
            callback: extraction for callback, extraction in overlays.items()
            if callback not in invalid_callbacks
        }

    return expanded, accepted, {
        "schema": 1,
        "oracle": "selective-call-frontier-v1",
        "eligible_edges": len(eligible_edges),
        "accepted_symbols": sorted(accepted),
        "accepted_modules": sorted(
            func_by_id[symbol].module_name or func_by_id[symbol].name
            for symbol in accepted if symbol in func_by_id),
        "accepted_sites": len(accepted_sites),
        "callback_modules": sorted({
            func_by_id[callback].module_name or func_by_id[callback].name
            for callback in accepted_callbacks.values()
            if callback in func_by_id
        }),
        "routes": sorted(({
            "module": func_by_id[symbol].module_name
            or func_by_id[symbol].name,
            "symbol": symbol,
            "callback_module": (
                func_by_id[accepted_callbacks[symbol]].module_name
                or func_by_id[accepted_callbacks[symbol]].name),
            "callback_symbol": accepted_callbacks[symbol],
        } for symbol in accepted), key=lambda row: (
            row["callback_module"], row["module"])),
        "rounds": round_rows,
        "rejected_symbols": sorted(set(frontiers) - accepted),
    }, overlays
