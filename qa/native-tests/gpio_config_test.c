#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const unsigned int offset = 0;
    struct gpio_v2_line_config config;
    int cfd = gpio_test_open("gpio-config", path);
    int lfd = gpio_test_request_v2(cfd, &offset, 1,
                                   GPIO_V2_LINE_FLAG_OUTPUT |
                                   GPIO_V2_LINE_FLAG_ACTIVE_LOW, 1, 0);

    if (lfd < 0)
        gpio_test_fail("gpio-config", "active-low-output");
    memset(&config, 0, sizeof(config));
    config.flags = GPIO_V2_LINE_FLAG_OUTPUT |
                   GPIO_V2_LINE_FLAG_ACTIVE_LOW;
    if (ioctl(lfd, GPIO_V2_LINE_SET_CONFIG_IOCTL, &config) < 0)
        gpio_test_fail("gpio-config", "set-flags");
    close(lfd);

    lfd = gpio_test_request_v2(cfd, &offset, 1, GPIO_V2_LINE_FLAG_INPUT,
                               0, 1000);
    if (lfd < 0)
        gpio_test_fail("gpio-config", "debounce");
    close(lfd);
    close(cfd);
    gpio_test_coverage("config_flags");
    gpio_test_coverage("config_debounce");
    gpio_test_pass("gpio-config");
    return 0;
}
