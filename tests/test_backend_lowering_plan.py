from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile


REHARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REHARNESS))

from verification.backend_lowering_plan import (
    build_backend_lowering_plan,
    verify_backend_lowering_plan,
)
from extractor.spec import (DeviceSpec, FunctionSpec, Signature,
                            device_spec_to_dict)


_AUTHORITY_TMP = tempfile.TemporaryDirectory()
_AUTHORITY_ROOT = Path(_AUTHORITY_TMP.name)
_AUTHORITY_GENERATED = _AUTHORITY_ROOT / "plan_test.c"
_AUTHORITY_KBUILD_CMD = _AUTHORITY_ROOT / ".plan_test.o.cmd"
_AUTHORITY_HEADER = _AUTHORITY_ROOT / "kernel_stubs.h"
_AUTHORITY_HEADER.write_text(r"""
struct module { int unused; };
extern struct module __this_module;
struct device { int unused; };
struct platform_device { struct device dev; };
struct device_driver { const char *name; };
struct platform_driver {
    int (*probe)(struct platform_device *);
    struct device_driver driver;
};
typedef int irqreturn_t;
int __platform_driver_register(struct platform_driver *, struct module *);
int request_irq(unsigned int, irqreturn_t (*)(int, void *),
                unsigned long, const char *, void *);
unsigned int readl(const void *);
void writel(unsigned int, void *);
""", encoding="utf-8")
_AUTHORITY_GENERATED.write_text(
    r"""
#include "kernel_stubs.h"
struct module __this_module;

static irqreturn_t generated_public_cb(int irq, void *data)
{
    __rh_op_op_public_cb: { writel(1, data); }
    return irq != 0;
}

static int generated_probe(struct platform_device *pdev)
{
    __rh_op_op_probe: { (void)readl(pdev); }
    return request_irq(1, generated_public_cb, 0, "plan-test", pdev);
}

static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .driver = { .name = "plan-test" },
};

static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}

static int (*__inittest(void))(void)
{
    return generated_driver_init;
}
""", encoding="utf-8")
_AUTHORITY_KBUILD_CMD.write_text(
    f"cmd_plan_test.o := cc -I{_AUTHORITY_ROOT} -std=gnu11 "
    "-c plan_test.c -o plan_test.o\n",
    encoding="utf-8")


def _runtime_authority() -> tuple[str, dict]:
    import hashlib
    from verification.linux_registration_ast_oracle import (
        linux_kbuild_compile_context,
    )

    _args, context = linux_kbuild_compile_context(
        _AUTHORITY_GENERATED, _AUTHORITY_KBUILD_CMD)
    generated_sha = hashlib.sha256(
        _AUTHORITY_GENERATED.read_bytes()).hexdigest()
    return generated_sha, context


def _runtime_authority_kwargs() -> dict:
    return {
        "generated_artifact": _AUTHORITY_GENERATED,
        "kbuild_cmd": _AUTHORITY_KBUILD_CMD,
    }


def _leaf(op_id: str, kind: str = "Read") -> dict:
    body = {
        "op_id": op_id,
        "width": "B4",
        "reliability": "Exact",
        "access_domain": "mmio",
        "evidence": {},
    }
    if kind == "Read":
        body.update({"addr": {"Fixed": {"base": "base", "offset": 0}},
                     "var": f"value_{op_id}"})
    elif kind == "Write":
        body.update({"addr": {"Fixed": {"base": "base", "offset": 4}},
                     "value": {"Const": 1}})
    else:
        body.update({"addr": {"Fixed": {"base": "base", "offset": 8}},
                     "read_var": "old", "transform": {"Var": "old"}})
    return {kind: body}


def _loop(kind: str, *, reliability: str = "Conservative",
          bounded: bool = False, proof_kind: str | None = None,
          guard_ops: list | None = None, body: list | None = None) -> dict:
    return {"Loop": {
        "loop_kind": kind,
        "reliability": reliability,
        "bounded": bounded,
        "proof_kind": proof_kind,
        "guard": {"Const": 1},
        "guard_ops": guard_ops or [],
        "body": body or [],
    }}


def _formal(*ops: dict) -> dict:
    return {
        "driver": "plan-test",
        "modules": [{"name": "probe", "source": "fixture.c", "ops": list(ops)}],
    }


def _formal_modules(modules: list[tuple[str, list[dict]]],
                    metadata: dict | None = None) -> dict:
    return {
        "driver": "plan-test",
        "metadata": metadata or {},
        "modules": [
            {"name": name, "source": f"{name}.c", "ops": ops}
            for name, ops in modules
        ],
    }


def _contract_for(formal: dict) -> dict:
    rows = []

    def walk(ops: list, module: str) -> None:
        for op in ops:
            kind = next((name for name in
                         ("Read", "Write", "ReadModifyWrite")
                         if name in op), None)
            if kind:
                rows.append({
                    "op_id": op[kind].get("op_id"),
                    "module": module,
                    "kind": kind,
                    "width": op[kind].get("width"),
                })
            elif "Cond" in op:
                walk(op["Cond"].get("then_ops") or [], module)
                walk(op["Cond"].get("else_ops") or [], module)
            elif "Seq" in op:
                walk(op["Seq"].get("ops") or [], module)
            elif "Loop" in op:
                walk(op["Loop"].get("guard_ops") or [], module)
                walk(op["Loop"].get("body") or [], module)

    for module in formal["modules"]:
        walk(module["ops"], module["name"])
    return {
        "schema": 1,
        "driver": formal["driver"],
        "register_operations": rows,
    }


