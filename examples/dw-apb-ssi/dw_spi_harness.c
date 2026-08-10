#include "dw_apb_ssi_harness.h"


struct dw_spi_cfg {
    uint32_t tmode;
    uint32_t ndf;
};

struct dw_apb_ssi_priv {
    uintptr_t base;
    uint32_t ver;
    uint32_t num_cs;
    uint32_t fifo_len;
    uint32_t caps;
    uint32_t current_freq;
    uint32_t cur_rx_sample_dly;
    uint32_t irq;
    int dma_mapped;
    uint32_t chip_select[4];
    void *cur_msg;
    void *tx;
    void *rx;
    uint32_t n_bytes;
    uint32_t tx_len;
    uint32_t rx_len;
    struct dw_spi_chip *chip;
    struct dw_spi_cfg *cfg;
};

/* Module functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int enable, int cs_high) {
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
    uint32_t irq_status;
    uint32_t r6, r8;
    uint32_t new_mask = 0;

    if (raw) {
        irq_status = harness_read32(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = harness_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        harness_write32(0, base + DW_SPI_SSIENR);
        r6 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
        r8 = harness_read32(base + DW_SPI_ICR);
        harness_write32(0x0, base + DW_SPI_SER);
        harness_write32(1, base + DW_SPI_SSIENR);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status, r12, rxw, r14, r16, tx_room, r20;
    uint32_t new_mask = 0;
    int max;

    irq_status = harness_read32(base + DW_SPI_ISR);
    r12 = harness_read32(base + 0x0);

    max = 4;
    while (max--) {
        rxw = harness_read32(base + DW_SPI_DR);
    }

    if (dev->rx_len == 0x0) {
        r14 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
    }
    if ((dev->rx_len == 0x0) == 0x0) {
        r16 = harness_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r16) {
            harness_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }

    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = harness_read32(base + DW_SPI_TXFLR);
        max = 4;
        while (max--) {
            uint32_t val = 0;
            if (dev->tx && dev->n_bytes != 1 && dev->n_bytes != 2) {
                val = *(uint32_t *)(dev->tx);
            } else if (dev->tx && dev->n_bytes != 1 && dev->n_bytes == 2) {
                val = *(uint16_t *)(dev->tx);
            } else if (dev->tx && dev->n_bytes == 1) {
                val = *(uint8_t *)(dev->tx);
            } else {
                val = 0;
            }
            harness_write32(val, base + DW_SPI_DR);
        }
        if (dev->tx_len == 0x0) {
            r20 = harness_read32(base + DW_SPI_IMR);
            harness_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status, r23;
    uint32_t new_mask = 0;

    irq_status = harness_read32(base + DW_SPI_ISR);
    if (dev->cur_msg == 0x0) {
        r23 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t speed_hz) {
    uintptr_t base = dev->base;
    uint32_t clk_div = 0;

    harness_write32(dev->chip->cr0, base + DW_SPI_CTRLR0);
    if ((dev->cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | dev->cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO) {
        uint32_t val = dev->cfg->ndf ? (dev->cfg->ndf - 1) : 0;
        harness_write32(val, base + DW_SPI_CTRLR1);
    }
    if (dev->current_freq != speed_hz) {
        harness_write32(clk_div, base + DW_SPI_BAUDR);
    }
    if (dev->cur_rx_sample_dly != dev->chip->rx_sample_dly) {
        harness_write32(dev->chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r30, r35, r39, tx_room, rxw;
    uint32_t new_mask = 0;
    uint32_t level = 0;

    harness_write32(0, base + DW_SPI_SSIENR);
    r30 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32(1, base + DW_SPI_SSIENR);

    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                tx_room = harness_read32(base + DW_SPI_TXFLR);
                int max = 4;
                while (max--) {
                    uint32_t val = 0;
                    if (dev->tx && dev->n_bytes != 1 && dev->n_bytes != 2) {
                        val = *(uint32_t *)(dev->tx);
                    } else if (dev->tx && dev->n_bytes != 1 && dev->n_bytes == 2) {
                        val = *(uint16_t *)(dev->tx);
                    } else if (dev->tx && dev->n_bytes == 1) {
                        val = *(uint8_t *)(dev->tx);
                    } else {
                        val = 0;
                    }
                    harness_write32(val, base + DW_SPI_DR);
                }
                r35 = harness_read32(base + 0x0);
                max = 4;
                while (max--) {
                    rxw = harness_read32(base + DW_SPI_DR);
                }
            }
        }
    }

    harness_write32(level, base + DW_SPI_TXFTLR);
    harness_write32((level - 0x1), base + DW_SPI_RXFTLR);
    r39 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r42, r44;
    uint32_t new_mask = 0;

    harness_write32(0, base + DW_SPI_SSIENR);
    r42 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r44 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r48, r50;
    uint32_t new_mask = 0;

    harness_write32(0, base + DW_SPI_SSIENR);
    r48 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r50 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r54, r62, entries, sts, nents, __return_read_0;
    uint32_t new_mask = 0;
    uint8_t buf[16] = {0};
    uint32_t len = 4;
    uint32_t ret = 0;

    harness_write32(0, base + DW_SPI_SSIENR);
    r54 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32(1, base + DW_SPI_SSIENR);

    while (len--) {
        harness_write32(*buf++, base + DW_SPI_DR);
    }

    while (len) {
        entries = harness_read32(base + DW_SPI_TXFLR);
        uint32_t room = 4;
        while (room--) {
            harness_write32(*buf++, base + DW_SPI_DR);
        }
    }

    while (len) {
        entries = harness_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = harness_read32(base + DW_SPI_RISR);
        }
        uint32_t max = entries;
        while (max--) {
            r62 = harness_read32(base + DW_SPI_DR);
        }
    }

    if (ret == 0x0) {
        nents = harness_read32(base + DW_SPI_TXFLR);
        int retry = 4;
        while (retry--) {
            __return_read_0 = harness_read32(base + DW_SPI_SR);
        }
    }

    harness_write32(0, base + DW_SPI_SSIENR);
    harness_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r68, r70, ser, r78, r80, cr0, tmp = 0;
    uint32_t new_mask = 0;
    int ret = 0;

    if (dev) {
        harness_write32(0, base + DW_SPI_SSIENR);
        r68 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
        r70 = harness_read32(base + DW_SPI_ICR);
        harness_write32(0x0, base + DW_SPI_SER);
        harness_write32(1, base + DW_SPI_SSIENR);

        if (dev->ver == 0x0) {
            dev->ver = harness_read32(base + DW_SPI_VERSION);
        }
        if (1) { /* spi_controller_is_target(dws->ctlr) == 0x0 */
            if (dev->num_cs == 0x0) {
                harness_write32(0xffff, base + DW_SPI_SER);
                ser = harness_read32(base + DW_SPI_SER);
                harness_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            uint32_t fifo = 0;
            while (fifo < 0x100) {
                harness_write32(fifo, base + DW_SPI_TXFTLR);
                r78 = harness_read32(base + DW_SPI_TXFTLR);
                fifo++;
            }
            harness_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (1) { /* dw_spi_ip_is(dws, PSSI) */
            r80 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(0, base + DW_SPI_SSIENR);
            harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(tmp, base + DW_SPI_CTRLR0);
            harness_write32(1, base + DW_SPI_SSIENR);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
    if (0) {
        if (1) {
            if (1) {
                if (dev) {
                    harness_write32(0, base + DW_SPI_SSIENR);
                }
            }
        }
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0, base + DW_SPI_SSIENR);
    harness_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0, base + DW_SPI_SSIENR);
    harness_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r93, r95, ser, r103, r105, cr0, tmp = 0;
    uint32_t new_mask = 0;

    harness_write32(0, base + DW_SPI_SSIENR);
    r93 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r95 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32(1, base + DW_SPI_SSIENR);

    if (dev->ver == 0x0) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if (1) { /* spi_controller_is_target(dws->ctlr) == 0x0 */
        if (dev->num_cs == 0x0) {
            harness_write32(0xffff, base + DW_SPI_SER);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        uint32_t fifo = 0;
        while (fifo < 0x100) {
            harness_write32(fifo, base + DW_SPI_TXFTLR);
            r103 = harness_read32(base + DW_SPI_TXFTLR);
            fifo++;
        }
        harness_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (1) { /* dw_spi_ip_is(dws, PSSI) */
        r105 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(0, base + DW_SPI_SSIENR);
        harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(tmp, base + DW_SPI_CTRLR0);
        harness_write32(1, base + DW_SPI_SSIENR);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        uint32_t val = (cs < 4) ? 8192 : sw_mode;
        harness_write32(val, base + MSCC_SPI_MST_SW_MODE);
    }
}

void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
    /* regmap tx_update stub */
}

void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
    /* regmap tx_update stub */
}

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dev, int enable) {
    /* regmap tx_write stubs */
    if (enable == 0x0) {
        /* SPARX5_FORCE_ENA */
        /* SPARX5_FORCE_VAL */
    }
    if ((enable == 0x0) == 0x0) {
        /* SPARX5_FORCE_VAL */
        /* SPARX5_FORCE_ENA */
    }
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    /* regmap tx_update stub */
    if (cs < 0x2) {
        /* ELBA_SPICS_REG */
    }
}

int main(void) {
    /* Allocate device instance */
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.chip_select[0] = 0;
    dev.n_bytes = 1;
    dev.tx_len = 4;
    dev.rx_len = 4;
    dev.irq = IRQ_NOTCONNECTED;
    dev.dma_mapped = 0;
    dev.caps = DW_SPI_CAP_CS_OVERRIDE;
    dev.fifo_len = 0;
    dev.num_cs = 0;
    dev.ver = 0;

    struct dw_spi_chip chip = {0};
    struct dw_spi_cfg cfg = {0};
    dev.chip = &chip;
    dev.cfg = &cfg;

    /* Call module functions in order */
    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_check_status(&dev, 1, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_update_config(&dev, 1000000);
    dw_spi_transfer_one(&dev);
    dw_spi_handle_err(&dev);
    dw_spi_target_abort(&dev);
    dw_spi_exec_mem_op(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_remove_controller(&dev);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 0, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);

    return 0;
}