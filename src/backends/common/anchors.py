"""Receipt-bound compound statements owned by unique operation labels."""
from __future__ import annotations

import re

from .receipts import lowering_receipt


def operation_anchor(op: dict, seen: set[str]) -> str:
    """Return the source-level label that owns one register lowering.

    Formal RIS assigns C-identifier-safe, globally unique ``op_<n>`` IDs.  Do
    not silently sanitize malformed IDs here: an altered label would sever the
    exact operation-to-C relation that the anchor is intended to expose to
    independent AST and mutation oracles.
    """
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), None)
    body = op.get(kind, {}) if kind else {}
    op_id = body.get("op_id")
    if not isinstance(op_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", op_id):
        raise ValueError(f"register RIS operation has invalid op_id: {op_id!r}")
    if op_id in seen:
        raise ValueError(f"duplicate register RIS operation id: {op_id}")
    seen.add(op_id)
    return f"__rh_op_{op_id}"


def begin_operation(out: list[str], pad: str, op: dict,
                     disposition: str, seen: set[str]) -> None:
    """Start a receipt-bound compound statement owned by a unique label."""
    out.append(f"{pad}{lowering_receipt(op, disposition)}")
    out.append(f"{pad}{operation_anchor(op, seen)}: {{")
