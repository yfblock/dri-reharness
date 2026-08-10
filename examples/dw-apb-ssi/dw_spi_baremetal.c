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
void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs_high, uint32_t enable) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        mmio_write32((0x1 << dev->chip_select[0]), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dev, uint32_t raw, uint32_t ret) {
    uintptr_t base = dev->base;
    uint32_t irq_status = 0;
    uint32_t r6 = 0, r8 = 0;
    uint32_t new_mask = 0;
    
    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if ((raw == 0x0)) {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        mmio_write32(0, base + DW_SPI_SSIENR);
        r6 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r8 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32(1, base + DW_SPI_SSIENR);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r12 = mmio_read32(base + 0x0);
    uint32_t r13 = 0, r14 = 0, r15 = 0, r17 = 0, tx_room = 0, r22 = 0;
    uint32_t new_mask = 0;
    (void)r12; (void)r13; (void)r14; (void)r15; (void)r17; (void)r22;

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
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
    if ((dev->rx_len == 0x0) == 0x0) {
        r17 = mmio_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r17) {
            mmio_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
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
            mmio_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r25 = 0;
    uint32_t new_mask = 0;
    (void)irq_status; (void)r25;

    if (dev->cur_msg == 0) {
        r25 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dev, uint32_t cr0, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t clk_div, uint32_t rx_sample_dly) {
    uintptr_t base = dev->base;
    uint32_t chip_cr0 = cr0;
    uint32_t chip_rx_sample_dly = rx_sample_dly;

    mmio_write32(chip_cr0, base + DW_SPI_CTRLR0);
    if (((tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        mmio_write32((ndf ? (ndf - 1) : 0), base + DW_SPI_CTRLR1);
    }
    if (dev->current_freq != speed_hz) {
        mmio_write32(clk_div, base + DW_SPI_BAUDR);
    }
    if (dev->cur_rx_sample_dly != chip_rx_sample_dly) {
        mmio_write32(chip_rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    uint32_t r32 = 0, r38 = 0, r39 = 0, r40 = 0, r43 = 0, tx_room = 0;
    uint32_t new_mask = 0;
    (void)r32; (void)r38; (void)r39; (void)r40; (void)r43; (void)tx_room;

    mmio_write32(0, base + DW_SPI_SSIENR);
    r32 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32(1, base + DW_SPI_SSIENR);

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
    mmio_write32(level, base + DW_SPI_TXFTLR);
    mmio_write32((level - 0x1), base + DW_SPI_RXFTLR);
    r43 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r46 = 0, r48 = 0;
    uint32_t new_mask = 0;
    (void)r46; (void)r48;

    mmio_write32(0, base + DW_SPI_SSIENR);
    r46 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r48 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r52 = 0, r54 = 0;
    uint32_t new_mask = 0;
    (void)r52; (void)r54;

    mmio_write32(0, base + DW_SPI_SSIENR);
    r52 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r54 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint32_t len, uint32_t ret) {
    uintptr_t base = dev->base;
    uint32_t r58 = 0, entries = 0, sts = 0, nents = 0, __return_read_0 = 0;
    uint32_t r68 = 0, r69 = 0;
    uint32_t new_mask = 0;
    (void)r58; (void)entries; (void)sts; (void)nents; (void)__return_read_0; (void)r68; (void)r69;

    mmio_write32(0, base + DW_SPI_SSIENR);
    r58 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32(1, base + DW_SPI_SSIENR);

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

    mmio_write32(0, base + DW_SPI_SSIENR);
    mmio_write32(1, base + DW_SPI_SSIENR);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r75 = 0, r77 = 0, ser = 0, r85 = 0, cr0 = 0, r87 = 0;
    uint32_t fifo = 0, tmp = 0;
    uint32_t new_mask = 0;
    int ret = 0;
    (void)r75; (void)r77; (void)ser; (void)r85; (void)cr0; (void)r87; (void)fifo; (void)tmp; (void)ret;

    if (dev) {
        mmio_write32(0, base + DW_SPI_SSIENR);
        r75 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r77 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32(1, base + DW_SPI_SSIENR);
        
        if (dev->ver == 0x0) {
            dev->ver = mmio_read32(base + DW_SPI_VERSION);
        }
        if (dev->ctlr == 0) { /* spi_controller_is_target */
            if (dev->num_cs == 0x0) {
                mmio_write32(0xffff, base + DW_SPI_SER);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                r85 = mmio_read32(base + DW_SPI_TXFTLR);
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dev->caps & 0x1) { /* dw_spi_ip_is PSSI */
            r87 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(0, base + DW_SPI_SSIENR);
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(tmp, base + DW_SPI_CTRLR0);
            mmio_write32(1, base + DW_SPI_SSIENR);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
    if (0x0) {
        if ((((dev->dma_ops) && (0)) && (ret == -EPROBE_DEFER)) == 0x0) {
            if ((((ret < 0x0) && ret) != -ENOTCONN) == 0x0) {
                if (dev) {
                    mmio_write32(0, base + DW_SPI_SSIENR);
                }
            }
        }
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32(0, base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32(0, base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r100 = 0, r102 = 0, ser = 0, r110 = 0, cr0 = 0, r112 = 0;
    uint32_t fifo = 0, tmp = 0;
    uint32_t new_mask = 0;
    (void)r100; (void)r102; (void)ser; (void)r110; (void)cr0; (void)r112; (void)fifo; (void)tmp;

    mmio_write32(0, base + DW_SPI_SSIENR);
    r100 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r102 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32(1, base + DW_SPI_SSIENR);

    if (dev->ver == 0x0) {
        dev->ver = mmio_read32(base + DW_SPI_VERSION);
    }
    if (dev->ctlr == 0) {
        if (dev->num_cs == 0x0) {
            mmio_write32(0xffff, base + DW_SPI_SER);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            r110 = mmio_read32(base + DW_SPI_TXFTLR);
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dev->caps & 0x1) {
        r112 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(0, base + DW_SPI_SSIENR);
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(tmp, base + DW_SPI_CTRLR0);
        mmio_write32(1, base + DW_SPI_SSIENR);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        mmio_write32(((cs < 4) ? 8192 : sw_mode), base + MSCC_SPI_MST_SW_MODE);
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
    uintptr_t base = dev->base;
    (void)base;
    if (enable == 0x0) {}
    if ((enable == 0x0) == 0x0) {}
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs) {
    uintptr_t base = dev->base;
    (void)base;
    if (cs < 0x2) {}
}

#endif /* DW_APB_SSI_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>
int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    
    dw_spi_add_controller(&dev);
    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_update_config(&dev, 0x00, 0, 0, 1000000, 4, 0);
    dw_spi_transfer_one(&dev, 16);
    dw_spi_remove_controller(&dev);
    
    return 0;
}
#endif