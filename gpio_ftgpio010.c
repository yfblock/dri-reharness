// SPDX-License-Identifier: GPL-2.0
/*
 * Faraday FTGPIO010 GPIO driver (reharness)
 * module name: gpio_ftgpio010
 */
#include <linux/bitops.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio/driver.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/irq.h>
#include <linux/pinctrl/pinconf-generic.h>

/* Register offsets */
#define GPIO_DATA_OUT		0x00
#define GPIO_DATA_IN		0x04
#define GPIO_DIR		0x08
#define GPIO_BYPASS_IN		0x0C
#define GPIO_DATA_SET		0x10
#define GPIO_DATA_CLR		0x14
#define GPIO_PULL_EN		0x18
#define GPIO_PULL_TYPE		0x1C
#define GPIO_INT_EN		0x20
#define GPIO_INT_STAT_RAW	0x24
#define GPIO_INT_STAT_MASKED	0x28
#define GPIO_INT_MASK		0x2C
#define GPIO_INT_CLR		0x30
#define GPIO_INT_TYPE		0x34
#define GPIO_INT_BOTH_EDGE	0x38
#define GPIO_INT_LEVEL		0x3C
#define GPIO_DEBOUNCE_EN	0x40
#define GPIO_DEBOUNCE_PRESCALE	0x44

struct ftgpio_gpio {
	struct device *dev;
	void __iomem *base;
	struct gpio_chip gc;
};

/* ---- IRQ callbacks (defined but NOT registered; no request_irq in probe) ---- */

static void __maybe_unused ftgpio_gpio_ack_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct ftgpio_gpio *g = gpiochip_get_data(gc);

	writel(BIT(irqd_to_hwirq(d)), g->base + GPIO_INT_CLR);
}

static void __maybe_unused ftgpio_gpio_mask_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 val;

	val = readl(g->base + GPIO_INT_EN);
	val &= ~BIT(irqd_to_hwirq(d));
	writel(val, g->base + GPIO_INT_EN);
}

static void __maybe_unused ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 val;

	val = readl(g->base + GPIO_INT_EN);
	val |= BIT(irqd_to_hwirq(d));
	writel(val, g->base + GPIO_INT_EN);
}

static int __maybe_unused ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	struct gpio_chip *gc = irq_data_get_irq_chip_data(d);
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	irq_hw_number_t hwirq = irqd_to_hwirq(d);
	u32 reg_type, reg_level, reg_both;

	reg_type = readl(g->base + GPIO_INT_TYPE);
	reg_level = readl(g->base + GPIO_INT_LEVEL);
	reg_both = readl(g->base + GPIO_INT_BOTH_EDGE);

	switch (type) {
	case IRQ_TYPE_EDGE_RISING:
		reg_type |= BIT(hwirq);
		reg_level |= BIT(hwirq);
		reg_both &= ~BIT(hwirq);
		break;
	case IRQ_TYPE_EDGE_FALLING:
		reg_type |= BIT(hwirq);
		reg_level &= ~BIT(hwirq);
		reg_both &= ~BIT(hwirq);
		break;
	case IRQ_TYPE_EDGE_BOTH:
		reg_type |= BIT(hwirq);
		reg_both |= BIT(hwirq);
		break;
	case IRQ_TYPE_LEVEL_HIGH:
		reg_type &= ~BIT(hwirq);
		reg_level |= BIT(hwirq);
		break;
	case IRQ_TYPE_LEVEL_LOW:
		reg_type &= ~BIT(hwirq);
		reg_level &= ~BIT(hwirq);
		break;
	default:
		return -EINVAL;
	}

	writel(reg_type, g->base + GPIO_INT_TYPE);
	writel(reg_level, g->base + GPIO_INT_LEVEL);
	writel(reg_both, g->base + GPIO_INT_BOTH_EDGE);

	return 0;
}

static void __maybe_unused ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	struct gpio_chip *gc = irq_desc_get_handler_data(desc);
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	unsigned long stat;

	stat = readl(g->base + GPIO_INT_STAT_RAW);
	(void)stat;
}

/* ---- GPIO chip callbacks (per .ris) ---- */

static int ftgpio_gpio_get_direction(struct gpio_chip *gc, unsigned int offset)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);

	if (readl(g->base + GPIO_DIR) & BIT(offset))
		return GPIO_LINE_DIRECTION_OUT;
	return GPIO_LINE_DIRECTION_IN;
}

