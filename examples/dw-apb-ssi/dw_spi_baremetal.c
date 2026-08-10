#include "dw-apb-ssi_baremetal.h"


struct dw_spi_chip {
    uint32_t cr0;
    uint32_t rx_sample_dly;
};

struct dw_spi_config {
    uint32_t tmode;
    uint32_t ndf;
};

/* Primitive MMIO Helpers */
static inline uint32_t mmio_read32(uintptr_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void mmio_write32(uint32_t val, uintptr_t addr) {
    *(volatile uint32_t *)addr = val;
}

/* Stubs for external dependencies */
static inline uint32_t spi_get_chipselect(void *spi, int idx) { (void)spi; (void)idx; return 0; }
static inline uint32_t spi_controller_is_target(void *ctlr) { (void)ctlr; return 0; }
static inline uint32_t dw_spi_ip_is(struct dw_apb_ssi_priv *dws, uint32_t id) { (void)dws; (void)id; return 1; }
static inline uint32_t dw_spi_ctlr_busy(struct dw_apb_ssi_priv *dws) { (void)dws; return 0; }
static inline uint32_t dw_readl(struct dw_apb_ssi_priv *dws, uint32_t off) { (void)dws; (void)off; return 0; }

/* Module Implementations */

void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs_high, uint32_t enable, void *spi) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        mmio_write32((0x1 << spi_get_chipselect(spi, 0)), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, uint32_t raw) {
    uintptr_t base = dev->base;
    uint32_t irq_status = 0;
    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t offset = 0;
    uint32_t r6 = mmio_read32(dev->regs + offset);
    (void)r6;
    
    if ((dev->rx_len == 0x0) == 0x0) {
        uint32_t r7 = mmio_read32(base + DW_SPI_RXFTLR);
        (void)r7;
        if (dev->rx_len <= dw_readl(dev, DW_SPI_RXFTLR)) {
            mmio_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }
    
    if (irq_status & DW_SPI_INT_TXEI) {
        uint32_t tx_room = mmio_read32(base + DW_SPI_TXFLR);
        (void)tx_room;
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    (void)irq_status;
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, struct dw_spi_chip *chip, struct dw_spi_config *cfg) {
    uintptr_t base = dev->base;
    mmio_write32(chip->cr0, base + DW_SPI_CTRLR0);
    
    if (((cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        uint32_t val = cfg->ndf ? (cfg->ndf - 1) : 0;
        mmio_write32(val, base + DW_SPI_CTRLR1);
    }
    
    if (dev->cur_rx_sample_dly != chip->rx_sample_dly) {
        mmio_write32(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                uint32_t tx_room = mmio_read32(base + DW_SPI_TXFLR);
                (void)tx_room;
                uint32_t offset = 0;
                uint32_t r15 = mmio_read32(dev->regs + offset);
                (void)r15;
            }
        }
    }
    mmio_write32(level, base + DW_SPI_TXFTLR);
    mmio_write32((level - 0x1), base + DW_SPI_RXFTLR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, uint32_t ret, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    uint32_t entries;
    uint32_t nents;
    uint32_t retry = 10;
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            uint32_t sts = mmio_read32(base + DW_SPI_RISR);
            (void)sts;
        }
    }
    
    if (ret == 0x0) {
        nents = mmio_read32(base + DW_SPI_TXFLR);
        (void)nents;
        uint32_t __return_read_0;
        while (dw_spi_ctlr_busy(dev) && retry--) {
            __return_read_0 = mmio_read32(base + DW_SPI_SR);
        }
    }
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    if (dev) {
        if (dev->ver == 0x0) {
            dev->ver = mmio_read32(base + DW_SPI_VERSION);
        }
        if (spi_controller_is_target(dev->ctlr) == 0x0) {
            if (dev->num_cs == 0x0) {
                uint32_t ser;
                mmio_write32(0xffff, base + DW_SPI_SER);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            uint32_t fifo = 0;
            while (fifo < 0x100) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                uint32_t r28 = mmio_read32(base + DW_SPI_TXFTLR);
                (void)r28;
                fifo++;
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dw_spi_ip_is(dev, PSSI)) {
            uint32_t r30 = mmio_read32(base + DW_SPI_CTRLR0);
            (void)r30;
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            uint32_t cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            uint32_t tmp = cr0;
            mmio_write32(tmp, base + DW_SPI_CTRLR0);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    if (dev->ver == 0x0) {
        dev->ver = mmio_read32(base + DW_SPI_VERSION);
    }
    if (spi_controller_is_target(dev->ctlr) == 0x0) {
        if (dev->num_cs == 0x0) {
            uint32_t ser;
            mmio_write32(0xffff, base + DW_SPI_SER);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        uint32_t fifo = 0;
        while (fifo < 0x100) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            uint32_t r40 = mmio_read32(base + DW_SPI_TXFTLR);
            (void)r40;
            fifo++;
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dw_spi_ip_is(dev, PSSI)) {
        uint32_t r42 = mmio_read32(base + DW_SPI_CTRLR0);
        (void)r42;
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        uint32_t cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        uint32_t tmp = cr0;
        mmio_write32(tmp, base + DW_SPI_CTRLR0);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        uint32_t val = (cs < 4) ? 8192 : sw_mode;
        mmio_write32(val, base + MSCC_SPI_MST_SW_MODE);
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
    (void)dev;
    if (enable == 0x0) {
        /* Empty then block */
    }
    if ((enable == 0x0) == 0x0) {
        /* Empty then block */
    }
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    (void)dev;
    if (cs < 0x2) {
        /* Empty then block */
    }
}

#ifdef REHARNESS_BAREMETAL_ORACLE
int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    
    dw_spi_add_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_set_cs(&dev, 1, 1, NULL);
    dw_spi_mscc_set_cs(&dev, 2, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 1);
    
    struct dw_spi_chip chip = {0};
    struct dw_spi_config cfg = {0};
    dw_spi_update_config(&dev, &chip, &cfg);
    
    dw_spi_transfer_one(&dev, 16);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_check_status(&dev, 1);
    dw_spi_exec_mem_op(&dev, 1, 0, 0);
    
    return 0;
}
#endif