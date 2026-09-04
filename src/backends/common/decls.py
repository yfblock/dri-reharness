"""Local declarations and MMIO primitive selection for generated C."""
from __future__ import annotations

import re

from extractor.formal import walk_leaf_ops

from .idents import _C_KEYWORDS, is_simple_id, value_var_names, vars_in_expr
from .receipts import transaction_kind


def transaction_local_decls(ops, already_declared: set[str], indent: int = 1) -> str:
    """Declare opaque transaction handles and payload locals for generated C.

    Source transaction handles are intentionally opaque: the backend ABI takes
    ``void *`` and owns the transport model.  Existing function parameters are
    never redeclared.
    """
    ids: set[str] = set()
    buffers: set[str] = set()
    reads: set[str] = set()
    values: set[str] = set()

    def expr_ids(expr):
        return vars_in_expr(expr)

    def visit(items):
        for op in items or []:
            kind = transaction_kind(op)
            if kind:
                body = op[kind]
                target = body.get("target") or {}
                ids.update(expr_ids(target))
                values.update(expr_ids(body.get("selector")))
                if kind == "TransactionRead":
                    payload = body.get("payload") or {}
                    if "Scalar" in payload:
                        name = payload["Scalar"].get("var")
                        if isinstance(name, str):
                            reads.add(name)
                    elif "Buffer" in payload:
                        result = body.get("result")
                        if isinstance(result, str):
                            reads.add(result)
                        name = payload["Buffer"].get("buffer")
                        buffers.update(expr_ids(name))
                        values.update(expr_ids(payload["Buffer"].get("count")))
                elif kind == "TransactionWrite":
                    payload = body.get("payload") or {}
                    if "Scalar" in payload:
                        scalar_value = payload["Scalar"].get("value")
                        values.update(expr_ids(scalar_value))
                    elif "Buffer" in payload:
                        buffers.update(expr_ids(payload["Buffer"].get("buffer")))
                        values.update(expr_ids(payload["Buffer"].get("count")))
                else:
                    values.update(expr_ids(body.get("mask")))
                    values.update(expr_ids(body.get("value")))
                    changed = body.get("changed_result")
                    if isinstance(changed, str):
                        reads.add(changed)
                continue
            if "Cond" in op:
                visit(op["Cond"].get("then_ops")); visit(op["Cond"].get("else_ops"))
            elif "Loop" in op:
                visit(op["Loop"].get("guard_ops")); visit(op["Loop"].get("body"))
            elif "Seq" in op:
                visit(op["Seq"].get("ops"))
    visit(ops)
    declared = set(already_declared)
    pad = "    " * indent
    lines: list[str] = []
    for name in sorted(reads):
        if is_simple_id(name) and name not in declared:
            lines.append(f"{pad}uint32_t {name} = 0;")
            declared.add(name)
    for name in sorted(values - declared):
        if is_simple_id(name) and name not in _C_KEYWORDS \
                and not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
            lines.append(f"{pad}uint32_t {name} = 0;")
            declared.add(name)
    for name in sorted(buffers):
        if is_simple_id(name) and name not in declared:
            lines.append(f"{pad}uint32_t {name}[64] = {{0}};")
            declared.add(name)
    for name in sorted(ids - declared):
        if (not is_simple_id(name) or name in _C_KEYWORDS
                or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name)):
            continue
        lines.append(f"{pad}void *{name} = 0;")
        declared.add(name)
    return "\n".join(lines)

def local_decls(ops, already_declared: set[str], regs: dict, indent: int = 1,
                ctype: str = "uint32_t") -> str:
    """Emit declarations for read vars + value-referenced locals not already
    declared (params / read vars) and not register macros. Member-access read
    targets (e.g. `edu->revision`) are NOT declared as locals — they are
    discarded at the read site (see ops_to_c)."""
    pad = "    " * indent
    lines: list[str] = []
    declared = set(already_declared)
    read_vars = sorted({o["Read"]["var"] for o in walk_leaf_ops(ops)
                        if "Read" in o and is_simple_id(o["Read"]["var"])
                        and o["Read"]["var"] not in declared})
    read_vars += sorted({o["StateRead"]["var"] for o in walk_leaf_ops(ops)
                         if "StateRead" in o
                         and is_simple_id(o["StateRead"]["var"])
                         and o["StateRead"]["var"] not in declared
                         and o["StateRead"]["var"] not in read_vars})
    read_vars += sorted({
        o["TransactionRead"].get("payload", {}).get("Scalar", {}).get("var")
        for o in walk_leaf_ops(ops) if "TransactionRead" in o
        and is_simple_id(
            o["TransactionRead"].get("payload", {}).get(
                "Scalar", {}).get("var", ""))
        and o["TransactionRead"]["payload"]["Scalar"]["var"] not in declared
        and o["TransactionRead"]["payload"]["Scalar"]["var"] not in read_vars
    })
    declared |= set(read_vars)
    for v in read_vars:
        lines.append(f"{pad}{ctype} {v} = 0;")
    rmw_read_vars = {
        o["ReadModifyWrite"].get("read_var")
        for o in walk_leaf_ops(ops) if "ReadModifyWrite" in o
    }
    extra = sorted(value_var_names(ops) - declared - set(regs.keys())
                   - {name for name in rmw_read_vars if name})
    for v in extra:
        # Upper-case identifiers are C/kernel constants, not locals.  Declaring
        # them would collide with macros such as PCI_VENDOR_ID_INTEL.
        if v in _C_KEYWORDS or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v):
            continue
        lines.append(f"{pad}{ctype} {v} = 0;")
    tx = transaction_local_decls(ops, declared, indent)
    if tx:
        lines.append(tx)
    return "\n".join(lines)

def width_suffix(width: str) -> str:
    return {"B1": "8", "B2": "16", "B4": "32", "B8": "64"}.get(width, "32")


def mmio_primitive(bind, operation: str, body: dict) -> str:
    byte_order = body.get("evidence", {}).get("byte_order", "native")
    write_semantics = body.get("evidence", {}).get("write_semantics")
    semantic = operation + ("W1C" if write_semantics == "w1c" else "")
    semantic += "BE" if byte_order == "big" else ""
    primitive = bind.prim(semantic, body["width"])
    if primitive:
        return primitive
    native = {
        ("MmioRead", "B1"): "readb", ("MmioRead", "B2"): "readw",
        ("MmioRead", "B4"): "readl", ("MmioRead", "B8"): "readl",
        ("MmioWrite", "B1"): "writeb", ("MmioWrite", "B2"): "writew",
        ("MmioWrite", "B4"): "writel", ("MmioWrite", "B8"): "writel",
    }
    return native.get((operation, body["width"]),
                      "readl" if operation == "MmioRead" else "writel")
