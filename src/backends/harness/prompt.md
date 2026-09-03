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
- Define one file-scope backing array for all MMIO:
  `static unsigned char rh_mmio_backing[65536];`
- Define stub implementations of all primitive functions (read/write 8/16/32-bit).
  Every stub must window its address into that array — a read is exactly
  `return *(volatile const unsigned int *)(void *)(rh_mmio_backing + (addr & 0xffffu));`
  (adjusted for width), a write stores to the same windowed pointer. Never
  dereference the raw address argument: an address of 0 or a NULL base must
  still land in backed memory. No lookup helpers, no byte-assembly.
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
  read the current value with a raw windowed dereference inside the value
  expression instead —
  `(*(volatile const unsigned int *)(void *)(rh_mmio_backing + ((base + offset) & 0xffffu)))`.
  A Write anchor body must contain exactly one primitive call — the write.
- Add a main() that creates static device instances, points every
  register-base member (base/regs/mmio) at rh_mmio_backing, and calls each
  module function in order. A main that returns without driving the modules
  produces an empty runtime trace and is rejected.
- Add a trace printf after each read/write, distinguishing the direction —
  after a read: printf("[trace %lu] R 0x%03lx = 0x%08x\n", trace_count++, offset, value);
  after a write: printf("[trace %lu] W 0x%03lx = 0x%08x\n", trace_count++, offset, value);
  (the direction letter must be R or W, never "R/W"; the runtime trace
  oracle parses it to order-check reads against writes).
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
