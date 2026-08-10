#include "dw-apb-ssi_harness.h"


/* Module functions */
void dw_spi_set_cs(struct dw_apb_ssi_priv *dws, int cs_high, int enable) {
    uintptr_t base = dws->base;
    if (cs_high == enable) {
        uint32_t offset = (1 << dws->chip_select[0]);
        harness_write32(DW_SPI_SER, base + offset);
    }
    if ((cs_high == enable) == 0x0) {
        harness_write32(DW_SPI_SER, base + 0x0);
    }
}

void dw_spi_check_status(struct dw_apb_ssi_priv *dws, int raw, int ret) {
    uintptr_t base = dws->base;
    uint32_t irq_status;
    uint32_t r6, r8;
    uint32_t new_mask = 0;

    if (raw) {
        irq_status = harness_read32(base + DW_SPI_RISR);
    }
    if ((raw == 0x0)) {
        irq_status = harness_read32(base + DW_SPI_ISR);
    }
    if (ret) {
        harness_write32(DW_SPI_SSIENR, base + 0x0);
        r6 = harness_read32(base + DW_SPI_IMR);
        harness_write32(DW_SPI_IMR, base + new_mask);
        r8 = harness_read32(base + DW_SPI_ICR);
        harness_write32(DW_SPI_SER, base + 0x0);
        harness_write32(DW_SPI_SSIENR, base + 0x1);
    }
}

void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
    uint32_t r12, r13, r14, r15, r17, r22;
    uint32_t tx_room;
    uint32_t new_mask = 0;

    r12 = harness_read32(base + 0x0);

    for (int i = 0; i < 1; i++) {
        if (dws->reg_io_width == 0x2) {
            r13 = harness_read16(base + 0x0);
        }
        if (dws->reg_io_width == 0x4) {
            r14 = harness_read32(base + 0x0);
        }
    }

    if (dws->rx_len == 0x0) {
        r15 = harness_read32(base + DW_SPI_IMR);
        harness_write32(DW_SPI_IMR, base + new_mask);
    }
    if ((dws->rx_len == 0x0) == 0x0) {
        r17 = harness_read32(base + DW_SPI_RXFTLR);
        if (dws->rx_len <= r17) {
            uint32_t offset = dws->rx_len - 1;
            harness_write32(DW_SPI_RXFTLR, base + offset);
        }
    }

    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = harness_read32(base + DW_SPI_TXFLR);
        for (int i = 0; i < 1; i++) {
            if (dws->reg_io_width == 0x2) {
                harness_write16(0, base + 0x0);
            }
            if (dws->reg_io_width == 0x4) {
                harness_write32(0, base + 0x0);
            }
        }
        if (dws->tx_len == 0x0) {
            r22 = harness_read32(base + DW_SPI_IMR);
            harness_write32(DW_SPI_IMR, base + new_mask);
        }
    }
}

void dw_spi_irq(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t irq_status = harness_read32(base + DW_SPI_ISR);
    uint32_t r25;
    uint32_t new_mask = 0;

    if (dws->cur_msg == 0x0) {
        r25 = harness_read32(base + DW_SPI_IMR);
        harness_write32(DW_SPI_IMR, base + new_mask);
    }
}

