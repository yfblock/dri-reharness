#include "dw_apb_ssi_baremetal.h"


/**
 * struct dw_spi_mmio – MMIO-glue private state.
 * Mirrors the upstream struct dw_spi_mmio from spi-dw-mmio.c.
 * Wraps the core dw_spi and carries per-SoC init / set_cs callbacks.
 */
struct dw_spi_mmio {
    struct dw_spi  dws;             /* core DW APB SSI state */

    /* Per-SoC overrides set by of_device_id.data */
    void    (*cs_override_set)(struct dw_spi_mmio *dwsmmio, int enable);
    int     (*init_func)(struct dw_spi_mmio *dwsmmio);

    /* Optional secondary MMIO region (MSCC / Sparx5 system controller) */
    uintptr_t   sys_mapbase;       /* secondary MMIO base */
    uint32_t    sys_mode_reg;     /* cached MSCC_SPI_MST_SW_MODE value */

    /* Sparx5-specific */
    uint32_t    sparx5_cs_count;
    uint32_t    sparx5_cs_oe[4];

    /* Intel / Alpine / HSSI / MountEvans / Canaan K210 / Elba */
    uint32_t    intel_scyc;        /* Intel SSI clock control */
    uint32_t    hssi_cs_map;       /* HSSI chip-select mapping */
    uint32_t    elba_cs_shift;     /* Elba CS override bit shift */
    uint32_t    elba_cs_active;    /* Elba CS active polarity */

    /* Canaan K210 clock divisor */
    uint32_t    k210_clk_div;

    /* MountEvans IMC specific */
    uint32_t    mountevans_imc_ver;
};

/* Convenience alias: module bodies use `struct dw_spi_priv` */
#define dw_apb_ssi_priv   dw_spi_mmio

/* =====================================================================
 * Static prototypes for every evidence.functions entry.
 * Parameter types from bind.types:
 *   DeviceState → struct dw_spi_mmio (alias of dw_apb_ssi_priv)
 *   UInt        → uint32_t
 *   Void        → void
 * ===================================================================== */

/* spi-dw-core.c */

static void dw_spi_set_cs(struct dw_spi_mmio *spi, uint32_t enable);

static uint32_t dw_spi_transfer_handler(struct dw_spi_mmio *dws);

static uint32_t dw_spi_irq(uint32_t irq, struct dw_spi_mmio *dev_id);

static uint32_t dw_spi_transfer_one(struct dw_spi_mmio *ctlr,
                                   struct dw_spi_mmio *spi,
                                   struct dw_spi_mmio *transfer);

static void dw_spi_handle_err(struct dw_spi_mmio *ctlr,
                             struct dw_spi_mmio *msg);

static uint32_t dw_spi_target_abort(struct dw_spi_mmio *ctlr);

static uint32_t dw_spi_exec_mem_op(struct dw_spi_mmio *mem,
                                  struct dw_spi_mmio *op);

static uint32_t dw_spi_setup(struct dw_spi_mmio *spi);

static void dw_spi_cleanup(struct dw_spi_mmio *spi);

/* spi-dw-mmio.c */

static void dw_spi_mscc_set_cs(struct dw_spi_mmio *spi, uint32_t enable);

