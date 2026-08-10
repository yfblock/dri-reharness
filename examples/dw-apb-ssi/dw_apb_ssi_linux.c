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

static void dw_spi_set_cs(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 cs_high = 0, enable = 0;
	u32 chip_select = 0;

	if (cs_high == enable) {
		writel((0x1 << chip_select), base + DW_SPI_SER);
	}
	if ((cs_high == enable) == 0x0) {
		writel(0x0, base + DW_SPI_SER);
	}
}

static void dw_spi_check_status(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 raw = 0, ret = 0, new_mask = 0;

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
	u32 new_mask = 0, max = 0, tx_room = 0;
	u32 irq_status = 0, rx_len = 0, tx_len = 0, n_bytes = 0;
	void *tx = NULL;

	irq_status = readl(base + DW_SPI_ISR);
	r12 = readl(base + DW_SPI_RXFLR);
	while (max--) {
		rxw = readl(base + DW_SPI_DR);
	}
	if (rx_len == 0x0) {
		r14 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
	}
	if ((rx_len == 0x0) == 0x0) {
		r16 = readl(base + DW_SPI_RXFTLR);
		if (rx_len <= r16) {
			writel((rx_len - 0x1), base + DW_SPI_RXFTLR);
		}
	}
	if (irq_status & DW_SPI_INT_TXEI) {
		tx_room = readl(base + DW_SPI_TXFLR);
		while (max--) {
			writel((tx && n_bytes != 1 && n_bytes != 2) ? (*(u32 *)tx) : ((tx && n_bytes != 1 && n_bytes == 2) ? (*(u16 *)tx) : ((tx && n_bytes == 1) ? (*(u8 *)tx) : 0)), base + DW_SPI_DR);
		}
		if (tx_len == 0x0) {
			r20 = readl(base + DW_SPI_IMR);
			writel(new_mask, base + DW_SPI_IMR);
		}
	}
}

static void dw_spi_irq(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 new_mask = 0, cur_msg = 0;

	irq_status = readl(base + DW_SPI_ISR);
	if (cur_msg == 0x0) {
		r23 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
	}
}

static void dw_spi_update_config(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 cr0 = 0, tmode = 0, ndf = 0, current_freq = 0, speed_hz = 1, clk_div = 0, cur_rx_sample_dly = 0, rx_sample_dly = 1;

	writel(cr0, base + DW_SPI_CTRLR0);
	if (((tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD | tmode))) == DW_SPI_CTRLR0_TMOD_RO) {
		writel((ndf ? (ndf - 1) : 0), base + DW_SPI_CTRLR1);
	}
	if (current_freq != speed_hz) {
		writel(clk_div, base + DW_SPI_BAUDR);
	}
	if (cur_rx_sample_dly != rx_sample_dly) {
		writel(rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
	}
}