def _linux_fixture() -> tuple[dict, dict, dict]:
    module_names = ("probe", "public_cb", "private_cb", "helper",
                    "remove", "shutdown")
    modules = [
        (name, [_leaf(f"op_{name}"),
                _loop("while", body=[_leaf(f"op_{name}_loop")])])
        for name in module_names
    ]
    formal = _formal_modules(modules, {
        "sources": ["a.c", "b.c"],
        "callback_binding_analysis": {"bindings": [{
            "function": "private_cb",
            "role": "unknown",
            "public_callback_type": False,
        }]},
    })
    device_spec = {
        "name": "plan-test",
        "functions": [
            {"name": "probe", "ris_ref": "probe", "role": "probe",
             "callback": "platform_driver.probe",
             "is_callback_entry": True},
            {"name": "public_cb", "ris_ref": "public_cb",
             "role": "interrupt_handler", "callback": "irq_handler.handler",
             "is_callback_entry": True},
            {"name": "private_cb", "ris_ref": "private_cb",
             "role": "unknown", "callback": "private_ops.complete",
             "is_callback_entry": True},
            {"name": "helper", "ris_ref": "helper", "role": "helper",
             "is_callback_entry": False},
            {"name": "remove", "ris_ref": "remove", "role": "remove",
             "callback": "platform_driver.remove",
             "is_callback_entry": True},
            {"name": "shutdown", "ris_ref": "shutdown", "role": "remove",
             "callback": "platform_driver.shutdown",
             "is_callback_entry": True},
        ],
    }
    return formal, _contract_for(formal), device_spec


def _lowering_report(contract: dict, missing: list[str]) -> dict:
    required = len(contract["register_operations"])
    return {
        "schema": 1,
        "complete": not missing,
        "required_ops": required,
        "receipts": required - len(missing),
        "missing": list(missing),
        "duplicate": [],
        "duplicate_expected_ids": [],
        "unknown": [],
        "rejected": [],
        "digest_mismatch": [],
        "kind_mismatch": [],
    }


def _device_spec_document(device_spec: dict) -> dict:
    return device_spec_to_dict(DeviceSpec(
        name=device_spec["name"],
        functions=[FunctionSpec(
            name=function["name"],
            signature=Signature(),
            role=function.get("role", "unknown"),
            ris_ref=function.get("ris_ref"),
            is_callback_entry=function["is_callback_entry"],
            callback_table=function.get("callback"),
        ) for function in device_spec["functions"]],
    ))


def _linux_runtime_fixture() -> tuple[dict, dict, dict]:
    formal = _formal_modules([
        ("probe", [_leaf("op_probe")]),
        ("public_cb", [_leaf("op_public_cb", "Write")]),
    ])
    device_spec = {
        "name": "plan-test",
        "functions": [
            {"name": "probe", "ris_ref": "probe", "role": "probe",
             "callback": "platform_driver.probe",
             "is_callback_entry": True},
            {"name": "public_cb", "ris_ref": "public_cb",
             "role": "interrupt_handler",
             "callback": "irq_handler.handler",
             "is_callback_entry": True},
        ],
    }
    return formal, _contract_for(formal), device_spec


