#!/usr/bin/env python3
"""Account for every register RIS operation in generated backend C.

This is intentionally a first-stage lowering proof: it detects silent drops,
duplicates, unknown operations, rejected operations and semantic-contract
digest drift.  A later AST verifier must additionally prove that the C
statement following each receipt implements the recorded semantics.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from repo_paths import REPO_ROOT as ROOT
sys.path.insert(0, str(ROOT))

from extractor.formal import walk_leaf_ops
from generator.common import (lowering_recipes, ris_op_digest,
                              transaction_digest)


_RECEIPT = re.compile(
    r"/\*\s*REHARNESS_RIS_OP\s+"
    r"id=(?P<id>\S+)\s+kind=(?P<kind>\S+)\s+"
    r"status=(?P<status>\S+)\s+digest=(?P<digest>[0-9a-f]{16})\s*\*/")

_TRANSACTION_REJECTION = re.compile(
    r"/\*\s*REHARNESS_UNSUPPORTED_TRANSACTION:\s*"
    r"(?P<kind>read|write|update)\s+(?P<transport>\S+)\s+"
    r"(?P<id>[A-Za-z0-9_]+)\s*\*/")

_TRANSACTION_RECEIPT = re.compile(
    r"/\*\s*REHARNESS_TRANSACTION_OP\s+"
    r"id=(?P<id>\S+)\s+kind=(?P<kind>Transaction(?:Read|Write|Update))\s+"
    r"transport=(?P<transport>\S+)\s+status=(?P<status>\S+)\s+"
    r"digest=(?P<digest>[0-9a-f]{16})\s*\*/")

SUPPORTED_TRANSACTION_TRANSPORTS = {"regmap", "i2c_smbus", "i2c", "mfd"}


def build_generation_contract(formal: dict) -> dict:
    operations = []
    transactions = []
    for module in formal.get("modules", []):
        recipes = lowering_recipes(module.get("ops", []))
        for op in walk_leaf_ops(module.get("ops", [])):
            kind = next((name for name in
                         ("Read", "Write", "ReadModifyWrite")
                         if name in op), None)
            if kind is None:
                transaction_kind = next((name for name in (
                    "TransactionRead", "TransactionWrite",
                    "TransactionUpdate") if name in op), None)
                if transaction_kind is None:
                    continue
                body = op[transaction_kind]
                transactions.append({
                    "op_id": body.get("op_id"),
                    "module": module.get("name"),
                    "kind": transaction_kind,
                    "transport": body.get("transport"),
                    "reliability": body.get("reliability"),
                    "evidence": copy.deepcopy(body.get("evidence", {})),
                    "digest": transaction_digest({transaction_kind: body}),
                    "contract": copy.deepcopy({
                        key: value for key, value in body.items()
                        if key not in {"evidence", "reliability", "path_precision",
                                       "access_domain", "transport"}
                    }),
                })
                continue
            body = op[kind]
            digest = ris_op_digest(op)
            operations.append({
                "op_id": body.get("op_id"),
                "module": module.get("name"),
                "kind": kind,
                "digest": digest,
                "width": body.get("width"),
                "reliability": body.get("reliability"),
                "access_domain": body.get("access_domain"),
                "evidence": copy.deepcopy(body.get("evidence", {})),
                "lowering_recipe": copy.deepcopy(
                    recipes.get(body.get("op_id"), {})),
            })
    return {
        "schema": 1,
        "driver": formal.get("driver"),
        "claim_scope": copy.deepcopy(
            formal.get("metadata", {}).get("assurance_scope", {})),
        "policy": {
            "required_disposition": "lowered",
            "cardinality": "exactly-once",
            "unknown_operations_allowed": False,
            "semantic_authority": "canonical-formal-ris",
        },
        "register_operations": operations,
        "transaction_operations": transactions,
    }


def verify_backend_lowering(formal: dict, generated_c: str) -> dict:
    contract = build_generation_contract(formal)
    expected_rows = contract["register_operations"]
    expected = {row["op_id"]: row for row in expected_rows if row["op_id"]}
    expected_counts = Counter(row["op_id"] for row in expected_rows)
    receipts = [match.groupdict() for match in _RECEIPT.finditer(generated_c)]
    receipt_counts = Counter(row["id"] for row in receipts)

    duplicate_expected = sorted(
        str(op_id) for op_id, count in expected_counts.items()
        if op_id is None or count != 1)
    missing = sorted(op_id for op_id in expected if receipt_counts[op_id] == 0)
    duplicate = sorted(op_id for op_id, count in receipt_counts.items()
                       if op_id in expected and count != 1)
    unknown = sorted(op_id for op_id in receipt_counts if op_id not in expected)
    rejected = sorted(row["id"] for row in receipts
                      if row["status"] != "lowered")
    digest_mismatch = sorted(row["id"] for row in receipts
                             if row["id"] in expected
                             and row["digest"] != expected[row["id"]]["digest"])
    kind_mismatch = sorted(row["id"] for row in receipts
                           if row["id"] in expected
                           and row["kind"] != expected[row["id"]]["kind"])
    transaction_rows = contract.get("transaction_operations", [])
    expected_transactions = {
        row["op_id"]: row for row in transaction_rows if row.get("op_id")}
    transaction_markers = [match.groupdict() for match in
                           _TRANSACTION_RECEIPT.finditer(generated_c)]
    transaction_markers.extend({**match.groupdict(), "status": "rejected",
                                "digest": ""} for match in
                               _TRANSACTION_REJECTION.finditer(generated_c))
    marker_counts = Counter(row["id"] for row in transaction_markers)
    missing_transaction_markers = sorted(
        op_id for op_id in expected_transactions if marker_counts[op_id] == 0)
    duplicate_transaction_markers = sorted(
        op_id for op_id, count in marker_counts.items()
        if op_id in expected_transactions and count != 1)
    unknown_transaction_markers = sorted(
        op_id for op_id in marker_counts if op_id not in expected_transactions)
    transaction_marker_mismatch = []
    marker_kind = {
        "TransactionRead": "TransactionRead",
        "TransactionWrite": "TransactionWrite",
        "TransactionUpdate": "TransactionUpdate"}
    for marker in transaction_markers:
        expected_transaction = expected_transactions.get(marker["id"])
        if expected_transaction is None:
            continue
        if (marker["kind"] != marker_kind[expected_transaction["kind"]]
                or marker["transport"] != expected_transaction["transport"]):
            transaction_marker_mismatch.append(marker["id"])
        if marker.get("digest") and marker["digest"] != expected_transaction["digest"]:
            transaction_marker_mismatch.append(marker["id"])
        if marker.get("status") != "lowered":
            transaction_marker_mismatch.append(marker["id"])
    transaction_marker_mismatch = sorted(set(transaction_marker_mismatch))
    transaction_accounting_complete = not any((
        missing_transaction_markers, duplicate_transaction_markers,
        unknown_transaction_markers, transaction_marker_mismatch))
    unsupported_transactions = sorted(
        row["op_id"] for row in transaction_rows
        if row.get("transport") not in SUPPORTED_TRANSACTION_TRANSPORTS)
    complete = not any((duplicate_expected, missing, duplicate, unknown,
                        rejected, digest_mismatch, kind_mismatch,
                        unsupported_transactions,
                        not transaction_accounting_complete))
    return {
        "schema": 1,
        "complete": complete,
        "required_ops": len(expected_rows),
        "receipts": len(receipts),
        "missing": missing,
        "duplicate": duplicate,
        "unknown": unknown,
        "rejected": rejected,
        "digest_mismatch": digest_mismatch,
        "kind_mismatch": kind_mismatch,
        "duplicate_expected_ids": duplicate_expected,
        "required_transactions": len(transaction_rows),
        "transaction_markers": len(transaction_markers),
        "transaction_accounting_complete": transaction_accounting_complete,
        "unsupported_transactions": unsupported_transactions,
        "missing_transaction_markers": missing_transaction_markers,
        "duplicate_transaction_markers": duplicate_transaction_markers,
        "unknown_transaction_markers": unknown_transaction_markers,
        "transaction_marker_mismatch": transaction_marker_mismatch,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify exactly-once lowering receipts against Formal RIS")
    parser.add_argument("--formal", required=True,
                        help="canonical Formal RIS JSON")
    parser.add_argument("--generated", required=True,
                        help="generated C containing lowering receipts")
    parser.add_argument("--contract",
                        help="optional frozen generation-contract JSON")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)

    formal_path = Path(args.formal)
    generated_path = Path(args.generated)
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    generated_bytes = generated_path.read_bytes()
    generated_c = generated_bytes.decode("utf-8")
    rebuilt_contract = build_generation_contract(formal)
    if args.contract:
        contract_path = Path(args.contract)
        contract_bytes = contract_path.read_bytes()
        frozen = json.loads(contract_bytes.decode("utf-8"))
        frozen_core = {key: frozen.get(key) for key in rebuilt_contract}
        if frozen_core != rebuilt_contract:
            report = {
                "schema": 1,
                "complete": False,
                "verifier_error": "formal_contract_mismatch",
                "formal": str(formal_path),
                "contract": str(contract_path),
                "generated": str(generated_path),
                "contract_sha256": hashlib.sha256(
                    contract_bytes).hexdigest(),
                "generated_sha256": hashlib.sha256(
                    generated_bytes).hexdigest(),
            }
            rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
            if args.output:
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered, encoding="utf-8")
            print(rendered, end="")
            return 3
    report = verify_backend_lowering(formal, generated_c)
    report["generated_sha256"] = hashlib.sha256(generated_bytes).hexdigest()
    if args.contract:
        report["contract_sha256"] = hashlib.sha256(contract_bytes).hexdigest()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
