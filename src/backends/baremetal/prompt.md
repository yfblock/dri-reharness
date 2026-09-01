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
- For every read, write, or read-modify-write operation, emit the exact supplied
  `REHARNESS_RIS_OP` receipt immediately before its implementation, followed by
  a matching direct compound AST anchor in the form
  `__rh_op_<op_id>: { ... }`. The receipt and anchor must use the same op_id;
  emit each operation exactly once and copy its supplied digest.
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
