#include "dw_apb_ssi_linux.h"


static int dw_apb_ssi_open(struct inode *inode, struct file *file)
{
    struct driver_priv *priv = container_of(file->private_data, struct driver_priv, misc);
    file->private_data = priv;
    return 0;
}

static ssize_t dw_apb_ssi_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
    struct driver_priv *priv = file->private_data;
    void __iomem *base = priv->base;
    u32 val;

    if (*ppos & 3 || count < 4)
        return -EINVAL;

    val = readl(base + *ppos);
    if (copy_to_user(buf, &val, 4))
        return -EFAULT;
    *ppos += 4;
    return 4;
}

static ssize_t dw_apb_ssi_write(struct file *file, const char __user *buf, size_t count, loff_t *ppos)
{
    struct driver_priv *priv = file->private_data;
    void __iomem *base = priv->base;
    u32 val;

    if (*ppos & 3 || count < 4)
        return -EINVAL;

    if (copy_from_user(&val, buf, 4))
        return -EFAULT;
    writel(val, base + *ppos);
    *ppos += 4;
    return 4;
}

static const struct file_operations dw_apb_ssi_fops = {
    .owner = THIS_MODULE,
    .open = dw_apb_ssi_open,
    .read = dw_apb_ssi_read,
    .write = dw_apb_ssi_write,
};

static void dw_spi_set_cs(struct driver_priv *priv, bool enable, bool cs_high, u32 chip_select)
{
    void __iomem *base = priv->base;
    u32 new_mask = 0;
    u32 cs = chip_select;

    if (cs_high == enable) {
        writel((0x1 << cs), base + DW_SPI_SER);
    } else {
        // else branch is empty
    }
    if ((cs_high == enable) == 0x0) {
        writel(0x0, base + DW_SPI_SER);
    } else {
        // else branch is empty
    }
}

static void dw_spi_check_status(struct driver_priv *priv, bool raw, int ret)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r6;
    u32 r8;
    u32 new_mask = 0;

    if (raw) {
        irq_status = readl(base + DW_SPI_RISR);
    } else {
        // else branch is empty
    }
    if (raw == 0x0) {
        irq_status = readl(base + DW_SPI_ISR);
    } else {
        // else branch is empty
    }
    if (ret) {
        writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
        r6 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r8 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
    } else {
        // else branch is empty
    }
}

