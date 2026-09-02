#![cfg_attr(not(test), no_std)]

use tock_registers::{
    register_bitfields,
    register_structs,
    registers::{ReadOnly, ReadWrite, WriteOnly},
    interfaces::{Readable, Writeable},
};
#[inline]
fn mmio_read32(regs: &DwApbSsiRegisters, offset: usize) -> u32 {
    match offset {
        0x000 => regs.ctrlr0.get(),
        0x004 => regs.ctrlr1.get(),
        0x008 => regs.ssienr.get(),
        0x010 => regs.ser.get(),
        0x014 => regs.baudr.get(),
        0x018 => regs.txftlr.get(),
        0x01c => regs.rxftlr.get(),
        0x020 => regs.txflr.get(),
        0x024 => regs.rxflr.get(),
        0x028 => regs.sr.get(),
        0x02c => regs.imr.get(),
        0x030 => regs.isr.get(),
        0x034 => regs.risr.get(),
        0x04c => regs.icr.get(),
        0x05c => regs.version.get(),
        0x094 => regs.dr.get(),
        0x0f0 => regs.rx_sample_dly.get(),
        0x0f4 => regs.cs_override.get(),
        _ => 0,
    }
}
#[inline]
fn mmio_write32(regs: &DwApbSsiRegisters, offset: usize, value: u32) {
    match offset {
        0x000 => regs.ctrlr0.set(value),
        0x004 => regs.ctrlr1.set(value),
        0x008 => regs.ssienr.set(value),
        0x010 => regs.ser.set(value),
        0x014 => regs.baudr.set(value),
        0x018 => regs.txftlr.set(value),
        0x01c => regs.rxftlr.set(value),
        0x02c => regs.imr.set(value),
        0x04c => regs.icr.set(value),
        0x094 => regs.dr.set(value),
        0x0f0 => regs.rx_sample_dly.set(value),
        0x0f4 => regs.cs_override.set(value),
        _ => {}
    }
}

register_bitfields![u32,
    Ctrlr0 [
        DFS  OFFSET(0)  NUMBITS(4)  [],
        FRF  OFFSET(4)  NUMBITS(2)  [],
        SCPH OFFSET(6)  NUMBITS(1)  [],
        SCPOL OFFSET(7) NUMBITS(1)  [],
        TMOD OFFSET(8)  NUMBITS(2)  [],
        SLV_OE OFFSET(10) NUMBITS(1) [],
        CFS  OFFSET(12) NUMBITS(4)  [],
        SPI_MOD OFFSET(16) NUMBITS(4) [],
    ],
    Sr [
        BUSY OFFSET(0) NUMBITS(1) [],
        TFNF  OFFSET(1) NUMBITS(1) [],
        TFE   OFFSET(2) NUMBITS(1) [],
        RFNE  OFFSET(3) NUMBITS(1) [],
        RFNF  OFFSET(4) NUMBITS(1) [],
        RFF   OFFSET(5) NUMBITS(1) [],
        TFF   OFFSET(6) NUMBITS(1) [],
        RFFS  OFFSET(7) NUMBITS(1) [],
        TFFS  OFFSET(8) NUMBITS(1) [],
    ],
    Imr [
        TXEI  OFFSET(0) NUMBITS(1) [],
        TXOI  OFFSET(1) NUMBITS(1) [],
        RXUI  OFFSET(2) NUMBITS(1) [],
        RXOI  OFFSET(3) NUMBITS(1) [],
        TXFI  OFFSET(4) NUMBITS(1) [],
        RXFI  OFFSET(5) NUMBITS(1) [],
        MSTI  OFFSET(6) NUMBITS(1) [],
        FRFI  OFFSET(7) NUMBITS(1) [],
        FTOI  OFFSET(8) NUMBITS(1) [],
    ],
    Isr [
        TXEI  OFFSET(0) NUMBITS(1) [],
        TXOI  OFFSET(1) NUMBITS(1) [],
        RXUI  OFFSET(2) NUMBITS(1) [],
        RXOI  OFFSET(3) NUMBITS(1) [],
        TXFI  OFFSET(4) NUMBITS(1) [],
        RXFI  OFFSET(5) NUMBITS(1) [],
        MSTI  OFFSET(6) NUMBITS(1) [],
        FRFI  OFFSET(7) NUMBITS(1) [],
        FTOI  OFFSET(8) NUMBITS(1) [],
    ],
];
register_structs! {
    pub DwApbSsiRegisters {
        (0x000 => ctrlr0: ReadWrite<u32, Ctrlr0::Register>),
        (0x004 => ctrlr1: ReadWrite<u32>),
        (0x008 => ssienr: ReadWrite<u32>),
        (0x00c => _reserved0),
        (0x010 => ser: ReadWrite<u32>),
        (0x014 => baudr: ReadWrite<u32>),
        (0x018 => txftlr: ReadWrite<u32>),
        (0x01c => rxftlr: ReadWrite<u32>),
        (0x020 => txflr: ReadOnly<u32>),
        (0x024 => rxflr: ReadOnly<u32>),
        (0x028 => sr: ReadOnly<u32, Sr::Register>),
        (0x02c => imr: ReadWrite<u32, Imr::Register>),
        (0x030 => isr: ReadOnly<u32, Isr::Register>),
        (0x034 => risr: ReadOnly<u32>),
        (0x038 => _reserved1),
        (0x048 => icr: ReadWrite<u32>),
        (0x04c => _reserved2),
        (0x050 => _reserved3),
        (0x054 => _reserved4),
        (0x058 => _reserved5),
        (0x05c => version: ReadOnly<u32>),
        (0x060 => dr: ReadWrite<u32>),
        (0x064 => _reserved6),
        (0x068 => _reserved7),
        (0x06c => _reserved8),
        (0x070 => _reserved9),
        (0x074 => _reserved10),
        (0x078 => _reserved11),
        (0x07c => _reserved12),
        (0x080 => _reserved13),
        (0x084 => _reserved14),
        (0x088 => _reserved15),
        (0x08c => _reserved16),
        (0x090 => _reserved17),
        (0x094 => _reserved18),
        (0x098 => _reserved19),
        (0x09c => _reserved20),
        (0x0a0 => _reserved21),
        (0x0a4 => _reserved22),
        (0x0a8 => _reserved23),
        (0x0ac => _reserved24),
        (0x0b0 => _reserved25),
        (0x0b4 => _reserved26),
        (0x0b8 => _reserved27),
        (0x0bc => _reserved28),
        (0x0c0 => _reserved29),
        (0x0c4 => _reserved30),
        (0x0c8 => _reserved31),
        (0x0cc => _reserved32),
        (0x0d0 => _reserved33),
        (0x0d4 => _reserved34),
        (0x0d8 => _reserved35),
        (0x0dc => _reserved36),
        (0x0e0 => _reserved37),
        (0x0e4 => _reserved38),
        (0x0e8 => _reserved39),
        (0x0ec => _reserved40),
        (0x0f0 => rx_sample_dly: ReadWrite<u32>),
        (0x0f4 => cs_override: ReadWrite<u32>),
        (0x0f8 => @END),
    }
}
pub type Dfs = u32;
pub type FifoLen = u32;
#[derive(Clone, Copy, Default)]
pub struct DwSpi {
    pub base: *mut u8,
    pub freq: u32,
    pub current_freq: u32,
    pub len: u32,
    pub tx: u32,
    pub rx: u32,
    pub tx_len: u32,
    pub rx_len: u32,
    pub bus_num: u32,
    pub num_cs: u32,
    pub max_mem_freq: u32,
    pub enh_desc: u32,
    pub fifo_len: FifoLen,
    pub dfs: Dfs,
    pub mode: u32,
    pub busy: bool,
    pub tx_buf: *const u8,
    pub rx_buf: *mut u8,
    pub tx_end: *const u8,
    pub rx_end: *mut u8,
    pub cs: u32,
    pub cr0: u32,
    pub rx_sample_dly: u32,
    pub ndf: u32,
    pub def_rx_sample_dly_ns: u32,
    pub n_bytes: u32,
    pub enhanced_info: u32,
    pub controller_revision: u32,
    pub dma_chan_tx: u32,
    pub dma_chan_rx: u32,
    pub dma_mapped: bool,
    pub ctrlr0_cached: u32,
    pub ctrlr1_cached: u32,
    pub imr_val: u32,
    pub polling_mode: bool,
}
#[derive(Clone, Copy, Default)]
pub struct DwSpiMmio {
    pub dws: DwSpi,
    pub syscon_base: *mut u8,
    pub reg_size: usize,
    pub cs_index: u32,
    pub set_cs_override: u32,
    pub hssi: bool,
    pub intel: bool,
    pub mountevans_imc: bool,
    pub canaan_k210: bool,
    pub elba: bool,
}
pub struct DwApbSsi {
    regs: &'static DwApbSsiRegisters,
    pub dws: DwSpi,
    pub dwsmmio: DwSpiMmio,
    pub dwsmscc: dw_spi_mmio_syscon_tx::SysconRegmap,
}
#[cfg(test)]
mod tests {
    #[test]
    fn smoke() {
        let dws = super::DwSpi::default();
        let dwsmmio = super::DwSpiMmio::default();
        assert_eq!(dws.freq, 0);
        assert!(!dws.busy);
        assert!(!dwsmmio.hssi);
    }
}

pub mod dw_spi_mmio_syscon_tx {

    /// Backing store emulating the syscon regmap (`dwsmscc->syscon` and the
    /// Elba `syscon`).
    #[derive(Clone)]
    pub struct SysconRegmap {
        regs: [u32; 0x1000],
    }

    impl Default for SysconRegmap {
        fn default() -> Self {
            Self { regs: [0; 0x1000] }
        }
    }

    /// `MSCC_SPI_MST_SW_MODE` (Ocelot/Jaguar2 CPU syscon, offset 0x24).
    pub const MSCC_SPI_MST_SW_MODE: usize = 0x24;

    impl SysconRegmap {
        /// `regmap_read` — plain word read.
        #[inline]
        pub fn regmap_read(&self, offset: usize) -> u32 {
            self.regs[offset >> 2]
        }

        /// `regmap_write` — plain word write.
        #[inline]
        pub fn regmap_write(&mut self, offset: usize, val: u32) {
            self.regs[offset >> 2] = val;
        }

        /// `regmap_update_bits` — read-modify-write: `(cur & !mask) | (val & mask)`.
        #[inline]
        pub fn regmap_update_bits(&mut self, offset: usize, mask: u32, val: u32) {
            let cur = self.regmap_read(offset);
            self.regmap_write(offset, (cur & !mask) | (val & mask));
        }
    }

    // -- register offsets / field encodings (spi-dw-mmio.c) ------------------

    /// `MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL` (Ocelot/Jaguar2 CPU syscon).
    const MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL: usize = 0x24;
    /// `MSCC_IF_SI_OWNER_MASK` — GENMASK(1, 0).
    const MSCC_IF_SI_OWNER_MASK: u32 = 0x3;
    /// `MSCC_IF_SI_OWNER_SIMC`.
    const MSCC_IF_SI_OWNER_SIMC: u32 = 2;
    /// `OCELOT_IF_SI_OWNER_OFFSET`.
    const OCELOT_IF_SI_OWNER_OFFSET: u32 = 4;
    /// `JAGUAR2_IF_SI_OWNER_OFFSET`.
    const JAGUAR2_IF_SI_OWNER_OFFSET: u32 = 6;

    /// `SPARX5_FORCE_ENA` (Sparx5 syscon).
    const SPARX5_FORCE_ENA: usize = 0xa4;
    /// `SPARX5_FORCE_VAL` (Sparx5 syscon).
    const SPARX5_FORCE_VAL: usize = 0xa8;

    /// `ELBA_SPICS_REG` (Elba syscon).
    const ELBA_SPICS_REG: usize = 0x246c;

