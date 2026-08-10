#include "edu_linux.h"


static int edu_open(struct inode *inode, struct file *file)
{
    struct edu_priv *priv = container_of(file->private_data, struct edu_priv, mdev);
    file->private_data = priv;
    return 0;
}

static ssize_t edu_read(struct file *file, char __user *buf, size_t count, loff_t *ppos)
{
    struct edu_priv *priv = file->private_data;
    u32 val;

    if (*ppos & 3 || count < 4)
        return -EINVAL;

    val = readl(priv->mmio + *ppos);
    if (copy_to_user(buf, &val, 4))
        return -EFAULT;
    *ppos += 4;
    return 4;
}

static ssize_t edu_write(struct file *file, const char __user *buf, size_t count, loff_t *ppos)
{
    struct edu_priv *priv = file->private_data;
    u32 val;

    if (*ppos & 3 || count < 4)
        return -EINVAL;

    if (copy_from_user(&val, buf, 4))
        return -EFAULT;
    writel(val, priv->mmio + *ppos);
    *ppos += 4;
    return 4;
}

static const struct file_operations edu_fops = {
    .owner = THIS_MODULE,
    .open = edu_open,
    .read = edu_read,
    .write = edu_write,
};

static irqreturn_t edu_irq_handler(int irq, void *dev_id)
{
    struct edu_priv *priv = dev_id;
    u32 status;

    RH_TRACE_FN(__func__);

    status = readl(priv->mmio + IO_IRQ_STATUS);
    writel(status, priv->mmio + IO_IRQ_ACK);

    return IRQ_HANDLED;
}

static int edu_pci_probe(struct pci_dev *pdev, const struct pci_device_id *ent)
{
    struct edu_priv *priv;
    int ret;
    u32 dev_id;

    RH_TRACE_FN(__func__);

    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv)
        return -ENOMEM;

    priv->pdev = pdev;
    priv->dev = &pdev->dev;
    pci_set_drvdata(pdev, priv);

    ret = pci_enable_device_mem(pdev);
    if (ret)
        return ret;

    ret = pci_request_regions(pdev, KBUILD_MODNAME);
    if (ret)
        goto err_disable;

    priv->mmio = pci_ioremap_bar(pdev, 0);
    if (!priv->mmio) {
        ret = -ENOMEM;
        goto err_regions;
    }

    RH_SET_BASE(priv->mmio);

    if (priv->mmio != NULL) {
        if (ret == 0) {
            dev_id = readl(priv->mmio + IO_ID);
        }
    }

    priv->mdev.minor = MISC_DYNAMIC_MINOR;
    priv->mdev.name = KBUILD_MODNAME;
    priv->mdev.fops = &edu_fops;

    ret = misc_register(&priv->mdev);
    if (ret)
        goto err_iomap;

    return 0;

err_iomap:
    iounmap(priv->mmio);
err_regions:
    pci_release_regions(pdev);
err_disable:
    pci_disable_device(pdev);
    return ret;
}

static void edu_pci_remove(struct pci_dev *pdev)
{
    struct edu_priv *priv = pci_get_drvdata(pdev);

    misc_deregister(&priv->mdev);
    iounmap(priv->mmio);
    pci_release_regions(pdev);
    pci_disable_device(pdev);
}

static const struct pci_device_id edu_pci_ids[] = {
    { PCI_DEVICE(EDU_VENDOR_ID, EDU_DEVICE_ID) },
    { 0, }
};
MODULE_DEVICE_TABLE(pci, edu_pci_ids);

static struct pci_driver edu_pci_driver = {
    .name = KBUILD_MODNAME,
    .id_table = edu_pci_ids,
    .probe = edu_pci_probe,
    .remove = edu_pci_remove,
};

module_pci_driver(edu_pci_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Edu PCI MMIO driver");