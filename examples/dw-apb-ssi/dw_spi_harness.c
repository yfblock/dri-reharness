#include "dw_apb_ssi_harness.h"


/* Module functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int cs_high, int enable) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        harness_write32((0x1 << dev->chip_select[0]), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        harness_write32(0x0, base + DW_SPI_SER);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, int raw, int ret) {
    uintptr_t base = dev->base;
    uint32_t irq_status = 0;
    uint32_t r6 = 0;
    uint32_t new_mask = 0;
    uint32_t r8 = 0;

    if (raw) {
        irq_status = harness_read32(base + DW_SPI_RISR);
    }
    if ((raw == 0x0)) {
        irq_status = harness_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        r6 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
        r8 = harness_read32(base + DW_SPI_ICR);
        harness_write32(0x0, base + DW_SPI_SER);
        harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
    uint32_t r13 = harness_read32(base + DW_SPI_RXFLR);
    uint32_t rxw = 0;
    uint32_t new_mask = 0;
    uint32_t r20 = 0;
    uint32_t r22 = 0;
    uint32_t tx_room = 0;
    uint32_t txw = 0;
    uint32_t r32 = 0;

    for (int max = 0; max < (int)r13; max++) {
        rxw = harness_read32(base + DW_SPI_DR);
        if (dev->rx) {
            if (dev->n_bytes == 0x1) {
                *(uint8_t *)(dev->rx) = rxw;
            } else if ((dev->n_bytes == 0x1) == 0x0) {
                if (dev->n_bytes == 0x2) {
                    *(uint16_t *)(dev->rx) = rxw;
                } else if ((dev->n_bytes == 0x2) == 0x0) {
                    *(uint32_t *)(dev->rx) = rxw;
                }
            }
            dev->rx += dev->n_bytes;
        }
        dev->rx_len = dev->rx_len - 1;
    }

    if (dev->rx_len == 0x0) {
        r20 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
    } else if ((dev->rx_len == 0x0) == 0x0) {
        r22 = harness_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r22) {
            harness_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }

    if (irq_status & BIT(8)) { /* DW_SPI_INT_TXEI */
        tx_room = harness_read32(base + DW_SPI_TXFLR);
        txw = 0x0;
        for (int max = 0; max < (int)tx_room; max++) {
            if (dev->tx) {
                if (dev->n_bytes == 0x1) {
                    txw = *(uint8_t *)(dev->tx);
                } else if ((dev->n_bytes == 0x1) == 0x0) {
                    if (dev->n_bytes == 0x2) {
                        txw = *(uint16_t *)(dev->tx);
                    } else if ((dev->n_bytes == 0x2) == 0x0) {
                        txw = *(uint32_t *)(dev->tx);
                    }
                }
                dev->tx += dev->n_bytes;
            }
            harness_write32(txw, base + DW_SPI_DR);
            dev->tx_len = dev->tx_len - 1;
        }
        if (dev->tx_len == 0x0) {
            r32 = harness_read32(base + DW_SPI_IMR);
            harness_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev, uint32_t dev_id) {
    uintptr_t base = dev->base;
    uint32_t ctlr = dev_id;
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
    uint32_t r36 = 0;
    uint32_t new_mask = 0;

    if (ctlr == 0x0) {
        r36 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0_val, uint32_t dfs, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t clk_div, uint32_t rx_sample_dly) {
    uintptr_t base = dev->base;
    uint32_t cr0 = cr0_val;
    cr0 = (cr0 | ((dfs - 0x1) << dev->dfs_offset));

    if (dev->ip == 0) { /* PSSI */
        cr0 = (cr0 | FIELD_PREP(0x300, tmode));
    } else {
        cr0 = (cr0 | FIELD_PREP(0x30000, tmode));
    }
    harness_write32(cr0, base + DW_SPI_CTRLR0);

    if (tmode == 0x2) { /* DW_SPI_CTRLR0_TMOD_RO */
        harness_write32((ndf ? (ndf - 0x1) : 0x0), base + DW_SPI_CTRLR1);
    }

    if (dev->current_freq != speed_hz) {
        harness_write32(clk_div, base + DW_SPI_BAUDR);
        dev->current_freq = speed_hz;
    }

    if (dev->cur_rx_sample_dly != rx_sample_dly) {
        harness_write32(rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
        dev->cur_rx_sample_dly = rx_sample_dly;
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t new_mask = 0;
    uint32_t r56 = 0;
    uint32_t tx_room = 0;
    uint32_t txw = 0;
    uint32_t r69 = 0;
    uint32_t rxw = 0;
    uint32_t level = 32;
    uint32_t r80 = 0;

    dev->dma_mapped = 0x0;
    dev->tx_len = 16;
    dev->rx_len = dev->tx_len;

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r56 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    if (dev->dma_mapped == 0x0) {
        if (dev->irq == 0) { /* IRQ_NOTCONNECTED */
            while (dev->rx_len) {
                tx_room = harness_read32(base + DW_SPI_TXFLR);
                txw = 0x0;
                for (int max = 0; max < (int)tx_room; max++) {
                    if (dev->tx) {
                        if (dev->n_bytes == 0x1) {
                            txw = *(uint8_t *)(dev->tx);
                        } else if ((dev->n_bytes == 0x1) == 0x0) {
                            if (dev->n_bytes == 0x2) {
                                txw = *(uint16_t *)(dev->tx);
                            } else if ((dev->n_bytes == 0x2) == 0x0) {
                                txw = *(uint32_t *)(dev->tx);
                            }
                        }
                        dev->tx += dev->n_bytes;
                    }
                    harness_write32(txw, base + DW_SPI_DR);
                    dev->tx_len = dev->tx_len - 1;
                }
                r69 = harness_read32(base + DW_SPI_RXFLR);
                for (int max = 0; max < (int)r69; max++) {
                    rxw = harness_read32(base + DW_SPI_DR);
                    if (dev->rx) {
                        if (dev->n_bytes == 0x1) {
                            *(uint8_t *)(dev->rx) = rxw;
                        } else if ((dev->n_bytes == 0x1) == 0x0) {
                            if (dev->n_bytes == 0x2) {
                                *(uint16_t *)(dev->rx) = rxw;
                            } else if ((dev->n_bytes == 0x2) == 0x0) {
                                *(uint32_t *)(dev->rx) = rxw;
                            }
                        }
                        dev->rx += dev->n_bytes;
                    }
                    dev->rx_len = dev->rx_len - 1;
                }
            }
        }
    }

    harness_write32(level, base + DW_SPI_TXFTLR);
    harness_write32((level - 0x1), base + DW_SPI_RXFTLR);
    r80 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r83 = 0;
    uint32_t new_mask = 0;
    uint32_t r85 = 0;

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r83 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r85 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r89 = 0;
    uint32_t new_mask = 0;
    uint32_t r91 = 0;

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r89 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r91 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t len = 16;
    uint8_t *out = dev->buf;
    uint32_t new_mask = 0;
    uint32_t r108 = 0;
    uint8_t *buf;
    uint32_t entries = 0;
    uint32_t sts = 0;
    uint32_t buffer_read_0 = 0;
    uint32_t nents = 0;
    uint32_t __return_read_0 = 0;

    if (len <= 256) {
        out = dev->buf;
    }
    for (uint32_t i = 0; i < 1; i++) {
        /* bounded loop */
    }

    dev->n_bytes = 0x1;
    dev->tx = out;
    dev->tx_len = len;
    dev->rx = NULL;
    dev->rx_len = 0x0;

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r108 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    buf = dev->tx;
    for (int max = 0; max < (int)len; max++) {
        harness_write32(*buf++, base + DW_SPI_DR);
        len--;
    }
    while (len) {
        entries = harness_read32(base + DW_SPI_TXFLR);
        for (int max = 0; max < (int)len; max++) {
            harness_write32(*buf++, base + DW_SPI_DR);
            len--;
        }
    }

    buf = dev->rx;
    while (len) {
        entries = harness_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = harness_read32(base + DW_SPI_RISR);
        }
        for (int max = 0; max < (int)len; max++) {
            buffer_read_0 = harness_read32(base + DW_SPI_DR);
            *buf++ = buffer_read_0;
            len--;
        }
    }

    nents = harness_read32(base + DW_SPI_TXFLR);
    for (int retry = 1000; (dev->ver & 1) && retry--; ) {
        __return_read_0 = harness_read32(base + DW_SPI_SR);
    }

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r133 = 0;
    uint32_t new_mask = 0;
    uint32_t r135 = 0;
    uint32_t ser = 0;
    uint32_t r145 = 0;
    uint32_t r148 = 0;
    uint32_t cr0 = 0;
    uint32_t tmp = 0;

    if (dev) {
        harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        r133 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
        r135 = harness_read32(base + DW_SPI_ICR);
        harness_write32(0x0, base + DW_SPI_SER);
        harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

        if (dev->ver == 0x0) {
            dev->ver = harness_read32(base + DW_SPI_VERSION);
        }

        if (dev->num_cs == 0x0) {
            harness_write32(0xffff, base + DW_SPI_SER);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(0x0, base + DW_SPI_SER);
        }

        if (dev->fifo_len == 0x0) {
            for (uint32_t fifo = 1; fifo < 0x100; fifo++) {
                harness_write32(fifo, base + DW_SPI_TXFTLR);
                r145 = harness_read32(base + DW_SPI_TXFTLR);
            }
            harness_write32(0x0, base + DW_SPI_TXFTLR);
            dev->fifo_len = 32;
        }

        if (dev->ip == 0) { /* PSSI */
            r148 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
            harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(tmp, base + DW_SPI_CTRLR0);
            harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
            if ((cr0 & 0x30) == 0x0) {
                dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
            }
        } else {
            dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
        }

        if (dev->caps & 0x2) { /* DW_SPI_CAP_CS_OVERRIDE */
            harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    harness_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    harness_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r188 = 0;
    uint32_t new_mask = 0;
    uint32_t r190 = 0;
    uint32_t ser = 0;
    uint32_t r200 = 0;
    uint32_t r203 = 0;
    uint32_t cr0 = 0;
    uint32_t tmp = 0;

    harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r188 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r190 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    if (dev->ver == 0x0) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }

    if (dev->num_cs == 0x0) {
        harness_write32(0xffff, base + DW_SPI_SER);
        ser = harness_read32(base + DW_SPI_SER);
        harness_write32(0x0, base + DW_SPI_SER);
    }

    if (dev->fifo_len == 0x0) {
        for (uint32_t fifo = 1; fifo < 0x100; fifo++) {
            harness_write32(fifo, base + DW_SPI_TXFTLR);
            r200 = harness_read32(base + DW_SPI_TXFTLR);
        }
        harness_write32(0x0, base + DW_SPI_TXFTLR);
        dev->fifo_len = 32;
    }

    if (dev->ip == 0) { /* PSSI */
        r203 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(tmp, base + DW_SPI_CTRLR0);
        harness_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        if ((cr0 & 0x30) == 0x0) {
            dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
        }
    } else {
        dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
    }

    if (dev->caps & 0x2) { /* DW_SPI_CAP_CS_OVERRIDE */
        harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        uint32_t sw_mode = 0;
        harness_write32(sw_mode, base + MSCC_SPI_MST_SW_MODE);
    }
}

void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dev, int enable) {
    /* regmap ops omitted */
}

void dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *dev) {
    /* regmap ops omitted */
}

void dw_spi_alpine_init(struct dw_apb_ssi_priv *dev) {
    dev->caps = 0x2; /* DW_SPI_CAP_CS_OVERRIDE */
}

void dw_spi_hssi_init(struct dw_apb_ssi_priv *dev) {
    dev->ip = 0x2; /* DW_HSSI_ID */
}

void dw_spi_intel_init(struct dw_apb_ssi_priv *dev) {
    dev->ip = 0x2; /* DW_HSSI_ID */
}

void dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *dev) {
    dev->fifo_len = 0x1f;
}

void dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *dev) {
    dev->fifo_len = 0x1f;
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    /* regmap ops omitted */
}

void dw_spi_elba_init(struct dw_apb_ssi_priv *dev) {
    /* regmap ops omitted */
}

void dw_spi_mmio_probe(struct dw_apb_ssi_priv *dev) {
    dev->paddr = 0x10000000;
    dev->bus_num = 0;
    dev->reg_io_width = 0x4;
}

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.chip_select[0] = 0;
    dev.dfs_offset = 0;
    dev.n_bytes = 1;
    dev.ip = 0; /* PSSI */

    dw_spi_mmio_probe(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_update_config(&dev, 0, 8, 0, 0, 1000000, 100, 0);
    dw_spi_transfer_one(&dev);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev, 0);
    dw_spi_check_status(&dev, 1, 0);
    dw_spi_handle_err(&dev);
    dw_spi_target_abort(&dev);
    dw_spi_exec_mem_op(&dev);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_mscc_set_cs(&dev, 0);
    dw_spi_mscc_sparx5_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 1);
    dw_spi_alpine_init(&dev);
    dw_spi_hssi_init(&dev);
    dw_spi_intel_init(&dev);
    dw_spi_mountevans_imc_init(&dev);
    dw_spi_canaan_k210_init(&dev);
    dw_spi_elba_init(&dev);
    dw_spi_elba_set_cs(&dev, 0);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_remove_controller(&dev);

    return 0;
}