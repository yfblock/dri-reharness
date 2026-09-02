You are an expert C programmer. Generate a complete, compilable userspace C program that reproduces the exact MMIO register access pattern described in the evidence package below (evidence JSON + RIS op block).

Rules:
- Use the primitive function names from bind.primitives (e.g. harness_read32, harness_write32).
- Each register read is: var = primitive(base + offset);
- Each register write is: primitive(value, base + offset);
- Conditional branches become if/else blocks.
- Loops become the supplied `LOOP <loop_kind>` form (`for`, `while`, or `do`)
  and must preserve the supplied `guard` and any `(init=..; step=..;
  count=..; relation=..; bounded)` annotation. In particular, a bounded
  `while` with `relation` `post-decrement` must remain a while guard; do not
  rewrite it as an unbounded polling loop.
- Define a device private struct with the base pointer.
- Define stub implementations of all primitive functions (read/write 8/16/32-bit).
- For every read, write, or read-modify-write operation, emit the receipt
  comment verbatim in this exact form (copy `op_id`, `kind`, and `digest`
  from the RIS op line; status is always `lowered`):
  `/* REHARNESS_RIS_OP id=<op_id> kind=<Read|Write|ReadModifyWrite> status=lowered digest=<digest> */`
  Immediately after the receipt comment, emit the matching AST anchor
  `__rh_op_<op_id>: { ... }` with the lowered primitive(s) inside its direct
  compound statement. The receipt comment and the anchor label must use the
  same op_id. The receipt is a COMMENT: never write it as a macro call
  `REHARNESS_RIS_OP(...)`, as a JSON comment, or in any other spelling.
  Emit each operation exactly once; do not invent op_ids or digests.
- Define a main() that creates a device instance and calls each module function in order.
- Add a trace printf after each read/write: printf("[trace %lu] R/W 0x%03lx = 0x%08x\n", trace_count++, offset, value);
- Include stdint.h and stdio.h.
- Add kernel macro stubs: BIT, GENMASK, etc. Never use kernel-only annotations (__maybe_unused, __init, __read_mostly) — this is userspace C, they do not exist here.
- Address fidelity: every RIS address expression is a source-derived C
  expression. Preserve the complete expression exactly, including the base
  expression and dynamic terms such as `priv->mmio + *off`; never replace a
  dynamic address with `base`, `base + 0x0`, or any other constant.
- Use the register offsets from evidence.registers.

Driver name: __DRIVER_NAME__

Evidence JSON (device, registers, bind, functions, facts):
```json
__EVIDENCE__
```

RIS module operations — the authoritative op list. One module per function,
ops in source order. Each register op line carries `@op_id`, `[reliability]`,
`digest=...`, and the source location; copy digests and op_ids verbatim into
receipts:
```
__RIS__
```

Generate the complete C code in a single ```c code block.