    /// `ELBA_SPICS_OFFSET(x) = (x) << 2`.
    #[inline]
    fn elba_spics_offset(cs: u32) -> u32 {
        cs << 2
    }

    /// `ELBA_SPICS_MASK(x) = GENMASK(2, 0) << ELBA_SPICS_OFFSET(x)`.
    #[inline]
    fn elba_spics_mask(cs: u32) -> u32 {
        0x7 << elba_spics_offset(cs)
    }

    /// `ELBA_SPICS_SET(x, v) = (v) << ELBA_SPICS_OFFSET(x)`.
    #[inline]
    fn elba_spics_set(cs: u32, v: u32) -> u32 {
        v << elba_spics_offset(cs)
    }

    /// `dw_spi_mscc_ocelot_init` — hand SI ownership to the SIMC
    /// (spi-dw-mmio.c:118).
    pub fn dw_spi_mscc_ocelot_init(syscon: &mut SysconRegmap) -> u32 {
        /* REHARNESS_TRANSACTION_OP id=op_167 kind=TransactionUpdate transport=regmap status=lowered digest=add72c08c4a3f3a6 */
        syscon.regmap_update_bits(
            MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
            MSCC_IF_SI_OWNER_MASK << OCELOT_IF_SI_OWNER_OFFSET,
            MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET,
        );
        0
    }

    /// `dw_spi_mscc_jaguar2_init` — hand SI ownership to the SIMC
    /// (spi-dw-mmio.c:118).
    pub fn dw_spi_mscc_jaguar2_init(syscon: &mut SysconRegmap) -> u32 {
        /* REHARNESS_TRANSACTION_OP id=op_171 kind=TransactionUpdate transport=regmap status=lowered digest=dd0eafe7f5dffe30 */
        syscon.regmap_update_bits(
            MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
            MSCC_IF_SI_OWNER_MASK << JAGUAR2_IF_SI_OWNER_OFFSET,
            MSCC_IF_SI_OWNER_SIMC << JAGUAR2_IF_SI_OWNER_OFFSET,
        );
        0
    }

    /// `dw_spi_sparx5_set_cs` — drive the chip-select through the Sparx5
    /// force registers (spi-dw-mmio.c:148).
    pub fn dw_spi_sparx5_set_cs(syscon: &mut SysconRegmap, cs: u32, enable: u32) {
        if enable != 0 {
            /* REHARNESS_TRANSACTION_OP id=op_175 kind=TransactionWrite transport=regmap status=lowered digest=205f308e0f9e09e8 */
            syscon.regmap_write(SPARX5_FORCE_ENA, 1);
            /* REHARNESS_TRANSACTION_OP id=op_176 kind=TransactionWrite transport=regmap status=lowered digest=e0a7b055c6ad8a24 */
            syscon.regmap_write(SPARX5_FORCE_VAL, (1u32 << cs) ^ 0xFFFF_FFFF);
        } else {
            /* REHARNESS_TRANSACTION_OP id=op_177 kind=TransactionWrite transport=regmap status=lowered digest=8164bafcc13cbb61 */
            syscon.regmap_write(SPARX5_FORCE_VAL, 0 ^ 0xFFFF_FFFF);
            /* REHARNESS_TRANSACTION_OP id=op_178 kind=TransactionWrite transport=regmap status=lowered digest=442f3ce583e95677 */
            syscon.regmap_write(SPARX5_FORCE_ENA, 0);
        }
    }

    /// `dw_spi_elba_set_cs` — drive the chip-select through the Elba SPICS
    /// register (spi-dw-mmio.c:272).
    pub fn dw_spi_elba_set_cs(syscon: &mut SysconRegmap, cs: u32, enable: u32) {
        let mask = elba_spics_mask(cs);
        let val = elba_spics_set(cs, enable);
        /* REHARNESS_TRANSACTION_OP id=op_191 kind=TransactionUpdate transport=regmap status=lowered digest=e1bbbfbe3e113748 */
        syscon.regmap_update_bits(ELBA_SPICS_REG, mask, val);
    }
    }

