"""Shared C-emission helpers for all backends."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from extractor.formal import expr_to_c, walk_leaf_ops, walk_all_ops

_VAR_ID = re.compile(r"^[A-Za-z_]\w*$")
_STRUCT_END_RE = re.compile(r"^};\s*$")


def split_header_source(code: str, driver_name: str, backend: str) -> tuple[str, str]:
    """Split a single-file generated driver into a .h and .c pair.

    The header receives everything up to and including the device-private
    struct definition (macros, inline helpers, register defines, struct)
    plus an include guard.  The source file receives an include of the
    header followed by the function implementations, callback tables and
    entry point.
    """
    lines = code.split("\n")
    first_struct_end = -1
    depth = 0
    for i, line in enumerate(lines):
        depth += line.count("{") - line.count("}")
        if depth == 0 and _STRUCT_END_RE.match(line):
            first_struct_end = i
            break
    if first_struct_end < 0:
        return "", code
    guard = f"REHARNESS_{driver_name.upper()}_{backend.upper()}_H"
    header_body = "\n".join(lines[:first_struct_end + 1])
    source_body = "\n".join(lines[first_struct_end + 1:])
    header = (f"#ifndef {guard}\n#define {guard}\n\n"
              + header_body + f"\n\n#endif /* {guard} */\n")
    source = f'#include "{driver_name}_{backend}.h"\n\n' + source_body
    return header, source


def generate_pair(backend_module, formal: dict, device_spec, bind,
                  **kwargs) -> tuple[str, str]:
    """Call a backend generate() and split into (.h, .c) strings."""
    code = backend_module.generate(formal, device_spec, bind, **kwargs)
    backend_name = backend_module.__name__.split(".")[-1]
    return split_header_source(code, device_spec.name, backend_name)


_C_KEYWORDS = {
    "auto", "char", "const", "double", "enum", "extern", "float", "for",
    "int", "long", "register", "restrict", "short", "signed", "static",
    "struct", "typedef", "union", "unsigned", "void", "volatile", "while",
}


def _called_names_in_text(text: str) -> set[str]:
    names = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text or ""))
    # Linux polling macros take the read accessor as their first argument and
    # invoke it internally.  That identifier is a function, not a scalar
    # local, even though source syntax does not place `(` immediately after it.
    for match in re.finditer(
            r"\bread_poll_timeout(?:_atomic)?\s*\(\s*([A-Za-z_]\w*)",
            text or ""):
        names.add(match.group(1))
    return names


def _vars_in_expr(e) -> set[str]:
    if e is None:
        return set()
    out: set[str] = set()
    if "Var" in e:
        v = e["Var"]
        if _VAR_ID.match(v):
            out.add(v)
        else:
            for m in re.finditer(r"\b[A-Za-z_]\w*\b", v):
                before = v[:m.start()].rstrip()
                after = v[m.end():].lstrip()
                if (after.startswith(("(", "->", "."))
                        or before.endswith(("->", "."))):
                    continue
                out.add(m.group(0))
        out -= _called_names_in_text(v)
    if "BinOp" in e:
        out |= _vars_in_expr(e["BinOp"]["left"])
        out |= _vars_in_expr(e["BinOp"]["right"])
    if "Ite" in e:
        out |= _vars_in_expr(e["Ite"]["guard"])
        out |= _vars_in_expr(e["Ite"]["then"])
        out |= _vars_in_expr(e["Ite"]["else"])
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"]["expr"])
    return out


def value_var_names(ops) -> set[str]:
    """Identifiers referenced in values, guards, or computed addresses."""
    names: set[str] = set()
    for op in walk_all_ops(ops):
        if "Cond" in op:
            names |= _vars_in_expr(op["Cond"]["guard"])
        elif "Loop" in op:
            names |= _vars_in_expr(op["Loop"].get("guard"))
            for loop_text in (op["Loop"].get("init", ""),
                              op["Loop"].get("step", "")):
                loop_names = {
                    name for name in re.findall(r"\b[A-Za-z_]\w*\b", loop_text)
                    if name not in _C_KEYWORDS
                }
                names |= loop_names - _called_names_in_text(loop_text)
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body and "Computed" in body.get("addr", {}):
            names |= _vars_in_expr(body["addr"]["Computed"])
        if "Write" in op:
            names |= _vars_in_expr(op["Write"].get("value"))
        elif "ReadModifyWrite" in op:
            names |= _vars_in_expr(op["ReadModifyWrite"].get("transform"))
        elif "StateWrite" in op:
            names |= _vars_in_expr(op["StateWrite"].get("value"))
        elif "OutputWrite" in op:
            names |= _vars_in_expr(op["OutputWrite"].get("value"))
        elif "Return" in op:
            names |= _vars_in_expr(op["Return"].get("value"))
    return names


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
        return _vars_in_expr(expr)

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
        if _is_simple_id(name) and name not in declared:
            lines.append(f"{pad}uint32_t {name} = 0;")
            declared.add(name)
    for name in sorted(values - declared):
        if _is_simple_id(name) and name not in _C_KEYWORDS \
                and not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
            lines.append(f"{pad}uint32_t {name} = 0;")
            declared.add(name)
    for name in sorted(buffers):
        if _is_simple_id(name) and name not in declared:
            lines.append(f"{pad}uint32_t {name}[64] = {{0}};")
            declared.add(name)
    for name in sorted(ids - declared):
        if (not _is_simple_id(name) or name in _C_KEYWORDS
                or re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name)):
            continue
        lines.append(f"{pad}void *{name} = 0;")
        declared.add(name)
    return "\n".join(lines)


def lowering_recipes(ops: list) -> dict[str, dict]:
    """Describe which physical primitives each Formal leaf owns.

    Dataflow-derived ``ReadModifyWrite`` leaves represent a source *write*
    whose transform depends on a preceding source Read.  Re-reading inside the
    RMW lowering duplicates a hardware access.  Intrinsic update-bits style
    operations have no preceding producer and legitimately own both a read and
    a write.
    """
    recipes: dict[str, dict] = {}

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
                if body.get("var") and op_id:
                    producers[body["var"]] = (op_id, body.get("addr", {}))
                continue
            if "Write" in op:
                body = op["Write"]
                if body.get("op_id"):
                    recipes[body["op_id"]] = {
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


def _is_simple_id(name: str) -> bool:
    return bool(_VAR_ID.match(name))


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
                        if "Read" in o and _is_simple_id(o["Read"]["var"])
                        and o["Read"]["var"] not in declared})
    read_vars += sorted({o["StateRead"]["var"] for o in walk_leaf_ops(ops)
                         if "StateRead" in o
                         and _is_simple_id(o["StateRead"]["var"])
                         and o["StateRead"]["var"] not in declared
                         and o["StateRead"]["var"] not in read_vars})
    read_vars += sorted({
        o["TransactionRead"].get("payload", {}).get("Scalar", {}).get("var")
        for o in walk_leaf_ops(ops) if "TransactionRead" in o
        and _is_simple_id(
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


def _width_suffix(width: str) -> str:
    return {"B1": "8", "B2": "16", "B4": "32", "B8": "64"}.get(width, "32")


def _mmio_primitive(bind, operation: str, body: dict) -> str:
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


def ris_op_digest(op: dict) -> str:
    """Stable semantic digest used by backend lowering receipts.

    Source paths and other provenance are deliberately excluded: the digest
    describes the operation the backend must lower, while the canonical
    Formal RIS remains the authority for provenance.  The digest is always
    derived from the current operation; callers must not cache it in Formal
    RIS, because doing so would hide later semantic mutations.
    """
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = copy.deepcopy(op.get(kind, {}))
    body.pop("op_id", None)
    body.pop("contract_digest", None)
    body.pop("_backend_contract_digest", None)
    body.pop("_backend_lowering_recipe", None)
    evidence = body.pop("evidence", {})
    # Most evidence locates the source operation and is intentionally outside
    # the semantic contract.  These fields, however, select different backend
    # MMIO primitives and therefore must participate in the digest.
    lowering_evidence = {
        name: evidence[name]
        for name in ("byte_order", "write_semantics")
        if name in evidence
    }
    semantic = {"kind": kind, "body": body}
    if lowering_evidence:
        semantic["lowering_evidence"] = lowering_evidence
    encoded = json.dumps(
        semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def lowering_receipt(op: dict, disposition: str = "lowered") -> str:
    """Machine-readable receipt for one register RIS operation."""
    kind = next((name for name in ("Read", "Write", "ReadModifyWrite")
                 if name in op), "Unknown")
    body = op.get(kind, {})
    digest = body.get("_backend_contract_digest") or ris_op_digest(op)
    return ("/* REHARNESS_RIS_OP "
            f"id={body.get('op_id', '?')} kind={kind} "
            f"status={disposition} digest={digest} */")


TRANSACTION_KINDS = ("TransactionRead", "TransactionWrite", "TransactionUpdate")


def transaction_kind(op: dict) -> str | None:
    return next((name for name in TRANSACTION_KINDS if name in op), None)


def transaction_digest(op: dict) -> str:
    """Stable digest for the backend-independent transaction contract."""
    kind = transaction_kind(op)
    if kind is None:
        return "0000000000000000"
    body = copy.deepcopy(op[kind])
    for key in ("op_id", "evidence", "reliability", "path_precision",
                "access_domain", "transport", "_backend_contract_digest"):
        body.pop(key, None)
    encoded = json.dumps({"schema": 1, "kind": kind, "body": body},
                         sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def transaction_receipt(op: dict, disposition: str = "lowered") -> str:
    kind = transaction_kind(op) or "Unknown"
    body = op.get(kind, {})
    digest = body.get("_backend_contract_digest") or transaction_digest(op)
    return ("/* REHARNESS_TRANSACTION_OP "
            f"id={body.get('op_id', '?')} kind={kind} "
            f"transport={body.get('transport', 'unknown')} "
            f"status={disposition} digest={digest} */")


def _transaction_anchor(op: dict, seen: set[str]) -> str:
    kind = transaction_kind(op)
    body = op.get(kind, {}) if kind else {}
    op_id = body.get("op_id")
    if not isinstance(op_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", op_id):
        raise ValueError(f"transaction operation has invalid op_id: {op_id!r}")
    if op_id in seen:
        raise ValueError(f"duplicate transaction operation id: {op_id}")
    seen.add(op_id)
    return f"__rh_txn_{op_id}"


def _transaction_expr(value: dict | None, default: str = "0") -> str:
    if value is None:
        return default
    return expr_to_c(value)


def _transaction_scalar_width(payload: dict) -> str:
    width = payload.get("width") or payload.get("element_width")
    return {"B1": "uint8_t", "B2": "uint16_t", "B4": "uint32_t",
            "B8": "uint64_t"}.get(width, "uint32_t")


def _i2c_helper(kind: str, body: dict, buffered: bool = False) -> str:
    protocol = body.get("protocol") or "smbus_byte_data"
    prefix = "reharness_i2c_master" if protocol == "raw" else "reharness_i2c_smbus"
    action = "read" if kind == "TransactionRead" else "write"
    if protocol == "raw":
        return f"{prefix}_{'recv' if action == 'read' else 'send'}"
    if buffered:
        return f"{prefix}_{action}_{'i2c_block' if protocol == 'i2c_block' else 'block_data'}"
    return f"{prefix}_{action}_{protocol.removeprefix('smbus_')}"


def _transaction_lowering(op: dict, pad: str, out: list[str], seen: set[str], bind=None) -> None:
    """Emit the shared transaction ABI used by all three generated backends."""
    kind = transaction_kind(op)
    if kind is None:
        return
    body = op[kind]
    target = _transaction_expr(body.get("target"), "0")
    selector = _transaction_expr(body.get("selector"), "0")
    transport = body.get("transport", "unknown")
    if transport not in {"regmap", "i2c_smbus", "i2c", "mfd"}:
        out.append(f"{pad}{transaction_receipt(op, 'rejected')}")
        out.append(f"{pad}{_transaction_anchor(op, seen)}: {{")
        out.append(f"{pad}    /* REHARNESS_UNSUPPORTED_TRANSACTION: {transport} */")
        out.append(f"{pad}}}")
        return
    out.append(f"{pad}{transaction_receipt(op)}")
    out.append(f"{pad}{_transaction_anchor(op, seen)}: {{")
    out.append(f'{pad}    reharness_transaction_mark("{body.get("op_id", "?")}");')
    if transport == "mfd":
        target = _transaction_expr(body.get("target"), "0")
        selector = _transaction_expr(body.get("selector"), "0")
        mask = _transaction_expr(body.get("mask"), "0")
        value = _transaction_expr(body.get("value"), "0")
        if getattr(bind, "backend", None) == "linux":
            helper = body.get("helper_symbol")
            if not isinstance(helper, str) or not re.fullmatch(r"[A-Za-z_]\w*", helper):
                out.append(f"{pad}    /* REHARNESS_UNSUPPORTED_MFD_HELPER */")
            elif body.get("helper_contract") == "set_bits":
                out.append(f"{pad}    (void){helper}((void *)({target}), {selector}, {mask});")
                out.append(f"{pad}    reharness_mfd_trace(\"U\", {selector}, 1, {mask});")
            elif body.get("helper_contract") == "clear_bits":
                out.append(f"{pad}    (void){helper}((void *)({target}), {selector}, {mask});")
                out.append(f"{pad}    reharness_mfd_trace(\"U\", {selector}, 1, 0);")
            else:
                out.append(f"{pad}    (void){helper}((void *)({target}), {selector}, {value});")
                out.append(f"{pad}    reharness_mfd_trace(\"W\", {selector}, 1, {value});")
        elif kind == "TransactionRead":
            var = (body.get("payload") or {}).get("Scalar", {}).get("var") or body.get("result") or "transaction_result"
            out.append(f"{pad}    {var} = 0;")
            out.append(f"{pad}    (void)reharness_mfd_read((void *)({target}), {selector}, (unsigned int *)&{var});")
        elif kind == "TransactionWrite":
            payload = body.get("payload") or {}
            value = _transaction_expr((payload.get("Scalar") or {}).get("value"), value)
            out.append(f"{pad}    (void)reharness_mfd_write((void *)({target}), {selector}, (unsigned int)({value}));")
        else:
            out.append(f"{pad}    (void)reharness_mfd_update((void *)({target}), {selector}, (unsigned int)({mask}), (unsigned int)({value}));")
        out.append(f"{pad}}}")
        return
    if transport in {"i2c_smbus", "i2c"}:
        payload = body.get("payload") or {}
        buffered = "Buffer" in payload
        helper = _i2c_helper(kind, body, buffered)
        if buffered:
            p = payload["Buffer"]
            buf = _transaction_expr(p.get("buffer"), "0")
            count = _transaction_expr(p.get("count"), "1")
            if body.get("protocol") == "raw":
                args = f"(void *)({target}), (void *)({buf}), {count}"
            else:
                args = f"(void *)({target}), {selector}, (void *)({buf}), {count}"
            call = f"{helper}({args})"
            result = body.get("result") if kind == "TransactionRead" else None
            if isinstance(result, str) and _is_simple_id(result):
                out.append(f"{pad}    {result} = {call};")
            else:
                out.append(f"{pad}    (void){call};")
        elif kind == "TransactionRead":
            p = payload.get("Scalar", {})
            var = p.get("var") or "transaction_result"
            out.append(f"{pad}    {var} = 0;")
            args = (f"(void *)({target}), (unsigned int *)&{var}"
                    if body.get("protocol") == "smbus_byte"
                    else f"(void *)({target}), {selector}, (unsigned int *)&{var}")
            out.append(f"{pad}    (void){helper}({args});")
            out.append(f"{pad}    (void){var};")
        else:
            p = payload.get("Scalar", {})
            value = _transaction_expr(p.get("value"), "0")
            args = (f"(void *)({target}), (unsigned int)({value})"
                    if body.get("protocol") == "smbus_byte"
                    else f"(void *)({target}), {selector}, (unsigned int)({value})")
            out.append(f"{pad}    (void){helper}({args});")
        out.append(f"{pad}}}")
        return
    if kind == "TransactionRead":
        payload = body.get("payload") or {}
        if "Buffer" in payload:
            p = payload["Buffer"]
            buf = _transaction_expr(p.get("buffer"), "0")
            count = _transaction_expr(p.get("count"), "1")
            out.append(f"{pad}    (void)reharness_regmap_bulk_read((void *)({target}), {selector}, {buf}, {count});")
        else:
            p = payload.get("Scalar", {})
            var = p.get("var") or "transaction_result"
            ctype = _transaction_scalar_width(p)
            out.append(f"{pad}    {var} = 0;")
            out.append(f"{pad}    (void)reharness_regmap_read((void *)({target}), {selector}, (unsigned int *)&{var});")
            out.append(f"{pad}    (void){var};")
    elif kind == "TransactionWrite":
        payload = body.get("payload") or {}
        if "Buffer" in payload:
            p = payload["Buffer"]
            buf = _transaction_expr(p.get("buffer"), "0")
            count = _transaction_expr(p.get("count"), "1")
            out.append(f"{pad}    (void)reharness_regmap_bulk_write((void *)({target}), {selector}, {buf}, {count});")
        else:
            p = payload.get("Scalar", {})
            value = _transaction_expr(p.get("value"), "0")
            out.append(f"{pad}    (void)reharness_regmap_write((void *)({target}), {selector}, (unsigned int)({value}));")
    else:
        mask = _transaction_expr(body.get("mask"), "0")
        value = _transaction_expr(body.get("value"), "0")
        changed = body.get("changed_result")
        call = (f"reharness_regmap_update((void *)({target}), {selector}, "
                f"(unsigned int)({mask}), (unsigned int)({value}))")
        if changed and _is_simple_id(changed):
            out.append(f"{pad}    {changed} = ({call} != 0);")
        else:
            out.append(f"{pad}    (void){call};")
    out.append(f"{pad}}}")


def transaction_runtime_prelude(backend: str) -> list[str]:
    """C ABI shared by generated regmap transaction leaves.

    Deprecated wrapper that emits nothing. Use
    transaction_runtime_prelude_filtered with transport flags instead.
    """
    return transaction_runtime_prelude_filtered(
        backend, has_regmap=False, has_i2c=False, has_mfd=False)


def detect_transaction_transports(formal: dict) -> dict:
    """Detect which non-MMIO transaction transports exist in the Formal RIS."""
    has_regmap = has_i2c = has_mfd = False
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            for name in ("TransactionRead", "TransactionWrite",
                         "TransactionUpdate"):
                if name in op:
                    transport = op[name].get("transport", "")
                    if transport == "regmap":
                        has_regmap = True
                    elif transport in ("i2c", "i2c_smbus"):
                        has_i2c = True
                    elif transport == "mfd":
                        has_mfd = True
    return {"has_regmap": has_regmap, "has_i2c": has_i2c,
            "has_mfd": has_mfd}


def transaction_runtime_prelude_filtered(
        backend: str, *, has_regmap: bool, has_i2c: bool,
        has_mfd: bool) -> list[str]:
    """Emit only the transaction runtime wrappers needed by the RIS."""
    if backend == "linux":
        lines: list[str] = []
        if has_regmap:
            lines.append("#include <linux/regmap.h>")
        if has_i2c:
            lines.append("#include <linux/i2c.h>")
        has_any = has_regmap or has_i2c or has_mfd
        if has_any:
            lines.extend([
                "static const char *reharness_txn_current_id = \"?\";"
                "static inline void reharness_transaction_mark(const char *id) { reharness_txn_current_id = id; }"
            ])
        if has_regmap:
            lines.append(
                "#define reharness_txn_trace(k, r, n, v) pr_debug(\"[reharness-txn] id=%s %s transport=regmap selector=0x%08x count=%u value=0x%08x\\\n\", reharness_txn_current_id, k, r, n, v)")
        if has_i2c:
            lines.extend([
                "#define reharness_i2c_trace(k, r, n, v) pr_debug(\"[reharness-txn] id=%s %s transport=i2c_smbus selector=0x%08x count=%u value=0x%08x\\\n\", reharness_txn_current_id, k, r, n, v)",
                "#define reharness_i2c_raw_trace(k, r, n, v) pr_debug(\"[reharness-txn] id=%s %s transport=i2c selector=0x%08x count=%u value=0x%08x\\\n\", reharness_txn_current_id, k, r, n, v)",
            ])
        if has_mfd:
            lines.append(
                "#define reharness_mfd_trace(k, r, n, v) pr_debug(\"[reharness-txn] id=%s %s transport=mfd selector=0x%08x count=%u value=0x%08x\\\n\", reharness_txn_current_id, k, r, n, v)")
        return lines
    trace = (
        'printf("[txn %lu] id=%s %s transport=regmap selector=0x%08x count=%u value=0x%08x\\n", '
        'reharness_txn_trace_count++, reharness_txn_current_id, kind, selector, count, value);')
    guard = "REHARNESS_BAREMETAL_ORACLE" if backend == "baremetal" else None
    lines: list[str] = []
    if has_regmap:
        lines.append("static uint32_t reharness_regmap_state[256];")
    if has_i2c:
        lines.append("static uint8_t reharness_i2c_state[256];")
    if has_mfd:
        lines.append("static uint32_t reharness_mfd_state[256];")
    has_any = has_regmap or has_i2c or has_mfd
    if has_any:
        lines.extend([
        "static unsigned long reharness_txn_trace_count;",
        "static const char *reharness_txn_current_id = \"?\";",
        "static inline void reharness_transaction_mark(const char *id) { reharness_txn_current_id = id; }",
        ])
    if has_regmap:
        lines.extend([
        "static inline void reharness_txn_trace(const char *kind, uint32_t selector, uint32_t count, uint32_t value) {",
        *([f"#ifdef {guard}", "    " + trace, "#else",
            "    (void)kind; (void)selector; (void)count; (void)value;",
            "#endif"] if guard else ["    " + trace]),
        "}",
        ])
    if has_i2c:
        lines.extend([
        "static inline void reharness_i2c_trace(const char *kind, uint32_t selector, uint32_t count, uint32_t value) {",
        *([f"#ifdef {guard}", "    " + trace.replace("transport=regmap", "transport=i2c_smbus"), "#else",
            "    (void)kind; (void)selector; (void)count; (void)value;", "#endif"] if guard else ["    " + trace.replace("transport=regmap", "transport=i2c_smbus")]),
        "}",
        "static inline void reharness_i2c_raw_trace(const char *kind, uint32_t selector, uint32_t count, uint32_t value) {",
        *([f"#ifdef {guard}", "    " + trace.replace("transport=regmap", "transport=i2c"), "#else",
            "    (void)kind; (void)selector; (void)count; (void)value;", "#endif"] if guard else ["    " + trace.replace("transport=regmap", "transport=i2c")]),
        "}",
        ])
    if has_mfd:
        lines.extend([
        "static inline void reharness_mfd_trace(const char *kind, uint32_t selector, uint32_t count, uint32_t value) {",
        *([f"#ifdef {guard}", "    " + trace.replace("transport=regmap", "transport=mfd"), "#else",
            "    (void)kind; (void)selector; (void)count; (void)value;", "#endif"] if guard else ["    " + trace.replace("transport=regmap", "transport=mfd")]),
        "}",
        ])
    if has_regmap:
        lines.extend([
            "static inline int reharness_regmap_read(void *t, uint32_t r, uint32_t *v) { (void)t; *v = reharness_regmap_state[r & 255u]; reharness_txn_trace(\"R\", r, 1, *v); return 0; }",
            "static inline int reharness_regmap_write(void *t, uint32_t r, uint32_t v) { (void)t; reharness_regmap_state[r & 255u] = v; reharness_txn_trace(\"W\", r, 1, v); return 0; }",
            "static inline int reharness_regmap_update(void *t, uint32_t r, uint32_t m, uint32_t v) { (void)t; uint32_t old = reharness_regmap_state[r & 255u]; uint32_t next = (old & ~m) | (v & m); reharness_regmap_state[r & 255u] = next; reharness_txn_trace(\"U\", r, 1, next); return old != next; }",
            "static inline int reharness_regmap_bulk_read(void *t, uint32_t r, uint32_t *b, uint32_t n) { (void)t; for (uint32_t i = 0; i < n; ++i) b[i] = reharness_regmap_state[(r + i) & 255u]; reharness_txn_trace(\"BR\", r, n, n ? b[0] : 0); return 0; }",
            "static inline int reharness_regmap_bulk_write(void *t, uint32_t r, const uint32_t *b, uint32_t n) { (void)t; for (uint32_t i = 0; i < n; ++i) reharness_regmap_state[(r + i) & 255u] = b[i]; reharness_txn_trace(\"BW\", r, n, n ? b[0] : 0); return 0; }",
        ])
    if has_i2c:
        lines.extend([
            "static inline int reharness_i2c_smbus_read_byte(void *t, unsigned int *v) { (void)t; *v = reharness_i2c_state[0]; reharness_i2c_trace(\"R\", 0, 1, *v); return 0; }",
            "static inline int reharness_i2c_smbus_write_byte(void *t, unsigned int v) { (void)t; reharness_i2c_state[0] = (uint8_t)v; reharness_i2c_trace(\"W\", 0, 1, v); return 0; }",
            "static inline int reharness_i2c_smbus_read_byte_data(void *t, unsigned int r, unsigned int *v) { (void)t; *v = reharness_i2c_state[r & 255u]; reharness_i2c_trace(\"R\", r, 1, *v); return 0; }",
            "static inline int reharness_i2c_smbus_write_byte_data(void *t, unsigned int r, unsigned int v) { (void)t; reharness_i2c_state[r & 255u] = (uint8_t)v; reharness_i2c_trace(\"W\", r, 1, v); return 0; }",
            "static inline int reharness_i2c_smbus_read_word_data(void *t, unsigned int r, unsigned int *v) { return reharness_i2c_smbus_read_byte_data(t, r, v); }",
            "static inline int reharness_i2c_smbus_write_word_data(void *t, unsigned int r, unsigned int v) { return reharness_i2c_smbus_write_byte_data(t, r, v); }",
            "static inline int reharness_i2c_smbus_read_word_data_swapped(void *t, unsigned int r, unsigned int *v) { return reharness_i2c_smbus_read_word_data(t, r, v); }",
            "static inline int reharness_i2c_smbus_write_word_data_swapped(void *t, unsigned int r, unsigned int v) { return reharness_i2c_smbus_write_word_data(t, r, v); }",
            "static inline int reharness_i2c_smbus_read_block_data(void *t, unsigned int r, void *b, unsigned int n) { (void)t; for (unsigned int i = 0; i < n; ++i) ((uint8_t *)b)[i] = reharness_i2c_state[(r + i) & 255u]; reharness_i2c_trace(\"BR\", r, n, n ? ((uint8_t *)b)[0] : 0); return (int)n; }",
            "static inline int reharness_i2c_smbus_write_block_data(void *t, unsigned int r, void *b, unsigned int n) { (void)t; for (unsigned int i = 0; i < n; ++i) reharness_i2c_state[(r + i) & 255u] = ((uint8_t *)b)[i]; reharness_i2c_trace(\"BW\", r, n, n ? ((uint8_t *)b)[0] : 0); return 0; }",
            "static inline int reharness_i2c_smbus_read_i2c_block(void *t, unsigned int r, void *b, unsigned int n) { return reharness_i2c_smbus_read_block_data(t, r, b, n); }",
            "static inline int reharness_i2c_smbus_write_i2c_block(void *t, unsigned int r, void *b, unsigned int n) { return reharness_i2c_smbus_write_block_data(t, r, b, n); }",
            "static inline int reharness_i2c_master_recv(void *t, void *b, unsigned int n) { (void)t; for (unsigned int i = 0; i < n; ++i) ((uint8_t *)b)[i] = reharness_i2c_state[i & 255u]; reharness_i2c_raw_trace(\"BR\", 0, n, n ? ((uint8_t *)b)[0] : 0); return (int)n; }",
            "static inline int reharness_i2c_master_send(void *t, void *b, unsigned int n) { (void)t; for (unsigned int i = 0; i < n; ++i) reharness_i2c_state[i & 255u] = ((uint8_t *)b)[i]; reharness_i2c_raw_trace(\"BW\", 0, n, n ? ((uint8_t *)b)[0] : 0); return (int)n; }",
        ])
    if has_mfd:
        lines.extend([
            "static inline int reharness_mfd_read(void *t, unsigned int r, unsigned int *v) { (void)t; *v = reharness_mfd_state[r & 255u]; reharness_mfd_trace(\"R\", r, 1, *v); return 0; }",
            "static inline int reharness_mfd_write(void *t, unsigned int r, unsigned int v) { (void)t; reharness_mfd_state[r & 255u] = v; reharness_mfd_trace(\"W\", r, 1, v); return 0; }",
            "static inline int reharness_mfd_update(void *t, unsigned int r, unsigned int m, unsigned int v) { (void)t; unsigned int old = reharness_mfd_state[r & 255u]; unsigned int next = (old & ~m) | (v & m); reharness_mfd_state[r & 255u] = next; reharness_mfd_trace(\"U\", r, 1, next); return old != next; }",
        ])
    return lines


def _operation_anchor(op: dict, seen: set[str]) -> str:
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


def _begin_operation(out: list[str], pad: str, op: dict,
                     disposition: str, seen: set[str]) -> None:
    """Start a receipt-bound compound statement owned by a unique label."""
    out.append(f"{pad}{lowering_receipt(op, disposition)}")
    out.append(f"{pad}{_operation_anchor(op, seen)}: {{")


def _replace_expr_var(expr, name: str | None, replacement: str):
    if not isinstance(expr, dict) or not name:
        return expr
    if expr.get("Var") == name:
        return {"Var": replacement}
    out = dict(expr)
    if "BinOp" in expr:
        b = dict(expr["BinOp"])
        b["left"] = _replace_expr_var(b.get("left"), name, replacement)
        b["right"] = _replace_expr_var(b.get("right"), name, replacement)
        out["BinOp"] = b
    elif "Ite" in expr:
        i = dict(expr["Ite"])
        i["guard"] = _replace_expr_var(i.get("guard"), name, replacement)
        i["then"] = _replace_expr_var(i.get("then"), name, replacement)
        i["else"] = _replace_expr_var(i.get("else"), name, replacement)
        out["Ite"] = i
    elif "Bits" in expr:
        b = dict(expr["Bits"])
        b["expr"] = _replace_expr_var(b.get("expr"), name, replacement)
        out["Bits"] = b
    return out


def addr_to_c(addr: dict, base_expr: str, register_macros: dict[str, int],
              state_expr: str = "") -> str:
    """Render a formal RegAddr as a C address expression.

    Symbolic registers render as `base_expr + REG_MACRO` (macro #defined in the
    header); Fixed as `base_expr + 0xOFF`; Computed as the expression."""
    if "Symbolic" in addr:
        reg = addr["Symbolic"]["register"]
        off = register_macros.get(reg)
        if off is not None:
            return f"{base_expr} + {reg}"
        return f"{base_expr} + 0x{off:x}" if off is not None else base_expr
    if "Fixed" in addr:
        off = addr["Fixed"]["offset"]
        source_base = addr["Fixed"].get("base", "")
        actual_base = base_expr
        if (state_expr and source_base and source_base != "base"
                and re.fullmatch(r"[A-Za-z_]\w*", source_base)):
            actual_base = f"{state_expr}->{source_base}"
        return f"{actual_base} + 0x{off:x}" if actual_base else f"0x{off:x}"
    if "Computed" in addr:
        return expr_to_c(addr["Computed"])
    return base_expr


def ops_to_c(ops: list, bind, base_expr: str, register_macros: dict[str, int],
             indent: int = 1, word_type: str = "uint32_t",
             state_expr: str = "dev", _anchor_ids: set[str] | None = None,
             _lowering_recipes: dict[str, dict] | None = None) -> str:
    """Translate a list of formal RISOps to C statements."""
    if _anchor_ids is None:
        _anchor_ids = set()
    if _lowering_recipes is None:
        _lowering_recipes = lowering_recipes(ops)
    pad = "    " * indent
    out: list[str] = []
    for op in ops:
        if transaction_kind(op) is not None:
            _transaction_lowering(op, pad, out, _anchor_ids, bind)
            continue
        leaf = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite"))
        if leaf is not None and leaf.get("reliability") == "Unsupported":
            _begin_operation(out, pad, op, "rejected", _anchor_ids)
            out.append(
                f"{pad}    /* REHARNESS_UNSUPPORTED_ACCESS_DOMAIN: "
                f"{leaf.get('access_domain', 'unknown')} {leaf.get('op_id', '?')} */")
            out.append(f"{pad}}}")
            continue
        if "Cond" in op:
            guard = expr_to_c(op["Cond"]["guard"])
            out.append(f"{pad}if ({guard}) {{")
            out.append(ops_to_c(op["Cond"]["then_ops"], bind, base_expr,
                                register_macros, indent + 1, word_type,
                                state_expr, _anchor_ids,
                                _lowering_recipes))
            if op["Cond"].get("else_ops"):
                out.append(f"{pad}}} else {{")
                out.append(ops_to_c(op["Cond"]["else_ops"], bind, base_expr,
                                    register_macros, indent + 1, word_type,
                                    state_expr, _anchor_ids,
                                    _lowering_recipes))
            out.append(f"{pad}}}")
        elif "Loop" in op:
            loop = op["Loop"]
            guard = expr_to_c(loop.get("guard", {"Top": None}))
            if (loop.get("reliability") == "Exact"
                    and loop.get("bounded")
                    and loop.get("loop_kind") == "for"):
                if loop.get("dynamic_bound"):
                    induction = loop.get("induction_var", "__reharness_i")
                    bound = expr_to_c(
                        loop.get("bound_expr") or loop.get("count"))
                    relation = loop.get("relation", "<")
                    start = int(loop.get("start", 0))
                    stride = int(loop.get("stride", 1))
                    step = (f"{induction}++" if stride == 1
                            else f"{induction} += {stride}")
                    out.append(
                        f"{pad}for (uint32_t {induction} = {start}, "
                        f"__reharness_limit = {bound}; "
                        f"{induction} {relation} __reharness_limit; {step}) {{")
                else:
                    init = loop.get("init", "").strip().rstrip(";")
                    step = loop.get("step", "").strip().rstrip(";")
                    out.append(f"{pad}for ({init}; {guard}; {step}) {{")
                out.append(ops_to_c(loop.get("body", []), bind, base_expr,
                                    register_macros, indent + 1, word_type,
                                    state_expr, _anchor_ids,
                                    _lowering_recipes))
                out.append(f"{pad}}}")
            elif (loop.get("reliability") == "Exact"
                  and loop.get("proof_kind") == "masked_w1c_drain"):
                out.append(f"{pad}for (;;) {{")
                out.append(ops_to_c(
                    loop.get("guard_ops", []), bind, base_expr,
                    register_macros, indent + 1, word_type, state_expr,
                    _anchor_ids, _lowering_recipes))
                guard_var = loop.get("guard_var", "guard")
                guard_value = expr_to_c(loop.get("guard_value"))
                out.append(f"{pad}    {guard_var} = {guard_value};")
                out.append(f"{pad}    if (!{guard_var})")
                out.append(f"{pad}        break;")
                out.append(ops_to_c(
                    loop.get("body", []), bind, base_expr,
                    register_macros, indent + 1, word_type, state_expr,
                    _anchor_ids, _lowering_recipes))
                out.append(f"{pad}}}")
            else:
                out.append(
                    f"{pad}/* REHARNESS_UNSUPPORTED_LOOP: "
                    f"{loop.get('loop_kind', 'loop')} guard={guard} */")
        elif "Seq" in op:
            out.append(ops_to_c(op["Seq"]["ops"], bind, base_expr,
                                register_macros, indent, word_type, state_expr,
                                _anchor_ids, _lowering_recipes))
        elif "Read" in op:
            o = op["Read"]
            r = _mmio_primitive(bind, "MmioRead", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            var = o["var"]
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            if (_is_simple_id(var)
                    or re.fullmatch(r"(?:g|dev)->[A-Za-z_]\w*", var)):
                out.append(f"{pad}    {var} = {r}({a});")
                if _is_simple_id(var):
                    out.append(f"{pad}    (void){var};")
            else:
                # member-access target (e.g. edu->revision) — discard the read
                # result (the field isn't in the generated harness struct)
                out.append(f"{pad}    (void){r}({a});")
            out.append(f"{pad}}}")
        elif "Write" in op:
            o = op["Write"]
            w = _mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            v = expr_to_c(o["value"])
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            out.append(f"{pad}    {w}({v}, {a});")
            out.append(f"{pad}}}")
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            r = _mmio_primitive(bind, "MmioRead", o)
            w = _mmio_primitive(bind, "MmioWrite", o)
            a = addr_to_c(o["addr"], base_expr, register_macros, state_expr)
            recipe = (o.get("_backend_lowering_recipe")
                      or _lowering_recipes.get(o.get("op_id"), {}))
            _begin_operation(out, pad, op, "lowered", _anchor_ids)
            if recipe.get("kind") == "write_from_read":
                out.append(
                    f"{pad}    {w}({expr_to_c(o.get('transform'))}, {a});")
            else:
                t = _replace_expr_var(
                    o.get("transform"), o.get("read_var"), "v")
                t_c = ("v" if isinstance(t, dict) and "Top" in t
                       else expr_to_c(t))
                out.append(f"{pad}    {word_type} v = {r}({a});")
                out.append(f"{pad}    {w}({t_c}, {a});")
            out.append(f"{pad}}}")
        elif "StateRead" in op:
            o = op["StateRead"]
            index = (f"[{expr_to_c(o['index'])}]"
                     if o.get("index") else "")
            out.append(
                f"{pad}{o['var']} = {state_expr}->{o['field']}{index};")
        elif "StateWrite" in op:
            o = op["StateWrite"]
            index = (f"[{expr_to_c(o['index'])}]"
                     if o.get("index") else "")
            out.append(
                f"{pad}{state_expr}->{o['field']}{index} = "
                f"{expr_to_c(o['value'])};")
        elif "OutputWrite" in op:
            o = op["OutputWrite"]
            out.append(f"{pad}*{o['target']} = {expr_to_c(o['value'])};")
        elif "Return" in op:
            out.append(f"{pad}return {expr_to_c(op['Return']['value'])};")
        elif "Delay" in op:
            out.append(
                f"{pad}reharness_delay_ns({expr_to_c(op['Delay']['cycles'])});")
    return "\n".join(s for s in out if s)
