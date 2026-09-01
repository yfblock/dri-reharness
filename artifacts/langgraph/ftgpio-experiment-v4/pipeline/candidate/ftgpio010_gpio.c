#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/irq.h>
#include <linux/gpio/driver.h>
#include <linux/interrupt.h>
#include <linux/offsetof.h>

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

#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#define readl(p) ({ u32 __v = __raw_readl(p); pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })

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

#ifndef IRQ_TYPE_NONE
#define IRQ_TYPE_NONE 0
#define IRQ_TYPE_EDGE_RISING 1
#define IRQ_TYPE_EDGE_FALLING 2
#define IRQ_TYPE_EDGE_BOTH (IRQ_TYPE_EDGE_RISING | IRQ_TYPE_EDGE_FALLING)
#define IRQ_TYPE_LEVEL_HIGH 4
#define IRQ_TYPE_LEVEL_LOW 8
#endif

#ifndef handle_bad_irq
#define handle_bad_irq NULL
#endif

struct gpio_ftgpio010 {
	void __iomem *base;
	struct gpio_chip chip;
	struct device *dev;
	unsigned int gpio_sdata;
	unsigned int gpio_sdir;
	void *clk;
	struct irq_chip irq_chip;
	struct gpio_irq_chip gpio_irq;
};

struct driver_priv {
	void __iomem *base;
	struct miscdevice misc;
	struct device *dev;
	struct gpio_ftgpio010 g;
};

static inline struct gpio_ftgpio010 *to_g(struct gpio_chip *gc)
{
	RH_TRACE_FN("to_g");
	return (struct gpio_ftgpio010 *)((char *)gc - offsetof(struct gpio_ftgpio010, chip));
}

static inline struct driver_priv *to_priv_from_gc(struct gpio_chip *gc)
{
	RH_TRACE_FN("to_priv_from_gc");
	struct gpio_ftgpio010 *g = to_g(gc);
	return (struct driver_priv *)((char *)g - offsetof(struct driver_priv, g));
}

static void ftgpio_gpio_ack_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_ack_irq");
	struct driver_priv *priv = NULL;
	void __iomem *base = priv ? priv->base : NULL;
	if (!base)
		return;
	/* REHARNESS_RIS_OP id=op_1 kind=Write status=lowered digest=5dd3bb35656acca9 */
	writel((0x1 << d->hwirq), base + GPIO_INT_CLR);
}

static void ftgpio_gpio_mask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_mask_irq");
	struct driver_priv *priv = NULL;
	void __iomem *base = priv ? priv->base : NULL;
	u32 val;
	if (!base)
		return;
	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	val = readl(base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_3 kind=ReadModifyWrite status=lowered digest=35b8bf6436435508 */
	writel((val & (~(0x1 << d->hwirq))), base + GPIO_INT_EN);
}

