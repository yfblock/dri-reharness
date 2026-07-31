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
#include <linux/platform_device.h>
#include <linux/ioport.h>

static char *target = "my-watchdog";
module_param(target, charp, 0644);
MODULE_PARM_DESC(target, "Platform device name (= driver name)");

static struct platform_device *pdev;

/* MMIO 资源：地址在 QEMU RAM 范围内，ioremap 映射到真实内存 */
static struct resource mock_res[] = {
	{
		.start = 0xF0000000,   /* 在 256MB RAM 之外 — 避免 request_mem_region 与 System RAM 冲突 (-EBUSY)，且现代内核禁止 ioremap RAM */
		.end   = 0xF0000FFF,   /* 4KB；QEMU 对未分配 MMIO 读返回 0、写丢弃，不会崩溃 */
		.flags = IORESOURCE_MEM,
		.name  = "mock-regs",
	},
};

static int __init device_registrar_init(void)
{
	int ret;

	pr_info("device-registrar: 注册 '%s' (MMIO @ 0xF0000000)\n", target);

	pdev = platform_device_alloc(target, -1);
	if (!pdev) {
		pr_err("device-registrar: alloc 失败\n");
		return -ENOMEM;
	}

	ret = platform_device_add_resources(pdev, mock_res, 1);
	if (ret) {
		pr_err("device-registrar: 添加资源失败 (%d)\n", ret);
		platform_device_put(pdev);
		return ret;
	}

	ret = platform_device_add(pdev);
	if (ret) {
		pr_err("device-registrar: 注册失败 (%d)\n", ret);
		platform_device_put(pdev);
		return ret;
	}

	pr_info("device-registrar: '%s' 已注册\n", target);
	return 0;
}

static void __exit device_registrar_exit(void)
{
	if (pdev)
		platform_device_unregister(pdev);
	pr_info("device-registrar: '%s' 已注销\n", target);
}

module_init(device_registrar_init);
module_exit(device_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Register platform device with RAM-backed MMIO");
