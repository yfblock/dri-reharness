#include "dw-apb-ssi_linux.h"


static int dw_apb_ssi_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;
	struct dw_apb_ssi_priv *priv = container_of(misc, struct dw_apb_ssi_priv, misc);
	file->private_data = priv;
	return 0;
}

static ssize_t dw_apb_ssi_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
	struct dw_apb_ssi_priv *priv = file->private_data;
	u32 val;

	if (count < 4 || (*ppos & 3))
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

	if (count < 4 || (*ppos & 3))
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
	int cs_high = 1;
	int enable = 1;
	if (cs_high == enable) {
		writel(DW_SPI_SER, priv->base + (1 << 0));
	}
	if ((cs_high == enable) == 0x0) {
		writel(DW_SPI_SER, priv->base + 0x0);
	}
}

static void dw_spi_check_status(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;
	int raw = 1;
	int ret = 1;
	u32 new_mask = 0;
	u32 r6, r8;

	if (raw) {
		irq_status = readl(priv->base + DW_SPI_RISR);
	} else {
		irq_status = readl(priv->base + DW_SPI_ISR);
	}

	if (ret) {
		writel(0, priv->base + 0);
		r6 = readl(priv->base + DW_SPI_IMR);
		writel(new_mask, priv->base + DW_SPI_IMR);
		r8 = readl(priv->base + DW_SPI_ICR);
		writel(0, priv->base + 0x0);
		writel(1, priv->base + 1);
	}
}

static void dw_spi_transfer_handler(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;
	u32 r12, r13, r14, r15, r17, r22;
	u32 tx_room;
	u32 new_mask = 0;
	int reg_io_width = 4;
	int rx_len = 0;
	int tx_len = 0;

	irq_status = readl(priv->base + DW_SPI_ISR);
	r12 = readl(priv->base + 0x0);

	for (;;) {
		if (reg_io_width == 0x2) {
			r13 = readw(priv->base + 0x0);
		}
		if (reg_io_width == 0x4) {
			r14 = readl(priv->base + 0x0);
		}
		break;
	}

	if (rx_len == 0x0) {
		r15 = readl(priv->base + DW_SPI_IMR);
		writel(new_mask, priv->base + DW_SPI_IMR);
	} else {
		r17 = readl(priv->base + DW_SPI_RXFTLR);
		if (rx_len <= r17) {
			writel(rx_len - 1, priv->base + DW_SPI_RXFTLR);
		}
	}

	if (irq_status & DW_SPI_INT_TXEI) {
		tx_room = readl(priv->base + DW_SPI_TXFLR);
		for (;;) {
			if (reg_io_width == 0x2) {
				writew(0, priv->base + 0x0);
			}
			if (reg_io_width == 0x4) {
				writel(0, priv->base + 0x0);
			}
			break;
		}
		if (tx_len == 0x0) {
			r22 = readl(priv->base + DW_SPI_IMR);
			writel(new_mask, priv->base + DW_SPI_IMR);
		}
	}
}

static void dw_spi_irq(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;
	u32 r25;
	u32 new_mask = 0;
	int cur_msg_null = 1;

	irq_status = readl(priv->base + DW_SPI_ISR);

	if (cur_msg_null) {
		r25 = readl(priv->base + DW_SPI_IMR);
		writel(new_mask, priv->base + DW_SPI_IMR);
	}
}

