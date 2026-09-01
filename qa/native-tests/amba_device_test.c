// SPDX-License-Identifier: GPL-2.0-only
/* Check that the synthetic AMBA device is visible through Linux sysfs. */
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
	const char *expected = argc > 1 ? argv[1] : "reharness-amba";
	DIR *directory;
	struct dirent *entry;

	directory = opendir("/sys/bus/amba/devices");
	if (!directory) {
		perror("open AMBA sysfs directory");
		return EXIT_FAILURE;
	}

	while ((entry = readdir(directory)) != NULL) {
		if (!strcmp(entry->d_name, expected)) {
			closedir(directory);
			printf("AMBA_DEVICE_LIFECYCLE_PASS name=%s\n", expected);
			return EXIT_SUCCESS;
		}
	}

	closedir(directory);
	fprintf(stderr, "AMBA device %s is not present\n", expected);
	return EXIT_FAILURE;
}
