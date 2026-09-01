#include <linux/module.h>
#include <linux/io.h>
#include <linux/err.h>
#include <linux/slab.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/gpio/driver.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/clk.h>
#include <linux/bitops.h>
#include <linux/pinctrl/pinconf-generic.h>

#define GPIO_DATA_IN              0x04
#define GPIO_DIR                  0x08
#define GPIO_DATA_SET             0x10
#define GPIO_DATA_CLR             0x14
#define GPIO_INT_EN               0x20
#define GPIO_INT_STAT_RAW         0x24
#define GPIO_INT_MASK             0x2c
#define GPIO_INT_CLR              0x30
#define GPIO_INT_TYPE             0x34
#define GPIO_INT_BOTH_EDGE        0x38
#define GPIO_INT_LEVEL            0x3c
#define GPIO_DEBOUNCE_EN          0x40
#define GPIO_DEBOUNCE_PRESCALE    0x44

#define FTGPIO_DIGEST "26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da"

struct driver_priv {
	void __iomem *base;
	struct device *dev;
	struct gpio_chip chip;
	struct clk *clk;
	u32 gpio_initial_data;
	u32 gpio_initial_direction;
};

static struct driver_priv *ftgpio_priv_from_gc(struct gpio_chip *gc)
{
	return gpiochip_get_data(gc);
}

void ftgpio_gpio_ack_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct driver_priv *priv = gc ? gpiochip_get_data(gc) : NULL;
	void __iomem *base;

	if (!priv)
		return;
	base = priv->base;
	/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_1: { writel(1U << d->hwirq, base + GPIO_INT_CLR); }
}

