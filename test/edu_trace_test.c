// test/edu_trace_test.c — edu 驱动 trace 一致性测试
// 通过 /dev/edu_drv 行使 .ris 的 read/write 模块, 校验真实 edu 寄存器值:
//   0x00 (RO) id        → 0x010000ed (0xRRrr00edu)
//   0x04 (RW) live check → 写 X, 读 ~X
//   0x08 (RW) factorial  → 写 N, poll 0x20, 读 N!
// 用法: ./edu_trace_test /dev/edu_drv
// 输出: EDU_TRACE_OK 或 EDU_TRACE_FAIL:<原因>
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <string.h>

static uint32_t rd(int fd, off_t off) {
    uint32_t v = 0;
    if (pread(fd, &v, 4, off) != 4) { perror("pread"); exit(2); }
    return v;
}
static void wr(int fd, off_t off, uint32_t v) {
    if (pwrite(fd, &v, 4, off) != 4) { perror("pwrite"); exit(2); }
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s /dev/edu_drv\n", argv[0]); return 2; }
    int fd = open(argv[1], O_RDWR);
    if (fd < 0) { perror("open"); printf("EDU_TRACE_FAIL:open %s\n", argv[1]); return 2; }

    uint32_t id = rd(fd, 0x00);
    if (id != 0x010000edu && id != 0x010000ed) {
        /* 0xRRrr00edu: 低字节 0xed; 宽松匹配 0x_____ed 且 rr00edu 形态 */
        if ((id & 0xff) != 0xed) {
            printf("EDU_TRACE_FAIL:id reg 0x%08x (期望低字节 0xed)\n", id);
            return 1;
        }
    }
    printf("TRACE id@0x00 = 0x%08x OK\n", id);

    uint32_t x = 0xA5A5A5A5;
    wr(fd, 0x04, x);
    uint32_t lc = rd(fd, 0x04);
    if (lc != ~x) {
        printf("EDU_TRACE_FAIL:live_check@0x04 写0x%08x 读0x%08x (期望0x%08x)\n", x, lc, ~x);
        return 1;
    }
    printf("TRACE live_check@0x04 write0x%08x read0x%08x OK (~X)\n", x, lc);

    uint32_t n = 5;
    wr(fd, 0x08, n);
    /* poll status 0x20 bit0 (computing) until clear, 最多 100000 次 */
    int i;
    for (i = 0; i < 100000; i++) {
        if (!(rd(fd, 0x20) & 0x01)) break;
    }
    uint32_t fact = rd(fd, 0x08);
    if (fact != 120) {
        printf("EDU_TRACE_FAIL:factorial@0x08(%u)=%u (期望120) poll=%d\n", n, fact, i);
        return 1;
    }
    printf("TRACE factorial@0x08(5)=%u OK\n", fact);

    printf("EDU_TRACE_OK\n");
    return 0;
}
