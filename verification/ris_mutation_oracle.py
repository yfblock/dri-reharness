#!/usr/bin/env python3
"""Mutation sensitivity checks for RIS extraction semantics."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _semantic_formal(formal: dict) -> dict:
    value = copy.deepcopy(formal)
    value.pop("metadata", None)
    for module in value.get("modules", []):
        module.pop("source", None)
        stack = list(module.get("ops", []))
        while stack:
            op = stack.pop()
            body = (op.get("Read") or op.get("Write")
                    or op.get("ReadModifyWrite"))
            if body is not None:
                for key in ("op_id", "evidence", "reliability",
                            "address_precision", "value_precision",
                            "path_precision"):
                    body.pop(key, None)
            if "Cond" in op:
                op["Cond"].pop("path_id", None)
                op["Cond"].pop("validation", None)
                op["Cond"].pop("validation_error", None)
                stack.extend(op["Cond"].get("then_ops", []))
                stack.extend(op["Cond"].get("else_ops") or [])
            elif "Loop" in op:
                op["Loop"].pop("path_id", None)
                op["Loop"].pop("validation", None)
                op["Loop"].pop("validation_error", None)
                stack.extend(op["Loop"].get("body", []))
            elif "Seq" in op:
                stack.extend(op["Seq"].get("ops", []))
    return value


def semantic_fingerprint(formal: dict) -> str:
    return json.dumps(_semantic_formal(formal), sort_keys=True,
                      separators=(",", ":"))


MUTATIONS = {
    "register_offset": (
        "#define GPIO_INT_EN\t\t0x20",
        "#define GPIO_INT_EN\t\t0x48"),
    "access_width": (
        "val = readl(g->base + GPIO_INT_EN);",
        "val = readw(g->base + GPIO_INT_EN);"),
    "rmw_operator": (
        "val &= ~BIT(irqd_to_hwirq(d));",
        "val |= BIT(irqd_to_hwirq(d));"),
    "branch_predicate": (
        "if (val == deb_div)",
        "if (val != deb_div)"),
}


def verify_ris_mutations() -> dict:
    from extractor import ExtractorConfig, extract_ris

    source = os.path.join(ROOT, "drivers", "test", "gpio-ftgpio010.c")
    text = open(source, "r", encoding="utf-8").read()
    baseline = extract_ris(ExtractorConfig(source=source))
    baseline_fingerprint = semantic_fingerprint(baseline.formal)
    results = {}
    with tempfile.TemporaryDirectory(prefix="rh_ris_mutation_") as directory:
        for name, (old, new) in MUTATIONS.items():
            if text.count(old) < 1:
                raise AssertionError(
                    f"mutation anchor {name} is missing")
            mutated_text = text.replace(old, new, 1)
            path = os.path.join(directory, "gpio-ftgpio010.c")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(mutated_text)
            mutated = extract_ris(ExtractorConfig(
                source=path, driver_name="gpio-ftgpio010"))
            changed = semantic_fingerprint(mutated.formal) != baseline_fingerprint
            results[name] = {"caught": changed}
            if not changed:
                raise AssertionError(f"RIS failed to detect mutation: {name}")
    return {
        "schema": 1,
        "baseline_ops": sum(len(module["ops"])
                            for module in baseline.formal["modules"]),
        "mutations": results,
        "mutations_caught": sum(item["caught"] for item in results.values()),
    }


if __name__ == "__main__":
    print(json.dumps(verify_ris_mutations(), indent=2, sort_keys=True))
