#include "dw_apb_ssi_baremetal.h"


/* ========================================================================
 * Static inline MMIO helpers (volatile pointer dereference)
 * ======================================================================== */

static inline uint8_t mmio_read8(uintptr_t addr)
{
    return *(volatile uint8_t *)addr;
}

static inline uint16_t mmio_read16(uintptr_t addr)
{
    return *(volatile uint16_t *)addr;
}

static inline uint32_t mmio_read32(uintptr_t addr)
{
    return *(volatile uint32_t *)addr;
}

static inline uint16_t mmio_read16be(uintptr_t addr)
{
    uint16_t v = *(volatile uint16_t *)addr;
    return ((v & 0x00ffU) << 8) | ((v & 0xff00U) >> 8);
}

static inline uint32_t mmio_read32be(uintptr_t addr)
{
    uint32_t v = *(volatile uint32_t *)addr;
    return ((v & 0x000000ffU) << 24) |
           ((v & 0x0000ff00U) << 8)  |
           ((v & 0x00ff0000U) >> 8)  |
           ((v & 0xff000000U) >> 24);
}

static inline void mmio_write8(uint8_t value, uintptr_t addr)
{
    *(volatile uint8_t *)addr = value;
}

static inline void mmio_write16(uint16_t value, uintptr_t addr)
{
    *(volatile uint16_t *)addr = value;
}

static inline void mmio_write32(uint32_t value, uintptr_t addr)
{
    *(volatile uint32_t *)addr = value;
}

static inline void mmio_write16be(uint16_t value, uintptr_t addr)
{
    uint16_t v = ((value & 0x00ffU) << 8) | ((value & 0xff00U) >> 8);
    *(volatile uint16_t *)addr = v;
}

static inline void mmio_write32be(uint32_t value, uintptr_t addr)
{
    uint32_t v = ((value & 0x000000ffU) << 24) |
                 ((value & 0x0000ff00U) << 8)  |
                 ((value & 0x00ff0000U) >> 8)  |
                 ((value & 0xff000000U) >> 24);
    *(volatile uint32_t *)addr = v;
}

static inline void mmio_write_w1c8(uint8_t value, uintptr_t addr)
{
    *(volatile uint8_t *)addr = value;
}

static inline void mmio_write_w1c16(uint16_t value, uintptr_t addr)
{
    *(volatile uint16_t *)addr = value;
}

static inline void mmio_write_w1c32(uint32_t value, uintptr_t addr)
{
    *(volatile uint32_t *)addr = value;
}

/* ========================================================================
 * Function prototypes
 *
 * Every parameter whose evidence type is DeviceState is rendered as
 * (struct dw_apb_ssi_priv *).  UInt → uint32_t, Void → void.
 * ======================================================================== */

/* spi-dw-core.c */

void dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);

uint32_t dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws);

uint32_t dw_spi_irq(uint32_t irq, struct dw_apb_ssi_priv *dev_id);

uint32_t dw_spi_transfer_one(struct dw_apb_ssi_priv *ctlr,
                             struct dw_apb_ssi_priv *spi,
                             struct dw_apb_ssi_priv *transfer);

void dw_spi_handle_err(struct dw_apb_ssi_priv *ctlr,
                       struct dw_apb_ssi_priv *msg);

uint32_t dw_spi_target_abort(struct dw_apb_ssi_priv *ctlr);

uint32_t dw_spi_exec_mem_op(struct dw_apb_ssi_priv *mem,
                            struct dw_apb_ssi_priv *op);

uint32_t dw_spi_setup(struct dw_apb_ssi_priv *spi);

void dw_spi_cleanup(struct dw_apb_ssi_priv *spi);

/* spi-dw-mmio.c */

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);

uint32_t dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *pdev,
                                  struct dw_apb_ssi_priv *dwsmmio);

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);

uint32_t dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_alpine_init(struct dw_apb_ssi_priv *pdev,
                            struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_hssi_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_intel_init(struct dw_apb_ssi_priv *pdev,
                           struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *pdev,
                                    struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);

uint32_t dw_spi_elba_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio);

uint32_t dw_spi_mmio_probe(struct dw_apb_ssi_priv *pdev);

uint32_t dw_spi_mmio_suspend(struct dw_apb_ssi_priv *dev);

uint32_t dw_spi_mmio_resume(struct dw_apb_ssi_priv *dev);

void dw_spi_mmio_remove(struct dw_apb_ssi_priv *pdev);

/* ========================================================================
 * REHARNESS_BAREMETAL_ORACLE — testing entry point
 * ======================================================================== */

#ifdef REHARNESS_BAREMETAL_ORACLE

#include <stddef.h>

/* Provide a default base address for the oracle if not externally set. */
#ifndef DW_APB_SSI_TEST_BASE
#define DW_APB_SSI_TEST_BASE  0x10000000UL
#endif

