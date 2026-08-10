#include "edu_harness.h"


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
