// SPDX-License-Identifier: GPL-2.0
#include <linux/module.h>
#include <linux/platform_device.h>

static int fixture_platform_probe(struct platform_device *pdev)
{
	dev_info(&pdev->dev, "PROFILE_PLATFORM_PROBE\n");
	return 0;
}

static void fixture_platform_remove(struct platform_device *pdev)
{
	dev_info(&pdev->dev, "PROFILE_PLATFORM_REMOVE\n");
}

static struct platform_driver fixture_platform_driver = {
	.driver = {
		.name = "fixture_platform_client",
	},
	.probe = fixture_platform_probe,
	.remove = fixture_platform_remove,
};

module_platform_driver(fixture_platform_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Generic platform profile fixture client");
