#include <linux/module.h>
#include <linux/io.h>
#include <linux/platform_device.h>
#include <linux/gpio/driver.h>
#include <linux/gpio/generic.h>
#include <linux/interrupt.h>
#include <linux/clk.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/bitops.h>
#include <linux/string.h>

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

#define GPIO_DATA_IN           0x04
#define GPIO_DIR               0x08
#define GPIO_DATA_SET          0x10
#define GPIO_DATA_CLR          0x14
#define GPIO_INT_EN            0x20
#define GPIO_INT_STAT_RAW      0x24
#define GPIO_INT_MASK          0x2c
#define GPIO_INT_CLR           0x30
#define GPIO_INT_TYPE          0x34
#define GPIO_INT_BOTH_EDGE     0x38
#define GPIO_INT_LEVEL         0x3c
#define GPIO_DEBOUNCE_EN       0x40
#define GPIO_DEBOUNCE_PRESCALE 0x44

struct gpio_ftgpio010 {
	struct device *dev;
	struct gpio_generic_chip chip;
	void __iomem *base;
	struct clk *clk;
	u32 gpio_sdata;
	u32 gpio_sdir;
	u32 num_irqs;
};

static inline struct gpio_ftgpio010 *ftgpio_from_gc(struct gpio_chip *gc)
{
	RH_TRACE_FN("ftgpio_from_gc");
	return container_of(gc, struct gpio_ftgpio010, chip.gc);
}

static inline struct gpio_ftgpio010 *ftgpio_from_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_from_irq");
	return irq_data_get_irq_chip_data(d);
}

static inline u32 ftgpio_irq_mask(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_irq_mask");
	return BIT((u32)irqd_to_hwirq(d));
}

static void ftgpio_gpio_ack_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_ack_irq");
	struct gpio_ftgpio010 *g = ftgpio_from_irq(d);
	void __iomem *base = g->base;

	/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=5dd3bb35656acca9 */
	__rh_op_op_1: {
		writel(BIT((u32)d->hwirq), base + GPIO_INT_CLR);
	}
}

static void ftgpio_gpio_mask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_mask_irq");
	struct gpio_ftgpio010 *g = ftgpio_from_irq(d);
	void __iomem *base = g->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	__rh_op_op_2: {
		val = readl(base + GPIO_INT_EN);
	}

	/* REHARNESS_RIS_OP id=op_3 kind=ReadModifyWrite status=lowered digest=35b8bf6436435508 */
	__rh_op_op_3: {
		writel(val & ~BIT((u32)irqd_to_hwirq(d)), base + GPIO_INT_EN);
	}
}

static void ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_unmask_irq");
	struct gpio_ftgpio010 *g = ftgpio_from_irq(d);
	void __iomem *base = g->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	__rh_op_op_4: {
		val = readl(base + GPIO_INT_EN);
	}

	/* REHARNESS_RIS_OP id=op_5 kind=ReadModifyWrite status=lowered digest=d8ab399a3e165c09 */
	__rh_op_op_5: {
		writel(val | BIT((u32)irqd_to_hwirq(d)), base + GPIO_INT_EN);
	}
}

static int ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	RH_TRACE_FN("ftgpio_gpio_set_irq_type");
	struct gpio_ftgpio010 *g = ftgpio_from_irq(d);
	void __iomem *base = g->base;
	u32 mask = ftgpio_irq_mask(d);
	u32 reg_type, reg_level, reg_both, value;

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

	if (type == IRQ_TYPE_EDGE_BOTH) {
		reg_type &= ~mask;
		reg_both |= mask;
		irq_set_handler_locked(d, handle_edge_irq);
	} else if (type == IRQ_TYPE_EDGE_RISING) {
		reg_type &= ~mask;
		reg_both &= ~mask;
		reg_level &= ~mask;
		irq_set_handler_locked(d, handle_edge_irq);
	} else if (type == IRQ_TYPE_EDGE_FALLING) {
		reg_type &= ~mask;
		reg_both &= ~mask;
		reg_level |= mask;
		irq_set_handler_locked(d, handle_edge_irq);
	} else if (type == IRQ_TYPE_LEVEL_HIGH) {
		reg_type |= mask;
		reg_level &= ~mask;
		irq_set_handler_locked(d, handle_level_irq);
	} else if (type == IRQ_TYPE_LEVEL_LOW) {
		reg_type |= mask;
		reg_level |= mask;
		irq_set_handler_locked(d, handle_level_irq);
	} else {
		irq_set_handler_locked(d, handle_bad_irq);
		return -EINVAL;
	}

	/* REHARNESS_RIS_OP id=op_27 kind=ReadModifyWrite status=lowered digest=d1c746cb513851b5 */
	__rh_op_op_27: {
		value = reg_type;
		writel(value, base + GPIO_INT_TYPE);
	}

	/* REHARNESS_RIS_OP id=op_28 kind=ReadModifyWrite status=lowered digest=26d436ff936be225 */
	__rh_op_op_28: {
		value = reg_level;
		writel(value, base + GPIO_INT_LEVEL);
	}

	/* REHARNESS_RIS_OP id=op_29 kind=ReadModifyWrite status=lowered digest=64b0966d1739dce7 */
	__rh_op_op_29: {
		value = reg_both;
		writel(value, base + GPIO_INT_BOTH_EDGE);
	}

	/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=f3139a9d8d4fcbca */
	__rh_op_op_30: {
		writel(BIT((u32)irqd_to_hwirq(d)), base + GPIO_INT_CLR);
	}

	return 0;
}