void ftgpio_gpio_mask_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct driver_priv *priv = gc ? gpiochip_get_data(gc) : NULL;
	void __iomem *base;
	u32 val;

	if (!priv)
		return;
	base = priv->base;
	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_2: { val = readl(base + GPIO_INT_EN); }
	/* REHARNESS_RIS_OP id=op_3 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_3: { writel(val & ~(1U << irqd_to_hwirq(d)), base + GPIO_INT_EN); }
}

void ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct driver_priv *priv = gc ? gpiochip_get_data(gc) : NULL;
	void __iomem *base;
	u32 val;

	if (!priv)
		return;
	base = priv->base;
	/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_4: { val = readl(base + GPIO_INT_EN); }
	/* REHARNESS_RIS_OP id=op_5 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_5: { writel(val | (1U << irqd_to_hwirq(d)), base + GPIO_INT_EN); }
}

int ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct driver_priv *priv = gc ? gpiochip_get_data(gc) : NULL;
	void __iomem *base;
	u32 reg_type, reg_level, reg_both;
	u32 mask = 1U << irqd_to_hwirq(d);

	if (!priv)
		return -ENODEV;
	base = priv->base;
	/* REHARNESS_RIS_OP id=op_6 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_6: { reg_type = readl(base + GPIO_INT_TYPE); }
	/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_7: { reg_level = readl(base + GPIO_INT_LEVEL); }
	/* REHARNESS_RIS_OP id=op_8 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_8: { reg_both = readl(base + GPIO_INT_BOTH_EDGE); }

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
	/* REHARNESS_RIS_OP id=op_27 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_27: { writel(reg_type, base + GPIO_INT_TYPE); }
	/* REHARNESS_RIS_OP id=op_28 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_28: { writel(reg_level, base + GPIO_INT_LEVEL); }
	/* REHARNESS_RIS_OP id=op_29 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_29: { writel(reg_both, base + GPIO_INT_BOTH_EDGE); }
	/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_30: { writel(1U << irqd_to_hwirq(d), base + GPIO_INT_CLR); }
	return 0;
}

void ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	struct gpio_chip *gc = irq_desc_get_handler_data(desc);
	struct driver_priv *priv = gc ? gpiochip_get_data(gc) : NULL;
	void __iomem *base;
	u32 stat;
	unsigned int bit;

	if (!priv || !gc)
		return;
	base = priv->base;
	/* REHARNESS_RIS_OP id=op_31 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_31: { stat = readl(base + GPIO_INT_STAT_RAW); }
	for_each_set_bit(bit, (unsigned long *)&stat, gc->ngpio)
		generic_handle_domain_irq(gc->irq.domain, bit);
}

int ftgpio_gpio_set_config(struct gpio_chip *gc, unsigned int offset,
				   unsigned long config)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 val;
	u32 deb_div = (u32)pinconf_to_config_argument(config);

	/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_32: { val = readl(base + GPIO_DEBOUNCE_PRESCALE); }
	if (val == deb_div) {
		/* REHARNESS_RIS_OP id=op_33 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_33: { val = readl(base + GPIO_DEBOUNCE_EN); }
		val |= 1U << offset;
		/* REHARNESS_RIS_OP id=op_35 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_35: { writel(val, base + GPIO_DEBOUNCE_EN); }
	}
	/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_36: { val = readl(base + GPIO_DEBOUNCE_EN); }
	val |= 1U << offset;
	/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_37: { writel(deb_div, base + GPIO_DEBOUNCE_PRESCALE); }
	/* REHARNESS_RIS_OP id=op_39 kind=ReadModifyWrite status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_39: { writel(val | (1U << offset), base + GPIO_DEBOUNCE_EN); }
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_get(struct gpio_chip *gc, unsigned int offset)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_61 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_61: { value = readl(base + GPIO_DATA_IN); }
	return !!(value & (1U << offset));
}

int ftgpio_gpio_probe__gpio_generic_get_multiple(struct gpio_chip *gc,
						 unsigned long *mask, unsigned long *bits)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_63 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_63: { value = readl(base + GPIO_DATA_IN); }
	*bits = (*bits & ~*mask) | (value & *mask);
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_set(struct gpio_chip *gc, unsigned int offset,
					int value)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;

	if (value != 0) {
		/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_66: { writel(1U << offset, base + GPIO_DATA_SET); }
	}
	if (value == 0) {
		/* REHARNESS_RIS_OP id=op_67 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_67: { writel(1U << offset, base + GPIO_DATA_CLR); }
	}
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_set_multiple(struct gpio_chip *gc,
						 unsigned long *mask, unsigned long *bits)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;

	if ((*bits & *mask) != 0) {
		/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_69: { writel(*bits & *mask, base + GPIO_DATA_SET); }
	}
	if (((~*bits) & *mask) != 0) {
		/* REHARNESS_RIS_OP id=op_70 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_70: { writel((~*bits) & *mask, base + GPIO_DATA_CLR); }
	}
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_direction_input(struct gpio_chip *gc,
						      unsigned int offset)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 shadow_dir = priv->gpio_initial_direction;

	shadow_dir &= ~(1U << offset);
	priv->gpio_initial_direction = shadow_dir;
	/* REHARNESS_RIS_OP id=op_74 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_74: { writel(shadow_dir, base + GPIO_DIR); }
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_direction_output(struct gpio_chip *gc,
						       unsigned int offset, int value)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 shadow_dir;

	if (value != 0) {
		/* REHARNESS_RIS_OP id=op_76 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_76: { writel(1U << offset, base + GPIO_DATA_SET); }
	}
	if (value == 0) {
		/* REHARNESS_RIS_OP id=op_77 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_77: { writel(1U << offset, base + GPIO_DATA_CLR); }
	}
	shadow_dir = priv->gpio_initial_direction;
	shadow_dir |= 1U << offset;
	priv->gpio_initial_direction = shadow_dir;
	/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_80: { writel(shadow_dir, base + GPIO_DIR); }
	return 0;
}

int ftgpio_gpio_probe__gpio_generic_get_direction(struct gpio_chip *gc,
						     unsigned int offset)
{
	struct driver_priv *priv = ftgpio_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 direction;

	/* REHARNESS_RIS_OP id=op_82 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_82: { direction = readl(base + GPIO_DIR); }
	return (direction & (1U << offset)) ? 0 : 1;
}

static const struct irq_chip ftgpio_irq_chip = {
	.name = "ftgpio010",
	.irq_ack = ftgpio_gpio_ack_irq,
	.irq_mask = ftgpio_gpio_mask_irq,
	.irq_unmask = ftgpio_gpio_unmask_irq,
	.irq_set_type = ftgpio_gpio_set_irq_type,
};

int ftgpio_gpio_probe(struct platform_device *pdev)
{
	struct driver_priv *priv;
	struct gpio_chip *gc;
	struct gpio_irq_chip *girq;
	int irq, ret;
	u32 initial_data, initial_direction;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	priv->dev = &pdev->dev;
	priv->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);
	priv->clk = devm_clk_get_optional(&pdev->dev, NULL);
	if (IS_ERR(priv->clk) && PTR_ERR(priv->clk) == -EPROBE_DEFER)
		return -EPROBE_DEFER;

	gc = &priv->chip;
	gc->label = dev_name(&pdev->dev);
	gc->parent = &pdev->dev;
	gc->owner = THIS_MODULE;
	gc->ngpio = 32;
	gc->base = -1;
	gc->get = ftgpio_gpio_probe__gpio_generic_get;
	gc->get_multiple = ftgpio_gpio_probe__gpio_generic_get_multiple;
	gc->set = ftgpio_gpio_probe__gpio_generic_set;
	gc->set_multiple = ftgpio_gpio_probe__gpio_generic_set_multiple;
	gc->direction_input = ftgpio_gpio_probe__gpio_generic_direction_input;
	gc->direction_output = ftgpio_gpio_probe__gpio_generic_direction_output;
	gc->get_direction = ftgpio_gpio_probe__gpio_generic_get_direction;
	if (!IS_ERR(priv->clk))
		gc->set_config = ftgpio_gpio_set_config;

	/* REHARNESS_RIS_OP id=op_43 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_43: { initial_data = readl(priv->base + GPIO_DATA_IN); }
	priv->gpio_initial_data = initial_data;
	/* REHARNESS_RIS_OP id=op_45 kind=Read status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_45: { initial_direction = readl(priv->base + GPIO_DIR); }
	priv->gpio_initial_direction = initial_direction;

	girq = &gc->irq;
	girq->parent_handler = ftgpio_gpio_irq_handler;
	girq->num_parents = 0;
	girq->parents = devm_kcalloc(&pdev->dev, 1, sizeof(*girq->parents), GFP_KERNEL);
	if (!girq->parents)
		return -ENOMEM;
	irq = platform_get_irq(pdev, 0);
	if (irq == -EPROBE_DEFER)
		return irq;
	if (irq >= 0) {
		girq->num_parents = 1;
		girq->parents[0] = irq;
	}
	girq->default_type = IRQ_TYPE_NONE;
	girq->handler = handle_bad_irq;
	gpio_irq_chip_set_chip(girq, &ftgpio_irq_chip);

	/* REHARNESS_RIS_OP id=op_56 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_56: { writel(0, priv->base + GPIO_INT_EN); }
	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_57: { writel(0, priv->base + GPIO_INT_MASK); }
	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_58: { writel(0xffffffffU, priv->base + GPIO_INT_CLR); }
	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=26974218f8297a1db02fa2d2c0a776cd7d90bb591cc8f1e9771d04128c97a9da */
__rh_op_op_59: { writel(0, priv->base + GPIO_DEBOUNCE_EN); }

	platform_set_drvdata(pdev, priv);
	ret = devm_gpiochip_add_data(&pdev->dev, gc, priv);
	if (ret)
		return ret;
	return 0;
}

static const struct platform_device_id ftgpio_gpio_id_table[] = {
	{ "ftgpio010", 0 },
	{ "ftgpio010_gpio", 0 },
	{ }
};
MODULE_DEVICE_TABLE(platform, ftgpio_gpio_id_table);

static const struct of_device_id ftgpio_gpio_of_match[] = {
	{ .compatible = "ftgpio010" },
	{ .compatible = "ftgpio010,gpio" },
	{ }
};
MODULE_DEVICE_TABLE(of, ftgpio_gpio_of_match);

static struct platform_driver ftgpio_gpio_driver = {
	.probe = ftgpio_gpio_probe,
	.id_table = ftgpio_gpio_id_table,
	.driver = {
		.name = "ftgpio010",
		.of_match_table = ftgpio_gpio_of_match,
	},
};

module_platform_driver(ftgpio_gpio_driver);

MODULE_ALIAS("platform:ftgpio010_gpio");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("FTGPIO010 GPIO controller driver");
