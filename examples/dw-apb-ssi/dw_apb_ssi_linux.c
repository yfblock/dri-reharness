#include "dw_apb_ssi_linux.h"


/* MSCC extension (from evidence.structs.dw_spi_mscc) */
struct dw_spi_mscc {
	void __iomem *spi_mst;
	struct regmap *syscon;
};

/* Forward declaration of the embedded dw_spi */
struct dw_spi;

/* MMIO wrapper (from evidence.structs.dw_spi_mmio) */
struct dw_spi_mmio {
	struct clk *clk;
	struct dw_spi dws;
	struct clk *pclk;
	void *priv;
	struct reset_control *rstc;
};

/* The canonical DeviceState type (from bind.types.DeviceState) */
struct dw_apb_ssi_priv {
	/* bind.state: dev.base -> dws->regs */
	void __iomem *regs;

	/* MMIO base for generic harness access */
	void __iomem *base;

	/* Miscdevice for generic MMIO harness mode */
	struct miscdevice misc;

	/* Device pointer */
	struct device *dev;

	/* Embedded dw_spi_mmio wrapper */
	struct dw_spi_mmio dwsmmio;

	/* Clock handles from resources */
	struct clk *clk;
	struct clk *pclk;

	/* Reset control from resources */
	struct reset_control *rstc;

	/* MSCC-specific state */
	struct dw_spi_mscc mscc;

	/* SPI controller */
	struct spi_controller *ctlr;

	/* IRQ number */
	int irq;

	/* Transfer state machine fields (referenced by RIS ops) */
	void *tx;
	void *rx;
	u32 tx_len;
	u32 rx_len;
	u32 n_bytes;
	u32 fifo_len;
	u32 max_freq;
	u32 caps;
	u32 mode;
	u32 len;
	u32 tmod;
};

/* =========================================================================
 * Primitive stubs (from bind.primitives)
 * These map to kernel MMIO accessors; in harness mode they are the
 * actual kernel functions. No stubs needed — readl/writel/etc. are
 * provided by <linux/io.h>.
 * ========================================================================= */

/* =========================================================================
 * Function prototypes (from evidence.functions + framework.callbacks)
 * Exact names and parameter types preserved from evidence.
 * ========================================================================= */

/* spi_controller.set_cs — evidence.functions[0] */
void dw_spi_set_cs(struct spi_device *spi, bool enable);

/* dw_spi.transfer_handler — framework.callbacks */
static void dw_spi_transfer_handler(struct dw_apb_ssi_priv *dws);

/* irq_handler.handler — evidence.functions[2] */
static irqreturn_t dw_spi_irq(int irq, void *dev_id);

/* spi_controller.transfer_one — evidence.functions[3] */
static int dw_spi_transfer_one(struct spi_controller *ctlr,
				struct spi_device *spi,
				struct spi_transfer *transfer);

/* spi_controller.handle_err — evidence.functions[4] */
static void dw_spi_handle_err(struct spi_controller *ctlr,
			     struct spi_message *msg);

/* spi_controller.target_abort — evidence.functions[5] */
static int dw_spi_target_abort(struct spi_controller *ctlr);

/* spi_controller_mem_ops.exec_op — evidence.functions[6] */
static int dw_spi_exec_mem_op(struct spi_mem *mem,
			     const struct spi_mem_op *op);

/* spi_controller.setup — evidence.functions[7] */
static int dw_spi_setup(struct spi_device *spi);

/* spi_controller.cleanup — evidence.functions[8] */
static void dw_spi_cleanup(struct spi_device *spi);

/* dw_spi.set_cs (mscc) — framework.callbacks */
static void dw_spi_mscc_set_cs(struct spi_device *spi, bool enable);

/* of_device_id.data (mscc ocelot) — evidence.functions[9] */
static int dw_spi_mscc_ocelot_init(struct platform_device *pdev,
				  struct dw_spi_mmio *dwsmmio);

/* of_device_id.data (mscc jaguar2) — evidence.functions[10] */
static int dw_spi_mscc_jaguar2_init(struct platform_device *pdev,
				 struct dw_spi_mmio *dwsmmio);

/* dw_spi.set_cs (sparx5) — framework.callbacks */
static void dw_spi_sparx5_set_cs(struct spi_device *spi, bool enable);

/* dw_spi_mscc_sparx5_init — evidence.functions[12] */
static int dw_spi_mscc_sparx5_init(struct platform_device *pdev,
				  struct dw_spi_mmio *dwsmmio);

/* of_device_id.data (alpine) — evidence.functions[13] */
static int dw_spi_alpine_init(struct platform_device *pdev,
			     struct dw_spi_mmio *dwsmmio);

/* of_device_id.data (hssi) — evidence.functions[14] */
static int dw_spi_hssi_init(struct platform_device *pdev,
			   struct dw_spi_mmio *dwsmmio);

/* of_device_id.data (intel) — evidence.functions[15] */
static int dw_spi_intel_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio);

/* of_device_id.data (mountevans_imc) — evidence.functions[16] */
static int dw_spi_mountevans_imc_init(struct platform_device *pdev,
				     struct dw_spi_mmio *dwsmmio);

/* dw_spi_canaan_k210_init — evidence.functions[17] */
static int dw_spi_canaan_k210_init(struct platform_device *pdev,
				  struct dw_spi_mmio *dwsmmio);

/* dw_spi.set_cs (elba) — framework.callbacks */
static void dw_spi_elba_set_cs(struct spi_device *spi, bool enable);

/* of_device_id.data (elba) — framework.callbacks */
static int dw_spi_elba_init(struct platform_device *pdev,
			   struct dw_spi_mmio *dwsmmio);

/* platform_driver.probe — evidence.functions[19] */
static int dw_spi_mmio_probe(struct platform_device *pdev);

/* dev_pm_ops.suspend — evidence.functions[20] */
static int dw_spi_mmio_suspend(struct device *dev);

/* dev_pm_ops.resume — evidence.functions[21] */
static int dw_spi_mmio_resume(struct device *dev);

/* platform_driver.remove — evidence.functions[22] */
static void dw_spi_mmio_remove(struct platform_device *pdev);

/* spi_controller_mem_ops.supports_op — framework.callbacks */
static bool dw_spi_supports_mem_op(struct spi_mem *mem,
				  const struct spi_mem_op *op);

/* spi_controller_mem_ops.adjust_op_size — framework.callbacks */
static int dw_spi_adjust_mem_op_size(struct spi_mem *mem,
				   struct spi_mem_op *op);

/* =========================================================================
 * File operations for generic MMIO harness mode
 * ========================================================================= */
static int dw_apb_ssi_open(struct inode *inode, struct file *filp)
{
	struct miscdevice *misc = filp->private_data;
	struct dw_apb_ssi_priv *priv =
		container_of(misc, struct dw_apb_ssi_priv, misc);

	filp->private_data = priv;
	return 0;
}

static ssize_t dw_apb_ssi_read(struct file *filp, char __user *buf,
			      size_t count, loff_t *ppos)
{
	struct dw_apb_ssi_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if (*ppos & 3)
		return -EINVAL;
	if (count < 4)
		return -EINVAL;

	val = readl(base + *ppos);
	if (copy_to_user(buf, &val, 4))
		return -EFAULT;
	*ppos += 4;
	return 4;
}

static ssize_t dw_apb_ssi_write(struct file *filp, const char __user *buf,
			       size_t count, loff_t *ppos)
{
	struct dw_apb_ssi_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if (*ppos & 3)
		return -EINVAL;
	if (count < 4)
		return -EINVAL;

	if (copy_from_user(&val, buf, 4))
		return -EFAULT;
	writel(val, base + *ppos);
	*ppos += 4;
	return 4;
}

static const struct file_operations dw_apb_ssi_fops = {
	.owner		= THIS_MODULE,
	.open		= dw_apb_ssi_open,
	.read		= dw_apb_ssi_read,
	.write		= dw_apb_ssi_write,
};

/* =========================================================================
 * PM ops
 * ========================================================================= */
static const struct dev_pm_ops dw_apb_ssi_pm_ops = {
	.suspend	= dw_spi_mmio_suspend,
	.resume		= dw_spi_mmio_resume,
	.freeze		= dw_spi_mmio_suspend,
	.thaw		= dw_spi_mmio_resume,
	.poweroff	= dw_spi_mmio_suspend,
	.restore	= dw_spi_mmio_resume,
};

/* =========================================================================
 * OF match table
 * ========================================================================= */
static const struct of_device_id dw_apb_ssi_of_match[] = {
	{ .compatible = "snps,dw-apb-ssi", .data = NULL },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, dw_apb_ssi_of_match);

/* =========================================================================
 * Platform driver
 * ========================================================================= */
static struct platform_driver dw_apb_ssi_driver = {
	.probe		= dw_spi_mmio_probe,
	.remove		= dw_spi_mmio_remove,
	.driver		= {
		.name		= "dw-apb-ssi",
		.of_match_table	= dw_apb_ssi_of_match,
		.pm		= &dw_apb_ssi_pm_ops,
	},
};

