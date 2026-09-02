#include "dw_apb_ssi_harness.h"


/* ------------------------------------------------------------------ */
/* Function prototypes (from evidence.functions)                      */
/* All declared static; bodies emitted in separate parts.            */
/* ------------------------------------------------------------------ */

static void dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
static uint32_t dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws);
static uint32_t dw_spi_irq(uint32_t irq, struct dw_apb_ssi_priv *dev_id);
static uint32_t dw_spi_transfer_one(struct dw_apb_ssi_priv *ctlr,
                                    struct dw_apb_ssi_priv *spi,
                                    struct dw_apb_ssi_priv *transfer);
static void dw_spi_handle_err(struct dw_apb_ssi_priv *ctlr,
                              struct dw_apb_ssi_priv *msg);
static uint32_t dw_spi_target_abort(struct dw_apb_ssi_priv *ctlr);
static uint32_t dw_spi_exec_mem_op(struct dw_apb_ssi_priv *mem,
                                   struct dw_apb_ssi_priv *op);
static uint32_t dw_spi_setup(struct dw_apb_ssi_priv *spi);
static void dw_spi_cleanup(struct dw_apb_ssi_priv *spi);
static void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
static uint32_t dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *pdev,
                                        struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *pdev,
                                         struct dw_apb_ssi_priv *dwsmmio);
