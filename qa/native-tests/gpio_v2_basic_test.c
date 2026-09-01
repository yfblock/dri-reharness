#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const unsigned int offset = 0;
    uint64_t bits;
    struct gpio_v2_line_config config;
    int cfd = gpio_test_open("gpio-v2-basic", path);
    int lfd = gpio_test_request_v2(cfd, &offset, 1,
                                   GPIO_V2_LINE_FLAG_OUTPUT, 0, 0);

    if (lfd < 0)
        gpio_test_fail("gpio-v2-basic", "request-output");
    if (gpio_test_get_values(lfd, 1, &bits) < 0)
        gpio_test_fail("gpio-v2-basic", "get-values");
    if (gpio_test_set_values(lfd, 1, 1) < 0 ||
        gpio_test_set_values(lfd, 1, 0) < 0)
        gpio_test_fail("gpio-v2-basic", "set-values");
    memset(&config, 0, sizeof(config));
    config.flags = GPIO_V2_LINE_FLAG_INPUT;
    if (ioctl(lfd, GPIO_V2_LINE_SET_CONFIG_IOCTL, &config) < 0)
        gpio_test_fail("gpio-v2-basic", "set-input");
    close(lfd);
    close(cfd);
    gpio_test_coverage("v2_single_line");
    gpio_test_coverage("v2_values");
    gpio_test_pass("gpio-v2-basic");
    return 0;
}
