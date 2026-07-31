#!/usr/bin/env python3
"""Independent AST-shape oracle for lowered typed transactions.

The oracle intentionally does not import backend generators.  It only accepts
the frozen transaction contract plus generated C and checks that each
``__rh_txn_<id>`` compound statement owns exactly one expected transport
helper.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


_ANCHOR = re.compile(r"__rh_txn_(?P<id>[A-Za-z0-9_]+)\s*:\s*\{(?P<body>.*?)\n\s*\}", re.S)
_CALL = re.compile(
    r"\b(?P<name>(?:reharness_(?:regmap|i2c_smbus|i2c_master)_[A-Za-z0-9_]+|"
    r"reharness_mfd_(?:read|write|update)|"
    r"[A-Za-z_]\w*_(?:reg_read|reg_write|set_bits|clear_bits)))\s*\(")


def _rows(document: dict) -> list[dict]:
    rows = document.get("transaction_operations")
    if not isinstance(rows, list):
        raise ValueError("contract has no transaction_operations list")
    return rows


def _expected(row: dict, backend: str | None = None) -> tuple[str, str] | None:
    transport = row.get("transport")
    if transport not in {"regmap", "i2c_smbus", "i2c", "mfd"}:
        return None
    kind = row.get("kind")
    contract = row.get("contract") or {}
    if transport == "regmap" and kind == "TransactionRead":
        payload = contract.get("payload") or {}
        return ("reharness_regmap_bulk_read" if "Buffer" in payload
                else "reharness_regmap_read", kind)
    if transport == "regmap" and kind == "TransactionWrite":
        payload = contract.get("payload") or {}
        return ("reharness_regmap_bulk_write" if "Buffer" in payload
                else "reharness_regmap_write", kind)
    if transport == "regmap" and kind == "TransactionUpdate":
        return ("reharness_regmap_update", kind)
    if transport == "mfd":
        if backend in {"harness", "baremetal"}:
            helper = {
                "TransactionRead": "reharness_mfd_read",
                "TransactionWrite": "reharness_mfd_write",
                "TransactionUpdate": "reharness_mfd_update",
            }.get(kind)
            return (helper, kind) if helper else None
        helper = contract.get("helper_symbol")
        return (helper, kind) if isinstance(helper, str) else None
    protocol = contract.get("protocol") or "smbus_byte_data"
    if protocol == "raw":
        helper = "reharness_i2c_master_recv" if kind == "TransactionRead" else "reharness_i2c_master_send"
    elif "Buffer" in (contract.get("payload") or {}):
        suffix = "i2c_block" if protocol == "i2c_block" else "block_data"
        helper = f"reharness_i2c_smbus_{'read' if kind == 'TransactionRead' else 'write'}_{suffix}"
    else:
        helper = f"reharness_i2c_smbus_{'read' if kind == 'TransactionRead' else 'write'}_{protocol.removeprefix('smbus_')}"
    return (helper, kind)


def verify_regmap_transaction_ast(
        contract: dict, generated: str | Path,
        backend: str | None = None) -> dict[str, Any]:
    source = (generated.read_text(encoding="utf-8") if isinstance(generated, Path)
              else generated)
    rows = _rows(contract)
    expected = {row.get("op_id"): row for row in rows
                if isinstance(row.get("op_id"), str)}
    anchors = {}
    malformed = []
    for match in _ANCHOR.finditer(source):
        op_id = match.group("id")
        if op_id in anchors:
            malformed.append(op_id)
        anchors[op_id] = match.group("body")
    missing = sorted(op_id for op_id in expected if op_id not in anchors)
    unknown = sorted(op_id for op_id in anchors if op_id not in expected)
    mismatches = []
    unsupported = []
    for op_id, row in expected.items():
        shape = _expected(row, backend)
        if shape is None:
            unsupported.append(op_id)
            continue
        body = anchors.get(op_id)
        if body is None:
            continue
        calls = [item.group("name") for item in _CALL.finditer(body)]
        if calls != [shape[0]]:
            mismatches.append({"op_id": op_id, "expected": [shape[0]],
                               "actual": calls})
    complete = not any((missing, unknown, malformed, mismatches, unsupported))
    return {
        "schema": 1,
        "oracle": "transaction-ast-v1",
        "complete": complete,
        "required_transactions": len(expected),
        "anchors": len(anchors),
        "missing_anchors": missing,
        "unknown_anchors": unknown,
        "malformed_anchors": sorted(set(malformed)),
        "primitive_mismatches": mismatches,
        "unsupported_transactions": unsupported,
    }


def verify_regmap_runtime_trace(contract: dict, trace: str) -> dict[str, Any]:
    """Check ordered transaction kind/count markers emitted by H/B runners."""
    rows = [row for row in _rows(contract)
            if row.get("transport") in {"regmap", "i2c_smbus", "i2c", "mfd"}]
    lines = []
    pattern = re.compile(
        r"^(?:\[txn\s+(?P<seq>\d+)\]|\[reharness-txn\])\s+"
        r"id=(?P<id>[A-Za-z0-9_]+)\s+"
        r"(?P<kind>R|W|U|BR|BW)\s+"
        r"transport=(?P<transport>\S+)\s+selector=0x[0-9a-f]+\s+"
        r"count=(?P<count>\d+)\s+value=0x[0-9a-f]+$")
    parse_errors = []
    for line in trace.splitlines():
        match = pattern.match(line.strip())
        if match:
            lines.append(match.groupdict())
        elif line.startswith(("[txn ", "[reharness-txn]")):
            parse_errors.append(line)
    expected_kinds = []
    expected_transports = []
    expected_counts: list[str | None] = []
    for row in rows:
        contract_row = row.get("contract") or {}
        kind = row.get("kind")
        payload = contract_row.get("payload") or {}
        buffered = "Buffer" in payload
        expected_kinds.append({"TransactionRead": "BR" if buffered else "R",
                               "TransactionWrite": "BW" if buffered else "W",
                               "TransactionUpdate": "U"}[kind])
        expected_transports.append(row.get("transport"))
        if buffered:
            count_expr = payload.get("Buffer", {}).get("count", {})
            expected_counts.append(
                str(count_expr["Const"]) if isinstance(count_expr, dict)
                and "Const" in count_expr else None)
        else:
            expected_counts.append("1")
    actual_kinds = [item["kind"] for item in lines]
    actual_ids = [item["id"] for item in lines]
    expected_ids = [row.get("op_id") for row in rows]
    actual_counts = [item["count"] for item in lines]
    actual_transports = [item["transport"] for item in lines]
    count_ok = len(actual_counts) == len(expected_counts) and all(
        expected is None or expected == actual
        for expected, actual in zip(expected_counts, actual_counts))
    complete = (not parse_errors and actual_ids == expected_ids
                and actual_kinds == expected_kinds
                and actual_transports == expected_transports and count_ok)
    return {
        "schema": 1,
        "oracle": "transaction-trace-v1",
        "complete": complete,
        "expected_kinds": expected_kinds,
        "expected_ids": expected_ids,
        "actual_ids": actual_ids,
        "actual_kinds": actual_kinds,
        "expected_transports": expected_transports,
        "actual_transports": actual_transports,
        "expected_counts": expected_counts,
        "actual_counts": actual_counts,
        "parse_errors": parse_errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--generated")
    parser.add_argument("--trace")
    args = parser.parse_args(argv)
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    report = {}
    if args.generated:
        report["ast"] = verify_regmap_transaction_ast(contract, Path(args.generated))
    if args.trace:
        report["trace"] = verify_regmap_runtime_trace(
            contract, Path(args.trace).read_text(encoding="utf-8"))
    report["complete"] = bool(report) and all(item["complete"] for item in report.values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
