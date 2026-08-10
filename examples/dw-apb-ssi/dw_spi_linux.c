#include "dw-apb-ssi_linux.h"


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

static void dw_spi_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs_high = 0;
    u32 enable = 1;
    u32 chip_select = 0;

    if (cs_high == enable) {
        writel((0x1 << chip_select), base + DW_SPI_SER);
    } else {
    }
    if ((cs_high == enable) == 0x0) {
        writel(0x0, base + DW_SPI_SER);
    } else {
    }
}

static void dw_spi_check_status(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r6, r8;
    u32 raw = 1;
    u32 ret = 1;
    u32 new_mask = 0;

    if (raw) {
        irq_status = readl(base + DW_SPI_RISR);
    } else {
    }
    if (raw == 0x0) {
        irq_status = readl(base + DW_SPI_ISR);
    } else {
    }
    if (ret) {
        writel(0, base + DW_SPI_SSIENR);
        r6 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r8 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel(1, base + DW_SPI_SSIENR);
    } else {
    }
}

static void dw_spi_transfer_handler(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r12, r14, r16, r20;
    u32 rxw, tx_room;
    u32 new_mask = 0;
    int max = 10;
    u32 rx_len = 0;
    u32 tx_len = 0;
    u32 n_bytes = 1;
    void *tx = NULL;

    irq_status = readl(base + DW_SPI_ISR);
    r12 = readl(base + 0x0);
    while (max--) {
        rxw = readl(base + DW_SPI_DR);
    }
    if (rx_len == 0x0) {
        r14 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    } else {
    }
    if ((rx_len == 0x0) == 0x0) {
        r16 = readl(base + DW_SPI_RXFTLR);
        if (rx_len <= r16) {
            writel((rx_len - 0x1), base + DW_SPI_RXFTLR);
        } else {
        }
    } else {
    }
    if (irq_status & DW_SPI_INT_TXEI) {
        tx_room = readl(base + DW_SPI_TXFLR);
        while (max--) {
            u32 val = 0;
            if (tx && n_bytes != 1 && n_bytes != 2) {
                val = *(u32 *)(tx);
            } else if (tx && n_bytes == 2) {
                val = *(u16 *)(tx);
            } else if (tx) {
                val = *(u8 *)(tx);
            } else {
                val = 0;
            }
            writel(val, base + DW_SPI_DR);
        }
        if (tx_len == 0x0) {
            r20 = readl(base + DW_SPI_IMR);
            writel(new_mask, base + DW_SPI_IMR);
        } else {
        }
    } else {
    }
}

static void dw_spi_irq(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 irq_status;
    u32 r23;
    u32 new_mask = 0;
    void *cur_msg = NULL;

    irq_status = readl(base + DW_SPI_ISR);
    if (cur_msg == 0x0) {
        r23 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
    } else {
    }
}

