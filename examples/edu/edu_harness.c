#include "edu_harness.h"


/* Module: edu_irq_handler */
void edu_irq_handler(struct edu_priv *dev)
{
    uint32_t status;

    status = harness_read32(dev->base + IO_IRQ_STATUS);

    harness_write32(status, dev->base + IO_IRQ_ACK);
}

/* Module: edu_read */
uint32_t edu_read(struct edu_priv *dev)
{
    uint32_t val;

    val = harness_read32(dev->base + 0x0);

    return val;
}

/* Module: edu_write */
void edu_write(struct edu_priv *dev, uint32_t val)
{
    harness_write32(val, dev->base + 0x0);
}

/* Module: edu_pci_probe */
int edu_pci_probe(struct edu_priv *dev)
{
    int ret = 0;
    uint32_t dev_id;

    if ((dev->mmio == 0x0) == 0x0) {
        if (ret == 0x0) {
            dev_id = harness_read32(dev->base + IO_ID);
        }
    }

    return ret;
}

int main(void)
{
    struct edu_priv dev;
    dev.base = 0x1000;
    dev.mmio = 0;

    edu_irq_handler(&dev);
    (void)edu_read(&dev);
    edu_write(&dev, 0xDEADBEEF);
    edu_pci_probe(&dev);

    return 0;
}