int main(void)
{
    struct dw_apb_ssi_priv dev;
    struct dw_apb_ssi_priv dev2;
    struct dw_apb_ssi_priv dev3;

    /* Zero-initialise all device structs. */
    dev.base  = (uintptr_t)DW_APB_SSI_TEST_BASE;
    dev2.base = (uintptr_t)DW_APB_SSI_TEST_BASE;
    dev3.base = (uintptr_t)DW_APB_SSI_TEST_BASE;

    /* --- spi-dw-core.c functions --- */

    dw_spi_set_cs(&dev, 0);
    dw_spi_set_cs(&dev, 1);

    (void)dw_spi_transfer_handler(&dev);

    (void)dw_spi_irq(0, &dev);

    (void)dw_spi_transfer_one(&dev, &dev2, &dev3);

    dw_spi_handle_err(&dev, &dev2);

    (void)dw_spi_target_abort(&dev);

    (void)dw_spi_exec_mem_op(&dev, &dev2);

    (void)dw_spi_setup(&dev);

    dw_spi_cleanup(&dev);

    /* --- spi-dw-mmio.c functions --- */

    dw_spi_mscc_set_cs(&dev, 0);
    dw_spi_mscc_set_cs(&dev, 1);

    (void)dw_spi_mscc_ocelot_init(&dev, &dev2);

    (void)dw_spi_mscc_jaguar2_init(&dev, &dev2);

    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_sparx5_set_cs(&dev, 1);

    (void)dw_spi_mscc_sparx5_init(&dev, &dev2);

    (void)dw_spi_alpine_init(&dev, &dev2);

    (void)dw_spi_hssi_init(&dev, &dev2);

    (void)dw_spi_intel_init(&dev, &dev2);

    (void)dw_spi_mountevans_imc_init(&dev, &dev2);

    (void)dw_spi_canaan_k210_init(&dev, &dev2);

    dw_spi_elba_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 1);

    (void)dw_spi_elba_init(&dev, &dev2);

    (void)dw_spi_mmio_probe(&dev);

    (void)dw_spi_mmio_suspend(&dev);

    (void)dw_spi_mmio_resume(&dev);

    dw_spi_mmio_remove(&dev);

    return 0;
}

#endif /* REHARNESS_BAREMETAL_ORACLE */

/* ---- part 01 of 03 ---- */
/* ========================================================================
 * Module function bodies — Part 1 of 4
 *
 * Modules: dw_spi_set_cs, dw_spi_transfer_handler
 *
 * Scaffold (includes, struct, helpers, prototypes, oracle main) is in
 * a separate file and must not be re-emitted.
 * ======================================================================== */

/* ------------------------------------------------------------------------
 * dw_spi_set_cs  (spi-dw-core.c:90)
 * ------------------------------------------------------------------------ */

void dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{
    /* The RIS uses dws->regs.DW_SPI_SER which maps to dws->base + offset */
    struct dw_apb_ssi_priv *dws = spi;
    uint32_t cs_high = 0; /* placeholder */

    if (cs_high == enable) {
        /* REHARNESS_RIS_OP op_1: W(B4, dws->regs.DW_SPI_SER) = (0x1 << spi_get_chipselect(spi, 0))
         * Config [Conservative] digest=80f430a0b4992e04
         * src: spi-dw.h:212 */
__rh_op_1: {
        mmio_write32((0x1 << 0), dws->base + DW_SPI_SER);
}
    }
    if ((cs_high == enable) == 0x0) {
        /* REHARNESS_RIS_OP op_2: W(B4, dws->regs.DW_SPI_SER) = 0x0
         * Init [Conservative] digest=baf8513c30b7be5b
         * src: spi-dw.h:212 */
__rh_op_2: {
        mmio_write32(0x0, dws->base + DW_SPI_SER);
}
    }
}

/* ------------------------------------------------------------------------
 * dw_spi_transfer_handler  (spi-dw-core.c:213)
 * ------------------------------------------------------------------------ */