static void ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	RH_TRACE_FN("ftgpio_gpio_irq_handler");
	struct gpio_ftgpio010 *g = irq_desc_get_handler_data(desc);
	void __iomem *base = g->base;
	u32 stat;

	/* REHARNESS_RIS_OP id=op_31 kind=Read status=lowered digest=e74749be940967d5 */
	__rh_op_op_31: {
		stat = readl(base + GPIO_INT_STAT_RAW);
	}

	if (stat)
		handle_nested_irq(irq_desc_get_irq(desc));
}

static int ftgpio_gpio_set_config(struct gpio_chip *gc,
				  unsigned int offset,
				  unsigned long config)
{
	RH_TRACE_FN("ftgpio_gpio_set_config");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);
	void __iomem *base = g->base;
	u32 deb_div = (u32)config;
	u32 val;

	/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=8eb491b0c0634ba7 */
	__rh_op_op_32: {
		val = readl(base + GPIO_DEBOUNCE_PRESCALE);
	}

	if (val == deb_div) {
		/* REHARNESS_RIS_OP id=op_33 kind=Read status=lowered digest=48230cd8ed117ec6 */
		__rh_op_op_33: {
			val = readl(base + GPIO_DEBOUNCE_EN);
		}

		/* REHARNESS_RIS_OP id=op_35 kind=ReadModifyWrite status=lowered digest=81000a354c140fe1 */
		__rh_op_op_35: {
			val |= BIT(offset);
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

	/* REHARNESS_RIS_OP id=op_39 kind=ReadModifyWrite status=lowered digest=a6b3f48cd0fe1e05 */
	__rh_op_op_39: {
		writel(val | BIT(offset), base + GPIO_DEBOUNCE_EN);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get(struct gpio_chip *gc,
					       unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);
	u32 value;

	/* REHARNESS_RIS_OP id=op_61 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	__rh_op_op_61: {
		value = readl(g->base + GPIO_DATA_IN);
	}

	return !!(value & BIT(offset));
}

static int ftgpio_gpio_probe__gpio_generic_get_multiple(
	struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_multiple");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);
	u32 value;

	/* REHARNESS_RIS_OP id=op_63 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	__rh_op_op_63: {
		value = readl(g->base + GPIO_DATA_IN);
	}

	*bits = (*bits & ~(*mask)) | (value & *mask);
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set(struct gpio_chip *gc,
					       unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);

	if (value) {
		/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=b36eb49659ebc50a */
		__rh_op_op_66: {
			writel(BIT(offset), g->base + GPIO_DATA_SET);
		}
	} else {
		/* REHARNESS_RIS_OP id=op_67 kind=Write status=lowered digest=3834a18c428720bf */
		__rh_op_op_67: {
			writel(BIT(offset), g->base + GPIO_DATA_CLR);
		}
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set_multiple(
	struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set_multiple");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);

	if (*bits & *mask) {
		/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=ab8d874dfdeeade8 */
		__rh_op_op_69: {
			writel(*bits & *mask, g->base + GPIO_DATA_SET);
		}
	}

	if (~*bits & *mask) {
		/* REHARNESS_RIS_OP id=op_70 kind=Write status=lowered digest=5f32f4874eb9aabb */
		__rh_op_op_70: {
			writel(~*bits & *mask, g->base + GPIO_DATA_CLR);
		}
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_input(
	struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_input");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);

	g->gpio_sdir &= ~BIT(offset);

	/* REHARNESS_RIS_OP id=op_74 kind=Write status=lowered digest=b949672343e78260 */
	__rh_op_op_74: {
		writel(g->gpio_sdir, g->base + GPIO_DIR);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_output(
	struct gpio_chip *gc, unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_output");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);

	if (value) {
		/* REHARNESS_RIS_OP id=op_76 kind=Write status=lowered digest=b36eb49659ebc50a */
		__rh_op_op_76: {
			writel(BIT(offset), g->base + GPIO_DATA_SET);
		}
	} else {
		/* REHARNESS_RIS_OP id=op_77 kind=Write status=lowered digest=3834a18c428720bf */
		__rh_op_op_77: {
			writel(BIT(offset), g->base + GPIO_DATA_CLR);
		}
	}

	g->gpio_sdir |= BIT(offset);

	/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=43d76c2e0b3f2385 */
	__rh_op_op_80: {
		writel(g->gpio_sdir, g->base + GPIO_DIR);
	}

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get_direction(
	struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_direction");
	struct gpio_ftgpio010 *g = ftgpio_from_gc(gc);
	u32 direction;

	/* REHARNESS_RIS_OP id=op_82 kind=Read status=lowered digest=9d0c4bdae3641bba */
	__rh_op_op_82: {
		direction = readl(g->base + GPIO_DIR);
	}

	return (direction & BIT(offset)) ? 0 : 1;
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
	struct gpio_ftgpio010 *g;
	struct gpio_irq_chip *girq;
	struct gpio_generic_chip_config config;
	struct resource *res;
	int irq, ret;
	u32 gpio_initial_data, gpio_initial_direction;

	g = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;

	g->dev = &pdev->dev;
	platform_set_drvdata(pdev, g);

	g->base = devm_platform_ioremap_resource(pdev, 0);
	RH_SET_BASE(g->base);
	if (IS_ERR(g->base))
		return PTR_ERR(g->base);

	g->clk = devm_clk_get_enabled(&pdev->dev, NULL);
	if (IS_ERR(g->clk) && PTR_ERR(g->clk) == -EPROBE_DEFER)
		return -EPROBE_DEFER;

	memset(&config, 0, sizeof(config));
	config.dev = &pdev->dev;
	config.sz = 4;
	config.dat = g->base + GPIO_DATA_IN;
	config.set = g->base + GPIO_DATA_SET;
	config.clr = g->base + GPIO_DATA_CLR;
	config.dirout = g->base + GPIO_DIR;

	/* REHARNESS_RIS_OP id=op_43 kind=Read status=lowered digest=16d85024e558eaef */
	__rh_op_op_43: {
		gpio_initial_data = readl(g->base + GPIO_DATA_IN);
	}
	g->gpio_sdata = gpio_initial_data;

	/* REHARNESS_RIS_OP id=op_45 kind=Read status=lowered digest=e9b515951bfad9ea */
	__rh_op_op_45: {
		gpio_initial_direction = readl(g->base + GPIO_DIR);
	}
	g->gpio_sdir = gpio_initial_direction;

	g->chip.gc.base = -1;
	g->chip.gc.parent = &pdev->dev;
	g->chip.gc.owner = THIS_MODULE;
	g->chip.gc.label = dev_name(&pdev->dev);
	g->chip.gc.ngpio = 32;
	g->chip.gc.get = ftgpio_gpio_probe__gpio_generic_get;
	g->chip.gc.get_multiple =
		ftgpio_gpio_probe__gpio_generic_get_multiple;
	g->chip.gc.set = ftgpio_gpio_probe__gpio_generic_set;
	g->chip.gc.set_multiple =
		ftgpio_gpio_probe__gpio_generic_set_multiple;
	g->chip.gc.direction_input =
		ftgpio_gpio_probe__gpio_generic_direction_input;
	g->chip.gc.direction_output =
		ftgpio_gpio_probe__gpio_generic_direction_output;
	g->chip.gc.get_direction =
		ftgpio_gpio_probe__gpio_generic_get_direction;
	g->chip.gc.set_config = ftgpio_gpio_set_config;

	ret = gpio_generic_chip_init(&g->chip, &config);
	if (ret)
		return ret;

	girq = &g->chip.gc.irq;
	girq->chip = &ftgpio_irq_chip;
	girq->parent_handler = ftgpio_gpio_irq_handler;
	girq->num_parents = 1;
	girq->default_type = IRQ_TYPE_NONE;
	girq->handler = handle_bad_irq;

	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;

	irq_set_handler_data(irq, g);

	/* REHARNESS_RIS_OP id=op_56 kind=Write status=lowered digest=7443390abf8fb623 */
	__rh_op_op_56: {
		writel(0, g->base + GPIO_INT_EN);
	}

	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=015d9e37bb50b02a */
	__rh_op_op_57: {
		writel(0, g->base + GPIO_INT_MASK);
	}

	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=153d39994bb1ba88 */
	__rh_op_op_58: {
		writel(0xffffffffU, g->base + GPIO_INT_CLR);
	}

	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=92b66149c6b53a4a */
	__rh_op_op_59: {
		writel(0, g->base + GPIO_DEBOUNCE_EN);
	}

	res = platform_get_resource(pdev, IORESOURCE_IRQ, 0);
	if (res)
		g->num_irqs = 32;

	return devm_gpiochip_add_data(&pdev->dev, &g->chip.gc, g);
}

static struct platform_driver ftgpio_gpio_driver = {
	.probe = ftgpio_gpio_probe,
	.driver = {
		.name = "ftgpio010-gpio",
		.of_match_table = of_match_ptr(NULL),
	},
};

module_platform_driver(ftgpio_gpio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("FTGPIO010 GPIO controller");
