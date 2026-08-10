#include "dw-apb-ssi_linux.h"


static int dw_apb_ssi_open(struct inode *inode, struct file *file)
{
	struct dw_apb_ssi_priv *priv = container_of(file->private_data, struct dw_apb_ssi_priv, misc);
	file->private_data = priv;
	return 0;
}

static ssize_t dw_apb_ssi_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
	struct dw_apb_ssi_priv *priv = file->private_data;
	u32 val;

	if (*ppos & 3 || count < 4)
		return -EINVAL;

	val = readl(priv->base + *ppos);
	if (copy_to_user(buf, &val, 4))
		return -EFAULT;
	*ppos += 4;
	return 4;
}

static ssize_t dw_apb_ssi_write(struct file *file, const char __user *buf, size_t count, loff_t *ppos)
{
	struct dw_apb_ssi_priv *priv = file->private_data;
	u32 val;

	if (*ppos & 3 || count < 4)
		return -EINVAL;

	if (copy_from_user(&val, buf, 4))
		return -EFAULT;
	writel(val, priv->base + *ppos);
	*ppos += 4;
	return 4;
}

static const struct file_operations dw_apb_ssi_fops = {
	.owner = THIS_MODULE,
	.open = dw_apb_ssi_open,
	.read = dw_apb_ssi_read,
	.write = dw_apb_ssi_write,
};

static void dw_spi_set_cs(struct dw_apb_ssi_priv *priv)
{
	int cs_high = 1, enable = 1, spi_get_chipselect = 0;
	u32 irq_status, r6, r7, tx_room;

	RH_TRACE_FN(__func__);

	if (cs_high == enable) {
		writel(DW_SPI_SER, priv->base + (1 << spi_get_chipselect));
	}
	if ((cs_high == enable) == 0x0) {
		writel(DW_SPI_SER, priv->base + 0x0);
	}
}

static void dw_spi_check_status(struct dw_apb_ssi_priv *priv)
{
	int raw = 1;
	u32 irq_status;

	RH_TRACE_FN(__func__);

	if (raw) {
		irq_status = readl(priv->base + DW_SPI_RISR);
	}
	if (raw == 0x0) {
		irq_status = readl(priv->base + DW_SPI_ISR);
	}
}

static void dw_spi_transfer_handler(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status, r6, r7, tx_room;
	int rx_len = 1;

	RH_TRACE_FN(__func__);

	irq_status = readl(priv->base + DW_SPI_ISR);
	r6 = readl(priv->base + 0x0);

	if (rx_len != 0x0) {
		r7 = readl(priv->base + DW_SPI_RXFTLR);
		if (rx_len <= r7) {
			writel(DW_SPI_RXFTLR, priv->base + (rx_len - 1));
		}
	}

	if (irq_status & DW_SPI_INT_TXEI) {
		tx_room = readl(priv->base + DW_SPI_TXFLR);
	}
}

static void dw_spi_irq(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;

	RH_TRACE_FN(__func__);

	irq_status = readl(priv->base + DW_SPI_ISR);
}