def _runtime_attestation(contract: dict, claimed_ids: list[str],
                         generated_sha: str | None = None,
                         plan: dict | None = None) -> dict:
    import hashlib

    authority_sha, authority_context = _runtime_authority()
    generated_sha = generated_sha or authority_sha
    claimed = set(claimed_ids)
    plan_by_id = {
        entry["op_id"]: entry for entry in (plan or {}).get("entries", [])
    }
    strict_ids = {
        op_id for op_id, entry in plan_by_id.items()
        if entry.get("strict_eligible") is True
    }
    routes = []

    def route_for(row: dict) -> dict:
        op_id = row["op_id"]
        module = row["module"]
        expected = plan_by_id.get(op_id) or {}
        callback = (expected.get("route") or {}).get("callback")
        target_usr = f"c:@F@generated_{module}"
        location = {"file": str(_AUTHORITY_GENERATED), "line": 10,
                    "column": 5, "offset": 100 + len(routes)}
        if callback == "platform_driver.probe":
            owner = {
                "root_usr": "c:@generated_driver",
                "root": "generated_driver",
                "scope": "global",
                "fields": [],
                "type": "struct platform_driver",
            }
            binding = {
                "kind": "initializer",
                "table": "platform_driver",
                "field": "probe",
                "field_usr": "c:@S@platform_driver@FI@probe",
                "owner": owner,
                "target_usr": target_usr,
                "target": f"generated_{module}",
                "target_signature": {},
                "signature_matches": True,
                "function_usr": None,
                "function": None,
                "control_depth": 0,
                "location": location,
            }
            registration = {
                "object": owner,
                "kind": "driver_root",
                "table": "platform_driver",
                "function_usr": "c:@F@generated_driver_init",
                "registration_offset": 900,
                "chain": [{
                    "kind": "registration_call",
                    "call": "__platform_driver_register",
                    "location": {**location, "offset": 900},
                }],
            }
        else:
            binding = {
                "kind": "call_argument",
                "call": "request_irq",
                "argument": 1,
                "location": location,
                "signature_matches": True,
            }
            registration = {
                "kind": "direct_irq",
                "function_usr": "c:@F@generated_probe",
                "registration_offset": 700,
                "chain": [
                    {"kind": "registered_probe",
                     "function_usr": "c:@F@generated_probe"},
                    {"kind": "registration_call", "call": "request_irq",
                     "location": {**location, "offset": 700}},
                ],
            }
        route = {
            "callback": callback,
            "target_usr": target_usr,
            "target": f"generated_{module}",
            "binding": binding,
            "registration": registration,
            "runtime_entry_registered": True,
        }
        owner = binding.get("owner") or {}
        owner_key = None
        if owner:
            owner_key = (
                owner.get("root_usr"),
                tuple(field.get("field_usr")
                      for field in owner.get("fields") or []),
            )
        identity = {
            "callback": route.get("callback"),
            "target_usr": route.get("target_usr"),
            "binding": {
                "kind": binding.get("kind"),
                "field_usr": binding.get("field_usr"),
                "owner": owner_key,
            },
            "registration": registration.get("chain"),
        }
        encoded = json.dumps(
            identity, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        route["route_id"] = hashlib.sha256(encoded).hexdigest()[:16]
        return route

    route_by_op = {}
    for row in contract["register_operations"]:
        if row["op_id"] in claimed:
            route = route_for(row)
            routes.append(route)
            route_by_op[row["op_id"]] = route

    anchors = [{
        "op_id": row["op_id"],
        "function_usr": f"c:@F@generated_{row['module']}",
        "function": f"generated_{row['module']}",
        "direct_compound": True,
        "location": {"file": str(_AUTHORITY_GENERATED), "line": 20,
                     "column": 5, "offset": 200 + index},
    } for index, row in enumerate(contract["register_operations"])]
    anchor_by_id = {anchor["op_id"]: anchor for anchor in anchors}
    operation_rows = []
    for row in contract["register_operations"]:
        op_id = row["op_id"]
        expected = plan_by_id.get(op_id) or {}
        operation_rows.append({
            "op_id": op_id,
            "module": row["module"],
            "strict_eligible": expected.get("strict_eligible") is True,
            "expected_callback": (expected.get("route") or {}).get("callback"),
            "anchor": anchor_by_id[op_id],
            "route": route_by_op.get(op_id),
            "runtime_registration_proven": op_id in claimed,
            "errors": [],
        })
    return {
        "schema": 1,
        "oracle": "linux-registration-ast-v1",
        "driver": contract["driver"],
        "complete": claimed == strict_ids,
        "claim_scope": {"proves": [], "does_not_prove": []},
        "generated": str(_AUTHORITY_GENERATED),
        "generated_sha256": generated_sha,
        "contract_driver": contract["driver"],
        "device_spec_driver": contract["driver"],
        "compile_context": authority_context,
        "diagnostics": [],
        "parse_errors": [],
        "definitions": [],
        "anchors": anchors,
        "bindings": [route["binding"] for route in routes],
        "pointer_edges": [],
        "calls": [],
        "module_init_targets": ["c:@F@generated_driver_init"],
        "registration_routes": routes,
        "route_errors": [],
        "operations": operation_rows,
        "strict_eligible_ops": len(strict_ids),
        "runtime_registered_ops": len(claimed),
        "runtime_registered_op_ids": sorted(claimed),
        "runtime_unregistered_op_ids": sorted(strict_ids - claimed),
        "missing_plan_ids": [],
        "unknown_plan_ids": [],
        "duplicate_anchors": [],
    }


def _ast_leaf_report(contract: dict, required_ids: list[str],
                     proven_ids: list[str] | None = None,
                     generated_sha: str | None = None,
                     plan: dict | None = None) -> dict:
    authority_sha, authority_context = _runtime_authority()
    generated_sha = generated_sha or authority_sha
    required = set(required_ids)
    proven = required if proven_ids is None else set(proven_ids)
    expected_shapes = {}
    for row in contract["register_operations"]:
        base = {
            "width_bits": {"B1": 8, "B2": 16, "B4": 32,
                           "B8": 64}.get(row.get("width")),
            "byte_order": (row.get("evidence") or {}).get(
                "byte_order", "native"),
            "write_semantics": (row.get("evidence") or {}).get(
                "write_semantics", "normal"),
        }
        if row["kind"] == "Read":
            shape = [{**base, "kind": "Read", "write_semantics": "normal"}]
        elif row["kind"] == "Write":
            shape = [{**base, "kind": "Write"}]
        elif (row.get("lowering_recipe") or {}).get("kind") == \
                "write_from_read":
            shape = [{**base, "kind": "Write"}]
        else:
            shape = [
                {**base, "kind": "Read", "write_semantics": "normal"},
                {**base, "kind": "Write"},
            ]
        expected_shapes[row["op_id"]] = shape
    operation_checks = []
    for row in contract["register_operations"]:
        op_id = row["op_id"]
        expected = expected_shapes[op_id]
        operation_checks.append({
            "op_id": op_id,
            "kind": row["kind"],
            "required": op_id in required,
            "expected": expected,
            "observed": copy.deepcopy(expected),
            "matches": op_id in proven,
        })
    primitive_mismatches = [
        row for row in operation_checks
        if row["required"] and not row["matches"]
    ]
    return {
        "schema": 1,
        "oracle": "generated-c-ast-leaf-v1",
        "claim_scope": {
            "backend_scope": ["harness", "baremetal"],
            "proves": [],
            "does_not_prove": [],
        },
        "driver": contract["driver"],
        "complete": not primitive_mismatches and proven == required,
        "generated": str(_AUTHORITY_GENERATED),
        "generated_sha256": generated_sha,
        "compile_context": authority_context,
        "required_ops": len(contract["register_operations"]),
        "required_ast_ops": len(required),
        "required_op_ids": sorted(required),
        "unknown_required_ids": [],
        "contract_ops": len(contract["register_operations"]),
        "anchors": len(contract["register_operations"]),
        "known_primitive_calls": len(contract["register_operations"]),
        "duplicate_expected_ids": [],
        "parse_errors": [],
        "diagnostics": [],
        "missing_anchors": [],
        "nonrequired_missing_anchors": [],
        "duplicate_anchors": [],
        "unknown_anchors": [],
        "malformed_anchors": [],
        "unsupported_expected_ops": [],
        "primitive_mismatches": primitive_mismatches,
        "trusted_primitive_delegations": [],
        "unanchored_primitives": [],
        "operation_checks": operation_checks,
    }


def _runtime_evidence(contract: dict, plan: dict) -> tuple[dict, dict]:
    from verification.generated_c_ast_oracle import verify_generated_c_ast
    from verification.linux_registration_ast_oracle import (
        linux_kbuild_compile_context,
        verify_linux_registration_ast,
    )

    strict_ids = sorted(entry["op_id"] for entry in plan["entries"]
                        if entry["strict_eligible"])
    functions = {}
    for entry in plan["entries"]:
        route = entry.get("route") or {}
        module = entry.get("module")
        if entry.get("strict_eligible") is not True or module in functions:
            continue
        functions[module] = SimpleNamespace(
            name=route.get("function") or module,
            ris_ref=module,
            role=route.get("role") or "unknown",
            callback_table=route.get("callback"),
        )
    device_spec = SimpleNamespace(
        name=contract["driver"], functions=list(functions.values()))
    clang_args, context = linux_kbuild_compile_context(
        _AUTHORITY_GENERATED, _AUTHORITY_KBUILD_CMD)
    ast = verify_generated_c_ast(
        contract, _AUTHORITY_GENERATED, clang_args=clang_args,
        required_op_ids=set(strict_ids), compile_context=context)
    registration = verify_linux_registration_ast(
        contract, device_spec, _AUTHORITY_GENERATED, plan,
        kbuild_cmd=_AUTHORITY_KBUILD_CMD)
    return registration, ast


def _effective_plan(formal: dict, device_spec: dict,
                    verified: dict) -> dict:
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    plan["entries"] = copy.deepcopy(verified["entries"])
    plan["summary"]["runtime_registered_ops"] = \
        verified["runtime_registered_ops"]
    plan["summary"]["ast_leaf_proven_ops"] = len(
        verified["linux_ast_leaf_proven_op_ids"])
    return plan


def test_plan_classifies_for_while_do_guard_body_and_nested_loops():
    nested_supported = _loop(
        "for", reliability="Exact", bounded=True, body=[_leaf("op_4")])
    formal = _formal(
        _leaf("op_1"),
        _loop("for", guard_ops=[_leaf("op_2")],
              body=[_leaf("op_3"), nested_supported]),
        _loop("while", guard_ops=[_leaf("op_5")], body=[_leaf("op_6")]),
        _loop("do", body=[_leaf("op_7")]),
    )
    report = verify_backend_lowering_plan(
        formal, _contract_for(formal), "harness")

    assert report["schema"] == 3
    assert report["oracle"] == "backend-lowering-plan-v3"
    assert report["accounting_complete"] is True
    assert report["classification_complete"] is True
    assert report["complete"] is False
    assert report["required_ops"] == report["planned_ops"] == 7
    assert report["lowered_ops"] == 1
    assert report["blocked_ops"] == 6
    entries = {entry["op_id"]: entry for entry in report["entries"]}
    assert entries["op_1"]["disposition"] == "lowered"
    assert entries["op_1"]["receipt_authorized"] is True
    assert entries["op_2"]["receipt_authorized"] is False
    assert entries["op_2"]["blocking_loop"]["region"] == "guard_ops"
    assert entries["op_3"]["blocking_loop"]["loop_kind"] == "for"
    assert len(entries["op_4"]["enclosing_loops"]) == 2
    assert entries["op_4"]["blocking_loop"]["depth"] == 1
    assert entries["op_5"]["blocking_loop"]["loop_kind"] == "while"
    assert entries["op_7"]["blocking_loop"]["loop_kind"] == "do"


def test_plan_lowers_supported_for_body_and_masked_drain_regions():
    formal = _formal(
        _loop("for", reliability="Exact", bounded=True,
              body=[_leaf("op_1")]),
        _loop("while", reliability="Exact", proof_kind="masked_w1c_drain",
              guard_ops=[_leaf("op_2")], body=[_leaf("op_3", "Write")]),
    )
    contract = _contract_for(formal)
    for backend in ("harness", "baremetal"):
        report = verify_backend_lowering_plan(
            formal, contract, backend,
            lowering_report=_lowering_report(contract, []))
        assert report["complete"] is True, (backend, report)
        assert report["definition_alignment_complete"] is True
        assert report["planned_ops"] == report["lowered_ops"] == 3
        assert report["authorized_ops"] == 3
        assert report["blocked_ops"] == 0


def test_bounded_for_guard_ops_fail_closed():
    formal = _formal(_loop(
        "for", reliability="Exact", bounded=True,
        guard_ops=[_leaf("op_1")], body=[_leaf("op_2")]))
    report = verify_backend_lowering_plan(
        formal, _contract_for(formal), "harness")
    entries = {entry["op_id"]: entry for entry in report["entries"]}
    assert report["accounting_complete"] is True
    assert report["complete"] is False
    assert entries["op_1"]["disposition"] == "blocked_unsupported_loop"
    assert "guard_ops" in entries["op_1"]["reason"]
    assert entries["op_2"]["disposition"] == "lowered"


def test_linux_definition_routes_authorization_and_loop_precedence():
    formal, contract, device_spec = _linux_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    blocked = sorted(entry["op_id"] for entry in plan["entries"]
                     if not entry["receipt_authorized"])
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, blocked))
    entries = {entry["op_id"]: entry for entry in report["entries"]}

    assert entries["op_probe"]["disposition"] == "candidate_definition_emit"
    assert entries["op_public_cb"]["disposition"] == \
        "candidate_definition_emit"
    assert entries["op_private_cb"]["disposition"] == \
        "definition_evidence_only"
    assert entries["op_helper"]["disposition"] == \
        "blocked_linux_root_unreachable"
    assert entries["op_remove"]["disposition"] == \
        "blocked_linux_lifecycle_stub"
    assert entries["op_shutdown"]["disposition"] == \
        "blocked_linux_lifecycle_unimplemented"
    for name in ("probe", "public_cb", "private_cb", "helper", "remove",
                 "shutdown"):
        assert entries[f"op_{name}_loop"]["disposition"] == \
            "blocked_unsupported_loop"
    assert report["authorized_ops"] == 3
    assert report["strict_eligible_ops"] == 2
    assert report["evidence_only_ops"] == 1
    assert report["blocked_ops"] == 9
    assert report["definition_alignment_complete"] is True
    assert report["runtime_complete"] is False
    assert report["strict_complete"] is False
    assert report["complete"] is False
    for entry in entries.values():
        if entry["receipt_authorized"]:
            assert entry["runtime_registration_proven"] is False
        if entry["disposition"].startswith("blocked_"):
            assert entry["receipt_authorized"] is False