static void dw_spi_update_config(struct dw_apb_ssi_priv *priv)
{
	u32 cr0 = 0;
	u32 cfg_tmode = DW_SPI_CTRLR0_TMOD_RO;
	u32 cfg_ndf = 0;
	int current_freq = 100;
	int speed_hz = 200;
	u32 clk_div = 10;
	int cur_rx_sample_dly = 0;
	int chip_rx_sample_dly = 1;

	writel(cr0, priv->base + DW_SPI_CTRLR0);

	if ((cfg_tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO) {
		writel(cfg_ndf ? (cfg_ndf - 1) : 0, priv->base + DW_SPI_CTRLR1);
	}

	if (current_freq != speed_hz) {
		writel(clk_div, priv->base + DW_SPI_BAUDR);
	}

	if (cur_rx_sample_dly != chip_rx_sample_dly) {
		writel(chip_rx_sample_dly, priv->base + DW_SPI_RX_SAMPLE_DLY);
	}
}

static void dw_spi_transfer_one(struct dw_apb_ssi_priv *priv)
{
	u32 r32, r38, r39, r40, r43;
	u32 tx_room;
	u32 new_mask = 0;
	u32 level = 32;
	int dma_mapped = 0;
	int irq = IRQ_NOTCONNECTED;
	int reg_io_width = 4;
	int rx_len = 1;

	writel(0, priv->base + 0);
	r32 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	writel(1, priv->base + 1);

	if (dma_mapped == 0x0) {
		if (irq == IRQ_NOTCONNECTED) {
			while (rx_len) {
				tx_room = readl(priv->base + DW_SPI_TXFLR);
				for (;;) {
					if (reg_io_width == 0x2) {
						writew(0, priv->base + 0x0);
					}
					if (reg_io_width == 0x4) {
						writel(0, priv->base + 0x0);
					}
					break;
				}
				r38 = readl(priv->base + 0x0);
				for (;;) {
					if (reg_io_width == 0x2) {
						r39 = readw(priv->base + 0x0);
					}
					if (reg_io_width == 0x4) {
						r40 = readl(priv->base + 0x0);
					}
					break;
				}
			}
		}
	}

	writel(level, priv->base + DW_SPI_TXFTLR);
	writel(level - 1, priv->base + DW_SPI_RXFTLR);
	r43 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
}

static void dw_spi_handle_err(struct dw_apb_ssi_priv *priv)
{
	u32 r46, r48;
	u32 new_mask = 0;

	writel(0, priv->base + 0);
	r46 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	r48 = readl(priv->base + DW_SPI_ICR);
	writel(0, priv->base + 0x0);
	writel(1, priv->base + 1);
}

static void dw_spi_target_abort(struct dw_apb_ssi_priv *priv)
{
	u32 r52, r54;
	u32 new_mask = 0;

	writel(0, priv->base + 0);
	r52 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	r54 = readl(priv->base + DW_SPI_ICR);
	writel(0, priv->base + 0x0);
	writel(1, priv->base + 1);
}

static void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *priv)
{
	u32 r58, r63, r66, r67, r68, r69, r70, r71;
	u32 entries;
	u32 new_mask = 0;
	int reg_io_width = 4;
	int len = 1;
	int ret = 0;

	writel(0, priv->base + 0);
	r58 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	writel(1, priv->base + 1);

	while (len--) {
		if (reg_io_width == 0x2) {
			writew(0, priv->base + 0x0);
		}
		if (reg_io_width == 0x4) {
			writel(0, priv->base + 0x0);
		}
	}

	while (len) {
		entries = readl(priv->base + DW_SPI_TXFLR);
		while (len) {
			if (reg_io_width == 0x2) {
				writew(0, priv->base + 0x0);
			}
			if (reg_io_width == 0x4) {
				writel(0, priv->base + 0x0);
			}
			len--;
		}
	}

	while (len) {
		entries = readl(priv->base + DW_SPI_RXFLR);
		if (entries == 0x0) {
			r67 = readl(priv->base + DW_SPI_RISR);
		}
		while (len) {
			if (reg_io_width == 0x2) {
				r68 = readw(priv->base + 0x0);
			}
			if (reg_io_width == 0x4) {
				r69 = readl(priv->base + 0x0);
			}
			len--;
		}
	}

	if (ret == 0x0) {
		r70 = readl(priv->base + DW_SPI_TXFLR);
		for (;;) {
			r71 = readl(priv->base + DW_SPI_SR);
			break;
		}
	}

	writel(0, priv->base + 0);
	writel(1, priv->base + 1);
}

