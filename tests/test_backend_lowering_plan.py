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

    assert report["schema"] == 2
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
        lambda plan: plan.update({"schema": 1}),
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
