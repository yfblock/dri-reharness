// SPDX-License-Identifier: GPL-2.0
/* Candidate-style I2C client used by the generic profile runtime fixture. */
#include <linux/i2c.h>
#include <linux/module.h>

#define REHARNESS_I2C_REGISTER 0x10
#define REHARNESS_I2C_EXPECTED_VALUE 0x5a

static int reharness_i2c_sensor_probe(struct i2c_client *client)
{
	u8 register_address = REHARNESS_I2C_REGISTER;
	u8 value = 0;
	struct i2c_msg messages[2] = {
		{
			.addr = client->addr,
			.len = 1,
			.buf = &register_address,
		},
		{
			.addr = client->addr,
			.flags = I2C_M_RD,
			.len = 1,
			.buf = &value,
		},
	};
	int ret;

	ret = i2c_transfer(client->adapter, messages, ARRAY_SIZE(messages));
	if (ret != ARRAY_SIZE(messages) || value != REHARNESS_I2C_EXPECTED_VALUE) {
		dev_err(&client->dev,
			"REHARNESS_I2C_DRIVER_PROBE_FAILED ret=%d value=0x%02x\n",
			ret, value);
		return ret < 0 ? ret : -EIO;
	}

	dev_info(&client->dev,
		 "REHARNESS_I2C_DRIVER_PROBE register=0x%02x value=0x%02x\n",
		 REHARNESS_I2C_REGISTER, value);
	return 0;
}

static void reharness_i2c_sensor_remove(struct i2c_client *client)
{
	dev_info(&client->dev, "REHARNESS_I2C_DRIVER_REMOVE\n");
}

static const struct i2c_device_id reharness_i2c_sensor_ids[] = {
	{ "reharness_i2c_sens", 0 },
	{ }
};
MODULE_DEVICE_TABLE(i2c, reharness_i2c_sensor_ids);

static struct i2c_driver reharness_i2c_sensor_driver = {
	.driver = {
		.name = "reharness_i2c_sens",
	},
	.probe = reharness_i2c_sensor_probe,
	.remove = reharness_i2c_sensor_remove,
	.id_table = reharness_i2c_sensor_ids,
};

module_i2c_driver(reharness_i2c_sensor_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic I2C client fixture");
