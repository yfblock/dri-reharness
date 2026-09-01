// SPDX-License-Identifier: GPL-2.0-only
/* Exercise the Linux I2C character-device ABI, independent of a fixture ioctl. */
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int transfer(int fd, struct i2c_msg *messages, uint32_t count)
{
	struct i2c_rdwr_ioctl_data request = {
		.msgs = messages,
		.nmsgs = count,
	};

	return ioctl(fd, I2C_RDWR, &request);
}

static int write_register(int fd, uint16_t address, uint8_t reg, uint8_t value)
{
	uint8_t buffer[] = {reg, value};
	struct i2c_msg message = {
		.addr = address,
		.flags = 0,
		.len = sizeof(buffer),
		.buf = buffer,
	};

	return transfer(fd, &message, 1) == 1 ? 0 : -1;
}

static int read_register(int fd, uint16_t address, uint8_t reg, uint8_t *value)
{
	struct i2c_msg messages[] = {
		{
			.addr = address,
			.flags = 0,
			.len = 1,
			.buf = &reg,
		},
		{
			.addr = address,
			.flags = I2C_M_RD,
			.len = 1,
			.buf = value,
		},
	};

	return transfer(fd, messages, 2) == 2 ? 0 : -1;
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/i2c-0";
	uint8_t value = 0;
	int fd = open(path, O_RDWR);

	if (fd < 0) {
		perror("open i2c-dev");
		return EXIT_FAILURE;
	}
	if (write_register(fd, 0x50, 0x11, 0xa5) < 0
			|| read_register(fd, 0x50, 0x11, &value) < 0
			|| value != 0xa5) {
		fprintf(stderr, "valid I2C_RDWR transaction failed: value=0x%02x errno=%d\n",
				value, errno);
		close(fd);
		return EXIT_FAILURE;
	}
	puts("I2CDEV_TRANSACTION_PASS");

	if (read_register(fd, 0x51, 0x10, &value) >= 0 || errno != ENXIO) {
		fprintf(stderr, "invalid I2C_RDWR address was not rejected: errno=%d\n",
				errno);
		close(fd);
		return EXIT_FAILURE;
	}
	puts("I2CDEV_INVALID_ADDRESS_PASS");
	close(fd);
	return EXIT_SUCCESS;
}
