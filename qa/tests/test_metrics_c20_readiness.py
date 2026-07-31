from __future__ import annotations

import copy


if __package__:
    from ._bootstrap import REPO_ROOT as REHARNESS
else:
    from _bootstrap import REPO_ROOT as REHARNESS

from extractor import ExtractorConfig, extract_ris
from extractor.metrics import score


OP_ID = "op_5"
ROUTE_ID = "0123456789abcdef"
GENERATED_SHA = "a" * 64
COMPILE_CONTEXT = {
    "origin": "kbuild-cmd",
    "provenance": "/tmp/reharness-metrics/.edu.o.cmd",
    "raw_command_sha256": "b" * 64,
    "arguments_sha256": "c" * 64,
    "argument_count": 7,
}


def _linux_result() -> dict:
    lowering = {
        "schema": 1,
        "complete": True,
        "required_ops": 1,
        "receipts": 1,
        "missing": [],
        "duplicate": [],
        "duplicate_expected_ids": [],
        "unknown": [],
        "rejected": [],
        "digest_mismatch": [],
        "kind_mismatch": [],
    }
    ast = {
        "schema": 1,
        "oracle": "generated-c-ast-leaf-v1",
        "driver": "edu",
        "complete": True,
        "generated": "/tmp/reharness-metrics/edu.c",
        "generated_sha256": GENERATED_SHA,
        "compile_context": copy.deepcopy(COMPILE_CONTEXT),
        "required_ops": 1,
        "required_ast_ops": 1,
        "required_op_ids": [OP_ID],
        "contract_ops": 1,
        "operation_checks": [{
            "op_id": OP_ID,
            "kind": "Read",
            "required": True,
            "expected": [{
                "kind": "Read",
                "width_bits": 32,
                "byte_order": "native",
                "write_semantics": "normal",
            }],
            "observed": [{
                "kind": "Read",
                "width_bits": 32,
                "byte_order": "native",
                "write_semantics": "normal",
            }],
            "matches": True,
        }],
        "duplicate_expected_ids": [],
        "unknown_required_ids": [],
        "parse_errors": [],
        "missing_anchors": [],
        "duplicate_anchors": [],
        "unknown_anchors": [],
        "malformed_anchors": [],
        "unsupported_expected_ops": [],
        "primitive_mismatches": [],
        "unanchored_primitives": [],
    }
    route = {
        "route_id": ROUTE_ID,
        "callback": "pci_driver.probe",
        "target_usr": "c:@F@generated_edu_pci_probe",
        "target": "generated_edu_pci_probe",
        "binding": {
            "kind": "initializer",
            "table": "pci_driver",
            "field": "probe",
            "field_usr": "c:@S@pci_driver@FI@probe",
            "owner": {
                "root_usr": "c:@generated_driver",
                "root": "generated_driver",
                "scope": "global",
                "fields": [],
                "type": "struct pci_driver",
            },
            "target_usr": "c:@F@generated_edu_pci_probe",
            "signature_matches": True,
        },
        "registration": {
            "kind": "driver_root",
            "table": "pci_driver",
            "function_usr": "c:@F@generated_driver_init",
            "registration_offset": 900,
            "chain": [{
                "kind": "registration_call",
                "call": "__pci_register_driver",
            }],
        },
        "runtime_entry_registered": True,
    }
    registration = {
        "schema": 1,
        "oracle": "linux-registration-ast-v1",
        "driver": "edu",
        "complete": True,
        "generated": "/tmp/reharness-metrics/edu.c",
        "generated_sha256": GENERATED_SHA,
        "compile_context": copy.deepcopy(COMPILE_CONTEXT),
        "registration_routes": [copy.deepcopy(route)],
        "operations": [{
            "op_id": OP_ID,
            "module": "edu_pci_probe",
            "strict_eligible": True,
            "expected_callback": "pci_driver.probe",
            "anchor": {
                "op_id": OP_ID,
                "function_usr": "c:@F@generated_edu_pci_probe",
                "function": "generated_edu_pci_probe",
                "direct_compound": True,
            },
            "route": copy.deepcopy(route),
            "runtime_registration_proven": True,
            "errors": [],
        }],
        "strict_eligible_ops": 1,
        "runtime_registered_ops": 1,
        "runtime_registered_op_ids": [OP_ID],
        "runtime_unregistered_op_ids": [],
        "parse_errors": [],
        "route_errors": [],
        "missing_plan_ids": [],
        "unknown_plan_ids": [],
        "duplicate_anchors": [],
    }
    plan = {
        "schema": 3,
        "oracle": "backend-lowering-plan-v3",
        "driver": "edu",
        "backend": "linux",
        "required_ops": 1,
        "strict_eligible_ops": 1,
        "strict_eligible_op_ids": [OP_ID],
        "runtime_registered_ops": 1,
        "runtime_registered_op_ids": [OP_ID],
        "entries": [{
            "op_id": OP_ID,
            "module": "edu_pci_probe",
            "kind": "Read",
            "disposition": "candidate_definition_emit",
            "receipt_authorized": True,
            "strict_eligible": True,
            "route": {
                "function": "edu_pci_probe",
                "ris_ref": "edu_pci_probe",
                "role": "probe",
                "callback": "pci_driver.probe",
            },
            "runtime_registration_proven": True,
            "ast_leaf_proven": True,
            "registration_route_id": ROUTE_ID,
        }],
        "reconciliation_performed": True,
        "runtime_attestation_valid": True,
        "runtime_attestation_complete": True,
        "runtime_attestation_errors": [],
        "linux_ast_leaf_valid": True,
        "linux_ast_leaf_complete": True,
        "linux_ast_leaf_errors": [],
        "runtime_generated_sha256": GENERATED_SHA,
        "runtime_compile_context": copy.deepcopy(COMPILE_CONTEXT),
        "runtime_artifact_authority_valid": True,
        "runtime_artifact_authority_errors": [],
        "runtime_complete": True,
        "strict_complete": True,
    }
    return {
        "compiled": True,
        "syntax_ok": True,
        "has_todo": False,
        "unsupported": False,
        "backend_lowering_complete": True,
        "backend_lowering": lowering,
        "backend_lowering_plan_required": True,
        "backend_lowering_plan_accounting_complete": True,
        "backend_lowering_plan_classification_complete": True,
        "backend_lowering_plan_authorization_complete": True,
        "backend_lowering_plan_reconciliation_complete": True,
        "backend_lowering_plan_definition_alignment_complete": True,
        "backend_lowering_plan_runtime_complete": True,
        "backend_lowering_plan_strict_complete": True,
        "backend_lowering_plan": plan,
        "linux_ast_leaf_required": True,
        "linux_ast_leaf_complete": True,
        "linux_ast_leaf": ast,
        "linux_registration_ast_required": True,
        "linux_registration_ast_complete": True,
        "linux_registration_ast": registration,
    }