static void dw_spi_transfer_one(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 new_mask = 0, dma_mapped = 1, irq = 0, max = 0, rx_len = 0, tx_len = 0, n_bytes = 0, level = 0;
	void *tx = NULL;

	writel(0, base + DW_SPI_SSIENR);
	r30 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	writel(1, base + DW_SPI_SSIENR);
	if (dma_mapped == 0x0) {
		if (irq == IRQ_NOTCONNECTED) {
			while (rx_len) {
				tx_room = readl(base + DW_SPI_TXFLR);
				while (max--) {
					writel((tx && n_bytes != 1 && n_bytes != 2) ? (*(u32 *)tx) : ((tx && n_bytes != 1 && n_bytes == 2) ? (*(u16 *)tx) : ((tx && n_bytes == 1) ? (*(u8 *)tx) : 0)), base + DW_SPI_DR);
				}
				r35 = readl(base + DW_SPI_RXFLR);
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
	u32 len = 1, ret = 0, retry = 1;
	u8 *buf = NULL;

	writel(0, base + DW_SPI_SSIENR);
	r54 = readl(base + DW_SPI_IMR);
	writel(0, base + DW_SPI_IMR);
	writel(1, base + DW_SPI_SSIENR);
	while (len--) {
		writel(*buf++, base + DW_SPI_DR);
	}
	while (len) {
		u32 entries = readl(base + DW_SPI_TXFLR);
		u32 room = 0;
		while (room < len) {
			writel(*buf++, base + DW_SPI_DR);
		}
	}
	while (len) {
		u32 entries = readl(base + DW_SPI_RXFLR);
		if (entries == 0x0) {
			u32 sts = readl(base + DW_SPI_RISR);
		}
		while (entries < len) {
			r62 = readl(base + DW_SPI_DR);
		}
	}
	if (ret == 0x0) {
		u32 nents = readl(base + DW_SPI_TXFLR);
		while (retry--) {
			u32 __return_read_0 = readl(base + DW_SPI_SR);
		}
	}
	writel(0, base + DW_SPI_SSIENR);
	writel(1, base + DW_SPI_SSIENR);
}

static void dw_spi_add_controller(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 dws = 1, new_mask = 0, ver = 0, is_target = 0, num_cs = 0, fifo_len = 0, is_pssi = 1, caps = DW_SPI_CAP_CS_OVERRIDE, fifo = 0, tmp = 0, ret = 0;

	if (dws) {
		writel(0, base + DW_SPI_SSIENR);
		r68 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
		r70 = readl(base + DW_SPI_ICR);
		writel(0x0, base + DW_SPI_SER);
		writel(1, base + DW_SPI_SSIENR);
		if (ver == 0x0) {
			ver = readl(base + DW_SPI_VERSION);
		}
		if (is_target == 0x0) {
			if (num_cs == 0x0) {
				writel(0xffff, base + DW_SPI_SER);
				r75 = readl(base + DW_SPI_SER);
				writel(0x0, base + DW_SPI_SER);
			}
		}
		if (fifo_len == 0x0) {
			for (fifo = 0; fifo < 0x100; fifo++) {
				writel(fifo, base + DW_SPI_TXFTLR);
				r78 = readl(base + DW_SPI_TXFTLR);
			}
			writel(0x0, base + DW_SPI_TXFTLR);
		}
		if (is_pssi) {
			r80 = readl(base + DW_SPI_CTRLR0);
			writel(0, base + DW_SPI_SSIENR);
			writel(0xffffffff, base + DW_SPI_CTRLR0);
			cr0 = readl(base + DW_SPI_CTRLR0);
			writel(tmp, base + DW_SPI_CTRLR0);
			writel(1, base + DW_SPI_SSIENR);
		}
		if (caps & DW_SPI_CAP_CS_OVERRIDE) {
			writel(0xf, base + DW_SPI_CS_OVERRIDE);
		}
	}
	if (0x0) {
		writel(0, base + DW_SPI_SSIENR);
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
	u32 new_mask = 0, ver = 0, is_target = 0, num_cs = 0, fifo_len = 0, is_pssi = 1, caps = DW_SPI_CAP_CS_OVERRIDE, fifo = 0, tmp = 0;

	writel(0, base + DW_SPI_SSIENR);
	r93 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	r95 = readl(base + DW_SPI_ICR);
	writel(0x0, base + DW_SPI_SER);
	writel(1, base + DW_SPI_SSIENR);
	if (ver == 0x0) {
		ver = readl(base + DW_SPI_VERSION);
	}
	if (is_target == 0x0) {
		if (num_cs == 0x0) {
			writel(0xffff, base + DW_SPI_SER);
			r100 = readl(base + DW_SPI_SER);
			writel(0x0, base + DW_SPI_SER);
		}
	}
	if (fifo_len == 0x0) {
		for (fifo = 0; fifo < 0x100; fifo++) {
			writel(fifo, base + DW_SPI_TXFTLR);
			r103 = readl(base + DW_SPI_TXFTLR);
		}
		writel(0x0, base + DW_SPI_TXFTLR);
	}
	if (is_pssi) {
		r105 = readl(base + DW_SPI_CTRLR0);
		writel(0, base + DW_SPI_SSIENR);
		writel(0xffffffff, base + DW_SPI_CTRLR0);
		r108 = readl(base + DW_SPI_CTRLR0);
		writel(tmp, base + DW_SPI_CTRLR0);
		writel(1, base + DW_SPI_SSIENR);
	}
	if (caps & DW_SPI_CAP_CS_OVERRIDE) {
		writel(0xf, base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_mscc_set_cs(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 cs = 0, sw_mode = 0;

	if (cs < 0x4) {
		writel((cs < 4) ? 8192 : sw_mode, base + MSCC_SPI_MST_SW_MODE);
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

static void dw_spi_sparx5_set_cs(struct driver_priv *priv)
{
	static struct regmap *dwsmscc_syscon = NULL;
	u32 enable = 0;

	if (enable == 0x0) {
		regmap_write(dwsmscc_syscon, SPARX5_FORCE_ENA, 0);
		regmap_write(dwsmscc_syscon, SPARX5_FORCE_VAL, 0);
	}
	if ((enable == 0x0) == 0x0) {
		regmap_write(dwsmscc_syscon, SPARX5_FORCE_VAL, 0);
		regmap_write(dwsmscc_syscon, SPARX5_FORCE_ENA, 0);
	}
}

static void dw_spi_elba_set_cs(struct driver_priv *priv)
{
	static struct regmap *dwsmmio_priv = NULL;
	u32 cs = 0;

	if (cs < 0x2) {
		regmap_update_bits(dwsmmio_priv, ELBA_SPICS_REG, 0, 0);
	}
}

static int dw_apb_ssi_probe(struct platform_device *pdev)
{
	struct driver_priv *priv;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

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
	if (ret)
		return ret;

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
MODULE_DESCRIPTION("DW APB SSI Generic MMIO Driver");