static void ftgpio_gpio_unmask_irq(struct irq_data *d)
{
	RH_TRACE_FN("ftgpio_gpio_unmask_irq");
	struct driver_priv *priv = NULL;
	void __iomem *base = priv ? priv->base : NULL;
	u32 val;
	if (!base)
		return;
	/* REHARNESS_RIS_OP id=op_4 kind=Read status=lowered digest=67a27c7ab6f431e2 */
	val = readl(base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_5 kind=ReadModifyWrite status=lowered digest=d8ab399a3e165c09 */
	writel((val | (0x1 << d->hwirq)), base + GPIO_INT_EN);
}

static int ftgpio_gpio_set_irq_type(struct irq_data *d, unsigned int type)
{
	RH_TRACE_FN("ftgpio_gpio_set_irq_type");
	struct driver_priv *priv = NULL;
	void __iomem *base = priv ? priv->base : NULL;
	u32 reg_type, reg_level, reg_both;
	u32 mask = (0x1 << d->hwirq);

	if (!base)
		return -EINVAL;

	/* REHARNESS_RIS_OP id=op_6 kind=Read status=lowered digest=b359d00e3d754d3e */
	reg_type = readl(base + GPIO_INT_TYPE);
	/* REHARNESS_RIS_OP id=op_7 kind=Read status=lowered digest=85db95e4e47b9e4c */
	reg_level = readl(base + GPIO_INT_LEVEL);
	/* REHARNESS_RIS_OP id=op_8 kind=Read status=lowered digest=6642efb8949d9184 */
	reg_both = readl(base + GPIO_INT_BOTH_EDGE);

	if (type == IRQ_TYPE_EDGE_BOTH) {
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both | mask);
		d->hwirq = d->hwirq;
	} else if (type == IRQ_TYPE_EDGE_RISING) {
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both & (~mask));
		reg_level = (reg_level & (~mask));
	} else if (type == IRQ_TYPE_EDGE_FALLING) {
		reg_type = (reg_type & (~mask));
		reg_both = (reg_both & (~mask));
		reg_level = (reg_level | mask);
	} else if (type == IRQ_TYPE_LEVEL_HIGH) {
		reg_type = (reg_type | mask);
		reg_level = (reg_level & (~mask));
	} else if (type == IRQ_TYPE_LEVEL_LOW) {
		reg_type = (reg_type | mask);
		reg_level = (reg_level | mask);
	} else {
		return -EINVAL;
	}

	/* REHARNESS_RIS_OP id=op_27 kind=ReadModifyWrite status=lowered digest=d1c746cb513851b5 */
	writel(((type == IRQ_TYPE_EDGE_BOTH) ? (reg_type & (~mask)) : ((type == IRQ_TYPE_EDGE_RISING) ? (reg_type & (~mask)) : ((type == IRQ_TYPE_EDGE_FALLING) ? (reg_type & (~mask)) : ((type == IRQ_TYPE_LEVEL_HIGH) ? (reg_type | mask) : ((type == IRQ_TYPE_LEVEL_LOW) ? (reg_type | mask) : reg_type))))), base + GPIO_INT_TYPE);
	/* REHARNESS_RIS_OP id=op_28 kind=ReadModifyWrite status=lowered digest=26d436ff936be225 */
	writel(((type == IRQ_TYPE_EDGE_BOTH) ? reg_level : ((type == IRQ_TYPE_EDGE_RISING) ? (reg_level & (~mask)) : ((type == IRQ_TYPE_EDGE_FALLING) ? (reg_level | mask) : ((type == IRQ_TYPE_LEVEL_HIGH) ? (reg_level & (~mask)) : ((type == IRQ_TYPE_LEVEL_LOW) ? (reg_level | mask) : reg_level))))), base + GPIO_INT_LEVEL);
	/* REHARNESS_RIS_OP id=op_29 kind=ReadModifyWrite status=lowered digest=64b0966d1739dce7 */
	writel(((type == IRQ_TYPE_EDGE_BOTH) ? (reg_both | mask) : ((type == IRQ_TYPE_EDGE_RISING) ? (reg_both & (~mask)) : ((type == IRQ_TYPE_EDGE_FALLING) ? (reg_both & (~mask)) : ((type == IRQ_TYPE_LEVEL_HIGH) ? reg_both : ((type == IRQ_TYPE_LEVEL_LOW) ? reg_both : reg_both))))), base + GPIO_INT_BOTH_EDGE);

	return 0;
}

static void ftgpio_gpio_irq_handler(struct irq_desc *desc)
{
	RH_TRACE_FN("ftgpio_gpio_irq_handler");
	struct driver_priv *priv = NULL;
	void __iomem *base = priv ? priv->base : NULL;
	struct gpio_irq_chip *irqchip = NULL;
	u32 stat;

	if (!base)
		return;

	if (irqchip && irqchip->irq_ack == NULL) {
		if (irqchip->irq_ack) {
			/* REHARNESS_RIS_OP id=op_30 kind=Write status=lowered digest=93a501c95c7a42f2 */
			writel((0x1 << desc->irq_data.hwirq), base + GPIO_INT_CLR);
		}
	}

	/* REHARNESS_RIS_OP id=op_31 kind=Read status=lowered digest=e74749be940967d5 */
	stat = readl(base + GPIO_INT_STAT_RAW);
	(void)stat;
}

