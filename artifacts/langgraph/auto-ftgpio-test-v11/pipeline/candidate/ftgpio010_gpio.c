#include <linux/module.h>
#include <linux/io.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/clk.h>
#include <linux/gpio/driver.h>
#include <linux/gpio/generic.h>
#include <linux/interrupt.h>
#include <linux/platform_device.h>

/* === reharness MMIO trace instrumentation (file-local, after includes) === */
static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
#undef readb
#define readb(p)    ({ u8  __v = __raw_readb(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writeb
#define writeb(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writeb((v),(p)); })
#undef readw
#define readw(p)    ({ u16 __v = __raw_readw(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writew
#define writew(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writew((v),(p)); })
#undef ioread32
#define ioread32(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef iowrite32
#define iowrite32(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
/* === end instrumentation === */

#define GPIO_DATA_IN            0x04
#define GPIO_DIR                0x08
#define GPIO_DATA_SET           0x10
#define GPIO_DATA_CLR           0x14
#define GPIO_INT_EN             0x20
#define GPIO_INT_STAT_RAW       0x24
#define GPIO_INT_MASK           0x2c
#define GPIO_INT_CLR            0x30
#define GPIO_INT_TYPE           0x34
#define GPIO_INT_BOTH_EDGE      0x38
#define GPIO_INT_LEVEL          0x3c
#define GPIO_DEBOUNCE_EN        0x40
#define GPIO_DEBOUNCE_PRESCALE  0x44

struct driver_priv {
	void __iomem *base;
	struct device *dev;
	struct gpio_generic_chip chip;
	struct clk *clk;
	u32 gpio_sdata;
	u32 gpio_sdir;
};

static inline struct driver_priv *ftgpio_from_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_from_irq");
	return irq_data_get_irq_chip_data(d);
}

static void ftgpio_gpio_ack_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_ack_irq");
	struct driver_priv *priv = ftgpio_from_irq(d);
	void __iomem *base = priv->base;

	/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=5dd3bb35656acca9 */
	__rh_op_op_1: {
		writel(0x1U << d->hwirq, base + GPIO_INT_CLR);
	}
}

static void ftgpio_gpio_mask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_mask_irq");
	struct driver_priv *priv = ftgpio_from_irq(d);
	void __iomem *base = priv->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	__rh_op_op_2: {
		val = readl(base + GPIO_INT_EN);
	}
	/* REHARNESS_RIS_OP id=op_3 kind=ReadModifyWrite status=lowered digest=35b8bf6436435508 */
	__rh_op_op_3: {
		writel(val & ~(1U << irqd_to_hwirq(d)), base + GPIO_INT_EN);
	}
}

static void ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_unmask_irq");
	struct driver_priv *priv = ftgpio_from_irq(d);
	void __iomem *base = priv->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	__rh_op_op_4: {
		val = readl(base + GPIO_INT_EN);
	}
	/* REHARNESS_RIS_OP id=op_5 kind=ReadModifyWrite status=lowered digest=d8ab399a3e165c09 */
	__rh_op_op_5: {
		writel(val | (1U << irqd_to_hwirq(d)), base + GPIO_INT_EN);
	}
}

