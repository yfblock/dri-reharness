"""Call graph + wrapper-function inlining.

Pass 1: extract each target function's own (direct) MMIO ops.
Pass 2: build the call graph; for each function, inline callees that are
themselves target functions with MMIO ops (depth-limited, recursion-safe).
"""
from __future__ import annotations
import copy
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from .ast_model import (
    Func, callback_entry_symbols, function_calls, source_text,
    walk_with_control,
)
from .dataflow import extract_function, FuncExtraction
from .wrappers import infer_wrapper_summaries
from .wrappers import _candidate_functions
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
            parameter_cursors = []
            if callee.cursor is not None:
                parameter_cursors = [
                    child for child in callee.cursor.get_children()
                    if child.kind.name == "PARM_DECL"]
            for index, expression in enumerate(call.arg_text):
                parameter = callee.params[index] if index < len(callee.params) \
                    else (None, None)
                parameter_cursor = (
                    parameter_cursors[index]
                    if index < len(parameter_cursors) else None)
                parameter_canonical_type = (
                    parameter_cursor.type.get_canonical().spelling
                    if parameter_cursor is not None and parameter_cursor.type
                    else parameter[1])
                argument_canonical_type = (
                    call.args[index].type.get_canonical().spelling
                    if index < len(call.args) and call.args[index].type
                    else "")
                arguments.append({
                    "index": index,
                    "expression": expression.strip(),
                    "parameter": parameter[0],
                    "parameter_type": parameter[1],
                    "parameter_canonical_type": parameter_canonical_type,
                    "argument_type": (
                        call.args[index].type.get_canonical().spelling),
                    "argument_canonical_type": argument_canonical_type,
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


def _op_site(op) -> tuple[str, str] | None:
    evidence = op.evidence or {}
    owner = evidence.get("symbol")
    site_id = evidence.get("site_id")
    if not isinstance(owner, str) or not owner:
        return None
    if not isinstance(site_id, str) or not site_id:
        return None
    return owner, site_id


def _op_occurrence(op) -> tuple:
    evidence = op.evidence or {}
    path = tuple(
        (item.get("function"), item.get("line"), item.get("callee"),
         item.get("indirect_expression"))
        for item in evidence.get("inlined_at", [])
        if isinstance(item, dict)
    )
    return (
        _op_site(op), path, op.kind, repr(op.addr), op.width, op.value,
        op.condition, tuple(op.cond_stack), repr(op.control_stack), op.var,
    )


def _with_ops(extraction: FuncExtraction, ops: list) -> FuncExtraction:
    return FuncExtraction(
        name=extraction.name,
        params=list(extraction.params),
        return_expr=extraction.return_expr,
        return_read_var=extraction.return_read_var,
        ops=list(ops),
        calls=list(extraction.calls),
        warnings=list(extraction.warnings),
    )


def _eligible_call_edges(calls: list[dict]) -> set[tuple[str, str]]:
    """Return exact, non-recursive edges suitable for frontier propagation."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for call in calls:
        caller = call.get("caller_usr")
        callee = call.get("callee_usr")
        if isinstance(caller, str) and isinstance(callee, str):
            grouped[(caller, callee)].append(call)

    candidates = {
        edge for edge, rows in grouped.items()
        if edge[0] != edge[1] and rows
        and all(_call_row_is_proven(row) for row in rows)
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for caller, callee in candidates:
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

    return {
        edge for edge in candidates
        if not reaches(edge[1], edge[0])
    }


def _type_is_scalar(type_name: str) -> bool:
    """Recognize C scalar types for which the call conversion is defined."""
    normalized = " ".join(type_name.replace("*", " ").split())
    return bool(re.fullmatch(
        r"(?:(?:const|volatile|restrict|signed|unsigned|short|long|long long|\s)*)"
        r"(?:void|_Bool|char|short|int|long|long long|float|double|long double|"
        r"u(?:8|16|32|64)|s(?:8|16|32|64)|__u(?:8|16|32|64)|"
        r"__le(?:16|32|64)|__be(?:16|32|64)|size_t)",
        normalized))


def _types_compatible(parameter_type: str, argument_type: str) -> bool:
    """Return whether Clang's argument-to-parameter conversion is provable.

    Canonical Clang types are equal for the common case.  C also defines the
    conversion between arithmetic scalar types and between ``void *`` and an
    object pointer; accepting only those standard conversions keeps argument
    substitution precise without pretending that unrelated pointer types or
    opaque aggregates are interchangeable.
    """
    parameter = " ".join(parameter_type.split())
    argument = " ".join(argument_type.split())
    if parameter == argument:
        return True
    parameter_pointer = "*" in parameter
    argument_pointer = "*" in argument
    if parameter_pointer and argument_pointer:
        parameter_base = parameter.replace("*", " ").split()
        argument_base = argument.replace("*", " ").split()
        return "void" in parameter_base or "void" in argument_base
    return (not parameter_pointer and not argument_pointer
            and _type_is_scalar(parameter)
            and _type_is_scalar(argument))


_LOOP_INIT_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*=\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*$")
_LOOP_GUARD_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(<|<=)\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\s*$")
_LOOP_STEP_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(\+\+|\+=\s*1)\s*$")


def _literal_int(text: str) -> int | None:
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        return None


def _loop_executes_exactly_once(frame: dict) -> bool:
    """Prove the narrow static loop shape that has one invocation."""
    if frame.get("kind") != "loop" or frame.get("loop_kind") != "for":
        return False
    init = _LOOP_INIT_RE.fullmatch(frame.get("init", ""))
    guard = _LOOP_GUARD_RE.fullmatch(frame.get("guard", ""))
    step = _LOOP_STEP_RE.fullmatch(frame.get("step", ""))
    if not init or not guard or not step:
        return False
    variable, start_text = init.groups()
    guard_variable, relation, bound_text = guard.groups()
    step_variable, _step = step.groups()
    if variable != guard_variable or variable != step_variable:
        return False
    start = _literal_int(start_text)
    bound = _literal_int(bound_text)
    if start is None or bound is None:
        return False
    count = bound - start + (1 if relation == "<=" else 0)
    return count == 1


def _call_row_is_proven(call: dict, *, allow_structured_loops: bool = False) -> bool:
    """Check one AST call row before it participates in a proof.

    Frontier propagation needs a runtime-exact call count, so it keeps the
    default strict loop rule.  Call-context ownership is a separate proof:
    an operation inside a preserved structured loop has one static callsite
    even when its runtime iteration count is data-dependent.
    """
    if call.get("resolution_authority") not in {
            "direct_function_declaration", "static_indirect_target"}:
        return False
    if (call.get("return_binding") or {}).get("status") != "exact":
        return False
    multiplicity = call.get("multiplicity") or {}
    if (multiplicity.get("kind") != "syntactic_callsite"
            or multiplicity.get("per_caller_invocation") != 1):
        return False
    if any((frame or {}).get("kind") == "loop"
           and not allow_structured_loops
           and not _loop_executes_exactly_once(frame)
           for frame in call.get("control") or []):
        return False
    arguments = call.get("argument_mapping")
    if not isinstance(arguments, list):
        return False
    for argument in arguments:
        if not isinstance(argument, dict):
            return False
        if not all(isinstance(argument.get(key), str)
                   and bool(argument.get(key))
                   for key in ("parameter", "parameter_type", "argument_type")):
            return False
        parameter_type = (argument.get("parameter_canonical_type")
                          or argument["parameter_type"])
        argument_type = (argument.get("argument_canonical_type")
                         or argument["argument_type"])
        if not _types_compatible(parameter_type, argument_type):
            return False
    return True


def _definition_site(op) -> tuple[str, str] | None:
    """Return the primitive definition site through wrapper summaries."""
    evidence = op.evidence or {}
    while isinstance(evidence.get("wrapper_definition"), dict):
        evidence = evidence["wrapper_definition"]
    owner = evidence.get("symbol")
    site_id = evidence.get("site_id")
    if not isinstance(owner, str) or not owner:
        return None
    if not isinstance(site_id, str) or not site_id:
        return None
    return owner, site_id


def _register_ops(extraction: FuncExtraction | None) -> list:
    if extraction is None:
        return []
    return [op for op in extraction.ops if op.kind in {
        "Read", "Write", "ReadModifyWrite", "TransactionRead",
        "TransactionWrite", "TransactionUpdate",
    }]


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
    """
    candidates = set(candidates)
    if not candidates:
        return {"proven": True, "reason": "no_inlined_candidates"}

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
    for root in roots:
        for op in _register_ops(expanded.get(root)):
            site = _definition_site(op)
            if site is not None and site[0] in candidates:
                actual[site] += 1

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
         repr((op.evidence or {}).get("inlined_at", [])),
         repr(op.transaction))
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
        if op.kind not in {
                "Read", "Write", "ReadModifyWrite", "TransactionRead",
                "TransactionWrite", "TransactionUpdate"}:
            continue
        evidence = op.evidence or {}
        # A summarized wrapper operation has callsite evidence at the current
        # caller and definition evidence for the actual primitive access. For
        # coverage/deduplication, only the latter identifies the hardware site;
        # otherwise every wrapper layer appears to be a distinct register op.
        while isinstance(evidence.get("wrapper_definition"), dict):
            evidence = evidence["wrapper_definition"]
        site_id = evidence.get("site_id")
        owner = evidence.get("symbol")
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
        if op.kind not in {
                "Read", "Write", "ReadModifyWrite", "TransactionRead",
                "TransactionWrite", "TransactionUpdate"}:
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
    base = build_inline_cache(
        _candidate_functions(funcs), macros, tu, source_lines, mmio_globals, mmio_alias_facts,
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