static void dw_spi_transfer_handler(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r12;
    u32 rxw;
    u32 r14;
    u32 r16;
    u32 tx_room;
    u32 r20;
    u32 new_mask = 0;
    int max = 4;

    irq_status = readl(base + DW_SPI_ISR);
    r12 = readl(base + 0x0);
    while (max--) {
        rxw = readl(base + DW_SPI_DR);
    }
    if (priv->rx_len == 0x0) {
        r14 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    } else {
        // else branch is empty
    }
    if ((priv->rx_len == 0x0) == 0x0) {
        r16 = readl(base + DW_SPI_RXFTLR);
        if (priv->rx_len <= r16) {
            writel((priv->rx_len - 0x1), base + DW_SPI_RXFTLR);
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = readl(base + DW_SPI_TXFLR);
        max = 4;
        while (max--) {
            u32 val = 0;
            if (priv->tx && priv->n_bytes != 1 && priv->n_bytes != 2) {
                val = *(u32 *)(priv->tx);
            } else if (priv->tx && priv->n_bytes != 1 && priv->n_bytes == 2) {
                val = *(u16 *)(priv->tx);
            } else if (priv->tx && priv->n_bytes == 1) {
                val = *(u8 *)(priv->tx);
            }
            writel(val, base + DW_SPI_DR);
        }
        if (priv->tx_len == 0x0) {
            r20 = readl(base + DW_SPI_IMR);
            writel(new_mask, base + DW_SPI_IMR);
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
}

static void dw_spi_irq(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r23;
    u32 new_mask = 0;

    irq_status = readl(base + DW_SPI_ISR);
    if (0) { // ctlr->cur_msg == 0x0
        r23 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    } else {
        // else branch is empty
    }
}

static void dw_spi_update_config(struct driver_priv *priv, u32 cr0, u32 tmode, u32 ndf, u32 speed_hz, u32 rx_sample_dly)
{
    void __iomem *base = priv->base;
    struct dw_spi_chip_data chip = { .cr0 = cr0, .rx_sample_dly = rx_sample_dly };
    struct cfg { u32 tmode; u32 ndf; } cfg = { .tmode = tmode, .ndf = ndf };
    u32 clk_div = 100;

    writel(chip.cr0, base + DW_SPI_CTRLR0);
    if ((cfg.tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
        writel((cfg.ndf ? (cfg.ndf - 1) : 0), base + DW_SPI_CTRLR1);
    } else {
        // else branch is empty
    }
    if (priv->current_freq != speed_hz) {
        writel(clk_div, base + DW_SPI_BAUDR);
    } else {
        // else branch is empty
    }
    if (priv->cur_rx_sample_dly != chip.rx_sample_dly) {
        writel(chip.rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    } else {
        // else branch is empty
    }
}

static void dw_spi_transfer_one(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r30;
    u32 new_mask = 0;
    u32 tx_room;
    u32 r35;
    u32 rxw;
    u32 r39;
    u32 level = 32;
    int max = 4;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r30 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
    if (priv->dma_mapped == 0x0) {
        if (priv->irq == IRQ_NOTCONNECTED) {
            while (priv->rx_len) {
                tx_room = readl(base + DW_SPI_TXFLR);
                max = 4;
                while (max--) {
                    u32 val = 0;
                    if (priv->tx && priv->n_bytes != 1 && priv->n_bytes != 2) {
                        val = *(u32 *)(priv->tx);
                    } else if (priv->tx && priv->n_bytes != 1 && priv->n_bytes == 2) {
                        val = *(u16 *)(priv->tx);
                    } else if (priv->tx && priv->n_bytes == 1) {
                        val = *(u8 *)(priv->tx);
                    }
                    writel(val, base + DW_SPI_DR);
                }
                r35 = readl(base + 0x0);
                max = 4;
                while (max--) {
                    rxw = readl(base + DW_SPI_DR);
                }
            }
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
    writel(level, base + DW_SPI_TXFTLR);
    writel((level - 0x1), base + DW_SPI_RXFTLR);
    r39 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
}

static void dw_spi_handle_err(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r42;
    u32 new_mask = 0;
    u32 r44;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r42 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r44 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static void dw_spi_target_abort(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r48;
    u32 new_mask = 0;
    u32 r50;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r48 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r50 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static void dw_spi_exec_mem_op(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r54;
    u32 new_mask = 0;
    u32 entries;
    u32 sts;
    u32 r62;
    u32 nents;
    u32 __return_read_0;
    int len = 4;
    int room = 0;
    u8 buf[4] = {0};
    u8 *pbuf = buf;
    int retry = 5;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r54 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
    while (len--) {
        writel(*pbuf++, base + DW_SPI_DR);
    }
    while (len) {
        entries = readl(base + DW_SPI_TXFLR);
        while ((room = len) > 0) {
            writel(*pbuf++, base + DW_SPI_DR);
            len--;
        }
    }
    while (len) {
        entries = readl(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = readl(base + DW_SPI_RISR);
        } else {
            // else branch is empty
        }
        while ((room = len) > 0) {
            r62 = readl(base + DW_SPI_DR);
            len--;
        }
    }
    if (0 == 0x0) {
        nents = readl(base + DW_SPI_TXFLR);
        while ((1 && retry--)) {
            __return_read_0 = readl(base + DW_SPI_SR);
        }
    } else {
        // else branch is empty
    }
    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
}

static void dw_spi_add_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r68;
    u32 new_mask = 0;
    u32 r70;
    u32 ser;
    u32 r78;
    u32 r80;
    u32 cr0;
    u32 tmp = 0;
    int fifo = 0;

    if (1) { // dws
        writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
        r68 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r70 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
        if (priv->ver == 0x0) {
            priv->ver = readl(base + DW_SPI_VERSION);
        } else {
            // else branch is empty
        }
        if (1 == 0x0) { // spi_controller_is_target(dws->ctlr) == 0x0
            if (priv->num_cs == 0x0) {
                writel(0xffff, base + DW_SPI_SER);
                ser = readl(base + DW_SPI_SER);
                writel(0x0, base + DW_SPI_SER);
            } else {
                // else branch is empty
            }
        } else {
            // else branch is empty
        }
        if (priv->fifo_len == 0x0) {
            for (; fifo < 0x100; fifo++) {
                writel(fifo, base + DW_SPI_TXFTLR);
                r78 = readl(base + DW_SPI_TXFTLR);
            }
            writel(0x0, base + DW_SPI_TXFTLR);
        } else {
            // else branch is empty
        }
        if (1) { // dw_spi_ip_is(dws, PSSI)
            r80 = readl(base + DW_SPI_CTRLR0);
            writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
            writel(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = readl(base + DW_SPI_CTRLR0);
            writel(tmp, base + DW_SPI_CTRLR0);
            writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
        } else {
            // else branch is empty
        }
        if (priv->caps & DW_SPI_CAP_CS_OVERRIDE) {
            writel(0xf, base + DW_SPI_CS_OVERRIDE);
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
    if (0x0) {
        if (1) {
            if (1) {
                if (1) { // dws
                    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
                } else {
                    // else branch is empty
                }
            } else {
                // else branch is empty
            }
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
}

static void dw_spi_remove_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_suspend_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_resume_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r93;
    u32 new_mask = 0;
    u32 r95;
    u32 ser;
    u32 r103;
    u32 r105;
    u32 cr0;
    u32 tmp = 0;
    int fifo = 0;

    writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
    r93 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r95 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
    if (priv->ver == 0x0) {
        priv->ver = readl(base + DW_SPI_VERSION);
    } else {
        // else branch is empty
    }
    if (1 == 0x0) {
        if (priv->num_cs == 0x0) {
            writel(0xffff, base + DW_SPI_SER);
            ser = readl(base + DW_SPI_SER);
            writel(0x0, base + DW_SPI_SER);
        } else {
            // else branch is empty
        }
    } else {
        // else branch is empty
    }
    if (priv->fifo_len == 0x0) {
        for (; fifo < 0x100; fifo++) {
            writel(fifo, base + DW_SPI_TXFTLR);
            r103 = readl(base + DW_SPI_TXFTLR);
        }
        writel(0x0, base + DW_SPI_TXFTLR);
    } else {
        // else branch is empty
    }
    if (1) {
        r105 = readl(base + DW_SPI_CTRLR0);
        writel((0 ? 1 : 0), base + DW_SPI_SSIENR);
        writel(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = readl(base + DW_SPI_CTRLR0);
        writel(tmp, base + DW_SPI_CTRLR0);
        writel((1 ? 1 : 0), base + DW_SPI_SSIENR);
    } else {
        // else branch is empty
    }
    if (priv->caps & DW_SPI_CAP_CS_OVERRIDE) {
        writel(0xf, base + DW_SPI_CS_OVERRIDE);
    } else {
        // else branch is empty
    }
}

static void dw_spi_mscc_set_cs(struct driver_priv *priv, u32 cs, u32 sw_mode)
{
    void __iomem *base = priv->base;

    if (cs < 0x4) {
        writel((cs < 4 ? 8192 : sw_mode), base + MSCC_SPI_MST_SW_MODE);
    } else {
        // else branch is empty
    }
}

static void dw_spi_mscc_ocelot_init(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    static struct regmap *dwsmscc_syscon = NULL;

    writel(0x0, base + MSCC_SPI_MST_SW_MODE);
    regmap_update_bits(dwsmscc_syscon, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL, 0, 0);
}

static void dw_spi_mscc_jaguar2_init(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    static struct regmap *dwsmscc_syscon = NULL;

    writel(0x0, base + MSCC_SPI_MST_SW_MODE);
    regmap_update_bits(dwsmscc_syscon, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL, 0, 0);
}

static void dw_spi_sparx5_set_cs(struct driver_priv *priv, bool enable)
{
    static struct regmap *dwsmscc_syscon = NULL;

    if (enable == 0x0) {
        regmap_write(dwsmscc_syscon, SPARX5_FORCE_ENA, 0);
        regmap_write(dwsmscc_syscon, SPARX5_FORCE_VAL, 0);
    } else {
        // else branch is empty
    }
    if ((enable == 0x0) == 0x0) {
        regmap_write(dwsmscc_syscon, SPARX5_FORCE_VAL, 0);
        regmap_write(dwsmscc_syscon, SPARX5_FORCE_ENA, 0);
    } else {
        // else branch is empty
    }
}

static void dw_spi_elba_set_cs(struct driver_priv *priv, u32 cs)
{
    static struct regmap *dwsmmio_priv = NULL;

    if (cs < 0x2) {
        regmap_update_bits(dwsmmio_priv, ELBA_SPICS_REG, 0, 0);
    } else {
        // else branch is empty
    }
}

static int dw_apb_ssi_probe(struct platform_device *pdev)
{
    struct driver_priv *priv;
    int ret;

    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv)
        return -ENOMEM;

    priv->dev = &pdev->dev;

    priv->base = devm_platform_ioremap_resource(pdev, 0);
    if (IS_ERR(priv->base))
        return PTR_ERR(priv->base);

    RH_SET_BASE(priv->base);

    RH_TRACE_FN("dw_spi_set_cs");
    dw_spi_set_cs(priv, true, true, 0);
    RH_TRACE_FN("dw_spi_check_status");
    dw_spi_check_status(priv, true, 0);
    RH_TRACE_FN("dw_spi_transfer_handler");
    dw_spi_transfer_handler(priv);
    RH_TRACE_FN("dw_spi_irq");
    dw_spi_irq(priv);
    RH_TRACE_FN("dw_spi_update_config");
    dw_spi_update_config(priv, 0, 0, 0, 100, 0);
    RH_TRACE_FN("dw_spi_transfer_one");
    dw_spi_transfer_one(priv);
    RH_TRACE_FN("dw_spi_handle_err");
    dw_spi_handle_err(priv);
    RH_TRACE_FN("dw_spi_target_abort");
    dw_spi_target_abort(priv);
    RH_TRACE_FN("dw_spi_exec_mem_op");
    dw_spi_exec_mem_op(priv);
    RH_TRACE_FN("dw_spi_add_controller");
    dw_spi_add_controller(priv);
    RH_TRACE_FN("dw_spi_remove_controller");
    dw_spi_remove_controller(priv);
    RH_TRACE_FN("dw_spi_suspend_controller");
    dw_spi_suspend_controller(priv);
    RH_TRACE_FN("dw_spi_resume_controller");
    dw_spi_resume_controller(priv);
    RH_TRACE_FN("dw_spi_mscc_set_cs");
    dw_spi_mscc_set_cs(priv, 0, 0);
    RH_TRACE_FN("dw_spi_mscc_ocelot_init");
    dw_spi_mscc_ocelot_init(priv);
    RH_TRACE_FN("dw_spi_mscc_jaguar2_init");
    dw_spi_mscc_jaguar2_init(priv);
    RH_TRACE_FN("dw_spi_sparx5_set_cs");
    dw_spi_sparx5_set_cs(priv, true);
    RH_TRACE_FN("dw_spi_elba_set_cs");
    dw_spi_elba_set_cs(priv, 0);

    priv->misc.minor = MISC_DYNAMIC_MINOR;
    priv->misc.name = KBUILD_MODNAME;
    priv->misc.fops = &dw_apb_ssi_fops;

    ret = misc_register(&priv->misc);
    if (ret) {
        dev_err(&pdev->dev, "Failed to register misc device\n");
        return ret;
    }

    platform_set_drvdata(pdev, priv);

    return 0;
}

static void dw_apb_ssi_remove(struct platform_device *pdev)
{
    struct driver_priv *priv = platform_get_drvdata(pdev);

    RH_TRACE_FN("dw_spi_remove_controller");
    dw_spi_remove_controller(priv);
    RH_TRACE_FN("dw_spi_suspend_controller");
    dw_spi_suspend_controller(priv);

    misc_deregister(&priv->misc);
}

static const struct of_device_id dw_apb_ssi_match[] = {
    { .compatible = "snps,dw-apb-ssi", },
    { /* Sentinel */ }
};
MODULE_DEVICE_TABLE(of, dw_apb_ssi_match);

static struct platform_driver dw_apb_ssi_driver = {
    .probe = dw_apb_ssi_probe,
    .remove_new = dw_apb_ssi_remove,
    .driver = {
        .name = "dw-apb-ssi",
        .of_match_table = dw_apb_ssi_match,
    },
};

module_platform_driver(dw_apb_ssi_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Synopsys DesignWare APB SSI Driver");