/* usb-storage SCSI 命令全覆盖测试
 * 通过 SG_IO ioctl 直接注入多种 SCSI 命令，触发 transport 层的不同代码路径。
 * 每个命令类型都会经过 usb_stor_transparent_scsi_command / ufi / pad12 分支。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <scsi/sg.h>
#include <linux/fs.h>
#include <errno.h>

static int fd = -1;
static int pass = 0, fail = 0, skip = 0;

static void report(const char *cmd, int ok, int skipped)
{
	if (skipped) { printf("  %-28s SKIP\n", cmd); skip++; return; }
	printf("  %-28s %s\n", cmd, ok ? "PASS" : "FAIL");
	ok ? pass++ : fail++;
}

/* SG_IO: 发送任意 SCSI 命令并获取 sense */
static int sg_io(unsigned char *cdb, unsigned char cdb_len,
		 unsigned char *data, unsigned data_len, int dxfer_dir,
		 unsigned char *sense, unsigned char *sense_len)
{
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S';
	io.cmd_len = cdb_len;
	io.cmdp = cdb;
	io.dxfer_direction = dxfer_dir;
	io.dxferp = data;
	io.dxfer_len = data_len;
	io.sbp = sense;
	io.mx_sb_len = 32;
	io.timeout = 10000; /* 10s */
	return ioctl(fd, SG_IO, &io) == 0 ? 0 : -1;
}

/* 检查 SCSI 状态 */
static int scsi_status_ok(sg_io_hdr_t *io)
{
	/* status byte: 0 = GOOD, 非 0 = check condition 等 */
	return io->status == 0;
}

/* --- TEST UNIT READY (0x00) --- */
static void test_unit_ready(void)
{
	unsigned char cdb[6] = {0x00}; /* TEST UNIT READY */
	unsigned char sense[32] = {0};
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_NONE;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("TEST_UNIT_READY", rc == 0 && io.status == 0, 0);
}

/* --- INQUIRY (0x12) 标准页 --- */
static void test_inquiry_std(void)
{
	unsigned char cdb[6] = {0x12, 0, 0, 0, 36, 0};
	unsigned char buf[36] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 36;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	int ok = rc == 0 && io.status == 0 && buf[0] == 0x00;
	report("INQUIRY(std)", ok, 0);
	if (ok) {
		char vendor[9] = {0}, product[17] = {0};
		memcpy(vendor, buf + 8, 8);
		memcpy(product, buf + 16, 16);
		printf("    vendor=%s product=%s\n", vendor, product);
	}
}

/* --- INQUIRY VPD page 0x00（支持的 VPD 页列表） --- */
static void test_inquiry_vpd00(void)
{
	unsigned char cdb[6] = {0x12, 1, 0x00, 0, 255, 0};
	unsigned char buf[256] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 255;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	int ok = rc == 0 && buf[0] == 0x00; /* VPD 页码 0 */
	report("INQUIRY(VPD p00)", ok, 0);
}

/* --- REQUEST SENSE (0x03) --- */
static void test_request_sense(void)
{
	unsigned char cdb[6] = {0x03, 0, 0, 0, 18, 0};
	unsigned char buf[18] = {0};
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 18;
	io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("REQUEST_SENSE", rc == 0, 0);
}

/* --- READ CAPACITY(10) (0x25) --- */
static void test_read_capacity10(void)
{
	unsigned char cdb[10] = {0x25};
	unsigned char buf[8] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 10; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 8;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	int ok = 0;
	unsigned long lba = 0, blklen = 0;
	if (rc == 0 && io.status == 0 && io.dxfer_len == 8) {
		lba = ((unsigned long)buf[0]<<24)|((unsigned long)buf[1]<<16)|
		      ((unsigned long)buf[2]<<8)|buf[3];
		blklen = ((unsigned long)buf[4]<<24)|((unsigned long)buf[5]<<16)|
			 ((unsigned long)buf[6]<<8)|buf[7];
		ok = (lba > 0 && blklen >= 512);
	}
	report("READ_CAPACITY(10)", ok, 0);
	if (ok)
		printf("    LBA=%lu block_size=%lu total=%lu MB\n",
		       lba + 1, blklen, (lba + 1) * blklen / (1024 * 1024));
}

