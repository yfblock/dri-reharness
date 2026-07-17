from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


REHARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REHARNESS))

from verification.backend_lowering_plan import (
    build_backend_lowering_plan,
    verify_backend_lowering_plan,
)


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
    contract = _contract_for(formal)
    report = verify_backend_lowering_plan(formal, contract, "harness")

    assert report["accounting_complete"] is True
    assert report["classification_complete"] is True
    assert report["complete"] is False
    assert report["required_ops"] == report["planned_ops"] == 7
    assert report["lowered_ops"] == 1
    assert report["blocked_ops"] == 6
    entries = {entry["op_id"]: entry for entry in report["entries"]}
    assert entries["op_1"]["disposition"] == "lowered"
    assert entries["op_2"]["blocking_loop"]["region"] == "guard_ops"
    assert entries["op_3"]["blocking_loop"]["loop_kind"] == "for"
    # The supported nested loop cannot override its unsupported outer loop.
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
        report = verify_backend_lowering_plan(formal, contract, backend)
        assert report["complete"] is True, (backend, report)
        assert report["accounting_complete"] is True
        assert report["planned_ops"] == report["lowered_ops"] == 3
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


def test_candidate_cannot_relabel_blocked_operation_as_lowered():
    formal = _formal(_loop("while", body=[_leaf("op_1")]))
    contract = _contract_for(formal)
    plan = build_backend_lowering_plan(formal, "harness")
    plan["entries"][0].update({
        "disposition": "lowered",
        "reason": None,
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


def test_cli_writes_json_and_returns_nonzero_for_accounted_blocker():
    formal = _formal(_loop("do", body=[_leaf("op_1")]))
    contract = _contract_for(formal)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        formal_path = root / "formal.json"
        contract_path = root / "contract.json"
        output = root / "nested" / "plan.json"
        formal_path.write_text(json.dumps(formal), encoding="utf-8")
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        process = subprocess.run([
            sys.executable,
            str(REHARNESS / "verification" / "backend_lowering_plan.py"),
            "--formal", str(formal_path),
            "--contract", str(contract_path),
            "--backend", "baremetal",
            "--output", str(output),
        ], cwd=REHARNESS, capture_output=True, text=True)
        assert process.returncode == 2, process.stdout + process.stderr
        report = json.loads(process.stdout)
        assert report == json.loads(output.read_text(encoding="utf-8"))
        assert report["accounting_complete"] is True
        assert report["complete"] is False
        assert report["blocked_op_ids"] == ["op_1"]


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