static void dw_spi_update_config(struct dw_apb_ssi_priv *priv)
{
	u32 cr0 = 0, cfg_tmode = DW_SPI_CTRLR0_TMOD_RO, cfg_ndf = 1, speed_hz = 1, current_freq = 0;
	u32 clk_div = 2, chip_rx_sample_dly = 1, cur_rx_sample_dly = 0;

	RH_TRACE_FN(__func__);

	writel(DW_SPI_CTRLR0, priv->base + cr0);

	if ((cfg_tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
		writel(DW_SPI_CTRLR1, priv->base + (cfg_ndf ? (cfg_ndf - 1) : 0));
	}

	if (current_freq != speed_hz) {
		writel(DW_SPI_BAUDR, priv->base + clk_div);
	}

	if (cur_rx_sample_dly != chip_rx_sample_dly) {
		writel(DW_SPI_RX_SAMPLE_DLY, priv->base + chip_rx_sample_dly);
	}
}

static void dw_spi_transfer_one(struct dw_apb_ssi_priv *priv)
{
	int dma_mapped = 0, irq = IRQ_NOTCONNECTED, rx_len = 1;
	u32 level = 2, tx_room, r18;

	RH_TRACE_FN(__func__);

	writel(DW_SPI_SSIENR, priv->base + 0);
	writel(DW_SPI_SSIENR, priv->base + 1);

	if (dma_mapped == 0x0) {
		if (irq == IRQ_NOTCONNECTED) {
			while (rx_len) {
				tx_room = readl(priv->base + DW_SPI_TXFLR);
				r18 = readl(priv->base + 0x0);
			}
		}
	}

	writel(DW_SPI_TXFTLR, priv->base + level);
	writel(DW_SPI_RXFTLR, priv->base + (level - 1));
}

static void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *priv)
{
	int len = 1, ret = 0, retry = DW_SPI_WAIT_RETRIES;
	u32 entries, nents, sts, __return_read_0;

	RH_TRACE_FN(__func__);

	writel(DW_SPI_SSIENR, priv->base + 0);
	writel(DW_SPI_SSIENR, priv->base + 1);

	while (len) {
		entries = readl(priv->base + DW_SPI_TXFLR);
	}

	while (len) {
		entries = readl(priv->base + DW_SPI_RXFLR);
		if (entries == 0x0) {
			sts = readl(priv->base + DW_SPI_RISR);
		}
	}

	if (ret == 0x0) {
		nents = readl(priv->base + DW_SPI_TXFLR);
		while (retry--) {
			__return_read_0 = readl(priv->base + DW_SPI_SR);
		}
	}

	writel(DW_SPI_SSIENR, priv->base + 0);
	writel(DW_SPI_SSIENR, priv->base + 1);
}

static void dw_spi_add_controller(struct dw_apb_ssi_priv *priv)
{
	int dws = 1, ver = 0, is_target = 0, num_cs = 0, fifo_len = 0, ip_is_pssi = 1;
	int caps = DW_SPI_CAP_CS_OVERRIDE, ret = -ENOTCONN, dma_ops = 0;
	u32 fifo, r35, r37, cr0, tmp = 0, ser;

	RH_TRACE_FN(__func__);

	if (dws) {
		if (ver == 0x0) {
			ver = readl(priv->base + DW_SPI_VERSION);
		}
		if (is_target == 0x0) {
			if (num_cs == 0x0) {
				writel(DW_SPI_SER, priv->base + 0xffff);
				ser = readl(priv->base + DW_SPI_SER);
				writel(DW_SPI_SER, priv->base + 0x0);
			}
		}
		if (fifo_len == 0x0) {
			for (fifo = 0; fifo < 0x100; fifo++) {
				writel(DW_SPI_TXFTLR, priv->base + fifo);
				r35 = readl(priv->base + DW_SPI_TXFTLR);
			}
			writel(DW_SPI_TXFTLR, priv->base + 0x0);
		}
		if (ip_is_pssi) {
			r37 = readl(priv->base + DW_SPI_CTRLR0);
			writel(DW_SPI_SSIENR, priv->base + 0);
			writel(DW_SPI_CTRLR0, priv->base + 0xffffffff);
			cr0 = readl(priv->base + DW_SPI_CTRLR0);
			writel(DW_SPI_CTRLR0, priv->base + tmp);
			writel(DW_SPI_SSIENR, priv->base + 1);
		}
		if (caps & DW_SPI_CAP_CS_OVERRIDE) {
			writel(DW_SPI_CS_OVERRIDE, priv->base + 0xf);
		}
	}

	if (0x0) {
		if (((dma_ops && 0) && (ret == -EPROBE_DEFER)) == 0x0) {
			if ((((ret < 0x0) && ret) != -ENOTCONN) == 0x0) {
				if (dws) {
					writel(DW_SPI_SSIENR, priv->base + 0);
				}
			}
		}
	}
}

