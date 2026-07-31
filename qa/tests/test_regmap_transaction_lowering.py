from __future__ import annotations

import subprocess

from extractor.extractor import ExtractorConfig, extract_ris
from extractor.spec import default_bind
from generator import baremetal, harness, linux
from verification.backend_lowering_oracle import (
    build_generation_contract, verify_backend_lowering,
)
from verification.regmap_transaction_ast_oracle import (
    verify_regmap_runtime_trace, verify_regmap_transaction_ast,
)
from verification.regmap_transaction_mutation_oracle import verify_regmap_mutations


def _fixture():
    return extract_ris(ExtractorConfig(source="tests/fixtures/regmap_access.c"))


def test_regmap_contract_lowers_scalar_update_bulk_in_harness_and_baremetal(tmp_path):
    result = _fixture()
    contract = build_generation_contract(result.formal)
    assert [row["kind"] for row in contract["transaction_operations"]] == [
        "TransactionRead", "TransactionWrite", "TransactionUpdate",
        "TransactionRead"]
    for backend, generate in (("harness", harness.generate),
                              ("baremetal", baremetal.generate)):
        source = generate(result.formal, result.device_spec,
                          default_bind(result.device_spec, backend))
        assert verify_backend_lowering(result.formal, source)["complete"]
        assert verify_regmap_transaction_ast(contract, source)["complete"]
        path = tmp_path / f"{backend}.c"
        path.write_text(source, encoding="utf-8")
        flags = [] if backend == "harness" else ["-DREHARNESS_BAREMETAL_ORACLE"]
        binary = tmp_path / backend
        command = ["cc", "-std=gnu11", *flags, str(path)]
        if backend == "harness":
            command += ["-o", str(binary)]
        else:
            command += ["-c", "-o", str(binary.with_suffix(".o"))]
        subprocess.run(command, check=True, capture_output=True, text=True)
        if backend == "harness":
            trace = subprocess.run([str(binary)], check=True,
                                   capture_output=True, text=True).stdout
            assert verify_regmap_runtime_trace(contract, trace)["complete"]
            assert verify_regmap_mutations(contract, source, trace)["complete"]


def test_regmap_ast_oracle_detects_helper_and_order_mutations():
    result = _fixture()
    contract = build_generation_contract(result.formal)
    source = harness.generate(result.formal, result.device_spec,
                              default_bind(result.device_spec, "harness"))
    mutated = source.replace(
        "(void)reharness_regmap_update((void *)(dev->regmap)",
        "(void)reharness_regmap_write((void *)(dev->regmap)", 1)
    report = verify_regmap_transaction_ast(contract, mutated)
    assert report["complete"] is False
    assert report["primitive_mismatches"]
    reordered = source
    # Trace order is independently checked even when all AST shapes remain.
    trace = "\n".join([
        "[txn 0] id=op_1 W transport=regmap selector=0x00000000 count=1 value=0x00000000",
        "[txn 1] id=op_2 R transport=regmap selector=0x00000004 count=1 value=0x00000000",
        "[txn 2] id=op_3 U transport=regmap selector=0x00000008 count=1 value=0x00000055",
        "[txn 3] id=op_4 BR transport=regmap selector=0x0000000c count=2 value=0x00000000",
    ])
    assert verify_regmap_runtime_trace(contract, trace)["complete"] is False
    assert reordered


def test_regmap_linux_contract_uses_real_regmap_wrappers():
    result = _fixture()
    source = linux.generate(result.formal, result.device_spec,
                            default_bind(result.device_spec, "linux"))
    assert "#include <linux/regmap.h>" in source
    assert "regmap_update_bits" in source
    # The fixture's helper is intentionally not a Linux callback root; the
    # backend still exposes the same real-regmap ABI for reachable modules.
    assert "reharness_regmap_bulk_read" in source
