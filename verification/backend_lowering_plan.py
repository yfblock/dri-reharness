#!/usr/bin/env python3
"""Build and verify a fail-closed backend lowering plan from Formal RIS.

The oracle is deliberately independent of backend generators.  It accounts
for every Formal register operation, authorizes lowering receipts only for
canonical definition-emission routes, and keeps Linux runtime registration as
a separate (currently unproved) property.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import copy
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractor.spec import device_spec_from_dict


SUPPORTED_BACKENDS = {"harness", "baremetal", "linux"}
REGISTER_KINDS = ("Read", "Write", "ReadModifyWrite")
DISPOSITIONS = {
    "lowered",
    "candidate_definition_emit",
    "definition_evidence_only",
    "blocked_unsupported_loop",
    "blocked_linux_lifecycle_stub",
    "blocked_linux_lifecycle_unimplemented",
    "blocked_linux_root_unreachable",
}
BLOCKED_DISPOSITIONS = {
    "blocked_unsupported_loop",
    "blocked_linux_lifecycle_stub",
    "blocked_linux_lifecycle_unimplemented",
    "blocked_linux_root_unreachable",
}
AUTHORIZED_DISPOSITIONS = {
    "lowered", "candidate_definition_emit", "definition_evidence_only",
}
STRICT_ELIGIBLE_DISPOSITIONS = {"lowered", "candidate_definition_emit"}
SCHEMA = 2
ORACLE = "backend-lowering-plan-v2"


def _register_kind(op: dict) -> str | None:
    return next((kind for kind in REGISTER_KINDS if kind in op), None)


def _loop_lowering_mode(loop: dict) -> str | None:
    """Return the exact lowering mode independently mirrored from policy."""
    if (loop.get("reliability") == "Exact"
            and loop.get("bounded")
            and loop.get("loop_kind") == "for"):
        return "bounded_for"
    if (loop.get("reliability") == "Exact"
            and loop.get("proof_kind") == "masked_w1c_drain"):
        return "masked_w1c_drain"
    return None


def _loop_context(loop: dict, depth: int, region: str) -> dict[str, Any]:
    mode = _loop_lowering_mode(loop)
    # A bounded-for backend lowers its body, but has no independent guard_ops
    # lowering.  Masked W1C drain loops lower both guard_ops and body.
    region_lowerable = bool(
        mode == "masked_w1c_drain"
        or (mode == "bounded_for" and region == "body"))
    return {
        "depth": depth,
        "region": region,
        "loop_kind": loop.get("loop_kind", "loop"),
        "reliability": loop.get("reliability"),
        "bounded": bool(loop.get("bounded")),
        "dynamic_bound": bool(loop.get("dynamic_bound")),
        "proof_kind": loop.get("proof_kind"),
        "lowering_mode": mode,
        "region_lowerable": region_lowerable,
        "guard": copy.deepcopy(loop.get("guard")),
        "count": copy.deepcopy(loop.get("count")),
        "init": loop.get("init"),
        "step": loop.get("step"),
    }


def _blocked_loop_reason(loop: dict) -> str:
    if (loop.get("lowering_mode") == "bounded_for"
            and loop.get("region") == "guard_ops"):
        return "bounded for-loop guard_ops are not lowered by backend policy"
    return (
        f"enclosing {loop.get('loop_kind', 'loop')} loop is not proven "
        "lowerable by backend policy "
        f"(reliability={loop.get('reliability')!r}, "
        f"bounded={loop.get('bounded')!r}, "
        f"proof_kind={loop.get('proof_kind')!r})")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _device_functions(device_spec: Any) -> list[Any]:
    if device_spec is None:
        raise ValueError("Linux backend lowering plan requires a DeviceSpec")
    functions = _get(device_spec, "functions")
    if not isinstance(functions, list):
        raise ValueError("DeviceSpec has no functions list")
    return functions


def _callback(function: Any) -> str | None:
    is_callback_entry = _get(function, "is_callback_entry")
    if type(is_callback_entry) is not bool:
        raise ValueError(
            "DeviceSpec function has no boolean is_callback_entry")
    value = _get(function, "callback_table")
    if value is None:
        value = _get(function, "callback")
    callback = value if isinstance(value, str) and value else None
    if callback is not None and not is_callback_entry:
        raise ValueError(
            "DeviceSpec callback ownership contradicts is_callback_entry")
    return callback


def _linux_routes(device_spec: Any) -> dict[str, dict[str, Any]]:
    """Index DeviceSpec functions without importing generator code."""
    routes: dict[str, dict[str, Any]] = {}
    for index, function in enumerate(_device_functions(device_spec)):
        name = _get(function, "name")
        ris_ref = _get(function, "ris_ref")
        module = ris_ref if isinstance(ris_ref, str) and ris_ref else name
        if not isinstance(module, str) or not module:
            raise ValueError(f"DeviceSpec function {index} has no name/ris_ref")
        if module in routes:
            raise ValueError(f"ambiguous DeviceSpec route for {module!r}")
        role = _get(function, "role", "unknown")
        routes[module] = {
            "kind": "device_spec_function",
            "role": role if isinstance(role, str) and role else "unknown",
            "callback": _callback(function),
            "function": name if isinstance(name, str) else None,
            "provenance": ("device_spec.functions[].ris_ref"
                           if isinstance(ris_ref, str) and ris_ref
                           else "device_spec.functions[].name"),
        }
    return routes


def _private_multisource_evidence_functions(formal: dict) -> set[str]:
    metadata = formal.get("metadata") or {}
    sources = metadata.get("sources") or []
    bindings = ((metadata.get("callback_binding_analysis") or {})
                .get("bindings") or [])
    if not isinstance(sources, list) or len(sources) <= 1:
        return set()
    return {
        row.get("function") for row in bindings
        if isinstance(row, dict)
        and isinstance(row.get("function"), str)
        and row.get("role") == "unknown"
        and row.get("public_callback_type") is False
    }


def _harness_route(module_name: str | None) -> dict[str, Any]:
    return {
        "kind": "formal_definition",
        "role": None,
        "callback": None,
        "function": module_name,
        "provenance": "formal.modules[].name",
    }


def _linux_disposition(
        module_name: str | None, route: dict[str, Any] | None,
        evidence_only: set[str], blocking_loop: dict | None,
        ) -> tuple[str, str | None]:
    # Precedence is deliberately loop > lifecycle > root.
    if blocking_loop is not None:
        return "blocked_unsupported_loop", _blocked_loop_reason(blocking_loop)
    callback = (route or {}).get("callback")
    if callback == "platform_driver.remove":
        return (
            "blocked_linux_lifecycle_stub",
            "Linux remove lifecycle route is emitted only as a backend stub",
        )
    if callback == "platform_driver.shutdown":
        return (
            "blocked_linux_lifecycle_unimplemented",
            "Linux shutdown lifecycle route is not implemented by the backend",
        )
    role = (route or {}).get("role")
    definition_route = route is not None and (role == "probe" or callback)
    if definition_route and module_name in evidence_only:
        return (
            "definition_evidence_only",
            "private unknown callback in multi-source Formal metadata proves "
            "definition preservation only",
        )
    if definition_route:
        return (
            "candidate_definition_emit",
            "DeviceSpec identifies a definition-emission candidate; runtime "
            "registration remains independently unproved",
        )
    return (
        "blocked_linux_root_unreachable",
        "no DeviceSpec probe/callback definition route reaches this module",
    )


def _authorization_fields(disposition: str, backend: str) -> dict[str, Any]:
    authorized = disposition in AUTHORIZED_DISPOSITIONS
    strict_eligible = disposition in STRICT_ELIGIBLE_DISPOSITIONS
    return {
        "receipt_authorized": authorized,
        "strict_eligible": strict_eligible,
        # H/B do not make Linux registration claims.  Every Linux candidate is
        # conservative until a separate registration attestation exists.
        "runtime_registration_proven": (
            False if backend == "linux" and authorized else None),
    }


def _plan_module_ops(
        module: dict, backend: str, route: dict[str, Any] | None,
        evidence_only: set[str],
        ) -> list[dict]:
    entries: list[dict] = []
    module_name = module.get("name")
    entry_route = (copy.deepcopy(route) if backend == "linux"
                   else _harness_route(module_name))
    if backend == "linux" and entry_route is None:
        entry_route = {
            "kind": "unmatched_formal_definition",
            "role": None,
            "callback": None,
            "function": module_name,
            "provenance": "formal.modules[].name",
        }

    def walk(ops: list, enclosing_loops: list[dict]) -> None:
        for op in ops or []:
            kind = _register_kind(op)
            if kind is not None:
                body = op.get(kind) or {}
                blockers = [loop for loop in enclosing_loops
                            if not loop.get("region_lowerable")]
                blocking_loop = copy.deepcopy(blockers[0]) if blockers else None
                if backend == "linux":
                    disposition, reason = _linux_disposition(
                        module_name, route, evidence_only, blocking_loop)
                elif blocking_loop:
                    disposition = "blocked_unsupported_loop"
                    reason = _blocked_loop_reason(blocking_loop)
                else:
                    disposition, reason = "lowered", None
                entry = {
                    "module": module_name,
                    "op_id": body.get("op_id"),
                    "kind": kind,
                    "disposition": disposition,
                    "reason": reason,
                    "route": copy.deepcopy(entry_route),
                    "enclosing_loops": copy.deepcopy(enclosing_loops),
                    "blocking_loop": blocking_loop,
                }
                entry.update(_authorization_fields(disposition, backend))
                entries.append(entry)
                continue
            if "Cond" in op:
                cond = op.get("Cond") or {}
                walk(cond.get("then_ops") or [], enclosing_loops)
                walk(cond.get("else_ops") or [], enclosing_loops)
            elif "Seq" in op:
                walk((op.get("Seq") or {}).get("ops") or [], enclosing_loops)
            elif "Loop" in op:
                loop = op.get("Loop") or {}
                depth = len(enclosing_loops) + 1
                walk(loop.get("guard_ops") or [], [
                    *enclosing_loops, _loop_context(loop, depth, "guard_ops")])
                walk(loop.get("body") or [], [
                    *enclosing_loops, _loop_context(loop, depth, "body")])

    walk(module.get("ops") or [], [])
    return entries


def _summary(entries: list[dict]) -> dict[str, Any]:
    counts = Counter(entry["disposition"] for entry in entries)
    return {
        "planned_ops": len(entries),
        # Preserve the v1 H/B summary fields while exposing the full v2
        # disposition partition below.
        "lowered": counts["lowered"],
        "blocked_unsupported_loop": counts["blocked_unsupported_loop"],
        "authorized_ops": sum(bool(entry["receipt_authorized"])
                              for entry in entries),
        "strict_eligible_ops": sum(bool(entry["strict_eligible"])
                                   for entry in entries),
        "blocked_ops": sum(counts[name] for name in BLOCKED_DISPOSITIONS),
        "disposition_counts": {
            name: counts[name] for name in sorted(DISPOSITIONS)
        },
    }


def build_backend_lowering_plan(
        formal: dict, backend: str, device_spec: Any = None) -> dict:
    """Return the canonical Formal/DeviceSpec-derived backend plan."""
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"backend lowering plan v2 does not support backend {backend!r}")
    modules = formal.get("modules")
    if not isinstance(modules, list):
        raise ValueError("Formal RIS has no modules list")
    if backend == "linux":
        device_name = _get(device_spec, "name")
        formal_driver = formal.get("driver")
        if not isinstance(device_name, str) or not device_name:
            raise ValueError("DeviceSpec has no driver name")
        if device_name != formal_driver:
            raise ValueError(
                "DeviceSpec driver does not match Formal driver: "
                f"{device_name!r} != {formal_driver!r}")
        routes = _linux_routes(device_spec)
    else:
        routes = {}
    evidence_only = (_private_multisource_evidence_functions(formal)
                     if backend == "linux" else set())
    entries = [
        entry
        for module in modules
        for entry in _plan_module_ops(
            module, backend, routes.get(module.get("name")), evidence_only)
    ]
    return {
        "schema": SCHEMA,
        "oracle": ORACLE,
        "driver": formal.get("driver"),
        "backend": backend,
        "policy": {
            "semantic_authority": (
                "canonical-formal-ris-plus-device-spec"
                if backend == "linux" else "canonical-formal-ris"),
            "cardinality": "exactly-once",
            "authorization_axis": "definition-receipt",
            "runtime_axis": "independent-registration-attestation",
            "blocked_entries_authorize_receipts": False,
            "linux_precedence": ["loop", "lifecycle", "root"],
            "supported_backends": sorted(SUPPORTED_BACKENDS),
            "supported_loop_modes": ["bounded_for", "masked_w1c_drain"],
        },
        "entries": entries,
        "summary": _summary(entries),
    }


def _rows(document: dict, key: str) -> list[dict]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"document has no {key} list")
    return rows


def _invalid_or_duplicate_ids(rows: list[dict]) -> list[str]:
    ids = [row.get("op_id") for row in rows]
    counts = Counter(ids)
    return sorted(
        "<missing>" if op_id is None else str(op_id)
        for op_id, count in counts.items()
        if not isinstance(op_id, str) or not op_id or count != 1)


def _unique_by_id(rows: list[dict]) -> dict[str, dict]:
    counts = Counter(row.get("op_id") for row in rows)
    return {
        row["op_id"]: row for row in rows
        if isinstance(row.get("op_id"), str)
        and row.get("op_id")
        and counts[row["op_id"]] == 1
    }


def _entry_shape(entry: dict) -> dict:
    return {
        key: copy.deepcopy(entry.get(key))
        for key in (
            "module", "op_id", "kind", "disposition", "reason", "route",
            "receipt_authorized", "strict_eligible",
            "runtime_registration_proven", "enclosing_loops",
            "blocking_loop",
        )
    }


def _plan_envelope(plan: dict) -> dict:
    return {
        key: copy.deepcopy(plan.get(key))
        for key in ("schema", "oracle", "driver", "backend", "policy", "summary")
    }


def _report_id_set(report: dict, key: str) -> tuple[set[str], bool]:
    value = report.get(key)
    if not isinstance(value, list):
        return set(), False
    ids: set[str] = set()
    valid = True
    for row in value:
        op_id = row if isinstance(row, str) else None
        if not isinstance(op_id, str) or not op_id:
            valid = False
        elif op_id in ids:
            valid = False
        else:
            ids.add(op_id)
    return ids, valid


def _reconcile_lowering_report(
        report: dict | None, contract_ids: set[str], authorized_ids: set[str],
        blocked_ids: set[str], required_ops: int,
        ) -> dict[str, Any]:
    if report is None:
        return {
            "reconciliation_performed": False,
            "reconciliation_complete": False,
            "unauthorized_receipts": [],
            "authorized_missing": [],
            "lowering_report_errors": ["lowering_report_missing"],
        }
    if not isinstance(report, dict):
        return {
            "reconciliation_performed": True,
            "reconciliation_complete": False,
            "unauthorized_receipts": [],
            "authorized_missing": [],
            "lowering_report_errors": ["invalid_lowering_report"],
        }
    errors: list[str] = []
    required_fields = {
        "schema", "complete", "required_ops", "receipts", "missing",
        "duplicate", "duplicate_expected_ids", "unknown", "rejected",
        "digest_mismatch", "kind_mismatch",
    }
    if not required_fields <= set(report):
        errors.append("lowering_report_fields_missing")
    if type(report.get("schema")) is not int or report.get("schema") != 1:
        errors.append("lowering_report_schema_mismatch")
    if type(report.get("complete")) is not bool:
        errors.append("invalid_complete")
    if type(report.get("required_ops")) is not int:
        errors.append("invalid_required_ops")
    if type(report.get("receipts")) is not int:
        errors.append("invalid_receipts")
    missing, missing_valid = _report_id_set(report, "missing")
    if not missing_valid or not missing <= contract_ids:
        errors.append("invalid_missing_ids")
    observed_receipts = contract_ids - missing
    unauthorized_receipts = sorted(observed_receipts & blocked_ids)
    authorized_missing = sorted(authorized_ids & missing)
    if unauthorized_receipts:
        errors.append("unauthorized_receipts")
    if authorized_missing:
        errors.append("authorized_missing")
    if report.get("required_ops") != required_ops:
        errors.append("required_ops_mismatch")
    if report.get("receipts") != len(observed_receipts):
        errors.append("receipt_count_mismatch")
    report_problem_ids = False
    for key in (
            "duplicate", "duplicate_expected_ids", "unknown", "rejected",
            "digest_mismatch", "kind_mismatch"):
        ids, valid = _report_id_set(report, key)
        if not valid:
            errors.append(f"invalid_{key}")
        if ids:
            report_problem_ids = True
            errors.append(key)
    expected_report_complete = not missing and not report_problem_ids
    if (type(report.get("complete")) is bool
            and report["complete"] is not expected_report_complete):
        errors.append("complete_mismatch")
    if observed_receipts != authorized_ids:
        errors.append("receipt_authorization_set_mismatch")
    return {
        "reconciliation_performed": True,
        "reconciliation_complete": not errors,
        "unauthorized_receipts": unauthorized_receipts,
        "authorized_missing": authorized_missing,
        "lowering_report_errors": sorted(set(errors)),
    }


def verify_backend_lowering_plan(
        formal: dict, contract: dict, backend: str, plan: dict | None = None,
        device_spec: Any = None, lowering_report: dict | None = None,
        ) -> dict:
    """Verify a candidate plan against Formal, DeviceSpec, and contract."""
    canonical = build_backend_lowering_plan(formal, backend, device_spec)
    candidate = copy.deepcopy(plan if plan is not None else canonical)
    contract_rows = _rows(contract, "register_operations")
    plan_rows = _rows(candidate, "entries")
    canonical_rows = canonical["entries"]

    duplicate_contract_ids = _invalid_or_duplicate_ids(contract_rows)
    duplicate_formal_ids = _invalid_or_duplicate_ids(canonical_rows)
    duplicate_plan_ids = _invalid_or_duplicate_ids(plan_rows)
    contract_by_id = _unique_by_id(contract_rows)
    formal_by_id = _unique_by_id(canonical_rows)
    plan_by_id = _unique_by_id(plan_rows)

    contract_ids = set(contract_by_id)
    formal_ids = set(formal_by_id)
    plan_ids = set(plan_by_id)
    missing_from_contract = sorted(formal_ids - contract_ids)
    unknown_contract_ops = sorted(contract_ids - formal_ids)
    missing_plan_ops = sorted(contract_ids - plan_ids)
    unknown_plan_ops = sorted(plan_ids - contract_ids)

    contract_mismatches = []
    for op_id in sorted(contract_ids & formal_ids):
        expected = formal_by_id[op_id]
        observed = contract_by_id[op_id]
        fields = {
            name: {"formal": expected.get(name), "contract": observed.get(name)}
            for name in ("module", "kind")
            if expected.get(name) != observed.get(name)
        }
        if fields:
            contract_mismatches.append({"op_id": op_id, "fields": fields})

    classification_mismatches = []
    for op_id in sorted(formal_ids & plan_ids):
        expected = _entry_shape(formal_by_id[op_id])
        observed = _entry_shape(plan_by_id[op_id])
        if expected != observed:
            classification_mismatches.append({
                "op_id": op_id,
                "expected": expected,
                "observed": observed,
            })
    plan_envelope_mismatch = None
    if _plan_envelope(candidate) != _plan_envelope(canonical):
        plan_envelope_mismatch = {
            "expected": _plan_envelope(canonical),
            "observed": _plan_envelope(candidate),
        }

    malformed_plan_entries = []
    for index, entry in enumerate(plan_rows):
        disposition = entry.get("disposition")
        problems = []
        if disposition not in DISPOSITIONS:
            problems.append(f"invalid disposition {disposition!r}")
        if entry.get("kind") not in REGISTER_KINDS:
            problems.append(f"invalid register kind {entry.get('kind')!r}")
        if not isinstance(entry.get("route"), dict):
            problems.append("entry has no route")
        expected_authorized = disposition in AUTHORIZED_DISPOSITIONS
        expected_strict = disposition in STRICT_ELIGIBLE_DISPOSITIONS
        if entry.get("receipt_authorized") is not expected_authorized:
            problems.append("receipt authorization disagrees with disposition")
        if entry.get("strict_eligible") is not expected_strict:
            problems.append("strict eligibility disagrees with disposition")
        if disposition in BLOCKED_DISPOSITIONS and not entry.get("reason"):
            problems.append("blocked entry has no reason")
        if disposition == "blocked_unsupported_loop":
            if not entry.get("blocking_loop"):
                problems.append("loop-blocked entry has no blocking_loop")
            if not entry.get("enclosing_loops"):
                problems.append("loop-blocked entry has no enclosing_loops")
        elif entry.get("blocking_loop"):
            problems.append("non-loop-blocked entry retains a blocking_loop")
        if (backend == "linux" and expected_authorized
                and entry.get("runtime_registration_proven") is not False):
            problems.append("Linux definition candidate claims runtime registration")
        if problems:
            malformed_plan_entries.append({
                "index": index,
                "op_id": entry.get("op_id"),
                "problems": problems,
            })

    driver_mismatch = None
    if contract.get("driver") != formal.get("driver"):
        driver_mismatch = {
            "formal": formal.get("driver"),
            "contract": contract.get("driver"),
        }
    backend_mismatch = None
    if candidate.get("backend") != backend:
        backend_mismatch = {"requested": backend, "plan": candidate.get("backend")}

    accounting_complete = not any((
        duplicate_contract_ids, duplicate_formal_ids, duplicate_plan_ids,
        missing_from_contract, unknown_contract_ops, missing_plan_ops,
        unknown_plan_ops, contract_mismatches, malformed_plan_entries,
        driver_mismatch, backend_mismatch,
    ))
    classification_complete = not (
        classification_mismatches or plan_envelope_mismatch)
    authorization_complete = not malformed_plan_entries and not any(
        mismatch for mismatch in classification_mismatches
        if (mismatch["expected"].get("receipt_authorized")
            != mismatch["observed"].get("receipt_authorized")
            or mismatch["expected"].get("strict_eligible")
            != mismatch["observed"].get("strict_eligible")
            or mismatch["expected"].get("runtime_registration_proven")
            != mismatch["observed"].get("runtime_registration_proven")))

    disposition_counts = Counter(entry.get("disposition") for entry in plan_rows)
    authorized_ids = {
        entry["op_id"] for entry in plan_rows
        if entry.get("receipt_authorized") is True
        and isinstance(entry.get("op_id"), str)
    }
    blocked_ids = {
        entry["op_id"] for entry in plan_rows
        if entry.get("disposition") in BLOCKED_DISPOSITIONS
        and isinstance(entry.get("op_id"), str)
    }
    reconciliation = _reconcile_lowering_report(
        lowering_report, contract_ids, authorized_ids, blocked_ids,
        len(contract_rows))
    definition_alignment_complete = all((
        accounting_complete,
        classification_complete,
        authorization_complete,
        reconciliation["reconciliation_complete"],
    ))
    lowering_complete = (
        definition_alignment_complete and not blocked_ids
        and disposition_counts["definition_evidence_only"] == 0)
    runtime_complete = (
        lowering_complete if backend != "linux" else False)
    strict_complete = lowering_complete and runtime_complete
    complete = lowering_complete if backend != "linux" else strict_complete

    result = {
        "schema": SCHEMA,
        "oracle": ORACLE,
        "driver": formal.get("driver"),
        "backend": backend,
        "complete": complete,
        "accounting_complete": accounting_complete,
        "classification_complete": classification_complete,
        "authorization_complete": authorization_complete,
        "definition_alignment_complete": definition_alignment_complete,
        "reconciliation_complete": reconciliation["reconciliation_complete"],
        "lowering_complete": lowering_complete,
        "runtime_complete": runtime_complete,
        "strict_complete": strict_complete,
        "required_ops": len(contract_rows),
        "planned_ops": len(plan_rows),
        "lowered_ops": disposition_counts["lowered"],
        "candidate_definition_ops": disposition_counts[
            "candidate_definition_emit"],
        "evidence_only_ops": disposition_counts["definition_evidence_only"],
        "authorized_ops": len(authorized_ids),
        "strict_eligible_ops": sum(
            entry.get("strict_eligible") is True for entry in plan_rows),
        "blocked_ops": len(blocked_ids),
        "disposition_counts": {
            name: disposition_counts[name] for name in sorted(DISPOSITIONS)
        },
        "authorized_op_ids": sorted(authorized_ids),
        "blocked_op_ids": sorted(blocked_ids),
        "duplicate_contract_ids": duplicate_contract_ids,
        "duplicate_formal_ids": duplicate_formal_ids,
        "duplicate_plan_ids": duplicate_plan_ids,
        "missing_from_contract": missing_from_contract,
        "unknown_contract_ops": unknown_contract_ops,
        "missing_plan_ops": missing_plan_ops,
        "unknown_plan_ops": unknown_plan_ops,
        "contract_mismatches": contract_mismatches,
        "classification_mismatches": classification_mismatches,
        "plan_envelope_mismatch": plan_envelope_mismatch,
        "malformed_plan_entries": malformed_plan_entries,
        "driver_mismatch": driver_mismatch,
        "backend_mismatch": backend_mismatch,
        "policy": copy.deepcopy(canonical["policy"]),
        "entries": plan_rows,
    }
    result.update(reconciliation)
    return result


def _write_report(report: dict, output: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify a fail-closed backend lowering plan")
    parser.add_argument("--formal", required=True,
                        help="canonical Formal RIS JSON")
    parser.add_argument("--contract", required=True,
                        help="frozen generation-contract JSON")
    parser.add_argument("--backend", required=True,
                        choices=sorted(SUPPORTED_BACKENDS))
    parser.add_argument("--device-spec-json",
                        help="DeviceSpec JSON (required for Linux)")
    parser.add_argument("--lowering-report",
                        help="optional backend lowering receipt report JSON")
    parser.add_argument("--plan",
                        help="optional serialized candidate plan to verify")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)

    formal_path = Path(args.formal)
    contract_path = Path(args.contract)
    try:
        if args.backend == "linux" and not args.device_spec_json:
            raise ValueError("Linux backend requires --device-spec-json")
        formal = json.loads(formal_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        device_spec = None
        if args.device_spec_json:
            device_document = json.loads(Path(
                args.device_spec_json).read_text(encoding="utf-8"))
            device_spec = device_spec_from_dict(device_document)
        lowering_report = (
            json.loads(Path(args.lowering_report).read_text(encoding="utf-8"))
            if args.lowering_report else None)
        plan = (json.loads(Path(args.plan).read_text(encoding="utf-8"))
                if args.plan else None)
        report = verify_backend_lowering_plan(
            formal, contract, args.backend, plan, device_spec, lowering_report)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "oracle": ORACLE,
            "complete": False,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
            "formal": str(formal_path),
            "contract": str(contract_path),
            "backend": args.backend,
        }
        _write_report(report, args.output)
        return 3
    _write_report(report, args.output)
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
