#!/usr/bin/env python3
"""Verify register-operation anchors in self-contained generated C.

The lowering-receipt oracle proves that a backend *claims* to have lowered
every Formal RIS operation.  This oracle takes the next, deliberately narrow,
step: libclang must see one ``__rh_op_<op_id>`` LabelStmt per expected
operation and the label's direct CompoundStmt must contain exactly the MMIO
primitive shape required by the generation contract.

For Linux, callers must additionally provide provenance for arguments derived
from the exact generated module Kbuild ``.o.cmd``.  The oracle records that
context so a downstream verifier can bind this leaf proof to an independent
registration proof over the same translation unit.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from repo_paths import REPO_ROOT as ROOT
sys.path.insert(0, str(ROOT))

from verification.backend_lowering_oracle import build_generation_contract


ANCHOR_PREFIX = "__rh_op_"
WIDTH_BITS = {"B1": 8, "B2": 16, "B4": 32, "B8": 64}
_SIMPLE_PRIMITIVES = {
    "readb": ("Read", 8, "native", "normal"),
    "readw": ("Read", 16, "native", "normal"),
    "readl": ("Read", 32, "native", "normal"),
    "readq": ("Read", 64, "native", "normal"),
    "writeb": ("Write", 8, "native", "normal"),
    "writew": ("Write", 16, "native", "normal"),
    "writel": ("Write", 32, "native", "normal"),
    "writeq": ("Write", 64, "native", "normal"),
}


def _primitive_shape(name: str) -> dict[str, Any] | None:
    """Return the semantic shape of a known leaf MMIO primitive.

    The generated self-contained backends lower source/kernel names through
    macros, so libclang normally reports ``harness_*`` or ``mmio_*``.  The
    kernel spellings are retained for small standalone fixtures and later
    Linux-front-end reuse.  Unknown calls are never guessed from a loose
    substring match.
    """
    if name in _SIMPLE_PRIMITIVES:
        kind, width, byte_order, write_semantics = _SIMPLE_PRIMITIVES[name]
        return {
            "callee": name,
            "kind": kind,
            "width_bits": width,
            "byte_order": byte_order,
            "write_semantics": write_semantics,
        }

    match = re.fullmatch(
        r"(?P<family>harness|mmio)_(?P<kind>read|write)"
        r"(?P<w1c>_w1c)?(?P<bits>8|16|32|64)(?P<be>be)?",
        name,
    )
    if match:
        return {
            "callee": name,
            "kind": "Read" if match.group("kind") == "read" else "Write",
            "width_bits": int(match.group("bits")),
            "byte_order": "big" if match.group("be") else "native",
            "write_semantics": "w1c" if match.group("w1c") else "normal",
        }

    match = re.fullmatch(
        r"io(?P<kind>read|write)(?P<bits>8|16|32|64)(?P<be>be)?",
        name,
    )
    if match:
        return {
            "callee": name,
            "kind": "Read" if match.group("kind") == "read" else "Write",
            "width_bits": int(match.group("bits")),
            "byte_order": "big" if match.group("be") else "native",
            "write_semantics": "normal",
        }

    match = re.fullmatch(
        r"(?P<kind>read|write)(?P<letter>b|w|l|q)_relaxed", name)
    if match:
        bits = {"b": 8, "w": 16, "l": 32, "q": 64}[match.group("letter")]
        return {
            "callee": name,
            "kind": "Read" if match.group("kind") == "read" else "Write",
            "width_bits": bits,
            "byte_order": "native",
            "write_semantics": "normal",
        }
    return None


def _discover_libclang(explicit: str | None = None) -> str:
    candidates: list[Path] = []
    for value in (explicit, os.environ.get("LIBCLANG_PATH")):
        if not value:
            continue
        path = Path(value)
        if path.is_dir():
            candidates.extend(path.glob("libclang.so*"))
        else:
            candidates.append(path)
    candidates.extend(Path("/usr/lib").glob("llvm-*/lib/libclang.so*"))
    candidates.extend(Path("/usr/local/lib").glob("libclang.so*"))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise RuntimeError(
            "libclang was not found; set LIBCLANG_PATH or --clang-library")

    def version_key(path: Path) -> tuple[int, str]:
        match = re.search(r"llvm-(\d+)", str(path))
        return (int(match.group(1)) if match else -1, str(path))

    return str(max(existing, key=version_key))


def _load_clang(explicit: str | None = None):
    try:
        from clang import cindex
    except ImportError as exc:  # pragma: no cover - environment failure path
        raise RuntimeError("Python clang bindings are not installed") from exc
    if not cindex.Config.loaded:
        cindex.Config.set_library_file(_discover_libclang(explicit))
    return cindex


def _source_location(cursor, source: Path) -> dict[str, Any]:
    location = cursor.location
    return {
        "file": str(location.file) if location.file else None,
        "line": location.line,
        "column": location.column,
        "offset": location.offset,
    }


def _is_in_source(cursor, source: Path) -> bool:
    if not cursor.location.file:
        return False
    try:
        return Path(str(cursor.location.file)).resolve() == source
    except OSError:
        return False


def _contract_rows(document: dict) -> tuple[dict, list[dict]]:
    contract = (document if "register_operations" in document
                else build_generation_contract(document))
    rows = contract.get("register_operations")
    if not isinstance(rows, list):
        raise ValueError("generation contract has no register_operations list")
    return contract, rows


def _expected_shape(row: dict) -> list[dict[str, Any]]:
    kind = row.get("kind")
    width = WIDTH_BITS.get(row.get("width"))
    evidence = row.get("evidence") or {}
    byte_order = evidence.get("byte_order", "native")
    write_semantics = evidence.get("write_semantics", "normal")
    base = {
        "width_bits": width,
        "byte_order": byte_order,
        "write_semantics": write_semantics,
    }
    if kind == "Read":
        return [{**base, "kind": "Read", "write_semantics": "normal"}]
    if kind == "Write":
        return [{**base, "kind": "Write"}]
    recipe = row.get("lowering_recipe") or {}
    if kind == "ReadModifyWrite" and recipe.get("kind") == "write_from_read":
        return [{**base, "kind": "Write"}]
    if kind == "ReadModifyWrite":
        return [
            {**base, "kind": "Read", "write_semantics": "normal"},
            {**base, "kind": "Write"},
        ]
    return []


def _shape_core(shape: dict) -> dict:
    return {key: shape.get(key) for key in
            ("kind", "width_bits", "byte_order", "write_semantics")}


def _primitive_family(name: str) -> str | None:
    match = re.match(r"^(harness|mmio)_", name)
    return match.group(1) if match else None


def _is_w1c_delegation(call: dict, function_calls: list[dict]) -> bool:
    """Recognize the one canonical self-contained W1C wrapper delegation.

    Bare-metal's non-oracle ``mmio_write_w1cN`` implementation delegates once
    to ``mmio_writeN``.  Treating every call in every primitive-named function
    as trusted would create an easy hiding place for extra hardware accesses,
    so this exemption is intentionally exact and cardinality checked.
    """
    function = call.get("function") or ""
    owner = _primitive_shape(function)
    callee = _shape_core(call)
    if not owner or len(function_calls) != 1:
        return False
    return (
        owner["kind"] == "Write"
        and owner["write_semantics"] == "w1c"
        and callee["kind"] == "Write"
        and callee["write_semantics"] == "normal"
        and owner["width_bits"] == callee["width_bits"]
        and owner["byte_order"] == callee["byte_order"]
        and _primitive_family(function) is not None
        and _primitive_family(function) == _primitive_family(call["callee"])
    )


def _extract_ast(source: Path, clang_args: list[str], clang_library: str | None):
    cindex = _load_clang(clang_library)
    index = cindex.Index.create()
    translation_unit = index.parse(
        str(source), args=["-std=gnu11", "-Wno-everything", *clang_args])
    diagnostics = [{
        "severity": diagnostic.severity,
        "spelling": diagnostic.spelling,
        "location": {
            "file": (str(diagnostic.location.file)
                     if diagnostic.location.file else None),
            "line": diagnostic.location.line,
            "column": diagnostic.location.column,
        },
    } for diagnostic in translation_unit.diagnostics]

    anchors: list[dict[str, Any]] = []
    primitive_calls: list[dict[str, Any]] = []

    def visit(cursor, function: str | None = None,
              active_anchor: dict[str, Any] | None = None) -> None:
        if cursor.kind == cindex.CursorKind.FUNCTION_DECL:
            function = cursor.spelling

        if cursor.kind == cindex.CursorKind.LABEL_STMT:
            spelling = cursor.spelling
            if spelling.startswith(ANCHOR_PREFIX):
                children = list(cursor.get_children())
                direct_compound = (
                    len(children) == 1
                    and children[0].kind == cindex.CursorKind.COMPOUND_STMT)
                anchor = {
                    "label": spelling,
                    "op_id": spelling[len(ANCHOR_PREFIX):],
                    "direct_compound": direct_compound,
                    "location": _source_location(cursor, source),
                    "function": function,
                    "primitives": [],
                }
                anchors.append(anchor)
                for child in children:
                    visit(child, function, anchor)
                return

        if cursor.kind == cindex.CursorKind.CALL_EXPR:
            shape = _primitive_shape(cursor.spelling)
            if shape:
                call = {
                    **shape,
                    "location": _source_location(cursor, source),
                    "function": function,
                    "anchor": active_anchor["op_id"] if active_anchor else None,
                }
                primitive_calls.append(call)
                if active_anchor is not None:
                    active_anchor["primitives"].append(call)

        for child in cursor.get_children():
            visit(child, function, active_anchor)

    for top_level in translation_unit.cursor.get_children():
        if _is_in_source(top_level, source):
            visit(top_level)
    return diagnostics, anchors, primitive_calls


def verify_generated_c_ast(
        contract_or_formal: dict, generated: str | Path, *,
        clang_args: list[str] | None = None,
        clang_library: str | None = None,
        required_op_ids: set[str] | None = None,
        compile_context: dict[str, Any] | None = None) -> dict:
    """Return a fail-closed JSON-serializable structural verification report."""
    source = Path(generated).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"generated C does not exist: {source}")
    contract, rows = _contract_rows(contract_or_formal)
    expected_counts = Counter(row.get("op_id") for row in rows)
    duplicate_expected_ids = sorted(
        str(op_id) for op_id, count in expected_counts.items()
        if not op_id or count != 1)
    expected = {row["op_id"]: row for row in rows if row.get("op_id")}
    required_ids = (set(expected) if required_op_ids is None
                    else set(required_op_ids))
    unknown_required_ids = sorted(required_ids - set(expected))

    diagnostics, anchors, primitive_calls = _extract_ast(
        source, clang_args or [], clang_library)
    parse_errors = [item for item in diagnostics if item["severity"] >= 3]
    anchor_counts = Counter(anchor["op_id"] for anchor in anchors)
    missing_anchors = sorted(
        op_id for op_id in required_ids if anchor_counts[op_id] == 0)
    nonrequired_missing_anchors = sorted(
        op_id for op_id in expected
        if op_id not in required_ids and anchor_counts[op_id] == 0)
    duplicate_anchors = sorted(
        op_id for op_id, count in anchor_counts.items()
        if op_id in expected and count != 1)
    unknown_anchors = sorted(
        op_id for op_id in anchor_counts if op_id not in expected)
    malformed_anchors = sorted({
        anchor["op_id"] for anchor in anchors
        if not anchor["direct_compound"]
    })

    anchor_by_id = {
        anchor["op_id"]: anchor for anchor in anchors
        if anchor_counts[anchor["op_id"]] == 1
    }
    operation_checks = []
    primitive_mismatches = []
    unsupported_expected_ops = []
    for op_id, row in expected.items():
        anchor = anchor_by_id.get(op_id)
        expected_shape = _expected_shape(row)
        observed = ([_shape_core(item) for item in anchor["primitives"]]
                    if anchor else [])
        supported_contract = (
            row.get("kind") in ("Read", "Write", "ReadModifyWrite")
            and row.get("width") in WIDTH_BITS
            and row.get("reliability") != "Unsupported")
        required = op_id in required_ids
        matches = bool(anchor and anchor["direct_compound"]
                       and supported_contract
                       and observed == expected_shape)
        check = {
            "op_id": op_id,
            "kind": row.get("kind"),
            "required": required,
            "expected": expected_shape,
            "observed": observed,
            "matches": matches,
        }
        operation_checks.append(check)
        if required and not supported_contract:
            unsupported_expected_ops.append(op_id)
        elif required and anchor and not matches:
            primitive_mismatches.append(check)

    unanchored = [item for item in primitive_calls if item["anchor"] is None]
    calls_by_function: dict[str, list[dict]] = {}
    for item in unanchored:
        calls_by_function.setdefault(item.get("function") or "", []).append(item)
    trusted_primitive_delegations = [
        item for item in unanchored
        if _is_w1c_delegation(
            item, calls_by_function[item.get("function") or ""])
    ]
    trusted_ids = {id(item) for item in trusted_primitive_delegations}
    unanchored_primitives = [
        item for item in unanchored if id(item) not in trusted_ids
    ]

    complete = not any((
        duplicate_expected_ids,
        unknown_required_ids,
        parse_errors,
        missing_anchors,
        duplicate_anchors,
        unknown_anchors,
        malformed_anchors,
        primitive_mismatches,
        unsupported_expected_ops,
        unanchored_primitives,
    ))
    return {
        "schema": 1,
        "oracle": "generated-c-ast-leaf-v1",
        "claim_scope": {
            "backend_scope": ["harness", "baremetal", "linux"],
            "linux_context_requirement": (
                "caller must supply arguments sanitized from the exact "
                "generated module Kbuild .o.cmd"),
            "proves": [
                "unique_ast_anchor",
                "primitive_cardinality",
                "primitive_kind",
                "primitive_width",
                "primitive_byte_order",
                "primitive_write_semantics",
                "no_unanchored_known_primitives_except_exact_w1c_delegation",
            ],
            "does_not_prove": [
                "address_expression",
                "value_or_rmw_transform",
                "guard_or_path_semantics",
                "cross_operation_ordering",
                "call_semantics",
            ],
        },
        "complete": complete,
        "driver": contract.get("driver"),
        "generated": str(source),
        "generated_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "compile_context": compile_context,
        "required_ops": len(rows),
        "required_ast_ops": len(required_ids),
        "required_op_ids": sorted(required_ids),
        "unknown_required_ids": unknown_required_ids,
        "contract_ops": len(rows),
        "anchors": len(anchors),
        "known_primitive_calls": len(primitive_calls),
        "duplicate_expected_ids": duplicate_expected_ids,
        "parse_errors": parse_errors,
        "diagnostics": diagnostics,
        "missing_anchors": missing_anchors,
        "nonrequired_missing_anchors": nonrequired_missing_anchors,
        "duplicate_anchors": duplicate_anchors,
        "unknown_anchors": unknown_anchors,
        "malformed_anchors": malformed_anchors,
        "unsupported_expected_ops": sorted(unsupported_expected_ops),
        "primitive_mismatches": primitive_mismatches,
        "trusted_primitive_delegations": trusted_primitive_delegations,
        "unanchored_primitives": unanchored_primitives,
        "operation_checks": operation_checks,
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
        description="Verify generated-C LabelStmt anchors and MMIO leaves")
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--formal", help="canonical Formal RIS JSON")
    authority.add_argument("--contract", help="frozen generation contract JSON")
    parser.add_argument("--generated", required=True,
                        help="self-contained generated C")
    parser.add_argument("--clang-arg", action="append", default=[],
                        help="extra libclang parse argument (repeatable)")
    parser.add_argument("--clang-library",
                        help="path to libclang shared library")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)

    authority_path = Path(args.formal or args.contract)
    try:
        document = json.loads(authority_path.read_text(encoding="utf-8"))
        report = verify_generated_c_ast(
            document, args.generated, clang_args=args.clang_arg,
            clang_library=args.clang_library)
    except Exception as exc:
        report = {
            "schema": 1,
            "oracle": "generated-c-ast-leaf-v1",
            "complete": False,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
            "authority": str(authority_path),
            "generated": str(Path(args.generated)),
        }
        _write_report(report, args.output)
        return 3
    _write_report(report, args.output)
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
