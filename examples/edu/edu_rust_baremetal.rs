//! Auto-generated bare-metal Rust driver for edu (reharness)
#![allow(non_snake_case, non_camel_case_types, non_upper_case_globals, unused_variables, dead_code, unused_assignments)]
#![cfg_attr(not(test), no_std)]

use core::ptr::{read_volatile, write_volatile};

#[inline]
pub unsafe fn mmio_read32(addr: usize) -> u32 {
    read_volatile(addr as *const u32)
}
#[inline]
pub unsafe fn mmio_write32(val: u32, addr: usize) {
    write_volatile(addr as *mut u32, val);
}

#[inline]
pub unsafe fn mmio_read16(addr: usize) -> u16 {
    read_volatile(addr as *const u16)
}
#[inline]
pub unsafe fn mmio_write16(val: u16, addr: usize) {
    write_volatile(addr as *mut u16, val);
}

#[inline]
pub unsafe fn mmio_read8(addr: usize) -> u8 {
    read_volatile(addr as *const u8)
}
#[inline]
pub unsafe fn mmio_write8(val: u8, addr: usize) {
    write_volatile(addr as *mut u8, val);
}

#[inline]
pub unsafe fn mmio_read16_be(addr: usize) -> u16 {
    u16::from_be(read_volatile(addr as *const u16))
}
#[inline]
pub unsafe fn mmio_write16_be(val: u16, addr: usize) {
    write_volatile(addr as *mut u16, u16::to_be(val));
}
#[inline]
pub unsafe fn mmio_read32_be(addr: usize) -> u32 {
    u32::from_be(read_volatile(addr as *const u32))
}
#[inline]
pub unsafe fn mmio_write32_be(val: u32, addr: usize) {
    write_volatile(addr as *mut u32, u32::to_be(val));
}

#[inline]
pub unsafe fn mmio_write_w1c8(val: u8, addr: usize) {
    mmio_write8(val, addr);
}
#[inline]
pub unsafe fn mmio_write_w1c16(val: u16, addr: usize) {
    mmio_write16(val, addr);
}
#[inline]
pub unsafe fn mmio_write_w1c32(val: u32, addr: usize) {
    mmio_write32(val, addr);
}

#[inline]
pub fn reharness_delay_ns(ns: u32) { let _ = ns; }

pub const IO_ID: usize = 0x0;
pub const IO_IRQ_STATUS: usize = 0x24;
pub const IO_IRQ_ACK: usize = 0x64;

pub const CALL_EXPR: u32 = 0;
pub const Code: u32 = 0;
pub const Config: u32 = 0;
pub const Conservative: u32 = 0;
pub const Exact: u32 = 0;
pub const Fixed: u32 = 0;
pub const Interrupt: u32 = 0;
pub const Read: u32 = 0;
pub const Status: u32 = 0;
pub const Symbolic: u32 = 0;
pub const Var: u32 = 0;
pub const Write: u32 = 0;

#[repr(C)]
pub struct EduPriv {
    pub base: usize,
}

impl EduPriv {
    pub fn new(base: usize) -> Self {
        Self { base,
        }
    }
}

pub fn edu_irq_handler(irq: u32, dev: &mut EduPriv) {
    let mut status: u32 = 0;
    let base = dev.base;
    /* REHARNESS_RIS_OP id=op_1 kind=Read */
    let status: u32 = unsafe { mmio_read32(base + IO_IRQ_STATUS) };
    let _ = status;
    /* REHARNESS_RIS_OP id=op_2 kind=Write */
    unsafe { mmio_write32(status, base + IO_IRQ_ACK); }
}

pub fn edu_read(len: u32, dev: &mut EduPriv) {
    let mut val: u32 = 0;
    let base = dev.base;
    /* REHARNESS_RIS_OP id=op_3 kind=Read */
    let val: u32 = unsafe { mmio_read32(base + 0x0) };
    let _ = val;
}

pub fn edu_write(len: u32, dev: &mut EduPriv) {
    let val: u32 = 0;
    let base = dev.base;
    /* REHARNESS_RIS_OP id=op_4 kind=Write */
    unsafe { mmio_write32(val, base + 0x0); }
}

pub fn edu_pci_probe(dev: &mut EduPriv) {
    let mut dev_id: u32 = 0;
    let base = dev.base;
    /* REHARNESS_RIS_OP id=op_5 kind=Read */
    let dev_id: u32 = unsafe { mmio_read32(base + IO_ID) };
    let _ = dev_id;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_edu_driver() {
        let mut dev = EduPriv::new(0x1000_0000);
        unsafe { edu_pci_probe(&mut dev); }
    }
}
