#!/usr/bin/env python3
"""Build and verify a fail-closed backend lowering plan from Formal RIS.

This verifier is deliberately independent of backend generators and lowering
receipts.  It classifies every Formal register operation for the harness and
bare-metal backends using only the enclosing Formal control structure:

* operations outside unsupported loops are planned as ``lowered``;
* operations in loop regions the backends cannot lower exactly are planned as
  ``blocked_unsupported_loop``.

The plan is then checked against a frozen generation contract with exactly-once
accounting.  A blocked entry is accounted for, but never counts as successfully
lowered and never authorizes a receipt or AST anchor.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
from typing import Any


SUPPORTED_BACKENDS = {"harness", "baremetal"}
REGISTER_KINDS = ("Read", "Write", "ReadModifyWrite")
DISPOSITIONS = {"lowered", "blocked_unsupported_loop"}


def _register_kind(op: dict) -> str | None:
    return next((kind for kind in REGISTER_KINDS if kind in op), None)


def _loop_lowering_mode(loop: dict) -> str | None:
    """Return the exact lowering mode independently mirrored from policy."""
    if (loop.get("reliability") == "Exact"
            and loop.get("bounded")
            and loop.get("loop_kind") == "for"):
        return "bounded_for"
    if (loop.get("reliability") == "Exact"
            and loop.get("proof_kind") == "masked_w1c_drain"):
        return "masked_w1c_drain"
    return None


def _loop_context(loop: dict, depth: int, region: str) -> dict[str, Any]:
    mode = _loop_lowering_mode(loop)
    # A bounded-for backend lowers its body, but has no independent guard_ops
    # lowering.  Masked W1C drain loops lower both guard_ops and body.
    region_lowerable = bool(
        mode == "masked_w1c_drain"
        or (mode == "bounded_for" and region == "body"))
    return {
        "depth": depth,
        "region": region,
        "loop_kind": loop.get("loop_kind", "loop"),
        "reliability": loop.get("reliability"),
        "bounded": bool(loop.get("bounded")),
        "dynamic_bound": bool(loop.get("dynamic_bound")),
        "proof_kind": loop.get("proof_kind"),
        "lowering_mode": mode,
        "region_lowerable": region_lowerable,
        "guard": copy.deepcopy(loop.get("guard")),
        "count": copy.deepcopy(loop.get("count")),
        "init": loop.get("init"),
        "step": loop.get("step"),
    }


def _blocked_reason(loop: dict) -> str:
    if (loop.get("lowering_mode") == "bounded_for"
            and loop.get("region") == "guard_ops"):
        return ("bounded for-loop guard_ops are not lowered by the "
                "harness/bare-metal loop policy")
    return (
        f"enclosing {loop.get('loop_kind', 'loop')} loop is not proven "
        "lowerable by the harness/bare-metal policy "
        f"(reliability={loop.get('reliability')!r}, "
        f"bounded={loop.get('bounded')!r}, "
        f"proof_kind={loop.get('proof_kind')!r})")


def _plan_module_ops(module: dict) -> list[dict]:
    entries: list[dict] = []
    module_name = module.get("name")

    def walk(ops: list, enclosing_loops: list[dict]) -> None:
        for op in ops or []:
            kind = _register_kind(op)
            if kind is not None:
                body = op.get(kind) or {}
                blockers = [loop for loop in enclosing_loops
                            if not loop.get("region_lowerable")]
                blocking_loop = copy.deepcopy(blockers[0]) if blockers else None
                entries.append({
                    "module": module_name,
                    "op_id": body.get("op_id"),
                    "kind": kind,
                    "disposition": ("blocked_unsupported_loop"
                                    if blocking_loop else "lowered"),
                    "reason": (_blocked_reason(blocking_loop)
                               if blocking_loop else None),
                    "enclosing_loops": copy.deepcopy(enclosing_loops),
                    "blocking_loop": blocking_loop,
                })
                continue
            if "Cond" in op:
                cond = op.get("Cond") or {}
                walk(cond.get("then_ops") or [], enclosing_loops)
                walk(cond.get("else_ops") or [], enclosing_loops)
            elif "Seq" in op:
                walk((op.get("Seq") or {}).get("ops") or [], enclosing_loops)
            elif "Loop" in op:
                loop = op.get("Loop") or {}
                depth = len(enclosing_loops) + 1
                guard_context = _loop_context(loop, depth, "guard_ops")
                body_context = _loop_context(loop, depth, "body")
                walk(loop.get("guard_ops") or [],
                     [*enclosing_loops, guard_context])
                walk(loop.get("body") or [],
                     [*enclosing_loops, body_context])

    walk(module.get("ops") or [], [])
    return entries


def build_backend_lowering_plan(formal: dict, backend: str) -> dict:
    """Return the canonical Formal-derived plan for one supported backend."""
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"backend lowering plan v1 does not support backend {backend!r}")
    modules = formal.get("modules")
    if not isinstance(modules, list):
        raise ValueError("Formal RIS has no modules list")
    entries = [entry for module in modules for entry in _plan_module_ops(module)]
    counts = Counter(entry["disposition"] for entry in entries)
    return {
        "schema": 1,
        "oracle": "backend-lowering-plan-v1",
        "driver": formal.get("driver"),
        "backend": backend,
        "policy": {
            "semantic_authority": "canonical-formal-ris",
            "cardinality": "exactly-once",
            "blocked_entries_authorize_receipts": False,
            "supported_backends": sorted(SUPPORTED_BACKENDS),
            "supported_loop_modes": ["bounded_for", "masked_w1c_drain"],
        },
        "entries": entries,
        "summary": {
            "planned_ops": len(entries),
            "lowered": counts["lowered"],
            "blocked_unsupported_loop": counts[
                "blocked_unsupported_loop"],
        },
    }


def _rows(document: dict, key: str) -> list[dict]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise ValueError(f"document has no {key} list")
    return rows


def _invalid_or_duplicate_ids(rows: list[dict]) -> list[str]:
    ids = [row.get("op_id") for row in rows]
    counts = Counter(ids)
    return sorted(
        "<missing>" if op_id is None else str(op_id)
        for op_id, count in counts.items()
        if not isinstance(op_id, str) or not op_id or count != 1)


def _unique_by_id(rows: list[dict]) -> dict[str, dict]:
    counts = Counter(row.get("op_id") for row in rows)
    return {
        row["op_id"]: row for row in rows
        if isinstance(row.get("op_id"), str)
        and row.get("op_id")
        and counts[row["op_id"]] == 1
    }


def _entry_shape(entry: dict) -> dict:
    return {
        key: copy.deepcopy(entry.get(key))
        for key in ("module", "op_id", "kind", "disposition", "reason",
                    "enclosing_loops", "blocking_loop")
    }


def verify_backend_lowering_plan(
        formal: dict, contract: dict, backend: str, plan: dict | None = None,
        ) -> dict:
    """Verify a candidate plan against Formal RIS and a frozen contract.

    When ``plan`` is omitted, the canonical independently-derived plan is
    verified.  Supplying a candidate is useful for mutation tests and for a
    future pipeline that serializes plans before consuming them.
    """
    canonical = build_backend_lowering_plan(formal, backend)
    candidate = copy.deepcopy(plan if plan is not None else canonical)
    contract_rows = _rows(contract, "register_operations")
    plan_rows = _rows(candidate, "entries")
    canonical_rows = canonical["entries"]

    duplicate_contract_ids = _invalid_or_duplicate_ids(contract_rows)
    duplicate_formal_ids = _invalid_or_duplicate_ids(canonical_rows)
    duplicate_plan_ids = _invalid_or_duplicate_ids(plan_rows)
    contract_by_id = _unique_by_id(contract_rows)
    formal_by_id = _unique_by_id(canonical_rows)
    plan_by_id = _unique_by_id(plan_rows)

    contract_ids = set(contract_by_id)
    formal_ids = set(formal_by_id)
    plan_ids = set(plan_by_id)
    missing_from_contract = sorted(formal_ids - contract_ids)
    unknown_contract_ops = sorted(contract_ids - formal_ids)
    missing_plan_ops = sorted(contract_ids - plan_ids)
    unknown_plan_ops = sorted(plan_ids - contract_ids)

    contract_mismatches = []
    for op_id in sorted(contract_ids & formal_ids):
        expected = formal_by_id[op_id]
        observed = contract_by_id[op_id]
        fields = {
            name: {"formal": expected.get(name), "contract": observed.get(name)}
            for name in ("module", "kind")
            if expected.get(name) != observed.get(name)
        }
        if fields:
            contract_mismatches.append({"op_id": op_id, "fields": fields})

    classification_mismatches = []
    for op_id in sorted(formal_ids & plan_ids):
        expected = _entry_shape(formal_by_id[op_id])
        observed = _entry_shape(plan_by_id[op_id])
        if expected != observed:
            classification_mismatches.append({
                "op_id": op_id,
                "expected": expected,
                "observed": observed,
            })

    malformed_plan_entries = []
    for index, entry in enumerate(plan_rows):
        disposition = entry.get("disposition")
        problems = []
        if disposition not in DISPOSITIONS:
            problems.append(f"invalid disposition {disposition!r}")
        if entry.get("kind") not in REGISTER_KINDS:
            problems.append(f"invalid register kind {entry.get('kind')!r}")
        if disposition == "blocked_unsupported_loop":
            if not entry.get("reason"):
                problems.append("blocked entry has no reason")
            if not entry.get("blocking_loop"):
                problems.append("blocked entry has no blocking_loop")
            if not entry.get("enclosing_loops"):
                problems.append("blocked entry has no enclosing_loops")
        elif disposition == "lowered" and entry.get("blocking_loop"):
            problems.append("lowered entry retains a blocking_loop")
        if problems:
            malformed_plan_entries.append({
                "index": index,
                "op_id": entry.get("op_id"),
                "problems": problems,
            })

    driver_mismatch = None
    if contract.get("driver") != formal.get("driver"):
        driver_mismatch = {
            "formal": formal.get("driver"),
            "contract": contract.get("driver"),
        }
    backend_mismatch = None
    if candidate.get("backend") != backend:
        backend_mismatch = {
            "requested": backend,
            "plan": candidate.get("backend"),
        }

    accounting_complete = not any((
        duplicate_contract_ids,
        duplicate_formal_ids,
        duplicate_plan_ids,
        missing_from_contract,
        unknown_contract_ops,
        missing_plan_ops,
        unknown_plan_ops,
        contract_mismatches,
        malformed_plan_entries,
        driver_mismatch,
        backend_mismatch,
    ))
    classification_complete = not classification_mismatches
    blocked_ids = sorted(
        entry.get("op_id") for entry in plan_rows
        if entry.get("disposition") == "blocked_unsupported_loop"
        and isinstance(entry.get("op_id"), str))
    lowering_complete = (
        accounting_complete and classification_complete and not blocked_ids)
    complete = lowering_complete
    disposition_counts = Counter(
        entry.get("disposition") for entry in plan_rows)

    return {
        "schema": 1,
        "oracle": "backend-lowering-plan-v1",
        "driver": formal.get("driver"),
        "backend": backend,
        "complete": complete,
        "accounting_complete": accounting_complete,
        "classification_complete": classification_complete,
        "lowering_complete": lowering_complete,
        "required_ops": len(contract_rows),
        "planned_ops": len(plan_rows),
        "lowered_ops": disposition_counts["lowered"],
        "blocked_ops": disposition_counts["blocked_unsupported_loop"],
        "blocked_op_ids": blocked_ids,
        "duplicate_contract_ids": duplicate_contract_ids,
        "duplicate_formal_ids": duplicate_formal_ids,
        "duplicate_plan_ids": duplicate_plan_ids,
        "missing_from_contract": missing_from_contract,
        "unknown_contract_ops": unknown_contract_ops,
        "missing_plan_ops": missing_plan_ops,
        "unknown_plan_ops": unknown_plan_ops,
        "contract_mismatches": contract_mismatches,
        "classification_mismatches": classification_mismatches,
        "malformed_plan_entries": malformed_plan_entries,
        "driver_mismatch": driver_mismatch,
        "backend_mismatch": backend_mismatch,
        "policy": copy.deepcopy(canonical["policy"]),
        "entries": plan_rows,
    }


def _write_report(report: dict, output: str | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Build and verify a fail-closed harness/bare-metal "
                     "lowering plan from Formal RIS"))
    parser.add_argument("--formal", required=True,
                        help="canonical Formal RIS JSON")
    parser.add_argument("--contract", required=True,
                        help="frozen generation-contract JSON")
    parser.add_argument("--backend", required=True,
                        choices=sorted(SUPPORTED_BACKENDS))
    parser.add_argument("--plan",
                        help="optional serialized candidate plan to verify")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)

    formal_path = Path(args.formal)
    contract_path = Path(args.contract)
    try:
        formal = json.loads(formal_path.read_text(encoding="utf-8"))
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        plan = (json.loads(Path(args.plan).read_text(encoding="utf-8"))
                if args.plan else None)
        report = verify_backend_lowering_plan(
            formal, contract, args.backend, plan)
    except Exception as exc:
        report = {
            "schema": 1,
            "oracle": "backend-lowering-plan-v1",
            "complete": False,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
            "formal": str(formal_path),
            "contract": str(contract_path),
            "backend": args.backend,
        }
        _write_report(report, args.output)
        return 3
    _write_report(report, args.output)
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