def test_linux_call_closure_evidence_is_reported_but_not_authorized():
    formal, contract, device_spec = _linux_fixture()
    formal["metadata"]["call_graph"] = {
        "schema": 1,
        "oracle": "source-ast-call-v1",
        "lowering_enabled": False,
        "calls": [{
            "caller_module": "probe",
            "callee_module": "helper",
            "resolution_authority": "direct_function_declaration",
            "callsite": {"source": "fixture.c", "line": 10,
                         "column": 2, "offset": 100, "order": 1},
            "return_binding": {"status": "exact", "kind": "discarded"},
            "control": [],
            "multiplicity": {"kind": "syntactic_callsite",
                             "per_caller_invocation": 1,
                             "runtime_count_proven": False},
        }],
    }
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    helper = next(entry for entry in plan["entries"]
                  if entry["op_id"] == "op_helper")
    assert helper["disposition"] == "blocked_linux_root_unreachable"
    assert helper["receipt_authorized"] is False
    evidence = helper["call_closure_evidence"]
    assert evidence["status"] == "ast_reachable_but_lowering_disabled"
    assert evidence["strict_authorized"] is False
    assert evidence["path"][0]["callee_module"] == "helper"
    assert plan["summary"]["call_closure_evidence_ops"] == 1


def test_linux_runtime_registration_and_ast_leaf_complete_strict_plan():
    formal, contract, device_spec = _linux_runtime_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    runtime, ast = _runtime_evidence(contract, plan)
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())

    assert report["schema"] == 3
    assert report["oracle"] == "backend-lowering-plan-v3"
    assert report["definition_alignment_complete"] is True
    assert report["lowering_complete"] is True
    assert report["runtime_attestation_valid"] is True
    assert report["runtime_attestation_complete"] is True
    assert report["linux_ast_leaf_valid"] is True
    assert report["linux_ast_leaf_complete"] is True
    assert report["runtime_complete"] is True
    assert report["strict_complete"] is True
    assert report["complete"] is True
    assert report["runtime_registered_op_ids"] == [
        "op_probe", "op_public_cb"]
    assert report["runtime_and_ast_proven_op_ids"] == [
        "op_probe", "op_public_cb"]
    for entry in report["entries"]:
        assert entry["disposition"] == "candidate_definition_emit"
        assert entry["runtime_registration_proven"] is True
        assert entry["ast_leaf_proven"] is True
        operation = next(
            row for row in runtime["operations"]
            if row["op_id"] == entry["op_id"])
        assert entry["registration_route_id"] == \
            operation["route"]["route_id"]


