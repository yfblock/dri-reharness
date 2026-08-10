You are an expert C programmer. Generate a complete, compilable userspace C program that reproduces the exact MMIO register access pattern described in the evidence JSON below.

Rules:
- Use the primitive function names from bind.primitives (e.g. harness_read32, harness_write32).
- Each register read is: var = primitive(base + offset);
- Each register write is: primitive(value, base + offset);
- Conditional branches become if/else blocks.
- Loops become for/while loops.
- Define a device private struct with the base pointer.
- Define stub implementations of all primitive functions (read/write 8/16/32-bit).
- Define a main() that creates a device instance and calls each module function in order.
- Add a trace printf after each read/write: printf("[trace %lu] R/W 0x%03lx = 0x%08x\n", trace_count++, offset, value);
- Include stdint.h and stdio.h.
- Add kernel macro stubs: BIT, GENMASK, etc.
- Use the register offsets from evidence.registers.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete C code in a single ```c code block.