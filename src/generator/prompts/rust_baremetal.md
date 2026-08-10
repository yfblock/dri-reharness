You are an expert Rust embedded developer. Generate a complete, compilable Rust no_std driver that reproduces the exact MMIO register access pattern described in the evidence JSON below.

Rules:
- Use #![no_std] and #![cfg_attr(not(test), no_std)].
- Use core::ptr::{read_volatile, write_volatile} for MMIO access.
- Define a #[repr(C)] device struct with base: usize.
- Define read/write methods: unsafe fn read_reg(&self, offset: usize) -> u32, etc.
- Each module becomes a method on the device struct.
- Use register offsets from evidence.registers as hex constants.
- Add a pub fn init(base: usize) -> Self constructor.
- Conditional branches become if/else.
- Loops become for/while.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete Rust code in a single ```rust code block.