def test_linux_runtime_and_ast_authority_metadata_mutations_fail_closed():
    formal, contract, device_spec = _linux_runtime_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    canonical_runtime, canonical_ast = _runtime_evidence(contract, plan)
    cases = (
        ("runtime", lambda value: value.update({"schema": 2}),
         "runtime_attestation_schema_mismatch"),
        ("runtime", lambda value: value.update({"oracle": "other"}),
         "runtime_attestation_oracle_mismatch"),
        ("runtime", lambda value: value.update({"driver": "other"}),
         "runtime_attestation_driver_mismatch"),
        ("ast", lambda value: value.update({"schema": 2}),
         "linux_ast_leaf_schema_mismatch"),
        ("ast", lambda value: value.update({"oracle": "other"}),
         "linux_ast_leaf_oracle_mismatch"),
        ("ast", lambda value: value.update({"driver": "other"}),
         "linux_ast_leaf_driver_mismatch"),
    )
    for authority, mutate, expected in cases:
        runtime = copy.deepcopy(canonical_runtime)
        ast = copy.deepcopy(canonical_ast)
        mutate(runtime if authority == "runtime" else ast)
        report = verify_backend_lowering_plan(
            formal, contract, "linux", device_spec=device_spec,
            lowering_report=_lowering_report(contract, []),
            runtime_attestation=runtime, ast_leaf_report=ast,
            **_runtime_authority_kwargs())
        errors = (report["runtime_attestation_errors"]
                  if authority == "runtime"
                  else report["linux_ast_leaf_errors"])
        assert expected in errors
        assert report["runtime_complete"] is False
        assert report["strict_complete"] is False
        assert report["complete"] is False


def test_linux_runtime_and_ast_operation_sets_fail_closed():
    formal, contract, device_spec = _linux_runtime_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    canonical_runtime, canonical_ast = _runtime_evidence(contract, plan)

    runtime = copy.deepcopy(canonical_runtime)
    runtime["operations"].pop()
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=canonical_ast,
        **_runtime_authority_kwargs())
    assert "runtime_attestation_operation_set_mismatch" in \
        report["runtime_attestation_errors"]
    assert report["runtime_complete"] is False

    ast = copy.deepcopy(canonical_ast)
    ast["operation_checks"].pop()
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=canonical_runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "linux_ast_leaf_operation_set_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert report["runtime_complete"] is False