static void dw_spi_update_config(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cr0 = 0;
    u32 tmode = DW_SPI_CTRLR0_TMOD_RO;
    u32 ndf = 1;
    u32 current_freq = 0;
    u32 speed_hz = 1;
    u32 cur_rx_sample_dly = 0;
    u32 rx_sample_dly = 1;
    u32 clk_div = 2;

    writel(cr0, base + DW_SPI_CTRLR0);
    if ((tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
        writel(ndf ? (ndf - 1) : 0, base + DW_SPI_CTRLR1);
    } else {
    }
    if (current_freq != speed_hz) {
        writel(clk_div, base + DW_SPI_BAUDR);
    } else {
    }
    if (cur_rx_sample_dly != rx_sample_dly) {
        writel(rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
    } else {
    }
}

static void dw_spi_transfer_one(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r30, r35, r39;
    u32 tx_room, rxw;
    u32 new_mask = 0;
    u32 dma_mapped = 0;
    u32 irq = IRQ_NOTCONNECTED;
    u32 rx_len = 1;
    u32 tx_len = 1;
    u32 n_bytes = 1;
    void *tx = NULL;
    u32 level = 1;
    int max = 10;

    writel(0, base + DW_SPI_SSIENR);
    r30 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel(1, base + DW_SPI_SSIENR);
    if (dma_mapped == 0x0) {
        if (irq == IRQ_NOTCONNECTED) {
            while (rx_len) {
                tx_room = readl(base + DW_SPI_TXFLR);
                while (max--) {
                    u32 val = 0;
                    if (tx && n_bytes != 1 && n_bytes != 2) {
                        val = *(u32 *)(tx);
                    } else if (tx && n_bytes == 2) {
                        val = *(u16 *)(tx);
                    } else if (tx) {
                        val = *(u8 *)(tx);
                    } else {
                        val = 0;
                    }
                    writel(val, base + DW_SPI_DR);
                }
                r35 = readl(base + 0x0);
                while (max--) {
                    rxw = readl(base + DW_SPI_DR);
                }
            }
        }
    }
    writel(level, base + DW_SPI_TXFTLR);
    writel((level - 0x1), base + DW_SPI_RXFTLR);
    r39 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
}

static void dw_spi_handle_err(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r42, r44;
    u32 new_mask = 0;

    writel(0, base + DW_SPI_SSIENR);
    r42 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r44 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_target_abort(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r48, r50;
    u32 new_mask = 0;

    writel(0, base + DW_SPI_SSIENR);
    r48 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r50 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_exec_mem_op(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r54, r62, r63, nents;
    u32 entries, sts;
    u32 new_mask = 0;
    u32 ret = 0;
    int len = 10;
    int room = 0;
    u8 *buf = NULL;
    int retry = 5;

    writel(0, base + DW_SPI_SSIENR);
    r54 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    writel(1, base + DW_SPI_SSIENR);
    while (len--) {
        writel(*buf++, base + DW_SPI_DR);
    }
    while (len) {
        entries = readl(base + DW_SPI_TXFLR);
        while (room && len--) {
            writel(*buf++, base + DW_SPI_DR);
        }
    }
    while (len) {
        entries = readl(base + DW_SPI_RXFLR);
        if (entries == 0x0) {
            sts = readl(base + DW_SPI_RISR);
        } else {
        }
        while (entries && len--) {
            r62 = readl(base + DW_SPI_DR);
        }
    }
    if (ret == 0x0) {
        nents = readl(base + DW_SPI_TXFLR);
        while (retry--) {
            u32 __return_read_0 = readl(base + DW_SPI_SR);
        }
    } else {
    }
    writel(0, base + DW_SPI_SSIENR);
    writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_add_controller(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 r68, r70, r78, r80, cr0, ser;
    u32 dws_ver = 0;
    u32 new_mask = 0;
    u32 dws = 1;
    u32 dws_num_cs = 0;
    u32 dws_fifo_len = 0;
    u32 dws_caps = DW_SPI_CAP_CS_OVERRIDE;
    int fifo = 0;
    u32 tmp = 0;

    if (dws) {
        writel(0, base + DW_SPI_SSIENR);
        r68 = readl(base + DW_SPI_IMR);
        writel(new_mask, base + DW_SPI_IMR);
        r70 = readl(base + DW_SPI_ICR);
        writel(0x0, base + DW_SPI_SER);
        writel(1, base + DW_SPI_SSIENR);
        if (dws_ver == 0x0) {
            dws_ver = readl(base + DW_SPI_VERSION);
        } else {
        }
        if (1 == 0x0) {
            if (dws_num_cs == 0x0) {
                writel(0xffff, base + DW_SPI_SER);
                ser = readl(base + DW_SPI_SER);
                writel(0x0, base + DW_SPI_SER);
            } else {
            }
        } else {
        }
        if (dws_fifo_len == 0x0) {
            while (fifo < 0x100) {
                writel(fifo, base + DW_SPI_TXFTLR);
                r78 = readl(base + DW_SPI_TXFTLR);
                fifo++;
            }
            writel(0x0, base + DW_SPI_TXFTLR);
        } else {
        }
        if (1) {
            r80 = readl(base + DW_SPI_CTRLR0);
            writel(0, base + DW_SPI_SSIENR);
            writel(0xffffffff, base + DW_SPI_CTRLR0);
            cr0 = readl(base + DW_SPI_CTRLR0);
            writel(tmp, base + DW_SPI_CTRLR0);
            writel(1, base + DW_SPI_SSIENR);
        } else {
        }
        if (dws_caps & DW_SPI_CAP_CS_OVERRIDE) {
            writel(0xf, base + DW_SPI_CS_OVERRIDE);
        } else {
        }
    } else {
    }
    if (0x0) {
        if (1) {
            if (1) {
                if (dws) {
                    writel(0, base + DW_SPI_SSIENR);
                } else {
                }
            } else {
            }
        } else {
        }
    } else {
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
    u32 r93, r95, r103, r105, cr0, ser;
    u32 dws_ver = 0;
    u32 new_mask = 0;
    u32 dws_num_cs = 0;
    u32 dws_fifo_len = 0;
    u32 dws_caps = DW_SPI_CAP_CS_OVERRIDE;
    int fifo = 0;
    u32 tmp = 0;

    writel(0, base + DW_SPI_SSIENR);
    r93 = readl(base + DW_SPI_IMR);
    writel(new_mask, base + DW_SPI_IMR);
    r95 = readl(base + DW_SPI_ICR);
    writel(0x0, base + DW_SPI_SER);
    writel(1, base + DW_SPI_SSIENR);
    if (dws_ver == 0x0) {
        dws_ver = readl(base + DW_SPI_VERSION);
    } else {
    }
    if (1 == 0x0) {
        if (dws_num_cs == 0x0) {
            writel(0xffff, base + DW_SPI_SER);
            ser = readl(base + DW_SPI_SER);
            writel(0x0, base + DW_SPI_SER);
        } else {
        }
    } else {
    }
    if (dws_fifo_len == 0x0) {
        while (fifo < 0x100) {
            writel(fifo, base + DW_SPI_TXFTLR);
            r103 = readl(base + DW_SPI_TXFTLR);
            fifo++;
        }
        writel(0x0, base + DW_SPI_TXFTLR);
    } else {
    }
    if (1) {
        r105 = readl(base + DW_SPI_CTRLR0);
        writel(0, base + DW_SPI_SSIENR);
        writel(0xffffffff, base + DW_SPI_CTRLR0);
        cr0 = readl(base + DW_SPI_CTRLR0);
        writel(tmp, base + DW_SPI_CTRLR0);
        writel(1, base + DW_SPI_SSIENR);
    } else {
    }
    if (dws_caps & DW_SPI_CAP_CS_OVERRIDE) {
        writel(0xf, base + DW_SPI_CS_OVERRIDE);
    } else {
    }
}

static void dw_spi_mscc_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs = 0;
    u32 sw_mode = 0;

    if (cs < 0x4) {
        writel((cs < 4) ? 8192 : sw_mode, base + MSCC_SPI_MST_SW_MODE);
    } else {
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
    u32 enable = 1;

    if (enable == 0x0) {
    } else {
    }
    if ((enable == 0x0) == 0x0) {
    } else {
    }
}

static void dw_spi_elba_set_cs(struct driver_priv *priv)
{
    void __iomem *base = priv->base;
    u32 cs = 0;

    if (cs < 0x2) {
    } else {
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

    priv->misc.name = KBUILD_MODNAME;
    priv->misc.minor = MISC_DYNAMIC_MINOR;
    priv->misc.fops = &dw_apb_ssi_fops;
    priv->misc.parent = &pdev->dev;

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
    { .compatible = "snps,dw-apb-ssi", },
    { }
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
MODULE_DESCRIPTION("DW APB SSI Driver");