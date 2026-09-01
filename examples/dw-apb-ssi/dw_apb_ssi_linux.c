#include "dw_apb_ssi_linux.h"


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
	u32 cs_high = 0;
	u32 enable = 0;
	struct { u32 chip_select[1]; } *spi = NULL;

	if ((cs_high == enable)) {
		writel((0x1 << spi->chip_select[0]), base + DW_SPI_SER);
	}
	if (((cs_high == enable) == 0x0)) {
		writel(0x0, base + DW_SPI_SER);
	}
}

static void dw_spi_check_status(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 raw = 0;
	u32 irq_status;
	u32 ret = 0;
	u32 new_mask = 0;
	struct driver_priv *dws = priv;
	struct { void *cur_msg; } *ctlr = NULL;

	if (raw) {
		irq_status = readl(base + DW_SPI_RISR);
	}
	if ((raw == 0x0)) {
		irq_status = readl(base + DW_SPI_ISR);
	}
	if (ret) {
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		u32 r6 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
		u32 r8 = readl(base + DW_SPI_ICR);
		writel(0x0, base + DW_SPI_SER);
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		if (ctlr->cur_msg) {
			struct { int status; } *cur_msg = NULL;
			cur_msg->status = ret;
		}
	}
}

static void dw_spi_transfer_handler(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 irq_status;
	u32 r13;
	u32 rxw;
	u32 new_mask = 0;
	u32 tx_room;
	u32 txw;
	struct driver_priv *dws = priv;

	irq_status = readl(base + DW_SPI_ISR);
	r13 = readl(base + DW_SPI_RXFLR);
	u32 max = r13;
	while (max--) {
		rxw = readl(base + DW_SPI_DR);
		if (dws->rx) {
			if ((dws->n_bytes == 0x1)) {
				*(u8 *)(dws->rx) = rxw;
			}
			if (((dws->n_bytes == 0x1) == 0x0)) {
				if ((dws->n_bytes == 0x2)) {
					*(u16 *)(dws->rx) = rxw;
				}
				if (((dws->n_bytes == 0x2) == 0x0)) {
					*(u32 *)(dws->rx) = rxw;
				}
			}
			dws->rx = (dws->rx + dws->n_bytes);
		}
		dws->rx_len = (dws->rx_len + -1);
	}
	if ((dws->rx_len == 0x0)) {
		u32 r20 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
	}
	if (((dws->rx_len == 0x0) == 0x0)) {
		u32 r22 = readl(base + DW_SPI_RXFTLR);
		if ((dws->rx_len <= r22)) {
			writel((dws->rx_len - 0x1), base + DW_SPI_RXFTLR);
		}
	}
	if ((irq_status & DW_SPI_INT_TXEI)) {
		tx_room = readl(base + DW_SPI_TXFLR);
		txw = 0x0;
		u32 max2 = tx_room;
		while (max2--) {
			if (dws->tx) {
				if ((dws->n_bytes == 0x1)) {
					txw = *(u8 *)(dws->tx);
				}
				if (((dws->n_bytes == 0x1) == 0x0)) {
					if ((dws->n_bytes == 0x2)) {
						txw = *(u16 *)(dws->tx);
					}
					if (((dws->n_bytes == 0x2) == 0x0)) {
						txw = *(u32 *)(dws->tx);
					}
				}
				dws->tx = (dws->tx + dws->n_bytes);
			}
			writel(txw, base + DW_SPI_DR);
			dws->tx_len = (dws->tx_len + -1);
		}
		if ((dws->tx_len == 0x0)) {
			u32 r32 = readl(base + DW_SPI_IMR);
			writel(new_mask, base + DW_SPI_IMR);
		}
	}
}

static void dw_spi_irq(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	void *ctlr = NULL;
	void *dev_id = ctlr;
	u32 irq_status;
	u32 new_mask = 0;
	struct { void *cur_msg; } *ctlr_p = dev_id;

	ctlr = dev_id;
	irq_status = readl(base + DW_SPI_ISR);
	if ((ctlr_p->cur_msg == 0x0)) {
		u32 r36 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
	}
}

