"""Per-module and driver-level extraction quality metrics (plan Milestone 1).

Counts: total ops, symbolic/fixed/computed address counts, unknown (Top) value
count, condition/loop count, clang diagnostic count. Used by the readiness
scorer (Milestone 8) and the `metrics` CLI.
"""
from __future__ import annotations
import re
from .formal import walk_leaf_ops, walk_all_ops


def count_clang_errors(warnings: list[str]) -> int:
    """Count only error/fatal libclang diagnostics (severity 3/4)."""
    return sum("clang diag[3]" in w or "clang diag[4]" in w for w in warnings)


def _addr_kind(addr: dict) -> str | None:
    if not addr:
        return None
    if "Symbolic" in addr:
        return "symbolic"
    if "Fixed" in addr:
        return "fixed"
    if "Computed" in addr:
        return "computed"
    return None


def _value_is_top(expr: dict | None) -> bool:
    if expr is None:
        return False
    return "Top" in expr


def _expr_has_top(expr: dict | None) -> bool:
    """True if the Expr contains any Top (unknown) sub-term."""
    if expr is None:
        return False
    if "Top" in expr:
        return True
    if "BinOp" in expr:
        b = expr["BinOp"]
        return _expr_has_top(b.get("left")) or _expr_has_top(b.get("right"))
    if "Ite" in expr:
        i = expr["Ite"]
        return (_expr_has_top(i.get("guard")) or _expr_has_top(i.get("then"))
                or _expr_has_top(i.get("else")))
    if "Bits" in expr:
        return _expr_has_top(expr["Bits"].get("expr"))
    return False


def _computed_is_lowerable(expr: dict | None) -> bool:
    """Whether all address terms can be emitted without approximation."""
    if not isinstance(expr, dict) or "Top" in expr:
        return False
    if "Const" in expr:
        return True
    if "Var" in expr:
        value = expr["Var"].strip()
        if re.fullmatch(r"[A-Za-z_]\w*", value):
            return True
        if re.fullmatch(r"sizeof\s+[A-Za-z_]\w*", value):
            return True
        if re.fullmatch(
                r"[A-Za-z_]\w*->(?:base|regs|ioaddr|hwirq|[A-Za-z_]\w*_base)",
                value):
            return True
        if re.fullmatch(
                r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
                r"(?:->|\.)hpi(?:->|\.)(?:base|regstep)", value):
            return True
        return False
    if "BinOp" in expr:
        b = expr["BinOp"]
        return (_computed_is_lowerable(b.get("left"))
                and _computed_is_lowerable(b.get("right")))
    if "Ite" in expr:
        i = expr["Ite"]
        return (_computed_is_lowerable(i.get("guard"))
                and _computed_is_lowerable(i.get("then"))
                and _computed_is_lowerable(i.get("else")))
    if "Bits" in expr:
        return _computed_is_lowerable(expr["Bits"].get("expr"))
    return False


def module_metrics(module: dict) -> dict:
    ops = list(walk_leaf_ops(module["ops"]))
    total = len(ops)
    sym = fixed = comp = unsafe_comp = rmw = 0
    unknown_val = 0
    for o in ops:
        addr = (o.get("Read") or o.get("Write") or o.get("ReadModifyWrite") or {}).get("addr")
        k = _addr_kind(addr)
        if k == "symbolic":
            sym += 1
        elif k == "fixed":
            fixed += 1
        elif k == "computed":
            comp += 1
            if not _computed_is_lowerable(addr.get("Computed")):
                unsafe_comp += 1
        if "ReadModifyWrite" in o:
            rmw += 1
        # unknown value: Write/RMW value or transform is Top or contains Top
        val = None
        if "Write" in o:
            val = o["Write"].get("value")
        elif "ReadModifyWrite" in o:
            val = o["ReadModifyWrite"].get("transform")
        if _value_is_top(val) or _expr_has_top(val):
            unknown_val += 1
    cond = sum(1 for o in walk_all_ops(module["ops"]) if "Cond" in o)
    loop_nodes = [o["Loop"] for o in walk_all_ops(module["ops"])
                  if "Loop" in o]
    loop = len(loop_nodes)
    conservative_loop = sum(
        node.get("reliability") != "Exact" or not node.get("bounded")
        for node in loop_nodes)
    addr_total = sym + fixed + comp
    return {
        "module": module["name"],
        "total_ops": total,
        "symbolic": sym,
        "fixed": fixed,
        "computed": comp,
        "unsafe_computed": unsafe_comp,
        "rmw": rmw,
        "unknown_value": unknown_val,
        "cond": cond,
        "loop": loop,
        "conservative_loop": conservative_loop,
        "pct_symbolic": round(sym / addr_total, 3) if addr_total else None,
    }


