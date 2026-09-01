// SPDX-License-Identifier: GPL-2.0
/* Candidate-style SPI protocol driver used by the generic profile fixture. */
#include <linux/module.h>
#include <linux/spi/spi.h>

#define REHARNESS_SPI_REGISTER 0x10
#define REHARNESS_SPI_EXPECTED_VALUE 0xa6

static int reharness_spi_sensor_probe(struct spi_device *spi)
{
	u8 register_address = REHARNESS_SPI_REGISTER;
	u8 value = 0;
	struct spi_transfer transfers[2] = {
		{
			.tx_buf = &register_address,
			.len = 1,
		},
		{
			.rx_buf = &value,
			.len = 1,
		},
	};
	struct spi_message message;
	int ret;

	spi_message_init(&message);
	spi_message_add_tail(&transfers[0], &message);
	spi_message_add_tail(&transfers[1], &message);
	ret = spi_sync(spi, &message);
	if (ret || message.actual_length != 2 ||
			value != REHARNESS_SPI_EXPECTED_VALUE) {
		dev_err(&spi->dev,
			"REHARNESS_SPI_DRIVER_PROBE_FAILED ret=%d value=0x%02x\n",
			ret, value);
		return ret ? ret : -EIO;
	}

	dev_info(&spi->dev,
		 "REHARNESS_SPI_DRIVER_PROBE register=0x%02x value=0x%02x\n",
		 REHARNESS_SPI_REGISTER, value);
	return 0;
}

static void reharness_spi_sensor_remove(struct spi_device *spi)
{
	dev_info(&spi->dev, "REHARNESS_SPI_DRIVER_REMOVE\n");
}

static const struct spi_device_id reharness_spi_sensor_ids[] = {
	{ "reharness_spi_sens", 0 },
	{ }
};
MODULE_DEVICE_TABLE(spi, reharness_spi_sensor_ids);

static struct spi_driver reharness_spi_sensor_driver = {
	.driver = {
		.name = "reharness_spi_sens",
	},
	.probe = reharness_spi_sensor_probe,
	.remove = reharness_spi_sensor_remove,
	.id_table = reharness_spi_sensor_ids,
};

module_spi_driver(reharness_spi_sensor_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Deterministic SPI protocol fixture");