static void dw_spi_update_config(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct driver_priv *dws = priv;
	struct { u32 cr0; } *chip = NULL;
	struct { u32 dfs; u32 tmode; int ndf; } *cfg = NULL;
	u32 speed_hz = 0;
	u32 clk_div = 0;
	u32 cr0 = chip->cr0;
	cr0 = (cr0 | ((cfg->dfs - 0x1) << dws->dfs_offset));
	if (1) {
		cr0 = (cr0 | ((cfg->tmode) << 0));
	}
	if (!1) {
		cr0 = (cr0 | ((cfg->tmode) << 0));
	}
	writel(cr0, base + DW_SPI_CTRLR0);
	if (((cfg->tmode == (DW_SPI_CTRLR0_TMOD_EPROMREAD || cfg->tmode)) == DW_SPI_CTRLR0_TMOD_RO)) {
		writel((cfg->ndf ? (cfg->ndf - 0x1) : 0x0), base + DW_SPI_CTRLR1);
	}
	if ((dws->current_freq != speed_hz)) {
		writel(clk_div, base + DW_SPI_BAUDR);
		dws->current_freq = speed_hz;
	}
	if ((dws->cur_rx_sample_dly != chip->rx_sample_dly)) {
		writel(chip->rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
		dws->cur_rx_sample_dly = chip->rx_sample_dly;
	}
}

static void dw_spi_transfer_one(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct driver_priv *dws = priv;
	struct { int len; void *tx_buf; void *rx_buf; int bits_per_word; int speed_hz; int effective_speed_hz; } *transfer = NULL;
	u32 new_mask = 0;
	u32 level = 0;
	u32 imask;
	struct { int value; int unit; } delay;
	int nbits = 0;
	u32 txw;
	u32 rxw;
	struct { int tmode; int dfs; int freq; } cfg = {DW_SPI_CTRLR0_TMOD_TR, transfer->bits_per_word, transfer->speed_hz};
	dws->dma_mapped = 0x0;
	dws->tx = transfer->tx_buf;
	dws->tx_len = (transfer->len / dws->n_bytes);
	dws->rx = transfer->rx_buf;
	dws->rx_len = dws->tx_len;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	transfer->effective_speed_hz = dws->current_freq;
	u32 r56 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	if ((dws->dma_mapped == 0x0)) {
		if ((dws->irq == IRQ_NOTCONNECTED)) {
			delay.unit = 0;
			while (dws->rx_len) {
				u32 tx_room = readl(base + DW_SPI_TXFLR);
				txw = 0x0;
				u32 max = tx_room;
				while (max--) {
					if (dws->tx) {
						if ((dws->n_bytes == 0x1)) {
							txw = *(u8 *)(dws->tx);
						}
						if (((dws->n_bytes == 0x1) == 0x0)) {
							if ((dws->n_bytes == 0x2)) {
								txw = *(u16 *)(dws->tx);
							}
							if (((dws->n_bytes == 0x2) == 0x0)) {
								txw = *(u32 *)(dws->tx);
							}
						}
						dws->tx = (dws->tx + dws->n_bytes);
					}
					writel(txw, base + DW_SPI_DR);
					dws->tx_len = (dws->tx_len + -1);
				}
				delay.value = (nbits * (dws->rx_len - dws->tx_len));
				u32 r69 = readl(base + DW_SPI_RXFLR);
				u32 max2 = r69;
				while (max2--) {
					rxw = readl(base + DW_SPI_DR);
					if (dws->rx) {
						if ((dws->n_bytes == 0x1)) {
							*(u8 *)(dws->rx) = rxw;
						}
						if (((dws->n_bytes == 0x1) == 0x0)) {
							if ((dws->n_bytes == 0x2)) {
								*(u16 *)(dws->rx) = rxw;
							}
							if (((dws->n_bytes == 0x2) == 0x0)) {
								*(u32 *)(dws->rx) = rxw;
							}
						}
						dws->rx = (dws->rx + dws->n_bytes);
					}
					dws->rx_len = (dws->rx_len + -1);
				}
			}
		}
	}
	writel(level, base + DW_SPI_TXFTLR);
	writel((level - 0x1), base + DW_SPI_RXFTLR);
	dws->transfer_handler = dw_spi_transfer_handler;
	imask = ((((DW_SPI_INT_TXEI | DW_SPI_INT_TXOI) | DW_SPI_INT_RXUI) | DW_SPI_INT_RXOI) | DW_SPI_INT_RXFI);
	u32 r80 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
}

static void dw_spi_handle_err(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 new_mask = 0;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	u32 r83 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	u32 r85 = readl(base + DW_SPI_ICR);
	writel(0x0, base + DW_SPI_SER);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

static void dw_spi_target_abort(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	u32 new_mask = 0;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	u32 r89 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	u32 r91 = readl(base + DW_SPI_ICR);
	writel(0x0, base + DW_SPI_SER);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

static void dw_spi_exec_mem_op(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct driver_priv *dws = priv;
	u32 len = 0;
	u32 new_mask = 0;
	u32 ret = 0;
	u32 ns = 0;
	struct { struct { int nbytes; } cmd; struct { int dir; int nbytes; void *buf_in; } data; } *op = NULL;
	void *out = NULL;
	if ((len <= 256)) {
		out = dws->buf;
	}
	for (int i = 0; (i < op->cmd.nbytes); i++) {
	}
	dws->n_bytes = 0x1;
	dws->tx = out;
	dws->tx_len = len;
	if ((op->data.dir == 1)) {
		dws->rx = op->data.buf_in;
		dws->rx_len = op->data.nbytes;
	}
	if (((op->data.dir == 1) == 0x0)) {
		dws->rx = NULL;
		dws->rx_len = 0x0;
	}
	struct { int dfs; int tmode; int ndf; } cfg;
	cfg.dfs = 0x8;
	if ((op->data.dir == 1)) {
		cfg.tmode = DW_SPI_CTRLR0_TMOD_EPROMREAD;
		cfg.ndf = op->data.nbytes;
	}
	if (((op->data.dir == 1) == 0x0)) {
		cfg.tmode = DW_SPI_CTRLR0_TMOD_TO;
	}
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	u32 r108 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	u8 *buf = dws->tx;
	while (len--) {
		writel(*buf++, base + DW_SPI_DR);
	}
	while (len) {
		u32 entries = readl(base + DW_SPI_TXFLR);
		u32 room = entries;
		while ((room--, len--)) {
			writel(*buf++, base + DW_SPI_DR);
		}
	}
	buf = dws->rx;
	while (len) {
		u32 entries = readl(base + DW_SPI_RXFLR);
		u32 sts = 0;
		if ((entries == 0x0)) {
			sts = readl(base + DW_SPI_RISR);
		}
		u32 room = entries;
		while ((room--, len--)) {
			u32 buffer_read_0 = readl(base + DW_SPI_DR);
			*buf++ = buffer_read_0;
		}
	}
	if ((ret == 0x0)) {
		u32 nents = readl(base + DW_SPI_TXFLR);
		struct { int value; int unit; } delay;
		if ((ns <= NSEC_PER_USEC)) {
			delay.unit = 0;
			delay.value = ns;
		}
		if (((ns <= NSEC_PER_USEC) == 0x0)) {
			delay.unit = 0;
		}
		u32 retry = DW_SPI_WAIT_RETRIES;
		while ((1 && retry--)) {
			u32 __return_read_0 = readl(base + DW_SPI_SR);
		}
	}
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
}

static void dw_spi_setup(struct driver_priv *priv)
{
	void *chip = NULL;
	struct { void *controller_state; struct device dev; } *spi = NULL;
	struct driver_priv *dws = priv;
	u32 rx_sample_dly_ns = 0;
	if ((chip == 0x0)) {
		spi->controller_state = chip;
		if ((device_property_read_u32(&spi->dev, "rx-sample-delay-ns", &rx_sample_dly_ns) != 0x0)) {
			rx_sample_dly_ns = 0;
		}
	}
}

static void dw_spi_cleanup(struct driver_priv *priv)
{
	struct { void *controller_state; } *spi = NULL;
	spi->controller_state = NULL;
}

static void dw_spi_add_controller(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct driver_priv *dws = priv;
	u32 new_mask = 0;
	void *ctlr = NULL;
	int ret = 0;
	dws->ctlr = ctlr;
	dws->paddr = 0;
	if (dws) {
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		u32 r133 = readl(base + DW_SPI_IMR);
		writel(new_mask, base + DW_SPI_IMR);
		u32 r135 = readl(base + DW_SPI_ICR);
		writel(0x0, base + DW_SPI_SER);
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		if ((dws->ver == 0x0)) {
			dws->ver = readl(base + DW_SPI_VERSION);
		}
		if (0) {
			dws->num_cs = 0x1;
		}
		if (!0) {
			if ((dws->num_cs == 0x0)) {
				writel(0xffff, base + DW_SPI_SER);
				u32 ser = readl(base + DW_SPI_SER);
				writel(0x0, base + DW_SPI_SER);
			}
		}
		if ((dws->fifo_len == 0x0)) {
			u32 fifo = 0x1;
			for (; (fifo < 0x100); ) {
				fifo = 0x1;
				writel(fifo, base + DW_SPI_TXFTLR);
				u32 r145 = readl(base + DW_SPI_TXFTLR);
			}
			writel(0x0, base + DW_SPI_TXFTLR);
			dws->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
		}
		if (1) {
			u32 r148 = readl(base + DW_SPI_CTRLR0);
			writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
			writel(0xffffffff, base + DW_SPI_CTRLR0);
			u32 cr0 = readl(base + DW_SPI_CTRLR0);
			writel(0, base + DW_SPI_CTRLR0);
			writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
			if (((cr0 & 0x3) == 0x0)) {
				dws->caps = (dws->caps | DW_SPI_CAP_DFS32);
			}
		}
		if (!1) {
			dws->caps = (dws->caps | DW_SPI_CAP_DFS32);
		}
		if ((dws->caps & DW_SPI_CAP_CS_OVERRIDE)) {
			writel(0xf, base + DW_SPI_CS_OVERRIDE);
		}
	}
	if (1) {
		if (dws) {
			if (1) {
				dws->mem_ops = 0;
				dws->mem_ops = 0;
				dws->mem_ops = dw_spi_exec_mem_op;
				if ((dws->max_mem_freq == 0x0)) {
					dws->max_mem_freq = dws->max_freq;
				}
			}
		}
	}
	if (0) {
	}
	if (0) {
	}
	if (0) {
	}
	if (0) {
		if (1) {
			if (1) {
				if (dws) {
					dws->regset = 0;
					dws->regset = 0;
				}
			}
		}
	}
	if (0x0) {
		if (1) {
			if (1) {
				if (dws) {
					writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
				}
			}
		}
	}
}

static void dw_spi_remove_controller(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_suspend_controller(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	writel(0x0, base + DW_SPI_BAUDR);
}

static void dw_spi_resume_controller(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct driver_priv *dws = priv;
	u32 new_mask = 0;
	writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	u32 r188 = readl(base + DW_SPI_IMR);
	writel(new_mask, base + DW_SPI_IMR);
	u32 r190 = readl(base + DW_SPI_ICR);
	writel(0x0, base + DW_SPI_SER);
	writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	if ((dws->ver == 0x0)) {
		dws->ver = readl(base + DW_SPI_VERSION);
	}
	if (0) {
		dws->num_cs = 0x1;
	}
	if (!0) {
		if ((dws->num_cs == 0x0)) {
			writel(0xffff, base + DW_SPI_SER);
			u32 ser = readl(base + DW_SPI_SER);
			writel(0x0, base + DW_SPI_SER);
		}
	}
	if ((dws->fifo_len == 0x0)) {
		u32 fifo = 0x1;
		for (; (fifo < 0x100); ) {
			fifo = 0x1;
			writel(fifo, base + DW_SPI_TXFTLR);
			u32 r200 = readl(base + DW_SPI_TXFTLR);
		}
		writel(0x0, base + DW_SPI_TXFTLR);
		dws->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
	}
	if (1) {
		u32 r203 = readl(base + DW_SPI_CTRLR0);
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		writel(0xffffffff, base + DW_SPI_CTRLR0);
		u32 cr0 = readl(base + DW_SPI_CTRLR0);
		writel(0, base + DW_SPI_CTRLR0);
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
		if (((cr0 & 0x3) == 0x0)) {
			dws->caps = (dws->caps | DW_SPI_CAP_DFS32);
		}
	}
	if (!1) {
		dws->caps = (dws->caps | DW_SPI_CAP_DFS32);
	}
	if ((dws->caps & DW_SPI_CAP_CS_OVERRIDE)) {
		writel(0xf, base + DW_SPI_CS_OVERRIDE);
	}
}

static void dw_spi_mscc_set_cs(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct { void *priv; } *dwsmmio = container_of(&priv, struct { void *priv; }, priv);
	struct { struct regmap *syscon; } *dwsmscc = dwsmmio->priv;
	u32 cs = 0;
	u32 sw_mode;
	dwsmscc = dwsmmio->priv;
	if ((cs < 0x4)) {
		sw_mode = MSCC_SPI_MST_SW_MODE_SW_PIN_CTRL_MODE;
		writel(sw_mode, base + MSCC_SPI_MST_SW_MODE);
	}
}

static void dw_spi_mscc_ocelot_init(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct { struct { void *set_cs; } dws; void *priv; } *dwsmmio = container_of(&priv, struct { struct { void *set_cs; } dws; void *priv; }, priv);
	struct { struct regmap *syscon; } *dwsmscc = dwsmmio->priv;
	writel(0x0, base + MSCC_SPI_MST_SW_MODE);
	regmap_update_bits(dwsmscc->syscon, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL, 0, 0);
	dwsmmio->dws.set_cs = dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;
}

static void dw_spi_mscc_jaguar2_init(struct driver_priv *priv)
{
	void __iomem *base = priv->base;
	struct { struct { void *set_cs; } dws; void *priv; } *dwsmmio = container_of(&priv, struct { struct { void *set_cs; } dws; void *priv; }, priv);
	struct { struct regmap *syscon; } *dwsmscc = dwsmmio->priv;
	writel(0x0, base + MSCC_SPI_MST_SW_MODE);
	regmap_update_bits(dwsmscc->syscon, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL, 0, 0);
	dwsmmio->dws.set_cs = dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;
}

static void dw_spi_sparx5_set_cs(struct driver_priv *priv)
{
	struct { void *priv; } *dwsmmio = container_of(&priv, struct { void *priv; }, priv);
	struct { struct regmap *syscon; } *dwsmscc = dwsmmio->priv;
	u32 enable = 0;
	dwsmscc = dwsmmio->priv;
	if ((enable == 0x0)) {
		regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 0);
		regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL, 0);
	}
	if (((enable == 0x0) == 0x0)) {
		regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL, 0);
		regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 0);
	}
}