def driver_metrics(formal: dict, n_clang_diag: int = 0) -> dict:
    mods = [module_metrics(m) for m in formal["modules"]]
    agg = {k: 0 for k in ("total_ops", "symbolic", "fixed", "computed",
                           "unsafe_computed", "rmw", "unknown_value", "cond",
                           "loop", "conservative_loop")}
    for m in mods:
        for k in agg:
            agg[k] += m[k]
    addr_total = agg["symbolic"] + agg["fixed"] + agg["computed"]
    agg["pct_symbolic"] = round(agg["symbolic"] / addr_total, 3) if addr_total else None
    agg["pct_non_top_value"] = round(
        (agg["total_ops"] - agg["unknown_value"]) / agg["total_ops"], 3
    ) if agg["total_ops"] else None
    agg["clang_diag"] = n_clang_diag
    agg["modules"] = mods
    agg["register_map"] = len(formal.get("register_map", []))
    reliability = {"Exact": 0, "Conservative": 0, "Unknown": 0,
                   "Unsupported": 0}
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("Read") or op.get("Write")
                    or op.get("ReadModifyWrite"))
            if body is not None:
                level = body.get("reliability", "Unknown")
                reliability[level] = reliability.get(level, 0) + 1
    accounting = formal.get("metadata", {}).get("access_accounting", {})
    agg["reliability"] = reliability
    agg["access_accounting"] = {
        key: accounting.get(key, False if key in {"complete", "strict_complete"} else 0)
        for key in ("source_accesses", "emitted", "filtered",
                    "unsupported", "unaccounted",
                    "ris_ops_without_evidence", "complete", "strict_complete")
    }
    validation = formal.get("metadata", {}).get("path_validation", {})
    agg["path_validation"] = {
        key: validation.get(key, False if key == "complete" else 0)
        for key in ("complete", "satisfiable", "infeasible", "unknown")
    }
    agg["path_validation"]["nonexclusive_switch_pairs"] = sum(
        not pair.get("exclusive", False)
        for pair in validation.get("switch_pairs", []))
    control = formal.get("metadata", {}).get("control_accounting", {})
    agg["control_accounting"] = {
        "complete": control.get("complete", True),
        "modeled_early_returns": control.get("modeled_early_returns", 0),
        "assumed_framework_error_gotos": control.get(
            "assumed_framework_error_gotos", 0),
        "unsupported": control.get("unsupported", 0),
    }
    return agg


