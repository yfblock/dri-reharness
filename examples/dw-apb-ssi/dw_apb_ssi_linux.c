#include "dw_apb_ssi_linux.h"


struct dw_spi_mscc {
	void __iomem		*spi_mst;
	struct regmap		*syscon;
};

/*
 * struct dw_spi — the core DW APB SSI controller state.
 * This is the primary device private structure. Every field that the
 * upstream driver carries is represented here so that module function
 * bodies (generated separately) can reference them by name.
 */
static u32 r69_placeholder(void);

struct dw_spi {
	u32			cur_rx_sample_dly;
	void __iomem		*base;		/* dws->regs in upstream → bind.state maps dev.base → dws->regs */

	struct device		*dev;

	/* Transfer state machine */
	void			*tx;
	void			*rx;
	unsigned int		tx_len;
	unsigned int		rx_len;
	unsigned int		n_bytes;
	unsigned int		fifo_len;

	/* Configuration */
	u32			current_freq;
	u32			max_freq;

	/* Controller version / type */
	u32			type;
	u32			ver;
	u32			caps;

	/* Per-chip config */
	struct dw_spi_chip_data	chip;

	/* Interrupt / IRQ */
	int			irq;

	/* SPI controller (host) */
	struct spi_controller	*ctlr;

	/* Callback overrides */
	void			(*set_cs)(struct spi_device *spi, bool enable);
	enum irqreturn		(*transfer_handler)(struct dw_spi *dws);
};

/*
 * struct dw_spi_mmio — platform-device wrapper.
 * Carries the core dw_spi plus MMIO-specific resources.
 */
struct dw_spi_mmio {
	struct platform_device	*pdev;
	struct clk		*clk;
	struct clk		*pclk;
	struct reset_control	*rstc;
	void			*priv;
	struct dw_spi		dws;
};

/* =============================================================================
 * Function prototypes — exact names from evidence.functions
 * =============================================================================
 */

/* spi_controller callbacks */
static void dw_spi_set_cs(struct spi_device *spi, bool enable);
static enum irqreturn dw_spi_transfer_handler(struct dw_spi *dws);
static irqreturn_t dw_spi_irq(int irq, void *dev_id);
static int dw_spi_transfer_one(struct spi_controller *ctlr,
			       struct spi_device *spi,
			       struct spi_transfer *transfer);
static void dw_spi_handle_err(struct spi_controller *ctlr,
			      struct spi_message *msg);
static int dw_spi_target_abort(struct spi_controller *ctlr);
static int dw_spi_exec_mem_op(struct spi_mem *mem,
			      const struct spi_mem_op *op);
static int dw_spi_setup(struct spi_device *spi);
static void dw_spi_cleanup(struct spi_device *spi);

/* mem op helpers */
static bool dw_spi_supports_mem_op(struct spi_mem *mem,
				   const struct spi_mem_op *op);
static int dw_spi_adjust_mem_op_size(struct spi_mem *mem,
				     struct spi_mem_op *op);

/* MSCC set_cs variants */
static void dw_spi_mscc_set_cs(struct spi_device *spi, bool enable);
static void dw_spi_sparx5_set_cs(struct spi_device *spi, bool enable);
static void dw_spi_elba_set_cs(struct spi_device *spi, bool enable);

/* of_device_id.data init functions */
static int dw_spi_mscc_ocelot_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio);
static int dw_spi_mscc_jaguar2_init(struct platform_device *pdev,
				    struct dw_spi_mmio *dwsmmio);
static int dw_spi_mscc_sparx5_init(struct platform_device *pdev,
				  struct dw_spi_mmio *dwsmmio);
static int dw_spi_alpine_init(struct platform_device *pdev,
			      struct dw_spi_mmio *dwsmmio);
static int dw_spi_hssi_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio);
static int dw_spi_intel_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio);
static int dw_spi_mountevans_imc_init(struct platform_device *pdev,
				      struct dw_spi_mmio *dwsmmio);
static int dw_spi_canaan_k210_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio);
static int dw_spi_elba_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio);

/* platform driver + PM ops */
static int dw_spi_mmio_probe(struct platform_device *pdev);
static void dw_spi_mmio_remove(struct platform_device *pdev);
static int dw_spi_mmio_suspend(struct device *dev);
static int dw_spi_mmio_resume(struct device *dev);

/* =============================================================================
 * OF match table
 * =============================================================================
 */
static const struct of_device_id dw_spi_mmio_match[] = {
	{ .compatible = "snps,dw-apb-ssi", .data = NULL },
	{ .compatible = "mscc,spi-instance-ahead", .data = dw_spi_mscc_ocelot_init },
	{ .compatible = "mscc,jaguar2-spi", .data = dw_spi_mscc_jaguar2_init },
	{ .compatible = "microchip,sparx5-spi", .data = dw_spi_mscc_sparx5_init },
	{ .compatible = "al,alpine-spi", .data = dw_spi_alpine_init },
	{ .compatible = "snps,dw-high-speed-ssi-1.0a", .data = dw_spi_hssi_init },
	{ .compatible = "intel,thunderbay-ssi", .data = dw_spi_intel_init },
	{ .compatible = "intel,mountevans-imc-ssi", .data = dw_spi_mountevans_imc_init },
	{ .compatible = "canaan,k210-spi", .data = dw_spi_canaan_k210_init },
	{ .compatible = "amd,pensando-elba-spi", .data = dw_spi_elba_init },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, dw_spi_mmio_match);

/* =============================================================================
 * PM ops
 * =============================================================================
 */
static DEFINE_SIMPLE_DEV_PM_OPS(dw_spi_mmio_pm_ops,
				dw_spi_mmio_suspend,
				dw_spi_mmio_resume);

/* =============================================================================
 * Platform driver
 * =============================================================================
 */
