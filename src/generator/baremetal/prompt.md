You are an expert embedded C programmer. Generate a complete, compilable freestanding C driver that reproduces the exact MMIO register access pattern described in the evidence JSON below.

Rules:
- Target: bare metal (no OS, freestanding). Use stdint.h types only.
- Use the primitive function names from bind.primitives (e.g. mmio_read32, mmio_write32).
- Each register read is: var = primitive(base + offset);
- Each register write is: primitive(value, base + offset);
- Conditional branches become if/else blocks.
- Define a device private struct with uintptr_t base.
- Define static inline mmio read/write helpers using volatile pointer dereference.
- Export one function per module, each taking a pointer to the device struct.
- No main() function - this is a library.
- Add #ifdef REHARNESS_BAREMETAL_ORACLE guard with a main() for testing.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete C code in a single ```c code block.