uint32_t dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws)
{
    uint32_t irq_status;
    uint32_t ret;
    uint32_t new_mask = 0;
    uint32_t __return_read_0;
    uint32_t rxw = 0;
    uint32_t max;
    uint32_t tx_room;
    uint32_t txw;

    /* REHARNESS_RIS_OP op_3: irq_status := R(B4, dws->regs.DW_SPI_ISR)
     * Status [Exact] digest=1da529e7a809836c
     * src: spi-dw.h:207 */
__rh_op_3: {
    irq_status = mmio_read32(dws->base + DW_SPI_ISR);
}

    if (0 /* dw_spi_check_status(dws, false) */) {
        if (0x0) {
            /* REHARNESS_RIS_OP op_4: ret := R(B4, dws->regs.DW_SPI_RISR)
             * Status [Conservative] digest=f69675ec9835d413
             * src: spi-dw.h:207 */
__rh_op_4: {
            ret = mmio_read32(dws->base + DW_SPI_RISR);
}
        }
        if (0x0 == 0x0) {
            /* REHARNESS_RIS_OP op_5: ret := R(B4, dws->regs.DW_SPI_ISR)
             * Status [Conservative] digest=cc3597eae4a4ffcf
             * src: spi-dw.h:207 */
__rh_op_5: {
            ret = mmio_read32(dws->base + DW_SPI_ISR);
}
        }
        if (ret) {
            /* REHARNESS_RIS_OP op_6: W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0)
             * Interrupt [Conservative] digest=6b1f7c3c7aff2599
             * src: spi-dw.h:212 */
__rh_op_6: {
            mmio_write32((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
}
            /* REHARNESS_RIS_OP op_7: __return_read_0 := R(B4, dws->regs.DW_SPI_IMR)
             * Status [Conservative] digest=3485f4c43857a432
             * src: spi-dw.h:207 */
__rh_op_7: {
            __return_read_0 = mmio_read32(dws->base + DW_SPI_IMR);
}
            /* REHARNESS_RIS_OP op_8: W(B4, dws->regs.DW_SPI_IMR) = new_mask
             * Config [Conservative] digest=d8f3ef33fb01544e
             * src: spi-dw.h:212 */
__rh_op_8: {
            mmio_write32(new_mask, dws->base + DW_SPI_IMR);
}
            /* REHARNESS_RIS_OP op_9: __return_read_0 := R(B4, dws->regs.DW_SPI_ICR)
             * Status [Conservative] digest=484f59ac79ec2a84
             * src: spi-dw.h:207 */
__rh_op_9: {
            __return_read_0 = mmio_read32(dws->base + DW_SPI_ICR);
}
            /* REHARNESS_RIS_OP op_10: W(B4, dws->regs.DW_SPI_SER) = 0x0
             * Config [Conservative] digest=02bf20c4b2910e68
             * src: spi-dw.h:212 */
__rh_op_10: {
            mmio_write32(0x0, dws->base + DW_SPI_SER);
}
            /* REHARNESS_RIS_OP op_11: W(B4, dws->regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0)
             * Interrupt [Conservative] digest=dfd1fa2d71073b6b
             * src: spi-dw.h:212 */
__rh_op_11: {
            mmio_write32((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
}
            if (0 /* dws->ctlr->cur_msg */) {
                /* REHARNESS_RIS_OP op_12: STATE(dws->ctlr->cur_msg->status) := ret
                 * [Conservative]
                 * src: spi-dw-core.c:206 */
__rh_op_12: {
                /* dws->ctlr->cur_msg->status = ret; */
}
            }
        }
    }

    /* REHARNESS_RIS_OP op_13: __return_read_0 := R(B4, dws->regs.DW_SPI_RXFLR)
     * DataTransfer [Exact] digest=143382d23f314b96
     * src: spi-dw.h:207 */
__rh_op_13: {
    __return_read_0 = mmio_read32(dws->base + DW_SPI_RXFLR);
}

    /* LOOP while max-- (count=max; relation=post-decrement; bounded) [Exact] */
    max = __return_read_0; /* RXFLR read provides the loop count */
    while (max--) {
        uint32_t r14 = 0;
        uint32_t r15 = 0;

        if (0 /* dws->reg_io_width == 0x2 */) {
            /* REHARNESS_RIS_OP op_14: r14 := R(B2, 0x0)
             * Status [Conservative] digest=8b4a46336bcb6168
             * src: spi-dw.h:219 */
__rh_op_14: {
            r14 = mmio_read16(0x0);
}
        }
        if (0 /* dws->reg_io_width == 0x4 */) {
            /* REHARNESS_RIS_OP op_15: r15 := R(B4, 0x0)
             * Status [Conservative] digest=88533cfff9f6ba43
             * src: spi-dw.h:222 */
__rh_op_15: {
            r15 = mmio_read32(0x0);
}
        }
        if (0 /* dws->rx */) {
            if (0 /* dws->n_bytes == 0x1 */) {
                /* REHARNESS_RIS_OP op_16: OUT(*(u8 *)(dws->rx)) := rxw
                 * [Conservative]
                 * src: spi-dw-core.c:165 */
__rh_op_16: {
                /* *(uint8_t *)(dws->rx) = (uint8_t)rxw; */
}
            }
            if ((0 /* dws->n_bytes == 0x1 */) == 0x0) {
                if (0 /* dws->n_bytes == 0x2 */) {
                    /* REHARNESS_RIS_OP op_17: OUT(*(u16 *)(dws->rx)) := rxw
                     * [Conservative]
                     * src: spi-dw-core.c:167 */
__rh_op_17: {
                    /* *(uint16_t *)(dws->rx) = (uint16_t)rxw; */
}
                }
                if ((0 /* dws->n_bytes == 0x2 */) == 0x0) {
                    /* REHARNESS_RIS_OP op_18: OUT(*(u32 *)(dws->rx)) := rxw
                     * [Conservative]
                     * src: spi-dw-core.c:169 */
__rh_op_18: {
                    /* *(uint32_t *)(dws->rx) = rxw; */
}
                }
            }
            /* REHARNESS_RIS_OP op_19: STATE(dws->rx) := (dws->rx + dws->n_bytes)
             * [Conservative]
             * src: spi-dw-core.c:171 */
__rh_op_19: {
            /* dws->rx = (void *)((uintptr_t)dws->rx + dws->n_bytes); */
}
        }
        /* REHARNESS_RIS_OP op_20: STATE(dws->rx_len) := (dws->rx_len + -1)
         * [Conservative]
         * src: spi-dw-core.c:173 */
__rh_op_20: {
        /* dws->rx_len = dws->rx_len - 1; */
}
        (void)r14;
        (void)r15;
    }

    if (0 /* dws->rx_len == 0x0 */) {
        /* REHARNESS_RIS_OP op_21: __return_read_0 := R(B4, dws->regs.DW_SPI_IMR)
         * Status [Conservative] digest=3485f4c43857a432
         * src: spi-dw.h:207 */
__rh_op_21: {
        __return_read_0 = mmio_read32(dws->base + DW_SPI_IMR);
}
        /* REHARNESS_RIS_OP op_22: W(B4, dws->regs.DW_SPI_IMR) = new_mask
         * Config [Conservative] digest=d8f3ef33fb01544e
         * src: spi-dw.h:212 */
__rh_op_22: {
        mmio_write32(new_mask, dws->base + DW_SPI_IMR);
}
    }

    if ((0 /* dws->rx_len == 0x0 */) == 0x0) {
        /* REHARNESS_RIS_OP op_23: __return_read_0 := R(B4, dws->regs.DW_SPI_RXFTLR)
         * DataTransfer [Conservative] digest=19789ced0ff377bf
         * src: spi-dw.h:207 */
__rh_op_23: {
        __return_read_0 = mmio_read32(dws->base + DW_SPI_RXFTLR);
}
        if (0 /* dws->rx_len <= dw_readl(dws, DW_SPI_RXFTLR) */) {
            /* REHARNESS_RIS_OP op_24: W(B4, dws->regs.DW_SPI_RXFTLR) = (dws->rx_len - 0x1)
             * DataTransfer [Conservative] digest=048897f03058f8c8
             * src: spi-dw.h:212 */
__rh_op_24: {
            mmio_write32((0 /* dws->rx_len */ - 0x1), dws->base + DW_SPI_RXFTLR);
}
        }
    }

    if (irq_status & 0x1) {
        /* REHARNESS_RIS_OP op_25: tx_room := R(B4, dws->regs.DW_SPI_TXFLR)
         * DataTransfer [Conservative] digest=d5ec643b5880dd09
         * src: spi-dw.h:207 */
__rh_op_25: {
        tx_room = mmio_read32(dws->base + DW_SPI_TXFLR);
}
        /* REHARNESS_RIS_OP op_26: txw := VALUE(0x0)
         * [Conservative]
         * src: spi-dw-core.c:138 */
__rh_op_26: {
        txw = 0x0;
}
        /* LOOP while max-- (count=max; relation=post-decrement; bounded) [Exact] */
        max = tx_room;
        while (max--) {
            if (0 /* dws->tx */) {
                if (0 /* dws->n_bytes == 0x1 */) {
                    /* REHARNESS_RIS_OP op_27: txw := VALUE(*(u8 *)(dws->tx))
                     * [Conservative]
                     * src: spi-dw-core.c:143 */
__rh_op_27: {
                    /* txw = *(uint8_t *)(dws->tx); */
}
                }
                if ((0 /* dws->n_bytes == 0x1 */) == 0x0) {
                    if (0 /* dws->n_bytes == 0x2 */) {
                        /* REHARNESS_RIS_OP op_28: txw := VALUE(*(u16 *)(dws->tx))
                         * [Conservative]
                         * src: spi-dw-core.c:145 */
__rh_op_28: {
                        /* txw = *(uint16_t *)(dws->tx); */
}
                    }
                    if ((0 /* dws->n_bytes == 0x2 */) == 0x0) {
                        /* REHARNESS_RIS_OP op_29: txw := VALUE(*(u32 *)(dws->tx))
                         * [Conservative]
                         * src: spi-dw-core.c:147 */
__rh_op_29: {
                        /* txw = *(uint32_t *)(dws->tx); */
}
                    }
                }
                /* REHARNESS_RIS_OP op_30: STATE(dws->tx) := (dws->tx + dws->n_bytes)
                 * [Conservative]
                 * src: spi-dw-core.c:149 */
__rh_op_30: {
                /* dws->tx = (void *)((uintptr_t)dws->tx + dws->n_bytes); */
}
            }
            if (0 /* dws->reg_io_width == 0x2 */) {
                /* REHARNESS_RIS_OP op_31: W(B2, 0x0) = \top
                 * Config [Unknown] digest=112457f059093b11
                 * src: spi-dw.h:230 */
__rh_op_31: {
                mmio_write16(0 /* \top placeholder */, 0x0);
}
            }
            if (0 /* dws->reg_io_width == 0x4 */) {
                /* REHARNESS_RIS_OP op_32: W(B4, 0x0) = \top
                 * Config [Unknown] digest=c05dc6f3255038c0
                 * src: spi-dw.h:234 */
__rh_op_32: {
                mmio_write32(0 /* \top placeholder */, 0x0);
}
            }
            /* REHARNESS_RIS_OP op_33: STATE(dws->tx_len) := (dws->tx_len + -1)
             * [Conservative]
             * src: spi-dw-core.c:152 */
__rh_op_33: {
            /* dws->tx_len = dws->tx_len - 1; */
}
        }

        if (0 /* dws->tx_len == 0x0 */) {
            /* REHARNESS_RIS_OP op_34: __return_read_0 := R(B4, dws->regs.DW_SPI_IMR)
             * Status [Conservative] digest=3485f4c43857a432
             * src: spi-dw.h:207 */
__rh_op_34: {
            __return_read_0 = mmio_read32(dws->base + DW_SPI_IMR);
}
            /* REHARNESS_RIS_OP op_35: W(B4, dws->regs.DW_SPI_IMR) = new_mask
             * Config [Conservative] digest=d8f3ef33fb01544e
             * src: spi-dw.h:212 */
__rh_op_35: {
            mmio_write32(new_mask, dws->base + DW_SPI_IMR);
}
        }
    }

    (void)rxw;
    (void)txw;
    return __return_read_0;
}

/* ---- part 02 of 03 ---- */
/* ==========================================================================
 * dw-apb-ssi driver — Part 2 of 4
 * Module function bodies for:
 *   dw_spi_sparx5_set_cs
 *   dw_spi_mscc_sparx5_init
 *   dw_spi_alpine_init
 *   dw_spi_hssi_init
 *   dw_spi_intel_init
 *
 * This file expects the scaffold (struct dw_apb_ssi_priv, mmio helpers,
 * register macros, prototypes) to already be visible via inclusion.
 * ==========================================================================*/

/* -------------------------------------------------------------------------
 * module dw_spi_sparx5_set_cs
 * source: spi-dw-mmio.c:148
 * -------------------------------------------------------------------------*/
void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{
    /* op_181: dwsmscc := VALUE(dwsmmio->priv) [Exact]
     * spi-dw-mmio.c:152 */
    /* REHARNESS_RIS_OP op_181 Conservative digest= — STATE */
    __rh_op_181: {
        void *dwsmscc = (void *)0;  /* VALUE(dwsmmio->priv) */
        (void)dwsmscc;
    }

    uint32_t cs = 0;
    uint32_t cs_high = 0;

    /* op_182: TXWRITE[regmap] dwsmscc->syscon@SPARX5_FORCE_ENA
     *   {'Scalar': {'width': 'Unknown', 'value': {'Const': 1}}}
     *   [Conservative] digest=205f308e0f9e09e8  spi-dw-mmio.c:157 */
    if (enable == 0x0) {
        /* REHARNESS_RIS_OP op_182 Conservative digest=205f308e0f9e09e8 */
        __rh_op_182: {
            /* regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 1) */
        }

        /* op_183: TXWRITE[regmap] dwsmscc->syscon@SPARX5_FORCE_VAL
         *   {'Scalar': {'width': 'Unknown', 'value': {'BinOp': {'op': 'BitXor',
         *    'left': {'BinOp': {'op': 'Shl', 'left': {'Const': 1},
         *     'right': {'Var': 'cs'}}}, 'right': {'Const': 4294967295}}}}}
         *   [Conservative] digest=e0a7b055c6ad8a24  spi-dw-mmio.c:159 */
        /* REHARNESS_RIS_OP op_183 Conservative digest=e0a7b055c6ad8a24 */
        __rh_op_183: {
            uint32_t val = (1u << cs) ^ 4294967295u;
            (void)val;
            /* regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL, val) */
        }
    }

    /* op_184: TXWRITE[regmap] dwsmscc->syscon@SPARX5_FORCE_VAL
     *   {'Scalar': {'width': 'Unknown', 'value': {'BinOp': {'op': 'BitXor',
     *    'left': {'Const': 0}, 'right': {'Const': 4294967295}}}}}
     *   [Conservative] digest=8164bafcc13cbb61  spi-dw-mmio.c:164 */
    if ((enable == 0x0) == 0x0) {
        /* REHARNESS_RIS_OP op_184 Conservative digest=8164bafcc13cbb61 */
        __rh_op_184: {
            uint32_t val = 0u ^ 4294967295u;
            (void)val;
            /* regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL, val) */
        }

        /* op_185: TXWRITE[regmap] dwsmscc->syscon@SPARX5_FORCE_ENA
     *   {'Scalar': {'width': 'Unknown', 'value': {'Const': 0}}}
     *   [Conservative] digest=442f3ce583e95677  spi-dw-mmio.c:168 */
        /* REHARNESS_RIS_OP op_185 Conservative digest=442f3ce583e95677 */
        __rh_op_185: {
            /* regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 0) */
        }
    }

    /* op_186: W(B4, dws->regs.DW_SPI_SER) =
     *   (0x1 << spi_get_chipselect(spi, 0)) -- Config
     *   [Conservative] digest=80f430a0b4992e04  spi-dw.h:212 */
    if (cs_high == enable) {
        /* REHARNESS_RIS_OP op_186 Conservative digest=80f430a0b4992e04 */
        __rh_op_186: {
            uint32_t cs_index = 0; /* spi_get_chipselect(spi, 0) */
            mmio_write32((0x1u << cs_index), spi->base + DW_SPI_SER);
        }
    }

    /* op_187: W(B4, dws->regs.DW_SPI_SER) = 0x0 -- Init
     *   [Conservative] digest=baf8513c30b7be5b  spi-dw.h:212 */
    if ((cs_high == enable) == 0x0) {
        /* REHARNESS_RIS_OP op_187 Conservative digest=baf8513c30b7be5b */
        __rh_op_187: {
            mmio_write32(0x0u, spi->base + DW_SPI_SER);
        }
    }
}

/* -------------------------------------------------------------------------
 * module dw_spi_mscc_sparx5_init
 * source: spi-dw-mmio.c:174
 * -------------------------------------------------------------------------*/
uint32_t dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio)
{
    /* op_188: syscon_name := VALUE(("microchip,sparx5 - cpu) - syscon")) [Exact]
     * spi-dw-mmio.c:177 */
    /* REHARNESS_RIS_OP op_188 Exact digest= — STATE */
    __rh_op_188: {
        const char *syscon_name = "microchip,sparx5 - cpu) - syscon";
        (void)syscon_name;
    }

    /* op_189: dev := VALUE(&pdev->dev) [Exact]
     * spi-dw-mmio.c:178 */
    /* REHARNESS_RIS_OP op_189 Exact digest= — STATE */
    __rh_op_189: {
        struct dw_apb_ssi_priv *dev = pdev; /* &pdev->dev */
        (void)dev;
    }

    /* op_190: STATE(dwsmmio->dws.set_cs) := dw_spi_sparx5_set_cs [Exact]
     * spi-dw-mmio.c:197 */
    /* REHARNESS_RIS_OP op_190 Exact digest= — STATE */
    __rh_op_190: {
        /* dwsmmio->dws.set_cs = dw_spi_sparx5_set_cs; */
    }

    /* op_191: STATE(dwsmmio->priv) := dwsmscc [Exact]
     * spi-dw-mmio.c:198 */
    /* REHARNESS_RIS_OP op_191 Exact digest= — STATE */
    __rh_op_191: {
        /* dwsmmio->priv = dwsmscc; */
    }

    return 0;
}

/* -------------------------------------------------------------------------
 * module dw_spi_alpine_init
 * source: spi-dw-mmio.c:203
 * -------------------------------------------------------------------------*/
uint32_t dw_spi_alpine_init(struct dw_apb_ssi_priv *pdev,
                            struct dw_apb_ssi_priv *dwsmmio)
{
    /* op_192: STATE(dwsmmio->dws.caps) := 0x1 [Exact]
     * spi-dw-mmio.c:206 */
    /* REHARNESS_RIS_OP op_192 Exact digest= — STATE */
    __rh_op_192: {
        /* dwsmmio->dws.caps = 0x1; */
    }

    (void)pdev;
    (void)dwsmmio;
    return 0;
}

/* -------------------------------------------------------------------------
 * module dw_spi_hssi_init
 * source: spi-dw-mmio.c:219
 * -------------------------------------------------------------------------*/
uint32_t dw_spi_hssi_init(struct dw_apb_ssi_priv *pdev,
                          struct dw_apb_ssi_priv *dwsmmio)
{
    /* op_193: STATE(dwsmmio->dws.ip) := 0x1 [Exact]
     * spi-dw-mmio.c:222 */
    /* REHARNESS_RIS_OP op_193 Exact digest= — STATE */
    __rh_op_193: {
        /* dwsmmio->dws.ip = 0x1; */
    }

    (void)pdev;
    (void)dwsmmio;
    return 0;
}

/* -------------------------------------------------------------------------
 * module dw_spi_intel_init
 * source: spi-dw-mmio.c:229
 * -------------------------------------------------------------------------*/
uint32_t dw_spi_intel_init(struct dw_apb_ssi_priv *pdev,
                           struct dw_apb_ssi_priv *dwsmmio)
{
    /* op_194: STATE(dwsmmio->dws.ip) := 0x1 [Exact]
     * spi-dw-mmio.c:232 */
    /* REHARNESS_RIS_OP op_194 Exact digest= — STATE */
    __rh_op_194: {
        /* dwsmmio->dws.ip = 0x1; */
    }

    (void)pdev;
    (void)dwsmmio;
    return 0;
}

/* ---- part 03 of 03 ---- */
/* =========================================================================
 * dw-apb-ssi — Module function bodies (PART 3 of 4)
 *
 * This part emits the bodies for:
 *   - dw_spi_mmio_resume
 *   - dw_spi_mmio_remove
 *
 * The scaffold (includes, struct, primitives, prototypes) is in a separate
 * file and must not be repeated here.
 * ========================================================================= */

/* -------------------------------------------------------------------------
 * dw_spi_mmio_resume
 * Source: spi-dw-mmio.c:410
 * RIS module: dw_spi_mmio_resume
 * ------------------------------------------------------------------------- */
uint32_t dw_spi_mmio_resume(struct dw_apb_ssi_priv *dev)
{
    /* dev->base is the bound form of dwsmmio->dws.regs base */

    /* REHARNESS_RIS_OP op_261 digest=1d27a789973c926d
     * W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config
     */
    if (0) goto __rh_op_261;
    __rh_op_261: {
        mmio_write32((0x0 ? 0x1U : 0x0U), dev->base + DW_SPI_SSIENR);
    }

    /* REHARNESS_RIS_OP op_262 digest=2757833ac7c49d6e
     * __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_IMR) -- Status
     */
    if (0) goto __rh_op_262;
    __rh_op_262: {
        uint32_t __return_read_0 = mmio_read32(dev->base + DW_SPI_IMR);
        (void)__return_read_0;
    }

    /* REHARNESS_RIS_OP op_263 digest=8e770f91d3bf2125
     * W(B4, dwsmmio->dws.regs.DW_SPI_IMR) = new_mask -- Config
     */
    if (0) goto __rh_op_263;
    __rh_op_263: {
        uint32_t new_mask = 0;
        mmio_write32(new_mask, dev->base + DW_SPI_IMR);
    }

    /* REHARNESS_RIS_OP op_264 digest=4c5110b15dd96366
     * __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_ICR) -- Status
     */
    if (0) goto __rh_op_264;
    __rh_op_264: {
        uint32_t __return_read_0 = mmio_read32(dev->base + DW_SPI_ICR);
        (void)__return_read_0;
    }

    /* REHARNESS_RIS_OP op_265 digest=0fd5609f15e4b074
     * W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0x0 -- Init
     */
    if (0) goto __rh_op_265;
    __rh_op_265: {
        mmio_write32(0x0, dev->base + DW_SPI_SER);
    }

    /* REHARNESS_RIS_OP op_266 digest=4645554fd623d2f9
     * W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config
     */
    if (0) goto __rh_op_266;
    __rh_op_266: {
        mmio_write32((0x1 ? 0x1U : 0x0U), dev->base + DW_SPI_SSIENR);
    }

    /* IF (dwsmmio->dws.ver == 0x0) */
    {
        uint32_t ver = 0;
        if (ver == 0x0) {
            /* REHARNESS_RIS_OP op_267 digest=49e526b8e39e5d1e
             * dwsmmio->dws.ver := R(B4, dwsmmio->dws.regs.DW_SPI_VERSION) -- Status
             */
            if (0) goto __rh_op_267;
            __rh_op_267: {
                ver = mmio_read32(dev->base + DW_SPI_VERSION);
            }
        }
    }

    /* IF spi_controller_is_target(dwsmmio->dws.ctlr) */
    {
        uint32_t is_target = 0;
        if (is_target) {
            /* @op_268 STATE(dwsmmio->dws.num_cs) := 0x1 */
            if (0) goto __rh_op_268;
            __rh_op_268: {
                uint32_t num_cs = 0x1;
                (void)num_cs;
            }
        }

        /* IF (spi_controller_is_target(dwsmmio->dws.ctlr) == 0x0) */
        if ((is_target == 0x0)) {
            uint32_t num_cs = 0;
            if (num_cs == 0x0) {
                /* REHARNESS_RIS_OP op_269 digest=6a51a80674242213
                 * W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0xffff -- Config
                 */
                if (0) goto __rh_op_269;
                __rh_op_269: {
                    mmio_write32(0xffff, dev->base + DW_SPI_SER);
                }

                /* REHARNESS_RIS_OP op_270 digest=a239c0939dd0a923
                 * ser := R(B4, dwsmmio->dws.regs.DW_SPI_SER) -- Status
                 */
                if (0) goto __rh_op_270;
                __rh_op_270: {
                    uint32_t ser = mmio_read32(dev->base + DW_SPI_SER);
                    (void)ser;
                }

                /* REHARNESS_RIS_OP op_271 digest=db1ac64c51360b0f
                 * W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0x0 -- Init
                 */
                if (0) goto __rh_op_271;
                __rh_op_271: {
                    mmio_write32(0x0, dev->base + DW_SPI_SER);
                }
            }
        }
    }

    /* IF (dwsmmio->dws.fifo_len == 0x0) */
    {
        uint32_t fifo_len = 0;
        if (fifo_len == 0x0) {
            uint32_t fifo;

            /* LOOP for (fifo < 0x100) (init=fifo = 1; step=fifo++; count=0xff; bounded) */
            for (fifo = 1; fifo < 0x100; fifo++) {
                /* REHARNESS_RIS_OP op_272 digest=6037756f276501ed
                 * W(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) = fifo -- DataTransfer
                 */
                if (0) goto __rh_op_272;
                __rh_op_272: {
                    mmio_write32(fifo, dev->base + DW_SPI_TXFTLR);
                }

                /* REHARNESS_RIS_OP op_273 digest=a8a7738fe0a45411
                 * __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) -- DataTransfer
                 */
                if (0) goto __rh_op_273;
                __rh_op_273: {
                    uint32_t __return_read_0 = mmio_read32(dev->base + DW_SPI_TXFTLR);
                    (void)__return_read_0;
                }
            }

            /* REHARNESS_RIS_OP op_274 digest=3cd05c0ba585bb18
             * W(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) = 0x0 -- Init
             */
            if (0) goto __rh_op_274;
            __rh_op_274: {
                mmio_write32(0x0, dev->base + DW_SPI_TXFTLR);
            }

            /* @op_275 STATE(dwsmmio->dws.fifo_len) := ((fifo == 0x1) ? 0x0 : fifo) */
            if (0) goto __rh_op_275;
            __rh_op_275: {
                fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
            }
        }
    }

    /* IF dw_spi_ip_is(&dwsmmio->dws, PSSI) */
    {
        uint32_t is_pssi = 1; /* Conservative: assume PSSI */
        if (is_pssi) {
            uint32_t cr0 = 0;
            uint32_t tmp = 0;

            /* REHARNESS_RIS_OP op_276 digest=71b0f6a0db7be122
             * __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) -- Config
             */
            if (0) goto __rh_op_276;
            __rh_op_276: {
                uint32_t __return_read_0 = mmio_read32(dev->base + DW_SPI_CTRLR0);
                (void)__return_read_0;
            }

            /* REHARNESS_RIS_OP op_277 digest=ee759e5532a5c896
             * W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config
             */
            if (0) goto __rh_op_277;
            __rh_op_277: {
                mmio_write32((0x0 ? 0x1U : 0x0U), dev->base + DW_SPI_SSIENR);
            }

            /* REHARNESS_RIS_OP op_278 digest=84550cb99b28c1bc
             * W(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) = 0xffffffff -- Config
             */
            if (0) goto __rh_op_278;
            __rh_op_278: {
                mmio_write32(0xffffffff, dev->base + DW_SPI_CTRLR0);
            }

            /* REHARNESS_RIS_OP op_279 digest=e90c69b23aba4a3e
             * cr0 := R(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) -- Config
             */
            if (0) goto __rh_op_279;
            __rh_op_279: {
                cr0 = mmio_read32(dev->base + DW_SPI_CTRLR0);
            }

            /* REHARNESS_RIS_OP op_280 digest=18b2cc7c88f3fcf8
             * W(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) = tmp -- Config
             */
            if (0) goto __rh_op_280;
            __rh_op_280: {
                mmio_write32(tmp, dev->base + DW_SPI_CTRLR0);
            }

            /* REHARNESS_RIS_OP op_281 digest=6b94649b35e76f3b
             * W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config
             */
            if (0) goto __rh_op_281;
            __rh_op_281: {
                mmio_write32((0x1 ? 0x1U : 0x0U), dev->base + DW_SPI_SSIENR);
            }

            /* IF ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) */
            {
                uint32_t DW_PSSI_CTRLR0_DFS_MASK = 0xff;
                if ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) {
                    /* @op_282 STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
                    if (0) goto __rh_op_282;
                    __rh_op_282: {
                        uint32_t caps = 0;
                        caps = (caps | 0x2);
                    }
                }
            }
        }

        /* IF (dw_spi_ip_is(&dwsmmio->dws, PSSI) == 0x0) */
        if ((is_pssi == 0x0)) {
            /* @op_283 STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
            if (0) goto __rh_op_283;
            __rh_op_283: {
                uint32_t caps = 0;
                caps = (caps | 0x2);
            }
        }
    }

    /* IF (dwsmmio->dws.caps & 0x1) */
    {
        uint32_t caps = 0;
        if (caps & 0x1) {
            /* REHARNESS_RIS_OP op_284 digest=5fc38aeec53b0756
             * W(B4, dwsmmio->dws.regs.DW_SPI_CS_OVERRIDE) = 0xf -- Config
             */
            if (0) goto __rh_op_284;
            __rh_op_284: {
                mmio_write32(0xf, dev->base + DW_SPI_CS_OVERRIDE);
            }
        }
    }

    return 0;
}

/* -------------------------------------------------------------------------
 * dw_spi_mmio_remove
 * Source: spi-dw-mmio.c:425
 * RIS module: dw_spi_mmio_remove
 * ------------------------------------------------------------------------- */
void dw_spi_mmio_remove(struct dw_apb_ssi_priv *dev)
{
    /* dev->base is the bound form of dwsmmio->dws.regs base */

    /* REHARNESS_RIS_OP op_285 digest=1d27a789973c926d
     * W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config
     */
    if (0) goto __rh_op_285;
    __rh_op_285: {
        mmio_write32((0x0 ? 0x1U : 0x0U), dev->base + DW_SPI_SSIENR);
    }

    /* REHARNESS_RIS_OP op_286 digest=daa9d26d9fd723fa
     * W(B4, dwsmmio->dws.regs.DW_SPI_BAUDR) = 0x0 -- Power
     */
    if (0) goto __rh_op_286;
    __rh_op_286: {
        mmio_write32(0x0, dev->base + DW_SPI_BAUDR);
    }
}