def test_linux_runtime_route_id_must_be_nonempty():
    formal, contract, device_spec = _linux_runtime_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    canonical_runtime, ast = _runtime_evidence(contract, plan)
    for invalid_route_id in (None, ""):
        runtime = copy.deepcopy(canonical_runtime)
        runtime["operations"][0]["route"]["route_id"] = invalid_route_id
        report = verify_backend_lowering_plan(
            formal, contract, "linux", device_spec=device_spec,
            lowering_report=_lowering_report(contract, []),
            runtime_attestation=runtime, ast_leaf_report=ast,
            **_runtime_authority_kwargs())
        assert ({
            "runtime_attestation_route_reference_mismatch",
            "runtime_attestation_route_ids_invalid",
            "runtime_attestation_route_fingerprint_mismatch",
        } & set(report["runtime_attestation_errors"]))
        assert report["runtime_complete"] is False
        assert report["complete"] is False

    from verification.backend_lowering_plan import _route_fingerprint

    runtime = copy.deepcopy(canonical_runtime)
    operation = runtime["operations"][0]
    old_route_id = operation["route"]["route_id"]
    forged_route = copy.deepcopy(operation["route"])
    forged_usr = "c:plan_test.c@F@forged_probe"
    operation["anchor"]["function_usr"] = forged_usr
    forged_route["target_usr"] = forged_usr
    forged_route["target"] = "forged_probe"
    forged_route["binding"]["target_usr"] = forged_usr
    forged_route["binding"]["target"] = "forged_probe"
    forged_route["registration"]["chain"] = [{
        "kind": "registration_call",
        "call": "forged_platform_register",
        "location": {"file": str(_AUTHORITY_GENERATED), "line": 1,
                     "column": 1, "offset": 1},
    }]
    forged_route["route_id"] = _route_fingerprint(forged_route)
    operation["route"] = forged_route
    runtime["registration_routes"] = [
        forged_route if route["route_id"] == old_route_id else route
        for route in runtime["registration_routes"]
    ]
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert report["runtime_attestation_errors"] == []
    assert "runtime_attestation_independent_reverification_mismatch" in \
        report["runtime_artifact_authority_errors"]
    assert report["runtime_artifact_authority_valid"] is False
    assert report["runtime_complete"] is False
    assert report["complete"] is False


def test_linux_runtime_generated_sha_and_ast_required_set_fail_closed():
    formal, contract, device_spec = _linux_runtime_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    runtime, canonical_ast = _runtime_evidence(contract, plan)

    ast = copy.deepcopy(canonical_ast)
    ast["generated_sha256"] = "b" * 64
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "linux_runtime_generated_sha_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert report["runtime_complete"] is False

    runtime = copy.deepcopy(runtime)
    ast = copy.deepcopy(canonical_ast)
    runtime["generated_sha256"] = "f" * 64
    ast["generated_sha256"] = "f" * 64
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "runtime_attestation_generated_artifact_mismatch" in \
        report["runtime_attestation_errors"]
    assert "linux_ast_leaf_generated_artifact_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert {
        "runtime_attestation_independent_reverification_mismatch",
        "linux_ast_leaf_independent_reverification_mismatch",
    } <= set(report["runtime_artifact_authority_errors"])
    assert report["runtime_artifact_authority_valid"] is False
    assert report["runtime_complete"] is False

    runtime, canonical_ast = _runtime_evidence(contract, plan)
    ast = copy.deepcopy(canonical_ast)
    ast["compile_context"]["arguments_sha256"] = "d" * 64
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "linux_runtime_compile_context_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert report["runtime_complete"] is False

    runtime = copy.deepcopy(runtime)
    ast = copy.deepcopy(canonical_ast)
    forged_context = {
        "origin": "kbuild-cmd",
        "provenance": "/forged/.plan_test.o.cmd",
        "raw_command_sha256": "d" * 64,
        "arguments_sha256": "e" * 64,
        "argument_count": 1,
    }
    runtime["compile_context"] = copy.deepcopy(forged_context)
    ast["compile_context"] = copy.deepcopy(forged_context)
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "runtime_attestation_compile_context_authority_mismatch" in \
        report["runtime_attestation_errors"]
    assert "linux_ast_leaf_compile_context_authority_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert {
        "runtime_attestation_independent_reverification_mismatch",
        "linux_ast_leaf_independent_reverification_mismatch",
    } <= set(report["runtime_artifact_authority_errors"])
    assert report["runtime_artifact_authority_valid"] is False
    assert report["runtime_complete"] is False

    runtime, canonical_ast = _runtime_evidence(contract, plan)
    ast = copy.deepcopy(canonical_ast)
    ast["required_op_ids"].pop()
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=_lowering_report(contract, []),
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert "linux_ast_leaf_required_set_mismatch" in \
        report["linux_ast_leaf_errors"]
    assert report["runtime_complete"] is False


def test_linux_runtime_cannot_authorize_blocked_or_evidence_only_ops():
    formal, contract, device_spec = _linux_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    strict_ids = sorted(entry["op_id"] for entry in plan["entries"]
                        if entry["strict_eligible"])
    blocked = sorted(entry["op_id"] for entry in plan["entries"]
                     if not entry["receipt_authorized"])
    ast = _ast_leaf_report(contract, strict_ids, plan=plan)
    dispositions = {entry["op_id"]: entry["disposition"]
                    for entry in plan["entries"]}
    assert dispositions["op_private_cb"] == "definition_evidence_only"
    assert dispositions["op_helper"] == "blocked_linux_root_unreachable"

    for unauthorized_id in ("op_private_cb", "op_helper"):
        runtime = _runtime_attestation(
            contract, [*strict_ids, unauthorized_id], plan=plan)
        report = verify_backend_lowering_plan(
            formal, contract, "linux", device_spec=device_spec,
            lowering_report=_lowering_report(contract, blocked),
            runtime_attestation=runtime, ast_leaf_report=ast,
            **_runtime_authority_kwargs())
        assert "runtime_attestation_authorizes_non_candidate" in \
            report["runtime_attestation_errors"]
        assert report["runtime_attestation_valid"] is False
        assert unauthorized_id not in report["runtime_registered_op_ids"]
        assert report["strict_complete"] is False


