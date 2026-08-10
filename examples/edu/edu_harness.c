/* Auto-generated userspace harness for edu (reharness) */
#include <stdint.h>
#include <stdio.h>

#define BIT(n) (1u << (n))
#define GENMASK(h, l) (((~0u) << (l)) & (~0u >> (31 - (h))))
#define test_bit(n, bits) (((bits) >> (n)) & 1u)
#define likely(x) (x)
#define unlikely(x) (x)
#define irqd_to_hwirq(d) (d)
#define cpu_to_le32(x) (x)
#define le32_to_cpu(x) (x)
#define cpu_to_le16(x) (x)
#define le16_to_cpu(x) (x)
#define lower_32_bits(x) ((uint32_t)((x) & 0xffffffff))
#define upper_32_bits(x) ((uint32_t)((x) >> 32))
#define PAGE_SIZE 4096
#define PTR_ERR(x) ((long)(x))
#define ENOMEM (-12)
#define ENODEV (-19)
#define readl(a) harness_read32((uintptr_t)(a))
#define readw(a) harness_read16((uintptr_t)(a))
#define readb(a) harness_read8((uintptr_t)(a))
#define ioread32(a) harness_read32((uintptr_t)(a))
#define writel(v, a) harness_write32((uint32_t)(v), (uintptr_t)(a))
#define writew(v, a) harness_write16((uint16_t)(v), (uintptr_t)(a))
#define writeb(v, a) harness_write8((uint8_t)(v), (uintptr_t)(a))
#define mdelay(n) (0)
#define pci_resource_len(p, b) (0u)
#define mmc_gpio_get_cd(m) (0)
#define ahci_remap_dcc(i) (0u)
#define of_property_read_bool(np, name) (0)

#define MMIO_SIZE 0x1000
static uint8_t mmio_region[MMIO_SIZE];
static unsigned long trace_count = 0;

static void harness_seed_mmio(void) {
    for (unsigned int i = 0; i < MMIO_SIZE; ++i)
        mmio_region[i] = (uint8_t)(0x5aU + 37U * i);
}
static void harness_write_w1c_width(uint32_t value, uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a & 0xfff;
    uint32_t old = 0;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        old |= (uint32_t)mmio_region[off + i] << shift;
    }
    printf("[trace %lu] W 0x%03lx = 0x%08x\n", trace_count++, off, value);
    old &= ~value;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        mmio_region[off + i] = (uint8_t)(old >> shift);
    }
}
static uint32_t harness_read_width(uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a & 0xfff;
    uint32_t value = 0;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        value |= (uint32_t)mmio_region[off + i] << shift;
    }
    printf("[trace %lu] R 0x%03lx = 0x%08x\n", trace_count++, off, value);
    return value;
}
static void harness_write_width(uint32_t value, uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a & 0xfff;
    printf("[trace %lu] W 0x%03lx = 0x%08x\n", trace_count++, off, value);
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        mmio_region[off + i] = (uint8_t)(value >> shift);
    }
}
static inline uint8_t harness_read8(uintptr_t a) { return (uint8_t)harness_read_width(a, 1, 0); }
static inline uint16_t harness_read16(uintptr_t a) { return (uint16_t)harness_read_width(a, 2, 0); }
static inline uint32_t harness_read32(uintptr_t a) { return harness_read_width(a, 4, 0); }
static inline uint16_t harness_read16be(uintptr_t a) { return (uint16_t)harness_read_width(a, 2, 1); }
static inline uint32_t harness_read32be(uintptr_t a) { return harness_read_width(a, 4, 1); }
static inline void harness_write8(uint8_t v, uintptr_t a) { harness_write_width(v, a, 1, 0); }
static inline void harness_write16(uint16_t v, uintptr_t a) { harness_write_width(v, a, 2, 0); }
static inline void harness_write32(uint32_t v, uintptr_t a) { harness_write_width(v, a, 4, 0); }
static inline void harness_write_w1c8(uint8_t v, uintptr_t a) { harness_write_w1c_width(v, a, 1, 0); }
static inline void harness_write_w1c16(uint16_t v, uintptr_t a) { harness_write_w1c_width(v, a, 2, 0); }
static inline void harness_write_w1c32(uint32_t v, uintptr_t a) { harness_write_w1c_width(v, a, 4, 0); }
static inline void harness_write16be(uint16_t v, uintptr_t a) { harness_write_width(v, a, 2, 1); }
static inline void harness_write32be(uint32_t v, uintptr_t a) { harness_write_width(v, a, 4, 1); }
static inline void reharness_delay_ns(uint32_t ns) { (void)ns; }
#define REHARNESS_CALLBACK_BEGIN(n) printf("[reharness-callback-begin] %u\n", (unsigned)(n))
#define REHARNESS_CALLBACK_MARKER(name) printf("[reharness-callback] %s\n", (name))
#define REHARNESS_CALLBACK_RESULT(v) printf("[reharness-result] 0x%llx\n", (unsigned long long)(v))
#define REHARNESS_CALLBACK_OUTPUT(n, v) printf("[reharness-output] %s=0x%llx\n", (n), (unsigned long long)(v))
#define REHARNESS_CALLBACK_STATE(d, r) printf("[reharness-state] sdata=0x%llx sdir=0x%llx\n", (unsigned long long)(d), (unsigned long long)(r))
#define REHARNESS_VIRTIO_STATE(ea, ec, so, sc, en, sn, r) printf("[reharness-virtio-state] ea=0x%llx ec=0x%llx so=0x%llx sc=0x%llx en=0x%llx sn=0x%llx ready=0x%llx\n", (unsigned long long)(ea), (unsigned long long)(ec), (unsigned long long)(so), (unsigned long long)(sc), (unsigned long long)(en), (unsigned long long)(sn), (unsigned long long)(r))
#define REHARNESS_CALLBACK_END() printf("[reharness-callback-end]\n")
#define REHARNESS_W1C_BEGIN(n) printf("[reharness-w1c-begin] %u\n", (unsigned)(n))
#define REHARNESS_W1C_MARKER(name) printf("[reharness-w1c] %s\n", (name))
#define REHARNESS_W1C_END() printf("[reharness-w1c-end]\n")

