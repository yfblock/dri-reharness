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
import hashlib
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
SCHEMA = 3
ORACLE = "backend-lowering-plan-v3"


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
    if isinstance(callback, str) and callback.endswith(".remove"):
        return (
            "blocked_linux_lifecycle_stub",
            "Linux remove lifecycle route is replaced by a backend-owned "
            "cleanup implementation",
        )
    if isinstance(callback, str) and callback.endswith(".shutdown"):
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
        "ast_leaf_proven": (
            False if backend == "linux" and strict_eligible else None),
        "registration_route_id": None,
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
        "runtime_registered_ops": sum(
            entry.get("runtime_registration_proven") is True
            for entry in entries),
        "ast_leaf_proven_ops": sum(
            entry.get("ast_leaf_proven") is True for entry in entries),
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
            f"backend lowering plan v3 does not support backend {backend!r}")
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
            "linux_ast_axis": "generated-c-ast-leaf-v1-required-subset",
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
            "runtime_registration_proven", "ast_leaf_proven",
            "registration_route_id", "enclosing_loops",
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


def _route_fingerprint(route: dict) -> str:
    """Rebuild the registration oracle's stable route identity."""
    binding = route.get("binding") or {}
    owner = binding.get("owner") or {}
    owner_key = None
    if owner:
        owner_key = (
            owner.get("root_usr"),
            tuple(field.get("field_usr") for field in owner.get("fields") or []),
        )
    identity = {
        "callback": route.get("callback"),
        "target_usr": route.get("target_usr"),
        "binding": {
            "kind": binding.get("kind"),
            "field_usr": binding.get("field_usr"),
            "owner": owner_key,
        },
        "registration": (route.get("registration") or {}).get("chain"),
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _report_list(
        report: dict, key: str, errors: list[str], prefix: str,
        ) -> list[Any]:
    value = report.get(key)
    if not isinstance(value, list):
        errors.append(f"{prefix}_{key}_missing")
        return []
    return value


def _valid_kbuild_context(context: Any) -> bool:
    if not isinstance(context, dict):
        return False
    if context.get("origin") != "kbuild-cmd":
        return False
    if not isinstance(context.get("provenance"), str) or not context[
            "provenance"]:
        return False
    for key in ("raw_command_sha256", "arguments_sha256"):
        value = context.get(key)
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            return False
    return (type(context.get("argument_count")) is int
            and context["argument_count"] > 0)


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


def _linux_runtime_evidence(
        canonical: dict, contract_ids: set[str],
        runtime_attestation: dict | None,
        ast_leaf_report: dict | None,
        expected_generated_sha: str | None,
        expected_compile_context: dict | None,
        artifact_authority_errors: list[str],
        ) -> dict[str, Any]:
    """Validate independent per-op runtime and Linux AST evidence."""
    canonical_by_id = {
        entry["op_id"]: entry for entry in canonical["entries"]
        if isinstance(entry.get("op_id"), str)
    }
    strict_ids = {
        entry["op_id"] for entry in canonical["entries"]
        if entry.get("strict_eligible") is True
        and isinstance(entry.get("op_id"), str)
    }
    registration_errors: list[str] = []
    registration_rows: dict[str, dict] = {}
    registration_ids: set[str] = set()
    registration_sha = None
    registration_context = None
    if runtime_attestation is None:
        registration_errors.append("runtime_attestation_missing")
    elif not isinstance(runtime_attestation, dict):
        registration_errors.append("invalid_runtime_attestation")
    else:
        if runtime_attestation.get("schema") != 1:
            registration_errors.append("runtime_attestation_schema_mismatch")
        if runtime_attestation.get("oracle") != "linux-registration-ast-v1":
            registration_errors.append("runtime_attestation_oracle_mismatch")
        if runtime_attestation.get("driver") != canonical.get("driver"):
            registration_errors.append("runtime_attestation_driver_mismatch")
        for key in ("contract_driver", "device_spec_driver"):
            if runtime_attestation.get(key) != canonical.get("driver"):
                registration_errors.append(
                    f"runtime_attestation_{key}_mismatch")
        registration_sha = runtime_attestation.get("generated_sha256")
        if not isinstance(registration_sha, str) or not registration_sha:
            registration_errors.append("runtime_attestation_generated_sha_missing")
        registration_context = runtime_attestation.get("compile_context")
        if not _valid_kbuild_context(registration_context):
            registration_errors.append("runtime_attestation_compile_context_missing")

        global_registration_failure = False
        for key in (
                "parse_errors", "route_errors", "missing_plan_ids",
                "unknown_plan_ids", "duplicate_anchors"):
            values = _report_list(
                runtime_attestation, key, registration_errors,
                "runtime_attestation")
            if values:
                global_registration_failure = True
                registration_errors.append(
                    f"runtime_attestation_{key}_present")

        routes = _report_list(
            runtime_attestation, "registration_routes", registration_errors,
            "runtime_attestation")
        route_counts = Counter(
            route.get("route_id") for route in routes
            if isinstance(route, dict))
        if (len(route_counts) != len(routes)
                or any(not isinstance(route_id, str) or not route_id
                       or count != 1
                       for route_id, count in route_counts.items())):
            registration_errors.append("runtime_attestation_route_ids_invalid")
        route_by_id = {
            route["route_id"]: route for route in routes
            if isinstance(route, dict)
            and isinstance(route.get("route_id"), str)
            and route.get("route_id")
            and route_counts[route["route_id"]] == 1
        }
        if any(route_id != _route_fingerprint(route)
               for route_id, route in route_by_id.items()):
            registration_errors.append(
                "runtime_attestation_route_fingerprint_mismatch")

        operations = _report_list(
            runtime_attestation, "operations", registration_errors,
            "runtime_attestation")
        counts = Counter(
            row.get("op_id") for row in operations if isinstance(row, dict))
        if set(counts) != contract_ids or any(count != 1 for count in counts.values()):
            registration_errors.append("runtime_attestation_operation_set_mismatch")
        registration_rows = {
            row["op_id"]: row for row in operations
            if isinstance(row, dict)
            and isinstance(row.get("op_id"), str)
            and counts[row["op_id"]] == 1
        }
        claimed, valid = _report_id_set(
            runtime_attestation, "runtime_registered_op_ids")
        if not valid:
            registration_errors.append("invalid_runtime_registered_op_ids")
        registration_ids = claimed
        if not registration_ids <= strict_ids:
            registration_errors.append("runtime_attestation_authorizes_non_candidate")
        unregistered, valid = _report_id_set(
            runtime_attestation, "runtime_unregistered_op_ids")
        if not valid or unregistered != strict_ids - registration_ids:
            registration_errors.append(
                "runtime_attestation_unregistered_set_mismatch")
        if runtime_attestation.get("strict_eligible_ops") != len(strict_ids):
            registration_errors.append(
                "runtime_attestation_strict_count_mismatch")
        if runtime_attestation.get("runtime_registered_ops") != len(
                registration_ids):
            registration_errors.append(
                "runtime_attestation_registered_count_mismatch")

        for op_id in sorted(contract_ids):
            row = registration_rows.get(op_id) or {}
            expected = canonical_by_id.get(op_id) or {}
            expected_strict = expected.get("strict_eligible") is True
            expected_callback = (expected.get("route") or {}).get("callback")
            if row.get("module") != expected.get("module"):
                registration_errors.append(
                    "runtime_attestation_operation_module_mismatch")
            if row.get("strict_eligible") is not expected_strict:
                registration_errors.append(
                    "runtime_attestation_operation_eligibility_mismatch")
            if row.get("expected_callback") != expected_callback:
                registration_errors.append(
                    "runtime_attestation_operation_callback_mismatch")
            row_errors = row.get("errors")
            if not isinstance(row_errors, list):
                registration_errors.append(
                    "runtime_attestation_operation_errors_invalid")
                row_errors = []
            proven = row.get("runtime_registration_proven")
            if type(proven) is not bool or proven is not (op_id in registration_ids):
                registration_errors.append(
                    "runtime_attestation_operation_claim_mismatch")
            route = row.get("route")
            if proven is True:
                anchor = row.get("anchor")
                if (not isinstance(anchor, dict)
                        or anchor.get("op_id") != op_id
                        or not isinstance(anchor.get("function_usr"), str)
                        or not anchor.get("direct_compound")):
                    registration_errors.append(
                        "runtime_attestation_anchor_identity_mismatch")
                if not isinstance(route, dict):
                    registration_errors.append(
                        "runtime_attestation_route_id_missing")
                    continue
                route_id = route.get("route_id")
                if (not isinstance(route_id, str) or not route_id
                        or route_by_id.get(route_id) != route):
                    registration_errors.append(
                        "runtime_attestation_route_reference_mismatch")
                if (route.get("runtime_entry_registered") is not True
                        or route.get("callback") != expected_callback
                        or route.get("target_usr") != (
                            anchor or {}).get("function_usr")
                        or row_errors):
                    registration_errors.append(
                        "runtime_attestation_route_claim_mismatch")
        observed_claims = {
            op_id for op_id, row in registration_rows.items()
            if row.get("runtime_registration_proven") is True
        }
        if observed_claims != registration_ids:
            registration_errors.append("runtime_attestation_claim_set_mismatch")
        expected_complete = (
            not global_registration_failure
            and registration_ids == strict_ids)
        if (type(runtime_attestation.get("complete")) is not bool
                or runtime_attestation.get("complete") is not expected_complete):
            registration_errors.append(
                "runtime_attestation_complete_claim_mismatch")

    ast_errors: list[str] = []
    ast_proven_ids: set[str] = set()
    ast_sha = None
    ast_context = None
    if ast_leaf_report is None:
        ast_errors.append("linux_ast_leaf_report_missing")
    elif not isinstance(ast_leaf_report, dict):
        ast_errors.append("invalid_linux_ast_leaf_report")
    else:
        if ast_leaf_report.get("schema") != 1:
            ast_errors.append("linux_ast_leaf_schema_mismatch")
        if ast_leaf_report.get("oracle") != "generated-c-ast-leaf-v1":
            ast_errors.append("linux_ast_leaf_oracle_mismatch")
        if ast_leaf_report.get("driver") != canonical.get("driver"):
            ast_errors.append("linux_ast_leaf_driver_mismatch")
        ast_sha = ast_leaf_report.get("generated_sha256")
        if not isinstance(ast_sha, str) or not ast_sha:
            ast_errors.append("linux_ast_leaf_generated_sha_missing")
        ast_context = ast_leaf_report.get("compile_context")
        if not _valid_kbuild_context(ast_context):
            ast_errors.append("linux_ast_leaf_compile_context_missing")
        required, valid = _report_id_set(ast_leaf_report, "required_op_ids")
        if not valid or required != strict_ids:
            ast_errors.append("linux_ast_leaf_required_set_mismatch")
        if ast_leaf_report.get("required_ops") != len(contract_ids):
            ast_errors.append("linux_ast_leaf_required_count_mismatch")
        if ast_leaf_report.get("required_ast_ops") != len(strict_ids):
            ast_errors.append("linux_ast_leaf_subset_count_mismatch")
        if ast_leaf_report.get("contract_ops") != len(contract_ids):
            ast_errors.append("linux_ast_leaf_contract_count_mismatch")

        ast_failure_fields: dict[str, list[Any]] = {}
        for key in (
                "duplicate_expected_ids", "unknown_required_ids",
                "parse_errors", "missing_anchors", "duplicate_anchors",
                "unknown_anchors", "malformed_anchors",
                "unsupported_expected_ops", "primitive_mismatches",
                "unanchored_primitives"):
            ast_failure_fields[key] = _report_list(
                ast_leaf_report, key, ast_errors, "linux_ast_leaf")
        for key in (
                "duplicate_expected_ids", "unknown_required_ids",
                "parse_errors", "duplicate_anchors", "unknown_anchors",
                "unanchored_primitives"):
            if ast_failure_fields[key]:
                ast_errors.append(f"linux_ast_leaf_{key}_present")

        checks = _report_list(
            ast_leaf_report, "operation_checks", ast_errors,
            "linux_ast_leaf")
        check_counts = Counter(
            row.get("op_id") for row in checks if isinstance(row, dict))
        if set(check_counts) != contract_ids or any(
                count != 1 for count in check_counts.values()):
            ast_errors.append("linux_ast_leaf_operation_set_mismatch")
        checks_by_id = {
            row["op_id"]: row for row in checks
            if isinstance(row, dict)
            and isinstance(row.get("op_id"), str)
            and check_counts[row["op_id"]] == 1
        }
        for op_id in sorted(contract_ids):
            row = checks_by_id.get(op_id) or {}
            expected = canonical_by_id.get(op_id) or {}
            is_required = op_id in strict_ids
            if row.get("kind") != expected.get("kind"):
                ast_errors.append("linux_ast_leaf_operation_kind_mismatch")
            if row.get("required") is not is_required:
                ast_errors.append(
                    "linux_ast_leaf_operation_required_mismatch")
            if type(row.get("matches")) is not bool:
                ast_errors.append("linux_ast_leaf_operation_matches_invalid")
            if row.get("matches") is True and row.get("expected") != row.get(
                    "observed"):
                ast_errors.append("linux_ast_leaf_shape_claim_mismatch")
        ast_proven_ids = {
            op_id for op_id, row in checks_by_id.items()
            if op_id in strict_ids and row.get("matches") is True
        }
        if not ast_proven_ids <= strict_ids:
            ast_errors.append("linux_ast_leaf_proves_non_candidate")
        expected_ast_complete = not any(ast_failure_fields.values())
        if (type(ast_leaf_report.get("complete")) is not bool
                or ast_leaf_report.get("complete") is not expected_ast_complete
                or expected_ast_complete != (ast_proven_ids == strict_ids)):
            ast_errors.append("linux_ast_leaf_complete_claim_mismatch")
    if (registration_sha and ast_sha and registration_sha != ast_sha):
        ast_errors.append("linux_runtime_generated_sha_mismatch")
    if (expected_generated_sha is not None
            and registration_sha != expected_generated_sha):
        registration_errors.append(
            "runtime_attestation_generated_artifact_mismatch")
    if (expected_generated_sha is not None and ast_sha != expected_generated_sha):
        ast_errors.append("linux_ast_leaf_generated_artifact_mismatch")
    if (registration_context is not None and ast_context is not None
            and registration_context != ast_context):
        ast_errors.append("linux_runtime_compile_context_mismatch")
    if (expected_compile_context is not None
            and registration_context != expected_compile_context):
        registration_errors.append(
            "runtime_attestation_compile_context_authority_mismatch")
    if (expected_compile_context is not None
            and ast_context != expected_compile_context):
        ast_errors.append("linux_ast_leaf_compile_context_authority_mismatch")

    authority_valid = not artifact_authority_errors
    registration_valid = not registration_errors and authority_valid
    ast_valid = not ast_errors and authority_valid
    effective_ids = (
        registration_ids & ast_proven_ids
        if registration_valid and ast_valid else set())
    for entry in canonical["entries"]:
        op_id = entry.get("op_id")
        if entry.get("disposition") != "candidate_definition_emit":
            continue
        entry["ast_leaf_proven"] = op_id in ast_proven_ids and ast_valid
        entry["runtime_registration_proven"] = op_id in effective_ids
        row = registration_rows.get(op_id) or {}
        route = row.get("route") or {}
        entry["registration_route_id"] = (
            route.get("route_id") if op_id in effective_ids else None)
    canonical["summary"] = _summary(canonical["entries"])
    return {
        "runtime_attestation_valid": registration_valid,
        "runtime_attestation_complete": (
            registration_valid and registration_ids == strict_ids),
        "runtime_attestation_errors": sorted(set(registration_errors)),
        "runtime_attested_op_ids": sorted(registration_ids),
        "linux_ast_leaf_valid": ast_valid,
        "linux_ast_leaf_complete": ast_valid and ast_proven_ids == strict_ids,
        "linux_ast_leaf_errors": sorted(set(ast_errors)),
        "linux_ast_leaf_proven_op_ids": sorted(ast_proven_ids),
        "runtime_and_ast_proven_op_ids": sorted(effective_ids),
        "runtime_generated_sha256": registration_sha or ast_sha,
        "runtime_compile_context": registration_context or ast_context,
        "runtime_artifact_authority_valid": authority_valid,
        "runtime_artifact_authority_errors": sorted(
            set(artifact_authority_errors)),
        "strict_candidate_op_ids": sorted(strict_ids),
    }


def verify_backend_lowering_plan(
        formal: dict, contract: dict, backend: str, plan: dict | None = None,
        device_spec: Any = None, lowering_report: dict | None = None,
        runtime_attestation: dict | None = None,
        ast_leaf_report: dict | None = None,
        generated_artifact: str | Path | None = None,
        kbuild_cmd: str | Path | None = None,
        ) -> dict:
    """Verify a candidate plan against Formal, DeviceSpec, and contract."""
    canonical = build_backend_lowering_plan(formal, backend, device_spec)
    contract_rows = _rows(contract, "register_operations")
    raw_contract_ids = {
        row.get("op_id") for row in contract_rows
        if isinstance(row.get("op_id"), str) and row.get("op_id")
    }
    expected_generated_sha = None
    expected_compile_context = None
    expected_clang_args: list[str] | None = None
    artifact_authority_errors: list[str] = []
    if backend == "linux" and (
            runtime_attestation is not None or ast_leaf_report is not None):
        if generated_artifact is None:
            artifact_authority_errors.append("generated_artifact_missing")
        else:
            artifact_path = Path(generated_artifact).resolve()
            if not artifact_path.is_file():
                artifact_authority_errors.append("generated_artifact_unavailable")
            else:
                expected_generated_sha = hashlib.sha256(
                    artifact_path.read_bytes()).hexdigest()
        if kbuild_cmd is None or generated_artifact is None:
            artifact_authority_errors.append("kbuild_context_authority_missing")
        else:
            try:
                from verification.linux_registration_ast_oracle import (
                    linux_kbuild_compile_context,
                )
                expected_clang_args, expected_compile_context = \
                    linux_kbuild_compile_context(
                        Path(generated_artifact).resolve(),
                        Path(kbuild_cmd).resolve())
            except Exception as exc:
                artifact_authority_errors.append(
                    "kbuild_context_authority_invalid:"
                    f"{type(exc).__name__}:{exc}")
        canonical_can_be_strict = bool(canonical["entries"]) and all(
            entry.get("disposition") == "candidate_definition_emit"
            for entry in canonical["entries"])
        if (canonical_can_be_strict and not artifact_authority_errors
                and expected_clang_args is not None):
            try:
                from types import SimpleNamespace
                from verification.generated_c_ast_oracle import (
                    verify_generated_c_ast,
                )
                from verification.linux_registration_ast_oracle import (
                    verify_linux_registration_ast,
                )
                registration_device_spec = device_spec
                if isinstance(device_spec, Mapping):
                    registration_device_spec = SimpleNamespace(
                        name=_get(device_spec, "name"),
                        functions=[SimpleNamespace(
                            name=_get(function, "name"),
                            ris_ref=_get(function, "ris_ref"),
                            role=_get(function, "role", "unknown"),
                            callback_table=(
                                _get(function, "callback_table")
                                or _get(function, "callback")),
                        ) for function in _device_functions(device_spec)],
                    )
                strict_ids = {
                    entry["op_id"] for entry in canonical["entries"]
                    if entry.get("strict_eligible") is True
                }
                recomputed_ast = verify_generated_c_ast(
                    contract, Path(generated_artifact),
                    clang_args=expected_clang_args,
                    required_op_ids=strict_ids,
                    compile_context=expected_compile_context)
                recomputed_registration = verify_linux_registration_ast(
                    contract, registration_device_spec,
                    Path(generated_artifact), canonical,
                    kbuild_cmd=Path(kbuild_cmd))
                if ast_leaf_report != recomputed_ast:
                    artifact_authority_errors.append(
                        "linux_ast_leaf_independent_reverification_mismatch")
                if runtime_attestation != recomputed_registration:
                    artifact_authority_errors.append(
                        "runtime_attestation_independent_reverification_mismatch")
            except Exception as exc:
                artifact_authority_errors.append(
                    "runtime_evidence_independent_reverification_failed:"
                    f"{type(exc).__name__}:{exc}")
    runtime_evidence = (
        _linux_runtime_evidence(
            canonical, raw_contract_ids, runtime_attestation,
            ast_leaf_report, expected_generated_sha,
            expected_compile_context, artifact_authority_errors)
        if backend == "linux" else {
            "runtime_attestation_valid": True,
            "runtime_attestation_complete": True,
            "runtime_attestation_errors": [],
            "runtime_registered_op_ids": [],
            "linux_ast_leaf_valid": True,
            "linux_ast_leaf_complete": True,
            "linux_ast_leaf_errors": [],
            "linux_ast_leaf_proven_op_ids": [],
            "runtime_and_ast_proven_op_ids": [],
            "runtime_generated_sha256": None,
            "runtime_compile_context": None,
            "runtime_artifact_authority_valid": True,
            "runtime_artifact_authority_errors": [],
            "strict_candidate_op_ids": [],
        })
    candidate = copy.deepcopy(plan if plan is not None else canonical)
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
        if (backend == "linux"
                and entry.get("runtime_registration_proven") is True
                and disposition != "candidate_definition_emit"):
            problems.append(
                "non-candidate Linux entry claims runtime registration")
        if (backend == "linux"
                and entry.get("runtime_registration_proven") is True
                and (entry.get("ast_leaf_proven") is not True
                     or not isinstance(entry.get("registration_route_id"), str))):
            problems.append(
                "runtime-registered Linux entry lacks AST/route proof")
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
            != mismatch["observed"].get("runtime_registration_proven")
            or mismatch["expected"].get("ast_leaf_proven")
            != mismatch["observed"].get("ast_leaf_proven")
            or mismatch["expected"].get("registration_route_id")
            != mismatch["observed"].get("registration_route_id")))

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
    strict_candidate_ids = {
        entry["op_id"] for entry in plan_rows
        if entry.get("strict_eligible") is True
        and isinstance(entry.get("op_id"), str)
    }
    effective_runtime_ids = {
        entry["op_id"] for entry in plan_rows
        if entry.get("runtime_registration_proven") is True
        and entry.get("ast_leaf_proven") is True
        and isinstance(entry.get("op_id"), str)
    }
    runtime_complete = (
        lowering_complete if backend != "linux" else bool(
            lowering_complete
            and strict_candidate_ids
            and runtime_evidence["runtime_attestation_valid"]
            and runtime_evidence["linux_ast_leaf_valid"]
            and runtime_evidence["runtime_artifact_authority_valid"]
            and effective_runtime_ids == strict_candidate_ids))
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
        "strict_eligible_op_ids": sorted(strict_candidate_ids),
        "runtime_registered_ops": len(effective_runtime_ids),
        "runtime_registered_op_ids": sorted(effective_runtime_ids),
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
    result.update(runtime_evidence)
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
    parser.add_argument("--runtime-attestation",
                        help="Linux registration AST report JSON")
    parser.add_argument("--ast-leaf-report",
                        help="Linux required-subset AST leaf report JSON")
    parser.add_argument("--generated-artifact",
                        help="generated Linux module C used as SHA authority")
    parser.add_argument("--kbuild-cmd",
                        help="exact generated module .o.cmd context authority")
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
        runtime_attestation = (
            json.loads(Path(args.runtime_attestation).read_text(
                encoding="utf-8"))
            if args.runtime_attestation else None)
        ast_leaf_report = (
            json.loads(Path(args.ast_leaf_report).read_text(encoding="utf-8"))
            if args.ast_leaf_report else None)
        plan = (json.loads(Path(args.plan).read_text(encoding="utf-8"))
                if args.plan else None)
        report = verify_backend_lowering_plan(
            formal, contract, args.backend, plan=plan,
            device_spec=device_spec, lowering_report=lowering_report,
            runtime_attestation=runtime_attestation,
            ast_leaf_report=ast_leaf_report,
            generated_artifact=args.generated_artifact,
            kbuild_cmd=args.kbuild_cmd)
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
