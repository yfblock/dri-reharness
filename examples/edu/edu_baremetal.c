/* Auto-generated bare-metal driver for edu (reharness) */
#include <stdint.h>
#include <stddef.h>

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>
#define MMIO_SIZE 0x1000
static uint8_t oracle_mmio[MMIO_SIZE];
static uintptr_t oracle_base;
static unsigned long oracle_trace_count;
static void oracle_seed_mmio(void) {
    for (unsigned int i = 0; i < MMIO_SIZE; ++i)
        oracle_mmio[i] = (uint8_t)(0x5aU + 37U * i);
}
static void oracle_write_w1c(uint32_t value, uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a - oracle_base;
    uint32_t old = 0;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        old |= (uint32_t)oracle_mmio[off + i] << shift;
    }
    printf("[trace %lu] W 0x%03lx = 0x%08x\n", oracle_trace_count++, off, value);
    old &= ~value;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        oracle_mmio[off + i] = (uint8_t)(old >> shift);
    }
}
static uint32_t oracle_read(uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a - oracle_base;
    uint32_t value = 0;
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        value |= (uint32_t)oracle_mmio[off + i] << shift;
    }
    printf("[trace %lu] R 0x%03lx = 0x%08x\n", oracle_trace_count++, off, value);
    return value;
}
static void oracle_write(uint32_t value, uintptr_t a, unsigned int width, int be) {
    uintptr_t off = a - oracle_base;
    printf("[trace %lu] W 0x%03lx = 0x%08x\n", oracle_trace_count++, off, value);
    for (unsigned int i = 0; i < width; ++i) {
        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;
        oracle_mmio[off + i] = (uint8_t)(value >> shift);
    }
}
static inline uint32_t mmio_read32(uintptr_t a) { return oracle_read(a, 4, 0); }
static inline void mmio_write32(uint32_t v, uintptr_t a) { oracle_write(v, a, 4, 0); }
static inline uint16_t mmio_read16(uintptr_t a) { return (uint16_t)oracle_read(a, 2, 0); }
static inline void mmio_write16(uint16_t v, uintptr_t a) { oracle_write(v, a, 2, 0); }
static inline uint8_t mmio_read8(uintptr_t a) { return (uint8_t)oracle_read(a, 1, 0); }
static inline void mmio_write8(uint8_t v, uintptr_t a) { oracle_write(v, a, 1, 0); }
static inline void mmio_write_w1c32(uint32_t v, uintptr_t a) { oracle_write_w1c(v, a, 4, 0); }
static inline void mmio_write_w1c16(uint16_t v, uintptr_t a) { oracle_write_w1c(v, a, 2, 0); }
static inline void mmio_write_w1c8(uint8_t v, uintptr_t a) { oracle_write_w1c(v, a, 1, 0); }
static inline uint16_t mmio_read16be(uintptr_t a) { return (uint16_t)oracle_read(a, 2, 1); }
static inline void mmio_write16be(uint16_t v, uintptr_t a) { oracle_write(v, a, 2, 1); }
static inline uint32_t mmio_read32be(uintptr_t a) { return oracle_read(a, 4, 1); }
static inline void mmio_write32be(uint32_t v, uintptr_t a) { oracle_write(v, a, 4, 1); }
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
#else
static inline uint32_t mmio_read32(uintptr_t a) {
    return *(volatile uint32_t *)a;
}
static inline void mmio_write32(uint32_t v, uintptr_t a) {
    *(volatile uint32_t *)a = v;
}
static inline uint16_t mmio_read16(uintptr_t a) { return *(volatile uint16_t *)a; }
static inline void mmio_write16(uint16_t v, uintptr_t a) { *(volatile uint16_t *)a = v; }
static inline uint8_t mmio_read8(uintptr_t a) { return *(volatile uint8_t *)a; }
static inline void mmio_write8(uint8_t v, uintptr_t a) { *(volatile uint8_t *)a = v; }
static inline void mmio_write_w1c32(uint32_t v, uintptr_t a) { mmio_write32(v, a); }
static inline void mmio_write_w1c16(uint16_t v, uintptr_t a) { mmio_write16(v, a); }
static inline void mmio_write_w1c8(uint8_t v, uintptr_t a) { mmio_write8(v, a); }
static inline uint16_t mmio_read16be(uintptr_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    return (uint16_t)((uint16_t)p[0] << 8 | p[1]);
}
static inline void mmio_write16be(uint16_t v, uintptr_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v;
}
static inline uint32_t mmio_read32be(uintptr_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static inline void mmio_write32be(uint32_t v, uintptr_t a) {
    volatile uint8_t *p = (volatile uint8_t *)a;
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}
#define REHARNESS_CALLBACK_BEGIN(n) ((void)(n))
#define REHARNESS_CALLBACK_MARKER(name) ((void)(name))
#define REHARNESS_CALLBACK_RESULT(v) ((void)(v))
#define REHARNESS_CALLBACK_OUTPUT(n, v) ((void)(n), (void)(v))
#define REHARNESS_CALLBACK_STATE(d, r) ((void)(d), (void)(r))
#define REHARNESS_VIRTIO_STATE(ea, ec, so, sc, en, sn, r) ((void)(ea), (void)(ec), (void)(so), (void)(sc), (void)(en), (void)(sn), (void)(r))
#define REHARNESS_CALLBACK_END() ((void)0)
#define REHARNESS_W1C_BEGIN(n) ((void)(n))
#define REHARNESS_W1C_MARKER(name) ((void)(name))
#define REHARNESS_W1C_END() ((void)0)
#endif
static inline void reharness_delay_ns(uint32_t ns) {
    for (volatile uint32_t i = 0; i < ns / 100U + 1U; ++i) { }
}
#define readl(a) mmio_read32((uintptr_t)(a))
#define readw(a) mmio_read16((uintptr_t)(a))
#define readb(a) mmio_read8((uintptr_t)(a))
#define ioread32(a) mmio_read32((uintptr_t)(a))
#define writel(v, a) mmio_write32((uint32_t)(v), (uintptr_t)(a))
#define writew(v, a) mmio_write16((uint16_t)(v), (uintptr_t)(a))
#define writeb(v, a) mmio_write8((uint8_t)(v), (uintptr_t)(a))
#define mdelay(n) (0)
#define irqd_to_hwirq(d) (d)
#define BIT(n) (1u << (n))
#define GENMASK(h, l) (((~0u) << (l)) & (~0u >> (31 - (h))))
#define test_bit(n, bits) (((bits) >> (n)) & 1u)
#define likely(x) (x)
#define unlikely(x) (x)
#define pci_resource_len(p, b) (0u)
#define mmc_gpio_get_cd(m) (0)
#define ahci_remap_dcc(i) (0u)
#define of_property_read_bool(np, name) (0)

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

void edu_irq_handler(uint32_t irq, struct edu_priv *dev) {
    uint32_t status = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_1 kind=Read status=lowered digest=58c605e506ad0c2b */
    __rh_op_op_1: {
        status = mmio_read32(base + IO_IRQ_STATUS);
        (void)status;
    }
    /* REHARNESS_RIS_OP id=op_2 kind=Write status=lowered digest=f479e9c3cf35a289 */
    __rh_op_op_2: {
        mmio_write32(status, base + IO_IRQ_ACK);
    }
}

void edu_read(uint32_t len, struct edu_priv *dev) {
    uint32_t val = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=dbf046aef312a382 */
    __rh_op_op_3: {
        val = mmio_read32(base + 0x0);
        (void)val;
    }
}

void edu_write(uint32_t len, struct edu_priv *dev) {
    uint32_t val = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_4 kind=Write status=lowered digest=a145d50fd28e9830 */
    __rh_op_op_4: {
        mmio_write32(val, base + 0x0);
    }
}

void edu_pci_probe(struct edu_priv *dev) {
    uint32_t dev_id = 0;
    uintptr_t base = dev->base;
    /* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=4b8a9ab4cb9122ff */
    __rh_op_op_5: {
        dev_id = mmio_read32(base + IO_ID);
        (void)dev_id;
    }
}