static int ftgpio_gpio_set_config(struct gpio_chip *gc, unsigned int offset, unsigned long config)
{
	RH_TRACE_FN("ftgpio_gpio_set_config");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 val;
	u32 deb_div = (u32)config;

	if (!base)
		return -EINVAL;

	/* REHARNESS_RIS_OP id=op_32 kind=Read status=lowered digest=8eb491b0c0634ba7 */
	val = readl(base + GPIO_DEBOUNCE_PRESCALE);
	if (val == deb_div) {
		/* REHARNESS_RIS_OP id=op_33 kind=Read status=lowered digest=48230cd8ed117ec6 */
		val = readl(base + GPIO_DEBOUNCE_EN);
		val = (val | (0x1 << offset));
		/* REHARNESS_RIS_OP id=op_35 kind=ReadModifyWrite status=lowered digest=81000a354c140fe1 */
		writel(((val == deb_div) ? (val | (0x1 << offset)) : val), base + GPIO_DEBOUNCE_EN);
	}

	/* REHARNESS_RIS_OP id=op_36 kind=Read status=lowered digest=339408230d26d326 */
	val = readl(base + GPIO_DEBOUNCE_EN);
	/* REHARNESS_RIS_OP id=op_37 kind=Write status=lowered digest=a89c06a8b813ae48 */
	writel(deb_div, base + GPIO_DEBOUNCE_PRESCALE);
	val = (val | (0x1 << offset));
	/* REHARNESS_RIS_OP id=op_39 kind=ReadModifyWrite status=lowered digest=a6b3f48cd0fe1e05 */
	writel((val | (0x1 << offset)), base + GPIO_DEBOUNCE_EN);
	return 0;
}

static int ftgpio_gpio_probe__gpio_generic_get(struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_61 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	value = readl(base + GPIO_DATA_IN);
	return ((value & (0x1 << offset)) != 0x0);
}

static int ftgpio_gpio_probe__gpio_generic_get_multiple(struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_multiple");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 value;

	/* REHARNESS_RIS_OP id=op_63 kind=Read status=lowered digest=a2dc39d9a87e4bf7 */
	value = readl(base + GPIO_DATA_IN);
	*bits = ((*bits & (~*mask)) | (value & *mask));
	return 0x0;
}

static int ftgpio_gpio_probe__gpio_generic_set(struct gpio_chip *gc, unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;

	if (value != 0x0) {
		/* REHARNESS_RIS_OP id=op_66 kind=Write status=lowered digest=b36eb49659ebc50a */
		writel((0x1 << offset), base + GPIO_DATA_SET);
	}
	if (value == 0x0) {
		/* REHARNESS_RIS_OP id=op_67 kind=Write status=lowered digest=3834a18c428720bf */
		writel((0x1 << offset), base + GPIO_DATA_CLR);
	}
	return 0x0;
}

static int ftgpio_gpio_probe__gpio_generic_set_multiple(struct gpio_chip *gc, unsigned long *mask, unsigned long *bits)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_set_multiple");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;

	if ((*bits & *mask) != 0x0) {
		/* REHARNESS_RIS_OP id=op_69 kind=Write status=lowered digest=ab8d874dfdeeade8 */
		writel((*bits & *mask), base + GPIO_DATA_SET);
	}
	if (((~*bits) & *mask) != 0x0) {
		/* REHARNESS_RIS_OP id=op_70 kind=Write status=lowered digest=5f32f4874eb9aabb */
		writel(((~*bits) & *mask), base + GPIO_DATA_CLR);
	}
	return 0x0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_input(struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_input");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	unsigned int __shadow_dir;

	__shadow_dir = priv->g.gpio_sdir;
	priv->g.gpio_sdir = (__shadow_dir & (~(0x1 << offset)));
	/* REHARNESS_RIS_OP id=op_74 kind=Write status=lowered digest=b949672343e78260 */
	writel((__shadow_dir & (~(0x1 << offset))), base + GPIO_DIR);
	return 0x0;
}

static int ftgpio_gpio_probe__gpio_generic_direction_output(struct gpio_chip *gc, unsigned int offset, int value)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_direction_output");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	unsigned int __shadow_dir;

	if (value != 0x0) {
		/* REHARNESS_RIS_OP id=op_76 kind=Write status=lowered digest=b36eb49659ebc50a */
		writel((0x1 << offset), base + GPIO_DATA_SET);
	}
	if (value == 0x0) {
		/* REHARNESS_RIS_OP id=op_77 kind=Write status=lowered digest=3834a18c428720bf */
		writel((0x1 << offset), base + GPIO_DATA_CLR);
	}
	__shadow_dir = priv->g.gpio_sdir;
	priv->g.gpio_sdir = (__shadow_dir | (0x1 << offset));
	/* REHARNESS_RIS_OP id=op_80 kind=Write status=lowered digest=43d76c2e0b3f2385 */
	writel((__shadow_dir | (0x1 << offset)), base + GPIO_DIR);
	return 0x0;
}

