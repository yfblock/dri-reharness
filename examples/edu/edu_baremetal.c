#include "edu_baremetal.h"


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

