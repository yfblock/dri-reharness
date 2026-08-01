from __future__ import annotations

import subprocess
from pathlib import Path

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


SOURCE = "vendor/linux/drivers/clk/clk-twl6040.c"


def test_twl6040_mfd_runner_all_backends(tmp_path):
    result = extract_ris(ExtractorConfig(source=SOURCE))
    contract = build_generation_contract(result.formal)
    rows = contract["transaction_operations"]
    assert [row["contract"]["helper_contract"] for row in rows] == [
        "set_bits", "clear_bits"
    ]

    for backend, generate in (("harness", harness.generate),
                              ("baremetal", baremetal.generate)):
        source = generate(result.formal, result.device_spec,
                          default_bind(result.device_spec, backend))
        assert verify_backend_lowering(result.formal, source)["complete"]
        assert verify_regmap_transaction_ast(
            contract, source, backend=backend)["complete"]
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

    source = linux.generate(result.formal, result.device_spec,
                            default_bind(result.device_spec, "linux"))
    assert "#include <linux/mfd/twl6040.h>" in source
    assert "void *mfd;" in source
    assert "twl6040_set_bits" in source
    assert "twl6040_clear_bits" in source
    assert verify_backend_lowering(result.formal, source)["complete"]
    assert verify_regmap_transaction_ast(
        contract, source, backend="linux")["complete"]

    kernel_build = Path("platform/kernel/build").resolve()
    if (kernel_build / "Makefile").is_file():
        module_dir = tmp_path / "linux-mfd-module"
        module_dir.mkdir()
        (module_dir / "rh_mfd_c27.c").write_text(source, encoding="utf-8")
        (module_dir / "Makefile").write_text(
            "obj-m += rh_mfd_c27.o\n", encoding="utf-8")
        built = subprocess.run(
            ["make", "-C", str(kernel_build), f"M={module_dir}", "modules"],
            capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr


def test_mfd_linux_helper_substitution_is_rejected():
    result = extract_ris(ExtractorConfig(source=SOURCE))
    contract = build_generation_contract(result.formal)
    source = linux.generate(result.formal, result.device_spec,
                            default_bind(result.device_spec, "linux"))
    mutated = source.replace("twl6040_set_bits(", "twl6040_clear_bits(", 1)
    assert not verify_regmap_transaction_ast(
        contract, mutated, backend="linux")["complete"]
