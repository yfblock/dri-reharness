#include "dw-apb-ssi_linux.h"


static int dw_apb_ssi_open(struct inode *inode, struct file *file)
{
    struct miscdevice *misc = file->private_data;
    struct driver_priv *priv = container_of(misc, struct driver_priv, misc);
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

static void dw_spi_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs_high = priv->cs_high;
    u32 enable = priv->enable;

    if (cs_high == enable) {
        writel((0x1 << priv->chip_select[0]), base + DW_SPI_SER);
    }
    if ((cs_high == enable) == 0x0) {
        writel(0x0, base + DW_SPI_SER);
    }
}

static void dw_spi_check_status(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r6, r8;
    u32 raw = priv->raw;
    u32 ret = priv->ret;
    u32 new_mask = priv->new_mask;

    if (raw) {
        irq_status = readl(base + DW_SPI_RISR);
    }
    if (raw == 0x0) {
        irq_status = readl(base + DW_SPI_ISR);
    }
    if (ret) {
        writel(0, base + DW_SPI_SSIENR);
        r6 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r8 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel(1, base + DW_SPI_SSIENR);
    }
}

static void dw_spi_transfer_handler(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r12, r13, r14, r15, r17, r19, r22;
    u32 new_mask = priv->new_mask;

    irq_status = readl(base + DW_SPI_ISR);
    r12 = readl(base + 0x0);

    while (priv->rx_len--) {
        if (priv->reg_io_width == 0x2) {
            r13 = readw(base + 0x0);
        }
        if (priv->reg_io_width == 0x4) {
            r14 = readl(base + 0x0);
        }
    }

    if (priv->rx_len == 0x0) {
        r15 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    }
    if ((priv->rx_len == 0x0) == 0x0) {
        r17 = readl(base + DW_SPI_RXFTLR);
        if (priv->rx_len <= r17) {
            writel((priv->rx_len - 0x1), base + DW_SPI_RXFTLR);
        }
    }
    if (irq_status & DW_SPI_INT_TXEI) {
        r19 = readl(base + DW_SPI_TXFLR);
        while (priv->tx_len--) {
            if (priv->reg_io_width == 0x2) {
                writew(0, base + 0x0);
            }
            if (priv->reg_io_width == 0x4) {
                writel(0, base + 0x0);
            }
        }
        if (priv->tx_len == 0x0) {
            r22 = readl(base + DW_SPI_IMR);
            writel(new_mask, base + DW_SPI_IMR);
        }
    }
}

static void dw_spi_irq(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r25;
    u32 new_mask = priv->new_mask;

    irq_status = readl(base + DW_SPI_ISR);
    if (priv->cur_msg == 0x0) {
        r25 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    }
}

