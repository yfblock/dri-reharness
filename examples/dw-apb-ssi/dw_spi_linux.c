#include "spi-dw-core_linux.h"


struct spi_dw_core_priv {
	void __iomem *base;
	struct miscdevice misc;
	struct device *dev;
	u32 ver;
	u32 num_cs;
	u32 fifo_len;
	u32 caps;
	u32 cur_rx_sample_dly;
	u32 rx_len;
	struct dw_spi_chip_data *chip;
};

static int spi_dw_core_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;
	struct spi_dw_core_priv *priv = container_of(misc, struct spi_dw_core_priv, misc);
	file->private_data = priv;
	return 0;
}

static ssize_t spi_dw_core_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
	struct spi_dw_core_priv *priv = file->private_data;
	u32 val;

	if (count < 4 || (*ppos & 3))
		return -EINVAL;

	val = readl(priv->base + *ppos);
	if (copy_to_user(buf, &val, 4))
		return -EFAULT;
	*ppos += 4;
	return 4;
}

static ssize_t spi_dw_core_write(struct file *file, const char __user *buf, size_t count, loff_t *ppos)
{
	struct spi_dw_core_priv *priv = file->private_data;
	u32 val;

	if (count < 4 || (*ppos & 3))
		return -EINVAL;

	if (copy_from_user(&val, buf, 4))
		return -EFAULT;
	writel(val, priv->base + *ppos);
	*ppos += 4;
	return 4;
}

static const struct file_operations spi_dw_core_fops = {
	.owner = THIS_MODULE,
	.open = spi_dw_core_open,
	.read = spi_dw_core_read,
	.write = spi_dw_core_write,
};

static void dw_spi_set_cs(struct spi_dw_core_priv *priv, bool enable, bool cs_high)
{
	RH_TRACE_FN("dw_spi_set_cs");
	if (cs_high == enable)
		writel(0x1 << 0, priv->base + DW_SPI_SER);
	if ((cs_high == enable) == 0x0)
		writel(0x0, priv->base + DW_SPI_SER);
}

static void dw_writer(struct spi_dw_core_priv *priv)
{
	u32 tx_room;
	RH_TRACE_FN("dw_writer");
	tx_room = readl(priv->base + DW_SPI_TXFLR);
}

static void dw_reader(struct spi_dw_core_priv *priv)
{
	u32 r4;
	RH_TRACE_FN("dw_reader");
	r4 = readl(priv->base + 0);
}

static void dw_spi_check_status(struct spi_dw_core_priv *priv, bool raw)
{
	u32 irq_status;
	RH_TRACE_FN("dw_spi_check_status");
	if (raw)
		irq_status = readl(priv->base + DW_SPI_RISR);
	if (raw == 0x0)
		irq_status = readl(priv->base + DW_SPI_ISR);
}

static void dw_spi_transfer_handler(struct spi_dw_core_priv *priv)
{
	u32 irq_status;
	u32 r8;
	RH_TRACE_FN("dw_spi_transfer_handler");
	irq_status = readl(priv->base + DW_SPI_ISR);
	if ((priv->rx_len == 0x0) == 0x0) {
		r8 = readl(priv->base + DW_SPI_RXFTLR);
		if (priv->rx_len <= r8)
			writel(priv->rx_len - 0x1, priv->base + DW_SPI_RXFTLR);
	}
}

static void dw_spi_irq(struct spi_dw_core_priv *priv)
{
	u32 irq_status;
	RH_TRACE_FN("dw_spi_irq");
	irq_status = readl(priv->base + DW_SPI_ISR);
}

static void dw_spi_update_config(struct spi_dw_core_priv *priv, u32 tmode, u32 ndf)
{
	RH_TRACE_FN("dw_spi_update_config");
	writel(priv->chip->cr0, priv->base + DW_SPI_CTRLR0);
	if ((tmode | DW_SPI_CTRLR0_TMOD_EPROMREAD) == DW_SPI_CTRLR0_TMOD_RO)
		writel(ndf ? (ndf - 1) : 0, priv->base + DW_SPI_CTRLR1);
	if (priv->cur_rx_sample_dly != priv->chip->rx_sample_dly)
		writel(priv->chip->rx_sample_dly, priv->base + DW_SPI_RX_SAMPLE_DLY);
}

static void dw_spi_transfer_one(struct spi_dw_core_priv *priv, u32 level)
{
	RH_TRACE_FN("dw_spi_transfer_one");
	writel(level, priv->base + DW_SPI_TXFTLR);
	writel(level - 0x1, priv->base + DW_SPI_RXFTLR);
}

static void dw_spi_exec_mem_op(struct spi_dw_core_priv *priv, int len, int ret)
{
	u32 entries;
	u32 nents;
	u32 sts;
	RH_TRACE_FN("dw_spi_exec_mem_op");
	while (len) {
		entries = readl(priv->base + DW_SPI_TXFLR);
		break;
	}
	while (len) {
		entries = readl(priv->base + DW_SPI_RXFLR);
		if (entries == 0x0)
			sts = readl(priv->base + DW_SPI_RISR);
		break;
	}
	if (ret == 0x0)
		nents = readl(priv->base + DW_SPI_TXFLR);
}

