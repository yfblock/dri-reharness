/* USB mass-storage 闭环测例: 打开块设备, 读取首个扇区, 验证真实 I/O。 */
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/sda";
	char buf[512] = {0};
	int fd, attempt;
	long n = -1;

	/* usb-storage 绑定并扫描 LUN 需要一点时间: 最多等 10 秒 */
	for (attempt = 0; attempt < 20; attempt++) {
		fd = open(dev, O_RDONLY);
		if (fd >= 0)
			break;
		sleep(1);
	}
	if (fd < 0) {
		printf("REHARNESS_STORAGE_FAIL open %s\n", dev);
		return 1;
	}
	n = read(fd, buf, sizeof(buf));
	close(fd);
	if (n == 512) {
		printf("REHARNESS_STORAGE_OK read=%ld bytes\n", n);
		return 0;
	}
	printf("REHARNESS_STORAGE_FAIL read=%ld\n", n);
	return 1;
}