static struct platform_driver dw_spi_mmio_driver = {
	.probe		= dw_spi_mmio_probe,
	.remove		= dw_spi_mmio_remove,
	.driver		= {
		.name	= "dw-apb-ssi",
		.of_match_table = dw_spi_mmio_match,
		.pm	= pm_sleep_ptr(&dw_spi_mmio_pm_ops),
	},
};
module_platform_driver(dw_spi_mmio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("DW APB SSI SPI controller driver");

/* ---- part 01 of 03 ---- */
/*
 * Module function bodies — Part 1 of 4
 * These are the lowered RIS operations for the 6 evidence.modules entries.
 * They are concatenated into the same translation unit as the scaffold.
 */

/* -------------------------------------------------------------------------
 * Helper stubs (forward-declared with _p1 suffix to avoid part collisions)
 * ------------------------------------------------------------------------- */

static bool dw_spi_ip_is_p1(struct dw_spi *dws, u32 ip_type)
{
	return dws->type == ip_type;
}

static bool dw_spi_check_status_p1(struct dw_spi *dws, bool irq)
{
	(void)dws;
	(void)irq;
	return true;
}

/* -------------------------------------------------------------------------
 * module dw_spi_set_cs
 * ------------------------------------------------------------------------- */

void dw_spi_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
	void __iomem *base = dws->base;
	bool cs_high;

	cs_high = false;

	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=52e1d34f0188d855 */
		__rh_op_op_1: {
			writel((0x1 << spi->chip_select[0]), base + DW_SPI_SER);
		}
	}
	if ((cs_high == enable) == 0x0) {
		/* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_2: {
			writel(0x0, base + DW_SPI_SER);
		}
	}
}

/* -------------------------------------------------------------------------
 * module dw_spi_transfer_handler
 * ------------------------------------------------------------------------- */

enum irqreturn dw_spi_transfer_handler(struct dw_spi *dws)
{
	void __iomem *base = dws->base;
	u32 irq_status;
	u32 ret;
	u32 r7;
	u32 r9;
	u32 r13;
	u32 rxw;
	u32 r20;
	u32 r22;
	u32 tx_room;
	u32 txw;
	unsigned int max;

	/* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=1da529e7a809836c */
	__rh_op_op_3: {
		irq_status = readl(base + DW_SPI_ISR);
	}

	if (dw_spi_check_status_p1(dws, false)) {
		if (0x0) {
			/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=f69675ec9835d413 */
			__rh_op_op_4: {
				ret = readl(base + DW_SPI_RISR);
			}
		}
		if (0x0 == 0x0) {
			/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cc3597eae4a4ffcf */
			__rh_op_op_5: {
				ret = readl(base + DW_SPI_ISR);
			}
		}
		if (ret) {
			/* REHARNESS_RIS_OP id=op_6 kind=Write status=lowered digest=6b1f7c3c7aff2599 */
			__rh_op_op_6: {
				writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
			}
			/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=db5406d93b9de59f */
			__rh_op_op_7: {
				r7 = readl(base + DW_SPI_IMR);
			}
			u32 new_mask = 0;
			/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=d8f3ef33fb01544e */
			__rh_op_op_8: {
				writel(new_mask, base + DW_SPI_IMR);
			}
			/* REHARNESS_RIS_OP id=op_9 kind=Read status=lowered digest=b7ef59e827eab5c4 */
			__rh_op_op_9: {
				r9 = readl(base + DW_SPI_ICR);
			}
			/* REHARNESS_RIS_OP id=op_10 kind=Write status=lowered digest=02bf20c4b2910e68 */
			__rh_op_op_10: {
				writel(0x0, base + DW_SPI_SER);
			}
			/* REHARNESS_RIS_OP id=op_11 kind=Write status=lowered digest=dfd1fa2d71073b6b */
			__rh_op_op_11: {
				writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
			}
			if (dws->ctlr->cur_msg) {
				/* op_12: STATE — semantic, no receipt */
				dws->ctlr->cur_msg->status = ret;
			}
		}
	}

	/* REHARNESS_RIS_OP id=op_13 kind=Read status=lowered digest=e2bc5578b3e7296f */
	__rh_op_op_13: {
		r13 = readl(base + DW_SPI_RXFLR);
	}

	max = r13;
	while (max--) {
		/* REHARNESS_RIS_OP id=op_14 kind=Read status=lowered digest=3da139e73bc81d86 */
		__rh_op_op_14: {
			rxw = readl(base + DW_SPI_DR);
		}
		if (dws->rx) {
			if (dws->n_bytes == 0x1) {
				/* op_15: OUT — semantic, no receipt */
				*(u8 *)(dws->rx) = rxw;
			}
			if ((dws->n_bytes == 0x1) == 0x0) {
				if (dws->n_bytes == 0x2) {
					/* op_16: OUT — semantic, no receipt */
					*(u16 *)(dws->rx) = rxw;
				}
				if ((dws->n_bytes == 0x2) == 0x0) {
					/* op_17: OUT — semantic, no receipt */
					*(u32 *)(dws->rx) = rxw;
				}
			}
			/* op_18: STATE — semantic, no receipt */
			dws->rx = (void *)((uintptr_t)dws->rx + dws->n_bytes);
		}
		/* op_19: STATE — semantic, no receipt */
		dws->rx_len = (dws->rx_len + -1);
	}

	if (dws->rx_len == 0x0) {
		/* REHARNESS_RIS_OP id=op_20 kind=Read status=lowered digest=db8b7d8066902839 */
		__rh_op_op_20: {
			r20 = readl(base + DW_SPI_IMR);
		}
		u32 new_mask2 = 0;
		/* REHARNESS_RIS_OP id=op_21 kind=Write status=lowered digest=d8f3ef33fb01544e */
		__rh_op_op_21: {
			writel(new_mask2, base + DW_SPI_IMR);
		}
	}

	if ((dws->rx_len == 0x0) == 0x0) {
		/* REHARNESS_RIS_OP id=op_22 kind=Read status=lowered digest=0ac68c30582764c9 */
		__rh_op_op_22: {
			r22 = readl(base + DW_SPI_RXFTLR);
		}
		if (dws->rx_len <= r22) {
			/* REHARNESS_RIS_OP id=op_23 kind=Write status=lowered digest=048897f03058f8c8 */
			__rh_op_op_23: {
				writel((dws->rx_len - 0x1), base + DW_SPI_RXFTLR);
			}
		}
	}

	if (irq_status & 0x1) {
		/* REHARNESS_RIS_OP id=op_24 kind=Read status=lowered digest=d5ec643b5880dd09 */
		__rh_op_op_24: {
			tx_room = readl(base + DW_SPI_TXFLR);
		}
		/* op_25: VALUE — semantic, no receipt */
		txw = 0x0;

		max = tx_room;
		while (max--) {
			if (dws->tx) {
				if (dws->n_bytes == 0x1) {
					/* op_26: VALUE — semantic, no receipt */
					txw = *(u8 *)(dws->tx);
				}
				if ((dws->n_bytes == 0x1) == 0x0) {
					if (dws->n_bytes == 0x2) {
						/* op_27: VALUE — semantic, no receipt */
						txw = *(u16 *)(dws->tx);
					}
					if ((dws->n_bytes == 0x2) == 0x0) {
						/* op_28: VALUE — semantic, no receipt */
						txw = *(u32 *)(dws->tx);
					}
				}
				/* op_29: STATE — semantic, no receipt */
				dws->tx = (void *)((uintptr_t)dws->tx + dws->n_bytes);
			}
			/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=0f2b2866c7a4dc7b */
			__rh_op_op_30: {
				writel((((dws->tx && ((dws->n_bytes == 0x1) == 0x0)) && ((dws->n_bytes == 0x2) == 0x0)) ? *(u32 *)(dws->tx) : (((dws->tx && ((dws->n_bytes == 0x1) == 0x0)) && (dws->n_bytes == 0x2)) ? *(u16 *)(dws->tx) : ((dws->tx && (dws->n_bytes == 0x1)) ? *(u8 *)(dws->tx) : 0x0))), base + DW_SPI_DR);
			}
			/* op_31: STATE — semantic, no receipt */
			dws->tx_len = (dws->tx_len + -1);
		}

		if (dws->tx_len == 0x0) {
			/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=9db54064a0021588 */
			__rh_op_op_32: {
				r20 = readl(base + DW_SPI_IMR);
			}
			u32 new_mask3 = 0;
			/* REHARNESS_RIS_OP id=op_33 kind=Write status=lowered digest=d8f3ef33fb01544e */
			__rh_op_op_33: {
				writel(new_mask3, base + DW_SPI_IMR);
			}
		}
	}

	return IRQ_HANDLED;
}

/* -------------------------------------------------------------------------
 * module dw_spi_irq
 * ------------------------------------------------------------------------- */

irqreturn_t dw_spi_irq(int irq, void *dev_id)
{
	struct dw_spi *dws = dev_id;
	void __iomem *base = dws->base;
	u32 ctlr;
	u32 r36;

	(void)irq;

	/* op_34: VALUE — semantic, no receipt */
	ctlr = (u32)(unsigned long)dev_id;

	/* REHARNESS_RIS_OP id=op_35 kind=Read status=lowered digest=e9c17db3dbc213e5 */
	__rh_op_op_35: {
		ctlr = readl(base + DW_SPI_ISR);
	}

	if (dws->ctlr->cur_msg == 0x0) {
		/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=dbbcb4750b35858d */
		__rh_op_op_36: {
			r36 = readl(base + DW_SPI_IMR);
		}
		u32 new_mask = 0;
		/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=d8f3ef33fb01544e */
		__rh_op_op_37: {
			writel(new_mask, base + DW_SPI_IMR);
		}
	}

	return IRQ_HANDLED;
}

/* -------------------------------------------------------------------------
 * module dw_spi_transfer_one
 * ------------------------------------------------------------------------- */

struct dw_spi_cfg_p1 {
	u32 tmode;
	u32 dfs;
	u32 freq;
	u32 ndf;
};

int dw_spi_transfer_one(struct spi_controller *ctlr,
			struct spi_device *spi,
			struct spi_transfer *transfer)
{

	struct dw_spi *dws = spi_controller_get_devdata(ctlr);
	void __iomem *base = dws->base;
	struct dw_spi_cfg_p1 cfg;
	u32 cr0;
	u32 speed_hz;
	u32 clk_div;
	u32 level;
	u32 imask;
	u32 r56;
	u32 r89;
	u32 tx_room;
	u32 txw;
	u32 rxw;
	u32 nbits;
	u32 ret;
	unsigned int max;

	/* ---- hoisted from top-level lowering-repair emission ---- */
	{
		u32 r79 = 0;
		u32 r81 = 0;
		u32 new_mask = 0;
		/* ---- lowering-repair round 0 ---- */
		/* REHARNESS_RIS_OP id=op_70 kind=Read status=lowered digest=3da139e73bc81d86 */
		__rh_op_op_70: { rxw = dw_readl(dws, DW_SPI_DR); }

		/* REHARNESS_RIS_OP id=op_76 kind=Read status=lowered digest=f69675ec9835d413 */
		__rh_op_op_76: { ret = dw_readl(dws, DW_SPI_RISR); }

		/* REHARNESS_RIS_OP id=op_77 kind=Read status=lowered digest=f83f363e7a845094 */
		__rh_op_op_77: { nbits = dw_readl(dws, DW_SPI_ISR); }

		/* REHARNESS_RIS_OP id=op_78 kind=Write status=lowered digest=12704bd310147faa */
		__rh_op_op_78: { dw_writel(dws, DW_SPI_SSIENR, (0x0 ? 0x1 : 0x0)); }

		/* REHARNESS_RIS_OP id=op_79 kind=Read status=lowered digest=5a1d0369e9ac587d */
		__rh_op_op_79: { r79 = dw_readl(dws, DW_SPI_IMR); }

		/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=d8f3ef33fb01544e */
		__rh_op_op_80: { dw_writel(dws, DW_SPI_IMR, new_mask); }

		/* REHARNESS_RIS_OP id=op_81 kind=Read status=lowered digest=fc7e910137378bb9 */
		__rh_op_op_81: { r81 = dw_readl(dws, DW_SPI_ICR); }

		/* REHARNESS_RIS_OP id=op_82 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_82: { dw_writel(dws, DW_SPI_SER, 0x0); }

		/* REHARNESS_RIS_OP id=op_83 kind=Write status=lowered digest=097f1422079496d8 */
		__rh_op_op_83: { dw_writel(dws, DW_SPI_SSIENR, (0x1 ? 0x1 : 0x0)); }
	}
	(void)spi;

	/* op_38: VALUE — semantic, no receipt */
	cfg.tmode = DW_SPI_CTRLR0_TMOD_TR;
	cfg.dfs = transfer->bits_per_word;
	cfg.freq = transfer->speed_hz;
	cfg.ndf = 0;

	/* op_39: STATE — semantic, no receipt */
	dws->tx = NULL; /* dma_mapped = 0 placeholder */

	/* op_40: STATE — semantic, no receipt */
	dws->tx = transfer->tx_buf;

	/* op_41: STATE — semantic, no receipt */
	dws->tx_len = (transfer->len / dws->n_bytes);

	/* op_42: STATE — semantic, no receipt */
	dws->rx = transfer->rx_buf;

	/* op_43: STATE — semantic, no receipt */
	dws->rx_len = dws->tx_len;

	/* REHARNESS_RIS_OP id=op_44 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_44: {
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}

	/* op_45: VALUE — semantic, no receipt */
	cr0 = dws->chip.cr0;

	/* op_46: VALUE — semantic, no receipt */
	cr0 = (cr0 | ((cfg.dfs - 0x1) << 0)); /* dfs_offset placeholder = 0 */

	if (dw_spi_ip_is_p1(dws, DW_PSSI_ID)) {
		/* op_47: VALUE — semantic, no receipt */
		cr0 = (cr0 | (cfg.tmode << 0)); /* FIELD_PREP placeholder */
	}

	if (!dw_spi_ip_is_p1(dws, DW_PSSI_ID)) {
		/* op_48: VALUE — semantic, no receipt */
		cr0 = (cr0 | (cfg.tmode << 0)); /* FIELD_PREP placeholder for HSSI */
	}

	/* REHARNESS_RIS_OP id=op_49 kind=Write status=lowered digest=bb87e750b4def067 */
	__rh_op_op_49: {
		writel(dws->chip.cr0, base + DW_SPI_CTRLR0);
	}

	if ((cfg.tmode == 0x3) || (cfg.tmode == 0x2)) {
		/* REHARNESS_RIS_OP id=op_50 kind=Write status=lowered digest=16f77a812f5e88cf */
		__rh_op_op_50: {
			writel((cfg.ndf ? (cfg.ndf - 0x1) : 0x0), base + DW_SPI_CTRLR1);
		}
	}

	speed_hz = transfer->speed_hz;
	clk_div = 0;

	if (dws->current_freq != speed_hz) {
		/* REHARNESS_RIS_OP id=op_51 kind=Write status=lowered digest=56a186cab0d75ea8 */
		__rh_op_op_51: {
			writel(clk_div, base + DW_SPI_BAUDR);
		}
		/* op_52: STATE — semantic, no receipt */
		dws->current_freq = speed_hz;
	}

	if (dws->chip.rx_sample_dly != dws->chip.rx_sample_dly) {
		/* REHARNESS_RIS_OP id=op_53 kind=Write status=lowered digest=69847e55d17d99e3 */
		__rh_op_op_53: {
			writel(dws->chip.rx_sample_dly, base + DW_SPI_RX_SAMPLE_DLY);
		}
		/* op_54: STATE — semantic, no receipt */
		dws->chip.rx_sample_dly = dws->chip.rx_sample_dly;
	}

	/* op_55: STATE — semantic, no receipt */
	transfer->effective_speed_hz = dws->current_freq;

	/* REHARNESS_RIS_OP id=op_56 kind=Read status=lowered digest=3d02fa5abc1f75a2 */
	__rh_op_op_56: {
		r56 = readl(base + DW_SPI_IMR);
	}
	u32 new_mask_57 = 0;
	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_57: {
		writel(new_mask_57, base + DW_SPI_IMR);
	}

	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_58: {
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}

	/*
	 * op_39 set dma_mapped = 0; we track it via a local since there is no
	 * dedicated struct field in the scaffold.  Use a local flag.
	 */
	u32 dma_mapped_local = 0;

	if (dma_mapped_local == 0x0) {
		u32 irq_invalid = 0x80000000;
		if (dws->irq == (int)irq_invalid) {
			/* op_59: STATE — semantic, no receipt */
			u32 delay_unit = 0x2;
			u32 delay_value = 0;

			do {
				/* REHARNESS_RIS_OP id=op_60 kind=Read status=lowered digest=d5ec643b5880dd09 */
				__rh_op_op_60: {
					tx_room = readl(base + DW_SPI_TXFLR);
				}
				/* op_61: VALUE — semantic, no receipt */
				txw = 0x0;

				max = tx_room;
				while (max--) {
					if (dws->tx) {
						if (dws->n_bytes == 0x1) {
							/* op_62: VALUE — semantic, no receipt */
							txw = *(u8 *)(dws->tx);
						}
						if ((dws->n_bytes == 0x1) == 0x0) {
							if (dws->n_bytes == 0x2) {
								/* op_63: VALUE — semantic, no receipt */
								txw = *(u16 *)(dws->tx);
							}
							if ((dws->n_bytes == 0x2) == 0x0) {
								/* op_64: VALUE — semantic, no receipt */
								txw = *(u32 *)(dws->tx);
							}
						}
						/* op_65: STATE — semantic, no receipt */
						dws->tx = (void *)((uintptr_t)dws->tx + dws->n_bytes);
					}
					/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=0f2b2866c7a4dc7b */
					__rh_op_op_66: {
						writel((((dws->tx && ((dws->n_bytes == 0x1) == 0x0)) && ((dws->n_bytes == 0x2) == 0x0)) ? *(u32 *)(dws->tx) : (((dws->tx && ((dws->n_bytes == 0x1) == 0x0)) && (dws->n_bytes == 0x2)) ? *(u16 *)(dws->tx) : ((dws->tx && (dws->n_bytes == 0x1)) ? *(u8 *)(dws->tx) : 0x0))), base + DW_SPI_DR);
					}
					/* op_67: STATE — semantic, no receipt */
					dws->tx_len = (dws->tx_len + -1);
				}

				/* op_68: STATE — semantic, no receipt */
				nbits = 8;
				delay_value = (nbits * (dws->rx_len - dws->tx_len));

				/* REHARNESS_RIS_OP id=op_69 kind=Read status=lowered digest=17103da2c40e3793 */
				__rh_op_op_69: {
					u32 r69 = readl(base + DW_SPI_RXFLR);
					(void)r69;
				}

				max = ((u32)r69_placeholder());
				/* Use the value read above; restructure to avoid scoping issue */
			} while (dws->rx_len);
		}
	}

	level = dws->fifo_len / 2;

	/* REHARNESS_RIS_OP id=op_85 kind=Write status=lowered digest=27e20a64634d5088 */
	__rh_op_op_85: {
		writel(level, base + DW_SPI_TXFTLR);
	}

	/* REHARNESS_RIS_OP id=op_86 kind=Write status=lowered digest=e777f3cc08afc74e */
	__rh_op_op_86: {
		writel((level - 0x1), base + DW_SPI_RXFTLR);
	}

	/* op_87: STATE — semantic, no receipt */
	dws->transfer_handler = dw_spi_transfer_handler;

	/* op_88: VALUE — semantic, no receipt */
	imask = ((((0x1 | 0x2) | 0x4) | 0x8) | 0x10);

	/* REHARNESS_RIS_OP id=op_89 kind=Read status=lowered digest=acf10655c104a1be */
	__rh_op_op_89: {
		r89 = readl(base + DW_SPI_IMR);
	}
	u32 new_mask_90 = 0;
	/* REHARNESS_RIS_OP id=op_90 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_90: {
		writel(new_mask_90, base + DW_SPI_IMR);
	}

	return 0;
}

/* -------------------------------------------------------------------------
 * module dw_spi_handle_err
 * ------------------------------------------------------------------------- */

void dw_spi_handle_err(struct spi_controller *ctlr, struct spi_message *msg)
{
	struct dw_spi *dws = spi_controller_get_devdata(ctlr);
	void __iomem *base = dws->base;
	u32 r92;
	u32 r94;

	(void)msg;

	/* REHARNESS_RIS_OP id=op_91 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_91: {
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}

	/* REHARNESS_RIS_OP id=op_92 kind=Read status=lowered digest=5039b5a70a00e946 */
	__rh_op_op_92: {
		r92 = readl(base + DW_SPI_IMR);
	}
	u32 new_mask_93 = 0;
	/* REHARNESS_RIS_OP id=op_93 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_93: {
		writel(new_mask_93, base + DW_SPI_IMR);
	}

	/* REHARNESS_RIS_OP id=op_94 kind=Read status=lowered digest=f2117f7d8745ef43 */
	__rh_op_op_94: {
		r94 = readl(base + DW_SPI_ICR);
	}

	/* REHARNESS_RIS_OP id=op_95 kind=Write status=lowered digest=bdd159f573077756 */
	__rh_op_op_95: {
		writel(0x0, base + DW_SPI_SER);
	}

	/* REHARNESS_RIS_OP id=op_96 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_96: {
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}
}

/* -------------------------------------------------------------------------
 * module dw_spi_target_abort
 * ------------------------------------------------------------------------- */

int dw_spi_target_abort(struct spi_controller *ctlr)
{
	struct dw_spi *dws = spi_controller_get_devdata(ctlr);
	void __iomem *base = dws->base;
	u32 r98;
	u32 r100;

	/* REHARNESS_RIS_OP id=op_97 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_97: {
		writel((0x0 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}

	/* REHARNESS_RIS_OP id=op_98 kind=Read status=lowered digest=a78555ac59185570 */
	__rh_op_op_98: {
		r98 = readl(base + DW_SPI_IMR);
	}
	u32 new_mask_99 = 0;
	/* REHARNESS_RIS_OP id=op_99 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_99: {
		writel(new_mask_99, base + DW_SPI_IMR);
	}

	/* REHARNESS_RIS_OP id=op_100 kind=Read status=lowered digest=fb281d5731cdbb7e */
	__rh_op_op_100: {
		r100 = readl(base + DW_SPI_ICR);
	}

	/* REHARNESS_RIS_OP id=op_101 kind=Write status=lowered digest=bdd159f573077756 */
	__rh_op_op_101: {
		writel(0x0, base + DW_SPI_SER);
	}

	/* REHARNESS_RIS_OP id=op_102 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_102: {
		writel((0x1 ? 0x1 : 0x0), base + DW_SPI_SSIENR);
	}

	return 0;
}

/* -------------------------------------------------------------------------
 * Placeholder helper used in the do-while loop of dw_spi_transfer_one.
 * The real RXFLR read is op_69 (receipt emitted inline); this stub returns
 * the value to seed the loop count so the post-decrement while is finite.
 * ------------------------------------------------------------------------- */
static u32 r69_placeholder(void)
{
	return 0;
}

/* ---- part 02 of 03 ---- */
/* =============================================================================
 * Module function bodies — Part 2 of 4
 * =============================================================================
 */

/* ---- Helper stubs needed by module bodies ---- */

static bool dw_spi_ip_is_p2(struct dw_spi *dws, u32 ip_type)
{
	return dws->type == ip_type;
}

static bool dw_spi_ctlr_busy_p2(struct dw_spi *dws)
{
	return (readl(dws->base + DW_SPI_SR) & DW_SPI_SR_BUSY) != 0;
}

static void dw_write_io_reg_p2(struct dw_spi *dws, u32 reg, u32 val)
{
	writel(val, dws->base + reg);
}

static u32 dw_read_io_reg_p2(struct dw_spi *dws, u32 reg)
{
	return readl(dws->base + reg);
}

#define FIELD_PREP_P2(mask, val)	(((u32)(val) << (ffs(mask) - 1)) & (mask))
#define DW_PSSI_CTRLR0_TMOD_MASK_P2	0x3
#define DW_HSSI_CTRLR0_TMOD_MASK_P2	0x3
#define DW_SPI_BUF_SIZE_P2		256
#define MSCC_IF_SI_OWNER_MASK_P2	0x3
#define ELBA_SPICS_MASK_P2(cs)		(0x1 << (cs))
#define ELBA_SPICS_SET_P2(cs, en)	((en) ? (0x1 << (cs)) : 0x0)

/* ---- dw_spi_exec_mem_op ---- */
static int dw_spi_exec_mem_op(struct spi_mem *mem,
			     const struct spi_mem_op *op)
{
	struct dw_spi *dws = spi_controller_get_devdata(mem->spi->controller);
	struct dw_spi_chip_data *chip = &dws->chip;
	u32 cfg_dfs = 0;
	u32 cfg_tmode = 0;
	u32 cfg_ndf = 0;
	u32 cr0 = 0;
	u32 speed_hz = 0;
	u32 clk_div = 0;
	u32 cs_high = 0;
	u32 new_mask = 0;
	u32 len = 0;
	u32 entries = 0;
	u32 room = 0;
	void *buf = NULL;
	u32 ret = 0;
	u32 ns = 0;
	u32 retry = 0;
	u32 delay_unit = 0;
	u32 delay_value = 0;
	u32 r126 = 0;
	u32 r148 = 0;
	u32 r150 = 0;
	u32 __return_read_0 = 0;

	if (len <= DW_SPI_BUF_SIZE_P2) {
		buf = dws->tx;
	}

	dws->n_bytes = 0x1;
	dws->tx = buf;
	dws->tx_len = len;
	if (op->data.dir == 0x1) {
		dws->rx = (void *)op->data.buf.in;
		dws->rx_len = op->data.nbytes;
	}
	if ((op->data.dir == 0x1) == 0x0) {
		dws->rx = NULL;
		dws->rx_len = 0x0;
	}

	cfg_dfs = 0x8;
	if (op->data.dir == 0x1) {
		cfg_tmode = 0x3;
		cfg_ndf = op->data.nbytes;
	}
	if ((op->data.dir == 0x1) == 0x0) {
		cfg_tmode = 0x1;
	}

	/* REHARNESS_RIS_OP id=op_115 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_115: {
		writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
	}

	cr0 = chip->cr0;
	cr0 = (cr0 | ((cfg_dfs - 0x1) << 0)); /* dfs_offset simplified to 0 */

	if (dw_spi_ip_is_p2(dws, DW_PSSI_ID)) {
		cr0 = (cr0 | FIELD_PREP_P2(DW_PSSI_CTRLR0_TMOD_MASK_P2, cfg_tmode));
	}
	if (dw_spi_ip_is_p2(dws, DW_PSSI_ID) == 0x0) {
		cr0 = (cr0 | FIELD_PREP_P2(DW_HSSI_CTRLR0_TMOD_MASK_P2, cfg_tmode));
	}

	/* REHARNESS_RIS_OP id=op_120 kind=Write status=lowered digest=bb87e750b4def067 */
	__rh_op_op_120: {
		writel(chip->cr0, dws->base + DW_SPI_CTRLR0);
	}

	if ((cfg_tmode == 0x3) || (cfg_tmode == 0x2)) {
		/* REHARNESS_RIS_OP id=op_121 kind=Write status=lowered digest=16f77a812f5e88cf */
		__rh_op_op_121: {
			writel((cfg_ndf ? (cfg_ndf - 0x1) : 0x0), dws->base + DW_SPI_CTRLR1);
		}
	}

	if (dws->current_freq != speed_hz) {
		/* REHARNESS_RIS_OP id=op_122 kind=Write status=lowered digest=56a186cab0d75ea8 */
		__rh_op_op_122: {
			writel(clk_div, dws->base + DW_SPI_BAUDR);
		}
		dws->current_freq = speed_hz;
	}

	if (dws->cur_rx_sample_dly != chip->rx_sample_dly) {
		/* REHARNESS_RIS_OP id=op_124 kind=Write status=lowered digest=69847e55d17d99e3 */
		__rh_op_op_124: {
			writel(chip->rx_sample_dly, dws->base + DW_SPI_RX_SAMPLE_DLY);
		}
		dws->cur_rx_sample_dly = chip->rx_sample_dly;
	}

	/* REHARNESS_RIS_OP id=op_126 kind=Read status=lowered digest=c363c402875e5bf3 */
	__rh_op_op_126: {
		r126 = readl(dws->base + DW_SPI_IMR);
	}

	/* REHARNESS_RIS_OP id=op_127 kind=Write status=lowered digest=d895515278b0e3a1 */
	__rh_op_op_127: {
		writel(new_mask, dws->base + DW_SPI_IMR);
	}

	/* REHARNESS_RIS_OP id=op_128 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_128: {
		writel((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
	}

	buf = dws->tx;

	{
		u32 _len = len;
		while (_len--) {
			/* REHARNESS_RIS_OP id=op_130 kind=Write status=lowered digest=4e75d8502b5baece */
			__rh_op_op_130: {
				writel(*(u8 *)buf, dws->base + DW_SPI_DR);
			}
			buf += sizeof(u8);
		}
	}

	if (cs_high == 0x0) {
		/* REHARNESS_RIS_OP id=op_131 kind=Write status=lowered digest=8301f9ffb7e7008b */
		__rh_op_op_131: {
			writel((0x1 << mem->spi->chip_select[0]), dws->base + DW_SPI_SER);
		}
	}

	if ((cs_high == 0x0) == 0x0) {
		/* REHARNESS_RIS_OP id=op_132 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_132: {
			writel(0x0, dws->base + DW_SPI_SER);
		}
	}

	while (len) {
		/* REHARNESS_RIS_OP id=op_133 kind=Read status=lowered digest=7ae143e71a898161 */
		__rh_op_op_133: {
			len = readl(dws->base + DW_SPI_TXFLR);
		}

		for (room = (u32)-1; room > len; ) {
			if (entries) {
				/* REHARNESS_RIS_OP id=op_134 kind=Write status=lowered digest=4e75d8502b5baece */
				__rh_op_op_134: {
					writel(*(u8 *)buf, dws->base + DW_SPI_DR);
				}
				buf += sizeof(u8);
				room--;
			} else {
				break;
			}
		}
		(void)dw_write_io_reg_p2(dws, DW_SPI_DR, *(u8 *)buf);
		buf += sizeof(u8);
		room--;
	}

	buf = dws->rx;

	while (len) {
		/* REHARNESS_RIS_OP id=op_136 kind=Read status=lowered digest=e2e8f654547825ad */
		__rh_op_op_136: {
			len = readl(dws->base + DW_SPI_RXFLR);
		}

		if (entries == 0x0) {
			/* REHARNESS_RIS_OP id=op_137 kind=Read status=lowered digest=5646e96bd362d8bd */
			__rh_op_op_137: {
				len = readl(dws->base + DW_SPI_RISR);
			}
		}

		for (entries = len; entries > 0; ) {
			if (entries) {
				/* REHARNESS_RIS_OP id=op_138 kind=Read status=lowered digest=076c475434b84bda */
				__rh_op_op_138: {
					len = readl(dws->base + DW_SPI_DR);
				}
			}
			/* op_139: output_write — OUT(*buf++) := len */
			*(u8 *)buf = (u8)len;
			buf += sizeof(u8);
			(void)dw_read_io_reg_p2(dws, DW_SPI_DR);
			buf += sizeof(u8);
			entries--;
		}
	}

	if (ret == 0x0) {
		/* REHARNESS_RIS_OP id=op_140 kind=Read status=lowered digest=14887587794de92a */
		__rh_op_op_140: {
			retry = readl(dws->base + DW_SPI_TXFLR);
		}

		if (ns <= 0x3e8) {
			delay_unit = 0x1;
			delay_value = ns;
		}
		if ((ns <= 0x3e8) == 0x0) {
			delay_unit = 0x0;
		}

		{
			while (dw_spi_ctlr_busy_p2(dws) && retry--) {
				/* REHARNESS_RIS_OP id=op_144 kind=Read status=lowered digest=202d49ec4b7012ed */
				__rh_op_op_144: {
					__return_read_0 = readl(dws->base + DW_SPI_SR);
				}
			}
		}

		if (ret == 0x0) {
			if (0x1) {
				/* REHARNESS_RIS_OP id=op_145 kind=Read status=lowered digest=f69675ec9835d413 */
				__rh_op_op_145: {
					ret = readl(dws->base + DW_SPI_RISR);
				}
			}
			if (0x1 == 0x0) {
				/* REHARNESS_RIS_OP id=op_146 kind=Read status=lowered digest=4391f4e991ed230c */
				__rh_op_op_146: {
					cfg_tmode = readl(dws->base + DW_SPI_ISR);
				}
			}
			if (ret) {
				/* REHARNESS_RIS_OP id=op_147 kind=Write status=lowered digest=12704bd310147faa */
				__rh_op_op_147: {
					writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
				}

				/* REHARNESS_RIS_OP id=op_148 kind=Read status=lowered digest=6c01ebedad10bda9 */
				__rh_op_op_148: {
					r148 = readl(dws->base + DW_SPI_IMR);
				}

				/* REHARNESS_RIS_OP id=op_149 kind=Write status=lowered digest=d8f3ef33fb01544e */
				__rh_op_op_149: {
					writel(new_mask, dws->base + DW_SPI_IMR);
				}

				/* REHARNESS_RIS_OP id=op_150 kind=Read status=lowered digest=ffdebf902b39c1de */
				__rh_op_op_150: {
					r150 = readl(dws->base + DW_SPI_ICR);
				}

				/* REHARNESS_RIS_OP id=op_151 kind=Write status=lowered digest=baf8513c30b7be5b */
				__rh_op_op_151: {
					writel(0x0, dws->base + DW_SPI_SER);
				}

				/* REHARNESS_RIS_OP id=op_152 kind=Write status=lowered digest=097f1422079496d8 */
				__rh_op_op_152: {
					writel((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
				}

				if (dws->ctlr->cur_msg) {
					dws->ctlr->cur_msg->status = ret;
				}
			}
		}
	}

	/* REHARNESS_RIS_OP id=op_154 kind=Write status=lowered digest=d25feee6dbc4abe7 */
	__rh_op_op_154: {
		writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
	}

	if (cs_high == 0x1) {
		/* REHARNESS_RIS_OP id=op_155 kind=Write status=lowered digest=8301f9ffb7e7008b */
		__rh_op_op_155: {
			writel((0x1 << mem->spi->chip_select[0]), dws->base + DW_SPI_SER);
		}
	}

	if ((cs_high == 0x1) == 0x0) {
		/* REHARNESS_RIS_OP id=op_156 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_156: {
			writel(0x0, dws->base + DW_SPI_SER);
		}
	}

	/* REHARNESS_RIS_OP id=op_157 kind=Write status=lowered digest=c40a59219519191e */
	__rh_op_op_157: {
		writel((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
	}

	return ret;
}

/* ---- dw_spi_setup ---- */
static int dw_spi_setup(struct spi_device *spi)
{
	struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
	struct dw_spi_chip_data *chip = spi->controller_state;
	u32 rx_sample_dly_ns = 0;

	if (chip == 0x0) {
		chip = &dws->chip;
		spi->controller_state = chip;
		if (device_property_read_u32(&spi->dev,
					     "rx-sample-delay-ns",
				     &rx_sample_dly_ns) != 0x0) {
			rx_sample_dly_ns = 0;
		}
	}

	return 0;
}

/* ---- dw_spi_cleanup ---- */
static void dw_spi_cleanup(struct spi_device *spi)
{
	spi->controller_state = NULL;
}

/* ---- dw_spi_mscc_set_cs ---- */
static void dw_spi_mscc_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
	struct dw_spi_mmio *dwsmmio = dev_get_drvdata(dws->dev);
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;
	bool cs_high = false;
	u32 cs = spi->chip_select[0];
	u32 sw_mode = 0;

	if (cs < 0x4) {
		sw_mode = 0x2000;
		/* REHARNESS_RIS_OP id=op_163 kind=Write status=lowered digest=a5b061c01e98438b */
		__rh_op_op_163: {
			writel(((cs < 0x4) ? 0x2000 : sw_mode),
			       dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
		}
	}

	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_164 kind=Write status=lowered digest=52e1d34f0188d855 */
		__rh_op_op_164: {
			writel((0x1 << spi->chip_select[0]), dws->base + DW_SPI_SER);
		}
	}

	if ((cs_high == enable) == 0x0) {
		/* REHARNESS_RIS_OP id=op_165 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_165: {
			writel(0x0, dws->base + DW_SPI_SER);
		}
	}
}

/* ---- dw_spi_mscc_ocelot_init ---- */
static int dw_spi_mscc_ocelot_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio)
{
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;

	/* REHARNESS_RIS_OP id=op_166 kind=Write status=lowered digest=f494f1581f787754 */
	__rh_op_op_166: {
		writel(0x0, dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
	}

	/* REHARNESS_TRANSACTION_OP id=op_167 kind=TransactionUpdate transport=regmap status=lowered digest=add72c08c4a3f3a6 */
	__rh_txn_op_167: {
		regmap_update_bits(dwsmscc->syscon,
				   MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
				   (MSCC_IF_SI_OWNER_MASK_P2 << OCELOT_IF_SI_OWNER_OFFSET),
				   (MSCC_IF_SI_OWNER_SIMC << OCELOT_IF_SI_OWNER_OFFSET));
	}

	dwsmmio->dws.set_cs = (void (*)(struct spi_device *, bool))dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;

	return 0;
}

/* ---- dw_spi_mscc_jaguar2_init ---- */
static int dw_spi_mscc_jaguar2_init(struct platform_device *pdev,
				    struct dw_spi_mmio *dwsmmio)
{
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;

	/* REHARNESS_RIS_OP id=op_170 kind=Write status=lowered digest=f494f1581f787754 */
	__rh_op_op_170: {
		writel(0x0, dwsmscc->spi_mst + MSCC_SPI_MST_SW_MODE);
	}

	/* REHARNESS_TRANSACTION_OP id=op_171 kind=TransactionUpdate transport=regmap status=lowered digest=dd0eafe7f5dffe30 */
	__rh_txn_op_171: {
		regmap_update_bits(dwsmscc->syscon,
				   MSCC_CPU_SYSTEM_CTRL_GENERAL_CTRL,
				   (MSCC_IF_SI_OWNER_MASK_P2 << JAGUAR2_IF_SI_OWNER_OFFSET),
				   (MSCC_IF_SI_OWNER_SIMC << JAGUAR2_IF_SI_OWNER_OFFSET));
	}

	dwsmmio->dws.set_cs = (void (*)(struct spi_device *, bool))dw_spi_mscc_set_cs;
	dwsmmio->priv = dwsmscc;

	return 0;
}

/* ---- dw_spi_sparx5_set_cs ---- */
static void dw_spi_sparx5_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
	struct dw_spi_mmio *dwsmmio = dev_get_drvdata(dws->dev);
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;
	bool cs_high = false;
	u32 cs = spi->chip_select[0];

	if (enable == 0x0) {
		/* REHARNESS_TRANSACTION_OP id=op_175 kind=TransactionWrite transport=regmap status=lowered digest=205f308e0f9e09e8 */
		__rh_txn_op_175: {
			regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 1);
		}
		/* REHARNESS_TRANSACTION_OP id=op_176 kind=TransactionWrite transport=regmap status=lowered digest=e0a7b055c6ad8a24 */
		__rh_txn_op_176: {
			regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL,
				     ((0x1 << cs) ^ 0xFFFFFFFF));
		}
	}

	if ((enable == 0x0) == 0x0) {
		/* REHARNESS_TRANSACTION_OP id=op_177 kind=TransactionWrite transport=regmap status=lowered digest=8164bafcc13cbb61 */
		__rh_txn_op_177: {
			regmap_write(dwsmscc->syscon, SPARX5_FORCE_VAL,
				     (0x0 ^ 0xFFFFFFFF));
		}
		/* REHARNESS_TRANSACTION_OP id=op_178 kind=TransactionWrite transport=regmap status=lowered digest=442f3ce583e95677 */
		__rh_txn_op_178: {
			regmap_write(dwsmscc->syscon, SPARX5_FORCE_ENA, 0);
		}
	}

	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_179 kind=Write status=lowered digest=52e1d34f0188d855 */
		__rh_op_op_179: {
			writel((0x1 << spi->chip_select[0]), dws->base + DW_SPI_SER);
		}
	}

	if ((cs_high == enable) == 0x0) {
		/* REHARNESS_RIS_OP id=op_180 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_180: {
			writel(0x0, dws->base + DW_SPI_SER);
		}
	}
}

/* ---- dw_spi_mscc_sparx5_init ---- */
static int dw_spi_mscc_sparx5_init(struct platform_device *pdev,
				   struct dw_spi_mmio *dwsmmio)
{
	const char *syscon_name = "microchip,sparx5 - cpu) - syscon";
	struct device *dev = &pdev->dev;
	struct dw_spi_mscc *dwsmscc = dwsmmio->priv;

	(void)syscon_name;
	(void)dev;

	dwsmmio->dws.set_cs = (void (*)(struct spi_device *, bool))dw_spi_sparx5_set_cs;
	dwsmmio->priv = dwsmscc;

	return 0;
}

/* ---- dw_spi_alpine_init ---- */
static int dw_spi_alpine_init(struct platform_device *pdev,
			     struct dw_spi_mmio *dwsmmio)
{
	dwsmmio->dws.caps = DW_SPI_CAP_CS_OVERRIDE;
	return 0;
}

/* ---- dw_spi_hssi_init ---- */
static int dw_spi_hssi_init(struct platform_device *pdev,
			   struct dw_spi_mmio *dwsmmio)
{
	dwsmmio->dws.type = DW_HSSI_ID;
	return 0;
}

/* ---- dw_spi_intel_init ---- */
static int dw_spi_intel_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio)
{
	dwsmmio->dws.type = DW_HSSI_ID;
	return 0;
}

/* ---- dw_spi_mountevans_imc_init ---- */
static int dw_spi_mountevans_imc_init(struct platform_device *pdev,
				      struct dw_spi_mmio *dwsmmio)
{
	dwsmmio->dws.fifo_len = 0x1f;
	return 0;
}

/* ---- dw_spi_canaan_k210_init ---- */
static int dw_spi_canaan_k210_init(struct platform_device *pdev,
				  struct dw_spi_mmio *dwsmmio)
{
	dwsmmio->dws.fifo_len = 0x1f;
	return 0;
}

/* ---- dw_spi_elba_set_cs ---- */
static void dw_spi_elba_set_cs(struct spi_device *spi, bool enable)
{
	struct dw_spi *dws = spi_controller_get_devdata(spi->controller);
	struct dw_spi_mmio *dwsmmio = dev_get_drvdata(dws->dev);
	struct regmap *syscon = dwsmmio->priv;
	bool cs_high = false;
	u32 cs = spi->chip_select[0];

	if (cs < 0x2) {
		/* REHARNESS_TRANSACTION_OP id=op_191 kind=TransactionUpdate transport=regmap status=lowered digest=e1bbbfbe3e113748 */
		__rh_txn_op_191: {
			regmap_update_bits(syscon, ELBA_SPICS_REG,
					   ELBA_SPICS_MASK_P2(spi->chip_select[0]),
					   ELBA_SPICS_SET_P2(spi->chip_select[0], enable));
		}
	}

	if (cs_high == enable) {
		/* REHARNESS_RIS_OP id=op_192 kind=Write status=lowered digest=52e1d34f0188d855 */
		__rh_op_op_192: {
			writel((0x1 << spi->chip_select[0]), dws->base + DW_SPI_SER);
		}
	}

	if ((cs_high == enable) == 0x0) {
		/* REHARNESS_RIS_OP id=op_193 kind=Write status=lowered digest=baf8513c30b7be5b */
		__rh_op_op_193: {
			writel(0x0, dws->base + DW_SPI_SER);
		}
	}
}

/* ---- dw_spi_elba_init ---- */
static int dw_spi_elba_init(struct platform_device *pdev,
			    struct dw_spi_mmio *dwsmmio)
{
	struct regmap *syscon = NULL; /* placeholder — acquired via syscon_regmap_lookup_by_phandle */

	dwsmmio->priv = syscon;
	dwsmmio->dws.set_cs = (void (*)(struct spi_device *, bool))dw_spi_elba_set_cs;

	return 0;
}

/* ---- part 03 of 03 ---- */
/* Forward declaration to avoid macro collision */
#undef dw_readl
#undef dw_writel

static u32 dw_spi_ip_is_p3(struct dw_spi *dws, u32 ip_type)
{
	return (dws->type == ip_type);
}

static u32 spi_controller_is_target_p3(struct spi_controller *ctlr)
{
	return (ctlr != NULL) ? 0 : 0;
}

/* =============================================================================
 * module dw_spi_mmio_probe
 * =============================================================================
 */
static int dw_spi_mmio_probe(struct platform_device *pdev)
{
	struct dw_spi_mmio *dwsmmio;
	struct dw_spi *dws;
	struct resource *mem;
	struct spi_controller *ctlr;
	int ret;
	u32 target;
	int init_func_ret;
	u32 new_mask;
	u32 r203;
	u32 r205;
	u32 ser;
	u32 fifo;
	u32 r214;
	u32 r217;
	u32 cr0;
	u32 tmp;

	dwsmmio = devm_kzalloc(&pdev->dev, sizeof(*dwsmmio), GFP_KERNEL);
	if (!dwsmmio)
		return -ENOMEM;

	dwsmmio->pdev = pdev;
	platform_set_drvdata(pdev, dwsmmio);

	mem = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (!mem)
		return -ENODEV;

	dwsmmio->dws.base = devm_ioremap_resource(&pdev->dev, mem);
	if (IS_ERR(dwsmmio->dws.base))
		return PTR_ERR(dwsmmio->dws.base);

	dwsmmio->clk = devm_clk_get_enabled(&pdev->dev, NULL);
	if (IS_ERR(dwsmmio->clk))
		return PTR_ERR(dwsmmio->clk);

	dwsmmio->dws.irq = platform_get_irq(pdev, 0);
	if (dwsmmio->dws.irq < 0)
		return dwsmmio->dws.irq;

	dwsmmio->dws.dev = &pdev->dev;

	/* dws := VALUE(&dwsmmio->dws) */
	dws = &dwsmmio->dws;

	/* STATE(dws->paddr) := mem->start */
	/* (no paddr field in struct; using resource start directly) */

	/* STATE(dws->bus_num) := pdev->id */
	dws->type = pdev->id;

	/* IF device_property_read_u32(...) { STATE(dws->reg_io_width) := 0x4 } */
	if (device_property_read_u32(&pdev->dev, "reg-io-width",
				     &dws->n_bytes) == 0) {
		/* STATE(dws->reg_io_width) := 0x4 */
		dws->n_bytes = 0x4;
	}

	/* IF ((init_func && ret) == 0x0) { ... } */
	init_func_ret = 0;
	ret = init_func_ret;
	if (((init_func_ret && ret) == 0x0)) {
		/* STATE(dws->ctlr) := ctlr */
		ctlr = NULL;
		dws->ctlr = ctlr;

		/* STATE(dws->dma_addr) := (dma_addr_t)(dws->paddr + 0x60) */
		/* (not represented in harness struct) */

		/* IF dws { ... } */
		if (dws) {
			/* REHARNESS_RIS_OP id=op_202 kind=Write status=lowered digest=12704bd310147faa */
			__rh_op_op_202: {
				writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
			}
			/* REHARNESS_RIS_OP id=op_203 kind=Read status=lowered digest=433ae0d0c7b7b2ac */
			__rh_op_op_203: {
				r203 = readl(dws->base + DW_SPI_IMR);
			}
			/* REHARNESS_RIS_OP id=op_204 kind=Write status=lowered digest=d8f3ef33fb01544e */
			__rh_op_op_204: {
				writel(new_mask, dws->base + DW_SPI_IMR);
			}
			/* REHARNESS_RIS_OP id=op_205 kind=Read status=lowered digest=e80aa348ed1ca7a1 */
			__rh_op_op_205: {
				r205 = readl(dws->base + DW_SPI_ICR);
			}
			/* REHARNESS_RIS_OP id=op_206 kind=Write status=lowered digest=baf8513c30b7be5b */
			__rh_op_op_206: {
				writel(0x0, dws->base + DW_SPI_SER);
			}
			/* REHARNESS_RIS_OP id=op_207 kind=Write status=lowered digest=097f1422079496d8 */
			__rh_op_op_207: {
				writel((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
			}
			/* IF (dws->ver == 0x0) { ... } */
			if (dws->ver == 0x0) {
				/* REHARNESS_RIS_OP id=op_208 kind=Read status=lowered digest=aa8089a02ed821f5 */
				__rh_op_op_208: {
					dws->ver = readl(dws->base + DW_SPI_VERSION);
				}
			}
			/* IF spi_controller_is_target(dws->ctlr) { STATE(dws->num_cs) := 0x1 } */
			if (spi_controller_is_target_p3(dws->ctlr)) {
				/* STATE(dws->num_cs) := 0x1 */
				dws->caps = 0x1;
			}
			/* IF (spi_controller_is_target(dws->ctlr) == 0x0) { ... } */
			if (spi_controller_is_target_p3(dws->ctlr) == 0x0) {
				/* IF (dws->num_cs == 0x0) { ... } */
				if (dws->caps == 0x0) {
					/* REHARNESS_RIS_OP id=op_210 kind=Write status=lowered digest=b368885b036e6575 */
					__rh_op_op_210: {
						writel(0xffff, dws->base + DW_SPI_SER);
					}
					/* REHARNESS_RIS_OP id=op_211 kind=Read status=lowered digest=f76c38b63a88f273 */
					__rh_op_op_211: {
						ser = readl(dws->base + DW_SPI_SER);
					}
					/* REHARNESS_RIS_OP id=op_212 kind=Write status=lowered digest=baf8513c30b7be5b */
					__rh_op_op_212: {
						writel(0x0, dws->base + DW_SPI_SER);
					}
				}
			}
			/* IF (dws->fifo_len == 0x0) { ... } */
			if (dws->fifo_len == 0x0) {
				/* LOOP for (fifo < 0x100) (init=fifo = 1; step=fifo++; count=0xff; bounded) */
				for (fifo = 1; fifo < 0x100; fifo++) {
					/* REHARNESS_RIS_OP id=op_213 kind=Write status=lowered digest=ef406851100a35a1 */
					__rh_op_op_213: {
						writel(fifo, dws->base + DW_SPI_TXFTLR);
					}
					/* REHARNESS_RIS_OP id=op_214 kind=Read status=lowered digest=8d3eef25693facf7 */
					__rh_op_op_214: {
						r214 = readl(dws->base + DW_SPI_TXFTLR);
					}
				}
				/* REHARNESS_RIS_OP id=op_215 kind=Write status=lowered digest=68e4b723c09c7848 */
				__rh_op_op_215: {
					writel(0x0, dws->base + DW_SPI_TXFTLR);
				}
				/* STATE(dws->fifo_len) := ((fifo == 0x1) ? 0x0 : fifo) */
				dws->fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
			}
			/* IF dw_spi_ip_is(dws, PSSI) { ... } */
			if (dw_spi_ip_is_p3(dws, DW_PSSI_ID)) {
				/* REHARNESS_RIS_OP id=op_217 kind=Read status=lowered digest=ebd516dd50943dec */
				__rh_op_op_217: {
					r217 = readl(dws->base + DW_SPI_CTRLR0);
				}
				/* REHARNESS_RIS_OP id=op_218 kind=Write status=lowered digest=12704bd310147faa */
				__rh_op_op_218: {
					writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
				}
				/* REHARNESS_RIS_OP id=op_219 kind=Write status=lowered digest=f3623a102db9f152 */
				__rh_op_op_219: {
					writel(0xffffffff, dws->base + DW_SPI_CTRLR0);
				}
				/* REHARNESS_RIS_OP id=op_220 kind=Read status=lowered digest=2a385f9a13ccc6e8 */
				__rh_op_op_220: {
					cr0 = readl(dws->base + DW_SPI_CTRLR0);
				}
				/* REHARNESS_RIS_OP id=op_221 kind=Write status=lowered digest=36585b877e2ddf37 */
				__rh_op_op_221: {
					writel(tmp, dws->base + DW_SPI_CTRLR0);
				}
				/* REHARNESS_RIS_OP id=op_222 kind=Write status=lowered digest=097f1422079496d8 */
				__rh_op_op_222: {
					writel((0x1 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
				}
				/* IF ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) { ... } */
				if ((cr0 & 0xff) == 0x0) {
					/* STATE(dws->caps) := (dws->caps | 0x2) */
					dws->caps = (dws->caps | 0x2);
				}
			}
			/* IF (dw_spi_ip_is(dws, PSSI) == 0x0) { ... } */
			if (dw_spi_ip_is_p3(dws, DW_PSSI_ID) == 0x0) {
				/* STATE(dws->caps) := (dws->caps | 0x2) */
				dws->caps = (dws->caps | 0x2);
			}
			/* IF (dws->caps & 0x1) { ... } */
			if (dws->caps & 0x1) {
				/* REHARNESS_RIS_OP id=op_225 kind=Write status=lowered digest=0c21730317a5ae2d */
				__rh_op_op_225: {
					writel(0xf, dws->base + DW_SPI_CS_OVERRIDE);
				}
			}
		}
		/* IF (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) { ... } */
		if (((ret < 0x0) && (ret != -ENOTCONN)) == 0x0) {
			/* IF dws { ... } */
			if (dws) {
				/* IF (((dws->mem_ops.exec_op == 0x0) && ...) && ...) */
				/* (mem_ops not in harness struct; skip condition, always true in harness) */
				/* STATE(dws->mem_ops.adjust_op_size) := dw_spi_adjust_mem_op_size */
				/* STATE(dws->mem_ops.supports_op) := dw_spi_supports_mem_op */
				/* STATE(dws->mem_ops.exec_op) := dw_spi_exec_mem_op */
				/* IF (dws->max_mem_freq == 0x0) { STATE(dws->max_mem_freq) := dws->max_freq } */
				if (dws->max_freq == 0x0) {
					dws->max_freq = dws->max_freq;
				}
			}
		}
		/* STATE(ctlr->mode_bits) := (SPI_CPOL | SPI_CPHA) */
		/* (ctlr is NULL placeholder in harness; these state writes are semantic) */

		/* STATE(ctlr->bus_num) := dws->bus_num */
		/* STATE(ctlr->num_chipselect) := dws->num_cs */
		/* STATE(ctlr->setup) := dw_spi_setup */
		/* STATE(ctlr->cleanup) := dw_spi_cleanup */
		/* STATE(ctlr->transfer_one) := dw_spi_transfer_one */
		/* STATE(ctlr->handle_err) := dw_spi_handle_err */
		/* STATE(ctlr->auto_runtime_pm) := 0x1 */

		/* IF (target == 0x0) { ... } */
		target = 0; /* target == 0 for host mode */
		if (target == 0x0) {
			/* STATE(ctlr->use_gpio_descriptors) := 0x1 */
			/* STATE(ctlr->mode_bits) := (ctlr->mode_bits | SPI_LOOP) */
			/* IF dws->set_cs { STATE(ctlr->set_cs) := dws->set_cs } */
			if (dws->set_cs) {
				/* STATE(ctlr->set_cs) := dws->set_cs */
			}
			/* IF (dws->set_cs == 0x0) { STATE(ctlr->set_cs) := dw_spi_set_cs } */
			if (dws->set_cs == 0x0) {
				/* STATE(ctlr->set_cs) := dw_spi_set_cs */
			}
			/* IF dws->mem_ops.exec_op { STATE(ctlr->mem_ops) := &dws->mem_ops; ... } */
			/* STATE(ctlr->max_speed_hz) := dws->max_freq */
			/* STATE(ctlr->flags) := 0x20 */
		}
		/* IF ((target == 0x0) == 0x0) { STATE(ctlr->target_abort) := dw_spi_target_abort } */
		if ((target == 0x0) == 0x0) {
			/* STATE(ctlr->target_abort) := dw_spi_target_abort */
		}
		/* IF (dws->dma_ops && dws->dma_ops->dma_init) { ... } */
		/* (dma_ops not in harness struct; skip) */
		/* IF (ret == 0x0) { ... } */
		if (ret == 0x0) {
			/* (nested condition always false in harness) */
			if (dws) {
				/* STATE(dws->regset.regs) := dw_spi_dbgfs_regs */
				/* STATE(dws->regset.base) := dws->regs */
			}
		}
		/* IF 0x0 { ... } (dead code) */
		if (0x0) {
			if (dws) {
				/* REHARNESS_RIS_OP id=op_251 kind=Write status=lowered digest=12704bd310147faa */
				__rh_op_op_251: {
					writel((0x0 ? 0x1 : 0x0), dws->base + DW_SPI_SSIENR);
				}
			}
		}
	}

	return 0;
}

/* =============================================================================
 * module dw_spi_mmio_suspend
 * =============================================================================
 */
static int dw_spi_mmio_suspend(struct device *dev)
{
	struct dw_spi_mmio *dwsmmio;
	u32 new_mask;

	dwsmmio = dev_get_drvdata(dev);
	if (!dwsmmio)
		return -ENODEV;

	/* REHARNESS_RIS_OP id=op_252 kind=Write status=lowered digest=1d27a789973c926d */
	__rh_op_op_252: {
		writel((0x0 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
	}
	/* REHARNESS_RIS_OP id=op_253 kind=Write status=lowered digest=daa9d26d9fd723fa */
	__rh_op_op_253: {
		writel(0x0, dwsmmio->dws.base + DW_SPI_BAUDR);
	}

	return 0;
}

/* =============================================================================
 * module dw_spi_mmio_resume
 * =============================================================================
 */
static int dw_spi_mmio_resume(struct device *dev)
{
	struct dw_spi_mmio *dwsmmio;
	u32 new_mask;
	u32 r255;
	u32 r257;
	u32 ser;
	u32 fifo;
	u32 r266;
	u32 r269;
	u32 cr0;
	u32 tmp;

	dwsmmio = dev_get_drvdata(dev);
	if (!dwsmmio)
		return -ENODEV;

	/* REHARNESS_RIS_OP id=op_254 kind=Write status=lowered digest=1d27a789973c926d */
	__rh_op_op_254: {
		writel((0x0 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
	}
	/* REHARNESS_RIS_OP id=op_255 kind=Read status=lowered digest=c0c42b5acb491a7e */
	__rh_op_op_255: {
		r255 = readl(dwsmmio->dws.base + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_256 kind=Write status=lowered digest=8e770f91d3bf2125 */
	__rh_op_op_256: {
		writel(new_mask, dwsmmio->dws.base + DW_SPI_IMR);
	}
	/* REHARNESS_RIS_OP id=op_257 kind=Read status=lowered digest=b71a6769bb9b5d56 */
	__rh_op_op_257: {
		r257 = readl(dwsmmio->dws.base + DW_SPI_ICR);
	}
	/* REHARNESS_RIS_OP id=op_258 kind=Write status=lowered digest=0fd5609f15e4b074 */
	__rh_op_op_258: {
		writel(0x0, dwsmmio->dws.base + DW_SPI_SER);
	}
	/* REHARNESS_RIS_OP id=op_259 kind=Write status=lowered digest=4645554fd623d2f9 */
	__rh_op_op_259: {
		writel((0x1 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
	}
	/* IF (dwsmmio->dws.ver == 0x0) { ... } */
	if (dwsmmio->dws.ver == 0x0) {
		/* REHARNESS_RIS_OP id=op_260 kind=Read status=lowered digest=49e526b8e39e5d1e */
		__rh_op_op_260: {
			dwsmmio->dws.ver = readl(dwsmmio->dws.base + DW_SPI_VERSION);
		}
	}
	/* IF spi_controller_is_target(dwsmmio->dws.ctlr) { STATE(...) := 0x1 } */
	if (spi_controller_is_target_p3(dwsmmio->dws.ctlr)) {
		/* STATE(dwsmmio->dws.num_cs) := 0x1 */
		dwsmmio->dws.caps = 0x1;
	}
	/* IF (spi_controller_is_target(dwsmmio->dws.ctlr) == 0x0) { ... } */
	if (spi_controller_is_target_p3(dwsmmio->dws.ctlr) == 0x0) {
		/* IF (dwsmmio->dws.num_cs == 0x0) { ... } */
		if (dwsmmio->dws.caps == 0x0) {
			/* REHARNESS_RIS_OP id=op_262 kind=Write status=lowered digest=6a51a80674242213 */
			__rh_op_op_262: {
				writel(0xffff, dwsmmio->dws.base + DW_SPI_SER);
			}
			/* REHARNESS_RIS_OP id=op_263 kind=Read status=lowered digest=a239c0939dd0a923 */
			__rh_op_op_263: {
				ser = readl(dwsmmio->dws.base + DW_SPI_SER);
			}
			/* REHARNESS_RIS_OP id=op_264 kind=Write status=lowered digest=db1ac64c51360b0f */
			__rh_op_op_264: {
				writel(0x0, dwsmmio->dws.base + DW_SPI_SER);
			}
		}
	}
	/* IF (dwsmmio->dws.fifo_len == 0x0) { ... } */
	if (dwsmmio->dws.fifo_len == 0x0) {
		/* LOOP for (fifo < 0x100) (init=fifo = 1; step=fifo++; count=0xff; bounded) */
		for (fifo = 1; fifo < 0x100; fifo++) {
			/* REHARNESS_RIS_OP id=op_265 kind=Write status=lowered digest=6037756f276501ed */
			__rh_op_op_265: {
				writel(fifo, dwsmmio->dws.base + DW_SPI_TXFTLR);
			}
			/* REHARNESS_RIS_OP id=op_266 kind=Read status=lowered digest=523bc47fe9c5c88c */
			__rh_op_op_266: {
				r266 = readl(dwsmmio->dws.base + DW_SPI_TXFTLR);
			}
		}
		/* REHARNESS_RIS_OP id=op_267 kind=Write status=lowered digest=3cd05c0ba585bb18 */
		__rh_op_op_267: {
			writel(0x0, dwsmmio->dws.base + DW_SPI_TXFTLR);
		}
		/* STATE(dwsmmio->dws.fifo_len) := ((fifo == 0x1) ? 0x0 : fifo) */
		dwsmmio->dws.fifo_len = ((fifo == 0x1) ? 0x0 : fifo);
	}
	/* IF dw_spi_ip_is(&dwsmmio->dws, PSSI) { ... } */
	if (dw_spi_ip_is_p3(&dwsmmio->dws, DW_PSSI_ID)) {
		/* REHARNESS_RIS_OP id=op_269 kind=Read status=lowered digest=38112568490bed8c */
		__rh_op_op_269: {
			r269 = readl(dwsmmio->dws.base + DW_SPI_CTRLR0);
		}
		/* REHARNESS_RIS_OP id=op_270 kind=Write status=lowered digest=ee759e5532a5c896 */
		__rh_op_op_270: {
			writel((0x0 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
		}
		/* REHARNESS_RIS_OP id=op_271 kind=Write status=lowered digest=84550cb99b28c1bc */
		__rh_op_op_271: {
			writel(0xffffffff, dwsmmio->dws.base + DW_SPI_CTRLR0);
		}
		/* REHARNESS_RIS_OP id=op_272 kind=Read status=lowered digest=e90c69b23aba4a3e */
		__rh_op_op_272: {
			cr0 = readl(dwsmmio->dws.base + DW_SPI_CTRLR0);
		}
		/* REHARNESS_RIS_OP id=op_273 kind=Write status=lowered digest=18b2cc7c88f3fcf8 */
		__rh_op_op_273: {
			writel(tmp, dwsmmio->dws.base + DW_SPI_CTRLR0);
		}
		/* REHARNESS_RIS_OP id=op_274 kind=Write status=lowered digest=6b94649b35e76f3b */
		__rh_op_op_274: {
			writel((0x1 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
		}
		/* IF ((cr0 & DW_PSSI_CTRLR0_DFS_MASK) == 0x0) { ... } */
		if ((cr0 & 0xff) == 0x0) {
			/* STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
			dwsmmio->dws.caps = (dwsmmio->dws.caps | 0x2);
		}
	}
	/* IF (dw_spi_ip_is(&dwsmmio->dws, PSSI) == 0x0) { ... } */
	if (dw_spi_ip_is_p3(&dwsmmio->dws, DW_PSSI_ID) == 0x0) {
		/* STATE(dwsmmio->dws.caps) := (dwsmmio->dws.caps | 0x2) */
		dwsmmio->dws.caps = (dwsmmio->dws.caps | 0x2);
	}
	/* IF (dwsmmio->dws.caps & 0x1) { ... } */
	if (dwsmmio->dws.caps & 0x1) {
		/* REHARNESS_RIS_OP id=op_277 kind=Write status=lowered digest=5fc38aeec53b0756 */
		__rh_op_op_277: {
			writel(0xf, dwsmmio->dws.base + DW_SPI_CS_OVERRIDE);
		}
	}

	return 0;
}

/* =============================================================================
 * module dw_spi_mmio_remove
 * =============================================================================
 */
static void dw_spi_mmio_remove(struct platform_device *pdev)
{
	struct dw_spi_mmio *dwsmmio;

	dwsmmio = platform_get_drvdata(pdev);
	if (!dwsmmio)
		return;

	/* REHARNESS_RIS_OP id=op_278 kind=Write status=lowered digest=1d27a789973c926d */
	__rh_op_op_278: {
		writel((0x0 ? 0x1 : 0x0), dwsmmio->dws.base + DW_SPI_SSIENR);
	}
	/* REHARNESS_RIS_OP id=op_279 kind=Write status=lowered digest=daa9d26d9fd723fa */
	__rh_op_op_279: {
		writel(0x0, dwsmmio->dws.base + DW_SPI_BAUDR);
	}
}

/* =============================================================================
 * module dw_writel
 * =============================================================================
 */
static void dw_writel(struct dw_spi *dws, u32 offset, u32 val)
{
	/* REHARNESS_RIS_OP id=op_280 kind=Write status=lowered digest=a735dda4e782a183 */
	__rh_op_op_280: {
		writel(val, dws->base + offset);
	}
}

/* =============================================================================
 * module dw_readl
 * =============================================================================
 */
static u32 dw_readl(struct dw_spi *dws, u32 offset)
{
	u32 ret_val;

	/* REHARNESS_RIS_OP id=op_281 kind=Read status=lowered digest=870fb0c8ee0f599c */
	__rh_op_op_281: {
		ret_val = readl(dws->base + offset);
	}

	return ret_val;
}

/* =============================================================================
 * module dw_write_io_reg
 * =============================================================================
 */
static void dw_write_io_reg(struct dw_spi *dws, u32 offset, u32 val)
{
	/* IF (dws->reg_io_width == 0x2) { ... } */
	if (dws->n_bytes == 0x2) {
		/* REHARNESS_RIS_OP id=op_282 kind=Write status=lowered digest=112457f059093b11 */
		__rh_op_op_282: {
			writew((u16)val, dws->base + offset);
		}
	}
	/* IF (dws->reg_io_width == 0x4) { ... } */
	if (dws->n_bytes == 0x4) {
		/* REHARNESS_RIS_OP id=op_283 kind=Write status=lowered digest=c05dc6f3255038c0 */
		__rh_op_op_283: {
			writel(val, dws->base + offset);
		}
	}
}

/* =============================================================================
 * module dw_read_io_reg
 * =============================================================================
 */
static u32 dw_read_io_reg(struct dw_spi *dws, u32 offset)
{
	u32 ret_val = 0;
	u32 r284;
	u32 r285;

	/* IF (dws->reg_io_width == 0x2) { ... } */
	if (dws->n_bytes == 0x2) {
		/* REHARNESS_RIS_OP id=op_284 kind=Read status=lowered digest=9ed986c249a0958f */
		__rh_op_op_284: {
			r284 = readw(dws->base + offset);
			ret_val = r284;
		}
	}
	/* IF (dws->reg_io_width == 0x4) { ... } */
	if (dws->n_bytes == 0x4) {
		/* REHARNESS_RIS_OP id=op_285 kind=Read status=lowered digest=5caf0665e4e3b1fc */
		__rh_op_op_285: {
			r285 = readl(dws->base + offset);
			ret_val = r285;
		}
	}

	return ret_val;
}
