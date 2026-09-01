#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    struct gpio_v2_line_info info;
    int fd = gpio_test_open("gpio-line-info", path);

    memset(&info, 0, sizeof(info));
    info.offset = 0;
    if (ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info) < 0)
        gpio_test_fail("gpio-line-info", "line-0");
    if (info.offset != 0)
        gpio_test_fail("gpio-line-info", "line-0-offset");
    memset(&info, 0, sizeof(info));
    info.offset = 1;
    if (ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info) < 0)
        gpio_test_fail("gpio-line-info", "line-1");
    if (info.offset != 1)
        gpio_test_fail("gpio-line-info", "line-1-offset");
    close(fd);
    gpio_test_coverage("line_info");
    gpio_test_pass("gpio-line-info");
    return 0;
}
