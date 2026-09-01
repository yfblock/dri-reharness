/* usb-storage 综合功能测试：多尺寸 I/O + 写回读校验 + 刷新 + 容量探测。
 * 覆盖 SCSI 路径：READ_10/WRITE_10/TEST_UNIT_READY/START_STOP/SYNCHRONIZE_CACHE
 * → transparent_scsi_command → pad12 → bulk_sglist → blocking_completion */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/fs.h>

static int fd = -1;
static int pass = 0, fail = 0;

static void report(const char *test, int ok)
{
	printf("%s: %s\n", test, ok ? "PASS" : "FAIL");
	ok ? pass++ : fail++;
}

/* 读容量 */
static unsigned long long test_capacity(void)
{
	unsigned long long size64 = 0;
	unsigned long size32 = 0;
	int ok = 0;

	if (ioctl(fd, BLKGETSIZE64, &size64) == 0 && size64 > 0) { ok = 1; }
	else if (ioctl(fd, BLKGETSIZE, &size32) == 0 && size32 > 0) {
		size64 = (unsigned long long)size32 * 512;
		ok = 1;
	}
	report("capacity", ok);
	return ok ? size64 : 0;
}

/* 单次读写 */
static int test_io(unsigned long long offset, unsigned char *buf, unsigned size, int is_write)
{
	if (lseek(fd, offset, SEEK_SET) < 0) return -1;
	if (is_write) return write(fd, buf, size) == (long)size ? 0 : -1;
	memset(buf, 0, size);
	return read(fd, buf, size) == (long)size ? 0 : -1;
}

/* 多尺寸 I/O + 写读校验 */
static void test_multi_io(unsigned long long dev_size)
{
	static const unsigned sizes[] = { 512, 1024, 4096, 65536 };
	unsigned char *wbuf, *rbuf;
	unsigned long long base;
	int i, all_ok = 1;

	wbuf = malloc(65536);
	rbuf = malloc(65536);
	if (!wbuf || !rbuf) { report("multi_io", 0); return; }

	/* 写到设备末尾前 1MB 的位置（避免破坏分区表） */
	base = dev_size > (2 << 20) ? dev_size - (1 << 20) : 512;

	for (i = 0; i < 4; i++) {
		unsigned sz = sizes[i];
		if (base + sz > dev_size) break;
		memset(wbuf, 0xA5 + i, sz);
		if (test_io(base + i * 4096, wbuf, sz, 1) < 0) { all_ok = 0; continue; }
		memset(rbuf, 0, sz);
		if (test_io(base + i * 4096, rbuf, sz, 0) < 0) { all_ok = 0; continue; }
		if (memcmp(wbuf, rbuf, sz) != 0) { all_ok = 0; continue; }
	}
	/* 再写零回去（清理） */
	memset(wbuf, 0, sizes[3]);
	test_io(base, wbuf, sizes[3], 1);

	report("multi_io_write_read_verify", all_ok);
	free(wbuf); free(rbuf);
}

/* 刷新 + 重读验证 */
static void test_flush_verify(unsigned long long dev_size)
{
	unsigned char *wbuf, *rbuf;
	unsigned long long off = dev_size - 4096;
	int ok = 1;

	wbuf = malloc(4096); rbuf = malloc(4096);
	if (!wbuf || !rbuf) { report("flush", 0); return; }
	memset(wbuf, 0x5A, 4096);
	if (test_io(off, wbuf, 4096, 1) < 0) { report("flush", 0); free(wbuf); free(rbuf); return; }
	if (ioctl(fd, BLKFLSBUF, 0) < 0) { /* 忽略 flush 错误 */ }
	fsync(fd);
	memset(rbuf, 0, 4096);
	if (test_io(off, rbuf, 4096, 0) < 0 || memcmp(wbuf, rbuf, 4096) != 0)
		ok = 0;
	report("flush_verify", ok);
	free(wbuf); free(rbuf);
}

int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/sda";
	unsigned long long size;
	int attempt;

	/* 等待块设备就绪（LUN 扫描异步） */
	for (attempt = 0; attempt < 15; attempt++) {
		fd = open(dev, O_RDWR);
		if (fd >= 0) break;
		sleep(1);
	}
	if (fd < 0) {
		printf("REHARNESS_STORAGE_FAIL open %s\n", dev);
		return 1;
	}

	size = test_capacity();
	if (size > 4096) test_multi_io(size);
	if (size > 8192) test_flush_verify(size);

	close(fd);
	printf("REHARNESS_STORAGE_TESTS pass=%d fail=%d\n", pass, fail);
	if (fail == 0 && pass >= 2) {
		printf("REHARNESS_STORAGE_OK\n");
		return 0;
	}
	printf("REHARNESS_STORAGE_FAIL\n");
	return 1;
}
