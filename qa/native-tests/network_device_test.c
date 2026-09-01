// SPDX-License-Identifier: GPL-2.0-only
/* Exercise the standard Linux net_device lifecycle through ioctl ABI. */
#include <net/if.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

static int find_interface(const char *prefix, char *name, size_t capacity)
{
	struct if_nameindex *interfaces = if_nameindex();
	if (!interfaces)
		return -1;

	for (struct if_nameindex *item = interfaces; item->if_index != 0; ++item) {
		if (strncmp(item->if_name, prefix, strlen(prefix)) == 0) {
			(void)snprintf(name, capacity, "%s", item->if_name);
			if_freenameindex(interfaces);
			return 0;
		}
	}
	if_freenameindex(interfaces);
	return -1;
}

int main(int argc, char **argv)
{
	const char *prefix = argc > 1 ? argv[1] : "eth";
	struct ifreq request = {0};
	char interface_name[IFNAMSIZ] = {0};
	int fd;

	if (find_interface(prefix, interface_name, sizeof(interface_name)) < 0) {
		fprintf(stderr, "no network interface with prefix %s\n", prefix);
		return EXIT_FAILURE;
	}

	fd = socket(AF_INET, SOCK_DGRAM, 0);
	if (fd < 0) {
		perror("socket");
		return EXIT_FAILURE;
	}
	(void)snprintf(request.ifr_name, sizeof(request.ifr_name), "%s",
			interface_name);
	if (ioctl(fd, SIOCGIFINDEX, &request) < 0 || request.ifr_ifindex <= 0) {
		perror("SIOCGIFINDEX");
		close(fd);
		return EXIT_FAILURE;
	}
	if (ioctl(fd, SIOCGIFFLAGS, &request) < 0) {
		perror("SIOCGIFFLAGS");
		close(fd);
		return EXIT_FAILURE;
	}
	request.ifr_flags |= IFF_UP;
	if (ioctl(fd, SIOCSIFFLAGS, &request) < 0) {
		perror("SIOCSIFFLAGS up");
		close(fd);
		return EXIT_FAILURE;
	}
	if (ioctl(fd, SIOCGIFFLAGS, &request) < 0
			|| !(request.ifr_flags & IFF_UP)) {
		fprintf(stderr, "interface did not transition up\n");
		close(fd);
		return EXIT_FAILURE;
	}
	request.ifr_flags &= (short)~IFF_UP;
	if (ioctl(fd, SIOCSIFFLAGS, &request) < 0) {
		perror("SIOCSIFFLAGS down");
		close(fd);
		return EXIT_FAILURE;
	}
	close(fd);
	printf("NETWORK_INTERFACE_PASS name=%s\n", interface_name);
	return EXIT_SUCCESS;
}