static int ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	RH_TRACE_FN("ftgpio_gpio_set_irq_type");
	struct driver_priv *priv = ftgpio_from_irq(d);
	void __iomem *base = priv->base;
	u32 reg_type, reg_level, reg_both;
	u32 mask = 1U << d->hwirq;

	/* REHARNESS_RIS_OP id=op_6 kind=Read status=lowered digest=b359d00e3d754d3e */
	__rh_op_op_6: {
		reg_type = readl(base + GPIO_INT_TYPE);
	}
	/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=85db95e4e47b9e4c */
	__rh_op_op_7: {
		reg_level = readl(base + GPIO_INT_LEVEL);
	}
	/* REHARNESS_RIS_OP id=op_8 kind=Read status=lowered digest=6642efb8949d9184 */
	__rh_op_op_8: {
		reg_both = readl(base + GPIO_INT_BOTH_EDGE);
	}

	switch (type) {
	case IRQ_TYPE_EDGE_BOTH:
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type &= ~mask;
		reg_both |= mask;
		break;
	case IRQ_TYPE_EDGE_RISING:
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type &= ~mask;
		reg_both &= ~mask;
		reg_level &= ~mask;
		break;
	case IRQ_TYPE_EDGE_FALLING:
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type &= ~mask;
		reg_both &= ~mask;
		reg_level |= mask;
		break;
	case IRQ_TYPE_LEVEL_HIGH:
		irq_set_handler_locked(d, handle_level_irq);
		reg_type |= mask;
		reg_level &= ~mask;
		break;
	case IRQ_TYPE_LEVEL_LOW:
		irq_set_handler_locked(d, handle_level_irq);
		reg_type |= mask;
		reg_level |= mask;
		break;
	default:
		irq_set_handler_locked(d, handle_bad_irq);
		return -EINVAL;
	}

	/* REHARNESS_RIS_OP id=op_27 kind=ReadModifyWrite status=lowered digest=d1c746cb513851b5 */
	__rh_op_op_27: {
		writel(reg_type, base + GPIO_INT_TYPE);
	}
	/* REHARNESS_RIS_OP id=op_28 kind=ReadModifyWrite status=lowered digest=26d436ff936be225 */
	__rh_op_op_28: {
		writel(reg_level, base + GPIO_INT_LEVEL);
	}
	/* REHARNESS_RIS_OP id=op_29 kind=ReadModifyWrite status=lowered digest=64b0966d1739dce7 */
	__rh_op_op_29: {
		writel(reg_both, base + GPIO_INT_BOTH_EDGE);
	}
	/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=f3139a9d8d4fcbca */
	__rh_op_op_30: {
		writel(1U << irqd_to_hwirq(d), base + GPIO_INT_CLR);
	}

	return 0;
}

static void ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	RH_TRACE_FN("ftgpio_gpio_irq_handler");
	struct driver_priv *priv = irq_desc_get_handler_data(desc);
	void __iomem *base;
	u32 stat;

	if (!priv)
		return;

	base = priv->base;

	/* REHARNESS_RIS_OP id=op_31 kind=Read status=lowered digest=e74749be940967d5 */
	__rh_op_op_31: {
		stat = readl(base + GPIO_INT_STAT_RAW);
	}

	(void)stat;
}

