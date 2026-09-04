"""Receipt rendering and semantic digests for register and transaction ops."""
from __future__ import annotations

import copy
import hashlib
import json
import re


def lowering_recipes(ops: list) -> dict[str, dict]:
    """Describe the physical primitives owned by each register operation."""
    recipes: dict[str, dict] = {}

    def value_vars(value: object) -> set[str]:
        if not isinstance(value, dict):
            return set()
        if "Var" in value and isinstance(value["Var"], str):
            text = value["Var"]
            names = set(re.findall(r"\b[A-Za-z_]\w*\b", text))
            return {
                name for name in names
                if not re.search(rf"\b{re.escape(name)}\s*\(", text)
            }
        names: set[str] = set()
        for child in value.values():
            names |= value_vars(child)
        return names

    def visit(items: list | None,
              producers: dict[str, tuple[str, dict]]) -> None:
        for op in items or []:
            if "Cond" in op:
                visit(op["Cond"].get("then_ops"), dict(producers))
                visit(op["Cond"].get("else_ops"), dict(producers))
                continue
            if "Loop" in op:
                local = dict(producers)
                visit(op["Loop"].get("guard_ops"), local)
                visit(op["Loop"].get("body"), local)
                continue
            if "Seq" in op:
                visit(op["Seq"].get("ops"), producers)
                continue
            if "Read" in op:
                body = op["Read"]
                op_id = body.get("op_id")
                if op_id:
                    recipes[op_id] = {
                        "kind": "read", "primitives": ["Read"]}
                    if body.get("var"):
                        producers[body["var"]] = (
                            op_id, body.get("addr", {}))
                continue
            if "Write" in op:
                body = op["Write"]
                op_id = body.get("op_id")
                if op_id:
                    producer = next((producers.get(name)
                                     for name in value_vars(body.get("value"))
                                     if producers.get(name)
                                     and producers[name][1] == body.get("addr", {})),
                                    None)
                    if producer:
                        recipes[op_id] = {
                            "kind": "write_from_read",
                            "primitives": ["Write"],
                            "read_op_id": producer[0],
                        }
                    else:
                        recipes[op_id] = {
                            "kind": "write", "primitives": ["Write"]}
                continue
            if "ReadModifyWrite" in op:
                body = op["ReadModifyWrite"]
                op_id = body.get("op_id")
                if not op_id:
                    continue
                producer = producers.get(body.get("read_var"))
                if producer and producer[1] == body.get("addr", {}):
                    recipes[op_id] = {
                        "kind": "write_from_read",
                        "primitives": ["Write"],
                        "read_op_id": producer[0],
                    }
                else:
                    recipes[op_id] = {
                        "kind": "intrinsic_rmw",
                        "primitives": ["Read", "Write"],
                    }

    visit(ops, {})
    return recipes


def ris_op_digest(op: dict) -> str:
    """Return the stable semantic digest used by lowering receipts."""
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = copy.deepcopy(op.get(kind, {}))
    for key in ("op_id", "contract_digest", "_backend_contract_digest",
                "_backend_lowering_recipe"):
        body.pop(key, None)
    evidence = body.pop("evidence", {})
    semantic = {"kind": kind, "body": body}
    lowering_evidence = {
        key: evidence[key] for key in ("byte_order", "write_semantics")
        if key in evidence
    }
    if lowering_evidence:
        semantic["lowering_evidence"] = lowering_evidence
    encoded = json.dumps(
        semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def lowering_receipt(op: dict, disposition: str = "lowered") -> str:
    """Render a machine-readable receipt for a register RIS operation."""
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = op.get(kind, {})
    digest = body.get("_backend_contract_digest") or ris_op_digest(op)
    return ("/* REHARNESS_RIS_OP "
            f"id={body.get('op_id', '?')} kind={kind} "
            f"status={disposition} digest={digest} */")


def transaction_kind(op: dict) -> str | None:
    return next((name for name in (
        "TransactionRead", "TransactionWrite", "TransactionUpdate")
        if name in op), None)


def transaction_digest(op: dict) -> str:
    """Return the stable backend-independent transaction digest."""
    kind = transaction_kind(op)
    if kind is None:
        return "0000000000000000"
    body = copy.deepcopy(op[kind])
    for key in ("op_id", "evidence", "reliability", "path_precision",
                "access_domain", "transport", "_backend_contract_digest"):
        body.pop(key, None)
    encoded = json.dumps(
        {"schema": 1, "kind": kind, "body": body},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
