#include "dw_apb_ssi_harness.h"


void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int cs_high, int enable) {
    uintptr_t base = dev->base;
    uint32_t new_mask = 0;
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
    uint32_t r6 = 0, r8 = 0;
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
    uint32_t irq_status = 0, r12 = 0, rxw = 0, r14 = 0, r16 = 0, tx_room = 0, r20 = 0;
    uint32_t new_mask = 0;
    int max = 1;
    irq_status = harness_read32(base + DW_SPI_ISR);
    r12 = harness_read32(base + DW_SPI_RXFLR);
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
        max = 1;
        while (max--) {
            uint32_t val = 0;
            if (dev->tx && (dev->n_bytes == 1) == 0 && (dev->n_bytes == 2) == 0) {
                val = *(uint32_t *)(dev->tx);
            } else if (dev->tx && (dev->n_bytes == 1) == 0 && dev->n_bytes == 2) {
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
    uint32_t irq_status = 0, r23 = 0;
    uint32_t new_mask = 0;
    irq_status = harness_read32(base + DW_SPI_ISR);
    if (dev->cur_msg == 0x0) {
        r23 = harness_read32(base + DW_SPI_IMR);
        harness_write32(new_mask, base + DW_SPI_IMR);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t rx_sample_dly) {
    uintptr_t base = dev->base;
    uint32_t clk_div = 0;
    harness_write32(cr0, base + DW_SPI_CTRLR0);
    if (((tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | tmode))) == DW_SPI_CTRLR0_TMOD_RO) {
        harness_write32(ndf ? (ndf - 1) : 0, base + DW_SPI_CTRLR1);
    }
    if (dev->current_freq != speed_hz) {
        harness_write32(clk_div, base + DW_SPI_BAUDR);
    }
    if (dev->cur_rx_sample_dly != rx_sample_dly) {
        harness_write32(rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r30 = 0, tx_room = 0, r35 = 0, rxw = 0, r39 = 0;
    uint32_t new_mask = 0, level = 0;
    int max = 1;
    harness_write32(0, base + DW_SPI_SSIENR);
    r30 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32(1, base + DW_SPI_SSIENR);
    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                tx_room = harness_read32(base + DW_SPI_TXFLR);
                max = 1;
                while (max--) {
                    uint32_t val = 0;
                    if (dev->tx && (dev->n_bytes == 1) == 0 && (dev->n_bytes == 2) == 0) {
                        val = *(uint32_t *)(dev->tx);
                    } else if (dev->tx && (dev->n_bytes == 1) == 0 && dev->n_bytes == 2) {
                        val = *(uint16_t *)(dev->tx);
                    } else if (dev->tx && dev->n_bytes == 1) {
                        val = *(uint8_t *)(dev->tx);
                    } else {
                        val = 0;
                    }
                    harness_write32(val, base + DW_SPI_DR);
                }
                r35 = harness_read32(base + DW_SPI_RXFLR);
                max = 1;
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
    uint32_t r42 = 0, r44 = 0;
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
    uint32_t r48 = 0, r50 = 0;
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
    uint32_t r54 = 0, entries = 0, sts = 0, r62 = 0, nents = 0, __return_read_0 = 0;
    uint32_t new_mask = 0;
    int len = 1, retry = 1, room = 1;
    uint8_t buf_val = 0;
    uint8_t *buf = &buf_val;
    int ret = 0;
    int max = 1;
    harness_write32(0, base + DW_SPI_SSIENR);
    r54 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    harness_write32(1, base + DW_SPI_SSIENR);
    while (len--) {
        harness_write32(*buf++, base + DW_SPI_DR);
    }
    while (len) {
        entries = harness_read32(base + DW_SPI_TXFLR);
        while (room && len--) {
            harness_write32(*buf++, base + DW_SPI_DR);
        }
    }
    while (len) {
        entries = harness_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = harness_read32(base + DW_SPI_RISR);
        }
        while (entries && len--) {
            r62 = harness_read32(base + DW_SPI_DR);
        }
    }
    if (ret == 0x0) {
        nents = harness_read32(base + DW_SPI_TXFLR);
        while ((__return_read_0 = harness_read32(base + DW_SPI_SR)) && retry--) {
        }
    }
    harness_write32(0, base + DW_SPI_SSIENR);
    harness_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r68 = 0, r70 = 0, ser = 0, r78 = 0, cr0 = 0, r80 = 0, r105 = 0;
    uint32_t new_mask = 0, tmp = 0;
    int fifo = 0;
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
        if (dev->ctlr == 0x0) {
            if (dev->num_cs == 0x0) {
                harness_write32(0xffff, base + DW_SPI_SER);
                ser = harness_read32(base + DW_SPI_SER);
                harness_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                harness_write32(fifo, base + DW_SPI_TXFTLR);
                r78 = harness_read32(base + DW_SPI_TXFTLR);
            }
            harness_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dev->ver == 0x3230312a) {
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
    if (0x0) {
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
    uint32_t r93 = 0, r95 = 0, ser = 0, r103 = 0, cr0 = 0, r105 = 0;
    uint32_t new_mask = 0, tmp = 0;
    int fifo = 0;
    harness_write32(0, base + DW_SPI_SSIENR);
    r93 = harness_read32(base + DW_SPI_IMR);
    harness_write32(new_mask, base + DW_SPI_IMR);
    r95 = harness_read32(base + DW_SPI_ICR);
    harness_write32(0x0, base + DW_SPI_SER);
    harness_write32(1, base + DW_SPI_SSIENR);
    if (dev->ver == 0x0) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if (dev->ctlr == 0x0) {
        if (dev->num_cs == 0x0) {
            harness_write32(0xffff, base + DW_SPI_SER);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            harness_write32(fifo, base + DW_SPI_TXFTLR);
            r103 = harness_read32(base + DW_SPI_TXFTLR);
        }
        harness_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dev->ver == 0x3230312a) {
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

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, int cs, int enable, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        harness_write32((cs < 4) ? 8192 : sw_mode, base + MSCC_SPI_MST_SW_MODE);
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
    if (enable == 0x0) {
    }
    if ((enable == 0x0) == 0x0) {
    }
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, int cs) {
    if (cs < 0x2) {
    }
}

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.chip_select[0] = 0;
    dev.n_bytes = 1;
    dev.rx_len = 1;
    dev.tx_len = 1;
    dev.irq = IRQ_NOTCONNECTED;
    dev.dma_mapped = 0;
    dev.cur_msg = (void*)1;
    dev.ctlr = (void*)0;
    dev.num_cs = 0;
    dev.fifo_len = 0;
    dev.ver = 0x3230312a;
    dev.caps = DW_SPI_CAP_CS_OVERRIDE;

    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_check_status(&dev, 1, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_update_config(&dev, 0, 0, 1, 1000, 0);
    dw_spi_transfer_one(&dev);
    dw_spi_handle_err(&dev);
    dw_spi_target_abort(&dev);
    dw_spi_exec_mem_op(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_remove_controller(&dev);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 0, 1, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);

    return 0;
}