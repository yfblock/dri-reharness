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


SOURCE = "vendor/linux/drivers/gpio/gpio-tpic2810.c"


def test_tpic2810_i2c_smbus_runner_all_backends(tmp_path):
    result = extract_ris(ExtractorConfig(source=SOURCE))
    contract = build_generation_contract(result.formal)
    rows = contract["transaction_operations"]
    assert len(rows) == 2
    assert {row["transport"] for row in rows} == {"i2c_smbus"}
    assert {row["contract"]["protocol"] for row in rows} == {"smbus_byte_data"}

    for backend, generate in (("harness", harness.generate),
                              ("baremetal", baremetal.generate),
                              ("linux", linux.generate)):
        source = generate(result.formal, result.device_spec,
                          default_bind(result.device_spec, backend))
        assert verify_backend_lowering(result.formal, source)["complete"]
        assert verify_regmap_transaction_ast(contract, source)["complete"]
        assert "reharness_i2c_smbus_write_byte_data" in source
        if backend == "linux":
            assert "i2c_smbus_write_byte_data" in source
            continue
        path = tmp_path / f"{backend}.c"
        path.write_text(source, encoding="utf-8")
        binary = tmp_path / backend
        flags = ["-DREHARNESS_BAREMETAL_ORACLE"] if backend == "baremetal" else []
        subprocess.run(["cc", "-std=gnu11", *flags, str(path), "-o", str(binary)],
                       check=True, capture_output=True, text=True)
        trace = subprocess.run([str(binary)], check=True,
                               capture_output=True, text=True).stdout
        assert verify_regmap_runtime_trace(contract, trace)["complete"]
        assert verify_regmap_mutations(contract, source, trace)["complete"]


def test_i2c_contract_covers_all_public_api_shapes_in_harness_and_baremetal(tmp_path):
    result = extract_ris(ExtractorConfig(
        source="qa/tests/fixtures/i2c_transaction_access.c"))
    contract = build_generation_contract(result.formal)
    rows = contract["transaction_operations"]
    assert len(rows) == 14
    assert {row["contract"].get("protocol") for row in rows} == {
        "smbus_byte", "smbus_byte_data", "smbus_word_data",
        "smbus_word_data_swapped", "smbus_block", "i2c_block", "raw",
    }
    for backend, generate in (("harness", harness.generate),
                              ("baremetal", baremetal.generate)):
        source = generate(result.formal, result.device_spec,
                          default_bind(result.device_spec, backend))
        assert verify_backend_lowering(result.formal, source)["complete"]
        assert verify_regmap_transaction_ast(contract, source)["complete"]
        path = tmp_path / f"all-{backend}.c"
        path.write_text(source, encoding="utf-8")
        binary = tmp_path / f"all-{backend}"
        flags = ["-DREHARNESS_BAREMETAL_ORACLE"] if backend == "baremetal" else []
        subprocess.run(["cc", "-std=gnu11", *flags, str(path), "-o", str(binary)],
                       check=True, capture_output=True, text=True)
        trace = subprocess.run([str(binary)], check=True,
                               capture_output=True, text=True).stdout
        assert verify_regmap_runtime_trace(contract, trace)["complete"]
