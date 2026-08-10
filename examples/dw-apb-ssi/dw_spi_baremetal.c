#include "spi-dw-core_baremetal.h"


/* Stub helper functions for compilation */
static inline uint32_t spi_get_chipselect(void *spi, int idx) {
    (void)spi;
    (void)idx;
    return 0;
}

static inline int spi_controller_is_target(void *ctlr) {
    (void)ctlr;
    return 0;
}

static inline int dw_spi_ip_is(struct spi_dw_core_priv *dws, int ip) {
    (void)dws;
    (void)ip;
    return 1;
}

/* Module Functions */
static inline void dw_spi_set_cs(struct spi_dw_core_priv *dev, int cs_high, int enable, void *spi) {
    uintptr_t base = dev->base;
    uint32_t cs_high_enable = (cs_high == enable);
    
    if (cs_high_enable) {
        mmio_write32((0x1 << spi_get_chipselect(spi, 0)), base + DW_SPI_SER);
    }
    if (!cs_high_enable) {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

static inline void dw_writer(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t tx_room;
    
    tx_room = mmio_read32(base + DW_SPI_TXFLR);
}

static inline void dw_reader(struct spi_dw_core_priv *dev, uint32_t offset) {
    uintptr_t base = dev->regs ? (uintptr_t)dev->regs : dev->base;
    uint32_t r4;
    
    r4 = mmio_read32(base + offset);
}

static inline void dw_spi_check_status(struct spi_dw_core_priv *dev, int raw) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    
    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if (!raw) {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }
}

static inline void dw_spi_transfer_handler(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r8;
    
    irq_status = mmio_read32(base + DW_SPI_ISR);
    
    if (dev->rx_len != 0) {
        r8 = mmio_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r8) {
            mmio_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }
}

static inline void dw_spi_irq(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    
    irq_status = mmio_read32(base + DW_SPI_ISR);
}

static inline void dw_spi_update_config(struct spi_dw_core_priv *dev, void *chip_ptr, void *cfg_ptr) {
    uintptr_t base = dev->base;
    struct { uint32_t cr0; uint32_t rx_sample_dly; } *chip = chip_ptr;
    struct { uint32_t tmode; uint32_t ndf; } *cfg = cfg_ptr;
    
    mmio_write32(chip->cr0, base + DW_SPI_CTRLR0);
    
    if ((cfg->tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
        uint32_t val = cfg->ndf ? (cfg->ndf - 1) : 0;
        mmio_write32(val, base + DW_SPI_CTRLR1);
    }
    
    if (dev->cur_rx_sample_dly != chip->rx_sample_dly) {
        mmio_write32(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

static inline void dw_spi_transfer_one(struct spi_dw_core_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    
    mmio_write32(level, base + DW_SPI_TXFTLR);
    mmio_write32((level - 0x1), base + DW_SPI_RXFTLR);
}

static inline void dw_spi_exec_mem_op(struct spi_dw_core_priv *dev, uint32_t len, int ret) {
    uintptr_t base = dev->base;
    uint32_t entries;
    uint32_t nents;
    uint32_t sts;
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = mmio_read32(base + DW_SPI_RISR);
        }
    }
    
    if (ret == 0x0) {
        nents = mmio_read32(base + DW_SPI_TXFLR);
    }
}

static inline void dw_spi_add_controller(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r25;
    uint32_t r27;
    uint32_t cr0;
    uint32_t tmp;
    uint32_t fifo = 0;
    
    if (dev) {
        if (dev->ver == 0x0) {
            dev->ver = mmio_read32(base + DW_SPI_VERSION);
        }
        
        if (spi_controller_is_target(dev->ctlr) == 0x0) {
            if (dev->num_cs == 0x0) {
                mmio_write32(0xffff, base + DW_SPI_SER);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(0x0, base + DW_SPI_SER);
            }
        }
        
        if (dev->fifo_len == 0x0) {
            while (fifo < 0x100) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                r25 = mmio_read32(base + DW_SPI_TXFTLR);
                fifo++;
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
        }
        
        if (dw_spi_ip_is(dev, 0)) {
            r27 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(tmp, base + DW_SPI_CTRLR0);
        }
        
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
}

static inline void dw_spi_resume_controller(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r37;
    uint32_t r39;
    uint32_t cr0;
    uint32_t tmp;
    uint32_t fifo = 0;
    
    if (dev->ver == 0x0) {
        dev->ver = mmio_read32(base + DW_SPI_VERSION);
    }
    
    if (spi_controller_is_target(dev->ctlr) == 0x0) {
        if (dev->num_cs == 0x0) {
            mmio_write32(0xffff, base + DW_SPI_SER);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(0x0, base + DW_SPI_SER);
        }
    }
    
    if (dev->fifo_len == 0x0) {
        while (fifo < 0x100) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            r37 = mmio_read32(base + DW_SPI_TXFTLR);
            fifo++;
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
    }
    
    if (dw_spi_ip_is(dev, 0)) {
        r39 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(tmp, base + DW_SPI_CTRLR0);
    }
    
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

#endif /* SPI_DW_CORE_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
int main(void) {
    struct spi_dw_core_priv dev = {0};
    dev.base = 0x10000000;
    
    dw_spi_set_cs(&dev, 1, 1, NULL);
    dw_writer(&dev);
    dw_reader(&dev, 0x20);
    dw_spi_check_status(&dev, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    
    struct { uint32_t cr0; uint32_t rx_sample_dly; } chip = {0};
    struct { uint32_t tmode; uint32_t ndf; } cfg = {0};
    dw_spi_update_config(&dev, &chip, &cfg);
    
    dw_spi_transfer_one(&dev, 32);
    dw_spi_exec_mem_op(&dev, 1, 0);
    dw_spi_add_controller(&dev);
    dw_spi_resume_controller(&dev);
    
    return 0;
}
#endif