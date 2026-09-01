#include "gpio_test_common.h"

static void expect_failure(int result, const char *test, const char *operation)
{
    if (result >= 0) {
        errno = EIO;
        gpio_test_fail(test, operation);
    }
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const unsigned int bad = GPIO_V2_LINES_MAX;
    const unsigned int zero = 0;
    struct gpio_v2_line_info info;
    int cfd = gpio_test_open("gpio-errors", path);
    int first;
    int second;

    memset(&info, 0, sizeof(info));
    info.offset = bad;
    expect_failure(ioctl(cfd, GPIO_V2_GET_LINEINFO_IOCTL, &info),
                   "gpio-errors", "invalid-offset");
    first = gpio_test_request_v2(cfd, &zero, 1, GPIO_V2_LINE_FLAG_INPUT, 0, 0);
    if (first < 0)
        gpio_test_fail("gpio-errors", "busy-setup");
    second = gpio_test_request_v2(cfd, &zero, 1,
                                  GPIO_V2_LINE_FLAG_INPUT |
                                  GPIO_V2_LINE_FLAG_OUTPUT, 0, 0);
    expect_failure(second, "gpio-errors", "invalid-flags-or-busy");
    close(first);
    close(cfd);
    gpio_test_coverage("error_paths");
    gpio_test_pass("gpio-errors");
    return 0;
}
