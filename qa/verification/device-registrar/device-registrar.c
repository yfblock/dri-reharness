// SPDX-License-Identifier: GPL-2.0
/*
 * device-registrar.c — 注册 platform device 触发驱动 probe
 * 用法: insmod device-registrar.ko target=my-watchdog
 *
 * MMIO 地址 0x08000000 在 QEMU 256MB RAM 范围内，
 * ioremap 会映射到真实 RAM，readl/writel 不会崩溃。
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/clk-provider.h>
#include <linux/clkdev.h>
#include <linux/completion.h>
#include <linux/fs.h>
#include <linux/gpio/driver.h>
#include <linux/irqdesc.h>
#include <linux/miscdevice.h>
#include <linux/platform_device.h>
#include <linux/ioport.h>
#include <linux/irq_work.h>
#include <linux/mutex.h>
#include <linux/uaccess.h>

static char *target = "my-watchdog";
module_param(target, charp, 0644);
MODULE_PARM_DESC(target, "Platform device name (= driver name)");

static int irq = 5;
module_param(irq, int, 0644);
MODULE_PARM_DESC(irq, "Synthetic parent IRQ resource");

static unsigned long clock_rate = 66000000;
module_param(clock_rate, ulong, 0644);
MODULE_PARM_DESC(clock_rate, "Synthetic peripheral clock rate for GPIO debounce");

static struct platform_device *pdev;
static struct clk *test_clk;
static struct clk_lookup *test_clk_lookup;
static struct irq_work gpio_parent_work;
static struct completion gpio_parent_done;
static DEFINE_MUTEX(gpio_control_lock);
static struct irq_domain *gpio_event_domain;
static unsigned int gpio_event_line;
static int gpio_event_result;

#define REHARNESS_GPIO_TRIGGER _IOW('R', 0x01, unsigned int)

static int gpio_control_match(struct gpio_chip *gc, const void *data)
{
	return gc && gc->irq.domain;
}

static void gpio_event_work_fn(struct irq_work *work)
{
	if (irq >= 0)
		generic_handle_irq(irq);
	if (gpio_event_domain)
		gpio_event_result = generic_handle_domain_irq(gpio_event_domain,
								     gpio_event_line);
	complete(&gpio_parent_done);
}

static long gpio_control_ioctl(struct file *file, unsigned int command,
			       unsigned long argument)
{
	struct gpio_device *gdev;
	struct gpio_chip *gc;
	unsigned int line;
	int ret;

	if (command != REHARNESS_GPIO_TRIGGER)
		return -ENOTTY;
	if (copy_from_user(&line, (void __user *)argument, sizeof(line)))
		return -EFAULT;
	mutex_lock(&gpio_control_lock);

	gdev = gpio_device_find_by_label(target);
	if (!gdev)
		gdev = gpio_device_find(NULL, gpio_control_match);
	if (!gdev) {
		ret = -ENODEV;
		goto out_unlock;
	}
	gc = gpio_device_get_chip(gdev);
	if (!gc || line >= gc->ngpio || !gc->irq.domain) {
		ret = -EINVAL;
		goto out_put;
	}

	/* Exercise the registered chained parent path, then inject a line event.
	 * The latter is deterministic because this registrar is a test fixture,
	 * not a replacement for a QEMU GPIO hardware model. */
	reinit_completion(&gpio_parent_done);
	gpio_event_domain = gc->irq.domain;
	gpio_event_line = line;
	gpio_event_result = -EIO;
	if (!irq_work_queue(&gpio_parent_work)
			|| wait_for_completion_timeout(&gpio_parent_done, HZ) == 0) {
		irq_work_sync(&gpio_parent_work);
		ret = -ETIMEDOUT;
		goto out_clear_event;
	}
	irq_work_sync(&gpio_parent_work);
	ret = gpio_event_result;

out_clear_event:
	gpio_event_domain = NULL;
