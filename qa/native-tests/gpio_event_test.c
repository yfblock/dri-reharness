#include "gpio_test_common.h"

#include <poll.h>

#define REHARNESS_GPIO_TRIGGER _IOW('R', 0x01, unsigned int)

int main(int argc, char **argv)
{
    const char *chip = argc > 1 ? argv[1] : "/dev/gpiochip0";
    const char *control = argc > 2 ? argv[2] : "/dev/reharness-gpio-control";
    const unsigned int offset = 0;
    struct gpio_v2_line_event event;
    struct pollfd pollfd;
    unsigned int line = 0;
    int cfd = gpio_test_open("gpio-events", chip);
    int lfd = gpio_test_request_v2(cfd, &offset, 1,
                                   GPIO_V2_LINE_FLAG_INPUT |
                                   GPIO_V2_LINE_FLAG_EDGE_RISING, 0, 0);
    int trigger_fd;

    if (lfd < 0)
        gpio_test_fail("gpio-events", "request-edge");
    trigger_fd = open(control, O_RDWR);
    if (trigger_fd < 0)
        gpio_test_fail("gpio-events", "open-trigger");
    if (ioctl(trigger_fd, REHARNESS_GPIO_TRIGGER, &line) < 0)
        gpio_test_fail("gpio-events", "trigger");
    memset(&pollfd, 0, sizeof(pollfd));
    pollfd.fd = lfd;
    pollfd.events = POLLIN;
    if (poll(&pollfd, 1, 1000) != 1 || !(pollfd.revents & POLLIN))
        gpio_test_fail("gpio-events", "poll-event");
    if (read(lfd, &event, sizeof(event)) != (ssize_t)sizeof(event))
        gpio_test_fail("gpio-events", "read-event");
    close(trigger_fd);
    close(lfd);
    close(cfd);
    gpio_test_coverage("line_event");
    gpio_test_pass("gpio-events");
    return 0;
}
