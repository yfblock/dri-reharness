#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/gpio/driver.h>
#include <linux/interrupt.h>
#include <linux/irqdesc.h>

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

#define GPIO_DATA_IN 0x04
#define GPIO_DIR 0x08
#define GPIO_DATA_SET 0x10
#define GPIO_DATA_CLR 0x14
#define GPIO_INT_EN 0x20
#define GPIO_INT_STAT_RAW 0x24
#define GPIO_INT_MASK 0x2c
#define GPIO_INT_CLR 0x30
#define GPIO_INT_TYPE 0x34
#define GPIO_INT_BOTH_EDGE 0x38
#define GPIO_INT_LEVEL 0x3c
#define GPIO_DEBOUNCE_EN 0x40
#define GPIO_DEBOUNCE_PRESCALE 0x44

#define GPIO_BYPASS_IN 12
#define GPIO_DATA_OUT 0
#define GPIO_GENERIC_BIG_ENDIAN 1
#define GPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER 8
#define GPIO_GENERIC_NO_INPUT 256
#define GPIO_GENERIC_NO_OUTPUT 32
#define GPIO_GENERIC_NO_SET_ON_INPUT 64
#define GPIO_GENERIC_PINCTRL_BACKEND 128
#define GPIO_GENERIC_READ_OUTPUT_REG_SET 16
#define GPIO_GENERIC_UNREADABLE_REG_DIR 4
#define GPIO_GENERIC_UNREADABLE_REG_SET 2
#define GPIO_INT_STAT_MASKED 40
#define GPIO_LINE_DIRECTION_IN 1
#define GPIO_LINE_DIRECTION_OUT 0
#define GPIO_PULL_EN 24
#define GPIO_PULL_TYPE 28

struct gpio_ftgpio010 {
	void __iomem *base;
	struct gpio_chip chip;
	struct clk *clk;
	struct device *dev;
	u32 gpio_sdata;
	u32 gpio_sdir;
};

static struct gpio_ftgpio010 *ftgpio_global_g;

static void ftgpio_gpio_ack_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_ack_irq");
	struct gpio_ftgpio010 *g = irq_data_get_irq_chip_data(d);
	void __iomem *base = g->base;

	/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=5dd3bb35656acca9 */
	writel((0x1 << d->hwirq), base + GPIO_INT_CLR);
}

static void ftgpio_gpio_mask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_mask_irq");
	struct gpio_ftgpio010 *g = irq_data_get_irq_chip_data(d);
	void __iomem *base = g->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	val = readl(base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_3 kind=ReadModifyWrite status=lowered digest=35b8bf6436435508 */
	writel((val & (~(0x1 << irqd_to_hwirq(d)))), base + GPIO_INT_EN);
}

static void ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_unmask_irq");
	struct gpio_ftgpio010 *g = irq_data_get_irq_chip_data(d);
	void __iomem *base = g->base;
	u32 val;

	/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	val = readl(base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_5 kind=ReadModifyWrite status=lowered digest=d8ab399a3e165c09 */
	writel((val | (0x1 << irqd_to_hwirq(d))), base + GPIO_INT_EN);
}

static int ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	RH_TRACE_FN("ftgpio_gpio_set_irq_type");
	struct gpio_ftgpio010 *g = irq_data_get_irq_chip_data(d);
	void __iomem *base = g->base;
	u32 reg_type, reg_level, reg_both;
	u32 mask = (0x1 << irqd_to_hwirq(d));

	/* REHARNESS_RIS_OP id=op_6 kind=Read status=lowered digest=b359d00e3d754d3e */
	reg_type = readl(base + GPIO_INT_TYPE);
	/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=85db95e4e47b9e4c */
	reg_level = readl(base + GPIO_INT_LEVEL);
	/* REHARNESS_RIS_OP id=op_8 kind=Read status=lowered digest=6642efb8949d9184 */
	reg_both = readl(base + GPIO_INT_BOTH_EDGE);

	if (type == IRQ_TYPE_EDGE_BOTH) {
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both | mask);
	} else if (type == IRQ_TYPE_EDGE_RISING) {
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both & (~mask));
		reg_level = (reg_level & (~mask));
	} else if (type == IRQ_TYPE_EDGE_FALLING) {
		irq_set_handler_locked(d, handle_edge_irq);
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both & (~mask));
		reg_level = (reg_level | mask);
	} else if (type == IRQ_TYPE_LEVEL_HIGH) {
		irq_set_handler_locked(d, handle_level_irq);
		reg_type = (reg_type | mask);
		reg_level = (reg_level & (~mask));
	} else if (type == IRQ_TYPE_LEVEL_LOW) {
		irq_set_handler_locked(d, handle_level_irq);
		reg_type = (reg_type | mask);
		reg_level = (reg_level | mask);
	} else {
		irq_set_handler_locked(d, handle_bad_irq);
		return -EINVAL;
	}

	/* REHARNESS_RIS_OP id=op_27 kind=ReadModifyWrite status=lowered digest=d1c746cb513851b5 */
	writel(reg_type, base + GPIO_INT_TYPE);
	/* REHARNESS_RIS_OP id=op_28 kind=ReadModifyWrite status=lowered digest=26d436ff936be225 */
	writel(reg_level, base + GPIO_INT_LEVEL);
	/* REHARNESS_RIS_OP id=op_29 kind=ReadModifyWrite status=lowered digest=64b0966d1739dce7 */
	writel(reg_both, base + GPIO_INT_BOTH_EDGE);

	return 0;
}

