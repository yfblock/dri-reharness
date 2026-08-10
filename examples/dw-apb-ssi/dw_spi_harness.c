#include "dw-apb-ssi_harness.h"


struct chip {
    uint32_t rx_sample_dly;
};

struct cfg {
    uint32_t tmode;
    uint32_t ndf;
};

/* Dummy helper functions */
static inline int spi_get_chipselect(void *spi, int idx) { return 0; }
static inline int spi_controller_is_target(void *ctlr) { return 0; }
static inline int dw_spi_ip_is(struct dw_apb_ssi_priv *dws, int id) { return 1; }
#define PSSI 0
static inline int dw_spi_ctlr_busy(struct dw_apb_ssi_priv *dws) { return 0; }

/* Module Functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int cs_high, int enable, void *spi) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        harness_write32(DW_SPI_SER, base + (1 << spi_get_chipselect(spi, 0)));
    }
    if ((cs_high == enable) == 0x0) {
        harness_write32(DW_SPI_SER, base + 0x0);
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
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
    uint32_t r6 = harness_read32(base + 0x0);
    if (((dev->rx_len == 0x0) == 0x0)) {
        uint32_t r7 = harness_read32(base + DW_SPI_RXFTLR);
        if ((dev->rx_len <= r7)) {
            harness_write32(DW_SPI_RXFTLR, base + (dev->rx_len - 1));
        }
    }
    if ((irq_status & DW_SPI_INT_TXEI)) {
        uint32_t tx_room = harness_read32(base + DW_SPI_TXFLR);
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0, struct cfg *cfg, uint32_t speed_hz, uint32_t clk_div, struct chip *chip) {
    uintptr_t base = dev->base;
    harness_write32(DW_SPI_CTRLR0, base + cr0);
    if (((cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        harness_write32(DW_SPI_CTRLR1, base + (cfg->ndf ? (cfg->ndf - 1) : 0));
    }
    if ((dev->current_freq != speed_hz)) {
        harness_write32(DW_SPI_BAUDR, base + clk_div);
    }
    if ((dev->cur_rx_sample_dly != chip->rx_sample_dly)) {
        harness_write32(DW_SPI_RX_SAMPLE_DLY, base + chip->rx_sample_dly);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    harness_write32(DW_SPI_SSIENR, base + 0);
    harness_write32(DW_SPI_SSIENR, base + 1);
    if ((dev->dma_mapped == 0x0)) {
        if ((dev->irq == IRQ_NOTCONNECTED)) {
            while (dev->rx_len) {
                uint32_t tx_room = harness_read32(base + DW_SPI_TXFLR);
                uint32_t r18 = harness_read32(base + 0x0);
            }
        }
    }
    harness_write32(DW_SPI_TXFTLR, base + level);
    harness_write32(DW_SPI_RXFTLR, base + (level - 1));
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, int ret) {
    uintptr_t base = dev->base;
    harness_write32(DW_SPI_SSIENR, base + 0);
    harness_write32(DW_SPI_SSIENR, base + 1);
    while (len) {
        uint32_t entries = harness_read32(base + DW_SPI_TXFLR);
    }
    while (len) {
        uint32_t entries = harness_read32(base + DW_SPI_RXFLR);
        if ((entries == 0x0)) {
            uint32_t sts = harness_read32(base + DW_SPI_RISR);
        }
    }
    if ((ret == 0x0)) {
        uint32_t nents = harness_read32(base + DW_SPI_TXFLR);
        int retry = 1000;
        while ((dw_spi_ctlr_busy(dev) && retry--)) {
            uint32_t __return_read_0 = harness_read32(base + DW_SPI_SR);
        }
    }
    harness_write32(DW_SPI_SSIENR, base + 0);
    harness_write32(DW_SPI_SSIENR, base + 1);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev, int ret) {
    uintptr_t base = dev->base;
    if (dev) {
        if ((dev->ver == 0x0)) {
            dev->ver = harness_read32(base + DW_SPI_VERSION);
        }
        if ((spi_controller_is_target(dev->ctlr) == 0x0)) {
            if ((dev->num_cs == 0x0)) {
                harness_write32(DW_SPI_SER, base + 0xffff);
                uint32_t ser = harness_read32(base + DW_SPI_SER);
                harness_write32(DW_SPI_SER, base + 0x0);
            }
        }
        if ((dev->fifo_len == 0x0)) {
            for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
                harness_write32(DW_SPI_TXFTLR, base + fifo);
                uint32_t r35 = harness_read32(base + DW_SPI_TXFTLR);
            }
            harness_write32(DW_SPI_TXFTLR, base + 0x0);
        }
        if (dw_spi_ip_is(dev, PSSI)) {
            uint32_t r37 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(DW_SPI_SSIENR, base + 0);
            harness_write32(DW_SPI_CTRLR0, base + 0xffffffff);
            uint32_t cr0 = harness_read32(base + DW_SPI_CTRLR0);
            uint32_t tmp = 0;
            harness_write32(DW_SPI_CTRLR0, base + tmp);
            harness_write32(DW_SPI_SSIENR, base + 1);
        }
        if ((dev->caps & DW_SPI_CAP_CS_OVERRIDE)) {
            harness_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
        }
    }
    if (0x0) {
        if ((((dev->dma_ops && ((void**)dev->dma_ops)[0]) && (ret == -EPROBE_DEFER)) == 0x0)) {
            if ((((ret < 0x0) && ret) != -ENOTCONN) == 0x0) {
                if (dev) {
                    harness_write32(DW_SPI_SSIENR, base + 0);
                }
            }
        }
    }
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    if ((dev->ver == 0x0)) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if ((spi_controller_is_target(dev->ctlr) == 0x0)) {
        if ((dev->num_cs == 0x0)) {
            harness_write32(DW_SPI_SER, base + 0xffff);
            uint32_t ser = harness_read32(base + DW_SPI_SER);
            harness_write32(DW_SPI_SER, base + 0x0);
        }
    }
    if ((dev->fifo_len == 0x0)) {
        for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
            harness_write32(DW_SPI_TXFTLR, base + fifo);
            uint32_t r50 = harness_read32(base + DW_SPI_TXFTLR);
        }
        harness_write32(DW_SPI_TXFTLR, base + 0x0);
    }
    if (dw_spi_ip_is(dev, PSSI)) {
        uint32_t r52 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(DW_SPI_SSIENR, base + 0);
        harness_write32(DW_SPI_CTRLR0, base + 0xffffffff);
        uint32_t cr0 = harness_read32(base + DW_SPI_CTRLR0);
        uint32_t tmp = 0;
        harness_write32(DW_SPI_CTRLR0, base + tmp);
        harness_write32(DW_SPI_SSIENR, base + 1);
    }
    if ((dev->caps & DW_SPI_CAP_CS_OVERRIDE)) {
        harness_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if ((cs < 0x4)) {
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
    if ((enable == 0x0)) {
    }
    if (((enable == 0x0) == 0x0)) {
    }
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    if ((cs < 0x2)) {
    }
}

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.rx_len = 1;
    dev.irq = IRQ_NOTCONNECTED;

    dw_spi_set_cs(&dev, 1, 1, NULL);
    dw_spi_check_status(&dev, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    
    struct cfg cfg = {0};
    struct chip chip = {0};
    dw_spi_update_config(&dev, 0, &cfg, 1000, 2, &chip);
    
    dw_spi_transfer_one(&dev, 16);
    dw_spi_exec_mem_op(&dev, 1, 0);
    dw_spi_add_controller(&dev, 0);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 0, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);

    return 0;
}