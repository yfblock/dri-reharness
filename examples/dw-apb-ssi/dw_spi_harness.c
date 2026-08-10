#include "dw-apb-ssi_harness.h"


/* Helper functions */
static inline int spi_get_chipselect(int port, int idx) {
    return 0;
}

static inline int spi_controller_is_target(int ctrl) {
    return ctrl;
}

static inline int dw_spi_ip_is(struct dw_apb_ssi_priv *dws, int type) {
    return dws->ip_pssi;
}

static inline int dw_spi_ctlr_busy(struct dw_apb_ssi_priv *dws) {
    return 1;
}

static inline uint32_t dw_readl(struct dw_apb_ssi_priv *dws, uint32_t offset) {
    return harness_read32(dws->base + offset);
}

/* Module functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int cs_high, int enable) {
    uintptr_t base = dev->base;
    uint32_t cs;

    if (cs_high == enable) {
        cs = (0x1 << spi_get_chipselect(0, 0));
        harness_write32(cs, base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        harness_write32(0x0, base + DW_SPI_SER);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, int raw) {
    uintptr_t base = dev->base;
    uint32_t irq_status;

    if (raw) {
        irq_status = harness_read32(base + DW_SPI_RISR);
    }
    if ((raw == 0x0)) {
        irq_status = harness_read32(base + DW_SPI_ISR);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r6;
    uint32_t r7;
    uint32_t tx_room;

    irq_status = harness_read32(base + DW_SPI_ISR);
    r6 = harness_read32(base + 0x0); /* Computed offset */

    if ((dev->rx_len == 0x0) == 0x0) {
        r7 = harness_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= dw_readl(dev, DW_SPI_RXFTLR)) {
            harness_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }

    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = harness_read32(base + DW_SPI_TXFLR);
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;

    irq_status = harness_read32(base + DW_SPI_ISR);
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    struct dw_apb_ssi_priv *chip = dev;
    struct dw_apb_ssi_priv *cfg = dev;

    harness_write32(chip->cr0, base + DW_SPI_CTRLR0);

    if (((cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        uint32_t val = cfg->ndf ? (cfg->ndf - 1) : 0;
        harness_write32(val, base + DW_SPI_CTRLR1);
    }

    if (dev->cur_rx_sample_dly != chip->rx_sample_dly) {
        harness_write32(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t level = 0;
    uint32_t tx_room;
    uint32_t r15;

    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                tx_room = harness_read32(base + DW_SPI_TXFLR);
                r15 = harness_read32(base + 0x0); /* Computed offset */
            }
        }
    }

    harness_write32(level, base + DW_SPI_TXFTLR);
    harness_write32((level - 0x1), base + DW_SPI_RXFTLR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t len = 1;
    uint32_t entries;
    uint32_t sts;
    uint32_t nents;
    uint32_t __return_read_0;
    int ret = 0;
    int retry = 1;

    while (len) {
        entries = harness_read32(base + DW_SPI_TXFLR);
        break;
    }

    while (len) {
        entries = harness_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = harness_read32(base + DW_SPI_RISR);
        }
        break;
    }

    if (ret == 0x0) {
        nents = harness_read32(base + DW_SPI_TXFLR);
        while (dw_spi_ctlr_busy(dev) && retry--) {
            __return_read_0 = harness_read32(base + DW_SPI_SR);
            break;
        }
    }
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r28;
    uint32_t r30;
    uint32_t cr0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;

    if (dev) {
        if (dev->ver == 0x0) {
            dev->ver = harness_read32(base + DW_SPI_VERSION);
        }
        if (spi_controller_is_target(dev->is_target) == 0x0) {
            if (dev->num_cs == 0x0) {
                harness_write32(0xffff, base + DW_SPI_SER);
                ser = harness_read32(base + DW_SPI_SER);
                harness_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                harness_write32(fifo, base + DW_SPI_TXFTLR);
                r28 = harness_read32(base + DW_SPI_TXFTLR);
            }
            harness_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dw_spi_ip_is(dev, 1)) {
            r30 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(tmp, base + DW_SPI_CTRLR0);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r40;
    uint32_t r42;
    uint32_t cr0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;

    if (dev->ver == 0x0) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if (spi_controller_is_target(dev->is_target) == 0x0) {
        if (dev->num_cs == 0x0) {
            harness_write32(0xffff, base + DW_SPI_SER);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            harness_write32(fifo, base + DW_SPI_TXFTLR);
            r40 = harness_read32(base + DW_SPI_TXFTLR);
        }
        harness_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dw_spi_ip_is(dev, 1)) {
        r42 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(tmp, base + DW_SPI_CTRLR0);
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
}

void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dev, int enable) {
    if (enable == 0x0) {}
    if ((enable == 0x0) == 0x0) {}
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    if (cs < 0x2) {}
}

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.rx_len = 1;
    dev.ip_pssi = 1;
    dev.caps = DW_SPI_CAP_CS_OVERRIDE;

    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_check_status(&dev, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_update_config(&dev);
    dw_spi_transfer_one(&dev);
    dw_spi_exec_mem_op(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 0, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);

    return 0;
}