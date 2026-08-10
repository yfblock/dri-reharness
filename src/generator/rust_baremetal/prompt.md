You are an expert Rust embedded developer. Generate a complete, compilable Rust no_std driver that reproduces the exact MMIO register access pattern described in the evidence JSON below.

## Register Access: tock-registers

Use the tock-registers crate pattern for type-safe MMIO access. Do NOT use raw unsafe pointers (read_volatile/write_volatile). Instead define register maps using register_bitfields! and ReadOnly/ReadWrite/WriteOnly register types.

Include this prologue in every generated file:

    #![cfg_attr(not(test), no_std)]

    // tock-registers re-exports (inline minimal subset if crate is unavailable)
    #[cfg(not(feature = "tock-registers"))]
    mod tock_registers {
        use core::ptr::{read_volatile, write_volatile};
        pub trait RegisterLongName {}
        pub struct LocalRegisterCopy<T, R: RegisterLongName> { value: T, _reg: core::marker::PhantomData<R> }
        impl<T: Copy, R: RegisterLongName> LocalRegisterCopy<T, R> {
            pub fn new(v: T) -> Self { Self { value: v, _reg: core::marker::PhantomData } }
            pub fn get(&self) -> T { self.value }
        }
        pub struct ReadWrite<T: Copy, R: RegisterLongName> { address: *mut T, _reg: core::marker::PhantomData<R> }
        impl<T: Copy + core::ops::BitAnd<Output = T> + core::ops::BitOr<Output = T> + core::ops::Not<Output = T>, R: RegisterLongName> ReadWrite<T, R> {
            pub const fn new(addr: *mut T) -> Self { Self { address: addr, _reg: core::marker::PhantomData } }
            pub fn get(&self) -> T { unsafe { read_volatile(self.address) } }
            pub fn set(&self, value: T) { unsafe { write_volatile(self.address, value) } }
            pub fn read(&self) -> LocalRegisterCopy<T, R> { LocalRegisterCopy::new(self.get()) }
            pub fn write(&self, field: LocalRegisterCopy<T, R>) { self.set(field.get()); }
        }
        pub struct ReadOnly<T: Copy, R: RegisterLongName> { address: *const T, _reg: core::marker::PhantomData<R> }
        impl<T: Copy, R: RegisterLongName> ReadOnly<T, R> {
            pub const fn new(addr: *const T) -> Self { Self { address: addr, _reg: core::marker::PhantomData } }
            pub fn get(&self) -> T { unsafe { read_volatile(self.address) } }
            pub fn read(&self) -> LocalRegisterCopy<T, R> { LocalRegisterCopy::new(self.get()) }
        }
        pub struct WriteOnly<T: Copy, R: RegisterLongName> { address: *mut T, _reg: core::marker::PhantomData<R> }
        impl<T: Copy, R: RegisterLongName> WriteOnly<T, R> {
            pub const fn new(addr: *mut T) -> Self { Self { address: addr, _reg: core::marker::PhantomData } }
            pub fn set(&self, value: T) { unsafe { write_volatile(self.address, value) } }
        }
    }
    #[cfg(feature = "tock-registers")]
    use tock_registers::{
        registers::{ReadWrite, ReadOnly, WriteOnly, LocalRegisterCopy},
        register_bitfields,
    };

This provides a safe abstraction layer. When the tock-registers feature is enabled,
the real crate is used; otherwise the inline subset provides identical semantics.

## Register Layout

For each register in evidence.registers, define a RegisterLongName struct and a field in a #[repr(C)] register map struct. Example:

    #[repr(C)]
    struct EduRegisters {
        id: ReadOnly<u32, IdReg::Register>,       // offset 0x00
        _reserved0: [u8; 0x24 - 0x04],            // padding to next register
        irq_status: ReadOnly<u32, IrqStatus::Register>,  // offset 0x24
        _reserved1: [u8; 0x64 - 0x28],
        irq_ack: WriteOnly<u32, IrqAck::Register>,      // offset 0x64
    }

    struct IdReg; impl RegisterLongName for IdReg {}
    struct IrqStatus; impl RegisterLongName for IrqStatus {}
    struct IrqAck; impl RegisterLongName for IrqAck {}

Use ReadWrite for registers that are both read and written. Use ReadOnly for status/interrupt
registers that are only read. Use WriteOnly for acknowledge/command registers that are only written.
Use WriteOnly for write-1-to-clear (w1c) registers.

## Rules
- Use #![cfg_attr(not(test), no_std)].
- Define a #[repr(C)] register map struct with correct offsets and padding.
- Define a driver struct holding a pointer to the register map.
- pub fn new(base: *mut u8) -> Self constructor that casts base to &'static EduRegisters.
- Each module in evidence.modules becomes a safe method on the driver struct (no unsafe in public API).
- Register reads: self.regs.register_name.read().get()
- Register writes: self.regs.register_name.set(value)
- Conditional branches become if/else.
- Loops become for/while.
- Minimize use of unsafe: only in the constructor (casting raw pointer) and inside the inline fallback.
- Include #[derive(Clone, Copy)] on register field structs where appropriate.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete Rust code in a single ```rust code block.