def _readiness(linux: dict) -> dict:
    result = extract_ris(ExtractorConfig(
        source=str(REHARNESS / "benchmarks" / "drivers" / "baseline" /
                   "edu.c")))
    return score(
        result.device_spec, result.formal, result.warnings, result.facts,
        gen_results={"linux": linux})


def test_linux_c20_readiness_requires_every_attestation_layer():
    ready = _readiness(_linux_result())
    assert ready["backend_linux_ready"] is True, ready

    mutations = (
        (lambda item: item.pop("linux_ast_leaf"),
         "required-subset AST attestation unavailable"),
        (lambda item: item["linux_ast_leaf"].update({"complete": False}),
         "required-subset AST attestation failed"),
        (lambda item: item.pop("linux_registration_ast"),
         "registration attestation unavailable"),
        (lambda item: item["linux_registration_ast"].update({
            "oracle": "wrong-registration-oracle"}),
         "registration attestation failed"),
        (lambda item: item["backend_lowering_plan"].update({"schema": 2}),
         "effective lowering plan v3 unavailable"),
        (lambda item: item["backend_lowering_plan"].update({
            "strict_complete": False}),
         "effective lowering plan v3 strict proof failed"),
        (lambda item: _forge_generated_sha(item),
         "effective lowering plan v3 strict proof failed"),
        (lambda item: _forge_compile_context(item),
         "effective lowering plan v3 strict proof failed"),
        (lambda item: item["backend_lowering_plan"].pop("entries"),
         "effective lowering plan v3 strict proof failed"),
        (lambda item: item["backend_lowering_plan"].pop(
            "runtime_artifact_authority_valid"),
         "effective lowering plan v3 strict proof failed"),
    )
    for mutate, expected in mutations:
        candidate = copy.deepcopy(_linux_result())
        mutate(candidate)
        report = _readiness(candidate)
        assert report["backend_linux_ready"] is False
        assert any(expected in blocker for blocker in report["blockers"]), (
            expected, report["blockers"])


def _forge_generated_sha(item: dict) -> None:
    forged = "d" * 64
    item["linux_ast_leaf"]["generated_sha256"] = forged
    item["linux_registration_ast"]["generated_sha256"] = forged
    plan = item["backend_lowering_plan"]
    plan["runtime_generated_sha256"] = forged
    plan["runtime_artifact_authority_valid"] = False
    plan["runtime_artifact_authority_errors"] = [
        "generated_artifact_sha_mismatch"]


def _forge_compile_context(item: dict) -> None:
    forged = copy.deepcopy(COMPILE_CONTEXT)
    forged["arguments_sha256"] = "e" * 64
    item["linux_ast_leaf"]["compile_context"] = copy.deepcopy(forged)
    item["linux_registration_ast"]["compile_context"] = copy.deepcopy(forged)
    plan = item["backend_lowering_plan"]
    plan["runtime_compile_context"] = forged
    plan["runtime_artifact_authority_valid"] = False
    plan["runtime_artifact_authority_errors"] = [
        "kbuild_context_authority_mismatch"]


def _run_standalone() -> int:
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception:
            failures += 1
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