void dw_spi_update_config(struct dw_apb_ssi_priv *dws, uint32_t cr0, uint32_t tmode, uint32_t ndf, uint32_t speed_hz, uint32_t rx_sample_dly) {
    uintptr_t base = dws->base;
    uint32_t clk_div = 0;

    harness_write32(DW_SPI_CTRLR0, base + cr0);

    if (((tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
        uint32_t offset = ndf ? (ndf - 1) : 0;
        harness_write32(DW_SPI_CTRLR1, base + offset);
    }
    if (dws->current_freq != speed_hz) {
        harness_write32(DW_SPI_BAUDR, base + clk_div);
    }
    if (dws->cur_rx_sample_dly != rx_sample_dly) {
        harness_write32(DW_SPI_RX_SAMPLE_DLY, base + rx_sample_dly);
    }
}

void dw_spi_transfer_one(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r32, r38, r39, r40, r43;
    uint32_t tx_room;
    uint32_t new_mask = 0;
    uint32_t level = 0;

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    r32 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
    harness_write32(DW_SPI_SSIENR, base + 0x1);

    if (dws->dma_mapped == 0x0) {
        if (dws->irq == IRQ_NOTCONNECTED) {
            while (dws->rx_len) {
                tx_room = harness_read32(base + DW_SPI_TXFLR);
                for (int i = 0; i < 1; i++) {
                    if (dws->reg_io_width == 0x2) {
                        harness_write16(0, base + 0x0);
                    }
                    if (dws->reg_io_width == 0x4) {
                        harness_write32(0, base + 0x0);
                    }
                }
                r38 = harness_read32(base + 0x0);
                for (int i = 0; i < 1; i++) {
                    if (dws->reg_io_width == 0x2) {
                        r39 = harness_read16(base + 0x0);
                    }
                    if (dws->reg_io_width == 0x4) {
                        r40 = harness_read32(base + 0x0);
                    }
                }
            }
        }
    }

    harness_write32(DW_SPI_TXFTLR, base + level);
    harness_write32(DW_SPI_RXFTLR, base + (level - 1));
    r43 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
}

void dw_spi_handle_err(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r46, r48;
    uint32_t new_mask = 0;

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    r46 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
    r48 = harness_read32(base + DW_SPI_ICR);
    harness_write32(DW_SPI_SER, base + 0x0);
    harness_write32(DW_SPI_SSIENR, base + 0x1);
}

void dw_spi_target_abort(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r52, r54;
    uint32_t new_mask = 0;

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    r52 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
    r54 = harness_read32(base + DW_SPI_ICR);
    harness_write32(DW_SPI_SER, base + 0x0);
    harness_write32(DW_SPI_SSIENR, base + 0x1);
}

void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r58, r68, r69;
    uint32_t entries, nents, sts;
    uint32_t new_mask = 0;
    uint32_t len = 1;

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    r58 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
    harness_write32(DW_SPI_SSIENR, base + 0x1);

    while (len--) {
        if (dws->reg_io_width == 0x2) {
            harness_write16(0, base + 0x0);
        }
        if (dws->reg_io_width == 0x4) {
            harness_write32(0, base + 0x0);
        }
    }

    while (len) {
        entries = harness_read32(base + DW_SPI_TXFLR);
        while (len--) {
            if (dws->reg_io_width == 0x2) {
                harness_write16(0, base + 0x0);
            }
            if (dws->reg_io_width == 0x4) {
                harness_write32(0, base + 0x0);
            }
        }
    }

    while (len) {
        entries = harness_read32(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = harness_read32(base + DW_SPI_RISR);
        }
        while (len--) {
            if (dws->reg_io_width == 0x2) {
                r68 = harness_read16(base + 0x0);
            }
            if (dws->reg_io_width == 0x4) {
                r69 = harness_read32(base + 0x0);
            }
        }
    }

    if (0 == 0x0) {
        nents = harness_read32(base + DW_SPI_TXFLR);
        uint32_t retry = 1;
        while (retry--) {
            uint32_t __return_read_0 = harness_read32(base + DW_SPI_SR);
        }
    }

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    harness_write32(DW_SPI_SSIENR, base + 0x1);
}

void dw_spi_add_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r75, r77, r85, r87, r90;
    uint32_t ser, cr0;
    uint32_t new_mask = 0;
    uint32_t tmp = 0;

    if (1) {
        harness_write32(DW_SPI_SSIENR, base + 0x0);
        r75 = harness_read32(base + DW_SPI_IMR);
        harness_write32(DW_SPI_IMR, base + new_mask);
        r77 = harness_read32(base + DW_SPI_ICR);
        harness_write32(DW_SPI_SER, base + 0x0);
        harness_write32(DW_SPI_SSIENR, base + 0x1);

        if (dws->ver == 0x0) {
            dws->ver = harness_read32(base + DW_SPI_VERSION);
        }
        if (1) {
            if (dws->num_cs == 0x0) {
                harness_write32(DW_SPI_SER, base + 0xffff);
                ser = harness_read32(base + DW_SPI_SER);
                harness_write32(DW_SPI_SER, base + 0x0);
            }
        }
        if (dws->fifo_len == 0x0) {
            for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
                harness_write32(DW_SPI_TXFTLR, base + fifo);
                r85 = harness_read32(base + DW_SPI_TXFTLR);
            }
            harness_write32(DW_SPI_TXFTLR, base + 0x0);
        }
        if (1) { /* dw_spi_ip_is(dws, PSSI) */
            r87 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(DW_SPI_SSIENR, base + 0x0);
            harness_write32(DW_SPI_CTRLR0, base + 0xffffffff);
            cr0 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(DW_SPI_CTRLR0, base + tmp);
            harness_write32(DW_SPI_SSIENR, base + 0x1);
        }
        if (dws->caps & DW_SPI_CAP_CS_OVERRIDE) {
            harness_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
        }
    }
    if (0x0) {
        if (1) {
            if (1) {
                if (1) {
                    harness_write32(DW_SPI_SSIENR, base + 0x0);
                }
            }
        }
    }
}

