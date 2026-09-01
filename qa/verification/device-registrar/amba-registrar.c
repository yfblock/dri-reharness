// SPDX-License-Identifier: GPL-2.0-only
/* Deterministic AMBA device fixture for the generic profile runtime. */
#include <linux/amba/bus.h>
#include <linux/clk-provider.h>
#include <linux/clkdev.h>
#include <linux/err.h>
#include <linux/module.h>

#define REHARNESS_AMBA_PERIPHID 0x00100001
#define REHARNESS_AMBA_BASE 0x180000000ULL
#define REHARNESS_AMBA_SIZE 0x1000

static struct amba_device *reharness_amba_device;
static struct clk *reharness_amba_pclk;
static struct clk_lookup *reharness_amba_pclk_lookup;

static int __init reharness_amba_registrar_init(void)
{
	int ret;

	reharness_amba_pclk = clk_register_fixed_rate(
		NULL, "reharness-amba-apb-pclk", NULL, 0, 1000000);
	if (IS_ERR(reharness_amba_pclk))
		return PTR_ERR(reharness_amba_pclk);

	reharness_amba_pclk_lookup = clkdev_create(
		reharness_amba_pclk, "apb_pclk", "reharness-amba");
	if (!reharness_amba_pclk_lookup) {
		clk_unregister_fixed_rate(reharness_amba_pclk);
		reharness_amba_pclk = NULL;
		return -ENOMEM;
	}

	reharness_amba_device = amba_device_alloc(
		"reharness-amba", REHARNESS_AMBA_BASE, REHARNESS_AMBA_SIZE);
	if (!reharness_amba_device) {
		clkdev_drop(reharness_amba_pclk_lookup);
		clk_unregister_fixed_rate(reharness_amba_pclk);
		reharness_amba_pclk_lookup = NULL;
		reharness_amba_pclk = NULL;
		return -ENOMEM;
	}

	/* A hard-coded peripheral ID avoids requiring real AMBA MMIO registers. */
	reharness_amba_device->periphid = REHARNESS_AMBA_PERIPHID;
	ret = amba_device_add(reharness_amba_device, &iomem_resource);
	if (ret) {
		pr_err("REHARNESS_AMBA_DEVICE_ADD_FAILED ret=%d start=0x%llx size=0x%llx\n",
			ret,
			(unsigned long long)reharness_amba_device->res.start,
			(unsigned long long)resource_size(&reharness_amba_device->res));
		amba_device_put(reharness_amba_device);
		reharness_amba_device = NULL;
		clkdev_drop(reharness_amba_pclk_lookup);
		clk_unregister_fixed_rate(reharness_amba_pclk);
		reharness_amba_pclk_lookup = NULL;
		reharness_amba_pclk = NULL;
		return ret;
	}

	pr_info("REHARNESS_AMBA_DEVICE_READY name=%s periphid=0x%08x\n",
		dev_name(&reharness_amba_device->dev),
		reharness_amba_device->periphid);
	return 0;
}

static void __exit reharness_amba_registrar_exit(void)
{
	if (reharness_amba_device) {
		amba_device_unregister(reharness_amba_device);
		reharness_amba_device = NULL;
	}
	if (reharness_amba_pclk_lookup) {
		clkdev_drop(reharness_amba_pclk_lookup);
		reharness_amba_pclk_lookup = NULL;
	}
	if (reharness_amba_pclk) {
		clk_unregister_fixed_rate(reharness_amba_pclk);
		reharness_amba_pclk = NULL;
	}
	pr_info("REHARNESS_AMBA_REGISTRAR_UNLOADED\n");
}

module_init(reharness_amba_registrar_init);
module_exit(reharness_amba_registrar_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic AMBA device fixture");
