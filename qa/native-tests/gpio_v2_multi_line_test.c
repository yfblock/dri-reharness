#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const unsigned int offsets[] = {0, 1};
    uint64_t bits;
    int cfd = gpio_test_open("gpio-v2-multi-line", path);
    int lfd = gpio_test_request_v2(cfd, offsets, 2,
                                   GPIO_V2_LINE_FLAG_OUTPUT, 1, 0);

    if (lfd < 0)
        gpio_test_fail("gpio-v2-multi-line", "request");
    if (gpio_test_get_values(lfd, 3, &bits) < 0)
        gpio_test_fail("gpio-v2-multi-line", "get-multiple");
    if (gpio_test_set_values(lfd, 3, 2) < 0)
        gpio_test_fail("gpio-v2-multi-line", "set-multiple");
    close(lfd);
    close(cfd);
    gpio_test_coverage("v2_multi_line");
    gpio_test_pass("gpio-v2-multi-line");
    return 0;
}