uint32_t dw_spi_mscc_ocelot_init(struct dw_spi_mmio *pdev,
                                 struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_mscc_jaguar2_init(struct dw_spi_mmio *pdev,
                                  struct dw_spi_mmio *dwsmmio);

void dw_spi_sparx5_set_cs(struct dw_spi_mmio *spi, uint32_t enable);

uint32_t dw_spi_mscc_sparx5_init(struct dw_spi_mmio *pdev,
                                 struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_alpine_init(struct dw_spi_mmio *pdev,
                            struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_hssi_init(struct dw_spi_mmio *pdev,
                          struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_intel_init(struct dw_spi_mmio *pdev,
                           struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_mountevans_imc_init(struct dw_spi_mmio *pdev,
                                    struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_canaan_k210_init(struct dw_spi_mmio *pdev,
                                 struct dw_spi_mmio *dwsmmio);

void dw_spi_elba_set_cs(struct dw_spi_mmio *spi, uint32_t enable);

uint32_t dw_spi_elba_init(struct dw_spi_mmio *pdev,
                          struct dw_spi_mmio *dwsmmio);

uint32_t dw_spi_mmio_probe(struct dw_spi_mmio *pdev);

uint32_t dw_spi_mmio_suspend(struct dw_spi_mmio *dev);

uint32_t dw_spi_mmio_resume(struct dw_spi_mmio *dev);

void dw_spi_mmio_remove(struct dw_spi_mmio *pdev);

/* =====================================================================
 * Bare-metal oracle entry point.
 *
 * Instantiates the device with zero-initialized / plausible defaults and
 * calls every evidence function in order.
 * ===================================================================== */

#ifdef REHARNESS_BAREMETAL_ORACLE

#include <stdio.h>

int main(void)
{
    /* Allocate device state on the stack (freestanding, no malloc needed). */
    static struct dw_spi_mmio  st_mmio;
    struct dw_spi_mmio *dwsmmio = &st_mmio;
    struct dw_spi_mmio *pdev = &st_mmio;
    struct dw_spi_mmio *spi = &st_mmio;
    struct dw_spi_mmio *ctlr = &st_mmio;
    struct dw_spi_mmio *transfer = &st_mmio;
    struct dw_spi_mmio *msg = &st_mmio;
    struct dw_spi_mmio *mem = &st_mmio;
    struct dw_spi_mmio *op = &st_mmio;
    struct dw_spi_mmio *dws = &st_mmio;
    struct dw_spi_mmio *dev = &st_mmio;

    /* Zero-initialise the whole struct. */
    *dwsmmio = (struct dw_spi_mmio){0};

    /* Plausible defaults: set a base address for MMIO so helpers work. */
    dwsmmio->dws.base = (uintptr_t)0x10000000u;
    dwsmmio->dws.irq = 42u;
    dwsmmio->dws.fifo_len = 32u;
    dwsmmio->dws.rx_fifo_len = 32u;
    dwsmmio->dws.max_freq = 50000000u;
    dwsmmio->dws.current_freq = 25000000u;
    dwsmmio->dws.num_cs = 4u;
    dwsmmio->dws.reg_width = 4u;
    dwsmmio->dws.n_bytes = 1u;
    dwsmmio->dws.dws_version = 0x3332340au;  /* v2.34a */

    uint32_t enable = 1u;
    uint32_t irq = dwsmmio->dws.irq;

    /* Call every evidence function in source order. */

    /* spi-dw-core.c functions */
    dw_spi_set_cs(spi, enable);
    dw_spi_transfer_handler(dws);
    dw_spi_irq(irq, dws);
    dw_spi_transfer_one(ctlr, spi, transfer);
    dw_spi_handle_err(ctlr, msg);
    dw_spi_target_abort(ctlr);
    dw_spi_exec_mem_op(mem, op);
    dw_spi_setup(spi);
    dw_spi_cleanup(spi);

    /* spi-dw-mmio.c functions */
    dw_spi_mscc_set_cs(spi, enable);
    dw_spi_mscc_ocelot_init(pdev, dwsmmio);
    dw_spi_mscc_jaguar2_init(pdev, dwsmmio);
    dw_spi_sparx5_set_cs(spi, enable);
    dw_spi_mscc_sparx5_init(pdev, dwsmmio);
    dw_spi_alpine_init(pdev, dwsmmio);
    dw_spi_hssi_init(pdev, dwsmmio);
    dw_spi_intel_init(pdev, dwsmmio);
    dw_spi_mountevans_imc_init(pdev, dwsmmio);
    dw_spi_canaan_k210_init(pdev, dwsmmio);
    dw_spi_elba_set_cs(spi, enable);
    dw_spi_elba_init(pdev, dwsmmio);
    dw_spi_mmio_probe(pdev);
    dw_spi_mmio_suspend(dev);
    dw_spi_mmio_resume(dev);
    dw_spi_mmio_remove(pdev);

    printf("dw-apb-ssi oracle: all functions invoked.\n");
    return 0;
}

#endif /* REHARNESS_BAREMETAL_ORACLE */

/* ---- part 01 of 03 ---- */
/* =====================================================================
 * dw-apb-ssi — module function bodies (Part 1 of 4)
 * Modules: dw_spi_set_cs, dw_spi_transfer_handler
 * ===================================================================== */

/* ---------------------------------------------------------------------
 * Forward declarations for helpers referenced by module bodies.
 * --------------------------------------------------------------------- */

/* dw_spi_check_status — modelled as returning a nonzero value so the
 * IF body in the RIS (op_4..op_12) is exercised. */
static int dw_spi_check_status_p1(struct dw_spi_mmio *dws, int raw)
{
    (void)dws;
    (void)raw;
    return 1;
}

/* dw_spi_ip_is – returns nonzero when the IP type matches. */
static int __attribute__((unused)) dw_spi_ip_is_p1(struct dw_spi_mmio *dws, uint32_t type)
{
    (void)dws;
    (void)type;
    return 1;
}

/* FIELD_PREP helper */
static inline uint32_t field_prep_p1(uint32_t mask, uint32_t val)
{
    uint32_t shift = 0;
    uint32_t m = mask;
    while ((m & 1u) == 0u) {
        m >>= 1;
        shift++;
    }
    return (val << shift) & mask;
}

/* ---------------------------------------------------------------------
 * Module: dw_spi_set_cs
 * RIS: dw_spi_set_cs
 * --------------------------------------------------------------------- */
static void __attribute__((unused)) dw_spi_set_cs(struct dw_spi_mmio *spi, uint32_t enable)
{
    /* The RIS uses `dws` for the device; the function's first param is
     * `spi` (DeviceState). In the source the device struct provides
     * ->regs.DW_SPI_SER. We treat `spi` as the DeviceState pointer and
     * access the inner dw_spi via spi->dws. */
    struct dw_spi *dws = &spi->dws;

    /* cs_high models spi->mode & SPI_CS_HIGH; enable controls CS assert. */
    uint32_t cs_high = 0u;

    /* chip_select models spi->chip_select[0] */
    uint32_t chip_select = 0u;

    if (cs_high == enable) {
        /* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=52e1d34f0188d855 */
__rh_op_1: {
            mmio_write32((uint32_t)((0x1u << chip_select)), dws->base + DW_SPI_SER);
        }
    }
    if ((cs_high == enable) == 0x0u) {
        /* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=baf8513c30b7be5b */
__rh_op_2: {
            mmio_write32(0x0u, dws->base + DW_SPI_SER);
        }
    }
}

/* ---------------------------------------------------------------------
 * Module: dw_spi_transfer_handler
 * RIS: dw_spi_transfer_handler
 * --------------------------------------------------------------------- */
static uint32_t __attribute__((unused)) dw_spi_transfer_handler(struct dw_spi_mmio *dws_dev)
{
    struct dw_spi *dws = &dws_dev->dws;
    uint32_t irq_status;
    uint32_t ret = 0u;
    uint32_t r7 = 0u;
    uint32_t r9 = 0u;
    uint32_t r13 = 0u;
    uint32_t rxw = 0u;
    uint32_t r20 = 0u;
    uint32_t new_mask = 0u;
    uint32_t r22 = 0u;
    uint32_t tx_room = 0u;
    uint32_t txw = 0x0u;
    uint32_t r32 = 0u;
    uint32_t max_rx = dws->fifo_len;
    uint32_t max_tx = dws->fifo_len;
    uint32_t v_isr_read = 0u;

    /* op_3: irq_status := R(B4, dws->regs.DW_SPI_ISR) */
    /* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=1da529e7a809836c */
__rh_op_3: {
        irq_status = mmio_read32(dws->base + DW_SPI_ISR);
    }

    /* IF dw_spi_check_status(dws, false) */
    if (dw_spi_check_status_p1(dws_dev, 0)) {
        /* IF 0x0  — the RIS guard is a literal 0x0 (always-true branch
         * in the original is `if (raw)` which was false). We model the
         * condition as written. */
        if (0x0u) {
            /* ret := R(B4, dws->regs.DW_SPI_RISR) */
            /* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=f69675ec9835d413 */
__rh_op_4: {
                ret = mmio_read32(dws->base + DW_SPI_RISR);
            }
        }
        /* IF (0x0 == 0x0) */
        if (0x0u == 0x0u) {
            /* ret := R(B4, dws->regs.DW_SPI_ISR) */
            /* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cc3597eae4a4ffcf */
__rh_op_5: {
                ret = mmio_read32(dws->base + DW_SPI_ISR);
            }
        }
        if (ret) {
            /* W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) */
            /* REHARNESS_RIS_OP id=op_6 kind=Write status=lowered digest=6b1f7c3c7aff2599 */
__rh_op_6: {
                mmio_write32((0x0u ? 0x1u : 0x0u), dws->base + DW_SPI_SSIENR);
            }
            /* r7 := R(B4, dws->regs.DW_SPI_IMR) */
            /* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=db5406d93b9de59f */
__rh_op_7: {
                r7 = mmio_read32(dws->base + DW_SPI_IMR);
            }
            /* W(B4, dws->regs.DW_SPI_IMR) = new_mask */
            /* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=d8f3ef33fb01554e */
__rh_op_8: {
                mmio_write32(new_mask, dws->base + DW_SPI_IMR);
            }
            /* r9 := R(B4, dws->regs.DW_SPI_ICR) */
            /* REHARNESS_RIS_OP id=op_9 kind=Read status=lowered digest=b7ef59e827eab5c4 */
__rh_op_9: {
                r9 = mmio_read32(dws->base + DW_SPI_ICR);
            }
            /* W(B4, dws->regs.DW_SPI_SER) = 0x0 */
            /* REHARNESS_RIS_OP id=op_10 kind=Write status=lowered digest=02bf20c4b2910e68 */
__rh_op_10: {
                mmio_write32(0x0u, dws->base + DW_SPI_SER);
            }
            /* W(B4, dws->regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) */
            /* REHARNESS_RIS_OP id=op_11 kind=Write status=lowered digest=dfd1fa2d71073b6b */
__rh_op_11: {
                mmio_write32((0x1u ? 0x1u : 0x0u), dws->base + DW_SPI_SSIENR);
            }
            /* IF dws->ctlr->cur_msg — model cur_msg as nonzero */
            if (1) {
                /* STATE(dws->ctlr->cur_msg->status) := ret
                 * op_12 has no digest (pure state); no MMIO anchor. */
__rh_op_12: {
                    /* cur_msg->status = ret; modelled as no-op state store */
                    (void)ret;
                }
            }
        }
    }

    /* r13 := R(B4, dws->regs.DW_SPI_RXFLR) */
    /* REHARNESS_RIS_OP id=op_13 kind=Read status=lowered digest=e2bc5578b3e7296f */
__rh_op_13: {
        r13 = mmio_read32(dws->base + DW_SPI_RXFLR);
    }

    /* LOOP while max-- (count=max; relation=post-decrement; bounded) */
    {
        uint32_t max = r13;
        while (max--) {
            /* rxw := R(B4, dws->regs.DW_SPI_DR) */
            /* REHARNESS_RIS_OP id=op_14 kind=Read status=lowered digest=3da139e73bc81d86 */
__rh_op_14: {
                rxw = mmio_read32(dws->base + DW_SPI_DR);
            }
            if (dws->rx != (uint8_t *)0) {
                if (dws->n_bytes == 0x1u) {
                    /* OUT(*(u8 *)(dws->rx)) := rxw */
__rh_op_15: {
                        *(uint8_t *)(dws->rx) = (uint8_t)rxw;
                    }
                }
                if ((dws->n_bytes == 0x1u) == 0x0u) {
                    if (dws->n_bytes == 0x2u) {
                        /* OUT(*(u16 *)(dws->rx)) := rxw */
__rh_op_16: {
                            *(uint16_t *)(dws->rx) = (uint16_t)rxw;
                        }
                    }
                    if ((dws->n_bytes == 0x2u) == 0x0u) {
                        /* OUT(*(u32 *)(dws->rx)) := rxw */
__rh_op_17: {
                            *(uint32_t *)(dws->rx) = (uint32_t)rxw;
                        }
                    }
                }
                /* STATE(dws->rx) := (dws->rx + dws->n_bytes) */
__rh_op_18: {
                    dws->rx = (uint8_t *)((uintptr_t)dws->rx + dws->n_bytes);
                }
            }
            /* STATE(dws->rx_len) := (dws->rx_len + -1) */
__rh_op_19: {
                dws->rx_len = dws->rx_len + (uint32_t)(-1);
            }
        }
    }

    if (dws->rx_len == 0x0u) {
        /* r20 := R(B4, dws->regs.DW_SPI_IMR) */
        /* REHARNESS_RIS_OP id=op_20 kind=Read status=lowered digest=db8b7d8066902839 */
__rh_op_20: {
            r20 = mmio_read32(dws->base + DW_SPI_IMR);
        }
        /* W(B4, dws->regs.DW_SPI_IMR) = new_mask */
        /* REHARNESS_RIS_OP id=op_21 kind=Write status=lowered digest=d8f3ef33fb01554e */
__rh_op_21: {
            mmio_write32(new_mask, dws->base + DW_SPI_IMR);
        }
    }

    if ((dws->rx_len == 0x0u) == 0x0u) {
        /* r22 := R(B4, dws->regs.DW_SPI_RXFTLR) */
        /* REHARNESS_RIS_OP id=op_22 kind=Read status=lowered digest=0ac68c30582764c9 */
__rh_op_22: {
            r22 = mmio_read32(dws->base + DW_SPI_RXFTLR);
        }
        if (dws->rx_len <= r22) {
            /* W(B4, dws->regs.DW_SPI_RXFTLR) = (dws->rx_len - 0x1) */
            /* REHARNESS_RIS_OP id=op_23 kind=Write status=lowered digest=048897f03058f8c8 */
__rh_op_23: {
                mmio_write32((dws->rx_len - 0x1u), dws->base