def test_candidate_runtime_fields_cannot_override_independent_evidence():
    formal, contract, device_spec = _linux_runtime_fixture()
    base = build_backend_lowering_plan(formal, "linux", device_spec)
    runtime, ast = _runtime_evidence(contract, base)
    lowering = _lowering_report(contract, [])
    verified = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=lowering, runtime_attestation=runtime,
        ast_leaf_report=ast, **_runtime_authority_kwargs())
    effective = _effective_plan(formal, device_spec, verified)
    accepted = verify_backend_lowering_plan(
        formal, contract, "linux", plan=effective,
        device_spec=device_spec, lowering_report=lowering,
        runtime_attestation=runtime, ast_leaf_report=ast,
        **_runtime_authority_kwargs())
    assert accepted["complete"] is True, accepted

    for field, value in (
        ("runtime_registration_proven", False),
        ("ast_leaf_proven", False),
        ("registration_route_id", "tampered-route"),
    ):
        candidate = copy.deepcopy(effective)
        candidate["entries"][0][field] = value
        report = verify_backend_lowering_plan(
            formal, contract, "linux", plan=candidate,
            device_spec=device_spec, lowering_report=lowering,
            runtime_attestation=runtime, ast_leaf_report=ast,
            **_runtime_authority_kwargs())
        assert report["classification_complete"] is False
        assert report["authorization_complete"] is False
        assert report["strict_complete"] is False
        assert report["complete"] is False


def test_linux_accepts_device_spec_object_without_generator_dependency():
    formal = _formal(_leaf("op_1"))
    contract = _contract_for(formal)
    device_spec = SimpleNamespace(name="plan-test", functions=[SimpleNamespace(
        name="probe", ris_ref="probe", role="probe",
        is_callback_entry=True, callback_table="platform_driver.probe")])
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    assert plan["entries"][0]["disposition"] == "candidate_definition_emit"
    assert plan["entries"][0]["route"]["callback"] == \
        "platform_driver.probe"

    wrong_driver = copy.deepcopy(device_spec)
    wrong_driver.name = "other-driver"
    try:
        build_backend_lowering_plan(formal, "linux", wrong_driver)
    except ValueError as error:
        assert "does not match Formal driver" in str(error)
    else:
        raise AssertionError("mismatched DeviceSpec driver must fail closed")

    contradictory = copy.deepcopy(device_spec)
    contradictory.functions[0].is_callback_entry = False
    try:
        build_backend_lowering_plan(formal, "linux", contradictory)
    except ValueError as error:
        assert "contradicts is_callback_entry" in str(error)
    else:
        raise AssertionError("contradictory callback ownership must fail closed")


def test_duplicate_and_missing_contract_or_plan_fail_closed():
    formal = _formal(_leaf("op_1"), _leaf("op_2", "Write"))
    contract = _contract_for(formal)

    duplicate_contract = copy.deepcopy(contract)
    duplicate_contract["register_operations"].append(copy.deepcopy(
        duplicate_contract["register_operations"][0]))
    report = verify_backend_lowering_plan(
        formal, duplicate_contract, "baremetal")
    assert report["complete"] is False
    assert report["accounting_complete"] is False
    assert report["duplicate_contract_ids"] == ["op_1"]

    missing_contract = copy.deepcopy(contract)
    missing_contract["register_operations"].pop()
    report = verify_backend_lowering_plan(formal, missing_contract, "harness")
    assert report["complete"] is False
    assert report["missing_from_contract"] == ["op_2"]

    plan = build_backend_lowering_plan(formal, "harness")
    plan["entries"].append(copy.deepcopy(plan["entries"][0]))
    report = verify_backend_lowering_plan(formal, contract, "harness", plan)
    assert report["complete"] is False
    assert report["duplicate_plan_ids"] == ["op_1"]

    plan = build_backend_lowering_plan(formal, "harness")
    plan["entries"] = plan["entries"][:-1]
    report = verify_backend_lowering_plan(formal, contract, "harness", plan)
    assert report["complete"] is False
    assert report["missing_plan_ops"] == ["op_2"]


def test_candidate_schema_policy_summary_route_and_authorization_mutations_fail():
    formal, contract, device_spec = _linux_fixture()
    canonical = build_backend_lowering_plan(formal, "linux", device_spec)

    mutations = []
    for mutate in (
        lambda plan: plan.update({"schema": 2}),
        lambda plan: plan.update({"oracle": "backend-lowering-plan-v2"}),
        lambda plan: plan.update({"driver": "other-driver"}),
        lambda plan: plan["policy"].update({"cardinality": "at-most-once"}),
        lambda plan: plan["summary"].update({"authorized_ops": 999}),
        lambda plan: plan["entries"][0]["route"].update({"role": "helper"}),
        lambda plan: plan["entries"][0].update({"receipt_authorized": False}),
        lambda plan: plan["entries"][0].update({"strict_eligible": False}),
        lambda plan: plan["entries"][0].update({
            "runtime_registration_proven": True}),
        lambda plan: plan["entries"][0].update({
            "disposition": "definition_evidence_only"}),
    ):
        plan = copy.deepcopy(canonical)
        mutate(plan)
        mutations.append(plan)

    for plan in mutations:
        report = verify_backend_lowering_plan(
            formal, contract, "linux", plan, device_spec)
        assert report["complete"] is False
        assert report["definition_alignment_complete"] is False
        assert (report["classification_mismatches"]
                or report["plan_envelope_mismatch"])


def test_candidate_cannot_relabel_or_authorize_blocked_operation():
    formal = _formal(_loop("while", body=[_leaf("op_1")]))
    contract = _contract_for(formal)
    plan = build_backend_lowering_plan(formal, "harness")
    plan["entries"][0].update({
        "disposition": "lowered",
        "reason": None,
        "receipt_authorized": True,
        "strict_eligible": True,
        "blocking_loop": None,
    })
    report = verify_backend_lowering_plan(formal, contract, "harness", plan)
    assert report["complete"] is False
    assert report["classification_complete"] is False
    assert report["classification_mismatches"][0]["op_id"] == "op_1"


