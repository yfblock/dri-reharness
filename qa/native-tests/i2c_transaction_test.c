// SPDX-License-Identifier: GPL-2.0
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct reharness_i2c_request {
	uint8_t address;
	uint8_t reg;
	uint8_t value;
};

#define REHARNESS_I2C_READ \
	_IOWR('R', 0x10, struct reharness_i2c_request)
#define REHARNESS_I2C_WRITE \
	_IOW('R', 0x11, struct reharness_i2c_request)

static void fail(const char *message)
{
	perror(message);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/reharness-i2c-control";
	struct reharness_i2c_request request;
	int fd = open(path, O_RDWR);

	if (fd < 0)
		fail("open i2c control");

	request = (struct reharness_i2c_request){
		.address = 0x50, .reg = 0x11, .value = 0xa5,
	};
	if (ioctl(fd, REHARNESS_I2C_WRITE, &request) < 0)
		fail("valid i2c write");

	request.value = 0;
	if (ioctl(fd, REHARNESS_I2C_READ, &request) < 0
			|| request.value != 0xa5) {
		fprintf(stderr, "valid i2c read returned 0x%02x\n", request.value);
		return EXIT_FAILURE;
	}
	puts("I2C_TRANSACTION_PASS");

	request = (struct reharness_i2c_request){
		.address = 0x51, .reg = 0x10, .value = 0,
	};
	if (ioctl(fd, REHARNESS_I2C_READ, &request) >= 0 || errno != ENXIO) {
		fprintf(stderr, "invalid i2c address was not rejected (errno=%d)\n",
			errno);
		return EXIT_FAILURE;
	}
	puts("I2C_INVALID_ADDRESS_PASS");

	close(fd);
	return EXIT_SUCCESS;
}
