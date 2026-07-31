"""Per-module and driver-level extraction quality metrics (plan Milestone 1).

Counts: total ops, symbolic/fixed/computed address counts, unknown (Top) value
count, condition/loop count, clang diagnostic count. Used by the readiness
scorer (Milestone 8) and the `metrics` CLI.
"""
from __future__ import annotations
from collections import Counter
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
        if re.fullmatch(r"[A-Za-z_]\w*->(?:flags|nr_ports)", value):
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
    # State and callback-result operations are semantic RIS leaves, but are not
    # hardware register accesses and must not inflate MMIO readiness metrics.
    semantic_only = {"StateRead", "StateWrite", "OutputWrite", "Return"}
    ops = [op for op in walk_leaf_ops(module["ops"])
           if not (semantic_only & set(op))]
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
    rescue = formal.get("metadata", {}).get("callee_rescue", {})
    agg["callee_rescue"] = {
        "candidates": rescue.get("candidates", 0),
        "rescued": rescue.get("rescued", 0),
        "retained_inlined": rescue.get("retained_inlined", 0),
        "rescued_direct_ops": rescue.get("rescued_direct_ops", 0),
        "rescue_mode": rescue.get("rescue_mode", "none"),
        "call_semantics_proven": (
            rescue.get("call_semantics_proven") is True),
        "semantics_complete": (
            rescue.get("call_semantics_proven") is True),
    }
    subsystem = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {})
    summaries = subsystem.get("summaries", {})
    unmodeled_callbacks = summaries.get(
        "unmodeled_callbacks", []) if isinstance(summaries, dict) else []
    synthesized_callbacks = subsystem.get("synthetic_functions", 0)
    agg["subsystem_summary"] = {
        "synthetic_functions": synthesized_callbacks,
        "generic_backend_unvalidated": synthesized_callbacks,
        "unmodeled_callbacks": len(unmodeled_callbacks),
        "unmodeled": unmodeled_callbacks,
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
    rescued_callees = met.get("callee_rescue", {}).get("rescued", 0)
    if rescued_callees:
        blockers.append(
            f"{rescued_callees} helper module(s) retained only for lexical "
            "access coverage; call semantics not proven")
    flattened_callees = met.get("callee_rescue", {}).get("candidates", 0)
    call_semantics_ready = met.get("callee_rescue", {}).get(
        "call_semantics_proven", False)
    if flattened_callees and not rescued_callees:
        blockers.append(
            f"{flattened_callees} inlined helper definition(s) lack "
            "call-context proof")
    unmodeled_subsystem = met.get("subsystem_summary", {}).get(
        "unmodeled_callbacks", 0)
    if unmodeled_subsystem:
        blockers.append(
            f"{unmodeled_subsystem} subsystem library callback(s) lack semantic summary")
    unvalidated_subsystem = met.get("subsystem_summary", {}).get(
        "generic_backend_unvalidated", 0)
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    gpio_source_required = bool(
        summary_groups.get("gpio_generic", [])
        if isinstance(summary_groups, dict) else [])
    sdhci_source_required = any(
        (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
         or {}).get("evidence", {}).get("subsystem_summary") == "sdhci_accessor"
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", [])))
    virtio_source_required = bool(
        summary_groups.get("virtio_state", [])
        if isinstance(summary_groups, dict) else [])
    w1c_drain_required = any(
        "Loop" in op and op["Loop"].get("proof_kind") == "masked_w1c_drain"
        for module in formal.get("modules", [])
        for op in walk_all_ops(module.get("ops", [])))
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

    supported_subsystem_access = any(
        (op.get("StateRead") or op.get("StateWrite") or {}).get(
            "evidence", {}).get("summary_contract") in {
                "linux.virtio_config", "linux.virtqueue"}
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", [])))
    has_register_access = (
        met["symbolic"] + met["fixed"] + met["computed"] > 0
        or supported_subsystem_access)
    if not has_register_access:
        blockers.append("no MMIO register accesses")

    accounting_ready = bool(accounting.get("strict_complete", False))
    callee_semantics_ready = call_semantics_ready
    path_ready = (bool(path_validation.get("complete", False))
                  and path_validation.get("infeasible", 0) == 0
                  and path_validation.get("nonexclusive_switch_pairs", 0) == 0)
    linux_subsystem_ready = unmodeled_subsystem == 0
    generic_subsystem_ready = (
        linux_subsystem_ready and unvalidated_subsystem == 0)
    harness_subsystem_ready = generic_subsystem_ready
    baremetal_subsystem_ready = generic_subsystem_ready
    baremetal_ready = (accounting_ready and callee_semantics_ready
                       and path_ready and has_register_access
                       and generic_subsystem_ready
                       and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                       and unsupported_ops == 0
                       and unsupported_control == 0
                       and met["conservative_loop"] == 0
                       and ris_quality >= 0.7)
    linux_ready = (accounting_ready and callee_semantics_ready
                   and path_ready and has_register_access
                   and linux_subsystem_ready
                   and met["unsafe_computed"] == 0
                   and met["unknown_value"] == 0
                   and unsupported_ops == 0
                   and unsupported_control == 0
                   and met["conservative_loop"] == 0
                   and function_spec_quality >= 0.6
                   and not unbound_callbacks)
    harness_ready = baremetal_ready  # trace check applied below if gen_results present

    # Tighten readiness with actual generated-code quality (recom.md §"Make
    # Readiness Scoring Stricter"): a backend is ready only if its generated C
    # compiles, has no TODOs, and (harness) passes RIS trace equivalence.
    if gen_results:
        # Backend strict readiness is an artifact claim, not an extraction
        # precondition.  Missing backend entries must therefore remain false
        # even when the RIS/DeviceSpec side looks complete.
        harness_ready = False
        baremetal_ready = False
        linux_ready = False

        def _gr(backend):
            return gen_results.get(backend, {})

        def _lowering_plan_ready(report):
            plan = report.get("backend_lowering_plan")
            lowering = report.get("backend_lowering")
            return bool(
                report.get("backend_lowering_plan_required") is True
                and isinstance(plan, dict)
                and isinstance(lowering, dict)
                and report.get("backend_lowering_complete") is True
                and report.get(
                    "backend_lowering_plan_accounting_complete") is True
                and report.get(
                    "backend_lowering_plan_classification_complete") is True
                and report.get(
                    "backend_lowering_plan_authorization_complete") is True
                and report.get(
                    "backend_lowering_plan_reconciliation_complete") is True
                and report.get(
                    "backend_lowering_plan_definition_alignment_complete")
                is True
                and report.get("backend_lowering_plan_strict_complete") is True
                and plan.get("reconciliation_performed") is True
                and plan.get("strict_complete") is True
                and lowering.get("complete") is True)

        def _sha256(value):
            return bool(
                isinstance(value, str) and len(value) == 64
                and all(char in "0123456789abcdef" for char in value))

        def _kbuild_context(value):
            return bool(
                isinstance(value, dict)
                and value.get("origin") == "kbuild-cmd"
                and isinstance(value.get("provenance"), str)
                and value.get("provenance")
                and _sha256(value.get("raw_command_sha256"))
                and _sha256(value.get("arguments_sha256"))
                and type(value.get("argument_count")) is int
                and value.get("argument_count") > 0)

        def _linux_ast_ready(report):
            ast = report.get("linux_ast_leaf")
            return bool(
                report.get("linux_ast_leaf_required") is True
                and report.get("linux_ast_leaf_complete") is True
                and isinstance(ast, dict)
                and ast.get("schema") == 1
                and ast.get("oracle") == "generated-c-ast-leaf-v1"
                and ast.get("complete") is True
                and _sha256(ast.get("generated_sha256"))
                and _kbuild_context(ast.get("compile_context"))
                and isinstance(ast.get("required_op_ids"), list)
                and ast.get("required_ast_ops") == len(
                    ast.get("required_op_ids")))

        def _linux_registration_ready(report):
            registration = report.get("linux_registration_ast")
            return bool(
                report.get("linux_registration_ast_required") is True
                and report.get("linux_registration_ast_complete") is True
                and isinstance(registration, dict)
                and registration.get("schema") == 1
                and registration.get("oracle") ==
                    "linux-registration-ast-v1"
                and registration.get("complete") is True
                and _sha256(registration.get("generated_sha256"))
                and _kbuild_context(registration.get("compile_context"))
                and isinstance(
                    registration.get("runtime_registered_op_ids"), list)
                and registration.get("runtime_registered_ops") == len(
                    registration.get("runtime_registered_op_ids")))

        def _linux_effective_plan_ready(report):
            plan = report.get("backend_lowering_plan")
            ast = report.get("linux_ast_leaf")
            registration = report.get("linux_registration_ast")
            if not all(isinstance(item, dict) for item in (
                    plan, ast, registration)):
                return False
            entries = plan.get("entries")
            strict_ids = plan.get("strict_eligible_op_ids")
            runtime_ids = plan.get("runtime_registered_op_ids")
            if not all(isinstance(item, list) for item in (
                    entries, strict_ids, runtime_ids)):
                return False
            entry_ids = [entry.get("op_id") for entry in entries
                         if isinstance(entry, dict)]
            if (len(entry_ids) != len(entries)
                    or len(set(entry_ids)) != len(entry_ids)
                    or set(strict_ids) != set(runtime_ids)
                    or len(set(strict_ids)) != len(strict_ids)):
                return False
            entries_by_id = {entry["op_id"]: entry for entry in entries}
            if any(
                    op_id not in entries_by_id
                    or entries_by_id[op_id].get("strict_eligible") is not True
                    or entries_by_id[op_id].get(
                        "runtime_registration_proven") is not True
                    or entries_by_id[op_id].get("ast_leaf_proven") is not True
                    or not isinstance(entries_by_id[op_id].get(
                        "registration_route_id"), str)
                    or not entries_by_id[op_id]["registration_route_id"]
                    for op_id in strict_ids):
                return False
            generated_sha = plan.get("runtime_generated_sha256")
            compile_context = plan.get("runtime_compile_context")
            return bool(
                report.get("backend_lowering_plan_required") is True
                and plan.get("schema") == 3
                and plan.get("oracle") == "backend-lowering-plan-v3"
                and plan.get("required_ops") == len(entries)
                and plan.get("strict_eligible_ops") == len(strict_ids)
                and plan.get("runtime_registered_ops") == len(runtime_ids)
                and registration.get("runtime_registered_op_ids") ==
                    runtime_ids
                and ast.get("required_op_ids") == strict_ids
                and _sha256(generated_sha)
                and ast.get("generated_sha256") == generated_sha
                and registration.get("generated_sha256") == generated_sha
                and _kbuild_context(compile_context)
                and ast.get("compile_context") == compile_context
                and registration.get("compile_context") == compile_context
                and report.get(
                    "backend_lowering_plan_runtime_complete") is True
                and report.get(
                    "backend_lowering_plan_strict_complete") is True
                and plan.get("runtime_attestation_valid") is True
                and plan.get("runtime_attestation_complete") is True
                and plan.get("linux_ast_leaf_valid") is True
                and plan.get("linux_ast_leaf_complete") is True
                and plan.get("runtime_artifact_authority_valid") is True
                and not plan.get("runtime_artifact_authority_errors")
                and not plan.get("runtime_attestation_errors")
                and not plan.get("linux_ast_leaf_errors")
                and plan.get("runtime_complete") is True
                and plan.get("strict_complete") is True)

        for backend in ("harness", "baremetal", "linux"):
            generated = _gr(backend)
            if not generated:
                blockers.append(
                    f"{backend} backend generation/attestation results "
                    "unavailable")
                continue
            if generated.get("backend_lowering_plan_required") is not True:
                blockers.append(
                    f"{backend} backend lowering/receipt attestation "
                    "unavailable")
            elif (generated.get("backend_lowering_plan_required")
                    and not generated.get(
                        "backend_lowering_plan_accounting_complete")):
                blockers.append(
                    f"{backend} backend lowering plan accounting failed")
            elif (generated.get("backend_lowering_plan_required")
                  and not generated.get(
                      "backend_lowering_plan_classification_complete")):
                blockers.append(
                    f"{backend} backend lowering plan classification failed")
            elif (generated.get("backend_lowering_plan_required")
                  and not generated.get(
                      "backend_lowering_plan_authorization_complete")):
                blockers.append(
                    f"{backend} backend lowering receipt authorization failed")
            elif (generated.get("backend_lowering_plan_required")
                  and not generated.get(
                      "backend_lowering_plan_reconciliation_complete")):
                blockers.append(
                    f"{backend} backend lowering receipt reconciliation failed")
            if backend == "linux":
                ast = generated.get("linux_ast_leaf")
                if (generated.get("linux_ast_leaf_required") is not True
                        or not isinstance(ast, dict)):
                    blockers.append(
                        "linux backend required-subset AST attestation "
                        "unavailable")
                elif not _linux_ast_ready(generated):
                    blockers.append(
                        "linux backend required-subset AST attestation failed")

                registration = generated.get("linux_registration_ast")
                if (generated.get("linux_registration_ast_required") is not True
                        or not isinstance(registration, dict)):
                    blockers.append(
                        "linux backend registration attestation unavailable")
                elif not _linux_registration_ready(generated):
                    blockers.append(
                        "linux backend registration attestation failed")

                plan = generated.get("backend_lowering_plan")
                if (generated.get("backend_lowering_plan_required") is not True
                        or not isinstance(plan, dict)
                        or plan.get("schema") != 3
                        or plan.get("oracle") != "backend-lowering-plan-v3"):
                    blockers.append(
                        "linux backend effective lowering plan v3 unavailable")
                elif not _linux_effective_plan_ready(generated):
                    blockers.append(
                        "linux backend effective lowering plan v3 strict proof "
                        "failed")
            lowering = generated.get("backend_lowering", {})
            if lowering and not lowering.get("complete", False):
                plan = generated.get("backend_lowering_plan") or {}
                blocked_ids = set(plan.get("blocked_op_ids") or [])
                missing = set(lowering.get("missing") or [])
                explained_missing = (
                    missing & blocked_ids
                    if plan.get("accounting_complete")
                    and plan.get("classification_complete") else set())
                unexplained_missing = missing - explained_missing
                if explained_missing:
                    entries = {
                        entry.get("op_id"): entry
                        for entry in plan.get("entries", [])
                        if isinstance(entry, dict)
                    }
                    dispositions = Counter(
                        (entries.get(op_id) or {}).get(
                            "disposition", "unknown")
                        for op_id in explained_missing)
                    descriptions = {
                        "blocked_unsupported_loop":
                            "unsupported loop lowering",
                        "blocked_linux_lifecycle_stub":
                            "a synthesized lifecycle stub",
                        "blocked_linux_lifecycle_unimplemented":
                            "an unimplemented lifecycle route",
                        "blocked_linux_root_unreachable":
                            "a missing Linux definition root",
                    }
                    for disposition, count in sorted(
                            dispositions.items()):
                        blockers.append(
                            f"{backend} backend has {count} register "
                            "operation(s) explicitly blocked by "
                            f"{descriptions.get(disposition, disposition)}")
                discrepancy = len(unexplained_missing) + sum(
                    len(lowering.get(key, [])) for key in (
                    "duplicate", "unknown", "rejected",
                    "digest_mismatch", "kind_mismatch",
                    "duplicate_expected_ids"))
                if discrepancy:
                    blockers.append(
                        f"{backend} backend has {discrepancy} unexplained "
                        "RIS lowering accounting discrepancy/discrepancies")
        h = _gr("harness")
        if h:
            h_source_ready = (not gpio_source_required or bool(
                h.get("gpio_mmio_source_oracle_passed")))
            h_source_ready &= (not sdhci_source_required or bool(
                h.get("sdhci_accessor_oracle_passed")))
            h_source_ready &= (not virtio_source_required or bool(
                h.get("virtio_state_oracle_passed")))
            h_source_ready &= (not w1c_drain_required or bool(
                h.get("w1c_drain_contract_passed")
                and h.get("w1c_drain_runtime_passed")))
            harness_subsystem_ready = bool(
                linux_subsystem_ready
                and (unvalidated_subsystem == 0
                     or h.get("subsystem_callback_oracle_passed"))
                and h_source_ready)
            harness_ready = bool(accounting_ready and callee_semantics_ready
                                 and path_ready and has_register_access
                                 and harness_subsystem_ready
                                 and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                                 and unsupported_ops == 0
                                 and unsupported_control == 0
                                 and met["conservative_loop"] == 0
                                 and _lowering_plan_ready(h)
                                 and h.get("backend_lowering_complete", True)
                                 and h.get("backend_ast_leaf_complete", False)
                                 and h.get("compiled") and h.get("trace_passed")
                                 and not h.get("has_todo")
                                 and not h.get("unsupported"))
        bm = _gr("baremetal")
        if bm:
            bm_source_ready = (not gpio_source_required or bool(
                bm.get("gpio_mmio_source_oracle_passed")))
            bm_source_ready &= (not sdhci_source_required or bool(
                bm.get("sdhci_accessor_oracle_passed")))
            bm_source_ready &= (not virtio_source_required or bool(
                bm.get("virtio_state_oracle_passed")))
            bm_source_ready &= (not w1c_drain_required or bool(
                bm.get("w1c_drain_contract_passed")
                and bm.get("w1c_drain_runtime_passed")))
            baremetal_subsystem_ready = bool(
                linux_subsystem_ready
                and (unvalidated_subsystem == 0
                     or bm.get("subsystem_callback_oracle_passed"))
                and bm_source_ready)
            baremetal_ready = bool(accounting_ready and callee_semantics_ready
                                   and path_ready and has_register_access
                                   and baremetal_subsystem_ready
                                   and met["unsafe_computed"] == 0 and met["unknown_value"] == 0
                                   and unsupported_ops == 0
                                   and unsupported_control == 0
                                   and met["conservative_loop"] == 0
                                   and _lowering_plan_ready(bm)
                                   and bm.get("backend_lowering_complete", True)
                                   and bm.get("backend_ast_leaf_complete", False)
                                   and bm.get("compiled") and not bm.get("has_todo")
                                   and not bm.get("unsupported"))
        for backend, report in (("harness", h), ("baremetal", bm)):
            if (report and report.get("backend_ast_leaf_required")
                    and not report.get("backend_ast_leaf_complete")):
                ast_leaf = report.get("backend_ast_leaf") or {}
                plan = report.get("backend_lowering_plan") or {}
                blocked_ids = set(plan.get("blocked_op_ids") or [])
                missing = set(ast_leaf.get("missing_anchors") or [])
                explained_missing = (
                    missing & blocked_ids
                    if plan.get("accounting_complete")
                    and plan.get("classification_complete") else set())
                unexplained = bool(missing - explained_missing)
                unexplained |= any(ast_leaf.get(key) for key in (
                    "duplicate_expected_ids", "parse_errors",
                    "duplicate_anchors", "unknown_anchors",
                    "malformed_anchors", "unsupported_expected_ops",
                    "primitive_mismatches", "unanchored_primitives"))
                if unexplained:
                    blockers.append(
                        f"{backend} backend generated-C AST primitive proof "
                        "failed outside planned loop blockers")
        lx = _gr("linux")
        if lx:
            linux_plan = lx.get("backend_lowering_plan") or {}
            if (linux_plan.get("definition_alignment_complete")
                    and not linux_plan.get("runtime_complete")
                    and linux_plan.get("strict_eligible_ops", 0)):
                unregistered = max(
                    0,
                    linux_plan.get("strict_eligible_ops", 0)
                    - linux_plan.get("runtime_registered_ops", 0),
                )
                blockers.append(
                    "linux backend has "
                    f"{unregistered} strict candidate operation(s) without "
                    "independent runtime "
                    "registration/callsite attestation")
            linux_source_ready = (not gpio_source_required or bool(
                lx.get("gpio_mmio_source_oracle_passed")))
            linux_source_ready &= (not sdhci_source_required or bool(
                lx.get("sdhci_accessor_oracle_passed")))
            linux_source_ready &= (not virtio_source_required or bool(
                lx.get("virtio_state_oracle_passed")))
            linux_source_ready &= (not w1c_drain_required or bool(
                lx.get("w1c_drain_contract_passed")))
            # Linux has source-aware class-specific lowerings (notably clock
            # models) that may faithfully preserve semantics a generic
            # harness/bare-metal backend cannot execute.  Judge the actual
            # generated Linux artifact directly instead of requiring generic
            # backend readiness as a prerequisite.
            linux_ready = bool(accounting_ready and callee_semantics_ready
                               and path_ready
                               and linux_subsystem_ready
                               and linux_source_ready
                               and met["unsafe_computed"] == 0
                               and met["unknown_value"] == 0
                               and unsupported_ops == 0
                               and unsupported_control == 0
                               and function_spec_quality >= 0.6
                               and not unbound_callbacks
                               and _lowering_plan_ready(lx)
                               and _linux_ast_ready(lx)
                               and _linux_registration_ready(lx)
                               and _linux_effective_plan_ready(lx)
                               and lx.get("backend_lowering_complete", True)
                               and not lx.get("has_todo")
                               and not lx.get("unsupported")
                               and lx.get("compiled", False)
                               and lx.get("syntax_ok", False)
                               and has_register_access)
            if lx.get("unsupported"):
                blockers.append("linux backend has unsupported semantic bindings")

        if gpio_source_required and not all(
                _gr(backend).get("gpio_mmio_source_oracle_passed", False)
                for backend in ("harness", "baremetal", "linux")):
            blockers.append(
                "gpio-mmio callbacks lack passing source differential oracle")
        if sdhci_source_required and not all(
                _gr(backend).get("sdhci_accessor_oracle_passed", False)
                for backend in ("harness", "baremetal", "linux")):
            blockers.append(
                "SDHCI accessors lack passing source contract oracle")
        if virtio_source_required and not all(
                _gr(backend).get("virtio_state_oracle_passed", False)
                for backend in ("harness", "baremetal", "linux")):
            blockers.append(
                "virtio state transitions lack passing source contract oracle")
        if w1c_drain_required and not (
                _gr("harness").get("w1c_drain_runtime_passed", False)
                and _gr("baremetal").get("w1c_drain_runtime_passed", False)
                and _gr("linux").get("w1c_drain_contract_passed", False)):
            blockers.append("W1C drain loop lacks contract/runtime oracle")
    else:
        harness_ready = False
        baremetal_ready = False
        linux_ready = False
        blockers.append(
            "generated backend compile/lowering/attestation results "
            "unavailable")

    if (unvalidated_subsystem
            and not (harness_subsystem_ready and baremetal_subsystem_ready)):
        blockers.append(
            f"{unvalidated_subsystem} synthesized subsystem callback(s) "
            "lack generic-backend execution oracle")

    # LLM synthesis gate (plan M9): artifacts sufficient to ask an LLM to
    # synthesize/repair a candidate under verification feedback. Distinct from
    # deterministic Linux readiness — does not require Linux gen to be complete.
    llm_synthesis_ready = (callee_semantics_ready
                           and ris_quality >= 0.7
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
