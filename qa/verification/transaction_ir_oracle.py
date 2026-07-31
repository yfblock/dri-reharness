#!/usr/bin/env python3
"""Independent source-to-transaction IR shape oracle.

This verifier intentionally does not import ``extractor.transactions``.  It
reconstructs the public regmap and I2C call contracts from source text and
compares transport, operation kind, endpoint, payload shape and order with
Formal RIS.  MFD helper provenance remains outside this oracle's scope until
an independent header-AST verifier is added; readiness therefore stays
fail-closed for every transaction domain.
"""
from __future__ import annotations

import copy
from pathlib import Path
import re

from extractor.formal import parse_expr, simplify_expr, walk_leaf_ops


_KNOWN = {
    "regmap_read": ("TransactionRead", "regmap", "scalar"),
    "regmap_write": ("TransactionWrite", "regmap", "scalar"),
    "regmap_update_bits": ("TransactionUpdate", "regmap", "scalar"),
    "regmap_update_bits_check": (
        "TransactionUpdate", "regmap", "update_check"),
    "regmap_set_bits": ("TransactionUpdate", "regmap", "set_bits"),
    "regmap_clear_bits": ("TransactionUpdate", "regmap", "clear_bits"),
    "regmap_bulk_read": ("TransactionRead", "regmap", "buffer"),
    "regmap_bulk_write": ("TransactionWrite", "regmap", "buffer"),
    "regmap_raw_read": ("TransactionRead", "regmap", "buffer_bytes"),
    "regmap_raw_write": ("TransactionWrite", "regmap", "buffer_bytes"),
    "i2c_smbus_read_byte": ("TransactionRead", "i2c_smbus", "read_byte"),
    "i2c_smbus_write_byte": ("TransactionWrite", "i2c_smbus", "write_byte"),
    "i2c_smbus_read_byte_data": (
        "TransactionRead", "i2c_smbus", "read_byte_data"),
    "i2c_smbus_write_byte_data": (
        "TransactionWrite", "i2c_smbus", "write_byte_data"),
    "i2c_smbus_read_word_data": (
        "TransactionRead", "i2c_smbus", "read_word_data"),
    "i2c_smbus_write_word_data": (
        "TransactionWrite", "i2c_smbus", "write_word_data"),
}


