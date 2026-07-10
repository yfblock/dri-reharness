// SPDX-License-Identifier: GPL-2.0
#include <linux/cdev.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/uaccess.h>
#include <linux/io.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/dma-mapping.h>

#define EDU_VENDOR_ID  0x1234
#define EDU_DEVICE_ID  0x11e8

#define IO_IRQ_STATUS  0x24
#define IO_IRQ_ACK     0x64
#define IO_DMA_SRC     0x80
#define IO_DMA_DST     0x88
#define IO_DMA_CNT     0x90
#define IO_DMA_CMD     0x98

#define DMA_BASE       0x40000
#define DMA_CMD        0x1
#define DMA_IRQ        0x4
#define DMA_SIZE       0x1000

struct edu_priv {
	void __iomem *mmio;
	int irq;
	struct pci_dev *pdev;
	struct miscdevice mdev;
	void *dma_buf;
	dma_addr_t dma_handle;
};

static int edu_open(struct inode *inode, struct file *filp)
{
	struct edu_priv *priv = container_of(filp->private_data, struct edu_priv, mdev);
	filp->private_data = priv;
	return 0;
}

static ssize_t edu_read(struct file *filp, char __user *buf, size_t len, loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 kbuf;

	if (*off % 4 || len < 4)
		return 0;

	kbuf = readl(priv->mmio + *off);
	if (copy_to_user(buf, &kbuf, 4))
		return -EFAULT;

	*off += 4;
	return 4;
}

static ssize_t edu_write(struct file *filp, const char __user *buf, size_t len, loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 kbuf;

	if (*off % 4 || len < 4)
		return 0;

	if (copy_from_user(&kbuf, buf, 4))
		return -EFAULT;

	writel(kbuf, priv->mmio + *off);
	*off += 4;
	return 4;
}

static const struct file_operations edu_fops = {
	.owner  = THIS_MODULE,
	.open   = edu_open,
	.read   = edu_read,
	.write  = edu_write,
};


static int edu_pci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct edu_priv *priv;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;

	pci_set_master(pdev);

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable;

	priv->mmio = pci_ioremap_bar(pdev, 0);
	if (!priv->mmio) {
		ret = -ENOMEM;
		goto err_release;
	}

	dev_info(&pdev->dev, "edu id: 0x%08x\n", readl(priv->mmio + 0));


	priv->mdev.minor = MISC_DYNAMIC_MINOR;
	priv->mdev.name  = KBUILD_MODNAME;
	priv->mdev.fops  = &edu_fops;
	ret = misc_register(&priv->mdev);
	if (ret)
		goto err_iounmap;

	pci_set_drvdata(pdev, priv);
	dev_info(&pdev->dev, "edu probed\n");
	return 0;

err_iounmap:
	iounmap(priv->mmio);
err_release:
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
	{ PCI_DEVICE(EDU_VENDOR_ID, EDU_DEVICE_ID), },
	{ }
};
MODULE_DEVICE_TABLE(pci, edu_pci_ids);

static struct pci_driver edu_pci_driver = {
	.name     = KBUILD_MODNAME,
	.id_table = edu_pci_ids,
	.probe    = edu_pci_probe,
	.remove   = edu_pci_remove,
};

module_pci_driver(edu_pci_driver);
MODULE_DESCRIPTION("QEMU edu PCI driver (reharness-synthesized)");
MODULE_LICENSE("GPL");
