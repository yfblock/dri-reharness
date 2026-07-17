from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


REHARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REHARNESS))

from verification.generated_c_ast_oracle import verify_generated_c_ast


def _row(op_id: str, kind: str, width: str = "B4", *,
         byte_order: str = "native", write_semantics: str = "normal",
         lowering_recipe: dict | None = None) -> dict:
    evidence = {"byte_order": byte_order}
    if write_semantics != "normal":
        evidence["write_semantics"] = write_semantics
    row = {
        "op_id": op_id,
        "module": "probe",
        "kind": kind,
        "digest": "0000000000000000",
        "width": width,
        "reliability": "Exact",
        "access_domain": "mmio",
        "evidence": evidence,
    }
    if lowering_recipe is not None:
        row["lowering_recipe"] = lowering_recipe
    return row


def _contract(*rows: dict) -> dict:
    return {
        "schema": 1,
        "driver": "ast-oracle-test",
        "register_operations": list(rows),
    }


def _write(tmp_path: Path, body: str) -> Path:
    source = tmp_path / "generated.c"
    source.write_text("""
#include <stdint.h>
static uint32_t harness_read32(uintptr_t a) { return (uint32_t)a; }
static uint32_t harness_read32be(uintptr_t a) { return (uint32_t)a; }
static void harness_write16(uint16_t v, uintptr_t a) { (void)v; (void)a; }
static void harness_write32(uint32_t v, uintptr_t a) { (void)v; (void)a; }
static void harness_write_w1c32(uint32_t v, uintptr_t a) {
    harness_write32(v, a);
}
static void harness_write32be(uint32_t v, uintptr_t a) { (void)v; (void)a; }
static void generated(uintptr_t base) {
""" + body + "\n}\n", encoding="utf-8")
    return source


def test_ast_oracle_accepts_exact_read_write_rmw_and_helper_boundaries(tmp_path):
    contract = _contract(
        _row("op_1", "Read"),
        _row("op_2", "Write", "B4", write_semantics="w1c"),
        _row("op_3", "ReadModifyWrite", "B4", byte_order="big"),
    )
    source = _write(tmp_path, """
    __rh_op_op_1: { (void)harness_read32(base); }
    __rh_op_op_2: { harness_write_w1c32(1, base); }
    __rh_op_op_3: {
        uint32_t v = harness_read32be(base);
        harness_write32be(v | 1, base);
    }
""")
    report = verify_generated_c_ast(contract, source)
    assert report["complete"] is True
    assert report["anchors"] == 3
    assert report["primitive_mismatches"] == []
    # The W1C primitive delegates to another known primitive, but its helper
    # implementation is a trusted boundary rather than an unanchored RIS op.
    assert report["unanchored_primitives"] == []


def test_ast_oracle_rejects_wrong_kind_width_endian_and_rmw_cardinality(tmp_path):
    contract = _contract(
        _row("op_1", "Read", "B4", byte_order="big"),
        _row("op_2", "Write", "B4"),
        _row("op_3", "ReadModifyWrite", "B4"),
    )
    source = _write(tmp_path, """
    __rh_op_op_1: { (void)harness_read32(base); }
    __rh_op_op_2: { harness_write16(1, base); }
    __rh_op_op_3: { harness_write32(1, base); }
""")
    report = verify_generated_c_ast(contract, source)
    assert report["complete"] is False
    assert [item["op_id"] for item in report["primitive_mismatches"]] == [
        "op_1", "op_2", "op_3"]


def test_ast_oracle_distinguishes_write_from_read_from_intrinsic_rmw(tmp_path):
    contract = _contract(
        _row("op_1", "Read"),
        _row("op_2", "ReadModifyWrite", lowering_recipe={
            "kind": "write_from_read", "primitives": ["Write"],
            "read_op_id": "op_1",
        }),
    )
    source = _write(tmp_path, """
    uint32_t value = 0;
    __rh_op_op_1: { value = harness_read32(base); }
    __rh_op_op_2: { harness_write32(value | 1, base); }
""")
    report = verify_generated_c_ast(contract, source)
    assert report["complete"] is True

    duplicated_read = _write(tmp_path, """
    uint32_t value = 0;
    __rh_op_op_1: { value = harness_read32(base); }
    __rh_op_op_2: {
        value = harness_read32(base);
        harness_write32(value | 1, base);
    }
""")
    rejected = verify_generated_c_ast(contract, duplicated_read)
    assert rejected["complete"] is False
    assert rejected["primitive_mismatches"][0]["op_id"] == "op_2"