static void dw_spi_resume_controller(struct dw_apb_ssi_priv *priv)
{
	int ver = 0, is_target = 0, num_cs = 0, fifo_len = 0, ip_is_pssi = 1;
	int caps = DW_SPI_CAP_CS_OVERRIDE;
	u32 fifo, r50, r52, cr0, tmp = 0, ser;

	RH_TRACE_FN(__func__);

	if (ver == 0x0) {
		ver = readl(priv->base + DW_SPI_VERSION);
	}
	if (is_target == 0x0) {
		if (num_cs == 0x0) {
			writel(DW_SPI_SER, priv->base + 0xffff);
			ser = readl(priv->base + DW_SPI_SER);
			writel(DW_SPI_SER, priv->base + 0x0);
		}
	}
	if (fifo_len == 0x0) {
		for (fifo = 0; fifo < 0x100; fifo++) {
			writel(DW_SPI_TXFTLR, priv->base + fifo);
			r50 = readl(priv->base + DW_SPI_TXFTLR);
		}
		writel(DW_SPI_TXFTLR, priv->base + 0x0);
	}
	if (ip_is_pssi) {
		r52 = readl(priv->base + DW_SPI_CTRLR0);
		writel(DW_SPI_SSIENR, priv->base + 0);
		writel(DW_SPI_CTRLR0, priv->base + 0xffffffff);
		cr0 = readl(priv->base + DW_SPI_CTRLR0);
		writel(DW_SPI_CTRLR0, priv->base + tmp);
		writel(DW_SPI_SSIENR, priv->base + 1);
	}
	if (caps & DW_SPI_CAP_CS_OVERRIDE) {
		writel(DW_SPI_CS_OVERRIDE, priv->base + 0xf);
	}
}

static void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *priv)
{
	int cs = 1, sw_mode = 0;

	RH_TRACE_FN(__func__);

	if (cs < 0x4) {
		writel((cs < 4) ? 8192 : sw_mode, priv->base + MSCC_SPI_MST_SW_MODE);
	}
}

static void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *priv)
{
	RH_TRACE_FN(__func__);
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *priv)
{
	RH_TRACE_FN(__func__);
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *priv)
{
	int enable = 0;
	RH_TRACE_FN(__func__);
	if (enable == 0x0) {}
	if ((enable == 0x0) == 0x0) {}
}

static void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *priv)
{
	int cs = 1;
	RH_TRACE_FN(__func__);
	if (cs < 0x2) {}
}

static int dw_apb_ssi_probe(struct platform_device *pdev)
{
	struct dw_apb_ssi_priv *priv;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->dev = &pdev->dev;

	priv->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);

	RH_SET_BASE(priv->base);

	dw_spi_set_cs(priv);
	dw_spi_check_status(priv);
	dw_spi_transfer_handler(priv);
	dw_spi_irq(priv);
	dw_spi_update_config(priv);
	dw_spi_transfer_one(priv);
	dw_spi_exec_mem_op(priv);
	dw_spi_add_controller(priv);
	dw_spi_resume_controller(priv);
	dw_spi_mscc_set_cs(priv);
	dw_spi_mscc_ocelot_init(priv);
	dw_spi_mscc_jaguar2_init(priv);
	dw_spi_sparx5_set_cs(priv);
	dw_spi_elba_set_cs(priv);

	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &dw_apb_ssi_fops;
	priv->misc.parent = &pdev->dev;

	ret = misc_register(&priv->misc);
	if (ret)
		return ret;

	platform_set_drvdata(pdev, priv);
	dev_info(&pdev->dev, "dw-apb-ssi driver probed\n");
	return 0;
}

static int dw_apb_ssi_remove(struct platform_device *pdev)
{
	struct dw_apb_ssi_priv *priv = platform_get_drvdata(pdev);

	misc_deregister(&priv->misc);
	return 0;
}

static const struct of_device_id dw_apb_ssi_match[] = {
	{ .compatible = "snps,dw-apb-ssi", },
	{ /* sentinel */ }
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
MODULE_DESCRIPTION("Synopsys DesignWare APB SSI Driver");