def _split_args(text: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            out.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    out.append("".join(current).strip())
    return out


def _function_spans(text: str) -> list[tuple[int, int, str]]:
    spans = []
    pattern = re.compile(
        r"(?m)^\s*(?:static\s+)?(?:[A-Za-z_]\w*\s+)+"
        r"(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{")
    for match in pattern.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            spans.append((match.start(), index, match.group("name")))
    return spans


def _source_calls(source: str) -> list[dict]:
    text = Path(source).read_text(encoding="utf-8")
    spans = _function_spans(text)
    names = "|".join(sorted(map(re.escape, _KNOWN), key=len, reverse=True))
    calls = []
    for match in re.finditer(rf"\b(?P<name>{names})\s*\(", text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
            index += 1
        if depth:
            continue
        calls.append({
            "name": match.group("name"),
            "offset": match.start(),
            "args": _split_args(text[match.end():index - 1]),
            "function": next((name for start, end, name in spans
                              if start <= match.start() < end), ""),
        })
    return calls


def _expr(text: str | None):
    return simplify_expr(parse_expr(text)) if text is not None else None


def _expected(call: dict) -> dict | None:
    kind, transport, shape = _KNOWN[call["name"]]
    args = call["args"]
    if not args:
        return None
    selector = None
    if transport == "regmap" or shape.endswith("_data"):
        if len(args) < 2:
            return None
        selector = _expr(args[1])
    row = {"kind": kind, "transport": transport,
           "target": _expr(args[0]), "selector": selector}
    row["function"] = call.get("function", "")
    row["specialized"] = False
    if transport == "regmap":
        if kind == "TransactionRead":
            row["payload_kind"] = "Buffer" if shape.startswith("buffer") else "Scalar"
            if row["payload_kind"] == "Buffer":
                if len(args) < 4:
                    return None
                row.update({"buffer": _expr(args[2]), "count": _expr(args[3])})
        elif kind == "TransactionWrite":
            row["payload_kind"] = "Buffer" if shape.startswith("buffer") else "Scalar"
            if row["payload_kind"] == "Buffer":
                if len(args) < 4:
                    return None
                row.update({"buffer": _expr(args[2]), "count": _expr(args[3])})
            elif len(args) >= 3:
                row["value"] = _expr(args[2])
        elif len(args) >= 3:
            row["mask"] = _expr(args[2])
            row["value"] = (_expr(args[3])
                            if shape in {"scalar", "update_check"} and len(args) >= 4
                            else _expr(args[2]) if shape == "set_bits"
                            else {"Const": 0})
        return row
    row["payload_kind"] = "Scalar"
    if kind == "TransactionWrite":
        value_index = 2 if shape.endswith("_data") else 1
        if len(args) <= value_index:
            return None
        row["value"] = _expr(args[value_index])
    return row


def _observed(formal: dict) -> list[dict]:
    rows = []
    seen_sites: set[str] = set()
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            kind = next((name for name in (
                "TransactionRead", "TransactionWrite", "TransactionUpdate")
                if name in op), None)
            if kind is None:
                continue
            body = op[kind]
            callee = (body.get("evidence") or {}).get("callee")
            if callee not in _KNOWN:
                continue
            site_id = (body.get("evidence") or {}).get("site_id")
            if isinstance(site_id, str) and site_id in seen_sites:
                continue
            if isinstance(site_id, str):
                seen_sites.add(site_id)
            row = {"kind": kind, "transport": body.get("transport"),
                   "target": body.get("target"),
                   "selector": body.get("selector"),
                   "function": (body.get("evidence") or {}).get(
                       "function", ""),
                   "specialized": bool((body.get("evidence") or {}).get(
                       "inlined_at"))}
            if kind == "TransactionUpdate":
                row.update({"mask": body.get("mask"),
                            "value": body.get("value")})
            else:
                payload = body.get("payload") or {}
                payload_kind = "Buffer" if "Buffer" in payload else "Scalar"
                row["payload_kind"] = payload_kind
                payload_body = payload.get(payload_kind) or {}
                for key in ("value", "buffer", "count"):
                    if key in payload_body:
                        row[key] = payload_body[key]
            row["source_offset"] = (body.get("evidence") or {}).get("offset")
            rows.append(row)
    return rows


def verify_transaction_source(formal: dict, source: str) -> dict:
    expected = [row for row in (_expected(call) for call in _source_calls(source))
                if row is not None]
    observed = _observed(formal)
    observed_core = [{key: value for key, value in row.items()
                      if key != "source_offset"} for row in observed]
    functions = {row.get("function", "") for row in expected}
    if len(functions) > 1:
        # Formal modules are function-scoped; source-file order across
        # functions is not a transaction-order claim.  Preserve and compare
        # order within each function, while treating function groups as a
        # multiset of independent callback contracts.
        expected_groups = {}
        observed_groups = {}
        for row in expected:
            expected_groups.setdefault(row.get("function", ""), []).append(row)
        for row in observed_core:
            observed_groups.setdefault(row.get("function", ""), []).append(row)
        expected = [row for key in sorted(expected_groups)
                    for row in expected_groups[key]]
        observed_core = [row for key in sorted(observed_groups)
                         for row in observed_groups[key]]
    mismatches = []
    for index in range(max(len(expected), len(observed_core))):
        want = expected[index] if index < len(expected) else None
        got = observed_core[index] if index < len(observed_core) else None
        if got and got.get("specialized"):
            # Inlined helper arguments are intentionally instantiated at the
            # callsite (e.g. `enable` becomes `true`).  This oracle checks the
            # transport/endpoint/payload shape for that view; direct source
            # rows remain value-checked.
            got = {key: value for key, value in got.items()
                   if key not in {"value", "mask", "specialized"}}
            want = {key: value for key, value in (want or {}).items()
                    if key not in {"value", "mask", "specialized"}}
        if want != got:
            mismatches.append({"index": index, "expected": want, "observed": got})
    return {
        "schema": 1,
        "oracle": "source-transaction-shape-v1",
        "complete": not mismatches,
        "expected_transactions": len(expected),
        "observed_transactions": len(observed_core),
        "mismatches": mismatches,
        "scope": ["regmap", "i2c_smbus_scalar"],
    }


def mutation_suite(formal: dict, source: str) -> dict:
    baseline = verify_transaction_source(formal, source)
    mutations = {}
    mutators = {
        "transport": lambda body: body.__setitem__("transport", "mmio"),
        "selector": lambda body: body.__setitem__("selector", {"Const": 0xDEAD}),
        "kind": None,
        "order": None,
    }
    transaction_locations = []
    for module in formal.get("modules", []):
        for index, op in enumerate(module.get("ops", [])):
            kind = next((name for name in (
                "TransactionRead", "TransactionWrite", "TransactionUpdate")
                if name in op), None)
            if kind:
                transaction_locations.append((module, index, kind))
    for name, mutate in mutators.items():
        changed = copy.deepcopy(formal)
        locations = []
        for module in changed.get("modules", []):
            for index, op in enumerate(module.get("ops", [])):
                kind = next((item for item in (
                    "TransactionRead", "TransactionWrite", "TransactionUpdate")
                    if item in op), None)
                if kind:
                    locations.append((module, index, kind))
        if not locations:
            mutations[name] = False
            continue
        module, index, kind = locations[0]
        if name == "kind":
            body = module["ops"][index].pop(kind)
            replacement = ("TransactionWrite" if kind != "TransactionWrite"
                           else "TransactionRead")
            module["ops"][index][replacement] = body
        elif name == "order" and len(locations) >= 2:
            first_module, first_index, _ = locations[0]
            second_module, second_index, _ = locations[1]
            if first_module is second_module:
                first_module["ops"][first_index], first_module["ops"][second_index] = (
                    first_module["ops"][second_index], first_module["ops"][first_index])
            else:
                first_module["ops"][first_index], second_module["ops"][second_index] = (
                    second_module["ops"][second_index], first_module["ops"][first_index])
        else:
            mutate(module["ops"][index][kind])
        mutations[name] = not verify_transaction_source(changed, source)["complete"]
    return {"baseline_complete": baseline["complete"],
            "mutations_detected": mutations,
            "complete": baseline["complete"] and all(mutations.values())}
