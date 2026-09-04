"""Typed transaction lowering, receipts, anchors, and runtime preludes."""
from __future__ import annotations

import re

from extractor.formal import expr_to_c, walk_leaf_ops

from .idents import is_simple_id
from .receipts import transaction_digest, transaction_kind


def transaction_receipt(op: dict, disposition: str = "lowered") -> str:
    kind = transaction_kind(op) or "Unknown"
    body = op.get(kind, {})
    digest = body.get("_backend_contract_digest") or transaction_digest(op)
    return ("/* REHARNESS_TRANSACTION_OP "
            f"id={body.get('op_id', '?')} kind={kind} "
            f"transport={body.get('transport', 'unknown')} "
            f"status={disposition} digest={digest} */")


def transaction_anchor(op: dict, seen: set[str]) -> str:
    kind = transaction_kind(op)
    body = op.get(kind, {}) if kind else {}
    op_id = body.get("op_id")
    if not isinstance(op_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", op_id):
        raise ValueError(f"transaction operation has invalid op_id: {op_id!r}")
    if op_id in seen:
        raise ValueError(f"duplicate transaction operation id: {op_id}")
    seen.add(op_id)
    return f"__rh_txn_{op_id}"


def transaction_expr(value: dict | None, default: str = "0") -> str:
    if value is None:
        return default
    return expr_to_c(value)


def transaction_scalar_width(payload: dict) -> str:
    width = payload.get("width") or payload.get("element_width")
    return {"B1": "uint8_t", "B2": "uint16_t", "B4": "uint32_t",
            "B8": "uint64_t"}.get(width, "uint32_t")


def i2c_helper(kind: str, body: dict, buffered: bool = False) -> str:
    protocol = body.get("protocol") or "smbus_byte_data"
    prefix = "reharness_i2c_master" if protocol == "raw" else "reharness_i2c_smbus"
    action = "read" if kind == "TransactionRead" else "write"
    if protocol == "raw":
        return f"{prefix}_{'recv' if action == 'read' else 'send'}"
    if buffered:
        return f"{prefix}_{action}_{'i2c_block' if protocol == 'i2c_block' else 'block_data'}"
    return f"{prefix}_{action}_{protocol.removeprefix('smbus_')}"


def transaction_lowering(op: dict, pad: str, out: list[str], seen: set[str], bind=None) -> None:
    """Emit the shared transaction ABI used by all three generated backends."""
    kind = transaction_kind(op)
    if kind is None:
        return
    body = op[kind]
    target = transaction_expr(body.get("target"), "0")
    selector = transaction_expr(body.get("selector"), "0")
    transport = body.get("transport", "unknown")
    if transport not in {"regmap", "i2c_smbus", "i2c", "mfd"}:
        out.append(f"{pad}{transaction_receipt(op, 'rejected')}")
        out.append(f"{pad}{transaction_anchor(op, seen)}: {{")
        out.append(f"{pad}    /* REHARNESS_UNSUPPORTED_TRANSACTION: {transport} */")
        out.append(f"{pad}}}")
        return
    out.append(f"{pad}{transaction_receipt(op)}")
    out.append(f"{pad}{transaction_anchor(op, seen)}: {{")
    out.append(f'{pad}    reharness_transaction_mark("{body.get("op_id", "?")}");')
    if transport == "mfd":
        target = transaction_expr(body.get("target"), "0")
        selector = transaction_expr(body.get("selector"), "0")
        mask = transaction_expr(body.get("mask"), "0")
        value = transaction_expr(body.get("value"), "0")
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
            value = transaction_expr((payload.get("Scalar") or {}).get("value"), value)
            out.append(f"{pad}    (void)reharness_mfd_write((void *)({target}), {selector}, (unsigned int)({value}));")
        else:
            out.append(f"{pad}    (void)reharness_mfd_update((void *)({target}), {selector}, (unsigned int)({mask}), (unsigned int)({value}));")
        out.append(f"{pad}}}")
        return
    if transport in {"i2c_smbus", "i2c"}:
        payload = body.get("payload") or {}
        buffered = "Buffer" in payload
        helper = i2c_helper(kind, body, buffered)
        if buffered:
            p = payload["Buffer"]
            buf = transaction_expr(p.get("buffer"), "0")
            count = transaction_expr(p.get("count"), "1")
            if body.get("protocol") == "raw":
                args = f"(void *)({target}), (void *)({buf}), {count}"
            else:
                args = f"(void *)({target}), {selector}, (void *)({buf}), {count}"
            call = f"{helper}({args})"
            result = body.get("result") if kind == "TransactionRead" else None
            if isinstance(result, str) and is_simple_id(result):
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
            value = transaction_expr(p.get("value"), "0")
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
            buf = transaction_expr(p.get("buffer"), "0")
            count = transaction_expr(p.get("count"), "1")
            out.append(f"{pad}    (void)reharness_regmap_bulk_read((void *)({target}), {selector}, {buf}, {count});")
        else:
            p = payload.get("Scalar", {})
            var = p.get("var") or "transaction_result"
            ctype = transaction_scalar_width(p)
            out.append(f"{pad}    {var} = 0;")
            out.append(f"{pad}    (void)reharness_regmap_read((void *)({target}), {selector}, (unsigned int *)&{var});")
            out.append(f"{pad}    (void){var};")
    elif kind == "TransactionWrite":
        payload = body.get("payload") or {}
        if "Buffer" in payload:
            p = payload["Buffer"]
            buf = transaction_expr(p.get("buffer"), "0")
            count = transaction_expr(p.get("count"), "1")
            out.append(f"{pad}    (void)reharness_regmap_bulk_write((void *)({target}), {selector}, {buf}, {count});")
        else:
            p = payload.get("Scalar", {})
            value = transaction_expr(p.get("value"), "0")
            out.append(f"{pad}    (void)reharness_regmap_write((void *)({target}), {selector}, (unsigned int)({value}));")
    else:
        mask = transaction_expr(body.get("mask"), "0")
        value = transaction_expr(body.get("value"), "0")
        changed = body.get("changed_result")
        call = (f"reharness_regmap_update((void *)({target}), {selector}, "
                f"(unsigned int)({mask}), (unsigned int)({value}))")
        if changed and is_simple_id(changed):
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