def test_ast_oracle_rejects_missing_unknown_malformed_and_unanchored(tmp_path):
    contract = _contract(_row("op_1", "Read"), _row("op_2", "Write"))
    source = _write(tmp_path, """
    __rh_op_op_1: (void)harness_read32(base);
    __rh_op_op_unknown: { harness_write32(1, base); }
    harness_write32(2, base);
""")
    report = verify_generated_c_ast(contract, source)
    assert report["complete"] is False
    assert report["missing_anchors"] == ["op_2"]
    assert report["unknown_anchors"] == ["op_unknown"]
    assert report["malformed_anchors"] == ["op_1"]
    assert len(report["unanchored_primitives"]) == 1


def test_ast_oracle_fails_closed_on_parse_errors_and_unsupported_contract(tmp_path):
    source = _write(tmp_path, """
    __rh_op_op_1: { (void)harness_read32(base) }
""")
    bad_parse = verify_generated_c_ast(_contract(_row("op_1", "Read")), source)
    assert bad_parse["complete"] is False
    assert bad_parse["parse_errors"]

    source = _write(tmp_path, "__rh_op_op_1: { ; }")
    row = _row("op_1", "Read")
    row["reliability"] = "Unsupported"
    unsupported = verify_generated_c_ast(_contract(row), source)
    assert unsupported["complete"] is False
    assert unsupported["unsupported_expected_ops"] == ["op_1"]


def test_ast_oracle_cli_emits_json_and_nonzero_on_semantic_mismatch(tmp_path):
    contract_path = tmp_path / "generation-contract.json"
    contract_path.write_text(
        json.dumps(_contract(_row("op_1", "Read"))), encoding="utf-8")
    source = _write(tmp_path, "__rh_op_op_1: { harness_write32(1, base); }")
    output = tmp_path / "nested" / "report.json"
    result = subprocess.run([
        sys.executable,
        str(REHARNESS / "verification" / "generated_c_ast_oracle.py"),
        "--contract", str(contract_path),
        "--generated", str(source),
        "--output", str(output),
    ], cwd=REHARNESS, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report == json.loads(output.read_text(encoding="utf-8"))
    assert report["complete"] is False
    assert report["primitive_mismatches"][0]["op_id"] == "op_1"


def test_ast_oracle_accepts_real_harness_and_baremetal_generation(tmp_path):
    # Use an isolated process because the extractor and oracle both configure
    # process-global libclang state; the production CLI is isolated likewise.
    script = r'''
import json
from pathlib import Path
import sys
from extractor.extractor import ExtractorConfig, extract_ris
from extractor.spec import default_bind
from generator import baremetal, harness
from verification.generated_c_ast_oracle import verify_generated_c_ast

root, output = Path(sys.argv[1]), Path(sys.argv[2])
result = extract_ris(ExtractorConfig(
    source=str(root / "drivers" / "test" / "gpio-ftgpio010.c")))
reports = {}
for backend, generate in (("harness", harness.generate),
                          ("baremetal", baremetal.generate)):
    source = output / f"{backend}.c"
    source.write_text(generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, backend)), encoding="utf-8")
    reports[backend] = verify_generated_c_ast(result.formal, source)
print(json.dumps(reports))
'''
    process = subprocess.run(
        [sys.executable, "-c", script, str(REHARNESS), str(tmp_path)],
        cwd=REHARNESS, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    reports = json.loads(process.stdout)
    for backend, report in reports.items():
        assert report["complete"] is True, (backend, report)
        assert report["required_ops"] == report["anchors"] == 35
        assert report["primitive_mismatches"] == []
        assert report["unanchored_primitives"] == []


def _run_standalone() -> int:
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    passed = failed = 0
    for test in tests:
        try:
            with tempfile.TemporaryDirectory() as directory:
                test(Path(directory))
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
