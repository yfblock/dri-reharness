#!/usr/bin/env python3
"""Account for every register RIS operation in generated backend C.

This is intentionally a first-stage lowering proof: it detects silent drops,
duplicates, unknown operations, rejected operations and semantic-contract
digest drift.  A later AST verifier must additionally prove that the C
statement following each receipt implements the recorded semantics.
"""
from __future__ import annotations

from collections import Counter
import re

from extractor.formal import walk_leaf_ops
from generator.common import ris_op_digest


_RECEIPT = re.compile(
    r"/\*\s*REHARNESS_RIS_OP\s+"
    r"id=(?P<id>\S+)\s+kind=(?P<kind>\S+)\s+"
    r"status=(?P<status>\S+)\s+digest=(?P<digest>[0-9a-f]{16})\s*\*/")


def build_generation_contract(formal: dict) -> dict:
    operations = []
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            kind = next((name for name in
                         ("Read", "Write", "ReadModifyWrite")
                         if name in op), None)
            if kind is None:
                continue
            body = op[kind]
            digest = ris_op_digest(op)
            # Normalization rewrites backend-private expressions on deep
            # copies.  Carry the canonical digest through those rewrites so a
            # receipt always names the pre-normalization Formal RIS contract.
            body["contract_digest"] = digest
            operations.append({
                "op_id": body.get("op_id"),
                "module": module.get("name"),
                "kind": kind,
                "digest": digest,
                "width": body.get("width"),
                "reliability": body.get("reliability"),
                "access_domain": body.get("access_domain"),
                "evidence": body.get("evidence", {}),
            })
    return {
        "schema": 1,
        "driver": formal.get("driver"),
        "claim_scope": formal.get("metadata", {}).get("assurance_scope", {}),
        "policy": {
            "required_disposition": "lowered",
            "cardinality": "exactly-once",
            "unknown_operations_allowed": False,
            "semantic_authority": "canonical-formal-ris",
        },
        "register_operations": operations,
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
    complete = not any((duplicate_expected, missing, duplicate, unknown,
                        rejected, digest_mismatch, kind_mismatch))
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
    }
