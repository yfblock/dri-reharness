#include "dw_apb_ssi_baremetal.h"


struct dw_spi_chip {
    uint32_t cr0;
    uint32_t rx_sample_dly;
};

struct dw_spi_cfg {
    uint32_t tmode;
    uint32_t ndf;
};

struct dw_spi_mscc_priv {
    struct dw_apb_ssi_priv base_priv;
    void *syscon;
};

struct dw_spi_elba_priv {
    struct dw_apb_ssi_priv base_priv;
    void *priv;
};

/* Helper Macros */
#define dw_spi_ip_is(dws, ip) (0)
#define spi_controller_is_target(c) (0)

/* Module Functions */

static inline void dw_spi_set_cs(struct dw_apb_ssi_priv *dev, int cs_high, int enable) {
    uintptr_t base = dev->base;
    uint32_t new_mask = 0;
    if (cs_high == enable) {
        mmio_write32((0x1 << dev->chip_select[0]), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

static inline void dw_spi_check_status(struct dw_apb_ssi_priv *dev, int raw, int ret) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r6, r8;
    uint32_t new_mask = 0;
    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = mmio_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
        r6 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r8 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    }
}

static inline void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status, r12, rxw, r14, r16, tx_room, r20;
    uint32_t new_mask = 0;
    int max;
    
    irq_status = mmio_read32(base + DW_SPI_ISR);
    r12 = mmio_read32(base + DW_SPI_RXFLR);
    
    max = 64;
    while (max-- > 0) {
        rxw = mmio_read32(base + DW_SPI_DR);
    }
    
    if (dev->rx_len == 0x0) {
        r14 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
    
    if ((dev->rx_len == 0x0) == 0x0) {
        r16 = mmio_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r16) {
            mmio_write32((dev->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }
    
    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = mmio_read32(base + DW_SPI_TXFLR);
        max = 64;
        while (max-- > 0) {
            uint32_t val = 0;
            if (dev->tx && (dev->n_bytes == 1) == 0 && (dev->n_bytes == 2) == 0) {
                val = *(uint32_t *)(dev->tx);
            } else if (dev->tx && (dev->n_bytes == 1) == 0 && dev->n_bytes == 2) {
                val = *(uint16_t *)(dev->tx);
            } else if (dev->tx && dev->n_bytes == 1) {
                val = *(uint8_t *)(dev->tx);
            }
            mmio_write32(val, base + DW_SPI_DR);
        }
        if (dev->tx_len == 0x0) {
            r20 = mmio_read32(base + DW_SPI_IMR);
            mmio_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

static inline void dw_spi_irq(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status, r23;
    uint32_t new_mask = 0;
    
    irq_status = mmio_read32(base + DW_SPI_ISR);
    if (dev->cur_msg == 0) {
        r23 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
}

static inline void dw_spi_update_config(struct dw_apb_ssi_priv *dev, struct dw_spi_chip *chip, struct dw_spi_cfg *cfg, uint32_t speed_hz, uint32_t clk_div) {
    uintptr_t base = dev->base;
    mmio_write32(chip->cr0, base + DW_SPI_CTRLR0);
    
    if (((cfg->tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO)) {
        mmio_write32((cfg->ndf ? (cfg->ndf - 1) : 0), base + DW_SPI_CTRLR1);
    }
    if (dev->current_freq != speed_hz) {
        mmio_write32(clk_div, base + DW_SPI_BAUDR);
    }
    if (dev->cur_rx_sample_dly != chip->rx_sample_dly) {
        mmio_write32(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

static inline void dw_spi_transfer_one(struct dw_apb_ssi_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    uint32_t r30, r39, tx_room, r35, rxw;
    uint32_t new_mask = 0;
    int max;
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r30 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    
    if (dev->dma_mapped == 0x0) {
        if (dev->irq == IRQ_NOTCONNECTED) {
            while (dev->rx_len) {
                tx_room = mmio_read32(base + DW_SPI_TXFLR);
                max = 64;
                while (max-- > 0) {
                    uint32_t val = 0;
                    if (dev->tx && (dev->n_bytes == 1) == 0 && (dev->n_bytes == 2) == 0) {
                        val = *(uint32_t *)(dev->tx);
                    } else if (dev->tx && (dev->n_bytes == 1) == 0 && dev->n_bytes == 2) {
                        val = *(uint16_t *)(dev->tx);
                    } else if (dev->tx && dev->n_bytes == 1) {
                        val = *(uint8_t *)(dev->tx);
                    }
                    mmio_write32(val, base + DW_SPI_DR);
                }
                r35 = mmio_read32(base + DW_SPI_RXFLR);
                max = 64;
                while (max-- > 0) {
                    rxw = mmio_read32(base + DW_SPI_DR);
                }
            }
        }
    }
    
    mmio_write32(level, base + DW_SPI_TXFTLR);
    mmio_write32((level - 0x1), base + DW_SPI_RXFTLR);
    r39 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
}

static inline void dw_spi_handle_err(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r42, r44;
    uint32_t new_mask = 0;
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r42 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r44 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_target_abort(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r48, r50;
    uint32_t new_mask = 0;
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r48 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r50 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dev, uint8_t *buf, uint32_t len) {
    uintptr_t base = dev->base;
    uint32_t r54, entries, sts, r62, nents, __return_read_0;
    uint32_t new_mask = 0;
    int max;
    uint32_t ret = 0;
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r54 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    
    while (len-- > 0) {
        mmio_write32(*buf++, base + DW_SPI_DR);
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
        max = 64;
        while (max-- > 0 && len) {
            mmio_write32(*buf++, base + DW_SPI_DR);
            len--;
        }
    }
    
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = mmio_read32(base + DW_SPI_RISR);
        }
        max = 64;
        while (max-- > 0 && entries) {
            r62 = mmio_read32(base + DW_SPI_DR);
            entries--;
            len--;
        }
    }
    
    if (ret == 0x0) {
        nents = mmio_read32(base + DW_SPI_TXFLR);
        max = 1000;
        while (max-- > 0) {
            __return_read_0 = mmio_read32(base + DW_SPI_SR);
        }
    }
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_add_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r68, r70, ser, r78, r80, cr0, tmp = 0;
    uint32_t new_mask = 0;
    int ret = 0;
    uint32_t fifo = 0;
    
    if (dev) {
        mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
        r68 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r70 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
        
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
            for (fifo = 0; fifo < 0x100; fifo++) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                r78 = mmio_read32(base + DW_SPI_TXFTLR);
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dw_spi_ip_is(dev, PSSI)) {
            r80 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32(tmp, base + DW_SPI_CTRLR0);
            mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
    
    if (0x0) {
        if ((((dev->dma_ops && 0) && (ret == -EPROBE_DEFER)) == 0x0)) {
            if ((((ret < 0x0) && ret) != -ENOTCONN) == 0x0) {
                if (dev) {
                    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
                }
            }
        }
    }
}

static inline void dw_spi_remove_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

static inline void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

static inline void dw_spi_resume_controller(struct dw_apb_ssi_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t r93, r95, ser, r103, r105, cr0, tmp = 0;
    uint32_t new_mask = 0;
    uint32_t fifo = 0;
    
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r93 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r95 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    
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
        for (fifo = 0; fifo < 0x100; fifo++) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            r103 = mmio_read32(base + DW_SPI_TXFTLR);
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dw_spi_ip_is(dev, PSSI)) {
        r105 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32(tmp, base + DW_SPI_CTRLR0);
        mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

static inline void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dev, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dev->base;
    if (cs < 0x4) {
        mmio_write32((cs < 4 ? 8192 : sw_mode), base + MSCC_SPI_MST_SW_MODE);
    }
}

static inline void dw_spi_mscc_ocelot_init(struct dw_spi_mscc_priv *dev) {
    uintptr_t base = dev->base_priv.base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
    /* regmap tx_update omitted */
}

static inline void dw_spi_mscc_jaguar2_init(struct dw_spi_mscc_priv *dev) {
    uintptr_t base = dev->base_priv.base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
    /* regmap tx_update omitted */
}

static inline void dw_spi_sparx5_set_cs(struct dw_spi_mscc_priv *dev, int enable) {
    /* regmap tx_write omitted */
    if (enable == 0x0) {
        /* SPARX5_FORCE_ENA */
        /* SPARX5_FORCE_VAL */
    }
    if ((enable == 0x0) == 0x0) {
        /* SPARX5_FORCE_VAL */
        /* SPARX5_FORCE_ENA */
    }
}

static inline void dw_spi_elba_set_cs(struct dw_spi_elba_priv *dev, uint32_t cs) {
    /* regmap tx_update omitted */
    if (cs < 0x2) {
        /* ELBA_SPICS_REG */
    }
}

#endif /* DW_APB_SSI_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>
int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    dw_spi_add_controller(&dev);
    dw_spi_remove_controller(&dev);
    return 0;
}
#endif