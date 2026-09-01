// SPDX-License-Identifier: GPL-2.0
#include <linux/spi/spi.h>

static int fixture_spi_probe(struct spi_device *spi)
{
	u8 tx = 0;
	struct spi_transfer transfer = {
		.tx_buf = &tx,
		.len = 1,
	};
	struct spi_message message;

	spi_message_init(&message);
	spi_message_add_tail(&transfer, &message);
	return spi_sync(spi, &message);
}

static struct spi_driver fixture_spi_driver = {
	.driver = { .name = "fixture_spi_client" },
	.probe = fixture_spi_probe,
};

module_spi_driver(fixture_spi_driver);