static void ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	RH_TRACE_FN("ftgpio_gpio_irq_handler");
	struct gpio_ftgpio010 *g = irq_desc_get_handler_data(desc);
	struct irq_chip *irqchip = irq_desc_get_chip(desc);
	void __iomem *base = g->base;
	u32 stat;

	if (irqchip->irq_mask_ack == 0x0) {
		if (irqchip->irq_ack)
			/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=93a501c95c7a42f2 */
			writel((0x1 << irqd_to_hwirq(&desc->irq_data)), base + GPIO_INT_CLR);
	}

	/* REHARNESS_RIS_OP id=op_31 kind=Read status=lowered digest=e74749be940967d5 */
	stat = readl(base + GPIO_INT_STAT_RAW);
	generic_handle_domain_irq(g->chip.irq.domain, stat);
}

static int ftgpio_gpio_set_config(struct gpio_chip *gc, unsigned int offset, unsigned long config)
{
	RH_TRACE_FN("ftgpio_gpio_set_config");
	struct gpio_ftgpio010 *g = gpiochip_get_data(gc);
	void __iomem *base = g->base;
	u32 val;
	u32 deb_div = pinconf_to_config_argument(config);

	/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=8eb491b0c0634ba7 */
	val = readl(base + GPIO_DEBOUNCE_PRESCALE);
	if (val == deb_div) {
		/* REHARNESS_RIS_OP id=op_33 kind=Read status=lowered digest=48230cd8ed117ec6 */
		val = readl(base + GPIO_DEBOUNCE_EN);
		val = (val | (0x1 << offset));
		/* REHARNESS_RIS_OP id=op_35 kind=ReadModifyWrite status=lowered digest=81000a354c140fe1 */
		writel(val, base + GPIO_DEBOUNCE_EN);
	}

	/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=339408230d26d326 */
	val = readl(base + GPIO_DEBOUNCE_EN);
	/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=a89c06a8b813ae48 */
	writel(deb_div, base + GPIO_DEBOUNCE_PRESCALE);
	val = (val | (0x1 << offset));
	/* REHARNESS_RIS_OP id=op_39 kind=ReadModifyWrite status=lowered digest=a6b3f48cd0fe1e05 */
	writel(val, base + GPIO_DEBOUNCE_EN);

	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get");
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_61 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	value = readl(base + GPIO_DATA_IN);
	return ((value & (0x1 << 0)) != 0x0);
}