def test_formal_duplicate_id_fails_closed():
    formal = _formal(_leaf("op_1"), _leaf("op_1", "Write"))
    contract = _contract_for(formal)
    report = verify_backend_lowering_plan(formal, contract, "harness")
    assert report["complete"] is False
    assert report["duplicate_formal_ids"] == ["op_1"]
    assert report["duplicate_contract_ids"] == ["op_1"]


def test_lowering_report_reconciliation_accepts_authorized_receipts_only():
    formal, contract, device_spec = _linux_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    blocked = sorted(entry["op_id"] for entry in plan["entries"]
                     if not entry["receipt_authorized"])
    lowering = _lowering_report(contract, blocked)
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=lowering)
    assert report["reconciliation_performed"] is True
    assert report["reconciliation_complete"] is True
    assert report["unauthorized_receipts"] == []
    assert report["authorized_missing"] == []
    assert report["definition_alignment_complete"] is True
    assert report["runtime_complete"] is False


def test_lowering_report_reconciliation_fails_closed_for_receipt_errors():
    formal, contract, device_spec = _linux_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    blocked = sorted(entry["op_id"] for entry in plan["entries"]
                     if not entry["receipt_authorized"])
    authorized = sorted(entry["op_id"] for entry in plan["entries"]
                        if entry["receipt_authorized"])

    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec)
    assert report["reconciliation_performed"] is False
    assert report["reconciliation_complete"] is False
    assert report["definition_alignment_complete"] is False
    assert report["strict_complete"] is False
    assert report["lowering_report_errors"] == ["lowering_report_missing"]

    blocked_receipt = _lowering_report(contract, blocked[1:])
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=blocked_receipt)
    assert report["reconciliation_complete"] is False
    assert report["unauthorized_receipts"] == [blocked[0]]

    authorized_missing = _lowering_report(contract, [*blocked, authorized[0]])
    report = verify_backend_lowering_plan(
        formal, contract, "linux", device_spec=device_spec,
        lowering_report=authorized_missing)
    assert report["authorized_missing"] == [authorized[0]]
    assert report["reconciliation_complete"] is False

    for category in ("duplicate", "unknown", "rejected", "digest_mismatch",
                     "kind_mismatch"):
        lowering = _lowering_report(contract, blocked)
        lowering[category] = ["op_report_error"]
        report = verify_backend_lowering_plan(
            formal, contract, "linux", device_spec=device_spec,
            lowering_report=lowering)
        assert report["reconciliation_complete"] is False
        assert category in report["lowering_report_errors"]

    for mutate, expected in (
        (lambda value: value.pop("schema"),
         "lowering_report_fields_missing"),
        (lambda value: value.update({"schema": 2}),
         "lowering_report_schema_mismatch"),
        (lambda value: value.update({"complete": True}),
         "complete_mismatch"),
        (lambda value: value["missing"].append(value["missing"][0]),
         "invalid_missing_ids"),
    ):
        lowering = _lowering_report(contract, blocked)
        mutate(lowering)
        report = verify_backend_lowering_plan(
            formal, contract, "linux", device_spec=device_spec,
            lowering_report=lowering)
        assert report["reconciliation_complete"] is False
        assert expected in report["lowering_report_errors"]


def test_cli_harness_compatibility_and_linux_requires_device_spec():
    formal = _formal(_loop("do", body=[_leaf("op_1")]))
    contract = _contract_for(formal)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        formal_path = root / "formal.json"
        contract_path = root / "contract.json"
        output = root / "nested" / "plan.json"
        formal_path.write_text(json.dumps(formal), encoding="utf-8")
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        base = [
            sys.executable,
            str(REHARNESS / "verification" / "backend_lowering_plan.py"),
            "--formal", str(formal_path),
            "--contract", str(contract_path),
        ]
        process = subprocess.run([
            *base, "--backend", "baremetal", "--output", str(output),
        ], cwd=REHARNESS, capture_output=True, text=True)
        assert process.returncode == 2, process.stdout + process.stderr
        report = json.loads(process.stdout)
        assert report == json.loads(output.read_text(encoding="utf-8"))
        assert report["accounting_complete"] is True
        assert report["blocked_op_ids"] == ["op_1"]

        process = subprocess.run([
            *base, "--backend", "linux",
        ], cwd=REHARNESS, capture_output=True, text=True)
        assert process.returncode == 3, process.stdout + process.stderr
        report = json.loads(process.stdout)
        assert "--device-spec-json" in report["message"]


def test_cli_linux_device_spec_and_lowering_report():
    formal, contract, device_spec = _linux_fixture()
    plan = build_backend_lowering_plan(formal, "linux", device_spec)
    blocked = sorted(entry["op_id"] for entry in plan["entries"]
                     if not entry["receipt_authorized"])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = {
            "formal": root / "formal.json",
            "contract": root / "contract.json",
            "device": root / "device.json",
            "lowering": root / "lowering.json",
        }
        for key, value in (("formal", formal), ("contract", contract),
                           ("device", _device_spec_document(device_spec)),
                           ("lowering", _lowering_report(contract, blocked))):
            paths[key].write_text(json.dumps(value), encoding="utf-8")
        process = subprocess.run([
            sys.executable,
            str(REHARNESS / "verification" / "backend_lowering_plan.py"),
            "--formal", str(paths["formal"]),
            "--contract", str(paths["contract"]),
            "--backend", "linux",
            "--device-spec-json", str(paths["device"]),
            "--lowering-report", str(paths["lowering"]),
        ], cwd=REHARNESS, capture_output=True, text=True)
        assert process.returncode == 2, process.stdout + process.stderr
        report = json.loads(process.stdout)
        assert report["definition_alignment_complete"] is True
        assert report["reconciliation_complete"] is True
        assert report["runtime_complete"] is False


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
