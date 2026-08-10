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
	writel(0x1 << 0, priv->base + DW_SPI_SER);
	writel(0x0, priv->base + DW_SPI_SER);
}

static void dw_spi_check_status(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;
	irq_status = readl(priv->base + DW_SPI_RISR);
	irq_status = readl(priv->base + DW_SPI_ISR);
}

static void dw_spi_transfer_handler(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status, tx_room;
	irq_status = readl(priv->base + DW_SPI_ISR);
	if (irq_status & DW_SPI_INT_TXEI) {
		tx_room = readl(priv->base + DW_SPI_TXFLR);
	}
}

static void dw_spi_irq(struct dw_apb_ssi_priv *priv)
{
	u32 irq_status;
	irq_status = readl(priv->base + DW_SPI_ISR);
}

static void dw_spi_update_config(struct dw_apb_ssi_priv *priv)
{
	u32 cr0 = 0;
	writel(cr0, priv->base + DW_SPI_CTRLR0);
	writel(0, priv->base + DW_SPI_CTRLR1);
	writel(0, priv->base + DW_SPI_RX_SAMPLE_DLY);
}

static void dw_spi_transfer_one(struct dw_apb_ssi_priv *priv)
{
	u32 level = 0;
	writel(level, priv->base + DW_SPI_TXFTLR);
	writel(level - 1, priv->base + DW_SPI_RXFTLR);
}

static void dw_spi_exec_mem_op(struct dw_apb_ssi_priv *priv)
{
	u32 entries, nents, sts;
	entries = readl(priv->base + DW_SPI_TXFLR);
	entries = readl(priv->base + DW_SPI_RXFLR);
	if (entries == 0) {
		sts = readl(priv->base + DW_SPI_RISR);
	}
	nents = readl(priv->base + DW_SPI_TXFLR);
	readl(priv->base + DW_SPI_SR);
}

static void dw_spi_add_controller(struct dw_apb_ssi_priv *priv)
{
	u32 ser, cr0, tmp;
	int fifo;
	u32 caps = DW_SPI_CAP_CS_OVERRIDE;

	priv->ver = readl(priv->base + DW_SPI_VERSION);
	writel(0xffff, priv->base + DW_SPI_SER);
	ser = readl(priv->base + DW_SPI_SER);
	writel(0x0, priv->base + DW_SPI_SER);

	for (fifo = 0; fifo < 0x100; fifo++) {
		writel(fifo, priv->base + DW_SPI_TXFTLR);
		readl(priv->base + DW_SPI_TXFTLR);
	}
	writel(0x0, priv->base + DW_SPI_TXFTLR);

	readl(priv->base + DW_SPI_CTRLR0);
	writel(0xffffffff, priv->base + DW_SPI_CTRLR0);
	cr0 = readl(priv->base + DW_SPI_CTRLR0);
	writel(tmp, priv->base + DW_SPI_CTRLR0);

	if (caps & DW_SPI_CAP_CS_OVERRIDE) {
		writel(0xf, priv->base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_mscc_set_cs(struct dw_apb_ssi_priv *priv)
{
	writel(8192, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_mscc_ocelot_init(struct dw_apb_ssi_priv *priv)
{
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
}

static void dw_spi_mscc_jaguar2_init(struct dw_apb_ssi_priv *priv)
{
	writel(0x0, priv->base + MSCC_SPI_MST_SW_MODE);
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

	RH_TRACE_FN("dw_spi_exec_mem_op");
	dw_spi_exec_mem_op(priv);

	RH_TRACE_FN("dw_spi_add_controller");
	dw_spi_add_controller(priv);

	RH_TRACE_FN("dw_spi_mscc_set_cs");
	dw_spi_mscc_set_cs(priv);

	RH_TRACE_FN("dw_spi_mscc_ocelot_init");
	dw_spi_mscc_ocelot_init(priv);

	RH_TRACE_FN("dw_spi_mscc_jaguar2_init");
	dw_spi_mscc_jaguar2_init(priv);

	priv->misc.name = KBUILD_MODNAME;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.fops = &dw_apb_ssi_fops;

	ret = misc_register(&priv->misc);
	if (ret)
		return ret;

	platform_set_drvdata(pdev, priv);
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