static void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
static uint32_t dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *pdev,
                                         struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_alpine_init(struct dw_apb_ssi_priv *pdev,
                                   struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_hssi_init(struct dw_apb_ssi_priv *pdev,
                                 struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_intel_init(struct dw_apb_ssi_priv *pdev,
                                  struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *pdev,
                                            struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *pdev,
                                         struct dw_apb_ssi_priv *dwsmmio);
static void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable);
static uint32_t dw_spi_elba_init(struct dw_apb_ssi_priv *pdev,
                                  struct dw_apb_ssi_priv *dwsmmio);
static uint32_t dw_spi_mmio_probe(struct dw_apb_ssi_priv *pdev);
static uint32_t dw_spi_mmio_suspend(struct dw_apb_ssi_priv *dev);
static uint32_t dw_spi_mmio_resume(struct dw_apb_ssi_priv *dev);
static void dw_spi_mmio_remove(struct dw_apb_ssi_priv *pdev);

/* ------------------------------------------------------------------ */
/* Entry point                                                        */
/* ------------------------------------------------------------------ */

/*
 * Userspace main(): instantiate the device private struct with
 * a plausible base address and call every evidence function in order.
 */
int main(void)
{
    struct dw_apb_ssi_priv dev;
    struct dw_apb_ssi_priv dummy2;
    struct dw_apb_ssi_priv dummy3;

    memset(&dev, 0, sizeof(dev));
    memset(&dummy2, 0, sizeof(dummy2));
    memset(&dummy3, 0, sizeof(dummy3));

    dev.base = 0x10000000UL;

    printf("=== dw-apb-ssi scaffold: calling functions in evidence order ===\n");

    /* 1. dw_spi_set_cs(spi, enable) */
    dw_spi_set_cs(&dev, 1);

    /* 2. dw_spi_transfer_handler(dws) */
    dw_spi_transfer_handler(&dev);

    /* 3. dw_spi_irq(irq, dev_id) */
    dw_spi_irq(0, &dev);

    /* 4. dw_spi_transfer_one(ctlr, spi, transfer) */
    dw_spi_transfer_one(&dev, &dummy2, &dummy3);

    /* 5. dw_spi_handle_err(ctlr, msg) */
    dw_spi_handle_err(&dev, &dummy2);

    /* 6. dw_spi_target_abort(ctlr) */
    dw_spi_target_abort(&dev);

    /* 7. dw_spi_exec_mem_op(mem, op) */
    dw_spi_exec_mem_op(&dev, &dummy2);

    /* 8. dw_spi_setup(spi) */
    dw_spi_setup(&dev);

    /* 9. dw_spi_cleanup(spi) */
    dw_spi_cleanup(&dev);

    /* 10. dw_spi_mscc_set_cs(spi, enable) */
    dw_spi_mscc_set_cs(&dev, 1);

    /* 11. dw_spi_mscc_ocelot_init(pdev, dwsmmio) */
    dw_spi_mscc_ocelot_init(&dev, &dummy2);

    /* 12. dw_spi_mscc_jaguar2_init(pdev, dwsmmio) */
    dw_spi_mscc_jaguar2_init(&dev, &dummy2);

    /* 13. dw_spi_sparx5_set_cs(spi, enable) */
    dw_spi_sparx5_set_cs(&dev, 1);

    /* 14. dw_spi_mscc_sparx5_init(pdev, dwsmmio) */
    dw_spi_mscc_sparx5_init(&dev, &dummy2);

    /* 15. dw_spi_alpine_init(pdev, dwsmmio) */
    dw_spi_alpine_init(&dev, &dummy2);

    /* 16. dw_spi_hssi_init(pdev, dwsmmio) */
    dw_spi_hssi_init(&dev, &dummy2);

    /* 17. dw_spi_intel_init(pdev, dwsmmio) */
    dw_spi_intel_init(&dev, &dummy2);

    /* 18. dw_spi_mountevans_imc_init(pdev, dwsmmio) */
    dw_spi_mountevans_imc_init(&dev, &dummy2);

    /* 19. dw_spi_canaan_k210_init(pdev, dwsmmio) */
    dw_spi_canaan_k210_init(&dev, &dummy2);

    /* 20. dw_spi_elba_set_cs(spi, enable) */
    dw_spi_elba_set_cs(&dev, 1);

    /* 21. dw_spi_elba_init(pdev, dwsmmio) */
    dw_spi_elba_init(&dev, &dummy2);

    /* 22. dw_spi_mmio_probe(pdev) */
    dw_spi_mmio_probe(&dev);

    /* 23. dw_spi_mmio_suspend(dev) */
    dw_spi_mmio_suspend(&dev);

    /* 24. dw_spi_mmio_resume(dev) */
    dw_spi_mmio_resume(&dev);

    /* 25. dw_spi_mmio_remove(pdev) */
    dw_spi_mmio_remove(&dev);

    printf("=== dw-apb-ssi scaffold: done ===\n");
    return 0;
}

/* ---- part 01 of 03 ---- */
/* ================================================================== */
/* Part 1 of 4: dw_spi_set_cs, dw_spi_transfer_handler              */
/* ================================================================== */

/*
 * The scaffold already defines struct dw_apb_ssi_priv with a
 * `base` field of type uintptr_t.  All register accesses use
 * dws->base + <offset>.
 */

/* Helper: compute max from TXFLR (FIFO depth - current entries) */
static uint32_t __attribute__((unused)) dw_spi_tx_max_p1(struct dw_apb_ssi_priv *dws)
{
    uint32_t tx_room;
    uint32_t max_val;

    /* REHARNESS_RIS_OP id=op_24 kind=Read status=lowered digest=d5ec643b5880dd09 */
    __rh_op_24: {
        tx_room = harness_read32(dws->base + DW_SPI_TXFLR);
    }

    max_val = dws->fifo_len - tx_room;
    return max_val;
}

/* Helper: compute max from RXFLR (current entries) */
static uint32_t __attribute__((unused)) dw_spi_rx_max_p1(struct dw_apb_ssi_priv *dws)
{
    uint32_t max_val;

    /* REHARNESS_RIS_OP id=op_13 kind=Read status=lowered digest=e2bc5578b3e7296f */
    __rh_op_13: {
        max_val = harness_read32(dws->base + DW_SPI_RXFLR);
    }

    return max_val;
}

/* ------------------------------------------------------------------ */
/* dw_spi_set_cs                                                      */
/* ------------------------------------------------------------------ */

static void __attribute__((unused)) dw_spi_set_cs(struct dw_apb_ssi_priv *spi, uint32_t enable)
{
    uint32_t cs_high = 0;  /* SPI_MODE_CS_HIGH flag; default low */
    uint32_t chip_select_0 = 0;  /* spi->chip_select[0] */

    if (cs_high == enable) {
        /* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=52e1d34f0188d855 */
        __rh_op_1: {
            harness_write32((0x1 << chip_select_0), spi->base + DW_SPI_SER);
        }
    } else {
        /* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=baf8513c30b7be5b */
        __rh_op_2: {
            harness_write32(0x0, spi->base + DW_SPI_SER);
        }
    }
}

/* ------------------------------------------------------------------ */
/* dw_spi_transfer_handler                                            */
/* ------------------------------------------------------------------ */

static uint32_t __attribute__((unused)) dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws)
{
    uint32_t irq_status;
    uint32_t ret;
    uint32_t r7;
    uint32_t new_mask;
    uint32_t r9;
    uint32_t r13;
    uint32_t max_rx;
    uint32_t rxw;
    uint32_t r20;
    uint32_t r22;
    uint32_t rxftlr_val;
    uint32_t tx_room;
    uint32_t txw;
    uint32_t max_tx;
    uint32_t r32;

    /* op_3: irq_status := R(B4, dws->regs.DW_SPI_ISR) */
    /* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=1da529e7a809836c */
    __rh_op_3: {
        irq_status = harness_read32(dws->base + DW_SPI_ISR);
    }

    /* dw_spi_check_status(dws, false) — conservative: take the branch */
    if (1) {
        /* op_4: IF 0x0 { ret := R(B4, dws->regs.DW_SPI_RISR) } */
        /* condition is 0x0 (false), so skip */
        if (0) {
            /* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=f69675ec9835d413 */
            __rh_op_4: {
                ret = harness_read32(dws->base + DW_SPI_RISR);
            }
        }
        /* op_5: IF (0x0 == 0x0) { ret := R(B4, dws->regs.DW_SPI_ISR) } */
        if (1) {
            /* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cc3597eae4a4ffcf */
            __rh_op_5: {
                ret = harness_read32(dws->base + DW_SPI_ISR);
            }
        }
        /* op_6..op_12: IF ret { ... } */
        if (ret) {
            new_mask = 0;

            /* REHARNESS_RIS_OP id=op_6 kind=Write status=lowered digest=6b1f7c3c7aff2599 */
            __rh_op_6: {
                harness_write32((0 ? 1 : 0), dws->base + DW_SPI_SSIENR);
            }

            /* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=db5406d93b9de59f */
            __rh_op_7: {
                r7 = harness_read32(dws->base + DW_SPI_IMR);
            }

            /* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=d8f3ef33fb01544e */
            __rh_op_8: {
                harness_write32(new_mask, dws->base + DW_SPI_IMR);
            }

            /* REHARNESS_RIS_OP id=op_9 kind=Read status=lowered digest=b7ef59e827eab5c4 */
            __rh_op_9: {
                r9 = harness_read32(dws->base + DW_SPI_ICR);
            }

            /* REHARNESS_RIS_OP id=op_10 kind=Write status=lowered digest=02bf20c4b2910e68 */
            __rh_op_10: {
                harness_write32(0x0, dws->base + DW_SPI_SER);
            }

            /* REHARNESS_RIS_OP id=op_11 kind=Write status=lowered digest=dfd1fa2d71073b6b */
            __rh_op_11: {
                harness_write32((1 ? 1 : 0), dws->base + DW_SPI_SSIENR);
            }

            /* op_12: STATE(dws->ctlr->cur_msg->status) := ret — pure state, no receipt */
            /* (no MMIO, no digest — skip) */
        }
    }

    /* op_13: r13 := R(B4, dws->regs.DW_SPI_RXFLR) — via rx_max helper logic */
    max_rx = r13;

    /* LOOP while max-- (count=max; relation=post-decrement; bounded) */
    while (max_rx--) {
        /* REHARNESS_RIS_OP id=op_14 kind=Read status=lowered digest=3da139e73bc81d86 */
        __rh_op_14: {
            rxw = harness_read32(dws->base + DW_SPI_DR);
        }

        if (dws->rx) {
            if (dws->cur_nbytes == 0x1) {
                /* op_15: OUT(*(u8 *)(dws->rx)) := rxw — pure memory write */
                *(uint8_t *)dws->rx = (uint8_t)rxw;
            } else {
                if (dws->cur_nbytes == 0x2) {
                    /* op_16: OUT(*(u16 *)(dws->rx)) := rxw */
                    *(uint16_t *)dws->rx = (uint16_t)rxw;
                }