#define IO_ID 0x0
#define IO_IRQ_STATUS 0x24
#define IO_IRQ_ACK 0x64
#ifndef CALL_EXPR
#define CALL_EXPR 0
#endif
#ifndef Code
#define Code 0
#endif
#ifndef Config
#define Config 0
#endif
#ifndef Conservative
#define Conservative 0
#endif
#ifndef Exact
#define Exact 0
#endif
#ifndef Fixed
#define Fixed 0
#endif
#ifndef Interrupt
#define Interrupt 0
#endif
#ifndef Read
#define Read 0
#endif
#ifndef Status
#define Status 0
#endif
#ifndef Symbolic
#define Symbolic 0
#endif
#ifndef Var
#define Var 0
#endif
#ifndef Write
#define Write 0
#endif

struct edu_priv {
    uintptr_t base;
};

static void edu_irq_handler(uint32_t irq, struct edu_priv *dev) {
    uint32_t status = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_1 kind=Read status=lowered digest=58c605e506ad0c2b */
    __rh_op_op_1: {
        status = harness_read32(base + IO_IRQ_STATUS);
        (void)status;
    }
    /* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=f479e9c3cf35a289 */
    __rh_op_op_2: {
        harness_write32(status, base + IO_IRQ_ACK);
    }
}

static void edu_read(uint32_t len, struct edu_priv *dev) {
    uint32_t val = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=dbf046aef312a382 */
    __rh_op_op_3: {
        val = harness_read32(base + 0x0);
        (void)val;
    }
}

static void edu_write(uint32_t len, struct edu_priv *dev) {
    uint32_t val = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_4 kind=Write status=lowered digest=a145d50fd28e9830 */
    __rh_op_op_4: {
        harness_write32(val, base + 0x0);
    }
}

static void edu_pci_probe(struct edu_priv *dev) {
    uint32_t dev_id = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=4b8a9ab4cb9122ff */
    __rh_op_op_5: {
        dev_id = harness_read32(base + IO_ID);
        (void)dev_id;
    }
}

int main(void) {
    struct edu_priv dev = { .base = 0 };
    harness_seed_mmio();
    edu_pci_probe(&dev);
    printf("harness done: %lu MMIO ops traced\n", trace_count);
    return 0;
}