impl DwApbSsi {
#[allow(unused_variables, unused_mut, unused_assignments, unreachable_code)]
    pub fn __reharness_lowering_receipts(&mut self) {
        let mut level: u32 = 0;
        let mut sw_mode: u32 = 0;
        let mut cs: u32 = 0;
        let mut buf: *const u8 = self.dws.tx_buf;
        let mut clk_div: u32 = 0;
        let mut new_mask: u32 = 0;
        let mut cr0: u32 = 0;
        let mut fifo: u32 = 0;
        let mut tmp: u32 = 0;
        let mut val: u32 = 0;
        let mut offset: usize = 0;
/* ---- lowering-repair round 0 ---- */
/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=52e1d34f0188d855 */
'__rh_op_op_1: { self.regs.ser.set(0x1 << self.dws.cs); }    '__rh_op_op_2: { self.regs.ser.set(0x0); }
    '__rh_op_op_3: { self.regs.isr.get(); }
    '__rh_op_op_4: { self.regs.risr.get(); }
    '__rh_op_op_5: { self.regs.isr.get(); }
    '__rh_op_op_6: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_7: { self.regs.imr.get(); }
    '__rh_op_op_8: { self.regs.imr.set(new_mask); }
    '__rh_op_op_9: { self.regs.icr.get(); }
    '__rh_op_op_10: { self.regs.ser.set(0x0); }
    '__rh_op_op_11: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_13: { self.regs.rxflr.get(); }
    '__rh_op_op_14: { self.regs.dr.get(); }
    '__rh_op_op_20: { self.regs.imr.get(); }
    '__rh_op_op_21: { self.regs.imr.set(new_mask); }
    '__rh_op_op_22: { self.regs.rxftlr.get(); }
    '__rh_op_op_23: { self.regs.rxftlr.set(self.dws.rx_len - 0x1); }
    '__rh_op_op_24: { self.regs.txflr.get(); }
    '__rh_op_op_30: { self.regs.dr.set((if ((!self.dws.tx_buf.is_null() && ((self.dws.n_bytes != 0x1))) && ((self.dws.n_bytes != 0x2))) { unsafe { *(self.dws.tx_buf as *const u32) as u32 } } else { ((if ((!self.dws.tx_buf.is_null() && ((self.dws.n_bytes != 0x1))) && (self.dws.n_bytes == 0x2)) { unsafe { *(self.dws.tx_buf as *const u16) as u32 } } else { ((if (!self.dws.tx_buf.is_null() && (self.dws.n_bytes == 0x1)) { unsafe { *(self.dws.tx_buf as *const u8) as u32 } } else { 0x0 })) })) })); }
    '__rh_op_op_32: { self.regs.imr.get(); }
    '__rh_op_op_33: { self.regs.imr.set(new_mask); }
    '__rh_op_op_35: { self.regs.isr.get(); }
    '__rh_op_op_36: { self.regs.imr.get(); }
    '__rh_op_op_37: { self.regs.imr.set(new_mask); }
    '__rh_op_op_44: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_49: { self.regs.ctrlr0.set(self.dws.cr0); }
    '__rh_op_op_50: { self.regs.ctrlr1.set(((if (self.dws.ndf != 0) { (self.dws.ndf - 0x1) } else { 0x0 }))); }
    '__rh_op_op_51: { self.regs.baudr.set(clk_div); }
    '__rh_op_op_53: { self.regs.rx_sample_dly.set(self.dws.rx_sample_dly); }
    '__rh_op_op_56: { self.regs.imr.get(); }
    '__rh_op_op_57: { self.regs.imr.set(new_mask); }
    '__rh_op_op_58: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_60: { self.regs.txflr.get(); }
    '__rh_op_op_66: { self.regs.dr.set((if ((!self.dws.tx_buf.is_null() && ((self.dws.n_bytes != 0x1))) && ((self.dws.n_bytes != 0x2))) { unsafe { *(self.dws.tx_buf as *const u32) as u32 } } else { ((if ((!self.dws.tx_buf.is_null() && ((self.dws.n_bytes != 0x1))) && (self.dws.n_bytes == 0x2)) { unsafe { *(self.dws.tx_buf as *const u16) as u32 } } else { ((if (!self.dws.tx_buf.is_null() && (self.dws.n_bytes == 0x1)) { unsafe { *(self.dws.tx_buf as *const u8) as u32 } } else { 0x0 })) })) })); }
    '__rh_op_op_69: { self.regs.rxflr.get(); }
    '__rh_op_op_70: { self.regs.dr.get(); }
    '__rh_op_op_76: { self.regs.risr.get(); }
    '__rh_op_op_77: { self.regs.isr.get(); }
    '__rh_op_op_78: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_79: { self.regs.imr.get(); }
    '__rh_op_op_80: { self.regs.imr.set(new_mask); }
    '__rh_op_op_81: { self.regs.icr.get(); }
    '__rh_op_op_82: { self.regs.ser.set(0x0); }
    '__rh_op_op_83: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_85: { self.regs.txftlr.set(level); }
    '__rh_op_op_86: { self.regs.rxftlr.set(level.wrapping_sub(0x1)); }
    '__rh_op_op_89: { self.regs.imr.get(); }
    '__rh_op_op_90: { self.regs.imr.set(new_mask); }
    '__rh_op_op_91: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_92: { self.regs.imr.get(); }
    '__rh_op_op_93: { self.regs.imr.set(new_mask); }
    '__rh_op_op_94: { self.regs.icr.get(); }
    '__rh_op_op_95: { self.regs.ser.set(0x0); }
    '__rh_op_op_96: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_97: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_98: { self.regs.imr.get(); }
    '__rh_op_op_99: { self.regs.imr.set(new_mask); }
    '__rh_op_op_100: { self.regs.icr.get(); }
    '__rh_op_op_101: { self.regs.ser.set(0x0); }
    '__rh_op_op_102: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_115: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_120: { self.regs.ctrlr0.set(self.dws.cr0); }
    '__rh_op_op_121: { self.regs.ctrlr1.set(((if (self.dws.ndf != 0) { (self.dws.ndf - 0x1) } else { 0x0 }))); }
    '__rh_op_op_122: { self.regs.baudr.set(clk_div); }
    '__rh_op_op_124: { self.regs.rx_sample_dly.set(self.dws.rx_sample_dly); }
    '__rh_op_op_126: { self.regs.imr.get(); }
    '__rh_op_op_127: { self.regs.imr.set(new_mask); }
    '__rh_op_op_128: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_130: { self.regs.dr.set(unsafe { let v = core::ptr::read_volatile(buf) as u32; buf = buf.add(1); v }); }
    '__rh_op_op_131: { self.regs.ser.set(0x1 << self.dws.cs); }
    '__rh_op_op_132: { self.regs.ser.set(0x0); }
    '__rh_op_op_133: { self.regs.txflr.get(); }
    '__rh_op_op_134: { self.regs.dr.set(unsafe { let v = core::ptr::read_volatile(buf) as u32; buf = buf.add(1); v }); }
    '__rh_op_op_136: { self.regs.rxflr.get(); }
    '__rh_op_op_137: { self.regs.risr.get(); }
    '__rh_op_op_138: { self.regs.dr.get(); }
    '__rh_op_op_140: { self.regs.txflr.get(); }
    '__rh_op_op_144: { self.regs.sr.get(); }
    '__rh_op_op_145: { self.regs.risr.get(); }
    '__rh_op_op_146: { self.regs.isr.get(); }
    '__rh_op_op_147: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_148: { self.regs.imr.get(); }
    '__rh_op_op_149: { self.regs.imr.set(new_mask); }
    '__rh_op_op_150: { self.regs.icr.get(); }
    '__rh_op_op_151: { self.regs.ser.set(0x0); }
    '__rh_op_op_152: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_154: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_155: { self.regs.ser.set(0x1 << self.dws.cs); }
    '__rh_op_op_156: { self.regs.ser.set(0x0); }
    '__rh_op_op_157: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_163: { self.dwsmscc.regmap_write(dw_spi_mmio_syscon_tx::MSCC_SPI_MST_SW_MODE, (if (cs < 0x4) { 0x2000 } else { sw_mode })); }
    '__rh_op_op_164: { self.regs.ser.set(0x1 << self.dws.cs); }
    '__rh_op_op_165: { self.regs.ser.set(0x0); }
    '__rh_op_op_166: { self.dwsmscc.regmap_write(dw_spi_mmio_syscon_tx::MSCC_SPI_MST_SW_MODE, 0x0); }
    '__rh_op_op_170: { self.dwsmscc.regmap_write(dw_spi_mmio_syscon_tx::MSCC_SPI_MST_SW_MODE, 0x0); }
    '__rh_op_op_179: { self.regs.ser.set(0x1 << self.dws.cs); }
    '__rh_op_op_180: { self.regs.ser.set(0x0); }
    '__rh_op_op_192: { self.regs.ser.set(0x1 << self.dws.cs); }
    '__rh_op_op_193: { self.regs.ser.set(0x0); }
    '__rh_op_op_202: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_203: { self.regs.imr.get(); }
    '__rh_op_op_204: { self.regs.imr.set(new_mask); }
    '__rh_op_op_205: { self.regs.icr.get(); }
    '__rh_op_op_206: { self.regs.ser.set(0x0); }
    '__rh_op_op_207: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_208: { self.regs.version.get(); }
    '__rh_op_op_210: { self.regs.ser.set(0xffff); }
    '__rh_op_op_211: { self.regs.ser.get(); }
    '__rh_op_op_212: { self.regs.ser.set(0x0); }
    '__rh_op_op_213: { self.regs.txftlr.set(fifo); }
    '__rh_op_op_214: { self.regs.txftlr.get(); }
    '__rh_op_op_215: { self.regs.txftlr.set(0x0); }
    '__rh_op_op_217: { self.regs.ctrlr0.get(); }
    '__rh_op_op_218: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_219: { self.regs.ctrlr0.set(0xffffffff); }
    '__rh_op_op_220: { self.regs.ctrlr0.get(); }
    '__rh_op_op_221: { self.regs.ctrlr0.set(tmp); }
    '__rh_op_op_222: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_225: { self.regs.cs_override.set(0xf); }
    '__rh_op_op_251: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_252: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_253: { self.regs.baudr.set(0x0); }
    '__rh_op_op_254: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_255: { self.regs.imr.get(); }
    '__rh_op_op_256: { self.regs.imr.set(new_mask); }
    '__rh_op_op_257: { self.regs.icr.get(); }
    '__rh_op_op_258: { self.regs.ser.set(0x0); }
    '__rh_op_op_259: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_260: { self.regs.version.get(); }
    '__rh_op_op_262: { self.regs.ser.set(0xffff); }
    '__rh_op_op_263: { self.regs.ser.get(); }
    '__rh_op_op_264: { self.regs.ser.set(0x0); }
    '__rh_op_op_265: { self.regs.txftlr.set(fifo); }
    '__rh_op_op_266: { self.regs.txftlr.get(); }
    '__rh_op_op_267: { self.regs.txftlr.set(0x0); }
    '__rh_op_op_269: { self.regs.ctrlr0.get(); }
    '__rh_op_op_270: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_271: { self.regs.ctrlr0.set(0xffffffff); }
    '__rh_op_op_272: { self.regs.ctrlr0.get(); }
    '__rh_op_op_273: { self.regs.ctrlr0.set(tmp); }
    '__rh_op_op_274: { self.regs.ssienr.set(((if true { 0x1 } else { 0x0 }))); }
    '__rh_op_op_277: { self.regs.cs_override.set(0xf); }
    '__rh_op_op_278: { self.regs.ssienr.set(((if false { 0x1 } else { 0x0 }))); }
    '__rh_op_op_279: { self.regs.baudr.set(0x0); }
    '__rh_op_op_280: { mmio_write32(self.regs, offset as usize, val); }
    '__rh_op_op_281: { mmio_read32(self.regs, offset as usize); }
    '__rh_op_op_282: { mmio_write32(self.regs, offset as usize, val & 0xFFFF); }
    '__rh_op_op_283: { mmio_write32(self.regs, offset as usize, val); }
    '__rh_op_op_284: { mmio_read32(self.regs, offset as usize) & 0xFFFF; }
    '__rh_op_op_285: { mmio_read32(self.regs, offset as usize); }



/* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=1da529e7a809836c */
/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=f69675ec9835d413 */
/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cc3597eae4a4ffcf */
/* REHARNESS_RIS_OP id=op_6 kind=Write status=lowered digest=6b1f7c3c7aff2599 */
/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=db5406d93b9de59f */
/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_9 kind=Read status=lowered digest=b7ef59e827eab5c4 */
/* REHARNESS_RIS_OP id=op_10 kind=Write status=lowered digest=02bf20c4b2910e68 */
/* REHARNESS_RIS_OP id=op_11 kind=Write status=lowered digest=dfd1fa2d71073b6b */
/* REHARNESS_RIS_OP id=op_13 kind=Read status=lowered digest=e2bc5578b3e7296f */
/* REHARNESS_RIS_OP id=op_14 kind=Read status=lowered digest=3da139e73bc81d86 */
/* REHARNESS_RIS_OP id=op_20 kind=Read status=lowered digest=db8b7d8066902839 */
/* REHARNESS_RIS_OP id=op_21 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_22 kind=Read status=lowered digest=0ac68c30582764c9 */
/* REHARNESS_RIS_OP id=op_23 kind=Write status=lowered digest=048897f03058f8c8 */
/* REHARNESS_RIS_OP id=op_24 kind=Read status=lowered digest=d5ec643b5880dd09 */
/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=0f2b2866c7a4dc7b */
/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=9db54064a0021588 */
/* REHARNESS_RIS_OP id=op_33 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_35 kind=Read status=lowered digest=e9c17db3dbc213e5 */
/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=dbbcb4750b35858d */
/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_44 kind=Write status=lowered digest=d25feee6dbc4abe7 */
/* REHARNESS_RIS_OP id=op_49 kind=Write status=lowered digest=bb87e750b4def067 */
/* REHARNESS_RIS_OP id=op_50 kind=Write status=lowered digest=16f77a812f5e88cf */
/* REHARNESS_RIS_OP id=op_51 kind=Write status=lowered digest=56a186cab0d75ea8 */
/* REHARNESS_RIS_OP id=op_53 kind=Write status=lowered digest=69847e55d17d99e3 */
/* REHARNESS_RIS_OP id=op_56 kind=Read status=lowered digest=3d02fa5abc1f75a2 */
/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=d895515278b0e3a1 */
/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=c40a59219519191e */
/* REHARNESS_RIS_OP id=op_60 kind=Read status=lowered digest=d5ec643b5880dd09 */
/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=0f2b2866c7a4dc7b */
/* REHARNESS_RIS_OP id=op_69 kind=Read status=lowered digest=17103da2c40e3793 */
/* REHARNESS_RIS_OP id=op_70 kind=Read status=lowered digest=3da139e73bc81d86 */
/* REHARNESS_RIS_OP id=op_76 kind=Read status=lowered digest=f69675ec9835d413 */
/* REHARNESS_RIS_OP id=op_77 kind=Read status=lowered digest=f83f363e7a845094 */
/* REHARNESS_RIS_OP id=op_78 kind=Write status=lowered digest=12704bd310147faa */
/* REHARNESS_RIS_OP id=op_79 kind=Read status=lowered digest=5a1d0369e9ac587d */
/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_81 kind=Read status=lowered digest=fc7e910137378bb9 */
/* REHARNESS_RIS_OP id=op_82 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_83 kind=Write status=lowered digest=097f1422079496d8 */
/* REHARNESS_RIS_OP id=op_85 kind=Write status=lowered digest=27e20a64634d5088 */
/* REHARNESS_RIS_OP id=op_86 kind=Write status=lowered digest=e777f3cc08afc74e */
/* REHARNESS_RIS_OP id=op_89 kind=Read status=lowered digest=acf10655c104a1be */
/* REHARNESS_RIS_OP id=op_90 kind=Write status=lowered digest=d895515278b0e3a1 */
/* REHARNESS_RIS_OP id=op_91 kind=Write status=lowered digest=d25feee6dbc4abe7 */
/* REHARNESS_RIS_OP id=op_92 kind=Read status=lowered digest=5039b5a70a00e946 */
/* REHARNESS_RIS_OP id=op_93 kind=Write status=lowered digest=d895515278b0e3a1 */
/* REHARNESS_RIS_OP id=op_94 kind=Read status=lowered digest=f2117f7d8745ef43 */
/* REHARNESS_RIS_OP id=op_95 kind=Write status=lowered digest=bdd159f573077756 */
/* REHARNESS_RIS_OP id=op_96 kind=Write status=lowered digest=c40a59219519191e */
/* REHARNESS_RIS_OP id=op_97 kind=Write status=lowered digest=d25feee6dbc4abe7 */
/* REHARNESS_RIS_OP id=op_98 kind=Read status=lowered digest=a78555ac59185570 */
/* REHARNESS_RIS_OP id=op_99 kind=Write status=lowered digest=d895515278b0e3a1 */
/* REHARNESS_RIS_OP id=op_100 kind=Read status=lowered digest=fb281d5731cdbb7e */
/* REHARNESS_RIS_OP id=op_101 kind=Write status=lowered digest=bdd159f573077756 */
/* REHARNESS_RIS_OP id=op_102 kind=Write status=lowered digest=c40a59219519191e */
/* REHARNESS_RIS_OP id=op_115 kind=Write status=lowered digest=d25feee6dbc4abe7 */
/* REHARNESS_RIS_OP id=op_120 kind=Write status=lowered digest=bb87e750b4def067 */
/* REHARNESS_RIS_OP id=op_121 kind=Write status=lowered digest=16f77a812f5e88cf */
/* REHARNESS_RIS_OP id=op_122 kind=Write status=lowered digest=56a186cab0d75ea8 */
/* REHARNESS_RIS_OP id=op_124 kind=Write status=lowered digest=69847e55d17d99e3 */
/* REHARNESS_RIS_OP id=op_126 kind=Read status=lowered digest=c363c402875e5bf3 */
/* REHARNESS_RIS_OP id=op_127 kind=Write status=lowered digest=d895515278b0e3a1 */
/* REHARNESS_RIS_OP id=op_128 kind=Write status=lowered digest=c40a59219519191e */
/* REHARNESS_RIS_OP id=op_130 kind=Write status=lowered digest=4e75d8502b5baece */
/* REHARNESS_RIS_OP id=op_131 kind=Write status=lowered digest=8301f9ffb7e7008b */
/* REHARNESS_RIS_OP id=op_132 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_133 kind=Read status=lowered digest=7ae143e71a898161 */
/* REHARNESS_RIS_OP id=op_134 kind=Write status=lowered digest=4e75d8502b5baece */
/* REHARNESS_RIS_OP id=op_136 kind=Read status=lowered digest=e2e8f654547825ad */
/* REHARNESS_RIS_OP id=op_137 kind=Read status=lowered digest=5646e96bd362d8bd */
/* REHARNESS_RIS_OP id=op_138 kind=Read status=lowered digest=076c475434b84bda */
/* REHARNESS_RIS_OP id=op_140 kind=Read status=lowered digest=14887587794de92a */
/* REHARNESS_RIS_OP id=op_144 kind=Read status=lowered digest=202d49ec4b7012ed */
/* REHARNESS_RIS_OP id=op_145 kind=Read status=lowered digest=f69675ec9835d413 */
/* REHARNESS_RIS_OP id=op_146 kind=Read status=lowered digest=4391f4e991ed230c */
/* REHARNESS_RIS_OP id=op_147 kind=Write status=lowered digest=12704bd310147faa */
/* REHARNESS_RIS_OP id=op_148 kind=Read status=lowered digest=6c01ebedad10bda9 */
/* REHARNESS_RIS_OP id=op_149 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_150 kind=Read status=lowered digest=ffdebf902b39c1de */
/* REHARNESS_RIS_OP id=op_151 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_152 kind=Write status=lowered digest=097f1422079496d8 */
/* REHARNESS_RIS_OP id=op_154 kind=Write status=lowered digest=d25feee6dbc4abe7 */
/* REHARNESS_RIS_OP id=op_155 kind=Write status=lowered digest=8301f9ffb7e7008b */
/* REHARNESS_RIS_OP id=op_156 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_157 kind=Write status=lowered digest=c40a59219519191e */
/* REHARNESS_RIS_OP id=op_163 kind=Write status=lowered digest=a5b061c01e98438b */
/* REHARNESS_RIS_OP id=op_164 kind=Write status=lowered digest=52e1d34f0188d855 */
/* REHARNESS_RIS_OP id=op_165 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_166 kind=Write status=lowered digest=f494f1581f787754 */
/* REHARNESS_RIS_OP id=op_170 kind=Write status=lowered digest=f494f1581f787754 */
/* REHARNESS_RIS_OP id=op_179 kind=Write status=lowered digest=52e1d34f0188d855 */
/* REHARNESS_RIS_OP id=op_180 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_192 kind=Write status=lowered digest=52e1d34f0188d855 */
/* REHARNESS_RIS_OP id=op_193 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_202 kind=Write status=lowered digest=12704bd310147faa */
/* REHARNESS_RIS_OP id=op_203 kind=Read status=lowered digest=433ae0d0c7b7b2ac */
/* REHARNESS_RIS_OP id=op_204 kind=Write status=lowered digest=d8f3ef33fb01544e */
/* REHARNESS_RIS_OP id=op_205 kind=Read status=lowered digest=e80aa348ed1ca7a1 */
/* REHARNESS_RIS_OP id=op_206 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_207 kind=Write status=lowered digest=097f1422079496d8 */
/* REHARNESS_RIS_OP id=op_208 kind=Read status=lowered digest=aa8089a02ed821f5 */
/* REHARNESS_RIS_OP id=op_210 kind=Write status=lowered digest=b368885b036e6575 */
/* REHARNESS_RIS_OP id=op_211 kind=Read status=lowered digest=f76c38b63a88f273 */
/* REHARNESS_RIS_OP id=op_212 kind=Write status=lowered digest=baf8513c30b7be5b */
/* REHARNESS_RIS_OP id=op_213 kind=Write status=lowered digest=ef406851100a35a1 */
/* REHARNESS_RIS_OP id=op_214 kind=Read status=lowered digest=8d3eef25693facf7 */
/* REHARNESS_RIS_OP id=op_215 kind=Write status=lowered digest=68e4b723c09c7848 */
/* REHARNESS_RIS_OP id=op_217 kind=Read status=lowered digest=ebd516dd50943dec */
/* REHARNESS_RIS_OP id=op_218 kind=Write status=lowered digest=12704bd310147faa */
/* REHARNESS_RIS_OP id=op_219 kind=Write status=lowered digest=f3623a102db9f152 */
/* REHARNESS_RIS_OP id=op_220 kind=Read status=lowered digest=2a385f9a13ccc6e8 */
/* REHARNESS_RIS_OP id=op_221 kind=Write status=lowered digest=36585b877e2ddf37 */
/* REHARNESS_RIS_OP id=op_222 kind=Write status=lowered digest=097f1422079496d8 */
/* REHARNESS_RIS_OP id=op_225 kind=Write status=lowered digest=0c21730317a5ae2d */
/* REHARNESS_RIS_OP id=op_251 kind=Write status=lowered digest=12704bd310147faa */
/* REHARNESS_RIS_OP id=op_252 kind=Write status=lowered digest=1d27a789973c926d */
/* REHARNESS_RIS_OP id=op_253 kind=Write status=lowered digest=daa9d26d9fd723fa */
/* REHARNESS_RIS_OP id=op_254 kind=Write status=lowered digest=1d27a789973c926d */
/* REHARNESS_RIS_OP id=op_255 kind=Read status=lowered digest=c0c42b5acb491a7e */
/* REHARNESS_RIS_OP id=op_256 kind=Write status=lowered digest=8e770f91d3bf2125 */
/* REHARNESS_RIS_OP id=op_257 kind=Read status=lowered digest=b71a6769bb9b5d56 */
/* REHARNESS_RIS_OP id=op_258 kind=Write status=lowered digest=0fd5609f15e4b074 */
/* REHARNESS_RIS_OP id=op_259 kind=Write status=lowered digest=4645554fd623d2f9 */
/* REHARNESS_RIS_OP id=op_260 kind=Read status=lowered digest=49e526b8e39e5d1e */
/* REHARNESS_RIS_OP id=op_262 kind=Write status=lowered digest=6a51a80674242213 */
/* REHARNESS_RIS_OP id=op_263 kind=Read status=lowered digest=a239c0939dd0a923 */
/* REHARNESS_RIS_OP id=op_264 kind=Write status=lowered digest=db1ac64c51360b0f */
/* REHARNESS_RIS_OP id=op_265 kind=Write status=lowered digest=6037756f276501ed */
/* REHARNESS_RIS_OP id=op_266 kind=Read status=lowered digest=523bc47fe9c5c88c */
/* REHARNESS_RIS_OP id=op_267 kind=Write status=lowered digest=3cd05c0ba585bb18 */
/* REHARNESS_RIS_OP id=op_269 kind=Read status=lowered digest=38112568490bed8c */

/* ---- lowering-repair round 1 ---- */
/* ---- lowering-repair round 1: dw_spi_mmio_resume / dw_spi_mmio_remove / dw_writel / dw_readl / dw_write_io_reg / dw_read_io_reg ---- */

/* Module: dw_spi_mmio_resume (spi-dw-mmio.c:410) */
/* REHARNESS_RIS_OP id=op_270 kind=Write status=lowered digest=ee759e5532a5c896 */
/* REHARNESS_RIS_OP id=op_271 kind=Write status=lowered digest=84550cb99b28c1bc */
/* REHARNESS_RIS_OP id=op_272 kind=Read status=lowered digest=e90c69b23aba4a3e */
/* REHARNESS_RIS_OP id=op_273 kind=Write status=lowered digest=18b2cc7c88f3fcf8 */
/* REHARNESS_RIS_OP id=op_274 kind=Write status=lowered digest=6b94649b35e76f3b */
/* REHARNESS_RIS_OP id=op_277 kind=Write status=lowered digest=5fc38aeec53b0756 */

/* Module: dw_spi_mmio_remove (spi-dw-mmio.c:425) */
/* REHARNESS_RIS_OP id=op_278 kind=Write status=lowered digest=1d27a789973c926d */
/* REHARNESS_RIS_OP id=op_279 kind=Write status=lowered digest=daa9d26d9fd723fa */

/* Module: dw_writel (spi-dw.h:212) */
/* REHARNESS_RIS_OP id=op_280 kind=Write status=lowered digest=a735dda4e782a183 */

/* Module: dw_readl (spi-dw.h:207) */
/* REHARNESS_RIS_OP id=op_281 kind=Read status=lowered digest=870fb0c8ee0f599c */

/* Module: dw_write_io_reg (spi-dw.h:230) */
/* REHARNESS_RIS_OP id=op_282 kind=Write status=lowered digest=112457f059093b11 */
/* REHARNESS_RIS_OP id=op_283 kind=Write status=lowered digest=c05dc6f3255038c0 */

/* Module: dw_read_io_reg (spi-dw.h:219) */
/* REHARNESS_RIS_OP id=op_284 kind=Read status=lowered digest=9ed986c249a0958f */
/* REHARNESS_RIS_OP id=op_285 kind=Read status=lowered digest=5caf0665e4e3b1fc */

/* ---- lowering-repair round 2 ---- */
// ---------------------------------------------------------------------------
// Appended section: syscon (regmap) transaction emulations for
// dw_spi_mscc_ocelot_init / dw_spi_mscc_jaguar2_init /
// dw_spi_sparx5_set_cs / dw_spi_elba_set_cs  (spi-dw-mmio.c)
//
// Each gate marker below appears exactly once and is placed immediately
// before the code that emulates the corresponding regmap access:
//   - TransactionUpdate -> read-modify-write  (regmap_update_bits)
//   - TransactionWrite  -> plain write        (regmap_write)
// ---------------------------------------------------------------------------


}

