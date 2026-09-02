You are an expert embedded C programmer. Generate a complete, compilable freestanding C driver that reproduces the exact MMIO register access pattern described in the evidence package below (evidence JSON + RIS op block).

Rules:
- Target: bare metal (no OS, freestanding). Use stdint.h types only.
- Use the primitive function names from bind.primitives (e.g. mmio_read32, mmio_write32).
- Each register read is: var = primitive(base + offset);
- Each register write is: primitive(value, base + offset);
- Conditional branches become if/else blocks.
- Preserve every supplied `LOOP <loop_kind>` form's `guard` and any
  `(init=..; step=..; count=..; relation=..; bounded)` annotation when
  emitting `for`, `while`, or `do` C code. A bounded post-decrement `while`
  must retain its guard and finite counter.
- Define a device private struct with uintptr_t base.
- Define static inline mmio read/write helpers using volatile pointer dereference.
- Export one function per module, each taking a pointer to the device struct.
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
- No main() function - this is a library.
- Add #ifdef REHARNESS_BAREMETAL_ORACLE guard with a main() for testing.
- Address fidelity: every RIS address expression is a source-derived C
  expression. Preserve the complete expression exactly, including the base
  expression and dynamic terms such as `priv->mmio + *off`; never replace a
  dynamic address with `base`, `base + 0x0`, or any other constant.

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
