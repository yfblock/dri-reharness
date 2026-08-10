You are an expert Rust embedded developer. Generate a complete, compilable Rust no_std driver that reproduces the exact MMIO register access pattern described in the evidence JSON below.

## Register Access: tock-registers

Use the tock-registers crate for type-safe MMIO access. Do NOT use raw unsafe pointers (read_volatile/write_volatile). Instead use tock_registers::registers::{ReadOnly, ReadWrite, WriteOnly} and register_bitfields! macro.

## Required Imports

    #![cfg_attr(not(test), no_std)]

    use tock_registers::{
        register_bitfields,
        register_structs,
        registers::{ReadOnly, ReadWrite, WriteOnly},
    };

## Register Layout

Use register_structs! to define a #[repr(C)] register map with correct offsets and padding. Example:

    register_structs! {
        pub EduRegisters {
            (0x000 => id: ReadOnly<u32, IdReg::Register>),
            (0x004 => _reserved0),
            (0x024 => irq_status: ReadOnly<u32, IrqStatus::Register>),
            (0x028 => _reserved1),
            (0x064 => irq_ack: WriteOnly<u32, IrqAck::Register>),
            (0x068 => @END),
        }
    }

    register_bitfields![u32,
        IdReg [],
        IrqStatus [],
        IrqAck [],
    ]

Use ReadWrite for registers that are both read and written. Use ReadOnly for status/interrupt
registers that are only read. Use WriteOnly for acknowledge/command registers that are only written.

## Rules
- Use #![cfg_attr(not(test), no_std)].
- Use register_structs! macro for the register map layout.
- Use register_bitfields! macro to define register field types.
- Define a driver struct holding a pointer to the register map.
- pub fn new(base: *mut u8) -> Self constructor that casts base to &EduRegisters.
- Each module in evidence.modules becomes a safe method on the driver struct (no unsafe in public API).
- Register reads: self.regs.register_name.get() or self.regs.register_name.read()
- Register writes: self.regs.register_name.set(value)
- Conditional branches become if/else.
- Loops become for/while.
- Minimize use of unsafe: only in the constructor (casting raw pointer).

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete Rust code in a single ```rust code block.