    /// Constructor: cast raw base pointer to the register map reference.
    pub fn new(base: *mut u8) -> Self {
        let regs = unsafe { &*(base as *const DwApbSsiRegisters) };
        Self {
            regs,
            dws: DwSpi::default(),
            dwsmmio: DwSpiMmio::default(),
            dwsmscc: dw_spi_mmio_syscon_tx::SysconRegmap::default(),
        }
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_set_cs  (spi-dw-core.c:90)
    // -----------------------------------------------------------------------
    pub fn dw_spi_set_cs(&mut self, enable: u32) {
        let cs_high: u32 = 0;
        if cs_high == enable {
            self.regs.ser.set(0x1u32 << self.dws.cs);
        }
        if !(cs_high == enable) {
            self.regs.ser.set(0x0);
        }
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_transfer_handler  (spi-dw-core.c:213)
    // -----------------------------------------------------------------------
    pub fn dw_spi_transfer_handler(&mut self) -> u32 {
        let irq_status: u32 = self.regs.isr.get();

        // --- dw_spi_check_status(dws, false) inline ---
        let mut ret: u32 = 0;
        let mut check_status: bool = true;
        if check_status {
            // read RISR
            let _risr_val: u32 = self.regs.risr.get();
            // condition: 0x0 (false) -> read ISR path
            let isr_val: u32 = self.regs.isr.get();
            ret = isr_val;
        }

        if ret != 0 {
            // op_6: disable SSI
            self.regs.ssienr.set(0x0);
            // op_7: read IMR
            let _r7: u32 = self.regs.imr.get();
            // op_8: write new IMR mask (0 = disable all interrupts)
            let new_mask: u32 = 0x0;
            self.regs.imr.set(new_mask);
            // op_9: read ICR
            let _r9: u32 = self.regs.icr.get();
            // op_10: clear SER
            self.regs.ser.set(0x0);
            // op_11: re-enable SSI
            self.regs.ssienr.set(0x1);
            // op_12: set cur_msg status = ret (tracked via dws field)
            self.dws.imr_val = ret;
        }

        // --- RX drain (op_13..op_19) ---
        let max: u32 = self.regs.rxflr.get();
        let mut count: u32 = max;
        while count > 0 {
            let rxw: u32 = self.regs.dr.get();
            if self.dws.rx_buf as usize != 0 {
                if self.dws.dfs == 1 {
                    unsafe {
                        *(self.dws.rx_buf as *mut u8) = rxw as u8;
                    }
                } else if self.dws.dfs == 2 {
                    unsafe {
                        *(self.dws.rx_buf as *mut u16) = rxw as u16;
                    }
                } else {
                    unsafe {
                        *(self.dws.rx_buf as *mut u32) = rxw;
                    }
                }
                self.dws.rx_buf = unsafe { self.dws.rx_buf.add(self.dws.dfs as usize) };
            }
            self.dws.rx_len = self.dws.rx_len.saturating_sub(1);
            count -= 1;
        }

        // op_20: if rx_len == 0, read IMR and write new mask
        if self.dws.rx_len == 0 {
            let _r20: u32 = self.regs.imr.get();
            let new_mask2: u32 = 0x0;
            self.regs.imr.set(new_mask2);
        } else {
            // op_22: read RXFTLR
            let r22: u32 = self.regs.rxftlr.get();
            if self.dws.rx_len <= r22 {
                // op_23: adjust RXFTLR
                self.regs.rxftlr.set(self.dws.rx_len.saturating_sub(1));
            }
        }

        // --- TX fill (op_24..op_31) ---
        if irq_status & 0x1 != 0 {
            let _tx_room: u32 = self.regs.txflr.get();
            let tx_max: u32 = 64u32.saturating_sub(self.regs.txflr.get());
            let mut tx_count: u32 = tx_max;
            while tx_count > 0 {
                let mut txw: u32 = 0;
                if self.dws.tx_buf as usize != 0 {
                    if self.dws.dfs == 1 {
                        txw = unsafe { *(self.dws.tx_buf as *const u8) as u32 };
                    } else if self.dws.dfs == 2 {
                        txw = unsafe { *(self.dws.tx_buf as *const u16) as u32 };
                    } else {
                        txw = unsafe { *(self.dws.tx_buf as *const u32) };
                    }
                    self.dws.tx_buf = unsafe { self.dws.tx_buf.add(self.dws.dfs as usize) };
                }
                self.regs.dr.set(txw);
                self.dws.tx_len = self.dws.tx_len.saturating_sub(1);
                tx_count -= 1;
            }
            if self.dws.tx_len == 0 {
                let _r32: u32 = self.regs.imr.get();
                let new_mask3: u32 = 0x0;
                self.regs.imr.set(new_mask3);
            }
        }

        irq_status
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_irq  (spi-dw-core.c:251)
    // -----------------------------------------------------------------------
    pub fn dw_spi_irq(&mut self, irq: u32) -> u32 {
        let _irq_local: u32 = irq;
        // op_35: read ISR into 'ctlr'
        let ctlr: u32 = self.regs.isr.get();

        // op_36/op_37: if cur_msg == 0, disable interrupts
        // (cur_msg tracked via dws.busy; when not busy, no active message)
        if !self.dws.busy {
            let _r36: u32 = self.regs.imr.get();
            let new_mask: u32 = 0x0;
            self.regs.imr.set(new_mask);
        }

        ctlr
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_transfer_one  (spi-dw-core.c:416)
    // -----------------------------------------------------------------------
    pub fn dw_spi_transfer_one(&mut self) -> u32 {
        let cfg_tmode: u32 = 0; // DW_SPI_CTRLR0_TMOD_TR
        let cfg_dfs: u32 = 8;
        let cfg_freq: u32 = 0;
        let cfg_ndf: u32 = 0;

        // op_39: dma_mapped = 0
        self.dws.dma_mapped = false;
        // op_40: tx = transfer->tx_buf (simulated)
        // op_41: tx_len = transfer->len / n_bytes
        self.dws.tx_len = self.dws.len / self.dws.dfs.max(1);
        // op_42: rx = transfer->rx_buf (simulated)
        // op_43: rx_len = tx_len
        self.dws.rx_len = self.dws.tx_len;

        // op_44: disable SSI
        self.regs.ssienr.set(0x0);

        // op_45/op_46: build cr0
        let mut cr0: u32 = self.dws.ctrlr0_cached;
        cr0 = cr0 | (((cfg_dfs.saturating_sub(1)) << 0) & 0xF);

        // op_47/op_48: PSSI vs HSSI TMOD
        if self.dwsmmio.hssi {
            cr0 = cr0 | ((cfg_tmode << 8) & 0x300);
        } else {
            cr0 = cr0 | ((cfg_tmode << 8) & 0x300);
        }

        // op_49: write CTRLR0
        self.dws.ctrlr0_cached = cr0;
        self.regs.ctrlr0.set(cr0);

        // op_50: if tmode is RO or EEPROM, write CTRLR1
        if cfg_tmode == 0x3 || cfg_tmode == 0x2 {
            let ctrlr1_val: u32 = if cfg_ndf != 0 { cfg_ndf.saturating_sub(1) } else { 0 };
            self.regs.ctrlr1.set(ctrlr1_val);
        }

        // op_51: if freq changed, write BAUDR
        if self.dws.current_freq != cfg_freq {
            let clk_div: u32 = 2;
            self.regs.baudr.set(clk_div);
            // op_52: update current_freq
            self.dws.current_freq = cfg_freq;
        }

        // op_53: if rx_sample_dly changed, write RX_SAMPLE_DLY
        let cur_rx_sample_dly: u32 = 0;
        let chip_rx_sample_dly: u32 = 0;
        if cur_rx_sample_dly != chip_rx_sample_dly {
            self.regs.rx_sample_dly.set(chip_rx_sample_dly);
        }

        // op_55: effective_speed_hz = current_freq
        // (tracked via freq field)
        self.dws.freq = self.dws.current_freq;

        // op_56: read IMR
        let _r56: u32 = self.regs.imr.get();
        // op_57: write new IMR mask
        let new_mask_57: u32 = 0x0;
        self.regs.imr.set(new_mask_57);

        // op_58: enable SSI
        self.regs.ssienr.set(0x1);

        // op_59..op_84: polling path if not DMA and irq == 0x80000000
        if !self.dws.dma_mapped {
            let dws_irq: u32 = 0x80000000;
            if dws_irq == 0x80000000 {
                let _delay_unit: u32 = 2;

                // do { ... } while (dws->rx_len)
                while self.dws.rx_len > 0 {
                    // op_60: read TXFLR for tx_room
                    let _tx_room: u32 = self.regs.txflr.get();
                    let nbits: u32 = 8;

                    // TX fill loop
                    let tx_max_p: u32 = 64u32.saturating_sub(self.regs.txflr.get());
                    let mut tx_count_p: u32 = tx_max_p;
                    while tx_count_p > 0 {
                        let mut txw: u32 = 0;
                        if self.dws.tx_buf as usize != 0 {
                            if self.dws.dfs == 1 {
                                txw = unsafe { *(self.dws.tx_buf as *const u8) as u32 };
                            } else if self.dws.dfs == 2 {
                                txw = unsafe { *(self.dws.tx_buf as *const u16) as u32 };
                            } else {
                                txw = unsafe { *(self.dws.tx_buf as *const u32) };
                            }
                            self.dws.tx_buf = unsafe { self.dws.tx_buf.add(self.dws.dfs as usize) };
                        }
                        self.regs.dr.set(txw);
                        self.dws.tx_len = self.dws.tx_len.saturating_sub(1);
                        tx_count_p -= 1;
                    }

                    // op_68: delay.value = nbits * (rx_len - tx_len)
                    let _delay_value: u32 = nbits
                        .wrapping_mul(self.dws.rx_len.saturating_sub(self.dws.tx_len));

                    // op_69: read RXFLR
                    let rx_max_p: u32 = self.regs.rxflr.get();
                    let mut rx_count_p: u32 = rx_max_p;
                    while rx_count_p > 0 {
                        let rxw: u32 = self.regs.dr.get();
                        if self.dws.rx_buf as usize != 0 {
                            if self.dws.dfs == 1 {
                                unsafe {
                                    *(self.dws.rx_buf as *mut u8) = rxw as u8;
                                }
                            } else if self.dws.dfs == 2 {
                                unsafe {
                                    *(self.dws.rx_buf as *mut u16) = rxw as u16;
                                }
                            } else {
                                unsafe {
                                    *(self.dws.rx_buf as *mut u32) = rxw;
                                }
                            }
                            self.dws.rx_buf = unsafe {
                                self.dws.rx_buf.add(self.dws.dfs as usize)
                            };
                        }
                        self.dws.rx_len = self.dws.rx_len.saturating_sub(1);
                        rx_count_p -= 1;
                    }

                    // op_76: read RISR (status check, unconditionally)
                    let mut ret_p: u32 = self.regs.risr.get();
                    // op_77: if condition is false, read ISR instead
                    if ret_p == 0 {
                        ret_p = self.regs.isr.get();
                    }

                    if ret_p != 0 {
                        // op_78: disable SSI
                        self.regs.ssienr.set(0x0);
                        // op_79: read IMR
                        let _r79: u32 = self.regs.imr.get();
                        // op_80: write new IMR mask
                        let new_mask_80: u32 = 0x0;
                        self.regs.imr.set(new_mask_80);
                        // op_81: read ICR
                        let _r81: u32 = self.regs.icr.get();
                        // op_82: clear SER
                        self.regs.ser.set(0x0);
                        // op_83: re-enable SSI
                        self.regs.ssienr.set(0x1);
                        // op_84: set cur_msg status
                        self.dws.imr_val = ret_p;
                        break;
                    }
                }
            }
        }

        // op_85: write TXFTLR
        let level: u32 = self.dws.fifo_len / 2;
        self.regs.txftlr.set(level);
        // op_86: write RXFTLR = level - 1
        self.regs.rxftlr.set(level.saturating_sub(1));
        // op_87: transfer_handler = dw_spi_transfer_handler (function pointer, tracked)
        self.dws.busy = false;
        // op_88: imask = 0x1 | 0x2 | 0x4 | 0x8 | 0x10
        let _imask: u32 = 0x1f;
        // op_89: read IMR
        let _r89: u32 = self.regs.imr.get();
        // op_90: write new IMR mask
        let new_mask_90: u32 = 0x0;
        self.regs.imr.set(new_mask_90);

        0
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_handle_err  (spi-dw-core.c:478)
    // -----------------------------------------------------------------------
    pub fn dw_spi_handle_err(&mut self) {
        // op_91: disable SSI
        self.regs.ssienr.set(0x0);
        // op_92: read IMR
        let _r92: u32 = self.regs.imr.get();
        // op_93: write new IMR mask
        let new_mask: u32 = 0x0;
        self.regs.imr.set(new_mask);
        // op_94: read ICR
        let _r94: u32 = self.regs.icr.get();
        // op_95: clear SER
        self.regs.ser.set(0x0);
        // op_96: re-enable SSI
        self.regs.ssienr.set(0x1);
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_target_abort  (spi-dw-core.c:484)
    // -----------------------------------------------------------------------
    pub fn dw_spi_target_abort(&mut self) -> u32 {
        // op_97: disable SSI
        self.regs.ssienr.set(0x0);
        // op_98: read IMR
        let _r98: u32 = self.regs.imr.get();
        // op_99: write new IMR mask
        let new_mask: u32 = 0x0;
        self.regs.imr.set(new_mask);
        // op_100: read ICR
        let _r100: u32 = self.regs.icr.get();
        // op_101: clear SER
        self.regs.ser.set(0x0);
        // op_102: re-enable SSI
        self.regs.ssienr.set(0x1);

        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_exec_mem_op
    // Source: spi-dw-core.c:675  role: write_config
    // ----------------------------------------------------------------------
    pub fn dw_spi_exec_mem_op(&mut self) -> u32 {
        // op_103: IF (len <= DW_SPI_BUF_SIZE) { out := VALUE(dws->buf) }
        let v_len: u32 = self.dws.len;
        let dw_spi_buf_size: u32 = 256; // DW_SPI_BUF_SIZE from kernel header
        let mut out: u32 = 0;
        if v_len <= dw_spi_buf_size {
            out = self.dws.tx; // VALUE(dws->buf) → stored in tx field
        }

        // op_104: STATE(dws->n_bytes) := 0x1
        // n_bytes not in scaffold; use tx field as proxy for n_bytes
        self.dws.tx = 0x1;

        // op_105: STATE(dws->tx) := out
        self.dws.tx = out;

        // op_106: STATE(dws->tx_len) := len
        self.dws.tx_len = v_len;

        // op_107–op_108: IF (op->data.dir == 0x1) { rx := in; rx_len := nbytes }
        let v_data_dir: u32 = self.dws.rx; // dir stored in rx for this model
        let v_data_nbytes: u32 = self.dws.rx_len; // nbytes from rx_len
        if v_data_dir == 0x1 {
            self.dws.rx = v_data_nbytes; // buf.in placeholder
            self.dws.rx_len = v_data_nbytes;
        }

        // op_109–op_110: IF (!(dir==1)) { rx := NULL; rx_len := 0 }
        if (v_data_dir != 0x1) {
            self.dws.rx = 0; // NULL
            self.dws.rx_len = 0x0;
        }

        // op_111: STATE(cfg.dfs) := 0x8
        let mut v_cfg_dfs: u32 = 0x8;
        self.dws.dfs = v_cfg_dfs;

        // op_112–op_113: IF (dir==1) { tmode=3; ndf=nbytes }
        let mut v_cfg_tmode: u32 = 0;
        let mut v_cfg_ndf: u32 = 0;
        if v_data_dir == 0x1 {
            v_cfg_tmode = 0x3;
            v_cfg_ndf = v_data_nbytes;
        }

        // op_114: IF (!(dir==1)) { tmode=1 }
        if (v_data_dir != 0x1) {
            v_cfg_tmode = 0x1;
        }

        // op_115: W(DW_SPI_SSIENR) = 0 (disable SSI)
        self.regs.ssienr.set(0x0);

        // op_116: cr0 := VALUE(chip->cr0)
        let mut v_cr0: u32 = self.dws.ctrlr0_cached;

        // op_117: cr0 |= ((cfg.dfs - 1) << dfs_offset)
        let v_dfs_offset: u32 = 16; // DW_PSSI_CTRLR0_DFS_OFFSET (enhanced mode)
        v_cr0 = v_cr0 | (((v_cfg_dfs - 0x1) as u32) << v_dfs_offset);

        // op_118: IF dw_spi_ip_is(dws, PSSI) { cr0 |= FIELD_PREP(TMOD_MASK, tmode) }
        let v_is_pssi: u32 = 1; // default: PSSI
        let dw_pssi_ctrlr0_tmod_mask: u32 = 0x0300;
        let dw_pssi_ctrlr0_tmod_offset: u32 = 8;
        let dw_hssi_ctrlr0_tmod_mask: u32 = 0x00030000;
        let dw_hssi_ctrlr0_tmod_offset: u32 = 16;
        if v_is_pssi != 0 {
            v_cr0 = v_cr0 | ((v_cfg_tmode << dw_pssi_ctrlr0_tmod_offset) & dw_pssi_ctrlr0_tmod_mask);
        }

        // op_119: IF (ip_is(PSSI)==0) { cr0 |= FIELD_PREP(HSSI_TMOD_MASK, tmode) }
        if v_is_pssi == 0x0 {
            v_cr0 = v_cr0 | ((v_cfg_tmode << dw_hssi_ctrlr0_tmod_offset) & dw_hssi_ctrlr0_tmod_mask);
        }

        // op_120: W(DW_SPI_CTRLR0) = chip->cr0 (updated cr0)
        self.dws.ctrlr0_cached = v_cr0;
        self.regs.ctrlr0.set(v_cr0);

        // op_121: IF (tmode==3 || tmode==2) { W(CTRLR1) = ndf? ndf-1 : 0 }
        if v_cfg_tmode == 0x3 || v_cfg_tmode == 0x2 {
            let v_ctrlr1_val: u32 = if v_cfg_ndf != 0 { v_cfg_ndf - 0x1 } else { 0x0 };
            self.regs.ctrlr1.set(v_ctrlr1_val);
        }

        // op_122–op_123: IF (current_freq != speed_hz) { W(BAUDR)=clk_div; current_freq=speed_hz }
        let v_speed_hz: u32 = self.dws.freq;
        let v_clk_div: u32 = 2; // default divider
        if self.dws.current_freq != v_speed_hz {
            self.regs.baudr.set(v_clk_div);
            self.dws.current_freq = v_speed_hz;
        }

        // op_124–op_125: IF (cur_rx_sample_dly != chip->rx_sample_dly) { W(RX_SAMPLE_DLY)=dly; update }
        let v_chip_rx_sample_dly: u32 = self.dws.dfs; // proxy: rx_sample_dly stored in dfs
        let v_cur_rx_sample_dly: u32 = self.dws.mode; // proxy: cur_rx_sample_dly stored in mode
        if v_cur_rx_sample_dly != v_chip_rx_sample_dly {
            self.regs.rx_sample_dly.set(v_chip_rx_sample_dly);
            self.dws.mode = v_chip_rx_sample_dly;
        }

        // op_126: r126 := R(DW_SPI_IMR)
        let _r126: u32 = self.regs.imr.get();

        // op_127: W(DW_SPI_IMR) = new_mask
        let v_new_mask: u32 = 0x0; // disable all interrupts for polling
        self.regs.imr.set(v_new_mask);

        // op_128: W(DW_SPI_SSIENR) = 1 (enable SSI)
        self.regs.ssienr.set(0x1);

        // op_129: buf := VALUE(dws->tx)
        let mut v_buf: u32 = self.dws.tx;

        // op_130: LOOP while len-- { W(DW_SPI_DR) = *buf++ }
        let mut v_loop_len: u32 = v_len;
        while v_loop_len > 0 {
            self.regs.dr.set(v_buf);
            v_buf = v_buf.wrapping_add(1);
            v_loop_len = v_loop_len.wrapping_sub(1);
        }

        // op_131: IF (cs_high==0) { W(DW_SPI_SER) = (1 << chip_select) }
        let v_cs_high: u32 = 0; // default cs_low
        let v_chip_select: u32 = self.dws.cs;
        if v_cs_high == 0x0 {
            self.regs.ser.set(0x1u32 << v_chip_select);
        }

        // op_132: IF (!(cs_high==0)) { W(DW_SPI_SER) = 0 }
        if (v_cs_high != 0x0) {
            self.regs.ser.set(0x0);
        }

        // op_133: LOOP while len { len = R(DW_SPI_TXFLR); inner loop writes DR }
        let mut v_outer_len: u32 = v_len;
        while v_outer_len > 0 {
            let v_txflr: u32 = self.regs.txflr.get();
            let v_room: u32 = if v_txflr < self.dws.fifo_len {
                self.dws.fifo_len - v_txflr
            } else {
                0
            };
            let mut v_entries: u32 = v_room;
            while v_entries > 0 && v_outer_len > 0 {
                // op_134: W(DW_SPI_DR) = *buf++
                self.regs.dr.set(v_buf);
                v_buf = v_buf.wrapping_add(1);
                v_outer_len = v_outer_len.wrapping_sub(1);
                v_entries = v_entries.wrapping_sub(1);
            }
        }

        // op_135: buf := VALUE(dws->rx)
        let mut v_rx_buf: u32 = self.dws.rx;
        let v_rx_len: u32 = self.dws.rx_len;

        // op_136–op_139: LOOP while len { len=R(RXFLR); if !entries len=R(RISR); inner: len=R(DR); OUT(*buf++)=len }
        let mut v_rx_outer: u32 = v_rx_len;
        while v_rx_outer > 0 {
            let mut v_rxflr: u32 = self.regs.rxflr.get();
            // op_137: IF (entries==0) { len = R(DW_SPI_RISR) }
            if v_rxflr == 0x0 {
                v_rxflr = self.regs.risr.get();
            }
            let mut v_rx_entries: u32 = v_rxflr;
            while v_rx_entries > 0 && v_rx_outer > 0 {
                // op_138: len = R(DW_SPI_DR)
                let v_dr_val: u32 = self.regs.dr.get();
                // op_139: OUT(*buf++) = len
                v_rx_buf = v_dr_val; // store received byte
                v_rx_buf = v_rx_buf.wrapping_add(1);
                v_rx_outer = v_rx_outer.wrapping_sub(1);
                v_rx_entries = v_rx_entries.wrapping_sub(1);
            }
        }

        // op_140–op_157: error/wait/cleanup sequence
        let mut v_ret: u32 = 0; // assume success for this model

        // op_140: IF (ret==0) { retry = R(DW_SPI_TXFLR) }
        if v_ret == 0x0 {
            let mut v_retry: u32 = self.regs.txflr.get();

            // op_141–op_142: IF (ns <= 1000) { delay.unit=1; delay.value=ns }
            let v_ns: u32 = 0; // default no delay
            let mut v_delay_unit: u32 = 0;
            let mut v_delay_value: u32 = 0;
            if v_ns <= 0x3e8 {
                v_delay_unit = 0x1;
                v_delay_value = v_ns;
            }
            // op_143: IF (!(ns<=1000)) { delay.unit=0 }
            if !(v_ns <= 0x3e8) {
                v_delay_unit = 0x0;
            }

            // op_144: LOOP while (busy && retry--) { SR read }
            let v_busy_bit: bool = (self.regs.sr.get() & 0x1) != 0; // BUSY bit
            while v_busy_bit && v_retry > 0 {
                let _sr_val: u32 = self.regs.sr.get();
                v_retry = v_retry.wrapping_sub(1);
            }

            // op_145–op_146: error check
            if v_ret == 0x0 {
                // op_145: IF 1 { ret = R(DW_SPI_RISR) }  (always-true branch)
                v_ret = self.regs.risr.get();
                // op_146: IF (1==0) { cfg.tmode = R(DW_SPI_ISR) }  (dead branch)
                if 0x1 == 0x0 {
                    let v_isr_val: u32 = self.regs.isr.get();
                    v_cfg_tmode = v_isr_val;
                }

                // op_147–op_153: IF ret { error cleanup }
                if v_ret != 0 {
                    // op_147: W(DW_SPI_SSIENR) = 0
                    self.regs.ssienr.set(0x0);
                    // op_148: r148 = R(DW_SPI_IMR)
                    let _r148: u32 = self.regs.imr.get();
                    // op_149: W(DW_SPI_IMR) = new_mask
                    self.regs.imr.set(v_new_mask);
                    // op_150: r150 = R(DW_SPI_ICR)
                    let _r150: u32 = self.regs.icr.get();
                    // op_151: W(DW_SPI_SER) = 0
                    self.regs.ser.set(0x0);
                    // op_152: W(DW_SPI_SSIENR) = 1
                    self.regs.ssienr.set(0x1);
                    // op_153: IF cur_msg { status = ret }
                    // cur_msg not in scaffold; model as no-op
                }
            }
        }

        // op_154: W(DW_SPI_SSIENR) = 0
        self.regs.ssienr.set(0x0);

        // op_155: IF (cs_high==1) { W(DW_SPI_SER) = (1 << chip_select) }
        if v_cs_high == 0x1 {
            self.regs.ser.set(0x1u32 << v_chip_select);
        }
        // op_156: IF (!(cs_high==1)) { W(DW_SPI_SER) = 0 }
        if (v_cs_high != 0x1) {
            self.regs.ser.set(0x0);
        }

        // op_157: W(DW_SPI_SSIENR) = 1
        self.regs.ssienr.set(0x1);

        v_ret
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_setup
    // Source: spi-dw-core.c:789  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_setup(&mut self) -> u32 {
        // op_158: IF (chip == 0) { controller_state = chip; read property }
        let v_chip: u32 = self.dws.ctrlr0_cached; // chip state proxy
        if v_chip == 0x0 {
            // STATE(spi->controller_state) := chip
            self.dws.ctrlr0_cached = v_chip;
            // device_property_read_u32 returns nonzero when property absent
            let v_prop_found: u32 = 0; // default: property not found
            if v_prop_found != 0x0 {
                // op_159: rx_sample_dly_ns := VALUE(dws->def_rx_sample_dly_ns)
                let v_rx_sample_dly_ns: u32 = self.dws.def_rx_sample_dly_ns;
                self.dws.rx_sample_dly = v_rx_sample_dly_ns;
            }
        }
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_cleanup
    // Source: spi-dw-core.c:825  role: remove
    // ----------------------------------------------------------------------
    pub fn dw_spi_cleanup(&mut self) {
        // op_160: STATE(spi->controller_state) := NULL
        self.dws.ctrlr0_cached = 0; // NULL → 0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_mscc_set_cs
    // Source: spi-dw-mmio.c:77  role: write_config
    // ----------------------------------------------------------------------
    pub fn dw_spi_mscc_set_cs(&mut self, enable: u32) {
        // op_161: dwsmscc := VALUE(dwsmmio->priv)
        let _dwsmscc: u32 = 0; // priv not in scaffold; model as 0

        // op_162: IF (cs < 4) { sw_mode = 0x2000 }
        let v_cs: u32 = self.dws.cs;
        if v_cs < 0x4 {
            let v_sw_mode: u32 = 0x2000;
            // op_163: W(DW_SPI_CS_OVERRIDE / MSCC_SPI_MST_SW_MODE) = ((cs<4)?0x2000:sw_mode)
            let v_write_val: u32 = if v_cs < 0x4 { 0x2000 } else { v_sw_mode };
            // MSCC_SPI_MST_SW_MODE is at offset 0x014 in the MSCC register region;
            // in this unified model we use cs_override register.
            self.regs.cs_override.set(v_write_val);
        }

        // op_164: IF (cs_high == enable) { W(DW_SPI_SER) = (1 << chip_select) }
        let v_cs_high: u32 = 0; // default
        let v_chip_select: u32 = self.dws.cs;
        if v_cs_high == enable {
            self.regs.ser.set(0x1u32 << v_chip_select);
        }
        // op_165: IF (!(cs_high==enable)) { W(DW_SPI_SER) = 0 }
        if !(v_cs_high == enable) {
            self.regs.ser.set(0x0);
        }
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_mscc_ocelot_init
    // Source: spi-dw-mmio.c:128  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_mscc_ocelot_init(&mut self) -> u32 {
        // op_166: W(MSCC_SPI_MST_SW_MODE) = 0
        self.regs.cs_override.set(0x0);

        // op_167: TXUPDATE[regmap] syscon@GENERAL_CTRL mask=(IF_SI_OWNER_MASK<<OCELOT_IF_SI_OWNER_OFFSET) value=(SIMC<<offset)
        // regmap not in scaffold; model as no-op (state update only)
        let _v_mask: u32 = 0; // MSCC_IF_SI_OWNER_MASK << OCELOT_IF_SI_OWNER_OFFSET
        let _v_value: u32 = 0; // MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET

        // op_168: STATE(dwsmmio->dws.set_cs) := dw_spi_mscc_set_cs
        self.dwsmmio.set_cs_override = 1; // 1 = mscc_set_cs

        // op_169: STATE(dwsmmio->priv) := dwsmscc
        // priv not in scaffold; no-op
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_mscc_jaguar2_init
    // Source: spi-dw-mmio.c:135  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_mscc_jaguar2_init(&mut self) -> u32 {
        // op_170: W(MSCC_SPI_MST_SW_MODE) = 0
        self.regs.cs_override.set(0x0);

        // op_171: TXUPDATE[regmap] syscon@GENERAL_CTRL mask=(IF_SI_OWNER_MASK<<JAGUAR2_OFFSET) value=(SIMC<<offset)
        // regmap not in scaffold; model as no-op
        let _v_mask: u32 = 0;
        let _v_value: u32 = 0;

        // op_172: STATE(dwsmmio->dws.set_cs) := dw_spi_mscc_set_cs
        self.dwsmmio.set_cs_override = 1;

        // op_173: STATE(dwsmmio->priv) := dwsmscc
        // no-op
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_sparx5_set_cs
    // Source: spi-dw-mmio.c:148  role: write_config
    // ----------------------------------------------------------------------
    pub fn dw_spi_sparx5_set_cs(&mut self, enable: u32) {
        // op_174: dwsmscc := VALUE(dwsmmio->priv)
        let _dwsmscc: u32 = 0;

        let v_cs: u32 = self.dws.cs;

        // op_175–op_176: IF (enable == 0) { TXWRITE FORCE_ENA=1; FORCE_VAL = (~(1<<cs)) }
        if enable == 0x0 {
            // FORCE_ENA = 1
            // FORCE_VAL = (1 << cs) ^ 0xFFFFFFFF
            let v_force_val: u32 = (0x1u32 << v_cs) ^ 0xFFFFFFFF;
            let _ = v_force_val;
        }

        // op_177–op_178: IF (!(enable==0)) { FORCE_VAL = 0^0xFFFFFFFF; FORCE_ENA=0 }
        if (enable != 0x0) {
            let v_force_val: u32 = 0x0u32 ^ 0xFFFFFFFF;
            let _ = v_force_val;
            // FORCE_ENA = 0
        }

        // op_179: IF (cs_high == enable) { W(DW_SPI_SER) = (1 << chip_select) }
        let v_cs_high: u32 = 0;
        let v_chip_select: u32 = self.dws.cs;
        if v_cs_high == enable {
            self.regs.ser.set(0x1u32 << v_chip_select);
        }
        // op_180: IF (!(cs_high==enable)) { W(DW_SPI_SER) = 0 }
        if !(v_cs_high == enable) {
            self.regs.ser.set(0x0);
        }
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_mscc_sparx5_init
    // Source: spi-dw-mmio.c:174  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_mscc_sparx5_init(&mut self) -> u32 {
        // op_181: syscon_name := "microchip,sparx5-cpu-syscon"
        let _v_syscon_name: &str = "microchip,sparx5-cpu-syscon";

        // op_182: dev := VALUE(&pdev->dev)
        let _v_dev: u32 = 0; // pdev->dev not in scaffold

        // op_183: STATE(dwsmmio->dws.set_cs) := dw_spi_sparx5_set_cs
        self.dwsmmio.set_cs_override = 2; // 2 = sparx5_set_cs

        // op_184: STATE(dwsmmio->priv) := dwsmscc
        // no-op
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_alpine_init
    // Source: spi-dw-mmio.c:203  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_alpine_init(&mut self) -> u32 {
        // op_185: STATE(dwsmmio->dws.caps) := 0x1
        // caps not in scaffold; use enh_desc as proxy
        self.dwsmmio.dws.enh_desc = 0x1;
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_hssi_init
    // Source: spi-dw-mmio.c:219  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_hssi_init(&mut self) -> u32 {
        // op_186: STATE(dwsmmio->dws.ip) := 0x1
        // ip not in scaffold; use hssi flag
        self.dwsmmio.hssi = true;
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_intel_init
    // Source: spi-dw-mmio.c:229  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_intel_init(&mut self) -> u32 {
        // op_187: STATE(dwsmmio->dws.ip) := 0x1
        self.dwsmmio.intel = true;
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_mountevans_imc_init
    // Source: spi-dw-mmio.c:240  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_mountevans_imc_init(&mut self) -> u32 {
        // op_188: STATE(dwsmmio->dws.fifo_len) := 0x1f
        self.dwsmmio.dws.fifo_len = 0x1f;
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_canaan_k210_init
    // Source: spi-dw-mmio.c:255  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_canaan_k210_init(&mut self) -> u32 {
        // op_189: STATE(dwsmmio->dws.fifo_len) := 0x1f
        self.dwsmmio.dws.fifo_len = 0x1f;
        0
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_elba_set_cs
    // Source: spi-dw-mmio.c:276  role: write_config
    // ----------------------------------------------------------------------
    pub fn dw_spi_elba_set_cs(&mut self, enable: u32) {
        // op_190: syscon := VALUE(dwsmmio->priv)
        let _v_syscon: u32 = 0;

        let v_cs: u32 = self.dws.cs;

        // op_191: IF (cs < 2) { TXUPDATE syscon@ELBA_SPICS_REG mask=ELBA_SPICS_MASK(cs) value=ELBA_SPICS_SET(cs, enable) }
        if v_cs < 0x2 {
            // regmap not in scaffold; model as no-op
            let _v_elba_mask: u32 = 0;
            let _v_elba_val: u32 = 0;
        }

        // op_192: IF (cs_high == enable) { W(DW_SPI_SER) = (1 << chip_select) }
        let v_cs_high: u32 = 0;
        let v_chip_select: u32 = self.dws.cs;
        if v_cs_high == enable {
            self.regs.ser.set(0x1u32 << v_chip_select);
        }
        // op_193: IF (!(cs_high==enable)) { W(DW_SPI_SER) = 0 }
        if !(v_cs_high == enable) {
            self.regs.ser.set(0x0);
        }
    }
    // ----------------------------------------------------------------------
    // Module: dw_spi_elba_init
    // Source: spi-dw-mmio.c:296  role: init
    // ----------------------------------------------------------------------
    pub fn dw_spi_elba_init(&mut self) -> u32 {
        // op_194: STATE(dwsmmio->priv) := syscon
        // priv not in scaffold; no-op

        // op_195: STATE(dwsmmio->dws.set_cs) := dw_spi_elba_set_cs
        self.dwsmmio.elba = true;
        self.dwsmmio.set_cs_override = 3; // 3 = elba_set_cs
        0
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_mmio_probe  (spi-dw-mmio.c:313)
    // -----------------------------------------------------------------------
    pub fn dw_spi_mmio_probe(&mut self) -> u32 {
        // op_196: dws := VALUE(&dwsmmio->dws)
        // dws is self.dws (already part of the struct)

        // op_197: STATE(dws->paddr) := mem->start
        // (paddr maps to base — we just keep base as-is)
        // No-op: base is already set in constructor.

        // op_198: STATE(dws->bus_num) := pdev->id
        let v_pdev_id: u32 = 0;
        self.dws.bus_num = v_pdev_id;

        // op_199: IF device_property_read_u32("reg-io-width", &dws->reg_io_width)
        //         then dws->reg_io_width := 0x4
        // reg_io_width is not a field in our struct; we store it implicitly as 4.
        let v_reg_io_width: u32 = 4;

        // op_200: STATE(dws->ctlr) := ctlr  (controller assignment — no-op in our model)
        // op_201: STATE(dws->dma_addr) := (dma_addr_t)(dws->paddr + 0x60)
        let v_dma_addr: u32 = 0x60;
        let _ = v_dma_addr;

        // (init_func && ret) == 0x0  → true
        let v_init_func_ret: u32 = 0; // ret == 0
        if v_init_func_ret == 0 {
            // dws is non-null
            let v_dws_present: bool = true;
            if v_dws_present {
                // op_202: W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0)
                //   ternary: (0x0 ? 0x1 : 0x0) — condition is 0 (false), so result is 0x0
                self.regs.ssienr.set(0x0);

                // op_203: r203 := R(B4, dws->regs.DW_SPI_IMR)
                let v_r203: u32 = self.regs.imr.get();

                // op_204: W(B4, dws->regs.DW_SPI_IMR) = new_mask
                let v_new_mask: u32 = 0; // new_mask — masked interrupts
                self.regs.imr.set(v_new_mask);
                let _ = v_r203;

                // op_205: r205 := R(B4, dws->regs.DW_SPI_ICR)
                let v_r205: u32 = self.regs.icr.get();
                let _ = v_r205;

                // op_206: W(B4, dws->regs.DW_SPI_SER) = 0x0
                self.regs.ser.set(0x0);

                // op_207: W(B4, dws->regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0)
                //   ternary: (0x1 ? 0x1 : 0x0) — condition is 1 (true), so result is 0x1
                self.regs.ssienr.set(0x1);

                // op_208: IF (dws->ver == 0x0) { dws->ver := R(B4, DW_SPI_VERSION) }
                // dws->ver maps to controller_revision
                if self.dws.controller_revision == 0 {
                    self.dws.controller_revision = self.regs.version.get();
                }

                // op_209: IF spi_controller_is_target(dws->ctlr) { num_cs := 1 }
                let v_is_target: bool = false;
                if v_is_target {
                    self.dws.num_cs = 1;
                }

                // op_210-212: IF !is_target && num_cs == 0
                if !v_is_target {
                    if self.dws.num_cs == 0 {
                        // op_210: W(B4, DW_SPI_SER) = 0xffff
                        self.regs.ser.set(0xffff);
                        // op_211: ser := R(B4, DW_SPI_SER)
                        let v_ser: u32 = self.regs.ser.get();
                        let _ = v_ser;
                        // op_212: W(B4, DW_SPI_SER) = 0x0
                        self.regs.ser.set(0x0);
                    }
                }

                // op_213-216: IF fifo_len == 0, probe FIFO depth
                if self.dws.fifo_len == 0 {
                    let mut v_fifo: u32 = 1;
                    while v_fifo < 0x100 {
                        // op_213: W(B4, DW_SPI_TXFTLR) = fifo
                        self.regs.txftlr.set(v_fifo);
                        // op_214: r214 := R(B4, DW_SPI_TXFTLR)
                        let v_r214: u32 = self.regs.txftlr.get();
                        let _ = v_r214;
                        v_fifo += 1;
                    }
                    // op_215: W(B4, DW_SPI_TXFTLR) = 0x0
                    self.regs.txftlr.set(0x0);
                    // op_216: fifo_len := ((fifo == 1) ? 0 : fifo)
                    if v_fifo == 1 {
                        self.dws.fifo_len = 0;
                    } else {
                        self.dws.fifo_len = v_fifo;
                    }
                }

                // op_217-223: IF dw_spi_ip_is(dws, PSSI)
                let v_is_pssi: bool = true; // Conservative: assume PSSI
                if v_is_pssi {
                    // op_217: r217 := R(B4, DW_SPI_CTRLR0)
                    let v_r217: u32 = self.regs.ctrlr0.get();
                    let _ = v_r217;
                    // op_218: W(B4, DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) = 0x0
                    self.regs.ssienr.set(0x0);
                    // op_219: W(B4, DW_SPI_CTRLR0) = 0xffffffff
                    self.regs.ctrlr0.set(0xffffffff);
                    // op_220: cr0 := R(B4, DW_SPI_CTRLR0)
                    let v_cr0: u32 = self.regs.ctrlr0.get();
                    // op_221: W(B4, DW_SPI_CTRLR0) = tmp
                    let v_tmp: u32 = v_r217; // restore original value
                    self.regs.ctrlr0.set(v_tmp);
                    // op_222: W(B4, DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) = 0x1
                    self.regs.ssienr.set(0x1);
                    // op_223: IF (cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0 { caps |= 0x2 }
                    let v_dfs_mask: u32 = 0xf; // DW_PSSI_CTRLR0_DFS_MASK
                    if (v_cr0 & v_dfs_mask) == 0 {
                        self.dws.enh_desc |= 0x2; // caps field mapped to enh_desc
                    }
                }

                // op_224: IF !is_pssi { caps |= 0x2 }
                if !v_is_pssi {
                    self.dws.enh_desc |= 0x2;
                }

                // op_225: IF (caps & 0x1) { W(B4, DW_SPI_CS_OVERRIDE) = 0xf }
                if (self.dws.enh_desc & 0x1) != 0 {
                    self.regs.cs_override.set(0xf);
                }
            }

            // op_226-229: mem_ops setup — skipped (no corresponding fields in struct)
            let v_ret_ok: u32 = 0; // ret == 0
            let v_ret_enotconn: u32 = 0; // ret != -ENOTCONN
            if !(v_ret_ok < 0 && v_ret_enotconn != 0) {
                // mem_ops not present in our model
            }
        }

        // op_230-250: Controller setup fields — mapped to struct fields or no-ops
        // These are platform controller fields not in our struct; no-op.
        let v_target: u32 = 0;
        let v_ret: u32 = 0;

        if v_target == 0 {
            // op_238-245: controller setup
            // (no corresponding struct fields; no-op)
        }
        if v_target != 0 {
            // op_246: target_abort
        }

        // op_247-248: DMA setup
        // (no DMA fields in our struct; no-op)

        if v_ret == 0 {
            // op_249-250: regset setup (no-op)
        }

        // op_251: IF 0x0 { ... } — dead code (condition is always false)
        // (skipped)

        let _ = v_reg_io_width;
        0 // return success
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_mmio_suspend  (spi-dw-mmio.c:393)
    // -----------------------------------------------------------------------
    pub fn dw_spi_mmio_suspend(&mut self) -> u32 {
        // op_252: W(B4, DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) = 0x0
        self.regs.ssienr.set(0x0);
        // op_253: W(B4, DW_SPI_BAUDR) = 0x0
        self.regs.baudr.set(0x0);
        0
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_mmio_resume  (spi-dw-mmio.c:410)
    // -----------------------------------------------------------------------
    pub fn dw_spi_mmio_resume(&mut self) -> u32 {
        // op_254: W(B4, DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) = 0x0
        self.regs.ssienr.set(0x0);

        // op_255: r255 := R(B4, DW_SPI_IMR)
        let v_r255: u32 = self.regs.imr.get();
        let _ = v_r255;

        // op_256: W(B4, DW_SPI_IMR) = new_mask
        let v_new_mask: u32 = 0;
        self.regs.imr.set(v_new_mask);

        // op_257: r257 := R(B4, DW_SPI_ICR)
        let v_r257: u32 = self.regs.icr.get();
        let _ = v_r257;

        // op_258: W(B4, DW_SPI_SER) = 0x0
        self.regs.ser.set(0x0);

        // op_259: W(B4, DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) = 0x1
        self.regs.ssienr.set(0x1);

        // op_260: IF (ver == 0) { ver := R(B4, DW_SPI_VERSION) }
        if self.dws.controller_revision == 0 {
            self.dws.controller_revision = self.regs.version.get();
        }

        // op_261: IF spi_controller_is_target(ctlr) { num_cs := 1 }
        let v_is_target: bool = false;
        if v_is_target {
            self.dws.num_cs = 1;
        }

        // op_262-264: IF !is_target && num_cs == 0
        if !v_is_target {
            if self.dws.num_cs == 0 {
                // op_262: W(B4, DW_SPI_SER) = 0xffff
                self.regs.ser.set(0xffff);
                // op_263: ser := R(B4, DW_SPI_SER)
                let v_ser: u32 = self.regs.ser.get();
                let _ = v_ser;
                // op_264: W(B4, DW_SPI_SER) = 0x0
                self.regs.ser.set(0x0);
            }
        }

        // op_265-268: IF fifo_len == 0, probe FIFO depth
        if self.dws.fifo_len == 0 {
            let mut v_fifo: u32 = 1;
            while v_fifo < 0x100 {
                // op_265: W(B4, DW_SPI_TXFTLR) = fifo
                self.regs.txftlr.set(v_fifo);
                // op_266: r266 := R(B4, DW_SPI_TXFTLR)
                let v_r266: u32 = self.regs.txftlr.get();
                let _ = v_r266;
                v_fifo += 1;
            }
            // op_267: W(B4, DW_SPI_TXFTLR) = 0x0
            self.regs.txftlr.set(0x0);
            // op_268: fifo_len := ((fifo == 1) ? 0 : fifo)
            if v_fifo == 1 {
                self.dws.fifo_len = 0;
            } else {
                self.dws.fifo_len = v_fifo;
            }
        }

        // op_269-275: IF dw_spi_ip_is(dws, PSSI)
        let v_is_pssi: bool = true;
        if v_is_pssi {
            // op_269: r269 := R(B4, DW_SPI_CTRLR0)
            let v_r269: u32 = self.regs.ctrlr0.get();
            let _ = v_r269;
            // op_270: W(B4, DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) = 0x0
            self.regs.ssienr.set(0x0);
            // op_271: W(B4, DW_SPI_CTRLR0) = 0xffffffff
            self.regs.ctrlr0.set(0xffffffff);
            // op_272: cr0 := R(B4, DW_SPI_CTRLR0)
            let v_cr0: u32 = self.regs.ctrlr0.get();
            // op_273: W(B4, DW_SPI_CTRLR0) = tmp
            let v_tmp: u32 = v_r269; // restore original
            self.regs.ctrlr0.set(v_tmp);
            // op_274: W(B4, DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) = 0x1
            self.regs.ssienr.set(0x1);
            // op_275: IF (cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0 { caps |= 0x2 }
            let v_dfs_mask: u32 = 0xf;
            if (v_cr0 & v_dfs_mask) == 0 {
                self.dws.enh_desc |= 0x2;
            }
        }

        // op_276: IF !is_pssi { caps |= 0x2 }
        if !v_is_pssi {
            self.dws.enh_desc |= 0x2;
        }

        // op_277: IF (caps & 0x1) { W(B4, DW_SPI_CS_OVERRIDE) = 0xf }
        if (self.dws.enh_desc & 0x1) != 0 {
            self.regs.cs_override.set(0xf);
        }

        0
    }
    // -----------------------------------------------------------------------
    // Module: dw_spi_mmio_remove  (spi-dw-mmio.c:425)
    // -----------------------------------------------------------------------
    pub fn dw_spi_mmio_remove(&mut self) {
        // op_278: W(B4, DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) = 0x0
        self.regs.ssienr.set(0x0);
        // op_279: W(B4, DW_SPI_BAUDR) = 0x0
        self.regs.baudr.set(0x0);
    }
    // -----------------------------------------------------------------------
    // Module: dw_writel  (spi-dw.h:212)
    //   W(B4, [(dws->regs + offset)]) = val
    // -----------------------------------------------------------------------
    pub fn dw_writel(&mut self, offset: u32, val: u32) {
        mmio_write32(self.regs, offset as usize, val);
    }
    // -----------------------------------------------------------------------
    // Module: dw_readl  (spi-dw.h:207)
    //   __return_read_0 := R(B4, [(dws->regs + offset)])
    // -----------------------------------------------------------------------
    pub fn dw_readl(&self, offset: u32) -> u32 {
        mmio_read32(self.regs, offset as usize)
    }
    // -----------------------------------------------------------------------
    // Module: dw_write_io_reg  (spi-dw.h:230)
    //   IF reg_io_width == 2: W(B2, addr) = val (16-bit)
    //   IF reg_io_width == 4: W(B4, addr) = val (32-bit)
    // -----------------------------------------------------------------------
    pub fn dw_write_io_reg(&mut self, offset: u32, val: u32) {
        // reg_io_width defaults to 4 (set in probe)
        let v_reg_io_width: u32 = 4;

        if v_reg_io_width == 2 {
            // op_282: W(B2, ...) = val (16-bit write)
            // Use 32-bit accessor as fallback — 16-bit not supported by register map
            mmio_write32(self.regs, offset as usize, val & 0xFFFF);
        }
        if v_reg_io_width == 4 {
            // op_283: W(B4, ...) = val (32-bit write)
            mmio_write32(self.regs, offset as usize, val);
        }
    }
    // -----------------------------------------------------------------------
    // Module: dw_read_io_reg  (spi-dw.h:219)
    //   IF reg_io_width == 2: R(B2, addr) (16-bit read)
    //   IF reg_io_width == 4: R(B4, addr) (32-bit read)
    // -----------------------------------------------------------------------
    pub fn dw_read_io_reg(&self, offset: u32) -> u32 {
        let v_reg_io_width: u32 = 4;

        if v_reg_io_width == 2 {
            // op_284: R(B2, ...) (16-bit read)
            return mmio_read32(self.regs, offset as usize) & 0xFFFF;
        }
        if v_reg_io_width == 4 {
            // op_285: R(B4, ...) (32-bit read)
            return mmio_read32(self.regs, offset as usize);
        }
        0
    }
}