static int ftgpio_gpio_direction_input(struct gpio_chip *gc, unsigned int offset)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 val;

	val = readl(g->base + GPIO_DIR);
	val &= ~BIT(offset);
	writel(val, g->base + GPIO_DIR);

	return 0;
}

static int ftgpio_gpio_direction_output(struct gpio_chip *gc,
					unsigned int offset, int value)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 val;

	/* Set output value first to avoid glitches */
	val = readl(g->base + GPIO_DATA_OUT);
	if (value)
		val |= BIT(offset);
	else
		val &= ~BIT(offset);
	writel(val, g->base + GPIO_DATA_OUT);

	/* Then set direction to output */
	val = readl(g->base + GPIO_DIR);
	val |= BIT(offset);
	writel(val, g->base + GPIO_DIR);

	return 0;
}

static int ftgpio_gpio_get(struct gpio_chip *gc, unsigned int offset)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);

	return !!(readl(g->base + GPIO_DATA_IN) & BIT(offset));
}

static int ftgpio_gpio_set(struct gpio_chip *gc, unsigned int offset, int value)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 val;

	val = readl(g->base + GPIO_DATA_OUT);
	if (value)
		val |= BIT(offset);
	else
		val &= ~BIT(offset);
	writel(val, g->base + GPIO_DATA_OUT);

	return 0;
}

static int ftgpio_gpio_set_config(struct gpio_chip *gc, unsigned int offset,
				  unsigned long config)
{
	struct ftgpio_gpio *g = gpiochip_get_data(gc);
	u32 deb_div = pinconf_to_config_argument(config);
	u32 val;

	if (pinconf_to_config_param(config) != PIN_CONFIG_INPUT_DEBOUNCE)
		return -ENOTSUPP;

	val = readl(g->base + GPIO_DEBOUNCE_PRESCALE);
	if (val == deb_div) {
		val = readl(g->base + GPIO_DEBOUNCE_EN);
		val |= BIT(offset);
		writel(val, g->base + GPIO_DEBOUNCE_EN);
		return 0;
	}

	val = readl(g->base + GPIO_DEBOUNCE_EN);
	writel(deb_div, g->base + GPIO_DEBOUNCE_PRESCALE);
	val |= BIT(offset);
	writel(val, g->base + GPIO_DEBOUNCE_EN);

	return 0;
}

/* ---- Platform driver ---- */

static int ftgpio_gpio_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct ftgpio_gpio *g;
	struct resource *res;

	g = devm_kzalloc(dev, sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;

	g->dev = dev;

	res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	g->base = devm_ioremap_resource(dev, res);
	if (IS_ERR(g->base))
		return PTR_ERR(g->base);

	/* Hardware init (ris: ftgpio_gpio_probe) */
	writel(0x0, g->base + GPIO_INT_EN);
	writel(0x0, g->base + GPIO_INT_MASK);
	writel((0x0 ^ 0xffffffff), g->base + GPIO_INT_CLR);
	writel(0x0, g->base + GPIO_DEBOUNCE_EN);

	g->gc.parent = dev;
	g->gc.label = "ftgpio010";
	g->gc.base = -1;
	g->gc.ngpio = 8;
	g->gc.owner = THIS_MODULE;
	g->gc.get_direction = ftgpio_gpio_get_direction;
	g->gc.direction_input = ftgpio_gpio_direction_input;
	g->gc.direction_output = ftgpio_gpio_direction_output;
	g->gc.get = ftgpio_gpio_get;
	g->gc.set = ftgpio_gpio_set;
	g->gc.set_config = ftgpio_gpio_set_config;

	platform_set_drvdata(pdev, g);

	return devm_gpiochip_add_data(dev, &g->gc, g);
}

static void ftgpio_gpio_remove(struct platform_device *pdev)
{
}

static const struct of_device_id ftgpio_gpio_of_match[] = {
	{ .compatible = "faraday,ftgpio010", },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, ftgpio_gpio_of_match);

static struct platform_driver ftgpio_gpio_driver = {
	.probe = ftgpio_gpio_probe,
	.remove = ftgpio_gpio_remove,
	.driver = {
		.name = KBUILD_MODNAME,
		.of_match_table = ftgpio_gpio_of_match,
	},
};
module_platform_driver(ftgpio_gpio_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Faraday FTGPIO010 GPIO driver");
