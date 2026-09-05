You are an expert C programmer. Complete a userspace C program that reproduces the exact MMIO register access pattern described in the evidence package below (evidence JSON + RIS op block).

The file's part 00 is a fixed mechanical scaffold. You emit ONLY part 01 (the driver part): struct definitions, framework stubs, the module functions, and main().

Rules:
- NEVER emit: includes, the scaffold's macros/typedefs, register-offset #defines, the backing array, any primitive implementation, or any trace printf. Calling a primitive is enough — it traces itself.
- Use the primitive function names from bind.primitives (e.g. harness_read32, harness_write32).
- Each register read is: var = primitive(base + offset);
- Each register write is: primitive(value, base + offset);
- Conditional branches become if/else blocks.
- Loops become the supplied `LOOP <loop_kind>` form (`for`, `while`, or `do`)
  and must preserve the supplied `guard` and any `(init=..; step=..;
  count=..; relation=..; bounded)` annotation. In particular, a bounded
  `while` with `relation` `post-decrement` must remain a while guard; do not
  rewrite it as an unbounded polling loop.
- Define the device private struct with the base pointer, complete for the
  whole program (every private-state field the real upstream driver for this
  hardware carries; module bodies will reference conventional upstream field
  names). Fields are plain C — no kernel-only annotations (__maybe_unused and
  friends), the userspace dialect does not define them. Struct and helper
  identifiers must be valid C: a driver name like 8250_dw cannot start an
  identifier, so derive names such as dw8250_priv instead.
- Define minimal plain-C stubs for any kernel framework struct (struct device,
  struct platform_device, ...) or external function (devm_kzalloc, ...) that
  the driver's expressions reference or call — static, returning plausible
  zero-initialized static objects. Register/field names from the evidence are
  data, not C identifiers: never use one bare as a variable.
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
- If a Write's value expression needs the register's current value
  (read-modify-write), never call a read primitive inside the Write anchor:
  read the current value with the scaffold's raw reader instead —
  `rh_raw_read4(base + offset)` (width-matched: rh_raw_read1/2/4). It is
  untraced by design. A Write anchor body must contain exactly one primitive
  call — the write.
- Add a main() that creates static device instances, points every
  register-base member (base/regs/mmio) at rh_mmio_backing, and calls each
  module function in order. A main that returns without driving the modules
  produces an empty runtime trace and is rejected.
- Match the RIS access width exactly: B8 means ONE 64-bit access — never two
  32-bit halves; B4 32-bit, B2 16-bit, B1 8-bit. The verifier compares the
  primitive width against the RIS width per operation.
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

Scaffold part 00 (already prepended to the file — NEVER re-emit any of it) defines:
__SCAFFOLD__

Generate part 01 in a single ```c code block.
