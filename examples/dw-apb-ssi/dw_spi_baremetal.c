#include "dw_apb_ssi_baremetal.h"


struct dw_spi_cfg {
    uint32_t tmode;
    uint32_t ndf;
};

struct dw_apb_ssi_priv {
    uintptr_t base;
    
    uint8_t chip_select[4];
    uint32_t ver;
    uint32_t num_cs;
    uint32_t fifo_len;
    uint32_t caps;
    uint32_t current_freq;
    uint32_t cur_rx_sample_dly;
    int irq;
    int dma_mapped;
    
    const void *tx;
    uint32_t n_bytes;
    uint32_t tx_len;
    uint32_t rx_len;
    
    void *ctlr;
    void *cur_msg;
    
    struct dw_spi_chip *chip;
    struct dw_spi_cfg *cfg;
};

/* Helper Macros */
#define dw_spi_ip_is(dws, ip) (1)
#define spi_controller_is_target(c) (0)

/* Module Functions */

static inline void dw_spi_set_cs(struct dw_apb_ssi_priv *dws, int cs_high, int enable) {
    uintptr_t base = dws->base;
    if (cs_high == enable) {
        mmio_write32((0x1 << dws->chip_select[0]), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        mmio_write32(0x0, base + DW_SPI_SER);
    }
}

static inline void dw_spi_check_status(struct dw_apb_ssi_priv *dws, int raw, int ret) {
    uintptr_t base = dws->base;
    uint32_t irq_status;
    uint32_t r6;
    uint32_t r8;
    uint32_t new_mask = 0;

    if (raw) {
        irq_status = mmio_read32(base + DW_SPI_RISR);
    }
    if ((raw == 0x0)) {
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

static inline void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r12 = mmio_read32(base + 0x0);
    uint32_t rxw;
    uint32_t r14;
    uint32_t r16;
    uint32_t tx_room;
    uint32_t r20;
    uint32_t new_mask = 0;

    if (dws->rx_len) {
        rxw = mmio_read32(base + DW_SPI_DR);
    }

    if ((dws->rx_len == 0x0)) {
        r14 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
    if (((dws->rx_len == 0x0) == 0x0)) {
        r16 = mmio_read32(base + DW_SPI_RXFTLR);
        if ((dws->rx_len <= r16)) {
            mmio_write32((dws->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }
    if ((irq_status & DW_SPI_INT_TXEI)) {
        tx_room = mmio_read32(base + DW_SPI_TXFLR);
        if (tx_room) {
            uint32_t val = (dws->tx && ((dws->n_bytes == 1) == 0) && ((dws->n_bytes == 2) == 0)) ? *(uint32_t *)(dws->tx) : 
                           ((dws->tx && ((dws->n_bytes == 1) == 0) && (dws->n_bytes == 2)) ? *(uint16_t *)(dws->tx) : 
                           ((dws->tx && (dws->n_bytes == 1)) ? *(uint8_t *)(dws->tx) : 0));
            mmio_write32(val, base + DW_SPI_DR);
        }
        if ((dws->tx_len == 0x0)) {
            r20 = mmio_read32(base + DW_SPI_IMR);
            mmio_write32(new_mask, base + DW_SPI_IMR);
        }
    }
}

static inline void dw_spi_irq(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t irq_status = mmio_read32(base + DW_SPI_ISR);
    uint32_t r23;
    uint32_t new_mask = 0;

    if ((dws->cur_msg == 0x0)) {
        r23 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
    }
}

static inline void dw_spi_update_config(struct dw_apb_ssi_priv *dws, uint32_t speed_hz, uint32_t clk_div) {
    uintptr_t base = dws->base;
    mmio_write32(dws->chip->cr0, base + DW_SPI_CTRLR0);
    if (((dws->cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | dws->cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        mmio_write32((dws->cfg->ndf ? (dws->cfg->ndf - 1) : 0), base + DW_SPI_CTRLR1);
    }
    if ((dws->current_freq != speed_hz)) {
        mmio_write32(clk_div, base + DW_SPI_BAUDR);
    }
    if ((dws->cur_rx_sample_dly != dws->chip->rx_sample_dly)) {
        mmio_write32(dws->chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

static inline void dw_spi_transfer_one(struct dw_apb_ssi_priv *dws, uint32_t level) {
    uintptr_t base = dws->base;
    uint32_t r30;
    uint32_t r39;
    uint32_t tx_room;
    uint32_t rxw;
    uint32_t r35;
    uint32_t new_mask = 0;

    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r30 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);

    if ((dws->dma_mapped == 0x0)) {
        if ((dws->irq == IRQ_NOTCONNECTED)) {
            while (dws->rx_len) {
                tx_room = mmio_read32(base + DW_SPI_TXFLR);
                if (tx_room) {
                    uint32_t val = (dws->tx && ((dws->n_bytes == 1) == 0) && ((dws->n_bytes == 2) == 0)) ? *(uint32_t *)(dws->tx) : 
                                   ((dws->tx && ((dws->n_bytes == 1) == 0) && (dws->n_bytes == 2)) ? *(uint16_t *)(dws->tx) : 
                                   ((dws->tx && (dws->n_bytes == 1)) ? *(uint8_t *)(dws->tx) : 0));
                    mmio_write32(val, base + DW_SPI_DR);
                }
                r35 = mmio_read32(base + 0x0);
                if (dws->rx_len) {
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

static inline void dw_spi_handle_err(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r42;
    uint32_t r44;
    uint32_t new_mask = 0;

    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r42 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r44 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_target_abort(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r48;
    uint32_t r50;
    uint32_t new_mask = 0;

    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r48 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r50 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dws, uint8_t *buf, uint32_t len, int ret) {
    uintptr_t base = dws->base;
    uint32_t entries;
    uint32_t sts;
    uint32_t r62;
    uint32_t nents;
    uint32_t __return_read_0;
    uint32_t new_mask = 0;

    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    uint32_t r54 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);

    while (len--) {
        mmio_write32(*buf++, base + DW_SPI_DR);
    }
    while (len) {
        entries = mmio_read32(base + DW_SPI_TXFLR);
        uint32_t room = 0; /* dummy room */
        while (room && len) {
            mmio_write32(*buf++, base + DW_SPI_DR);
            len--;
        }
    }
    while (len) {
        entries = mmio_read32(base + DW_SPI_RXFLR);
        if ((entries == 0x0)) {
            sts = mmio_read32(base + DW_SPI_RISR);
        }
        while (entries && len) {
            r62 = mmio_read32(base + DW_SPI_DR);
            len--;
        }
    }
    if ((ret == 0x0)) {
        nents = mmio_read32(base + DW_SPI_TXFLR);
        int retry = 1000;
        while ((dw_spi_ip_is(dws, PSSI) && retry--)) {
            __return_read_0 = mmio_read32(base + DW_SPI_SR);
        }
    }
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static inline void dw_spi_add_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r68;
    uint32_t r70;
    uint32_t ser;
    uint32_t r80;
    uint32_t cr0;
    uint32_t r78;
    uint32_t new_mask = 0;

    if (dws) {
        mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
        r68 = mmio_read32(base + DW_SPI_IMR);
        mmio_write32(new_mask, base + DW_SPI_IMR);
        r70 = mmio_read32(base + DW_SPI_ICR);
        mmio_write32(0x0, base + DW_SPI_SER);
        mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
        if ((dws->ver == 0x0)) {
            dws->ver = mmio_read32(base + DW_SPI_VERSION);
        }
        if ((spi_controller_is_target(dws->ctlr) == 0x0)) {
            if ((dws->num_cs == 0x0)) {
                mmio_write32(0xffff, base + DW_SPI_SER);
                ser = mmio_read32(base + DW_SPI_SER);
                mmio_write32(0x0, base + DW_SPI_SER);
            }
        }
        if ((dws->fifo_len == 0x0)) {
            for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
                mmio_write32(fifo, base + DW_SPI_TXFTLR);
                r78 = mmio_read32(base + DW_SPI_TXFTLR);
            }
            mmio_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dw_spi_ip_is(dws, PSSI)) {
            r80 = mmio_read32(base + DW_SPI_CTRLR0);
            mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
            mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = mmio_read32(base + DW_SPI_CTRLR0);
            uint32_t tmp = cr0;
            mmio_write32(tmp, base + DW_SPI_CTRLR0);
            mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
        }
        if ((dws->caps & DW_SPI_CAP_CS_OVERRIDE)) {
            mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
    if (0x0) {
        int ret = 0;
        if ((((dws->dma_ops && 0) && (ret == -EPROBE_DEFER)) == 0x0)) {
            if ((((ret < 0x0) && ret) != -ENOTCONN) == 0x0) {
                if (dws) {
                    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
                }
            }
        }
    }
}

static inline void dw_spi_remove_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

static inline void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    mmio_write32(0x0, base + DW_SPI_BAUDR);
}

static inline void dw_spi_resume_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r93;
    uint32_t r95;
    uint32_t ser;
    uint32_t r103;
    uint32_t r105;
    uint32_t cr0;
    uint32_t new_mask = 0;

    mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r93 = mmio_read32(base + DW_SPI_IMR);
    mmio_write32(new_mask, base + DW_SPI_IMR);
    r95 = mmio_read32(base + DW_SPI_ICR);
    mmio_write32(0x0, base + DW_SPI_SER);
    mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    if ((dws->ver == 0x0)) {
        dws->ver = mmio_read32(base + DW_SPI_VERSION);
    }
    if ((spi_controller_is_target(dws->ctlr) == 0x0)) {
        if ((dws->num_cs == 0x0)) {
            mmio_write32(0xffff, base + DW_SPI_SER);
            ser = mmio_read32(base + DW_SPI_SER);
            mmio_write32(0x0, base + DW_SPI_SER);
        }
    }
    if ((dws->fifo_len == 0x0)) {
        for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
            mmio_write32(fifo, base + DW_SPI_TXFTLR);
            r103 = mmio_read32(base + DW_SPI_TXFTLR);
        }
        mmio_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dw_spi_ip_is(dws, PSSI)) {
        r105 = mmio_read32(base + DW_SPI_CTRLR0);
        mmio_write32((0 ? 1 : 0), base + DW_SPI_SSIENR);
        mmio_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = mmio_read32(base + DW_SPI_CTRLR0);
        uint32_t tmp = cr0;
        mmio_write32(tmp, base + DW_SPI_CTRLR0);
        mmio_write32((1 ? 1 : 0), base + DW_SPI_SSIENR);
    }
    if ((dws->caps & DW_SPI_CAP_CS_OVERRIDE)) {
        mmio_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

static inline void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dws, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dws->base;
    if ((cs < 0x4)) {
        mmio_write32(((cs < 4) ? 8192 : sw_mode), base + MSCC_SPI_MST_SW_MODE);
    }
}

static inline void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

static inline void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    mmio_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

static inline void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dws, int enable) {
    if ((enable == 0x0)) {
        /* regmap write hook */
    } else {
        /* regmap write hook */
    }
}

static inline void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dws, uint32_t cs) {
    if ((cs < 0x2)) {
        /* regmap update hook */
    }
}

#endif /* DW_APB_SSI_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>

int main(void) {
    struct dw_apb_ssi_priv dev = {0};
    dev.base = 0x10000000;
    
    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_check_status(&dev, 1, 0);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_update_config(&dev, 1000, 2);
    dw_spi_transfer_one(&dev, 4);
    dw_spi_handle_err(&dev);
    dw_spi_target_abort(&dev);
    dw_spi_exec_mem_op(&dev, 0, 0, 0);
    dw_spi_add_controller(&dev);
    dw_spi_remove_controller(&dev);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 1, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);
    
    return 0;
}
#endif