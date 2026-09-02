pub type u32_0 = ::core::ffi::c_uint;
pub const IO_ID: ::core::ffi::c_int = 0 as ::core::ffi::c_int;
pub const IO_IRQ_STATUS: ::core::ffi::c_int = 0x24 as ::core::ffi::c_int;
pub const IO_IRQ_ACK: ::core::ffi::c_int = 0x64 as ::core::ffi::c_int;
static mut mmio: *mut u32_0 = ::core::ptr::null::<u32_0>() as *mut u32_0;
unsafe extern "C" fn readl_(mut a: *mut u32_0) -> u32_0 {
    return *a;
}
unsafe extern "C" fn writel_(mut v: u32_0, mut a: *mut u32_0) {
    ::core::ptr::write_volatile(a, v);
}
#[no_mangle]
pub unsafe extern "C" fn edu_read(mut off: ::core::ffi::c_ulong) -> u32_0 {
    let mut val: u32_0 = 0;
    match off {
        0 => {
            val = readl_(mmio.offset(IO_ID as isize));
        }
        36 => {
            val = readl_(mmio.offset(IO_IRQ_STATUS as isize));
        }
        _ => {
            val = 0 as u32_0;
        }
    }
    return val;
}
#[no_mangle]
pub unsafe extern "C" fn edu_write(mut off: ::core::ffi::c_ulong, mut v: u32_0) {
    match off {
        36 => {
            writel_(v, mmio.offset(IO_IRQ_ACK as isize));
        }
        152 => {
            writel_(v, mmio.offset(0x98 as ::core::ffi::c_int as isize));
        }
        _ => {}
    };
}
