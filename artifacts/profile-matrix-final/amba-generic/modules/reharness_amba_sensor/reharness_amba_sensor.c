// SPDX-License-Identifier: GPL-2.0-only
/* Candidate-style AMBA driver used by the generic profile fixture. */
#include <linux/amba/bus.h>
#include <linux/module.h>

#define REHARNESS_AMBA_PERIPHID 0x00100001

static int reharness_amba_sensor_probe(struct amba_device *adev,
					       const struct amba_id *id)
{
	if (resource_size(&adev->res) != 0x1000) {
		dev_err(&adev->dev,
			"REHARNESS_AMBA_DRIVER_PROBE_FAILED resource_size=0x%llx\n",
			(unsigned long long)resource_size(&adev->res));
		return -EINVAL;
	}

	dev_info(&adev->dev,
		 "REHARNESS_AMBA_DRIVER_PROBE periphid=0x%08x resource=0x%llx\n",
		 adev->periphid, (unsigned long long)resource_size(&adev->res));
	return 0;
}

static void reharness_amba_sensor_remove(struct amba_device *adev)
{
	dev_info(&adev->dev, "REHARNESS_AMBA_DRIVER_REMOVE\n");
}

static const struct amba_id reharness_amba_sensor_ids[] = {
	{ .id = REHARNESS_AMBA_PERIPHID, .mask = 0xffffffff },
	{ 0, 0 },
};

static struct amba_driver reharness_amba_sensor_driver = {
	.drv = {
		.name = "reharness_amba_sensor",
	},
	.id_table = reharness_amba_sensor_ids,
	.probe = reharness_amba_sensor_probe,
	.remove = reharness_amba_sensor_remove,
};

module_amba_driver(reharness_amba_sensor_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic AMBA driver fixture");