out_put:
	gpio_device_put(gdev);
	out_unlock:
	mutex_unlock(&gpio_control_lock);
	return ret;
}

static const struct file_operations gpio_control_fops = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = gpio_control_ioctl,
};

static struct miscdevice gpio_control_device = {
	.minor = MISC_DYNAMIC_MINOR,
	.name = "reharness-gpio-control",
	.fops = &gpio_control_fops,
	.mode = 0666,
};

/* MMIO 资源：地址在 QEMU RAM 范围内，ioremap 映射到真实内存 */
static struct resource mock_res[] = {
	{
		.start = 0xF0000000,   /* 在 256MB RAM 之外 — 避免 request_mem_region 与 System RAM 冲突 (-EBUSY)，且现代内核禁止 ioremap RAM */
		.end   = 0xF0000FFF,   /* 4KB；QEMU 对未分配 MMIO 读返回 0、写丢弃，不会崩溃 */
		.flags = IORESOURCE_MEM,
		.name  = "mock-regs",
	},
	{
		.start = 5,
		.end   = 5,
		.flags = IORESOURCE_IRQ,
		.name  = "mock-irq",
	},
};

static int __init device_registrar_init(void)
{
	int ret;

	init_completion(&gpio_parent_done);
	init_irq_work(&gpio_parent_work, gpio_event_work_fn);

	mock_res[1].start = irq;
	mock_res[1].end = irq;

	pr_info("device-registrar: 注册 '%s' (MMIO @ 0xF0000000)\n", target);

	pdev = platform_device_alloc(target, -1);
	if (!pdev) {
		pr_err("device-registrar: alloc 失败\n");
		return -ENOMEM;
	}

	test_clk = clk_register_fixed_rate(NULL, "reharness-pclk", NULL, 0,
					   clock_rate);
	if (IS_ERR(test_clk)) {
		ret = PTR_ERR(test_clk);
		test_clk = NULL;
		platform_device_put(pdev);
		return ret;
	}
	test_clk_lookup = clkdev_create(test_clk, NULL, "%s", target);
	if (!test_clk_lookup) {
		clk_unregister_fixed_rate(test_clk);
		test_clk = NULL;
		platform_device_put(pdev);
		return -ENOMEM;
	}

	ret = platform_device_add_resources(pdev, mock_res, ARRAY_SIZE(mock_res));
	if (ret) {
		pr_err("device-registrar: 添加资源失败 (%d)\n", ret);
		clkdev_drop(test_clk_lookup);
		clk_unregister_fixed_rate(test_clk);
		test_clk_lookup = NULL;
		test_clk = NULL;
		platform_device_put(pdev);
		return ret;
	}

	ret = platform_device_add(pdev);
	if (ret) {
		pr_err("device-registrar: 注册失败 (%d)\n", ret);
		clkdev_drop(test_clk_lookup);
		clk_unregister_fixed_rate(test_clk);
		test_clk_lookup = NULL;
		test_clk = NULL;
		platform_device_put(pdev);
		return ret;
	}

	ret = misc_register(&gpio_control_device);
	if (ret) {
		platform_device_unregister(pdev);
		clkdev_drop(test_clk_lookup);
		clk_unregister_fixed_rate(test_clk);
		test_clk_lookup = NULL;
		test_clk = NULL;
		pdev = NULL;
		return ret;
	}

	pr_info("device-registrar: '%s' 已注册\n", target);
	return 0;
}

static void __exit device_registrar_exit(void)
{
	irq_work_sync(&gpio_parent_work);
	misc_deregister(&gpio_control_device);
	if (pdev)
		platform_device_unregister(pdev);
	if (test_clk_lookup)
		clkdev_drop(test_clk_lookup);
	if (test_clk)
		clk_unregister_fixed_rate(test_clk);
	pr_info("device-registrar: '%s' 已注销\n", target);
}

module_init(device_registrar_init);
module_exit(device_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Register platform device with RAM-backed MMIO");
