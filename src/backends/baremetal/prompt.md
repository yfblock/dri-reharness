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
  If a Write's value expression needs the register's current value
  (read-modify-write), never call a read helper inside the Write anchor: read
  the current value with a raw
  `(*(volatile const uint32_t *)(uintptr_t)(base + offset))` dereference inside
  the value expression. A Write anchor body must contain exactly one primitive
  call — the write.
- Export one function per module, each taking a pointer to the device struct.
- Add a trace printf inside every mmio helper, distinguish direction and
  include the value (the host oracle parses it):
  after a read:  printf("[trace %lu] R 0x%03lx = 0x%08x\n", n++, (unsigned long)(addr & 0xffffu), v);
  after a write: printf("[trace %lu] W 0x%03lx = 0x%08x\n", n++, (unsigned long)(addr & 0xffffu), v);
  (guard them with #ifdef REHARNESS_BAREMETAL_ORACLE plus #include <stdio.h>
  so the freestanding build stays printf-free; the direction letter must be
  R or W, never "R/W").
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
- Add #ifdef REHARNESS_BAREMETAL_ORACLE guard with a main() that drives the
  subsystem callbacks in plan order, using EXACTLY these output lines (the
  host oracle parses them):
  1. one line before any call:
     printf("[reharness-callback-begin] %d\n", N);   /* N = number of calls */
  2. per callback module <mod>, before calling it:
     printf("[reharness-callback] %s\n", "<mod>");
     then call the module function with a static device instance whose base
     member points at a static backing array;
  3. after each call, in order:
     printf("[reharness-result] 0x%08x\n", ret);        /* 0 if void */
     printf("[reharness-output] <name>=0x%08x\n", v);   /* per written out-param */
     printf("[reharness-state] sdata=0x%08x sdir=0x%08x\n",
            dev.sdata, dev.sdir);   /* GPIO shadow value/direction members,
                                        or the virtio seven-field line:
     printf("[reharness-virtio-state] ea=0x%08x ec=0x%08x so=0x%08x sc=0x%08x en=0x%08x sn=0x%08x ready=0x%08x\n", ...); */
  4. one line after the last call:
     printf("[reharness-callback-end]\n");
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
