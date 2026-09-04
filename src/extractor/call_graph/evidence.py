"""Definition-site evidence, coverage accounting, and rescue frontiers."""
from __future__ import annotations

from ..dataflow import FuncExtraction
from .. import mmio


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
    subsystem_covered_names: set[str] = set()
    for symbol, extraction in expanded.items():
        if symbol in candidates:
            continue
        base_covered |= _evidence_sites(extraction)[0]
        # A caller op whose evidence came from a subsystem accessor contract
        # reproduces that accessor's whole body (the layout IS the body
        # contract), so the header helper itself needs no retained module.
        # Restrict to names the mmio layer actually models — anything else
        # keeps its definition-frontier module and stays fail-closed.
        for op in extraction.ops:
            evidence = op.evidence or {}
            if evidence.get("origin") != "subsystem_summary":
                continue
            short = (evidence.get("site_id") or "").rsplit(":", 1)[-1]
            if (short in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
                    or short in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS):
                subsystem_covered_names.add(short)
    required = set().union(*direct_sites.values()) if direct_sites else set()
    subsystem_covered = {
        symbol for symbol in candidates
        if symbol.rsplit("::", 1)[-1] in subsystem_covered_names}

    rescued = {
        symbol for symbol in candidates
        if symbol in unproven or not (
            direct_sites[symbol] <= base_covered
            or symbol in subsystem_covered)
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
    # Subsystem-covered accessor helpers are exempt: their contract is
    # reproduced by the caller's subsystem-summary op, which never carries
    # the helper's definition site.
    for symbol in sorted(candidates - subsystem_covered):
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
        # Bounded helper flattening alone has no independent callsite,
        # argument, guard, fanout or recursion proof, so this statistic is
        # fail-closed by default.  The caller flips it only after
        # _prove_inlined_call_context (per-hop cited call rows plus exact
        # static path counts) succeeds; residual value-substitution
        # equivalence remains covered by row-level type/argument checks.
        "call_semantics_proven": False,
        "rescued_symbols": sorted(rescued),
        "unproven_symbols": sorted(unproven),
    }, frontiers