static int ftgpio_gpio_set_config(struct gpio_chip *gc,
				   unsigned int offset,
				   unsigned long config)
{
	RH_TRACE_FN("ftgpio_gpio_set_config");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 val;
	u32 deb_div = config;

	/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=8eb491b0c0634ba7 */
	__rh_op_op_32: {
		val = readl(base + GPIO_DEBOUNCE_PRESCALE);
	}

	if (val == deb_div) {
		/* REHARNESS_RIS_OP id=op_33 kind=Read status=lowered digest=48230cd8ed117ec6 */
		__rh_op_op_33: {
			val = readl(base + GPIO_DEBOUNCE_EN);
		}

		val |= 1U << offset;

		/* REHARNESS_RIS_OP id=op_35 kind=ReadModifyWrite status=lowered digest=81000a354c140fe1 */
		__rh_op_op_35: {
			writel(val, base + GPIO_DEBOUNCE_EN);
		}
	}

	/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=339408230d26d326 */
	__rh_op_op_36: {
		val = readl(base + GPIO_DEBOUNCE_EN);
	}
	/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=a89c06a8b813ae48 */
	__rh_op_op_37: {
		writel(deb_div, base + GPIO_DEBOUNCE_PRESCALE);
	}

	val |= 1U << offset;

	/* REHARNESS_RIS_OP id=op_39 kind=ReadModifyWrite status=lowered digest=a6b3f48cd0fe1e05 */
	__rh_op_op_39: {
		writel(val, base + GPIO_DEBOUNCE_EN);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get(struct gpio_chip *gc,
						unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_61 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	__rh_op_op_61: {
		value = readl(base + GPIO_DATA_IN);
	}

	return !!(value & (1U << offset));
}

static int ftgpio_gpio_probe__gpio_generic_get_multiple(
	struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_multiple");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_63 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	__rh_op_op_63: {
		value = readl(base + GPIO_DATA_IN);
	}

	*bits = (*bits & ~(*mask)) | (value & *mask);
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set(struct gpio_chip *gc,
						unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;

	if (value) {
		/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=b36eb49659ebc50a */
		__rh_op_op_66: {
			writel(1U << offset, base + GPIO_DATA_SET);
		}
	} else {
		/* REHARNESS_RIS_OP id=op_67 kind=Write status=lowered digest=3834a18c428720bf */
		__rh_op_op_67: {
			writel(1U << offset, base + GPIO_DATA_CLR);
		}
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set_multiple(
	struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set_multiple");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;

	if (*bits & *mask) {
		/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=ab8d874dfdeeade8 */
		__rh_op_op_69: {
			writel(*bits & *mask, base + GPIO_DATA_SET);
		}
	}

	if (~*bits & *mask) {
		/* REHARNESS_RIS_OP id=op_70 kind=Write status=lowered digest=5f32f4874eb9aabb */
		__rh_op_op_70: {
			writel(~*bits & *mask, base + GPIO_DATA_CLR);
		}
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_input(
	struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_input");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 shadow_dir = priv->gpio_sdir;

	priv->gpio_sdir = shadow_dir & ~(1U << offset);

	/* REHARNESS_RIS_OP id=op_74 kind=Write status=lowered digest=b949672343e78260 */
	__rh_op_op_74: {
		writel(priv->gpio_sdir, base + GPIO_DIR);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_output(
	struct gpio_chip *gc, unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_output");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 shadow_dir;

	if (value) {
		/* REHARNESS_RIS_OP id=op_76 kind=Write status=lowered digest=b36eb49659ebc50a */
		__rh_op_op_76: {
			writel(1U << offset, base + GPIO_DATA_SET);
		}
	} else {
		/* REHARNESS_RIS_OP id=op_77 kind=Write status=lowered digest=3834a18c428720bf */
		__rh_op_op_77: {
			writel(1U << offset, base + GPIO_DATA_CLR);
		}
	}

	shadow_dir = priv->gpio_sdir;
	priv->gpio_sdir = shadow_dir | (1U << offset);

	/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=43d76c2e0b3f2385 */
	__rh_op_op_80: {
		writel(priv->gpio_sdir, base + GPIO_DIR);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get_direction(
	struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_direction");
	struct driver_priv *priv = gpiochip_get_data(gc);
	void __iomem *base = priv->base;
	u32 direction;

	/* REHARNESS_RIS_OP id=op_82 kind=Read status=lowered digest=9d0c4bdae3641bba */
	__rh_op_op_82: {
		direction = readl(base + GPIO_DIR);
	}

	return (direction & (1U << offset)) ? 0 : 1;
}

static struct irq_chip ftgpio_irq_chip = {
	.name = "ftgpio010",
	.irq_ack = ftgpio_gpio_ack_irq,
	.irq_mask = ftgpio_gpio_mask_irq,
	.irq_unmask = ftgpio_gpio_unmask_irq,
	.irq_set_type = ftgpio_gpio_set_irq_type,
};

static int ftgpio_gpio_probe(struct platform_device *pdev)
{
	RH_TRACE_FN("ftgpio_gpio_probe");
	struct driver_priv *priv;
	struct gpio_generic_chip_config config;
	struct gpio_irq_chip *girq;
	void __iomem *base;
	int irq;
	u32 gpio_initial_data;
	u32 gpio_initial_direction;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->dev = &pdev->dev;

	base = devm_platform_ioremap_resource(pdev, 0);
	RH_SET_BASE(base);
	if (IS_ERR(base))
		return PTR_ERR(base);

	priv->base = base;

	priv->clk = devm_clk_get_enabled(&pdev->dev, "clk0");
	if (IS_ERR(priv->clk) && PTR_ERR(priv->clk) == -EPROBE_DEFER)
		return -EPROBE_DEFER;

	memset(&config, 0, sizeof(config));
	config.dev = &pdev->dev;
	config.sz = 4;
	config.dat = base + GPIO_DATA_IN;
	config.set = base + GPIO_DATA_SET;
	config.clr = base + GPIO_DATA_CLR;
	config.dirout = base + GPIO_DIR;

	/*
	 * The initial reads precede the initialization writes, matching the
	 * authoritative runtime trace.
	 */
	/* REHARNESS_RIS_OP id=op_43 kind=Read status=lowered digest=16d85024e558eaef */
	__rh_op_op_43: {
		gpio_initial_data = readl(base + GPIO_DATA_IN);
	}
	priv->gpio_sdata = gpio_initial_data;

	/* REHARNESS_RIS_OP id=op_45 kind=Read status=lowered digest=e9b515951bfad9ea */
	__rh_op_op_45: {
		gpio_initial_direction = readl(base + GPIO_DIR);
	}
	priv->gpio_sdir = gpio_initial_direction;

	/* REHARNESS_RIS_OP id=op_56 kind=Write status=lowered digest=7443390abf8fb623 */
	__rh_op_op_56: {
		writel(0, base + GPIO_INT_EN);
	}
	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=015d9e37bb50b02a */
	__rh_op_op_57: {
		writel(0, base + GPIO_INT_MASK);
	}
	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=153d39994bb1ba88 */
	__rh_op_op_58: {
		writel(0xffffffffU, base + GPIO_INT_CLR);
	}
	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=92b66149c6b53a4a */
	__rh_op_op_59: {
		writel(0, base + GPIO_DEBOUNCE_EN);
	}

	if (gpio_generic_chip_init(&priv->chip, &config))
		return -EINVAL;

	priv->chip.gc.label = "ftgpio010";
	priv->chip.gc.parent = &pdev->dev;
	priv->chip.gc.owner = THIS_MODULE;
	priv->chip.gc.get =
		ftgpio_gpio_probe__gpio_generic_get;
	priv->chip.gc.get_multiple =
		ftgpio_gpio_probe__gpio_generic_get_multiple;
	priv->chip.gc.set =
		ftgpio_gpio_probe__gpio_generic_set;
	priv->chip.gc.set_multiple =
		ftgpio_gpio_probe__gpio_generic_set_multiple;
	priv->chip.gc.direction_input =
		ftgpio_gpio_probe__gpio_generic_direction_input;
	priv->chip.gc.direction_output =
		ftgpio_gpio_probe__gpio_generic_direction_output;
	priv->chip.gc.get_direction =
		ftgpio_gpio_probe__gpio_generic_get_direction;
	priv->chip.gc.set_config = ftgpio_gpio_set_config;

	girq = &priv->chip.gc.irq;
	gpio_irq_chip_set_chip(girq, &ftgpio_irq_chip);
	girq->parent_handler = ftgpio_gpio_irq_handler;
	girq->num_parents = 1;

	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;

	girq->parents = devm_kcalloc(&pdev->dev, 1,
				     sizeof(*girq->parents), GFP_KERNEL);
	if (!girq->parents)
		return -ENOMEM;

	girq->parents[0] = irq;
	girq->default_type = IRQ_TYPE_NONE;
	girq->handler = handle_bad_irq;

	platform_set_drvdata(pdev, priv);
	return devm_gpiochip_add_data(&pdev->dev, &priv->chip.gc, priv);
}

static const struct of_device_id ftgpio_of_match[] = {
	{ .compatible = "ftgpio010-gpio" },
	{ }
};
MODULE_DEVICE_TABLE(of, ftgpio_of_match);

static struct platform_driver ftgpio_driver = {
	.probe = ftgpio_gpio_probe,
	.driver = {
		.name = "ftgpio010-gpio",
		.of_match_table = ftgpio_of_match,
	},
};

module_platform_driver(ftgpio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("FTGPIO010 GPIO controller driver");