def format_metrics(metrics: dict) -> str:
    lines = [
        f"driver metrics: {metrics['total_ops']} ops | "
        f"symbolic {metrics['symbolic']} fixed {metrics['fixed']} computed {metrics['computed']} | "
        f"rmw {metrics['rmw']} unknown_value {metrics['unknown_value']} | "
        f"cond {metrics['cond']} loop {metrics['loop']} | "
        f"pct_symbolic {metrics['pct_symbolic']} pct_non_top {metrics['pct_non_top_value']} | "
        f"clang_diag {metrics['clang_diag']} | regs {metrics['register_map']}",
        "",
        f"{'module':<28} {'ops':>4} {'sym':>4} {'fix':>4} {'cmp':>4} {'unk':>4} {'cond':>4} {'loop':>4} {'%sym':>5}",
        "-" * 78,
    ]
    for m in metrics["modules"]:
        lines.append(
            f"{m['module']:<28} {m['total_ops']:>4} {m['symbolic']:>4} {m['fixed']:>4} "
            f"{m['computed']:>4} {m['unknown_value']:>4} {m['cond']:>4} {m['loop']:>4} "
            f"{str(m['pct_symbolic']):>5}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Generation readiness scoring (consolidated from readiness.py per plan)
# ═══════════════════════════════════════════════════════════════════
def score(device_spec, formal: dict, warnings: list[str], facts=None,
          gen_results: dict | None = None) -> dict:
    met = driver_metrics(formal, n_clang_diag=count_clang_errors(warnings))
    total_ops = met["total_ops"] or 1
    addr_total = met["symbolic"] + met["fixed"] + met["computed"] or 1

    safe_addresses = addr_total - met["unsafe_computed"]
    raw_ris_quality = (
        0.5 * (safe_addresses / addr_total)
        + 0.2 * (met["symbolic"] / addr_total)
        + 0.2 * ((total_ops - met["unknown_value"]) / total_ops)
        + 0.1 * (1.0 if met["computed"] == 0 else 0.5)
    )
    diagnostic_penalty = min(0.2, met["clang_diag"] * 0.01)
    ris_quality = round(max(0.0, raw_ris_quality - diagnostic_penalty), 3)

    fns = device_spec.functions
    with_role = sum(1 for f in fns if f.role and f.role not in ("unknown", "helper"))
    function_spec_quality = round(with_role / len(fns), 3) if fns else 0.0

    regs_mapped = len(formal.get("register_map", []))
    resources_resolved = sum(1 for r in device_spec.resources if r.bind or r.type.endswith("Resource"))
    device_spec_quality = round(
        0.5 * (min(regs_mapped, 8) / 8)
        + 0.3 * (resources_resolved / max(len(device_spec.resources), 1))
        + 0.2 * (1.0 if device_spec.state else 0.0),
        3,
    )

    # facts quality (plan M9) — enough source context to reconstruct backend glue
    if facts is not None:
        facts_quality = round(
            0.30 * (1.0 if facts.structs else 0.0)
            + 0.30 * (1.0 if facts.callbacks else 0.0)
            + 0.20 * (1.0 if facts.resources else 0.0)
            + 0.10 * (1.0 if facts.error_paths else 0.0)
            + 0.10 * (1.0 if facts.helper_calls else 0.0),
            3,
        )
    else:
        facts_quality = 0.0

    blockers: list[str] = []
    accounting = met.get("access_accounting", {})
    if accounting.get("unaccounted", 0):
        blockers.append(
            f"{accounting['unaccounted']} source MMIO access site(s) unaccounted")
    if accounting.get("ris_ops_without_evidence", 0):
        blockers.append(
            f"{accounting['ris_ops_without_evidence']} RIS operation(s) lack source evidence")
    if accounting.get("filtered", 0):
        blockers.append(
            f"{accounting['filtered']} source MMIO access site(s) explicitly filtered")
    if accounting.get("unsupported", 0):
        blockers.append(
            f"{accounting['unsupported']} source register/opaque access site(s) unsupported")
    path_validation = met.get("path_validation", {})
    if path_validation.get("unknown", 0):
        blockers.append(
            f"{path_validation['unknown']} path predicate(s) not SMT-validated")
    if path_validation.get("infeasible", 0):
        blockers.append(
            f"{path_validation['infeasible']} contradictory/infeasible RIS path(s)")
    if path_validation.get("nonexclusive_switch_pairs", 0):
        blockers.append(
            f"{path_validation['nonexclusive_switch_pairs']} switch path pair(s) not proven exclusive")
    unsupported_ops = met.get("reliability", {}).get("Unsupported", 0)
    if unsupported_ops:
        blockers.append(
            f"{unsupported_ops} register operation(s) use unsupported access domain")
    unsupported_control = met.get("control_accounting", {}).get("unsupported", 0)
    if unsupported_control:
        blockers.append(
            f"{unsupported_control} unsupported control-flow transfer(s)")
    if met["unsafe_computed"] > 0:
        blockers.append(
            f"{met['unsafe_computed']} unsafe dynamic register address(es) "
            f"({met['computed']} computed total)")
    if met["unknown_value"] > 0:
        blockers.append(f"{met['unknown_value']} unknown (Top) value(s)")
    if met["clang_diag"] > 0:
        blockers.append(f"{met['clang_diag']} clang error diagnostic(s)")
    if met["conservative_loop"] > 0:
        blockers.append(
            f"{met['conservative_loop']} conservative loop summary/summaries require validation")
    unroled = [f.name for f in fns if f.role in ("unknown",)]
    if unroled:
        blockers.append(f"missing role for: {', '.join(unroled)}")

    callback_entries = [f for f in fns if f.is_callback_entry]
    unbound_callbacks = [f.name for f in callback_entries if not f.callback_table]
    if unbound_callbacks:
        blockers.append(f"callback entry without table binding: {', '.join(unbound_callbacks)}")

    has_register_access = (
        met["symbolic"] + met["fixed"] + met["computed"] > 0)
    if not has_register_access:
        blockers.append("no MMIO register accesses")

    accounting_ready = bool(accounting.get("strict_complete", False))
    path_ready = (bool(path_validation.get("complete", False))
                  and path_validation.get("infeasible", 0) == 0
                  and path_validation.get("nonexclusive_switch_pairs", 0) == 0)
    baremetal_ready = (accounting_ready and path_ready
                       and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                       and unsupported_ops == 0
                       and unsupported_control == 0
                       and met["conservative_loop"] == 0
                       and ris_quality >= 0.7)
    linux_ready = (baremetal_ready and function_spec_quality >= 0.6
                   and not unbound_callbacks and has_register_access)
    harness_ready = baremetal_ready  # trace check applied below if gen_results present

    # Tighten readiness with actual generated-code quality (recom.md §"Make
    # Readiness Scoring Stricter"): a backend is ready only if its generated C
    # compiles, has no TODOs, and (harness) passes RIS trace equivalence.
    if gen_results:
        def _gr(backend):
            return gen_results.get(backend, {})
        h = _gr("harness")
        if h:
            harness_ready = bool(accounting_ready and path_ready
                                 and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                                 and unsupported_control == 0
                                 and met["conservative_loop"] == 0
                                 and h.get("compiled") and h.get("trace_passed")
                                 and not h.get("has_todo")
                                 and not h.get("unsupported"))
        bm = _gr("baremetal")
        if bm:
            baremetal_ready = bool(accounting_ready and path_ready
                                   and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                                   and unsupported_control == 0
                                   and met["conservative_loop"] == 0
                                   and bm.get("compiled") and not bm.get("has_todo")
                                   and not bm.get("unsupported"))
        lx = _gr("linux")
        if lx:
            # Linux has source-aware class-specific lowerings (notably clock
            # models) that may faithfully preserve semantics a generic
            # harness/bare-metal backend cannot execute.  Judge the actual
            # generated Linux artifact directly instead of requiring generic
            # backend readiness as a prerequisite.
            linux_ready = bool(accounting_ready and path_ready
                               and met["unsafe_computed"] == 0
                               and met["unknown_value"] == 0
                               and unsupported_ops == 0
                               and unsupported_control == 0
                               and function_spec_quality >= 0.6
                               and not unbound_callbacks
                               and not lx.get("has_todo")
                               and not lx.get("unsupported")
                               and lx.get("compiled", False)
                               and lx.get("syntax_ok", False)
                               and has_register_access)
            if lx.get("unsupported"):
                blockers.append("linux backend has unsupported semantic bindings")

    # LLM synthesis gate (plan M9): artifacts sufficient to ask an LLM to
    # synthesize/repair a candidate under verification feedback. Distinct from
    # deterministic Linux readiness — does not require Linux gen to be complete.
    llm_synthesis_ready = (ris_quality >= 0.7
                           and function_spec_quality >= 0.5
                           and facts_quality >= 0.6
                           and len(device_spec.registers) > 0)

    return {
        "ris_quality": ris_quality,
        "function_spec_quality": function_spec_quality,
        "device_spec_quality": device_spec_quality,
        "facts_quality": facts_quality,
        "backend_harness_ready": harness_ready,
        "backend_bare_metal_ready": baremetal_ready,
        "backend_linux_ready": linux_ready,
        "llm_synthesis_ready": llm_synthesis_ready,
        "blockers": blockers,
    }


def format_score(s: dict) -> str:
    lines = ["generation_readiness:"]
    for k in ("ris_quality", "function_spec_quality", "device_spec_quality",
              "facts_quality"):
        lines.append(f"  {k}: {s[k]}")
    lines.append(f"  backend_harness_ready: {s['backend_harness_ready']}")
    lines.append(f"  backend_bare_metal_ready: {s['backend_bare_metal_ready']}")
    lines.append(f"  backend_linux_ready: {s['backend_linux_ready']}")
    lines.append(f"  llm_synthesis_ready: {s['llm_synthesis_ready']}")
    if s["blockers"]:
        lines.append("  blockers:")
        for b in s["blockers"]:
            lines.append(f"    - {b}")
    else:
        lines.append("  blockers: []")
    return "\n".join(lines)
