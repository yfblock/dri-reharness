#include "edu_harness.h"


/* Module: edu_irq_handler */
static void edu_irq_handler(struct edu_priv *dev)
{
    uintptr_t base = dev->base;
    uint32_t status;

    status = harness_read32(base + IO_IRQ_STATUS);
    harness_write32(status, base + IO_IRQ_ACK);
}

/* Module: edu_read */
static uint32_t edu_read(struct edu_priv *dev)
{
    uintptr_t base = dev->base;
    uint32_t val;

    val = harness_read32(base + 0x0);
    return val;
}

/* Module: edu_write */
static void edu_write(struct edu_priv *dev, uint32_t val)
{
    uintptr_t base = dev->base;

    harness_write32(val, base + 0x0);
}

/* Module: edu_pci_probe */
static int edu_pci_probe(struct edu_priv *dev)
{
    struct edu_priv *priv = dev;
    uintptr_t base = dev->base;
    uint32_t dev_id;
    int ret = 0;

    if ((priv->mmio == 0x0) == 0x0) {
        if (ret == 0x0) {
            dev_id = harness_read32(base + IO_ID);
        }
    }

    return ret;
}

int main(void)
{
    struct edu_priv dev;
    dev.base = 0;
    dev.mmio = 1;
    dev.irq = 0;

    edu_irq_handler(&dev);
    (void)edu_read(&dev);
    edu_write(&dev, 0xDEADBEEF);
    edu_pci_probe(&dev);

    return 0;
}