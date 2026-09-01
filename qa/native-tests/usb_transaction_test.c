// SPDX-License-Identifier: GPL-2.0
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define REHARNESS_USB_MAX_PAYLOAD 64
struct reharness_usb_status {
	uint8_t value[2];
};
struct reharness_usb_bulk {
	uint8_t endpoint;
	uint8_t length;
	uint8_t data[REHARNESS_USB_MAX_PAYLOAD];
	uint8_t actual;
};

#define REHARNESS_USB_GET_STATUS \
	_IOR('U', 0x10, struct reharness_usb_status)
#define REHARNESS_USB_BULK_OUT \
	_IOWR('U', 0x11, struct reharness_usb_bulk)

static void fail(const char *message)
{
	perror(message);
	exit(EXIT_FAILURE);
}

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/reharness-usb-control";
	const char *mode = argc > 2 ? argv[2] : "control";
	struct reharness_usb_status status;
	struct reharness_usb_bulk request;
	int fd = open(path, O_RDWR);

	if (fd < 0)
		fail("open usb control");

	if (strcmp(mode, "control") == 0) {
		if (ioctl(fd, REHARNESS_USB_GET_STATUS, &status) < 0)
			fail("usb control status");
		if ((status.value[1] & 0x60) != 0x60) {
			fprintf(stderr, "unexpected USB modem status 0x%02x\n",
				status.value[1]);
			return EXIT_FAILURE;
		}
		puts("USB_CONTROL_PASS");
	} else if (strcmp(mode, "bulk") == 0) {
		request.endpoint = 2;
		request.length = 12;
		memcpy(request.data, "reharness-usb", request.length);
		if (ioctl(fd, REHARNESS_USB_BULK_OUT, &request) < 0)
			fail("usb bulk out");
		if (request.actual != request.length)
			return EXIT_FAILURE;
		puts("USB_BULK_OUT_PASS");
	} else if (strcmp(mode, "invalid") == 0) {
		request.endpoint = 1;
		request.length = 1;
		request.data[0] = 0;
		if (ioctl(fd, REHARNESS_USB_BULK_OUT, &request) >= 0
				|| errno != ENODEV) {
			fprintf(stderr, "invalid USB endpoint was accepted (errno=%d)\n",
				errno);
			return EXIT_FAILURE;
		}
		puts("USB_INVALID_ENDPOINT_PASS");
	} else {
		fprintf(stderr, "unknown test mode: %s\n", mode);
		return EXIT_FAILURE;
	}

	close(fd);
	return EXIT_SUCCESS;
}
