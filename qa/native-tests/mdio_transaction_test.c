// SPDX-License-Identifier: GPL-2.0
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct reharness_mdio_request {
	uint8_t address;
	uint8_t reg;
	uint16_t value;
};

#define REHARNESS_MDIO_READ \
	_IOWR('R', 0x40, struct reharness_mdio_request)
#define REHARNESS_MDIO_WRITE \
	_IOW('R', 0x41, struct reharness_mdio_request)

static void fail(const char *message)
{
	perror(message);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/reharness-mdio-control";
	const char *mode = argc > 2 ? argv[2] : "valid";
	struct reharness_mdio_request request;
	int fd;

	fd = open(path, O_RDWR);
	if (fd < 0)
		fail("open mdio control");

	if (!strcmp(mode, "invalid")) {
		request = (struct reharness_mdio_request){
			.address = 2, .reg = 0x10,
		};
		if (ioctl(fd, REHARNESS_MDIO_READ, &request) >= 0 ||
				errno != ENODEV) {
			fprintf(stderr, "invalid MDIO address was not rejected (errno=%d)\n",
					errno);
			return EXIT_FAILURE;
		}
		puts("MDIO_INVALID_ADDRESS_PASS");
		close(fd);
		return EXIT_SUCCESS;
	}

	request = (struct reharness_mdio_request){
		.address = 1, .reg = 0x10,
	};
	if (ioctl(fd, REHARNESS_MDIO_READ, &request) < 0 ||
		request.value != 0xa5a5) {
		fprintf(stderr, "probe-updated MDIO value was 0x%04x\n",
			request.value);
		return EXIT_FAILURE;
	}
	request.value = 0xa55a;
	if (ioctl(fd, REHARNESS_MDIO_WRITE, &request) < 0)
		fail("valid MDIO write");
	request.value = 0;
	if (ioctl(fd, REHARNESS_MDIO_READ, &request) < 0 ||
		request.value != 0xa55a) {
		fprintf(stderr, "MDIO readback value was 0x%04x\n", request.value);
		return EXIT_FAILURE;
	}
	puts("MDIO_TRANSACTION_PASS");
	close(fd);
	return EXIT_SUCCESS;
}