static int ftgpio_gpio_probe__gpio_generic_get_multiple(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_multiple");
	void __iomem *base = priv->base;
	u32 value;
	u32 mask = 0;
	u32 bits = 0;

	/* REHARNESS_RIS_OP id=op_63 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	value = readl(base + GPIO_DATA_IN);
	/* REHARNESS_RIS_OP id=op_64 kind=Write status=lowered digest= */
	bits = ((bits & (~mask)) | (value & mask));
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set");
	void __iomem *base = priv->base;

	if (1) {
		/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=b36eb49659ebc50a */
		writel((0x1 << 0), base + GPIO_DATA_SET);
	} else {
		/* REHARNESS_RIS_OP id=op_67 kind=Write status=lowered digest=3834a18c428720bf */
		writel((0x1 << 0), base + GPIO_DATA_CLR);
	}
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_set_multiple(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set_multiple");
	void __iomem *base = priv->base;
	u32 bits = 1, mask = 1;

	if ((bits & mask) != 0x0) {
		/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=ab8d874dfdeeade8 */
		writel((bits & mask), base + GPIO_DATA_SET);
	}
	if (((~bits) & mask) != 0x0) {
		/* REHARNESS_RIS_OP id=op_70 kind=Write status=lowered digest=5f32f4874eb9aabb */
		writel(((~bits) & mask), base + GPIO_DATA_CLR);
	}
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_input(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_input");
	void __iomem *base = priv->base;
	u32 __shadow_dir;

	__shadow_dir = priv->gpio_sdir;
	priv->gpio_sdir = (__shadow_dir & (~(0x1 << 0)));
	/* REHARNESS_RIS_OP id=op_74 kind=Write status=lowered digest=b949672343e78260 */
	writel((__shadow_dir & (~(0x1 << 0))), base + GPIO_DIR);
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_output(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_output");
	void __iomem *base = priv->base;
	u32 __shadow_dir;

	if (1) {
		/* REHARNESS_RIS_OP id=op_76 kind=Write status=lowered digest=b36eb49659ebc50a */
		writel((0x1 << 0), base + GPIO_DATA_SET);
	} else {
		/* REHARNESS_RIS_OP id=op_77 kind=Write status=lowered digest=3834a18c428720bf */
		writel((0x1 << 0), base + GPIO_DATA_CLR);
	}
	__shadow_dir = priv->gpio_sdir;
	priv->gpio_sdir = (__shadow_dir | (0x1 << 0));
	/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=43d76c2e0b3f2385 */
	writel((__shadow_dir | (0x1 << 0)), base + GPIO_DIR);
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get_direction(struct gpio_ftgpio010 *priv)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_direction");
	void __iomem *base = priv->base;
	u32 direction;

	/* REHARNESS_RIS_OP id=op_82 kind=Read status=lowered digest=9d0c4bdae3641bba */
	direction = readl(base + GPIO_DIR);
	return (((direction & (0x1 << 0)) != 0x0) ? 0x0 : 0x1);
}

static int ftgpio_gpio_probe(struct platform_device *pdev)
{
	RH_TRACE_FN("ftgpio_gpio_probe");
	struct gpio_ftgpio010 *g;
	struct gpio_irq_chip *girq;
	struct device *dev = &pdev->dev;
	void __iomem *base;
	u32 gpio_initial_data;
	u32 gpio_initial_direction;

	g = devm_kzalloc(dev, sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;

	base = devm_platform_ioremap_resource(pdev, 0);
	RH_SET_BASE(base);
	if (IS_ERR(base))
		return PTR_ERR(base);

	g->base = base;
	g->dev = dev;
	ftgpio_global_g = g;

	/* REHARNESS_RIS_OP id=op_43 kind=Read status=lowered digest=16d85024e558eaef */
	gpio_initial_data = readl(base + GPIO_DATA_IN);
	g->gpio_sdata = gpio_initial_data;
	/* REHARNESS_RIS_OP id=op_45 kind=Read status=lowered digest=e9b515951bfad9ea */
	gpio_initial_direction = readl(base + GPIO_DIR);
	g->gpio_sdir = gpio_initial_direction;

	g->chip.base = -1;
	g->chip.parent = dev;
	g->chip.owner = THIS_MODULE;

	g->chip.label = dev_name(dev);
	g->chip.direction_input = ftgpio_gpio_probe__gpio_generic_direction_input;
	g->chip.direction_output = ftgpio_gpio_probe__gpio_generic_direction_output;
	g->chip.get = ftgpio_gpio_probe__gpio_generic_get;
	g->chip.get_direction = ftgpio_gpio_probe__gpio_generic_get_direction;
	g->chip.get_multiple = ftgpio_gpio_probe__gpio_generic_get_multiple;
	g->chip.set = ftgpio_gpio_probe__gpio_generic_set;
	g->chip.set_config = ftgpio_gpio_set_config;
	g->chip.set_multiple = ftgpio_gpio_probe__gpio_generic_set_multiple;

	g->chip.ngpio = 32;
	g->chip.can_sleep = false;

	girq = &g->chip.irq;
	girq->parent_handler = ftgpio_gpio_irq_handler;
	girq->num_parents = 1;
	girq->default_type = IRQ_TYPE_NONE;
	girq->handler = handle_bad_irq;
	girq->chip = (struct irq_chip *)&(struct irq_chip) {
		.name = "ftgpio010-irq",
		.irq_ack = ftgpio_gpio_ack_irq,
		.irq_mask = ftgpio_gpio_mask_irq,
		.irq_unmask = ftgpio_gpio_unmask_irq,
		.irq_set_type = ftgpio_gpio_set_irq_type,
	};

	/* REHARNESS_RIS_OP id=op_56 kind=Write status=lowered digest=7443390abf8fb623 */
	writel(0x0, base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=015d9e37bb50b02a */
	writel(0x0, base + GPIO_INT_MASK);
	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=153d39994bb1ba88 */
	writel(0xffffffff, base + GPIO_INT_CLR);
	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=92b66149c6b53a4a */
	writel(0x0, base + GPIO_DEBOUNCE_EN);

	return devm_gpiochip_add_data(dev, &g->chip, g);
}

static struct platform_driver ftgpio_gpio_driver = {
	.probe = ftgpio_gpio_probe,
	.driver = {
		.name = "gpio-ftgpio010",
	},
};

module_platform_driver(ftgpio_gpio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("FTGPIO010 GPIO controller harness");