static void dw_spi_add_controller(struct spi_dw_core_priv *priv)
{
	u32 ser;
	u32 r25;
	u32 r27;
	u32 cr0;
	u32 tmp;
	int fifo = 0;
	RH_TRACE_FN("dw_spi_add_controller");
	if (priv) {
		if (priv->ver == 0x0)
			priv->ver = readl(priv->base + DW_SPI_VERSION);
		if (1 == 0x0) { // spi_controller_is_target(dws->ctlr) == 0x0
			if (priv->num_cs == 0x0) {
				writel(0xffff, priv->base + DW_SPI_SER);
				ser = readl(priv->base + DW_SPI_SER);
				writel(0x0, priv->base + DW_SPI_SER);
			}
		}
		if (priv->fifo_len == 0x0) {
			while (fifo < 0x100) {
				writel(fifo, priv->base + DW_SPI_TXFTLR);
				r25 = readl(priv->base + DW_SPI_TXFTLR);
				fifo++;
			}
			writel(0x0, priv->base + DW_SPI_TXFTLR);
		}
		if (1) { // dw_spi_ip_is(dws, PSSI)
			r27 = readl(priv->base + DW_SPI_CTRLR0);
			writel(0xffffffff, priv->base + DW_SPI_CTRLR0);
			cr0 = readl(priv->base + DW_SPI_CTRLR0);
			writel(tmp, priv->base + DW_SPI_CTRLR0);
		}
		if (priv->caps & DW_SPI_CAP_CS_OVERRIDE)
			writel(0xf, priv->base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_resume_controller(struct spi_dw_core_priv *priv)
{
	u32 ser;
	u32 r37;
	u32 r39;
	u32 cr0;
	u32 tmp;
	int fifo = 0;
	RH_TRACE_FN("dw_spi_resume_controller");
	if (priv->ver == 0x0)
		priv->ver = readl(priv->base + DW_SPI_VERSION);
	if (1 == 0x0) { // spi_controller_is_target(dws->ctlr) == 0x0
		if (priv->num_cs == 0x0) {
			writel(0xffff, priv->base + DW_SPI_SER);
			ser = readl(priv->base + DW_SPI_SER);
			writel(0x0, priv->base + DW_SPI_SER);
		}
	}
	if (priv->fifo_len == 0x0) {
		while (fifo < 0x100) {
			writel(fifo, priv->base + DW_SPI_TXFTLR);
			r37 = readl(priv->base + DW_SPI_TXFTLR);
			fifo++;
		}
		writel(0x0, priv->base + DW_SPI_TXFTLR);
	}
	if (1) { // dw_spi_ip_is(dws, PSSI)
		r39 = readl(priv->base + DW_SPI_CTRLR0);
		writel(0xffffffff, priv->base + DW_SPI_CTRLR0);
		cr0 = readl(priv->base + DW_SPI_CTRLR0);
		writel(tmp, priv->base + DW_SPI_CTRLR0);
	}
	if (priv->caps & DW_SPI_CAP_CS_OVERRIDE)
		writel(0xf, priv->base + DW_SPI_CS_OVERRIDE);
}

static int spi_dw_core_probe(struct platform_device *pdev)
{
	struct spi_dw_core_priv *priv;
	struct dw_spi_chip_data *chip;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	chip = devm_kzalloc(&pdev->dev, sizeof(*chip), GFP_KERNEL);
	if (!chip)
		return -ENOMEM;

	priv->chip = chip;
	priv->dev = &pdev->dev;
	platform_set_drvdata(pdev, priv);

	priv->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);

	RH_SET_BASE(priv->base);

	dw_spi_set_cs(priv, true, false);
	dw_writer(priv);
	dw_reader(priv);
	dw_spi_check_status(priv, true);
	dw_spi_transfer_handler(priv);
	dw_spi_irq(priv);
	dw_spi_update_config(priv, DW_SPI_CTRLR0_TMOD_RO, 1);
	dw_spi_transfer_one(priv, 16);
	dw_spi_exec_mem_op(priv, 1, 0);
	dw_spi_add_controller(priv);
	dw_spi_resume_controller(priv);

	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &spi_dw_core_fops;

	ret = misc_register(&priv->misc);
	if (ret)
		return ret;

	return 0;
}

static int spi_dw_core_remove(struct platform_device *pdev)
{
	struct spi_dw_core_priv *priv = platform_get_drvdata(pdev);
	misc_deregister(&priv->misc);
	return 0;
}

static const struct of_device_id spi_dw_core_of_match[] = {
	{ .compatible = "snps,dw-apb-ssi", },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, spi_dw_core_of_match);

static struct platform_driver spi_dw_core_driver = {
	.probe = spi_dw_core_probe,
	.remove = spi_dw_core_remove,
	.driver = {
		.name = "spi-dw-core",
		.of_match_table = spi_dw_core_of_match,
	},
};

module_platform_driver(spi_dw_core_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Synopsys DesignWare SPI Controller core driver");