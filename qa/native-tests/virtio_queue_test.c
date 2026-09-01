// SPDX-License-Identifier: GPL-2.0-or-later
#include <errno.h>
#include <fcntl.h>
#include <linux/ioctl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

struct reharness_virtio_request {
	uint32_t sector;
	uint8_t value;
	uint8_t status;
};

#define REHARNESS_VIRTIO_READ \
	_IOWR('R', 0x30, struct reharness_virtio_request)

int main(int argc, char **argv)
{
	const char *path = argc > 1 ? argv[1] : "/dev/reharness-virtio-control";
	const char *mode = argc > 2 ? argv[2] : "valid";
	struct reharness_virtio_request request = { .sector = 0 };
	int fd;

	fd = open(path, O_RDWR);
	if (fd < 0) {
		fprintf(stderr, "open %s: %s\n", path, strerror(errno));
		return 1;
	}
	if (strcmp(mode, "invalid") == 0) {
		if (ioctl(fd, _IO('R', 0x7f), &request) != -1
				|| errno != ENOTTY) {
			printf("VIRTIO_INVALID_IOCTL_FAIL\n");
			close(fd);
			return 1;
		}
		printf("VIRTIO_INVALID_IOCTL_PASS\n");
		close(fd);
		return 0;
	}
	if (ioctl(fd, REHARNESS_VIRTIO_READ, &request) != 0
			|| request.status != 0) {
		printf("VIRTIO_QUEUE_FAIL status=%u errno=%d\n",
			request.status, errno);
		close(fd);
		return 1;
	}
	printf("VIRTIO_QUEUE_PASS value=0x%02x\n", request.value);
	close(fd);
	return 0;
}
