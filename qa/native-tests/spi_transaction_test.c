// SPDX-License-Identifier: GPL-2.0
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct reharness_spi_request {
	uint8_t chip_select;
	uint8_t reg;
	uint8_t value;
};

#define REHARNESS_SPI_READ \
	_IOWR('R', 0x20, struct reharness_spi_request)
#define REHARNESS_SPI_WRITE \
	_IOW('R', 0x21, struct reharness_spi_request)

static void fail(const char *message)
{
	perror(message);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/reharness-spi-control";
	struct reharness_spi_request request;
	int fd = open(path, O_RDWR);

	if (fd < 0)
		fail("open spi control");

	request = (struct reharness_spi_request){
		.chip_select = 0, .reg = 0x11, .value = 0xb4,
	};
	if (ioctl(fd, REHARNESS_SPI_WRITE, &request) < 0)
		fail("valid spi write");

	request.value = 0;
	if (ioctl(fd, REHARNESS_SPI_READ, &request) < 0
			|| request.value != 0xb4) {
		fprintf(stderr, "valid spi read returned 0x%02x\n", request.value);
		return EXIT_FAILURE;
	}
	puts("SPI_TRANSFER_PASS");

	request = (struct reharness_spi_request){
		.chip_select = 1, .reg = 0x10, .value = 0,
	};
	if (ioctl(fd, REHARNESS_SPI_READ, &request) >= 0 || errno != ENODEV) {
		fprintf(stderr, "invalid spi chip select was not rejected (errno=%d)\n",
			errno);
		return EXIT_FAILURE;
	}
	puts("SPI_INVALID_CHIP_SELECT_PASS");

	close(fd);
	return EXIT_SUCCESS;
}