static void dw_spi_add_controller(struct dw_apb_ssi_priv *priv)
{
	u32 r75, r77, r80, r82, r85, r87, r90;
	u32 ser;
	u32 new_mask = 0;
	int ver = 0;
	int is_target = 0;
	int num_cs = 0;
	int fifo_len = 0;
	int caps = DW_SPI_CAP_CS_OVERRIDE;
	int fifo;

	writel(0, priv->base + 0);
	r75 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	r77 = readl(priv->base + DW_SPI_ICR);
	writel(0, priv->base + 0x0);
	writel(1, priv->base + 1);

	if (ver == 0x0) {
		r80 = readl(priv->base + DW_SPI_VERSION);
	}

	if (is_target == 0x0) {
		if (num_cs == 0x0) {
			writel(0xffff, priv->base + 0xffff);
			r82 = readl(priv->base + DW_SPI_SER);
			writel(0x0, priv->base + 0x0);
		}
	}

	if (fifo_len == 0x0) {
		for (fifo = 0; fifo < 0x100; fifo++) {
			writel(fifo, priv->base + DW_SPI_TXFTLR);
			r85 = readl(priv->base + DW_SPI_TXFTLR);
		}
		writel(0x0, priv->base + 0x0);
	}

	r87 = readl(priv->base + DW_SPI_CTRLR0);
	writel(0, priv->base + 0);
	writel(0xffffffff, priv->base + 0xffffffff);
	r90 = readl(priv->base + DW_SPI_CTRLR0);
	writel(0, priv->base + DW_SPI_CTRLR0);
	writel(1, priv->base + 1);

	if (caps & DW_SPI_CAP_CS_OVERRIDE) {
		writel(0xf, priv->base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_remove_controller(struct dw_apb_ssi_priv *priv)
{
	writel(0, priv->base + 0);
	writel(0, priv->base + DW_SPI_BAUDR);
}

static void dw_spi_suspend_controller(struct dw_apb_ssi_priv *priv)
{
	writel(0, priv->base + 0);
	writel(0, priv->base + DW_SPI_BAUDR);
}

static void dw_spi_resume_controller(struct dw_apb_ssi_priv *priv)
{
	u32 r100, r102, r105, r107, r110, r112, r115;
	u32 ser;
	u32 new_mask = 0;
	int ver = 0;
	int is_target = 0;
	int num_cs = 0;
	int fifo_len = 0;
	int caps = DW_SPI_CAP_CS_OVERRIDE;
	int fifo;

	writel(0, priv->base + 0);
	r100 = readl(priv->base + DW_SPI_IMR);
	writel(new_mask, priv->base + DW_SPI_IMR);
	r102 = readl(priv->base + DW_SPI_ICR);
	writel(0, priv->base + 0x0);
	writel(1, priv->base + 1);

	if (ver == 0x0) {
		r105 = readl(priv->base + DW_SPI_VERSION);
	}

	if (is_target == 0x0) {
		if (num_cs == 0x0) {
			writel(0xffff, priv->base + 0xffff);
			r107 = readl(priv->base + DW_SPI_SER);
			writel(0x0, priv->base + 0x0);
		}
	}

	if (fifo_len == 0x0) {
		for (fifo = 0; fifo < 0x100; fifo++) {
			writel(fifo, priv->base + DW_SPI_TXFTLR);
			r110 = readl(priv->base + DW_SPI_TXFTLR);
		}
		writel(0x0, priv->base + 0x0);
	}

	r112 = readl(priv->base + DW_SPI_CTRLR0);
	writel(0, priv->base + 0);
	writel(0xffffffff, priv->base + 0xffffffff);
	r115 = readl(priv->base + DW_SPI_CTRLR0);
	writel(0, priv->base + DW_SPI_CTRLR0);
	writel(1, priv->base + 1);

	if (caps & DW_SPI_CAP_CS_OVERRIDE) {
		writel(0xf, priv->base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *priv)
{
	int cs = 2;
	u32 sw_mode = 0;

	if (cs < 0x4) {
		writel((cs < 4) ? 8192 : sw_mode, priv->base + MSCC_SPI_MST_SW_MODE);
	}
}

static void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *priv)
{
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *priv)
{
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_sparx5_set_cs(struct dw_apb_ssi_priv *priv)
{
	int enable = 0;
	if (enable == 0x0) {}
	if ((enable == 0x0) == 0x0) {}
}

static void dw_spi_elba_set_cs(struct dw_apb_ssi_priv *priv)
{
	int cs = 1;
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

	ret = misc_register(&priv->misc);
	if (ret) {
		dev_err(&pdev->dev, "Failed to register misc device\n");
		return ret;
	}

	platform_set_drvdata(pdev, priv);
	dev_info(&pdev->dev, "dw-apb-ssi module loaded\n");
	return 0;
}

static int dw_apb_ssi_remove(struct platform_device *pdev)
{
	struct dw_apb_ssi_priv *priv = platform_get_drvdata(pdev);

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
MODULE_DESCRIPTION("Synopsys DesignWare APB SSI Driver");