static void dw_spi_mscc_sparx5_init(struct driver_priv *priv)
{
	struct { struct { void *set_cs; } dws; void *priv; } *dwsmmio = container_of(&priv, struct { struct { void *set_cs; } dws; void *priv; }, priv);
	struct { struct regmap *syscon; } *dwsmscc = dwsmmio->priv;
	char *syscon_name = (("microchip,sparx5 - cpu) - syscon"));
	struct device *dev = NULL;
	dwsmmio->dws.set_cs = dw_spi_sparx5_set_cs;
	dwsmmio->priv = dwsmscc;
}

static void dw_spi_alpine_init(struct driver_priv *priv)
{
	struct { struct { u32 caps; } dws; } *dwsmmio = container_of(&priv, struct { struct { u32 caps; } dws; }, priv);
	dwsmmio->dws.caps = DW_SPI_CAP_CS_OVERRIDE;
}

static void dw_spi_hssi_init(struct driver_priv *priv)
{
	struct { struct { u32 ip; } dws; } *dwsmmio = container_of(&priv, struct { struct { u32 ip; } dws; }, priv);
	dwsmmio->dws.ip = DW_HSSI_ID;
}

static void dw_spi_intel_init(struct driver_priv *priv)
{
	struct { struct { u32 ip; } dws; } *dwsmmio = container_of(&priv, struct { struct { u32 ip; } dws; }, priv);
	dwsmmio->dws.ip = DW_HSSI_ID;
}

static void dw_spi_mountevans_imc_init(struct driver_priv *priv)
{
	struct { struct { u32 fifo_len; } dws; } *dwsmmio = container_of(&priv, struct { struct { u32 fifo_len; } dws; }, priv);
	dwsmmio->dws.fifo_len = 0x1f;
}

static void dw_spi_canaan_k210_init(struct driver_priv *priv)
{
	struct { struct { u32 fifo_len; } dws; } *dwsmmio = container_of(&priv, struct { struct { u32 fifo_len; } dws; }, priv);
	dwsmmio->dws.fifo_len = 0x1f;
}

static void dw_spi_elba_set_cs(struct driver_priv *priv)
{
	struct { void *priv; } *dwsmmio = container_of(&priv, struct { void *priv; }, priv);
	struct regmap *syscon = dwsmmio->priv;
	u32 cs = 0;
	syscon = dwsmmio->priv;
	if ((cs < 0x2)) {
		regmap_update_bits(syscon, ELBA_SPICS_REG, 0, 0);
	}
}

static void dw_spi_elba_init(struct driver_priv *priv)
{
	struct { void *priv; struct