void dw_spi_remove_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    harness_write32(DW_SPI_SSIENR, base + 0x0);
    harness_write32(DW_SPI_BAUDR, base + 0x0);
}

void dw_spi_suspend_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    harness_write32(DW_SPI_SSIENR, base + 0x0);
    harness_write32(DW_SPI_BAUDR, base + 0x0);
}

void dw_spi_resume_controller(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    uint32_t r100, r102, r110, r112, r115;
    uint32_t ser, cr0;
    uint32_t new_mask = 0;
    uint32_t tmp = 0;

    harness_write32(DW_SPI_SSIENR, base + 0x0);
    r100 = harness_read32(base + DW_SPI_IMR);
    harness_write32(DW_SPI_IMR, base + new_mask);
    r102 = harness_read32(base + DW_SPI_ICR);
    harness_write32(DW_SPI_SER, base + 0x0);
    harness_write32(DW_SPI_SSIENR, base + 0x1);

    if (dws->ver == 0x0) {
        dws->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if (1) {
        if (dws->num_cs == 0x0) {
            harness_write32(DW_SPI_SER, base + 0xffff);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(DW_SPI_SER, base + 0x0);
        }
    }
    if (dws->fifo_len == 0x0) {
        for (uint32_t fifo = 0; fifo < 0x100; fifo++) {
            harness_write32(DW_SPI_TXFTLR, base + fifo);
            r110 = harness_read32(base + DW_SPI_TXFTLR);
        }
        harness_write32(DW_SPI_TXFTLR, base + 0x0);
    }
    if (1) { /* dw_spi_ip_is(dws, PSSI) */
        r112 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(DW_SPI_SSIENR, base + 0x0);
        harness_write32(DW_SPI_CTRLR0, base + 0xffffffff);
        cr0 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(DW_SPI_CTRLR0, base + tmp);
        harness_write32(DW_SPI_SSIENR, base + 0x1);
    }
    if (dws->caps & DW_SPI_CAP_CS_OVERRIDE) {
        harness_write32(DW_SPI_CS_OVERRIDE, base + 0xf);
    }
}

void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *dws, uint32_t cs, uint32_t sw_mode) {
    uintptr_t base = dws->base;
    if (cs < 0x4) {
        uint32_t val = (cs < 4) ? 8192 : sw_mode;
        harness_write32(val, base + MSCC_SPI_MST_SW_MODE);
    }
}

void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *dws) {
    uintptr_t base = dws->base;
    harness_write32(0x0, base + MSCC_SPI_MST_SW_MODE);
}

void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *dws, int enable) {
    uintptr_t base = dws->base;
    if (enable == 0x0) {}
    if ((enable == 0x0) == 0x0) {}
}

void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *dws, uint32_t cs) {
    uintptr_t base = dws->base;
    if (cs < 0x2) {}
}

int main(void) {
    struct dw_apb_ssi_priv dev;
    dev.base = 0x10000000;
    dev.reg_io_width = 4;
    dev.rx_len = 1;
    dev.tx_len = 1;
    dev.current_freq = 1000000;
    dev.cur_rx_sample_dly = 0;
    dev.dma_mapped = 0;
    dev.irq = IRQ_NOTCONNECTED;
    dev.ver = 0;
    dev.num_cs = 0;
    dev.fifo_len = 0;
    dev.caps = DW_SPI_CAP_CS_OVERRIDE;
    dev.chip_select[0] = 0;
    dev.cur_msg = 1;

    dw_spi_set_cs(&dev, 1, 1);
    dw_spi_check_status(&dev, 1, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    dw_spi_update_config(&dev, 0, DW_SPI_CTRLR0_TMOD_RO, 1, 500000, 0);
    dw_spi_transfer_one(&dev);
    dw_spi_handle_err(&dev);
    dw_spi_target_abort(&dev);
    dw_spi_exec_mem_op(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_remove_controller(&dev);
    dw_spi_suspend_controller(&dev);
    dw_spi_resume_controller(&dev);
    dw_spi_mscc_set_cs(&dev, 0, 0);
    dw_spi_mscc_ocelot_init(&dev);
    dw_spi_mscc_jaguar2_init(&dev);
    dw_spi_sparx5_set_cs(&dev, 0);
    dw_spi_elba_set_cs(&dev, 0);

    return 0;
}