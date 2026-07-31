#!/usr/bin/env python3
"""Fail-closed mutation suite for the regmap lowering contract."""
from __future__ import annotations

try:
    from .regmap_transaction_ast_oracle import (
        verify_regmap_runtime_trace, verify_regmap_transaction_ast,
    )
except ImportError:  # pragma: no cover
    from regmap_transaction_ast_oracle import (
        verify_regmap_runtime_trace, verify_regmap_transaction_ast,
    )


def verify_regmap_mutations(contract: dict, generated: str, trace: str) -> dict:
    mutations = {}
    if "(void)reharness_mfd_update(" in generated:
        helper_mutation = generated.replace(
            "(void)reharness_mfd_update(",
            "(void)reharness_mfd_write(", 1)
    elif "twl6040_set_bits(" in generated:
        helper_mutation = generated.replace(
            "twl6040_set_bits(", "twl6040_clear_bits(", 1)
    elif "(void)reharness_i2c_smbus_write_byte_data(" in generated:
        helper_mutation = generated.replace(
            "(void)reharness_i2c_smbus_write_byte_data(",
            "(void)reharness_i2c_smbus_read_byte_data(", 1)
    else:
        helper_mutation = generated.replace(
            "reharness_regmap_update((void *)(dev->regmap)",
            "reharness_regmap_write((void *)(dev->regmap)", 1)
    mutations["update_helper_substitution"] = {
        "caught": not verify_regmap_transaction_ast(contract, helper_mutation)["complete"]}
    trace_lines = trace.splitlines()
    reordered = "\n".join(trace_lines[1:2] + trace_lines[0:1] + trace_lines[2:])
    mutations["trace_reorder"] = {
        "caught": not verify_regmap_runtime_trace(contract, reordered)["complete"]}
    count_mutation = trace.replace("count=1", "count=2", 1)
    mutations["bulk_count"] = {
        "caught": not verify_regmap_runtime_trace(contract, count_mutation)["complete"]}
    return {
        "schema": 1,
        "oracle": "regmap-transaction-mutation-v1",
        "mutations": mutations,
        "mutations_caught": sum(item["caught"] for item in mutations.values()),
        "complete": all(item["caught"] for item in mutations.values()),
    }
