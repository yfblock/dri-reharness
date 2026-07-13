// test/gpio_trace_test.c — 行使 gpio_chip 回调, 触发 .ris callback 模块的 MMIO 访问
// 用 v2 chardev ioctl (CONFIG_GPIO_CDEV_V1 not set):
//   GET_LINEINFO     → get_direction
//   GET_LINE(OUTPUT) → direction_output
//   GET_VALUES       → get
//   SET_VALUES(0/1)  → set
//   SET_CONFIG(INPUT)→ direction_input
// 用法: ./gpio_trace_test /dev/gpiochip0
// 输出: GPIO_TRACE_DONE 或 GPIO_TRACE_FAIL:<原因>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/gpio.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    int fd = open(path, O_RDWR);
    if (fd < 0) { perror("open"); printf("GPIO_TRACE_FAIL:open %s\n", path); return 2; }

    /* 1. get_direction: GET_LINEINFO 触发 gpiod_get_direction → gc->get_direction */
    struct gpio_v2_line_info info;
    memset(&info, 0, sizeof(info));
    info.offset = 0;
    int r1 = ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info);
    printf("ioctl LINEINFO=%d\n", r1);
    if (r1 < 0) {
        perror("GET_LINEINFO"); printf("GPIO_TRACE_FAIL:lineinfo\n"); return 1;
    }

    /* 2. direction_output: request line 0 as OUTPUT → gc->direction_output */
    struct gpio_v2_line_request req;
    memset(&req, 0, sizeof(req));
    req.num_lines = 1;
    req.offsets[0] = 0;
    strcpy(req.consumer, "rh");
    req.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
    int r2 = ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req);
    printf("ioctl GET_LINE=%d fd=%d\n", r2, req.fd);
    if (r2 < 0) {
        perror("GET_LINE"); printf("GPIO_TRACE_FAIL:request\n"); return 1;
    }
    int lfd = req.fd;

    /* 3. get: GET_VALUES → gc->get */
    struct gpio_v2_line_values vals;
    memset(&vals, 0, sizeof(vals));
    vals.mask = 1ULL;
    int r3 = ioctl(lfd, GPIO_V2_LINE_GET_VALUES_IOCTL, &vals);
    printf("ioctl GET_VALUES=%d bits=%llu\n", r3, vals.bits);
    if (r3 < 0) {
        perror("GET_VALUES"); printf("GPIO_TRACE_FAIL:get\n"); return 1;
    }

    /* 4. set: SET_VALUES(1) → gc->set */
    memset(&vals, 0, sizeof(vals));
    vals.mask = 1ULL; vals.bits = 1ULL;
    int r4a = ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &vals);
    printf("ioctl SET_VALUES(1)=%d\n", r4a);
    /* set(0) */
    vals.bits = 0ULL;
    int r4b = ioctl(lfd, GPIO_V2_LINE_SET_VALUES_IOCTL, &vals);
    printf("ioctl SET_VALUES(0)=%d\n", r4b);

    /* 5. direction_input: SET_CONFIG(INPUT) → gc->direction_input */
    struct gpio_v2_line_config cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.flags = GPIO_V2_LINE_FLAG_INPUT;
    int r5 = ioctl(lfd, GPIO_V2_LINE_SET_CONFIG_IOCTL, &cfg);
    printf("ioctl SET_CONFIG(INPUT)=%d\n", r5);

    close(lfd);
    close(fd);
    printf("GPIO_TRACE_DONE\n");
    return 0;
}
