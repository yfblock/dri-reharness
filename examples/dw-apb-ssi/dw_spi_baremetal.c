#include "dw-apb-ssi_baremetal.h"


/* Primitive MMIO Helpers */
static inline uint8_t mmio_read8(uintptr_t addr) {
    return *(volatile uint8_t *)addr;
}

static inline uint16_t mmio_read16(uintptr_t addr) {
    return *(volatile uint16_t *)addr;
}

static inline uint32_t mmio_read32(uintptr_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void mmio_write8(uint8_t val, uintptr_t addr) {
    *(volatile uint8_t *)addr = val;
}

static inline void mmio_write16(uint16_t val, uintptr_t addr) {
    *(volatile uint16_t *)addr = val;
}

static inline void mmio_write32(uint32_t val, uintptr_t addr) {
    *(volatile uint32_t *)addr = val;
}

/* Module Functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs_high, uint32_t enable, uint32_t chip_select) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        mmio_write32(DW_SPI_SER, base + (1 << chip_select));
    }
    if ((cs_high == enable) == 0x0) {
        mmio_write32(DW_SPI_SER, base + 0x0);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, uint32_t raw, uint32_t ret, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r6;
    uint32_t r8;
    
    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
        r6 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
        r8 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(DW_SPI_SER, base + 0x0);
        mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r12 = mmio_read32(base + 0x0);
    uint32_t r13;
    uint32_t r14;
    uint32_t r15;
    uint32_t r17;
    uint32_t tx_room;
    uint32_t r22;
    
    while (1) {
        if (dev->reg_io_width == 0x2) {
            r13 = mmio_read16(base + 0x0);
        }
        if (dev->reg_io_width == 0x4) {
            r14 = mmio_read32(base + 0x0);
        }
    }
    
    if (dev->rx_len == 0x0) {
        r15 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    }
    if ((dev->rx_len == 0x0) == 0x0) {
        r17 = mmio_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r17) {
            mmio_write32(DW_SPI_RXFTLR, dev->regs + (dev->rx_len - 1));
        }
    }
    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = mmio_read32(base + DW_SPI_TXFLR);
        while (1) {
            if (dev->reg_io_width == 0x2) {
                mmio_write16(0, base + 0x0);
            }
            if (dev->reg_io_width == 0x4) {
                mmio_write32(0, base + 0x0);
            }
        }
        if (dev->tx_len == 0x0) {
            r22 = mmio_read32(base + DW_SPI_IMR);
            mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r25;
    
    if (dev->cur_msg == 0) {
        r25 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t clk_div, uint32_t rx_sample_dly) {
    uintptr_t base = dev->base;
    
    mmio_write32(DW_SPI_CTRLR0, dev->regs + cr0);
    if ((tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | tmode)) == DW_SPI_CTRLR0_TMOD_RO) {
        uint32_t val = ndf ? (ndf - 1) : 0;
        mmio_write32(DW_SPI_CTRLR1, dev->regs + val);
    }
    if (dev->current_freq != speed_hz) {
        mmio_write32(DW_SPI_BAUDR, dev->regs + clk_div);
    }
    if (dev->cur_rx_sample_dly != rx_sample_dly) {
        mmio_write32(DW_SPI_RX_SAMPLE_DLY, dev->regs + rx_sample_dly);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t new_mask, uint32_t level) {
    uintptr_t base = dev->base;
    uint32_t r32;
    uint32_t tx_room;
    uint32_t r38;
    uint32_t r39;
    uint32_t r40;
    uint32_t r43;
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    r32 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
    
    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                tx_room = mmio_read32(base + DW_SPI_TXFLR);
                while (1) {
                    if (dev->reg_io_width == 0x2) {
                        mmio_write16(0, base + 0x0);
                    }
                    if (dev->reg_io_width == 0x4) {
                        mmio_write32(0, base + 0x0);
                    }
                }
                r38 = mmio_read32(base + 0x0);
                while (1) {
                    if (dev->reg_io_width == 0x2) {
                        r39 = mmio_read16(base + 0x0);
                    }
                    if (dev->reg_io_width == 0x4) {
                        r40 = mmio_read32(base + 0x0);
                    }
                }
            }
        }
    }
    
    mmio_write32(DW_SPI_TXFTLR, dev->regs + level);
    mmio_write32(DW_SPI_RXFTLR, dev->regs + (level - 1));
    r43 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r46 = mmio_read32(base + DW_SPI_IMR);
    uint32_t r48 = mmio_read32(base + DW_SPI_ICR);
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    mmio_write32(DW_SPI_SER, base + 0x0);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r52 = mmio_read32(base + DW_SPI_IMR);
    uint32_t r54 = mmio_read32(base + DW_SPI_ICR);
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    mmio_write32(DW_SPI_SER, base + 0x0);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, uint32_t ret) {
    uintptr_t base = dev->base;
    uint32_t r58 = mmio_read32(base + DW_SPI_IMR);
    uint32_t entries;
    uint32_t sts;
    uint32_t r68;
    uint32_t r69;
    uint32_t nents;
    uint32_t __return_read_0;
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_IMR, dev->regs + 0);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
    
    while (len--) {
        if (dev->reg_io_width == 0x2) {
            mmio_write16(0, base + 0x0);
        }
        if (dev->reg_io_width == 0x4) {
            mmio_write32(0, base + 0x0);
        }
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
        while (1) {
            if (dev->reg_io_width == 0x2) {
                mmio_write16(0, base + 0x0);
            }
            if (dev->reg_io_width == 0x4) {
                mmio_write32(0, base + 0x0);
            }
        }
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = mmio_read32(base + DW_SPI_RISR);
        }
        while (1) {
            if (dev->reg_io_width == 0x2) {
                r68 = mmio_read16(base + 0x0);
            }
            if (dev->reg_io_width == 0x4) {
                r69 = mmio_read32(base + 0x0);
            }
        }
    }
    
    if (ret == 0x0) {
        nents = mmio_read32(base + DW_SPI_TXFLR);
        while (1) {
            __return_read_0 = mmio_read32(base + DW_SPI_SR);
        }
    }
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r75;
    uint32_t r77;
    uint32_t ser;
    uint32_t r85;
    uint32_t r87;
    uint32_t cr0;
    uint32_t fifo;
    
    if (dev) {
        mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
        r75 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
        r77 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(DW_SPI_SER, base + 0x0);
        mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
        
        if (dev->ver == 0x0) {
            dev->ver = mmio_read32(base + DW_SPI_VERSION);
        }
        if (dev->ctlr == 0) {
            if (dev->num_cs == 0x0) {
                mmio_write32(DW_SPI_SER, base + 0xffff);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(DW_SPI_SER, base + 0x0);
            }
        }
        if (dev->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                mmio_write32(DW_SPI_TXFTLR, dev->regs + fifo);
                r85 = mmio_read32(base + DW_SPI_TXFTLR);
            }
            mmio_write32(DW_SPI_TXFTLR, base + 0x0);
        }
        if (dev->ver == 0x53535301) { /* PSSI Check Mock */
            r87 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
            mmio_write32(DW_SPI_CTRLR0, base + 0xffffffff);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(DW_SPI_CTRLR0, dev->regs + cr0);
            mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            mmio_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
        }
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_BAUDR, dev->regs + 0);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_BAUDR, dev->regs + 0);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev, uint32_t new_mask) {
    uintptr_t base = dev->base;
    uint32_t r100 = mmio_read32(base + DW_SPI_IMR);
    uint32_t r102 = mmio_read32(base + DW_SPI_ICR);
    uint32_t ser;
    uint32_t r110;
    uint32_t r112;
    uint32_t cr0;
    uint32_t fifo;
    
    mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
    mmio_write32(DW_SPI_IMR, dev->regs + new_mask);
    mmio_write32(DW_SPI_SER, base + 0x0);
    mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
    
    if (dev->ver == 0x0) {
        dev->ver = mmio_read32(base + DW_SPI_VERSION);
    }
    if (dev->ctlr == 0) {
        if (dev->num_cs == 0x0) {
            mmio_write32(DW_SPI_SER, base + 0xffff);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(DW_SPI_SER, base + 0x0);
        }
    }
    if (dev->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            mmio_write32(DW_SPI_TXFTLR, dev->regs + fifo);
            r110 = mmio_read32(base + DW_SPI_TXFTLR);
        }
        mmio_write32(DW_SPI_TXFTLR, base + 0x0);
    }
    if (dev->ver == 0x53535301) { /* PSSI Check Mock */
        r112 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(DW_SPI_SSIENR, dev->regs + 0);
        mmio_write32(DW_SPI_CTRLR0, base + 0xffffffff);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(DW_SPI_CTRLR0, dev->regs + cr0);
        mmio_write32(DW_SPI_SSIENR, dev->regs + 1);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        mmio_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        uint32_t val = (cs < 4) ? 8192 : sw_mode;
        mmio_write32(MSCC_SPI_MST_SW_MODE, base + MSCC_SPI_MST_SW_MODE);
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
    if (enable == 0x0) {
        /* Empty branch */
    }
    if ((enable == 0x0) == 0x0) {
        /* Empty branch */
    }
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    if (cs < 0x2) {
        /* Empty branch */
    }
}

#endif /* DW_APB_SSI_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dev.regs = dev.base;
    
    dw_spi_set_cs(&dev, 1, 1, 0);
    dw_spi_check_status(&dev, 1, 1, 0);
    dw_spi_transfer_handler(&dev, 0);
    dw_spi_irq(&dev, 0);
    dw_spi_update_config(&dev, 0, 0, 0, 1000000, 2, 0);
    dw_spi_transfer_one(&dev, 0, 16);
    dw_spi_handle_err(&dev, 0);
    dw_spi_target_abort(&dev, 0);
    dw_spi_exec_mem_op(&dev, 16, 0);
    dw_spi_add_controller(&dev, 0);
    dw_spi_remove_controller(&dev);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev, 0);
    dw_spi_mscc_set_cs(&dev, 0, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);
    
    return 0;
}
#endif