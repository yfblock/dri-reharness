"""verify_linux_registration_ast: full report assembly and CLI entry point."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from extractor.spec import device_spec_from_dict
from linux_registration_contracts import (
    LinuxRegistrationContractError,
    resolve_linux_registration_policy,
)

from .ast_collect import _collect_ast
from .context import _device_routes, linux_kbuild_compile_context
from .routes import _registered_routes
from .runtime_contract import _runtime_identity_contract


SCHEMA = 1
ORACLE = "linux-registration-ast-v1"


def verify_linux_registration_ast(
        contract: dict, device_spec: Any,
        generated: str | Path | list[str | Path] | tuple[str | Path, ...],
        lowering_plan: dict, *, kbuild_cmd: str | Path,
        clang_library: str | None = None,
        runtime_identity: Mapping[str, Any] | None = None) -> dict:
    if isinstance(generated, (str, Path)):
        sources = [Path(generated).resolve()]
    elif isinstance(generated, (list, tuple)):
        sources = [Path(item).resolve() for item in generated]
    else:
        raise TypeError("generated must be a source path or a list of source paths")
    if not sources:
        raise ValueError("generated source list must not be empty")
    command_file = Path(kbuild_cmd).resolve()
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "generated C source does not exist: " + ", ".join(missing))
    if not command_file.is_file():
        raise FileNotFoundError(f"Kbuild command file does not exist: {command_file}")
    if contract.get("driver") != device_spec.name:
        raise ValueError("contract and DeviceSpec driver identities differ")
    if lowering_plan.get("driver") != contract.get("driver"):
        raise ValueError("lowering plan driver identity differs from contract")
    if lowering_plan.get("backend") != "linux":
        raise ValueError("registration oracle requires a Linux lowering plan")
    if (lowering_plan.get("schema") != 3
            or lowering_plan.get("oracle") != "backend-lowering-plan-v3"):
        raise ValueError(
            "registration oracle requires backend-lowering-plan-v3")

    declared_registration = (
        runtime_identity.get("registration")
        if isinstance(runtime_identity, Mapping) else None)
    registration_policy_errors: list[str] = []
    try:
        registration_policy = resolve_linux_registration_policy(
            declared_registration)
    except LinuxRegistrationContractError as exc:
        registration_policy_errors.append(str(exc))
        registration_policy = {
            "root_tables": frozenset(),
            "device_id_tables": frozenset(),
            "supported_callback_tables": frozenset(),
            "struct_tables": {},
            "registration_apis": {},
            "link_tables": {},
            "irq_attach_apis": {},
            "direct_irq_apis": {},
        }

    contexts: list[dict] = []
    ast = {
        "diagnostics": [], "definitions": {}, "anchors": [],
        "bindings": [], "identity_bindings": [], "pointer_edges": [],
        "call_results": [],
        "calls": [], "module_init_targets": [],
    }
    for source in sources:
        clang_args, context = linux_kbuild_compile_context(source, command_file)
        contexts.append(context)
        part = _collect_ast(
            source, clang_args, clang_library, registration_policy)
        ast["diagnostics"].extend(part["diagnostics"])
        ast["definitions"].update(part["definitions"])
        for field in ("anchors", "bindings", "identity_bindings", "pointer_edges",
                      "call_results", "calls"):
            ast[field].extend(part[field])
        ast["module_init_targets"].extend(part["module_init_targets"])
    ast["module_init_targets"] = sorted(set(ast["module_init_targets"]))
    context = contexts[0]
    parse_errors = [item for item in ast["diagnostics"]
                    if item["severity"] >= 3]
    routes, route_errors = _registered_routes(
        ast, sources[0], registration_policy)
    runtime_identity_errors, runtime_identity_observed = (
        _runtime_identity_contract(ast, routes, runtime_identity))
    route_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for route in routes:
        route_index[(route["callback"], route["target_usr"])].append(route)

    anchor_counts = Counter(item["op_id"] for item in ast["anchors"])
    anchor_by_id = {
        item["op_id"]: item for item in ast["anchors"]
        if anchor_counts[item["op_id"]] == 1
    }
    contract_rows = contract.get("register_operations")
    if not isinstance(contract_rows, list):
        raise ValueError("generation contract has no register_operations list")
    contract_counts = Counter(
        row.get("op_id") for row in contract_rows if isinstance(row, dict))
    if (any(not isinstance(op_id, str) or not op_id or count != 1
            for op_id, count in contract_counts.items())
            or len(contract_counts) != len(contract_rows)):
        raise ValueError(
            "generation contract operation IDs must be unique and nonempty")
    contract_by_id = {row.get("op_id"): row for row in contract_rows
                      if isinstance(row.get("op_id"), str)}
    plan_entries = lowering_plan.get("entries")
    if not isinstance(plan_entries, list):
        raise ValueError("lowering plan has no entries list")
    plan_counts = Counter(
        entry.get("op_id") for entry in plan_entries
        if isinstance(entry, dict))
    if (any(not isinstance(op_id, str) or not op_id or count != 1
            for op_id, count in plan_counts.items())
            or len(plan_counts) != len(plan_entries)):
        raise ValueError(
            "lowering plan operation IDs must be unique and nonempty")
    for entry in plan_entries:
        strict_eligible = entry.get("strict_eligible")
        if type(strict_eligible) is not bool:
            raise ValueError(
                "lowering plan strict eligibility must be boolean")
        if (strict_eligible
                and entry.get("disposition") != "candidate_definition_emit"):
            raise ValueError(
                "only candidate_definition_emit operations may be strict")
    plan_by_id = {entry.get("op_id"): entry for entry in plan_entries
                  if isinstance(entry.get("op_id"), str)}
    routes_by_module = _device_routes(device_spec)

    operation_rows = []
    proven_ids = []
    for op_id in sorted(contract_by_id):
        contract_row = contract_by_id[op_id]
        plan_entry = plan_by_id.get(op_id) or {}
        strict_eligible = plan_entry.get("strict_eligible") is True
        module = contract_row.get("module")
        # For verified call closure the contract operation remains owned by
        # its helper module, while its unique AST anchor is emitted in the
        # registered root callback named by the lowering-plan route.  Ordinary
        # entries retain the independent DeviceSpec callback authority.
        plan_route = plan_entry.get("route") or {}
        authority = (plan_route
                     if plan_route.get("kind") == "verified_call_closure"
                     else routes_by_module.get(module) or {})
        expected_callback = authority.get("callback")
        expected_function = authority.get("function")
        anchor = anchor_by_id.get(op_id)
        actual_function = anchor.get("function") if anchor else None
        expected_registered_functions = sorted({
            route.get("target") for route in routes
            if route.get("callback") == expected_callback
            and isinstance(route.get("target"), str)
        }) if expected_callback else []
        matching = []
        errors = []
        if strict_eligible:
            if expected_callback is None:
                errors.append("lowering plan route has no callback owner")
            if expected_callback and expected_callback.split(".", 1)[0] not in \
                    registration_policy["supported_callback_tables"]:
                errors.append("unsupported_registration_shape")
            if anchor is None:
                errors.append("missing unique operation AST anchor")
            elif not anchor["direct_compound"]:
                errors.append("operation AST anchor has no direct compound")
            if (expected_registered_functions and actual_function
                    and actual_function not in expected_registered_functions):
                errors.append("operation_callback_ownership_mismatch")
            if anchor and expected_callback:
                matching = route_index.get(
                    (expected_callback, anchor["function_usr"]), [])
                if not matching:
                    errors.append("no exact registered callback route")
                elif len(matching) != 1:
                    errors.append("ambiguous registered callback route")
        proven = bool(strict_eligible and not errors and len(matching) == 1)
        if proven:
            proven_ids.append(op_id)
        operation_rows.append({
            "op_id": op_id,
            "module": module,
            "strict_eligible": strict_eligible,
            "expected_callback": expected_callback,
            "expected_function": expected_function,
            "expected_registered_functions": expected_registered_functions,
            "actual_function": actual_function,
            "anchor": anchor,
            "route": matching[0] if len(matching) == 1 else None,
            "runtime_registration_proven": proven,
            "errors": errors,
        })

    strict_ids = sorted(entry["op_id"] for entry in plan_entries
                        if entry.get("strict_eligible") is True
                        and isinstance(entry.get("op_id"), str))
    missing_plan_ids = sorted(set(contract_by_id) - set(plan_by_id))
    unknown_plan_ids = sorted(set(plan_by_id) - set(contract_by_id))
    duplicate_anchors = sorted(op_id for op_id, count in anchor_counts.items()
                               if count != 1)
    complete = not any((
        parse_errors, route_errors, missing_plan_ids, unknown_plan_ids,
        duplicate_anchors, set(strict_ids) - set(proven_ids),
        runtime_identity_errors, registration_policy_errors,
    ))
    # The generated artifact hash is content authority.  Do not include the
    # workspace path: the C AST oracle and backend authority use the same
    # content hash, and paths are intentionally unstable across staging roots.
    generated_bytes = b"".join(source.read_bytes() for source in sources)
    generated_value: str | list[str] = (
        str(sources[0]) if len(sources) == 1
        else [str(source) for source in sources])
    report = {
        "schema": SCHEMA,
        "oracle": ORACLE,
        "driver": contract.get("driver"),
        "complete": complete,
        "claim_scope": {
            "proves": [
                "exact_kbuild_parse_context",
                "unique_operation_anchor_to_generated_function",
                "callback_field_and_signature_identity",
                "framework_object_identity",
                "straight_line_assignment_before_registration",
                "module_or_object_root_registration",
                "straight_line_gpio_and_irq_registration",
                "runtime_named_identity_when_requested",
                "misc_file_operations_registration",
                "typed_pm_and_static_clock_object_graph",
                "sdhci_pdata_init_add_host_identity",
                "single_instance_usb_hcd_create_add_remove_put",
                "single_instance_usb_gadget_ep0_add_delete",
            ],
            "does_not_prove": [
                "callback_invocation_by_the_kernel",
                "guard_or_path_semantics_inside_callback",
                "banked_or_aliasing_object_dataflow",
                "clock_match_data_fanout",
                "sdhci_wrapper_or_path_dependent_pdata",
                "multi_instance_or_mode_split_usb_lifecycle",
            ],
        },
        "generated": generated_value,
        "generated_sha256": hashlib.sha256(generated_bytes).hexdigest(),
        "contract_driver": contract.get("driver"),
        "device_spec_driver": device_spec.name,
        "compile_context": context,
        "compile_contexts": contexts,
        "diagnostics": ast["diagnostics"],
        "parse_errors": parse_errors,
        "definitions": sorted(ast["definitions"].values(),
                              key=lambda item: item["name"]),
        "anchors": ast["anchors"],
        "bindings": ast["bindings"],
        "identity_bindings": ast["identity_bindings"],
        "pointer_edges": ast["pointer_edges"],
        "call_results": ast["call_results"],
        "calls": ast["calls"],
        "module_init_targets": ast["module_init_targets"],
        "registration_routes": routes,
        "route_errors": route_errors,
        "runtime_identity_requested": (
            dict(runtime_identity) if isinstance(runtime_identity, Mapping)
            else None),
        "runtime_identity_errors": runtime_identity_errors,
        "runtime_identity_observed": runtime_identity_observed,
        "registration_policy_errors": registration_policy_errors,
        "operations": operation_rows,
        "strict_eligible_ops": len(strict_ids),
        "runtime_registered_ops": len(proven_ids),
        "runtime_registered_op_ids": sorted(proven_ids),
        "runtime_unregistered_op_ids": sorted(set(strict_ids) - set(proven_ids)),
        "missing_plan_ids": missing_plan_ids,
        "unknown_plan_ids": unknown_plan_ids,
        "duplicate_anchors": duplicate_anchors,
    }
    return report


def _write_report(report: dict, output: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Linux generated-C callback registration by AST")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--device-spec-json", required=True)
    parser.add_argument("--lowering-plan", required=True)
    parser.add_argument("--generated", required=True)
    parser.add_argument("--kbuild-cmd", required=True)
    parser.add_argument("--clang-library")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        device_spec = device_spec_from_dict(json.loads(
            Path(args.device_spec_json).read_text(encoding="utf-8")))
        plan = json.loads(Path(args.lowering_plan).read_text(encoding="utf-8"))
        report = verify_linux_registration_ast(
            contract, device_spec, args.generated, plan,
            kbuild_cmd=args.kbuild_cmd, clang_library=args.clang_library)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "oracle": ORACLE,
            "complete": False,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
        }
        _write_report(report, args.output)
        return 3
    _write_report(report, args.output)
    return 0 if report["complete"] else 2
