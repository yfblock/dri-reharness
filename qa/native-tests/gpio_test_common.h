#ifndef REHARNESS_GPIO_TEST_COMMON_H
#define REHARNESS_GPIO_TEST_COMMON_H

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <linux/gpio.h>

static inline void gpio_test_fail(const char *test, const char *operation)
{
    fprintf(stderr, "GPIO_SUBSYSTEM_FAIL=%s:%s errno=%d (%s)\n",
            test, operation, errno, strerror(errno));
    exit(1);
}

static inline int gpio_test_open(const char *test, const char *path)
{
    int fd = open(path, O_RDWR);
    if (fd < 0)
        gpio_test_fail(test, "open");
    return fd;
}

static inline void gpio_test_pass(const char *test)
{
    printf("GPIO_SUBSYSTEM_PASS=%s\n", test);
}

static inline void gpio_test_coverage(const char *id)
{
    printf("REHARNESS_COVERAGE_%s=pass\n", id);
}

static inline int gpio_test_request_v2(int cfd, const unsigned int *offsets,
                                       unsigned int count, uint64_t flags,
                                       uint64_t output_values,
                                       unsigned int debounce_us)
{
    struct gpio_v2_line_request request;
    uint64_t mask = count == 64 ? ~0ULL : ((1ULL << count) - 1);

    memset(&request, 0, sizeof(request));
    request.num_lines = count;
    request.config.flags = flags;
    strcpy(request.consumer, "reharness");
    memcpy(request.offsets, offsets, count * sizeof(offsets[0]));
    if (flags & GPIO_V2_LINE_FLAG_OUTPUT) {
        request.config.num_attrs = 1;
        request.config.attrs[0].mask = mask;
        request.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
        request.config.attrs[0].attr.values = output_values;
    } else if (debounce_us) {
        request.config.num_attrs = 1;
        request.config.attrs[0].mask = mask;
        request.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE;
        request.config.attrs[0].attr.debounce_period_us = debounce_us;
    }
    if (ioctl(cfd, GPIO_V2_GET_LINE_IOCTL, &request) < 0)
        return -errno;
    return request.fd;
}

static inline int gpio_test_get_values(int line_fd, uint64_t mask,
                                       uint64_t *bits)
{
    struct gpio_v2_line_values values;

    memset(&values, 0, sizeof(values));
    values.mask = mask;
    if (ioctl(line_fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &values) < 0)
        return -errno;
    *bits = values.bits;
    return 0;
}

static inline int gpio_test_set_values(int line_fd, uint64_t mask,
                                       uint64_t bits)
{
    struct gpio_v2_line_values values;

    memset(&values, 0, sizeof(values));
    values.mask = mask;
    values.bits = bits;
    if (ioctl(line_fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &values) < 0)
        return -errno;
    return 0;
}

#endif
