#include "edu_baremetal.h"


/* Primitive MMIO Helpers */
static inline uint8_t mmio_read8(uintptr_t addr) {
    return *(volatile uint8_t *)addr;
}

static inline uint16_t mmio_read16(uintptr_t addr) {
    return *(volatile uint16_t *)addr;
}

static inline uint32_t mmio_read32(uintptr_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline uint16_t mmio_read16be(uintptr_t addr) {
    return *(volatile uint16_t *)addr;
}

static inline uint32_t mmio_read32be(uintptr_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void mmio_write8(uint8_t val, uintptr_t addr) {
    *(volatile uint8_t *)addr = val;
}

static inline void mmio_write16(uint16_t val, uintptr_t addr) {
    *(volatile uint16_t *)addr = val;
}

static inline void mmio_write32(uint32_t val, uintptr_t addr) {
    *(volatile uint32_t *)addr = val;
}

static inline void mmio_write16be(uint16_t val, uintptr_t addr) {
    *(volatile uint16_t *)addr = val;
}

static inline void mmio_write32be(uint32_t val, uintptr_t addr) {
    *(volatile uint32_t *)addr = val;
}

static inline void mmio_write_w1c8(uint8_t val, uintptr_t addr) {
    *(volatile uint8_t *)addr = val;
}

static inline void mmio_write_w1c16(uint16_t val, uintptr_t addr) {
    *(volatile uint16_t *)addr = val;
}

static inline void mmio_write_w1c32(uint32_t val, uintptr_t addr) {
    *(volatile uint32_t *)addr = val;
}

/* Exported Driver Functions */

void edu_irq_handler(struct edu_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t status;

    status = mmio_read32(base + IO_IRQ_STATUS);
    mmio_write32(status, base + IO_IRQ_ACK);
}

uint32_t edu_read(struct edu_priv *dev) {
    uintptr_t base = dev->base;
    uint32_t val;

    val = mmio_read32(base + 0x0);
    return val;
}

void edu_write(struct edu_priv *dev, uint32_t val) {
    uintptr_t base = dev->base;

    mmio_write32(val, base + 0x0);
}

void edu_pci_probe(struct edu_priv *priv) {
    uintptr_t base = priv->base;
    uint32_t ret = 0; 
    uint32_t dev_id;

    if ((priv->mmio == 0x0) == 0x0) {
        if (ret == 0x0) {
            dev_id = mmio_read32(base + IO_ID);
        }
    }
}

#endif /* EDU_DRIVER_H */

#ifdef REHARNESS_BAREMETAL_ORACLE
#include <stdio.h>

int main(void) {
    struct edu_priv dev = { 0 };
    dev.base = 0x10000000;
    dev.mmio = 0x10000000;

    edu_pci_probe(&dev);
    edu_write(&dev, 0xDEADBEEF);
    uint32_t r = edu_read(&dev);
    edu_irq_handler(&dev);

    printf("Read value: 0x%08x\n", r);
    return 0;
}
#endif