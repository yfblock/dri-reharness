#include "gpio_test_common.h"

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/gpiochip0";
    struct gpiohandle_request request;
    struct gpiohandle_data values;
    int cfd = gpio_test_open("gpio-v1-compat", path);

    memset(&request, 0, sizeof(request));
    request.lines = 1;
    request.lineoffsets[0] = 0;
    request.flags = GPIOHANDLE_REQUEST_OUTPUT;
    request.default_values[0] = 0;
    strcpy(request.consumer_label, "reharness-v1");
    if (ioctl(cfd, GPIO_GET_LINEHANDLE_IOCTL, &request) < 0)
        gpio_test_fail("gpio-v1-compat", "get-line-handle");
    memset(&values, 0, sizeof(values));
    if (ioctl(request.fd, GPIOHANDLE_GET_LINE_VALUES_IOCTL, &values) < 0)
        gpio_test_fail("gpio-v1-compat", "get-values");
    values.values[0] = 1;
    if (ioctl(request.fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &values) < 0)
        gpio_test_fail("gpio-v1-compat", "set-values");
    close(request.fd);
    close(cfd);
    gpio_test_coverage("v1_single_line");
    gpio_test_pass("gpio-v1-compat");
    return 0;
}
