// SPDX-License-Identifier: GPL-2.0
/* Candidate-style MDIO device driver used by the generic profile fixture. */
#include <linux/mdio.h>
#include <linux/module.h>

#define REHARNESS_MDIO_REGISTER 0x10
#define REHARNESS_MDIO_EXPECTED_VALUE 0x5a5a

static int reharness_mdio_sensor_probe(struct mdio_device *mdiodev)
{
	int value;
	int ret;

	value = mdiodev_read(mdiodev, REHARNESS_MDIO_REGISTER);
	if (value != REHARNESS_MDIO_EXPECTED_VALUE) {
		dev_err(&mdiodev->dev,
			"REHARNESS_MDIO_DRIVER_PROBE_FAILED read=0x%x\n", value);
		return value < 0 ? value : -EIO;
	}

	ret = mdiodev_write(mdiodev, REHARNESS_MDIO_REGISTER, 0xa5a5);
	if (ret) {
		dev_err(&mdiodev->dev,
			"REHARNESS_MDIO_DRIVER_PROBE_FAILED write=%d\n", ret);
		return ret;
	}

	dev_info(&mdiodev->dev,
		 "REHARNESS_MDIO_DRIVER_PROBE register=0x%02x value=0x%04x\n",
		 REHARNESS_MDIO_REGISTER, value);
	return 0;
}

static void reharness_mdio_sensor_remove(struct mdio_device *mdiodev)
{
	dev_info(&mdiodev->dev, "REHARNESS_MDIO_DRIVER_REMOVE\n");
}

static struct mdio_driver reharness_mdio_sensor_driver = {
	.probe = reharness_mdio_sensor_probe,
	.remove = reharness_mdio_sensor_remove,
	.mdiodrv.driver = {
		.name = "reharness_mdio_sensor",
	},
};

mdio_module_driver(reharness_mdio_sensor_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic MDIO device fixture");
