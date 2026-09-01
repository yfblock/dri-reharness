#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const unsigned int offset = 0;
    struct gpio_v2_line_info info;
    int cfd = gpio_test_open("gpio-lifecycle", path);
    unsigned int iteration;

    for (iteration = 0; iteration < 8; ++iteration) {
        int lfd = gpio_test_request_v2(cfd, &offset, 1,
                                       GPIO_V2_LINE_FLAG_INPUT, 0, 0);
        if (lfd < 0)
            gpio_test_fail("gpio-lifecycle", "request-release");
        close(lfd);
    }
    memset(&info, 0, sizeof(info));
    info.offset = offset;
    if (ioctl(cfd, GPIO_V2_GET_LINEINFO_IOCTL, &info) < 0)
        gpio_test_fail("gpio-lifecycle", "final-line-info");
    if (info.flags & GPIO_V2_LINE_FLAG_USED)
        gpio_test_fail("gpio-lifecycle", "line-still-used");
    close(cfd);
    gpio_test_coverage("lifecycle");
    gpio_test_pass("gpio-lifecycle");
    return 0;
}
