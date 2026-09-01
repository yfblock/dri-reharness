#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    struct gpiochip_info info;
    int fd = gpio_test_open("gpio-chip-info", path);

    memset(&info, 0, sizeof(info));
    if (ioctl(fd, GPIO_GET_CHIPINFO_IOCTL, &info) < 0)
        gpio_test_fail("gpio-chip-info", "GPIO_GET_CHIPINFO_IOCTL");
    if (info.lines < 2)
        gpio_test_fail("gpio-chip-info", "line-count");
    close(fd);
    gpio_test_coverage("chip_info");
    gpio_test_pass("gpio-chip-info");
    return 0;
}