static int ftgpio_gpio_probe__gpio_generic_get_direction(struct gpio_chip *gc, unsigned int offset)
{
	RH_TRACE_FN("ftgpio_gpio_probe__gpio_generic_get_direction");
	struct driver_priv *priv = to_priv_from_gc(gc);
	void __iomem *base = priv->base;
	u32 direction;

	/* REHARNESS_RIS_OP id=op_82 kind=Read status=lowered digest=9d0c4bdae3641bba */
	direction = readl(base + GPIO_DIR);
	return (((direction & (0x1 << offset)) != 0x0) ? 0x0 : 0x1);
}

static int ftgpio_gpio_probe(struct platform_device *pdev)
{
	RH_TRACE_FN("ftgpio_gpio_probe");
	struct driver_priv *priv;
	struct gpio_irq_chip *girq;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->dev = &pdev->dev;
	priv->base = devm_platform_ioremap_resource(pdev, 0);
	RH_SET_BASE(priv->base);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);


	priv->g.base = priv->base;
	priv->g.dev = priv->dev;
	priv->g.chip.base = -1;
	priv->g.chip.parent = &pdev->dev;
	priv->g.chip.owner = THIS_MODULE;
	priv->g.chip.set_config = ftgpio_gpio_set_config;
	priv->g.chip.direction_input = ftgpio_gpio_probe__gpio_generic_direction_input;
	priv->g.chip.direction_output = ftgpio_gpio_probe__gpio_generic_direction_output;
	priv->g.chip.get = ftgpio_gpio_probe__gpio_generic_get;
	priv->g.chip.get_direction = ftgpio_gpio_probe__gpio_generic_get_direction;
	priv->g.chip.get_multiple = ftgpio_gpio_probe__gpio_generic_get_multiple;
	priv->g.chip.set = ftgpio_gpio_probe__gpio_generic_set;
	priv->g.chip.set_multiple = ftgpio_gpio_probe__gpio_generic_set_multiple;

	priv->g.irq_chip.name = "gpio-ftgpio010-irqchip";
	priv->g.irq_chip.irq_ack = ftgpio_gpio_ack_irq;
	priv->g.irq_chip.irq_mask = ftgpio_gpio_mask_irq;
	priv->g.irq_chip.irq_unmask = ftgpio_gpio_unmask_irq;
	priv->g.irq_chip.irq_set_type = ftgpio_gpio_set_irq_type;

	girq = &priv->g.gpio_irq;
	girq->parent_handler = ftgpio_gpio_irq_handler;
	girq->num_parents = 0x1;
	girq->default_type = IRQ_TYPE_NONE;
	girq->handler = handle_bad_irq;
	girq->chip = &priv->g.irq_chip;

	/* REHARNESS_RIS_OP id=op_43 kind=Read status=lowered digest=16d85024e558eaef */
	priv->g.gpio_sdata = readl(priv->base + GPIO_DATA_IN);
	priv->g.gpio_sdata = priv->g.gpio_sdata;
	/* REHARNESS_RIS_OP id=op_45 kind=Read status=lowered digest=e9b515951bfad9ea */
	priv->g.gpio_sdir = readl(priv->base + GPIO_DIR);
	priv->g.gpio_sdir = priv->g.gpio_sdir;

	/* REHARNESS_RIS_OP id=op_56 kind=Write status=lowered digest=7443390abf8fb623 */
	writel(0x0, priv->base + GPIO_INT_EN);
	/* REHARNESS_RIS_OP id=op_57 kind=Write status=lowered digest=015d9e37bb50b02a */
	writel(0x0, priv->base + GPIO_INT_MASK);
	/* REHARNESS_RIS_OP id=op_58 kind=Write status=lowered digest=153d39994bb1ba88 */
	writel(0xffffffff, priv->base + GPIO_INT_CLR);
	/* REHARNESS_RIS_OP id=op_59 kind=Write status=lowered digest=92b66149c6b53a4a */
	writel(0x0, priv->base + GPIO_DEBOUNCE_EN);


	if (devm_gpiochip_add_data(&pdev->dev, &priv->g.chip, priv))
		return -EINVAL;

	return 0;
}

static void ftgpio_platform_remove(struct platform_device *pdev)
{
	RH_TRACE_FN("ftgpio_platform_remove");
	(void)pdev;
}

static struct platform_driver ftgpio_platform_driver = {
	.probe = ftgpio_gpio_probe,
	.remove = ftgpio_platform_remove,
	.driver = {
		.name = "gpio-ftgpio010",
	},
};

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("gpio-ftgpio010 synthesized implementation");
module_platform_driver(ftgpio_platform_driver);