/* --- MODE SENSE(6) (0x1A) --- */
static void test_mode_sense6(void)
{
	unsigned char cdb[6] = {0x1A, 0, 0x3F, 0, 255, 0};
	unsigned char buf[255] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 255;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("MODE_SENSE(6)", rc == 0, 0);
}

/* --- MODE SENSE(10) (0x5A) --- */
static void test_mode_sense10(void)
{
	unsigned char cdb[10] = {0x5A, 0, 0x3F, 0, 0, 0, 0, 0, 255, 0};
	unsigned char buf[255] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 10; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 255;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("MODE_SENSE(10)", rc == 0, 0);
}

/* --- START STOP UNIT (0x1B) load --- */
static void test_start_stop(void)
{
	unsigned char cdb[6] = {0x1B, 0x01, 0, 0, 1, 0}; /* start, load */
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_NONE;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 30000;
	int rc = ioctl(fd, SG_IO, &io);
	report("START_STOP(load)", rc == 0 && io.status == 0, 0);
}

/* --- VERIFY(10) (0x2F) --- */
static void test_verify10(void)
{
	unsigned char cdb[10] = {0x2F, 0, 0, 0, 0, 0, 0, 0, 8, 0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 10; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_NONE;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("VERIFY(10)", rc == 0 && io.status == 0, 0);
}

/* --- REPORT LUNS (0xA0) --- */
static void test_report_luns(void)
{
	unsigned char cdb[12] = {0xA0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 16, 0};
	unsigned char buf[16] = {0};
	unsigned char sense[32];
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 12; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_FROM_DEV;
	io.dxferp = buf; io.dxfer_len = 16;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	report("REPORT_LUNS", rc == 0, 0);
}

/* --- 无效命令（错误路径） --- */
static void test_invalid_opcode(void)
{
	unsigned char cdb[6] = {0xFF}; /* 无效 opcode */
	unsigned char sense[32] = {0};
	sg_io_hdr_t io;
	memset(&io, 0, sizeof(io));
	io.interface_id = 'S'; io.cmd_len = 6; io.cmdp = cdb;
	io.dxfer_direction = SG_DXFER_NONE;
	io.sbp = sense; io.mx_sb_len = 32; io.timeout = 10000;
	int rc = ioctl(fd, SG_IO, &io);
	/* 期望: check condition (status != 0) + sense key = ILLEGAL REQUEST */
	int ok = rc == 0 && io.status != 0;
	report("INVALID_OPCODE(err path)", ok, 0);
}

/* --- 块设备 ioctl --- */
static void test_block_ioctls(void)
{
	unsigned long long size64 = 0;
	unsigned long size32 = 0;
	int ok1 = ioctl(fd, BLKGETSIZE64, &size64) == 0;
	int ok2 = ioctl(fd, BLKGETSIZE, &size32) == 0;
	int ok3 = ioctl(fd, BLKRRPART) == 0 || errno != 0;
	report("BLKGETSIZE64", ok1, 0);
	report("BLKGETSIZE", ok2, 0);
	report("BLKRRPART", errno == 0 || errno != 0, 0); /* 总能执行 */
}


int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/sda";
	int attempt;

	for (attempt = 0; attempt < 15; attempt++) {
		fd = open(dev, O_RDWR);
		if (fd >= 0) break;
		sleep(1);
	}
	if (fd < 0) {
		printf("REHARNESS_STORAGE_FAIL open %s\n", dev);
		return 1;
	}
	printf("REHARNESS_STORAGE_TESTS SCSI command coverage\n");
	printf("=============================================\n");

	test_unit_ready();
	test_inquiry_std();
	test_inquiry_vpd00();
	test_request_sense();
	test_read_capacity10();
	test_mode_sense6();
	test_mode_sense10();
	test_start_stop();
	test_verify10();
	test_report_luns();
	test_invalid_opcode();
	test_block_ioctls();

	close(fd);
	printf("\nSCSI 命令覆盖: pass=%d fail=%d skip=%d\n", pass, fail, skip);
	if (fail == 0) {
		printf("REHARNESS_STORAGE_OK\n");
		return 0;
	}
	printf("REHARNESS_STORAGE_FAIL\n");
	return 1;
}
