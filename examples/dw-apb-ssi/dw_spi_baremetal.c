#include "dw_apb_ssi_baremetal.h"


/* Module Functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs_high, uint32_t enable) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        mmio_write32((0x1 << dev->chip_select[0]), base + DW_SPI_SER);
    } else {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, uint32_t raw, uint32_t ret, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r6;
    uint32_t r8;

    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    } else {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }

    if (ret) {
        mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        r6 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r8 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        if (dev->ctlr) {
            /* state write omitted for missing struct fields */
        }
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r13 = mmio_read32(base + DW_SPI_RXFLR);
    uint32_t rxw;
    uint32_t r20;
    uint32_t r22;
    uint32_t tx_room;
    uint32_t txw = 0;

    while (r13--) {
        rxw = mmio_read32(base + DW_SPI_DR);
        if (dev->rx) {
            if (dev->n_bytes == 0x1) {
                *(uint8_t *)(dev->rx) = rxw;
            } else {
                if (dev->n_bytes == 0x2) {
                    *(uint16_t *)(dev->rx) = rxw;
                } else {
                    *(uint32_t *)(dev->rx) = rxw;
                }
            }
            dev->rx += dev->n_bytes;
        }
        dev->rx_len += -1;
    }

    if (dev->rx_len == 0x0) {
        r20 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    } else {
        r22 = mmio_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r22) {
            mmio_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }

    if (irq_status & 0x1) { /* DW_SPI_INT_TXEI placeholder */
        tx_room = mmio_read32(base + DW_SPI_TXFLR);
        txw = 0x0;
        while (tx_room--) {
            if (dev->tx) {
                if (dev->n_bytes == 0x1) {
                    txw = *(uint8_t *)(dev->tx);
                } else {
                    if (dev->n_bytes == 0x2) {
                        txw = *(uint16_t *)(dev->tx);
                    } else {
                        txw = *(uint32_t *)(dev->tx);
                    }
                }
                dev->tx += dev->n_bytes;
            }
            mmio_write32(txw, base + DW_SPI_DR);
            dev->tx_len += -1;
        }
        if (dev->tx_len == 0x0) {
            uint32_t r32 = mmio_read32(base + DW_SPI_IMR);
            mmio_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev, void *dev_id, uint32_t new_mask) {
    uintptr_t base = dev->base;
    void *ctlr = dev_id;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);

    if (ctlr == 0x0) {
        uint32_t r36 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0_val, uint32_t dfs, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t clk_div, uint32_t rx_sample_dly) {
    uintptr_t base = dev->base;
    uint32_t cr0 = cr0_val;
    cr0 = (cr0 | ((dfs - 0x1) << dev->dfs_offset));

    if (dev->ip == 0) { /* PSSI */
        cr0 = (cr0 | (tmode << 10)); /* FIELD_PREP simulated */
    } else {
        cr0 = (cr0 | (tmode << 10)); /* FIELD_PREP simulated */
    }

    mmio_write32(cr0, base + DW_SPI_CTRLR0);

    if (tmode == 3) { /* DW_SPI_CTRLR0_TMOD_RO */
        mmio_write32((ndf ? (ndf - 0x1) : 0x0), base + DW_SPI_CTRLR1);
    }

    if (dev->current_freq != speed_hz) {
        mmio_write32(clk_div, base + DW_SPI_BAUDR);
        dev->current_freq = speed_hz;
    }

    if (dev->cur_rx_sample_dly != rx_sample_dly) {
        mmio_write32(rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
        dev->cur_rx_sample_dly = rx_sample_dly;
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t new_mask, uint32_t level) {
    uintptr_t base = dev->base;
    uint32_t r56;
    uint32_t r80;
    uint32_t tx_room;
    uint32_t txw;
    uint32_t r69;

    dev->tx = 0; /* transfer->tx_buf */
    dev->tx_len = 0;
    dev->rx = 0; /* transfer->rx_buf */
    dev->rx_len = dev->tx_len;

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r56 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    if (dev->dma_mapped == 0x0) {
        if (dev->irq == 0) { /* IRQ_NOTCONNECTED */
            while (dev->rx_len) {
                tx_room = mmio_read32(base + DW_SPI_TXFLR);
                txw = 0x0;
                while (tx_room--) {
                    if (dev->tx) {
                        if (dev->n_bytes == 0x1) {
                            txw = *(uint8_t *)(dev->tx);
                        } else {
                            if (dev->n_bytes == 0x2) {
                                txw = *(uint16_t *)(dev->tx);
                            } else {
                                txw = *(uint32_t *)(dev->tx);
                            }
                        }
                        dev->tx += dev->n_bytes;
                    }
                    mmio_write32(txw, base + DW_SPI_DR);
                    dev->tx_len += -1;
                }
                r69 = mmio_read32(base + DW_SPI_RXFLR);
                while (r69--) {
                    uint32_t rxw = mmio_read32(base + DW_SPI_DR);
                    if (dev->rx) {
                        if (dev->n_bytes == 0x1) {
                            *(uint8_t *)(dev->rx) = rxw;
                        } else {
                            if (dev->n_bytes == 0x2) {
                                *(uint16_t *)(dev->rx) = rxw;
                            } else {
                                *(uint32_t *)(dev->rx) = rxw;
                            }
                        }
                        dev->rx += dev->n_bytes;
                    }
                    dev->rx_len += -1;
                }
            }
        }
    }

    mmio_write32(level, base + DW_SPI_TXFTLR);
    mmio_write32((level - 0x1), base + DW_SPI_RXFTLR);
    dev->transfer_handler = 0; /* dw_spi_transfer_handler ptr */

    r80 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r83;
    uint32_t r85;

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r83 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r85 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r89;
    uint32_t r91;

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r89 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r91 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, uint8_t *out, uint32_t new_mask, uint32_t data_dir_in, uint32_t data_nbytes) {
    uintptr_t base = dev->base;
    uint32_t r108;
    uint8_t *buf;
    uint32_t entries;
    uint32_t nents;
    uint32_t r120;

    if (len <= 256) { /* DW_SPI_BUF_SIZE */
        /* out = dev->buf; */
    }

    dev->n_bytes = 0x1;
    dev->tx = out;
    dev->tx_len = len;

    if (data_dir_in) {
        dev->rx = 0; /* op->data.buf.in */
        dev->rx_len = data_nbytes;
    } else {
        dev->rx = NULL;
        dev->rx_len = 0x0;
    }

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r108 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    buf = dev->tx;
    while (len--) {
        mmio_write32(*buf++, base + DW_SPI_DR);
    }

    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
        while (entries-- && len) {
            mmio_write32(*buf++, base + DW_SPI_DR);
            len--;
        }
    }

    buf = dev->rx;
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            uint32_t sts = mmio_read32(base + DW_SPI_RISR);
        }
        while (entries-- && len) {
            uint32_t buffer_read_0 = mmio_read32(base + DW_SPI_DR);
            *buf++ = buffer_read_0;
            len--;
        }
    }

    if (1) { /* ret == 0x0 */
        nents = mmio_read32(base + DW_SPI_TXFLR);
        while (1) {
            r120 = mmio_read32(base + DW_SPI_SR);
        }
    }

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev, uint32_t new_mask, uint32_t target) {
    uintptr_t base = dev->base;
    uint32_t r133;
    uint32_t r135;
    uint32_t ser;
    uint32_t r145;
    uint32_t r148;
    uint32_t cr0;

    if (dev) {
        mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        r133 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r135 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

        if (dev->ver == 0x0) {
            dev->ver = mmio_read32(base + DW_SPI_VERSION);
        }

        if (dev->ctlr == 0) { /* spi_controller_is_target placeholder */
            dev->num_cs = 0x1;
        } else {
            if (dev->num_cs == 0x0) {
                mmio_write32(0xffff, base + DW_SPI_SER);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(0x0, base + DW_SPI_SER);
            }
        }

        if (dev->fifo_len == 0x0) {
            uint32_t fifo = 1;
            while (fifo < 0x100) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                r145 = mmio_read32(base + DW_SPI_TXFTLR);
                fifo++;
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
            dev->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
        }

        if (dev->ip == 0) { /* dw_spi_ip_is PSSI */
            r148 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(0, base + DW_SPI_CTRLR0); /* tmp */
            mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
            if ((cr0 & 0x3) == 0x0) { /* DW_PSSI_CTRLR0_DFS_MASK */
                dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
            }
        } else {
            dev->caps |= 0x1; /* DW_SPI_CAP_DFS32 */
        }

        if (dev->caps & 0x2) { /* DW_SPI_CAP_CS_OVERRIDE */
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }

    if (target == 0x0) {
        /* target == 0 branch */
    } else {
        /* target != 0 branch */
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r188;
    uint32_t r190;
    uint32_t ser;
    uint32_t r200;
    uint32_t r203;
    uint32_t cr0;

    mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
    r188 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r190 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);

    if (dev->ver == 0x0) {
        dev->ver = mmio_read32(base + DW_SPI_VERSION);
    }

    if (dev->ctlr == 0) {
        dev->num_cs = 0x1;
    } else {
        if (dev->num_cs == 0x0) {
            mmio_write32(0xffff, base + DW_SPI_SER);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(0x0, base + DW_SPI_SER);
        }
    }

    if (dev->fifo_len == 0x0) {
        uint32_t fifo = 1;
        while (fifo < 0x100) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            r200 = mmio_read32(base + DW_SPI_TXFTLR);
            fifo++;
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
        dev->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
    }

    if (dev->ip == 0) {
        r203 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(0, base + DW_SPI_CTRLR0);
        mmio_write32((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
        if ((cr0 & 0x3) == 0x0) {
            dev->caps |= 0x1;
        }
    } else {
        dev->caps |= 0x1;
    }

    if (dev->caps & 0x2) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        uint32_t sw_mode = 0; /* MSCC_SPI_MST_SW_MODE_SW_PIN_CTRL_MODE */
        mmio_write32(sw_mode, base + MSCC_SPI_MST_SW_MODE);
    }
}

void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dev, uint32_t enable) {
    /* regmap operations omitted for bare metal simplicity */
}

void dw_spi_mscc_sparx5_init(struct dw_apb_ssi_priv *dev) {
    /* regmap operations omitted */
}

void dw_spi_alpine_init(struct dw_apb_ssi_priv *dev) {
    dev->caps = 0x2; /* DW_SPI_CAP_CS_OVERRIDE */
}

void dw_spi_hssi_init(struct dw_apb_ssi_priv *dev) {
    dev->ip = 0x1; /* DW_HSSI_ID */
}

void dw_spi_intel_init(struct dw_apb_ssi_priv *dev) {
    dev->ip = 0x1; /* DW_HSSI_ID */
}

void dw_spi_mountevans_imc_init(struct dw_apb_ssi_priv *dev) {
    dev->fifo_len = 0x1f;
}

void dw_spi_canaan_k210_init(struct dw_apb_ssi_priv *dev) {
    dev->fifo_len = 0x1f;
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    /* regmap operations omitted */
}

void dw_spi_elba_init(struct dw_apb_ssi_priv *dev) {
    /* state assignments omitted */
}

void dw_spi_mmio_probe(struct dw_apb_ssi_priv *dev, uintptr_t paddr, uint32_t bus_num) {
    dev->base = paddr;
    dev->ver = bus_num;
}

#ifdef REHARNESS_BAREMETAL_ORACLE
int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;

    dw_spi_add_controller(&dev, 0, 0);
    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_remove_controller(&dev);

    return 0;
}
#endif