static void dw_spi_update_config(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cr0 = priv->cr0_val;
    u32 tmode = priv->cfg_tmode;
    u32 ndf = priv->cfg_ndf;
    u32 speed_hz = priv->speed_hz;
    u32 clk_div = priv->clk_div;
    u32 chip_rx_sample_dly = priv->chip_rx_sample_dly;

    writel(cr0, base + DW_SPI_CTRLR0);
    if (((tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) & DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
        writel(ndf ? (ndf - 1) : 0, base + DW_SPI_CTRLR1);
    }
    if (priv->current_freq != speed_hz) {
        writel(clk_div, base + DW_SPI_BAUDR);
    }
    if (priv->cur_rx_sample_dly != chip_rx_sample_dly) {
        writel(chip_rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    }
}

static void dw_spi_transfer_one(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r32, r38, r39, r40, r43;
    u32 tx_room;
    u32 level = priv->level;
    u32 new_mask = priv->new_mask;

    writel(0, base + DW_SPI_SSIENR);
    r32 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel(1, base + DW_SPI_SSIENR);

    if (priv->dma_mapped == 0x0) {
        if (priv->irq == IRQ_NOTCONNECTED) {
            while (priv->rx_len) {
                tx_room = readl(base + DW_SPI_TXFLR);
                while (priv->tx_len--) {
                    if (priv->reg_io_width == 0x2) {
                        writew(0, base + 0x0);
                    }
                    if (priv->reg_io_width == 0x4) {
                        writel(0, base + 0x0);
                    }
                }
                r38 = readl(base + 0x0);
                while (priv->rx_len--) {
                    if (priv->reg_io_width == 0x2) {
                        r39 = readw(base + 0x0);
                    }
                    if (priv->reg_io_width == 0x4) {
                        r40 = readl(base + 0x0);
                    }
                }
            }
        }
    }

    writel(level, base + DW_SPI_TXFTLR);
    writel((level - 0x1), base + DW_SPI_RXFTLR);
    r43 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
}

static void dw_spi_handle_err(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r46, r48;
    u32 new_mask = priv->new_mask;

    writel(0, base + DW_SPI_SSIENR);
    r46 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r48 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_target_abort(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r52, r54;
    u32 new_mask = priv->new_mask;

    writel(0, base + DW_SPI_SSIENR);
    r52 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r54 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_exec_mem_op(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r58, r68, r69;
    u32 entries, sts, nents;
    u32 len = priv->rx_len;
    u32 ret = priv->ret;
    u32 new_mask = priv->new_mask;

    writel(0, base + DW_SPI_SSIENR);
    r58 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel(1, base + DW_SPI_SSIENR);

    while (len--) {
        if (priv->reg_io_width == 0x2) {
            writew(0, base + 0x0);
        }
        if (priv->reg_io_width == 0x4) {
            writel(0, base + 0x0);
        }
    }

    while (len) {
        entries = readl(base + DW_SPI_TXFLR);
        while (len--) {
            if (priv->reg_io_width == 0x2) {
                writew(0, base + 0x0);
            }
            if (priv->reg_io_width == 0x4) {
                writel(0, base + 0x0);
            }
        }
    }

    while (len) {
        entries = readl(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = readl(base + DW_SPI_RISR);
        }
        while (len--) {
            if (priv->reg_io_width == 0x2) {
                r68 = readw(base + 0x0);
            }
            if (priv->reg_io_width == 0x4) {
                r69 = readl(base + 0x0);
            }
        }
    }

    if (ret == 0x0) {
        nents = readl(base + DW_SPI_TXFLR);
        while (DW_SPI_WAIT_RETRIES--) {
            u32 __return_read_0 = readl(base + DW_SPI_SR);
        }
    }

    writel(0, base + DW_SPI_SSIENR);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_add_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r75, r77, r85, r87, r90;
    u32 ser, cr0, tmp;
    u32 fifo = 0;
    u32 new_mask = priv->new_mask;

    if (1) { /* dws */
        writel(0, base + DW_SPI_SSIENR);
        r75 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r77 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel(1, base + DW_SPI_SSIENR);

        if (priv->ver == 0x0) {
            priv->ver = readl(base + DW_SPI_VERSION);
        }
        if (1) { /* spi_controller_is_target(dws->ctlr) == 0x0 */
            if (priv->num_cs == 0x0) {
                writel(0xffff, base + DW_SPI_SER);
                ser = readl(base + DW_SPI_SER);
                writel(0x0, base + DW_SPI_SER);
            }
        }
        if (priv->fifo_len == 0x0) {
            for (fifo = 0; fifo < 0x100; fifo++) {
                writel(fifo, base + DW_SPI_TXFTLR);
                r85 = readl(base + DW_SPI_TXFTLR);
            }
            writel(0x0, base + DW_SPI_TXFTLR);
        }
        if (1) { /* dw_spi_ip_is(dws, PSSI) */
            r87 = readl(base + DW_SPI_CTRLR0);
            writel(0, base + DW_SPI_SSIENR);
            writel(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = readl(base + DW_SPI_CTRLR0);
            writel(tmp, base + DW_SPI_CTRLR0);
            writel(1, base + DW_SPI_SSIENR);
        }
        if (priv->caps & DW_SPI_CAP_CS_OVERRIDE) {
            writel(0xf, base + DW_SPI_CS_OVERRIDE);
        }
    }
    if (0) {
        if (1) {
            if (1) {
                if (1) {
                    writel(0, base + DW_SPI_SSIENR);
                }
            }
        }
    }
}

static void dw_spi_remove_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    writel(0, base + DW_SPI_SSIENR);
    writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_suspend_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    writel(0, base + DW_SPI_SSIENR);
    writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_resume_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r100, r102, r110, r112, r115;
    u32 ser, cr0, tmp;
    u32 fifo = 0;
    u32 new_mask = priv->new_mask;

    writel(0, base + DW_SPI_SSIENR);
    r100 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r102 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);

    if (priv->ver == 0x0) {
        priv->ver = readl(base + DW_SPI_VERSION);
    }
    if (1) { /* spi_controller_is_target(dws->ctlr) == 0x0 */
        if (priv->num_cs == 0x0) {
            writel(0xffff, base + DW_SPI_SER);
            ser = readl(base + DW_SPI_SER);
            writel(0x0, base + DW_SPI_SER);
        }
    }
    if (priv->fifo_len == 0x0) {
        for (fifo = 0; fifo < 0x100; fifo++) {
            writel(fifo, base + DW_SPI_TXFTLR);
            r110 = readl(base + DW_SPI_TXFTLR);
        }
        writel(0x0, base + DW_SPI_TXFTLR);
    }
    if (1) { /* dw_spi_ip_is(dws, PSSI) */
        r112 = readl(base + DW_SPI_CTRLR0);
        writel(0, base + DW_SPI_SSIENR);
        writel(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = readl(base + DW_SPI_CTRLR0);
        writel(tmp, base + DW_SPI_CTRLR0);
        writel(1, base + DW_SPI_SSIENR);
    }
    if (priv->caps & DW_SPI_CAP_CS_OVERRIDE) {
        writel(0xf, base + DW_SPI_CS_OVERRIDE);
    }
}

static void dw_spi_mscc_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs = priv->cs;
    u32 sw_mode = priv->sw_mode;

    if (cs < 0x4) {
        writel((cs < 4) ? 8192 : sw_mode, base + MSCC_SPI_MST_SW_MODE);
    }
}

static void dw_spi_mscc_ocelot_init(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    writel(0x0, base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_mscc_jaguar2_init(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    writel(0x0, base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_sparx5_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 enable = priv->enable;
    if (enable == 0x0) {
    }
    if ((enable == 0x0) == 0x0) {
    }
}

static void dw_spi_elba_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs = priv->cs;
    if (cs < 0x2) {
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
    dw_spi_set_cs(priv);
    RH_TRACE_FN("dw_spi_check_status");
    dw_spi_check_status(priv);
    RH_TRACE_FN("dw_spi_transfer_handler");
    dw_spi_transfer_handler(priv);
    RH_TRACE_FN("dw_spi_irq");
    dw_spi_irq(priv);
    RH_TRACE_FN("dw_spi_update_config");
    dw_spi_update_config(priv);
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
    dw_spi_mscc_set_cs(priv);
    RH_TRACE_FN("dw_spi_mscc_ocelot_init");
    dw_spi_mscc_ocelot_init(priv);
    RH_TRACE_FN("dw_spi_mscc_jaguar2_init");
    dw_spi_mscc_jaguar2_init(priv);
    RH_TRACE_FN("dw_spi_sparx5_set_cs");
    dw_spi_sparx5_set_cs(priv);
    RH_TRACE_FN("dw_spi_elba_set_cs");
    dw_spi_elba_set_cs(priv);

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

static int dw_apb_ssi_remove(struct platform_device *pdev)
{
    struct driver_priv *priv = platform_get_drvdata(pdev);

    RH_TRACE_FN("dw_spi_remove_controller");
    dw_spi_remove_controller(priv);
    RH_TRACE_FN("dw_spi_suspend_controller");
    dw_spi_suspend_controller(priv);

    misc_deregister(&priv->misc);
    return 0;
}

static const struct of_device_id dw_apb_ssi_match[] = {
    { .compatible = "snps,dw-apb-ssi" },
    { /* Sentinel */ }
};
MODULE_DEVICE_TABLE(of, dw_apb_ssi_match);

static struct platform_driver dw_apb_ssi_driver = {
    .probe = dw_apb_ssi_probe,
    .remove = dw_apb_ssi_remove,
    .driver = {
        .name = "dw-apb-ssi",
        .of_match_table = dw_apb_ssi_match,
    },
};

module_platform_driver(dw_apb_ssi_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("DW APB SSI Generic MMIO Driver");