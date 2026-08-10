#include "spi-dw-core_harness.h"


/* Helper stubs */
uint32_t spi_get_chipselect(void *spi, int idx) { return 0; }
int spi_controller_is_target(void *ctlr) { return 0; }
int dw_spi_ip_is(struct spi_dw_core_priv *dws, const char *id) { return 1; }

/* Module functions */
void dw_spi_set_cs(struct spi_dw_core_priv *dev, void *spi, int cs_high, int enable) {
    uintptr_t base = dev->base;
    if (cs_high == enable) {
        uint32_t value = (0x1 << spi_get_chipselect(spi, 0));
        harness_write32(value, base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        uint32_t value = 0x0;
        harness_write32(value, base + DW_SPI_SER);
    }
}

void dw_writer(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t tx_room;
    tx_room = harness_read32(base + DW_SPI_TXFLR);
}

void dw_reader(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t offset = 0;
    uint32_t r4;
    r4 = harness_read32(dev->regs + offset);
}

void dw_spi_check_status(struct spi_dw_core_priv *dev, int raw) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    if (raw) {
        irq_status = harness_read32(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = harness_read32(base + DW_SPI_ISR);
    }
}

void dw_spi_transfer_handler(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    uint32_t r8;
    irq_status = harness_read32(base + DW_SPI_ISR);
    if ((dev->rx_len == 0x0) == 0x0) {
        r8 = harness_read32(base + DW_SPI_RXFTLR);
        if (dev->rx_len <= r8) {
            uint32_t value = (dev->rx_len - 0x1);
            harness_write32(value, base + DW_SPI_RXFTLR);
        }
    }
}

void dw_spi_irq(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t irq_status;
    irq_status = harness_read32(base + DW_SPI_ISR);
}

void dw_spi_update_config(struct spi_dw_core_priv *dev, void *chip_cfg) {
    uintptr_t base = dev->base;
    struct { uint32_t cr0; uint32_t tmode; uint32_t ndf; uint32_t rx_sample_dly; } *chip = chip_cfg;
    struct { uint32_t tmode; uint32_t ndf; } *cfg = chip_cfg;
    
    harness_write32(chip->cr0, base + DW_SPI_CTRLR0);
    
    if ((cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO) {
        uint32_t value = cfg->ndf ? (cfg->ndf - 1) : 0;
        harness_write32(value, base + DW_SPI_CTRLR1);
    }
    if (dev->cur_rx_sample_dly != chip->rx_sample_dly) {
        harness_write32(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

void dw_spi_transfer_one(struct spi_dw_core_priv *dev, uint32_t level) {
    uintptr_t base = dev->base;
    harness_write32(level, base + DW_SPI_TXFTLR);
    harness_write32((level - 0x1), base + DW_SPI_RXFTLR);
}

void dw_spi_exec_mem_op(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t len = 1;
    uint32_t entries;
    uint32_t nents;
    uint32_t sts;
    int ret = 0;

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
    }
}

void dw_spi_add_controller(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r25;
    uint32_t r27;
    uint32_t cr0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;

    if (1) { /* dws */
        if (dev->ver == 0x0) {
            dev->ver = harness_read32(base + DW_SPI_VERSION);
        }
        if (spi_controller_is_target(NULL) == 0x0) {
            if (dev->num_cs == 0x0) {
                harness_write32(0xffff, base + DW_SPI_SER);
                ser = harness_read32(base + DW_SPI_SER);
                harness_write32(0x0, base + DW_SPI_SER);
            }
        }
        if (dev->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                harness_write32(fifo, base + DW_SPI_TXFTLR);
                r25 = harness_read32(base + DW_SPI_TXFTLR);
                if (r25 != fifo) break;
            }
            harness_write32(0x0, base + DW_SPI_TXFTLR);
        }
        if (dw_spi_ip_is(dev, "PSSI")) {
            r27 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = harness_read32(base + DW_SPI_CTRLR0);
            harness_write32(tmp, base + DW_SPI_CTRLR0);
        }
        if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
            harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
}

void dw_spi_resume_controller(struct spi_dw_core_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t ser;
    uint32_t r37;
    uint32_t r39;
    uint32_t cr0;
    uint32_t tmp = 0;
    uint32_t fifo = 0;

    if (dev->ver == 0x0) {
        dev->ver = harness_read32(base + DW_SPI_VERSION);
    }
    if (spi_controller_is_target(NULL) == 0x0) {
        if (dev->num_cs == 0x0) {
            harness_write32(0xffff, base + DW_SPI_SER);
            ser = harness_read32(base + DW_SPI_SER);
            harness_write32(0x0, base + DW_SPI_SER);
        }
    }
    if (dev->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            harness_write32(fifo, base + DW_SPI_TXFTLR);
            r37 = harness_read32(base + DW_SPI_TXFTLR);
            if (r37 != fifo) break;
        }
        harness_write32(0x0, base + DW_SPI_TXFTLR);
    }
    if (dw_spi_ip_is(dev, "PSSI")) {
        r39 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = harness_read32(base + DW_SPI_CTRLR0);
        harness_write32(tmp, base + DW_SPI_CTRLR0);
    }
    if (dev->caps & DW_SPI_CAP_CS_OVERRIDE) {
        harness_write32(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

int main(void) {
    struct spi_dw_core_priv dev = {0};
    dev.base = 0x10000000;
    dev.regs = dev.base;
    dev.caps = DW_SPI_CAP_CS_OVERRIDE;
    
    dw_spi_set_cs(&dev, NULL, 1, 1);
    dw_writer(&dev);
    dw_reader(&dev);
    dw_spi_check_status(&dev, 1);
    dw_spi_transfer_handler(&dev);
    dw_spi_irq(&dev);
    
    uint32_t chip_cfg[4] = {0xDEADBEEF, DW_SPI_CTRLR0_TMOD_RO, 10, 5};
    dw_spi_update_config(&dev, chip_cfg);
    
    dw_spi_transfer_one(&dev, 32);
    dw_spi_exec_mem_op(&dev);
    dw_spi_add_controller(&dev);
    dw_spi_resume_controller(&dev);
    
    return 0;
}