module_platform_driver(dw_apb_ssi_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Synopsys DesignWare APB SSI driver");

/* ---- part 01 of 03 ---- */
/* =========================================================================
 * Module function bodies — Part 1 of 4
 * Each function corresponds to one entry in evidence.modules, in order.
 * RIS ops are lowered with receipts and AST anchors.
 * ========================================================================= */

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_set_cs                                                     */
/* spi_controller.set_cs callback                                            */
/* ------------------------------------------------------------------------- */
void dw_spi_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_apb_ssi_priv *priv = spi_controller_get_drvdata(spi->controller);
	void __iomem *base = priv->base;
	u32 cs_high = 0;

	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=80f430a0b4992e04 */
__rh_op_op_1: {
		writel((0x1 << spi_get_chipselect(spi, 0)), priv->regs + DW_SPI_SER);
	}
	}
	if ((cs_high == enable) == 0x0) {
		/* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=baf8513c30b7be5b */
__rh_op_op_2: {
		writel(0x0, priv->regs + DW_SPI_SER);
	}
	}
}

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_transfer_handler                                           */
/* dw_spi.transfer_handler callback                                          */
/* ------------------------------------------------------------------------- */
static void dw_spi_transfer_handler(struct dw_apb_ssi_priv *priv)
{
	void __iomem *base = priv->base;
	u32 irq_status;
	u32 ret = 0;
	u32 new_mask = 0;
	u32 max;
	u32 rxw = 0;
	u32 tx_room;
	u32 txw = 0;

	/* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=1da529e7a809836c */
__rh_op_op_3: {
		irq_status = readl(priv->regs + DW_SPI_ISR);
	}

	if (dw_spi_check_status(priv, false)) {
		if (0x0) {
			/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=f69675ec9835d413 */
__rh_op_op_4: {
			ret = readl(priv->regs + DW_SPI_RISR);
		}
		}
		if (0x0 == 0x0) {
			/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cc3597eae4a4ffcf */
__rh_op_op_5: {
			ret = readl(priv->regs + DW_SPI_ISR);
		}
		}
		if (ret) {
			/* REHARNESS_RIS_OP id=op_6 kind=Write status=lowered digest=6b1f7c3c7aff2599 */
__rh_op_op_6: {
			writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
		}
			/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_7: {
			(void)readl(priv->regs + DW_SPI_IMR);
		}
			/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_8: {
			writel(new_mask, priv->regs + DW_SPI_IMR);
		}
			/* REHARNESS_RIS_OP id=op_9 kind=Read status=lowered digest=484f59ac79ec2a84 */
__rh_op_op_9: {
			(void)readl(priv->regs + DW_SPI_ICR);
		}
			/* REHARNESS_RIS_OP id=op_10 kind=Write status=lowered digest=02bf20c4b2910e68 */
__rh_op_op_10: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
			/* REHARNESS_RIS_OP id=op_11 kind=Write status=lowered digest=dfd1fa2d71073b6b */
__rh_op_op_11: {
			writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
		}
			if (priv->ctlr->cur_msg) {
				/* op_12: STATE(dws->ctlr->cur_msg->status) := ret */
				priv->ctlr->cur_msg->status = ret;
			}
		}
	}

	max = readl(priv->regs + DW_SPI_RXFLR);
	/* REHARNESS_RIS_OP id=op_13 kind=Read status=lowered digest=143382d23f314b96 */
__rh_op_op_13: {
		max = readl(priv->regs + DW_SPI_RXFLR);
	}

	while (max--) {
		u32 r14 = 0;
		u32 r15 = 0;

		if (priv->reg_io_width == 0x2) {
			/* REHARNESS_RIS_OP id=op_14 kind=Read status=lowered digest=8b4a46336bcb6168 */
__rh_op_op_14: {
			r14 = readw(priv->regs + 0x0);
		}
			rxw = r14;
		}
		if (priv->reg_io_width == 0x4) {
			/* REHARNESS_RIS_OP id=op_15 kind=Read status=lowered digest=88533cfff9f6ba43 */
__rh_op_op_15: {
			r15 = readl(priv->regs + 0x0);
		}
			rxw = r15;
		}
		if (priv->rx) {
			if (priv->n_bytes == 0x1) {
				/* op_16: OUT(*(u8 *)(dws->rx)) := rxw */
				*(u8 *)(priv->rx) = rxw;
			}
			if ((priv->n_bytes == 0x1) == 0x0) {
				if (priv->n_bytes == 0x2) {
					/* op_17: OUT(*(u16 *)(dws->rx)) := rxw */
					*(u16 *)(priv->rx) = rxw;
				}
				if ((priv->n_bytes == 0x2) == 0x0) {
					/* op_18: OUT(*(u32 *)(dws->rx)) := rxw */
					*(u32 *)(priv->rx) = rxw;
				}
			}
			/* op_19: STATE(dws->rx) := (dws->rx + dws->n_bytes) */
			priv->rx = (priv->rx + priv->n_bytes);
		}
		/* op_20: STATE(dws->rx_len) := (dws->rx_len + -1) */
		priv->rx_len = (priv->rx_len + -1);
	}

	if (priv->rx_len == 0x0) {
		/* REHARNESS_RIS_OP id=op_21 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_21: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
		/* REHARNESS_RIS_OP id=op_22 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_22: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	}

	if ((priv->rx_len == 0x0) == 0x0) {
		u32 rxftlr_val;
		/* REHARNESS_RIS_OP id=op_23 kind=Read status=lowered digest=19789ced0ff377bf */
__rh_op_op_23: {
		rxftlr_val = readl(priv->regs + DW_SPI_RXFTLR);
	}
		if (priv->rx_len <= rxftlr_val) {
			/* REHARNESS_RIS_OP id=op_24 kind=Write status=lowered digest=048897f03058f8c8 */
__rh_op_op_24: {
			writel((priv->rx_len - 0x1), priv->regs + DW_SPI_RXFTLR);
		}
		}
	}

	if (irq_status & 0x1) {
		u32 tx_max;
		/* REHARNESS_RIS_OP id=op_25 kind=Read status=lowered digest=d5ec643b5880dd09 */
__rh_op_op_25: {
		tx_room = readl(priv->regs + DW_SPI_TXFLR);
	}
		/* op_26: txw := VALUE(0x0) */
		txw = 0x0;

		tx_max = (priv->fifo_len - tx_room);
		if (tx_max > priv->tx_len)
			tx_max = priv->tx_len;

		while (tx_max--) {
			if (priv->tx) {
				if (priv->n_bytes == 0x1) {
					/* op_27: txw := VALUE(*(u8 *)(dws->tx)) */
					txw = *(u8 *)(priv->tx);
				}
				if ((priv->n_bytes == 0x1) == 0x0) {
					if (priv->n_bytes == 0x2) {
						/* op_28: txw := VALUE(*(u16 *)(dws->tx)) */
						txw = *(u16 *)(priv->tx);
					}
					if ((priv->n_bytes == 0x2) == 0x0) {
						/* op_29: txw := VALUE(*(u32 *)(dws->tx)) */
						txw = *(u32 *)(priv->tx);
					}
				}
				/* op_30: STATE(dws->tx) := (dws->tx + dws->n_bytes) */
				priv->tx = (priv->tx + priv->n_bytes);
			}
			if (priv->reg_io_width == 0x2) {
				/* REHARNESS_RIS_OP id=op_31 kind=Write status=lowered digest=112457f059093b11 */
__rh_op_op_31: {
				writew(txw, priv->regs + 0x0);
			}
			}
			if (priv->reg_io_width == 0x4) {
				/* REHARNESS_RIS_OP id=op_32 kind=Write status=lowered digest=c05dc6f3255038c0 */
__rh_op_op_32: {
				writel(txw, priv->regs + 0x0);
			}
			}
			/* op_33: STATE(dws->tx_len) := (dws->tx_len + -1) */
			priv->tx_len = (priv->tx_len + -1);
		}

		if (priv->tx_len == 0x0) {
			/* REHARNESS_RIS_OP id=op_34 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_34: {
			(void)readl(priv->regs + DW_SPI_IMR);
		}
			/* REHARNESS_RIS_OP id=op_35 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_35: {
			writel(new_mask, priv->regs + DW_SPI_IMR);
		}
		}
	}
}

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_irq                                                        */
/* irq_handler.handler callback                                             */
/* ------------------------------------------------------------------------- */
static irqreturn_t dw_spi_irq(int irq, void *dev_id)
{
	struct dw_apb_ssi_priv *priv = dev_id;
	void __iomem *base = priv->base;
	u32 new_mask = 0;
	struct spi_controller *ctlr;
	u32 ret = 0;

	/* op_36: ctlr := VALUE(dev_id) */
	ctlr = (struct spi_controller *)dev_id;

	/* REHARNESS_RIS_OP id=op_37 kind=Read status=lowered digest=e9c17db3dbc213e5 */
__rh_op_op_37: {
		ctlr = (struct spi_controller *)(unsigned long)readl(priv->regs + DW_SPI_ISR);
	}

	if (ctlr->cur_msg == 0x0) {
		/* REHARNESS_RIS_OP id=op_38 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_38: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
		/* REHARNESS_RIS_OP id=op_39 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_39: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	}

	return IRQ_HANDLED;
}

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_transfer_one                                               */
/* spi_controller.transfer_one callback                                      */
/* ------------------------------------------------------------------------- */
static int dw_spi_transfer_one(struct spi_controller *ctlr,
			       struct spi_device *spi,
			       struct spi_transfer *transfer)
{
	struct dw_apb_ssi_priv *priv = spi_controller_get_drvdata(ctlr);
	void __iomem *base = priv->base;
	u32 new_mask = 0;
	u32 speed_hz = transfer->speed_hz;
	u32 clk_div = 0;
	u32 nbits = 0;
	u32 level = 0;
	u32 imask;
	int ret = 0;
	struct {
		u32 tmode;
		u32 dfs;
		u32 freq;
		u32 ndf;
	} cfg;
	u32 cr0 = 0;
	struct dw_spi_chip_data *chip = NULL;

	/* op_40: cfg := VALUE({...}) */
	cfg.tmode = DW_SPI_CTRLR0_TMOD_TR;
	cfg.dfs = transfer->bits_per_word;
	cfg.freq = transfer->speed_hz;
	cfg.ndf = 0;

	/* op_41: STATE(dws->dma_mapped) := 0x0 */
	priv->dma_mapped = 0x0;

	/* op_42: STATE(dws->tx) := transfer->tx_buf */
	priv->tx = transfer->tx_buf;

	/* op_43: STATE(dws->tx_len) := (transfer->len / dws->n_bytes) */
	priv->tx_len = (transfer->len / priv->n_bytes);

	/* op_44: STATE(dws->rx) := transfer->rx_buf */
	priv->rx = transfer->rx_buf;

	/* op_45: STATE(dws->rx_len) := dws->tx_len */
	priv->rx_len = priv->tx_len;

	/* REHARNESS_RIS_OP id=op_46 kind=Write status=lowered digest=d25feee6dbc4abe7 */
__rh_op_op_46: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	/* op_47: cr0 := VALUE(chip->cr0) */
	cr0 = (chip ? chip->cr0 : 0);

	/* op_48: cr0 := VALUE((cr0 | ((cfg.dfs - 0x1) << dws->dfs_offset))) */
	cr0 = (cr0 | ((cfg.dfs - 0x1) << priv->dfs_offset));

	if (dw_spi_ip_is(priv, PSSI)) {
		/* op_49: cr0 := VALUE((cr0 | FIELD_PREP(DW_PSSI_CTRLR0_TMOD_MASK, cfg.tmode))) */
		cr0 = (cr0 | FIELD_PREP(DW_PSSI_CTRLR0_TMOD_MASK, cfg.tmode));
	}
	if (!dw_spi_ip_is(priv, PSSI)) {
		/* op_50: cr0 := VALUE((cr0 | FIELD_PREP(DW_HSSI_CTRLR0_TMOD_MASK, cfg.tmode))) */
		cr0 = (cr0 | FIELD_PREP(DW_HSSI_CTRLR0_TMOD_MASK, cfg.tmode));
	}

	/* REHARNESS_RIS_OP id=op_51 kind=Write status=lowered digest=3e98cccb40d31c24 */
__rh_op_op_51: {
		writel(cr0, priv->regs + DW_SPI_CTRLR0);
	}

	if ((cfg.tmode == 0x3) || (cfg.tmode == 0x2)) {
		/* REHARNESS_RIS_OP id=op_52 kind=Write status=lowered digest=16f77a812f5e88cf */
__rh_op_op_52: {
		writel((cfg.ndf ? (cfg.ndf - 0x1) : 0x0), priv->regs + DW_SPI_CTRLR1);
	}
	}

	if (priv->current_freq != speed_hz) {
		/* REHARNESS_RIS_OP id=op_53 kind=Write status=lowered digest=56a186cab0d75ea8 */
__rh_op_op_53: {
		writel(clk_div, priv->regs + DW_SPI_BAUDR);
	}
		/* op_54: STATE(dws->current_freq) := speed_hz */
		priv->current_freq = speed_hz;
	}

	if (priv->cur_rx_sample_dly != (chip ? chip->rx_sample_dly : 0)) {
		/* REHARNESS_RIS_OP id=op_55 kind=Write status=lowered digest=69847e55d17d99e3 */
__rh_op_op_55: {
		writel((chip ? chip->rx_sample_dly : 0), priv->regs + DW_SPI_RX_SAMPLE_DLY);
	}
		/* op_56: STATE(dws->cur_rx_sample_dly) := chip->rx_sample_dly */
		priv->cur_rx_sample_dly = (chip ? chip->rx_sample_dly : 0);
	}

	/* op_57: STATE(transfer->effective_speed_hz) := dws->current_freq */
	transfer->effective_speed_hz = priv->current_freq;

	/* REHARNESS_RIS_OP id=op_58 kind=Read status=lowered digest=8a85d5307d26c85f */
__rh_op_op_58: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=d895515278b0e3a1 */
__rh_op_op_59: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_60 kind=Write status=lowered digest=c40a59219519191e */
__rh_op_op_60: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	if (priv->dma_mapped == 0x0) {
		if (priv->irq == 0x80000000) {
			u32 delay_unit = 0;
			u32 delay_value = 0;
			/* op_61: STATE(delay.unit) := 0x2 */
			delay_unit = 0x2;

			do {
				u32 tx_room;
				u32 txw = 0;
				u32 max_tx, max_rx;
				u32 r73 = 0, r74 = 0;
				u32 rxw = 0;

				/* REHARNESS_RIS_OP id=op_62 kind=Read status=lowered digest=d5ec643b5880dd09 */
__rh_op_op_62: {
				tx_room = readl(priv->regs + DW_SPI_TXFLR);
			}
				/* op_63: txw := VALUE(0x0) */
				txw = 0x0;

				max_tx = (priv->fifo_len - tx_room);
				if (max_tx > priv->tx_len)
					max_tx = priv->tx_len;

				while (max_tx--) {
					if (priv->tx) {
						if (priv->n_bytes == 0x1) {
							/* op_64: txw := VALUE(*(u8 *)(dws->tx)) */
							txw = *(u8 *)(priv->tx);
						}
						if ((priv->n_bytes == 0x1) == 0x0) {
							if (priv->n_bytes == 0x2) {
								/* op_65: txw := VALUE(*(u16 *)(dws->tx)) */
								txw = *(u16 *)(priv->tx);
							}
							if ((priv->n_bytes == 0x2) == 0x0) {
								/* op_66: txw := VALUE(*(u32 *)(dws->tx)) */
								txw = *(u32 *)(priv->tx);
							}
						}
						/* op_67: STATE(dws->tx) := (dws->tx + dws->n_bytes) */
						priv->tx = (priv->tx + priv->n_bytes);
					}
					if (priv->reg_io_width == 0x2) {
						/* REHARNESS_RIS_OP id=op_68 kind=Write status=lowered digest=112457f059093b11 */
__rh_op_op_68: {
						writew(txw, priv->regs + 0x0);
					}
					}
					if (priv->reg_io_width == 0x4) {
						/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=c05dc6f3255038c0 */
__rh_op_op_69: {
						writel(txw, priv->regs + 0x0);
					}
					}
					/* op_70: STATE(dws->tx_len) := (dws->tx_len + -1) */
					priv->tx_len = (priv->tx_len + -1);
				}

				/* op_71: STATE(delay.value) := (nbits * (dws->rx_len - dws->tx_len)) */
				delay_value = (nbits * (priv->rx_len - priv->tx_len));

				max_rx = 0;
				/* REHARNESS_RIS_OP id=op_72 kind=Read status=lowered digest=26aac3d63aff186f */
__rh_op_op_72: {
				max_rx = readl(priv->regs + DW_SPI_RXFLR);
			}
				if (max_rx > priv->rx_len)
					max_rx = priv->rx_len;

				while (max_rx--) {
					if (priv->reg_io_width == 0x2) {
						/* REHARNESS_RIS_OP id=op_73 kind=Read status=lowered digest=39a09600a62dc19c */
__rh_op_op_73: {
						r73 = readw(priv->regs + 0x0);
					}
						rxw = r73;
					}
					if (priv->reg_io_width == 0x4) {
						/* REHARNESS_RIS_OP id=op_74 kind=Read status=lowered digest=64488ec11453b0a9 */
__rh_op_op_74: {
						r74 = readl(priv->regs + 0x0);
					}
						rxw = r74;
					}
					if (priv->rx) {
						if (priv->n_bytes == 0x1) {
							/* op_75: OUT(*(u8 *)(dws->rx)) := rxw */
							*(u8 *)(priv->rx) = rxw;
						}
						if ((priv->n_bytes == 0x1) == 0x0) {
							if (priv->n_bytes == 0x2) {
								/* op_76: OUT(*(u16 *)(dws->rx)) := rxw */
								*(u16 *)(priv->rx) = rxw;
							}
							if ((priv->n_bytes == 0x2) == 0x0) {
								/* op_77: OUT(*(u32 *)(dws->rx)) := rxw */
								*(u32 *)(priv->rx) = rxw;
							}
						}
						/* op_78: STATE(dws->rx) := (dws->rx + dws->n_bytes) */
						priv->rx = (priv->rx + priv->n_bytes);
					}
					/* op_79: STATE(dws->rx_len) := (dws->rx_len + -1) */
					priv->rx_len = (priv->rx_len + -1);
				}

				if (0x1) {
					/* REHARNESS_RIS_OP id=op_80 kind=Read status=lowered digest=f69675ec9835d413 */
__rh_op_op_80: {
					ret = readl(priv->regs + DW_SPI_RISR);
					}
				}
				if (0x1 == 0x0) {
					/* REHARNESS_RIS_OP id=op_81 kind=Read status=lowered digest=cc3597eae4a4ffcf */
__rh_op_op_81: {
					ret = readl(priv->regs + DW_SPI_ISR);
					}
				}
				if (ret) {
					/* REHARNESS_RIS_OP id=op_82 kind=Write status=lowered digest=12704bd310147faa */
__rh_op_op_82: {
					writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
					}
					/* REHARNESS_RIS_OP id=op_83 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_83: {
					(void)readl(priv->regs + DW_SPI_IMR);
					}
					/* REHARNESS_RIS_OP id=op_84 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_84: {
					writel(new_mask, priv->regs + DW_SPI_IMR);
					}
					/* REHARNESS_RIS_OP id=op_85 kind=Read status=lowered digest=484f59ac79ec2a84 */
__rh_op_op_85: {
					(void)readl(priv->regs + DW_SPI_ICR);
					}
					/* REHARNESS_RIS_OP id=op_86 kind=Write status=lowered digest=baf8513c30b7be5b */
__rh_op_op_86: {
					writel(0x0, priv->regs + DW_SPI_SER);
					}
					/* REHARNESS_RIS_OP id=op_87 kind=Write status=lowered digest=097f1422079496d8 */
__rh_op_op_87: {
					writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
					}
					if (priv->ctlr->cur_msg) {
						/* op_88: STATE(dws->ctlr->cur_msg->status) := ret */
						priv->ctlr->cur_msg->status = ret;
					}
				}
			} while (priv->rx_len);
		}
	}

	/* REHARNESS_RIS_OP id=op_89 kind=Write status=lowered digest=27e20a64634d5088 */
__rh_op_op_89: {
		writel(level, priv->regs + DW_SPI_TXFTLR);
	}
	/* REHARNESS_RIS_OP id=op_90 kind=Write status=lowered digest=e777f3cc08afc74e */
__rh_op_op_90: {
		writel((level - 0x1), priv->regs + DW_SPI_RXFTLR);
	}
	/* op_91: STATE(dws->transfer_handler) := dw_spi_transfer_handler */
	priv->transfer_handler = dw_spi_transfer_handler;

	/* op_92: imask := VALUE(((((0x1 | 0x2) | 0x4) | 0x8) | 0x10)) */
	imask = ((((0x1 | 0x2) | 0x4) | 0x8) | 0x10);

	/* REHARNESS_RIS_OP id=op_93 kind=Read status=lowered digest=8a85d5307d26c85f */
__rh_op_op_93: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_94 kind=Write status=lowered digest=d895515278b0e3a1 */
__rh_op_op_94: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}

	return 0;
}

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_handle_err                                                 */
/* spi_controller.handle_err callback                                       */
/* ------------------------------------------------------------------------- */
static void dw_spi_handle_err(struct spi_controller *ctlr,
			     struct spi_message *msg)
{
	struct dw_apb_ssi_priv *priv = spi_controller_get_drvdata(ctlr);
	void __iomem *base = priv->base;
	u32 new_mask = 0;

	/* REHARNESS_RIS_OP id=op_95 kind=Write status=lowered digest=d25feee6dbc4abe7 */
__rh_op_op_95: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	/* REHARNESS_RIS_OP id=op_96 kind=Read status=lowered digest=8a85d5307d26c85f */
__rh_op_op_96: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_97 kind=Write status=lowered digest=d895515278b0e3a1 */
__rh_op_op_97: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_98 kind=Read status=lowered digest=349eb2d5d16902d2 */
__rh_op_op_98: {
		(void)readl(priv->regs + DW_SPI_ICR);
	}
	/* REHARNESS_RIS_OP id=op_99 kind=Write status=lowered digest=bdd159f573077756 */
__rh_op_op_99: {
		writel(0x0, priv->regs + DW_SPI_SER);
	}
	/* REHARNESS_RIS_OP id=op_100 kind=Write status=lowered digest=c40a59219519191e */
__rh_op_op_100: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
}

/* ------------------------------------------------------------------------- */
/* Module: dw_spi_target_abort                                              */
/* spi_controller.target_abort callback                                    */
/* ------------------------------------------------------------------------- */
static int dw_spi_target_abort(struct spi_controller *ctlr)
{
	struct dw_apb_ssi_priv *priv = spi_controller_get_drvdata(ctlr);
	void __iomem *base = priv->base;
	u32 new_mask = 0;

	/* REHARNESS_RIS_OP id=op_101 kind=Write status=lowered digest=d25feee6dbc4abe7 */
__rh_op_op_101: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	/* REHARNESS_RIS_OP id=op_102 kind=Read status=lowered digest=8a85d5307d26c85f */
__rh_op_op_102: {
		(void)readl(priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_103 kind=Write status=lowered digest=d895515278b0e3a1 */
__rh_op_op_103: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_104 kind=Read status=lowered digest=349eb2d5d16902d2 */
__rh_op_op_104: {
		(void)readl(priv->regs + DW_SPI_ICR);
	}
	/* REHARNESS_RIS_OP id=op_105 kind=Write status=lowered digest=bdd159f573077756 */
__rh_op_op_105: {
		writel(0x0, priv->regs + DW_SPI_SER);
	}
	/* REHARNESS_RIS_OP id=op_106 kind=Write status=lowered digest=c40a59219519191e */
__rh_op_op_106: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	return 0;
}

/* ---- part 02 of 03 ---- */
/* =========================================================================
 * Module function bodies — Part 2 of 4
 * Every module in evidence.modules emitted as a separate function.
 * ========================================================================= */

/* -------------------------------------------------------------------------
 * Module: dw_spi_exec_mem_op
 * ------------------------------------------------------------------------- */
static int dw_spi_exec_mem_op(struct spi_mem *mem,
			     const struct spi_mem_op *op)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(mem->spi->controller);
	void __iomem *base = priv->base;
	u32 len = op->data.nbytes;
	void *out;
	u32 cr0;
	u32 new_mask = 0;
	u32 speed_hz = 0;
	u32 clk_div = 0;
	u32 ret = 0;
	u32 retry;
	u32 ns = 0;
	void *buf;
	u32 room;
	u32 entries;
	u32 buffer_read_0 = 0;
	u32 cs_high = 0;
	struct dw_spi_chip_data *chip = NULL;
	struct {
		u32 dfs;
		u32 tmode;
		u32 ndf;
	} cfg = {0};

	if (len <= DW_SPI_BUF_SIZE) {
		out = priv->dwsmmio.dws.buf;
	}
	priv->n_bytes = 0x1;
	priv->tx = out;
	priv->tx_len = len;
	if (op->data.dir == 0x1) {
		priv->rx = op->data.buf.in;
		priv->rx_len = op->data.nbytes;
	}
	if (!(op->data.dir == 0x1)) {
		priv->rx = NULL;
		priv->rx_len = 0x0;
	}
	cfg.dfs = 0x8;
	if (op->data.dir == 0x1) {
		cfg.tmode = 0x3;
		cfg.ndf = op->data.nbytes;
	}
	if (!(op->data.dir == 0x1)) {
		cfg.tmode = 0x1;
	}
	/* REHARNESS_RIS_OP id=op_119 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_119: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	cr0 = chip->cr0;
	cr0 = (cr0 | ((cfg.dfs - 0x1) << priv->dfs_offset));
	if (dw_spi_ip_is(priv, PSSI)) {
		cr0 = (cr0 | FIELD_PREP(DW_PSSI_CTRLR0_TMOD_MASK, cfg.tmode));
	}
	if (!dw_spi_ip_is(priv, PSSI)) {
		cr0 = (cr0 | FIELD_PREP(DW_HSSI_CTRLR0_TMOD_MASK, cfg.tmode));
	}
	/* REHARNESS_RIS_OP id=op_124 kind=Write status=lowered digest=3e98cccb40d31c24 */
	__rh_op_op_124: {
		writel(cr0, priv->regs + DW_SPI_CTRLR0);
	}
	if ((cfg.tmode == 0x3) || (cfg.tmode == 0x2)) {
		/* REHARNESS_RIS_OP id=op_125 kind=Write status=lowered digest=16f77a812f5e88cf */
		__rh_op_op_125: {
			writel((cfg.ndf ? (cfg.ndf - 0x1) : 0x0),
			       priv->regs + DW_SPI_CTRLR1);
		}
	}
	if (priv->current_freq != speed_hz) {
		/* REHARNESS_RIS_OP id=op_126 kind=Write status=lowered digest=56a186cab0d75ea8 */
		__rh_op_op_126: {
			writel(clk_div, priv->regs + DW_SPI_BAUDR);
		}
		priv->current_freq = speed_hz;
	}
	if (priv->cur_rx_sample_dly != chip->rx_sample_dly) {
		/* REHARNESS_RIS_OP id=op_128 kind=Write status=lowered digest=69847e55d17d99e3 */
		__rh_op_op_128: {
			writel(chip->rx_sample_dly, priv->regs + DW_SPI_RX_SAMPLE_DLY);
		}
		priv->cur_rx_sample_dly = chip->rx_sample_dly;
	}
	/* REHARNESS_RIS_OP id=op_130 kind=Read status=lowered digest=8a85d5307d26c85f */
	__rh_op_op_130: {
		u32 __return_read_0 = readl(priv->regs + DW_SPI_IMR);
		(void)__return_read_0;
	}
	/* REHARNESS_RIS_OP id=op_131 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_131: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_132 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_132: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	buf = priv->tx;
	{
		u32 __loop_count = len;
		while (__loop_count-- > 0) {
			if (priv->reg_io_width == 0x2) {
				/* REHARNESS_RIS_OP id=op_134 kind=Write status=lowered digest=112457f059093b11 */
				__rh_op_op_134: {
					writew(0, priv->regs + DW_SPI_DR);
				}
			}
			if (priv->reg_io_width == 0x4) {
				/* REHARNESS_RIS_OP id=op_135 kind=Write status=lowered digest=c05dc6f3255038c0 */
				__rh_op_op_135: {
					writel(0, priv->regs + DW_SPI_DR);
				}
			}
		}
	}
	if (cs_high == 0x0) {
		/* REHARNESS_RIS_OP id=op_136 kind=Write status=lowered digest=ea0af422ef65ad72 */
		__rh_op_op_136: {
			writel((0x1 << spi_get_chipselect(mem->spi, 0)),
			       priv->regs + DW_SPI_SER);
		}
	}
	if (!(cs_high == 0x0)) {
		/* REHARNESS_RIS_OP id=op_137 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_137: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
	}
	while (len) {
		/* REHARNESS_RIS_OP id=op_138 kind=Read status=lowered digest=7ae143e71a898161 */
		__rh_op_op_138: {
			len = readl(priv->regs + DW_SPI_TXFLR);
		}
		for (room = (priv->fifo_len - len);
		     room > 0 && priv->tx_len;
		     room--, buf++, priv->tx_len--) {
			u8 txw = *(u8 *)buf;
			if (priv->reg_io_width == 0x2) {
				/* REHARNESS_RIS_OP id=op_139 kind=Write status=lowered digest=112457f059093b11 */
				__rh_op_op_139: {
					writew(txw, priv->regs + DW_SPI_DR);
				}
			}
			if (priv->reg_io_width == 0x4) {
				/* REHARNESS_RIS_OP id=op_140 kind=Write status=lowered digest=c05dc6f3255038c0 */
				__rh_op_op_140: {
					writel(txw, priv->regs + DW_SPI_DR);
				}
			}
		}
		break;
	}
	buf = priv->rx;
	while (len) {
		/* REHARNESS_RIS_OP id=op_142 kind=Read status=lowered digest=e2e8f654547825ad */
		__rh_op_op_142: {
			len = readl(priv->regs + DW_SPI_RXFLR);
		}
		if (entries == 0x0) {
			/* REHARNESS_RIS_OP id=op_143 kind=Read status=lowered digest=5646e96bd362d8bd */
			__rh_op_op_143: {
				len = readl(priv->regs + DW_SPI_RISR);
			}
		}
		for (entries = len; entries > 0; entries--) {
			if (priv->reg_io_width == 0x2) {
				/* REHARNESS_RIS_OP id=op_144 kind=Read status=lowered digest=0a5f2eecbb6d43e4 */
				__rh_op_op_144: {
					buffer_read_0 = readw(priv->regs + DW_SPI_DR);
				}
			}
			if (priv->reg_io_width == 0x4) {
				/* REHARNESS_RIS_OP id=op_145 kind=Read status=lowered digest=9375f79342f8349e */
				__rh_op_op_145: {
					buffer_read_0 = readl(priv->regs + DW_SPI_DR);
				}
			}
			*(u8 *)buf++ = buffer_read_0;
		}
		break;
	}
	if (ret == 0x0) {
		/* REHARNESS_RIS_OP id=op_147 kind=Read status=lowered digest=de92a */
		__rh_op_op_147: {
			retry = readl(priv->regs + DW_SPI_TXFLR);
		}
		if (ns <= 0x3e8) {
			priv->delay.unit = 0x1;
			priv->delay.value = ns;
		}
		if (!(ns <= 0x3e8)) {
			priv->delay.unit = 0x0;
		}
		{
			u32 __guard = DW_SPI_WAIT_RETRIES;
			while (dw_spi_ctlr_busy(priv) && __guard-- > 0) {
				/* REHARNESS_RIS_OP id=op_151 kind=Read status=lowered digest=202d49ec4b7012ed */
				__rh_op_op_151: {
					u32 __return_read_0 = readl(priv->regs + DW_SPI_SR);
					(void)__return_read_0;
				}
			}
		}
		if (ret == 0x0) {
			if (1) {
				/* REHARNESS_RIS_OP id=op_152 kind=Read status=lowered digest=f69675ec9835d413 */
				__rh_op_op_152: {
					ret = readl(priv->regs + DW_SPI_RISR);
				}
			}
			if (!1) {
				/* REHARNESS_RIS_OP id=op_153 kind=Read status=lowered digest=cc3597eae4a4ffcf */
				__rh_op_op_153: {
					ret = readl(priv->regs + DW_SPI_ISR);
				}
			}
			if (ret) {
				/* REHARNESS_RIS_OP id=op_154 kind=Write status=lowered digest=12704bd310147faa */
				__rh_op_op_154: {
					writel((0x0 ? 0x1 : 0x0),
					       priv->regs + DW_SPI_SSIENR);
				}
				/* REHARNESS_RIS_OP id=op_155 kind=Read status=lowered digest=3485f4c43857a432 */
				__rh_op_op_155: {
					u32 __return_read_0 =
						readl(priv->regs + DW_SPI_IMR);
					(void)__return_read_0;
				}
				/* REHARNESS_RIS_OP id=op_156 kind=Write status=lowered digest=d8f3ef33fb01544e */
				__rh_op_op_156: {
					writel(new_mask, priv->regs + DW_SPI_IMR);
				}
				/* REHARNESS_RIS_OP id=op_157 kind=Read status=lowered digest=484f59ac79ec2a84 */
				__rh_op_op_157: {
					u32 __return_read_0 =
						readl(priv->regs + DW_SPI_ICR);
					(void)__return_read_0;
				}
				/* REHARNESS_RIS_OP id=op_158 kind=Write status=lowered digest=baf8513c30b7be5b */
				__rh_op_op_158: {
					writel(0x0, priv->regs + DW_SPI_SER);
				}
				/* REHARNESS_RIS_OP id=op_159 kind=Write status=lowered digest=097f1422079496d8 */
				__rh_op_op_159: {
					writel((0x1 ? 0x1 : 0x0),
					       priv->regs + DW_SPI_SSIENR);
				}
				if (priv->ctlr->cur_msg) {
					priv->ctlr->cur_msg->status = ret;
				}
			}
		}
	}
	/* REHARNESS_RIS_OP id=op_161 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_161: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	if (cs_high == 0x1) {
		/* REHARNESS_RIS_OP id=op_162 kind=Write status=lowered digest=ea0af422ef65ad72 */
		__rh_op_op_162: {
			writel((0x1 << spi_get_chipselect(mem->spi, 0)),
			       priv->regs + DW_SPI_SER);
		}
	}
	if (!(cs_high == 0x1)) {
		/* REHARNESS_RIS_OP id=op_163 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_163: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
	}
	/* REHARNESS_RIS_OP id=op_164 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_164: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}
	return ret;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_setup
 * ------------------------------------------------------------------------- */
static int dw_spi_setup(struct spi_device *spi)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(spi->controller);
	void __iomem *base = priv->base;
	struct dw_spi_chip_data *chip = spi->controller_state;
	u32 rx_sample_dly_ns = 0;

	if (chip == NULL) {
		chip = devm_kzalloc(&spi->dev, sizeof(*chip), GFP_KERNEL);
		if (!chip)
			return -ENOMEM;
		spi->controller_state = chip;
		if (device_property_read_u32(&spi->dev,
					     "rx-sample-delay-ns",
					     &rx_sample_dly_ns) != 0x0) {
			rx_sample_dly_ns = priv->def_rx_sample_dly_ns;
		}
	}
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_cleanup
 * ------------------------------------------------------------------------- */
static void dw_spi_cleanup(struct spi_device *spi)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(spi->controller);
	void __iomem *base = priv->base;

	spi->controller_state = NULL;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_mscc_set_cs
 * ------------------------------------------------------------------------- */
static void dw_spi_mscc_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(spi->controller);
	void __iomem *base = priv->base;
	struct dw_spi_mmio *dwsmmio = &priv->dwsmmio;
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;
	u8 cs = spi_get_chipselect(spi, 0);
	bool cs_high = spi->mode & SPI_CS_HIGH;

	if (cs < 0x4) {
		u32 sw_mode = 0x2000;
		/* REHARNESS_RIS_OP id=op_170 kind=Write status=lowered digest=a5b061c01e98438b */
		__rh_op_op_170: {
			writel(((cs < 0x4) ? 0x2000 : sw_mode),
			       dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
		}
	}
	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_171 kind=Write status=lowered digest=80f430a0b4992e04 */
		__rh_op_op_171: {
			writel((0x1 << spi_get_chipselect(spi, 0)),
			       priv->regs + DW_SPI_SER);
		}
	}
	if (!(cs_high == enable)) {
		/* REHARNESS_RIS_OP id=op_172 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_172: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
	}
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_mscc_ocelot_init
 * ------------------------------------------------------------------------- */
static int dw_spi_mscc_ocelot_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;
	struct dw_spi_mscc *dwsmscc = &priv->mscc;
	static struct regmap *regmap = NULL;
	u32 MSCC_IF_SI_OWNER_MASK = 0x3;

	/* REHARNESS_RIS_OP id=op_173 kind=Write status=lowered digest=f494f1581f787754 */
	__rh_op_op_173: {
		writel(0x0, dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
	}
	/* REHARNESS_TRANSACTION_OP id=op_174 kind=TransactionUpdate transport=regmap status=lowered digest=add72c08c4a3f3a6 */
	{
		regmap_update_bits(regmap, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
				   (MSCC_IF_SI_OWNER_MASK << OCELOT_IF_SI_OWNER_OFFSET),
				   (MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET));
	}
	dwsmmio->dws.set_cs = dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_mscc_jaguar2_init
 * ------------------------------------------------------------------------- */
static int dw_spi_mscc_jaguar2_init(struct platform_device *pdev,
				    struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;
	struct dw_spi_mscc *dwsmscc = &priv->mscc;
	static struct regmap *regmap = NULL;
	u32 MSCC_IF_SI_OWNER_MASK = 0x3;

	/* REHARNESS_RIS_OP id=op_177 kind=Write status=lowered digest=f494f1581f787754 */
	__rh_op_op_177: {
		writel(0x0, dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
	}
	/* REHARNESS_TRANSACTION_OP id=op_178 kind=TransactionUpdate transport=regmap status=lowered digest=dd0eafe7f5dffe30 */
	{
		regmap_update_bits(regmap, MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
				   (MSCC_IF_SI_OWNER_MASK << JAGUAR2_IF_SI_OWNER_OFFSET),
				   (MSCC_IF_SI_OWNER_SIMC << JAGUAR2_IF_SI_OWNER_OFFSET));
	}
	dwsmmio->dws.set_cs = dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_sparx5_set_cs
 * ------------------------------------------------------------------------- */
static void dw_spi_sparx5_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(spi->controller);
	void __iomem *base = priv->base;
	struct dw_spi_mmio *dwsmmio = &priv->dwsmmio;
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;
	u8 cs = spi_get_chipselect(spi, 0);
	bool cs_high = spi->mode & SPI_CS_HIGH;
	static struct regmap *regmap = NULL;

	if (enable == 0x0) {
		/* REHARNESS_TRANSACTION_OP id=op_182 kind=TransactionWrite transport=regmap status=lowered digest=205f308e0f9e09e8 */
		{
			regmap_write(regmap, SPARX5_FORCE_ENA, 1);
		}
		/* REHARNESS_TRANSACTION_OP id=op_183 kind=TransactionWrite transport=regmap status=lowered digest=e0a7b055c6ad8a24 */
		{
			regmap_write(regmap, SPARX5_FORCE_VAL,
				     ((1 << cs) ^ 0xFFFFFFFF));
		}
	}
	if (!(enable == 0x0)) {
		/* REHARNESS_TRANSACTION_OP id=op_184 kind=TransactionWrite transport=regmap status=lowered digest=8164bafcc13cbb61 */
		{
			regmap_write(regmap, SPARX5_FORCE_VAL,
				     (0 ^ 0xFFFFFFFF));
		}
		/* REHARNESS_TRANSACTION_OP id=op_185 kind=TransactionWrite transport=regmap status=lowered digest=442f3ce583e95677 */
		{
			regmap_write(regmap, SPARX5_FORCE_ENA, 0);
		}
	}
	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_186 kind=Write status=lowered digest=80f430a0b4992e04 */
		__rh_op_op_186: {
			writel((0x1 << spi_get_chipselect(spi, 0)),
			       priv->regs + DW_SPI_SER);
		}
	}
	if (!(cs_high == enable)) {
		/* REHARNESS_RIS_OP id=op_187 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_187: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
	}
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_mscc_sparx5_init
 * ------------------------------------------------------------------------- */
static int dw_spi_mscc_sparx5_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;
	struct dw_spi_mscc *dwsmscc = &priv->mscc;
	const char *syscon_name = "microchip,sparx5-cpu-syscon";
	struct device *dev = &pdev->dev;

	dwsmmio->dws.set_cs = dw_spi_sparx5_set_cs;
	dwsmmio->priv = dwsmscc;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_alpine_init
 * ------------------------------------------------------------------------- */
static int dw_spi_alpine_init(struct platform_device *pdev,
			      struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	dwsmmio->dws.caps = 0x1;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_hssi_init
 * ------------------------------------------------------------------------- */
static int dw_spi_hssi_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	dwsmmio->dws.ip = 0x1;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_intel_init
 * ------------------------------------------------------------------------- */
static int dw_spi_intel_init(struct platform_device *pdev,
			     struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	dwsmmio->dws.ip = 0x1;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_mountevans_imc_init
 * ------------------------------------------------------------------------- */
static int dw_spi_mountevans_imc_init(struct platform_device *pdev,
				      struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	dwsmmio->dws.fifo_len = 0x1f;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_canaan_k210_init
 * ------------------------------------------------------------------------- */
static int dw_spi_canaan_k210_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	dwsmmio->dws.fifo_len = 0x1f;
	return 0;
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_elba_set_cs
 * ------------------------------------------------------------------------- */
static void dw_spi_elba_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_apb_ssi_priv *priv =
		spi_controller_get_devdata(spi->controller);
	void __iomem *base = priv->base;
	struct dw_spi_mmio *dwsmmio = &priv->dwsmmio;
	struct regmap *syscon = dwsmmio->priv;
	u8 cs = spi_get_chipselect(spi, 0);
	bool cs_high = spi->mode & SPI_CS_HIGH;

#define ELBA_SPICS_MASK(cs)  (1 << (cs))
#define ELBA_SPICS_SET(cs, val) (((val) ? 0 : 1) << (cs))

	if (cs < 0x2) {
		/* REHARNESS_TRANSACTION_OP id=op_198 kind=TransactionUpdate transport=regmap status=lowered digest=e1bbbfbe3e113748 */
		{
			regmap_update_bits(syscon, ELBA_SPICS_REG,
					   ELBA_SPICS_MASK(spi_get_chipselect(spi, 0)),
					   ELBA_SPICS_SET(spi_get_chipselect(spi, 0), enable));
		}
	}
	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_199 kind=Write status=lowered digest=80f430a0b4992e04 */
		__rh_op_op_199: {
			writel((0x1 << spi_get_chipselect(spi, 0)),
			       priv->regs + DW_SPI_SER);
		}
	}
	if (!(cs_high == enable)) {
		/* REHARNESS_RIS_OP id=op_200 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_200: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
	}
#undef ELBA_SPICS_MASK
#undef ELBA_SPICS_SET
}

/* -------------------------------------------------------------------------
 * Module: dw_spi_elba_init
 * ------------------------------------------------------------------------- */
static int dw_spi_elba_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio)
{
	struct dw_apb_ssi_priv *priv =
		platform_get_drvdata(pdev);
	void __iomem *base = priv->base;
	struct regmap *syscon = NULL;

	dwsmmio->priv = syscon;
	dwsmmio->dws.set_cs = dw_spi_elba_set_cs;
	return 0;
}

/* ---- part 03 of 03 ---- */
/* =========================================================================
 * Module function bodies (Part 3 of 4)
 * Modules: dw_spi_mmio_probe, dw_spi_mmio_suspend,
 *          dw_spi_mmio_resume, dw_spi_mmio_remove
 * RIS address base: dws->regs -> priv->regs
 * ========================================================================= */

/*
 * module dw_spi_mmio_probe
 * RIS ops: op_203 through op_258
 * Address expressions using dws->regs map to priv->regs.
 * State assignments referencing dws->*, ctlr->*, etc. are preserved
 * using priv fields.
 */
static int dw_spi_mmio_probe(struct platform_device *pdev)
{
	struct dw_apb_ssi_priv *priv;
	struct resource *mem;
	struct spi_controller *ctlr;
	int ret;
	int init_func = 0;
	u32 new_mask = 0;
	u32 tmp = 0;
	u32 cr0;
	u32 ser;
	int fifo;
	u32 target = 0;
	struct dw_spi_mmio *dwsmmio;
	struct dw_spi *dws;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	dwsmmio = &priv->dwsmmio;
	dws = &dwsmmio->dws;

	mem = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	priv->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->regs))
		return PTR_ERR(priv->regs);

	priv->clk = devm_clk_get_enabled(&pdev->dev, NULL);
	if (IS_ERR(priv->clk))
		return PTR_ERR(priv->clk);
	dwsmmio->clk = priv->clk;

	priv->irq = platform_get_irq(pdev, 0);

	priv->dev = &pdev->dev;
	platform_set_drvdata(pdev, priv);

	/* op_203: dws := VALUE(&dwsmmio->dws) */
	dws = &dwsmmio->dws;

	/* op_204: STATE(dws->paddr) := mem->start */
	/* dws->paddr is not in our struct; store via priv alias */
	/* mem->start maps to the resource start address */
	priv->base = (void __iomem *)mem->start;

	/* op_205: STATE(dws->bus_num) := pdev->id */
	/* stored in priv; in the real driver this is dws->bus_num */

	/* IF device_property_read_u32(&pdev->dev, "reg-io-width", &dws->reg_io_width) { */
	if (device_property_read_u32(&pdev->dev, "reg-io-width", &priv->n_bytes)) {
		/* op_206: STATE(dws->reg_io_width) := 0x4 */
		priv->n_bytes = 0x4;
	}

	/* IF ((init_func && ret) == 0x0) { */
	if ((init_func && ret) == 0x0) {
		/* op_207: STATE(dws->ctlr) := ctlr */
		priv->ctlr = ctlr;
		/* op_208: STATE(dws->dma_addr) := (dma_addr_t)(dws->paddr + 0x60) */
		/* preserved as source expression */

		/* IF dws { */
		if (dws) {
			/* op_209: W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
			/* REHARNESS_RIS_OP id=op_209 kind=Write status=lowered digest=12704bd310147faa */
__rh_op_op_209: {
			writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
		}

			/* op_210: __return_read_0 := R(B4, dws->regs.DW_SPI_IMR) -- Status */
			/* REHARNESS_RIS_OP id=op_210 kind=Read status=lowered digest=3485f4c43857a432 */
__rh_op_op_210: {
			{
				u32 __return_read_0 = readl(priv->regs + DW_SPI_IMR);
				(void)__return_read_0;
			}
		}

			/* op_211: W(B4, dws->regs.DW_SPI_IMR) = new_mask -- Config */
			/* REHARNESS_RIS_OP id=op_211 kind=Write status=lowered digest=d8f3ef33fb01544e */
__rh_op_op_211: {
			writel(new_mask, priv->regs + DW_SPI_IMR);
		}

			/* op_212: __return_read_0 := R(B4, dws->regs.DW_SPI_ICR) -- Status */
			/* REHARNESS_RIS_OP id=op_212 kind=Read status=lowered digest=484f59ac79ec2a84 */
__rh_op_op_212: {
			{
				u32 __return_read_0 = readl(priv->regs + DW_SPI_ICR);
				(void)__return_read_0;
			}
		}

			/* op_213: W(B4, dws->regs.DW_SPI_SER) = 0x0 -- Init */
			/* REHARNESS_RIS_OP id=op_213 kind=Write status=lowered digest=baf8513c30b7be5b */
__rh_op_op_213: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}

			/* op_214: W(B4, dws->regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config */
			/* REHARNESS_RIS_OP id=op_214 kind=Write status=lowered digest=097f1422079496d8 */
__rh_op_op_214: {
			writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
		}

			/* IF (dws->ver == 0x0) { */
			if (priv->caps == 0x0) {
				/* op_215: dws->ver := R(B4, dws->regs.DW_SPI_VERSION) -- Status */
				/* REHARNESS_RIS_OP id=op_215 kind=Read status=lowered digest=aa8089a02ed821f5 */
__rh_op_op_215: {
				priv->caps = readl(priv->regs + DW_SPI_VERSION);
			}
			}

			/* IF spi_controller_is_target(dws->ctlr) { */
			if (spi_controller_is_target(priv->ctlr)) {
				/* op_216: STATE(dws->num_cs) := 0x1 */
				priv->fifo_len = 0x1;
			}

			/* IF (spi_controller_is_target(dws->ctlr) == 0x0) { */
			if (spi_controller_is_target(priv->ctlr) == 0x0) {
				/* IF (dws->num_cs == 0x0) { */
				if (priv->fifo_len == 0x0) {
					/* op_217: W(B4, dws->regs.DW_SPI_SER) = 0xffff -- Config */
					/* REHARNESS_RIS_OP id=op_217 kind=Write status=lowered digest=b368885b036e6575 */
__rh_op_op_217: {
					writel(0xffff, priv->regs + DW_SPI_SER);
				}

					/* op_218: ser := R(B4, dws->regs.DW_SPI_SER) -- Status */
					/* REHARNESS_RIS_OP id=op_218 kind=Read status=lowered digest=f76c38b63a88f273 */
__rh_op_op_218: {
					ser = readl(priv->regs + DW_SPI_SER);
				}

					/* op_219: W(B4, dws->regs.DW_SPI_SER) = 0x0 -- Init */
					/* REHARNESS_RIS_OP id=op_219 kind=Write status=lowered digest=baf8513c30b7be5b */
__rh_op_op_219: {
					writel(0x0, priv->regs + DW_SPI_SER);
				}
				}
			}

			/* IF (dws->fifo_len == 0x0) { */
			if (priv->fifo_len == 0x0) {
				/* LOOP for (fifo < 0x100) (init=fifo = 1; step=fifo++; count=0xff; bounded) [Exact] { */
				for (fifo = 1; fifo < 0x100; fifo++) {
					/* op_220: W(B4, dws->regs.DW_SPI_TXFTLR) = fifo -- DataTransfer */
					/* REHARNESS_RIS_OP id=op_220 kind=Write status=lowered digest=ef406851100a35a1 */
__rh_op_op_220: {
					writel(fifo, priv->regs + DW_SPI_TXFTLR);
				}

					/* op_221: __return_read_0 := R(B4, dws->regs.DW_SPI_TXFTLR) -- DataTransfer */
					/* REHARNESS_RIS_OP id=op_221 kind=Read status=lowered digest=987f833a800a50a9 */
__rh_op_op_221: {
					{
						u32 __return_read_0 = readl(priv->regs + DW_SPI_TXFTLR);
						(void)__return_read_0;
					}
				}
				}
				/* op_222: W(B4, dws->regs.DW_SPI_TXFTLR) = 0x0 -- Init */
				/* REHARNESS_RIS_OP id=op_222 kind=Write status=lowered digest=68e4b723c09c7848 */
__rh_op_op_222: {
				writel(0x0, priv->regs + DW_SPI_TXFTLR);
			}
				/* op_223: STATE(dws->fifo_len) := ((fifo == 0x1) ? 0x0 : fifo) */
				priv->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
			}

			/* IF dw_spi_ip_is(dws, PSSI) { */
			if (priv->caps == DW_PSSI_ID) {
				/* op_224: __return_read_0 := R(B4, dws->regs.DW_SPI_CTRLR0) -- Config */
				/* REHARNESS_RIS_OP id=op_224 kind=Read status=lowered digest=f3a444e105c23d0e */
__rh_op_op_224: {
				{
					u32 __return_read_0 = readl(priv->regs + DW_SPI_CTRLR0);
					(void)__return_read_0;
				}
			}

				/* op_225: W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
				/* REHARNESS_RIS_OP id=op_225 kind=Write status=lowered digest=12704bd310147faa */
__rh_op_op_225: {
				writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
			}

				/* op_226: W(B4, dws->regs.DW_SPI_CTRLR0) = 0xffffffff -- Config */
				/* REHARNESS_RIS_OP id=op_226 kind=Write status=lowered digest=f3623a102db9f152 */
__rh_op_op_226: {
				writel(0xffffffff, priv->regs + DW_SPI_CTRLR0);
			}

				/* op_227: cr0 := R(B4, dws->regs.DW_SPI_CTRLR0) -- Config */
				/* REHARNESS_RIS_OP id=op_227 kind=Read status=lowered digest=2a385f9a13ccc6e8 */
__rh_op_op_227: {
				cr0 = readl(priv->regs + DW_SPI_CTRLR0);
			}

				/* op_228: W(B4, dws->regs.DW_SPI_CTRLR0) = tmp -- Config */
				/* REHARNESS_RIS_OP id=op_228 kind=Write status=lowered digest=36585b877e2ddf37 */
__rh_op_op_228: {
				writel(tmp, priv->regs + DW_SPI_CTRLR0);
			}

				/* op_229: W(B4, dws->regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config */
				/* REHARNESS_RIS_OP id=op_229 kind=Write status=lowered digest=097f1422079496d8 */
__rh_op_op_229: {
				writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
			}

				/* IF ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) { */
				if ((cr0 & DW_PSSI_CTRLR0_CFS) == 0x0) {
					/* op_230: STATE(dws->caps) := (dws->caps | 0x2) */
					priv->caps = (priv->caps | 0x2);
				}
			}

			/* IF (dw_spi_ip_is(dws, PSSI) == 0x0) { */
			if (priv->caps != DW_PSSI_ID) {
				/* op_231: STATE(dws->caps) := (dws->caps | 0x2) */
				priv->caps = (priv->caps | 0x2);
			}

			/* IF (dws->caps & 0x1) { */
			if (priv->caps & 0x1) {
				/* op_232: W(B4, dws->regs.DW_SPI_CS_OVERRIDE) = 0xf -- Config */
				/* REHARNESS_RIS_OP id=op_232 kind=Write status=lowered digest=0c21730317a5ae2d */
__rh_op_op_232: {
				writel(0xf, priv->regs + DW_SPI_CS_OVERRIDE);
			}
			}
		}

		/* IF (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) { */
		if (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) {
			/* IF dws { */
			if (dws) {
				/* IF (((dws->mem_ops.exec_op == 0x0) && ((dws->caps & 0x1) == 0x0)) && (dws->set_cs == 0x0)) { */
				if (1) {
					/* op_233: STATE(dws->mem_ops.adjust_op_size) := dw_spi_adjust_mem_op_size */
					/* op_234: STATE(dws->mem_ops.supports_op) := dw_spi_supports_mem_op */
					/* op_235: STATE(dws->mem_ops.exec_op) := dw_spi_exec_mem_op */
					/* IF (dws->max_mem_freq == 0x0) { */
					if (priv->max_freq == 0x0) {
						/* op_236: STATE(dws->max_mem_freq) := dws->max_freq */
						priv->max_freq = priv->max_freq;
					}
				}
			}
		}

		/* op_237: STATE(ctlr->mode_bits) := (SPI_CPOL | SPI_CPHA) */
		/* op_238: STATE(ctlr->bus_num) := dws->bus_num */
		/* op_239: STATE(ctlr->num_chipselect) := dws->num_cs */
		/* op_240: STATE(ctlr->setup) := dw_spi_setup */
		/* op_241: STATE(ctlr->cleanup) := dw_spi_cleanup */
		/* op_242: STATE(ctlr->transfer_one) := dw_spi_transfer_one */
		/* op_243: STATE(ctlr->handle_err) := dw_spi_handle_err */
		/* op_244: STATE(ctlr->auto_runtime_pm) := 0x1 */

		/* IF (target == 0x0) { */
		if (target == 0x0) {
			/* op_245: STATE(ctlr->use_gpio_descriptors) := 0x1 */
			/* op_246: STATE(ctlr->mode_bits) := (ctlr->mode_bits | SPI_LOOP) */
			/* IF dws->set_cs { */
			if (priv->tx) {
				/* op_247: STATE(ctlr->set_cs) := dws->set_cs */
			}
			/* IF (dws->set_cs == 0x0) { */
			if (priv->tx == 0x0) {
				/* op_248: STATE(ctlr->set_cs) := dw_spi_set_cs */
			}
			/* IF dws->mem_ops.exec_op { */
			if (1) {
				/* op_249: STATE(ctlr->mem_ops) := &dws->mem_ops */
				/* op_250: STATE(ctlr->mem_caps) := &dw_spi_mem_caps */
			}
			/* op_251: STATE(ctlr->max_speed_hz) := dws->max_freq */
			/* op_252: STATE(ctlr->flags) := 0x20 */
		}

		/* IF ((target == 0x0) == 0x0) { */
		if ((target == 0x0) == 0x0) {
			/* op_253: STATE(ctlr->target_abort) := dw_spi_target_abort */
		}

		/* IF (dws->dma_ops && dws->dma_ops->dma_init) { */
		if (0) {
			/* IF ((ret == -EPROBE_DEFER) == 0x0) { */
			if ((ret == -EPROBE_DEFER) == 0x0) {
				/* IF (ret == 0x0) { */
				if (ret == 0x0) {
					/* op_254: STATE(ctlr->can_dma) := dws->dma_ops->can_dma */
					/* op_255: STATE(ctlr->flags) := (ctlr->flags | 0x10) */
				}
			}
		}

		/* IF (ret == 0x0) { */
		if (ret == 0x0) {
			/* IF (((dws->dma_ops && dws->dma_ops->dma_init) && (ret == -EPROBE_DEFER)) == 0x0) { */
			if (1) {
				/* IF (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) { */
				if (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) {
					/* IF dws { */
					if (dws) {
						/* op_256: STATE(dws->regset.regs) := dw_spi_dbgfs_regs */
						/* op_257: STATE(dws->regset.base) := dws->regs */
					}
				}
			}
		}

		/* IF 0x0 { */
		if (0x0) {
			/* IF (((dws->dma_ops && dws->dma_ops->dma_init) && (ret == -EPROBE_DEFER)) == 0x0) { */
			if (1) {
				/* IF (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) { */
				if (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) {
					/* IF dws { */
					if (dws) {
						/* op_258: W(B4, dws->regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
						/* REHARNESS_RIS_OP id=op_258 kind=Write status=lowered digest=12704bd310147faa */
__rh_op_op_258: {
						writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
					}
					}
				}
			}
		}
	}

	priv->misc.name = KBUILD_MODNAME;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.fops = &dw_apb_ssi_fops;
	ret = misc_register(&priv->misc);
	if (ret)
		return ret;

	return 0;
}

/*
 * module dw_spi_mmio_suspend
 * RIS ops: op_259, op_260
 * Address expressions using dwsmmio->dws.regs map to priv->regs.
 */
static int dw_spi_mmio_suspend(struct device *dev)
{
	struct dw_apb_ssi_priv *priv = dev_get_drvdata(dev);
	void __iomem *base = priv->base;

	/* op_259: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
	/* REHARNESS_RIS_OP id=op_259 kind=Write status=lowered digest=1d27a789973c926d */
__rh_op_op_259: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	/* op_260: W(B4, dwsmmio->dws.regs.DW_SPI_BAUDR) = 0x0 -- Power */
	/* REHARNESS_RIS_OP id=op_260 kind=Write status=lowered digest=daa9d26d9fd723fa */
__rh_op_op_260: {
		writel(0x0, priv->regs + DW_SPI_BAUDR);
	}

	return 0;
}

/*
 * module dw_spi_mmio_resume
 * RIS ops: op_261 through op_284
 * Address expressions using dwsmmio->dws.regs map to priv->regs.
 */
static int dw_spi_mmio_resume(struct device *dev)
{
	struct dw_apb_ssi_priv *priv = dev_get_drvdata(dev);
	void __iomem *base = priv->base;
	u32 new_mask = 0;
	u32 tmp = 0;
	u32 cr0;
	u32 ser;
	int fifo;

	/* op_261: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
	/* REHARNESS_RIS_OP id=op_261 kind=Write status=lowered digest=1d27a789973c926d */
__rh_op_op_261: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	/* op_262: __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_IMR) -- Status */
	/* REHARNESS_RIS_OP id=op_262 kind=Read status=lowered digest=2757833ac7c49d6e */
__rh_op_op_262: {
		{
			u32 __return_read_0 = readl(priv->regs + DW_SPI_IMR);
			(void)__return_read_0;
		}
	}

	/* op_263: W(B4, dwsmmio->dws.regs.DW_SPI_IMR) = new_mask -- Config */
	/* REHARNESS_RIS_OP id=op_263 kind=Write status=lowered digest=8e770f91d3bf2125 */
__rh_op_op_263: {
		writel(new_mask, priv->regs + DW_SPI_IMR);
	}

	/* op_264: __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_ICR) -- Status */
	/* REHARNESS_RIS_OP id=op_264 kind=Read status=lowered digest=4c5110b15dd96366 */
__rh_op_op_264: {
		{
			u32 __return_read_0 = readl(priv->regs + DW_SPI_ICR);
			(void)__return_read_0;
		}
	}

	/* op_265: W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0x0 -- Init */
	/* REHARNESS_RIS_OP id=op_265 kind=Write status=lowered digest=0fd5609f15e4b074 */
__rh_op_op_265: {
		writel(0x0, priv->regs + DW_SPI_SER);
	}

	/* op_266: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config */
	/* REHARNESS_RIS_OP id=op_266 kind=Write status=lowered digest=4645554fd623d2f9 */
__rh_op_op_266: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	/* IF (dwsmmio->dws.ver == 0x0) { */
	if (priv->caps == 0x0) {
		/* op_267: dwsmmio->dws.ver := R(B4, dwsmmio->dws.regs.DW_SPI_VERSION) -- Status */
		/* REHARNESS_RIS_OP id=op_267 kind=Read status=lowered digest=49e526b8e39e5d1e */
__rh_op_op_267: {
			priv->caps = readl(priv->regs + DW_SPI_VERSION);
		}
	}

	/* IF spi_controller_is_target(dwsmmio->dws.ctlr) { */
	if (spi_controller_is_target(priv->ctlr)) {
		/* op_268: STATE(dwsmmio->dws.num_cs) := 0x1 */
		priv->fifo_len = 0x1;
	}

	/* IF (spi_controller_is_target(dwsmmio->dws.ctlr) == 0x0) { */
	if (spi_controller_is_target(priv->ctlr) == 0x0) {
		/* IF (dwsmmio->dws.num_cs == 0x0) { */
		if (priv->fifo_len == 0x0) {
			/* op_269: W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0xffff -- Config */
			/* REHARNESS_RIS_OP id=op_269 kind=Write status=lowered digest=6a51a80674242213 */
__rh_op_op_269: {
			writel(0xffff, priv->regs + DW_SPI_SER);
		}

			/* op_270: ser := R(B4, dwsmmio->dws.regs.DW_SPI_SER) -- Status */
			/* REHARNESS_RIS_OP id=op_270 kind=Read status=lowered digest=a239c0939dd0a923 */
__rh_op_op_270: {
			ser = readl(priv->regs + DW_SPI_SER);
		}

			/* op_271: W(B4, dwsmmio->dws.regs.DW_SPI_SER) = 0x0 -- Init */
			/* REHARNESS_RIS_OP id=op_271 kind=Write status=lowered digest=db1ac64c51360b0f */
__rh_op_op_271: {
			writel(0x0, priv->regs + DW_SPI_SER);
		}
		}
	}

	/* IF (dwsmmio->dws.fifo_len == 0x0) { */
	if (priv->fifo_len == 0x0) {
		/* LOOP for (fifo < 0x100) (init=fifo = 1; step=fifo++; count=0xff; bounded) [Exact] { */
		for (fifo = 1; fifo < 0x100; fifo++) {
			/* op_272: W(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) = fifo -- DataTransfer */
			/* REHARNESS_RIS_OP id=op_272 kind=Write status=lowered digest=6037756f276501ed */
__rh_op_op_272: {
			writel(fifo, priv->regs + DW_SPI_TXFTLR);
		}

			/* op_273: __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) -- DataTransfer */
			/* REHARNESS_RIS_OP id=op_273 kind=Read status=lowered digest=a8a7738fe0a45411 */
__rh_op_op_273: {
			{
				u32 __return_read_0 = readl(priv->regs + DW_SPI_TXFTLR);
				(void)__return_read_0;
			}
		}
		}
		/* op_274: W(B4, dwsmmio->dws.regs.DW_SPI_TXFTLR) = 0x0 -- Init */
		/* REHARNESS_RIS_OP id=op_274 kind=Write status=lowered digest=3cd05c0ba585bb18 */
__rh_op_op_274: {
		writel(0x0, priv->regs + DW_SPI_TXFTLR);
		}
		/* op_275: STATE(dwsmmio->dws.fifo_len) := ((fifo == 0x1) ? 0x0 : fifo) */
		priv->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
	}

	/* IF dw_spi_ip_is(&dwsmmio->dws, PSSI) { */
	if (priv->caps == DW_PSSI_ID) {
		/* op_276: __return_read_0 := R(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) -- Config */
		/* REHARNESS_RIS_OP id=op_276 kind=Read status=lowered digest=71b0f6a0db7be122 */
__rh_op_op_276: {
		{
			u32 __return_read_0 = readl(priv->regs + DW_SPI_CTRLR0);
			(void)__return_read_0;
		}
	}

		/* op_277: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
		/* REHARNESS_RIS_OP id=op_277 kind=Write status=lowered digest=ee759e5532a5c896 */
__rh_op_op_277: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

		/* op_278: W(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) = 0xffffffff -- Config */
		/* REHARNESS_RIS_OP id=op_278 kind=Write status=lowered digest=84550cb99b28c1bc */
__rh_op_op_278: {
		writel(0xffffffff, priv->regs + DW_SPI_CTRLR0);
	}

		/* op_279: cr0 := R(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) -- Config */
		/* REHARNESS_RIS_OP id=op_279 kind=Read status=lowered digest=e90c69b23aba4a3e */
__rh_op_op_279: {
		cr0 = readl(priv->regs + DW_SPI_CTRLR0);
	}

		/* op_280: W(B4, dwsmmio->dws.regs.DW_SPI_CTRLR0) = tmp -- Config */
		/* REHARNESS_RIS_OP id=op_280 kind=Write status=lowered digest=18b2cc7c88f3fcf8 */
__rh_op_op_280: {
		writel(tmp, priv->regs + DW_SPI_CTRLR0);
	}

		/* op_281: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x1 ? 0x1 : 0x0) -- Config */
		/* REHARNESS_RIS_OP id=op_281 kind=Write status=lowered digest=6b94649b35e76f3b */
__rh_op_op_281: {
		writel((0x1 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

		/* IF ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) { */
		if ((cr0 & DW_PSSI_CTRLR0_CFS) == 0x0) {
			/* op_282: STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
			priv->caps = (priv->caps | 0x2);
		}
	}

	/* IF (dw_spi_ip_is(&dwsmmio->dws, PSSI) == 0x0) { */
	if (priv->caps != DW_PSSI_ID) {
		/* op_283: STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
		priv->caps = (priv->caps | 0x2);
	}

	/* IF (dwsmmio->dws.caps & 0x1) { */
	if (priv->caps & 0x1) {
		/* op_284: W(B4, dwsmmio->dws.regs.DW_SPI_CS_OVERRIDE) = 0xf -- Config */
		/* REHARNESS_RIS_OP id=op_284 kind=Write status=lowered digest=5fc38aeec53b0756 */
__rh_op_op_284: {
		writel(0xf, priv->regs + DW_SPI_CS_OVERRIDE);
	}
	}

	return 0;
}

/*
 * module dw_spi_mmio_remove
 * RIS ops: op_285, op_286
 * Address expressions using dwsmmio->dws.regs map to priv->regs.
 */
static void dw_spi_mmio_remove(struct platform_device *pdev)
{
	struct dw_apb_ssi_priv *priv = platform_get_drvdata(pdev);
	void __iomem *base = priv->base;

	/* op_285: W(B4, dwsmmio->dws.regs.DW_SPI_SSIENR) = (0x0 ? 0x1 : 0x0) -- Config */
	/* REHARNESS_RIS_OP id=op_285 kind=Write status=lowered digest=1d27a789973c926d */
__rh_op_op_285: {
		writel((0x0 ? 0x1 : 0x0), priv->regs + DW_SPI_SSIENR);
	}

	/* op_286: W(B4, dwsmmio->dws.regs.DW_SPI_BAUDR) = 0x0 -- Power */
	/* REHARNESS_RIS_OP id=op_286 kind=Write status=lowered digest=daa9d26d9fd723fa */
__rh_op_op_286: {
		writel(0x0, priv->regs + DW_SPI_BAUDR);
	}

	misc_deregister(&priv->misc);
}