// SPDX-License-Identifier: GPL-2.0
/*
 * edu_drv.c - QEMU edu PCI driver (synthesized by reharness)
 * Target: Linux 7.1.0-rc7
 */

#include <linux/cdev.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uaccess.h>

#define BAR 0
#define EDU_DEVICE_ID 0x11e8
#define QEMU_VENDOR_ID 0x1234

/* Registers (BAR0 MMIO). */
#define IO_IRQ_STATUS 0x24
#define IO_IRQ_ACK    0x64
#define IO_DMA_SRC    0x80
#define IO_DMA_DST    0x88
#define IO_DMA_CNT    0x90
#define IO_DMA_CMD    0x98

/* Constants. */
#define DMA_BASE  0x40000
#define DMA_CMD   0x1
#define DMA_IRQ   0x4

struct edu_priv {
	void __iomem *mmio;
	int irq;
	struct pci_dev *pdev;
	struct miscdevice mdev;
};

static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(QEMU_VENDOR_ID, EDU_DEVICE_ID), },
	{ 0, }
};
MODULE_DEVICE_TABLE(pci, edu_pci_ids);

static irqreturn_t edu_irq_handler(int irq, void *data)
{
	struct edu_priv *priv = data;
	u32 status;

	status = readl(priv->mmio + IO_IRQ_STATUS);
	if (status == 0)
		return IRQ_NONE;

	writel(status, priv->mmio + IO_IRQ_ACK);
	return IRQ_HANDLED;
}

static ssize_t edu_read(struct file *filp, char __user *buf, size_t len, loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 kbuf;

	if (*off % 4 || len < 4)
		return -EINVAL;

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
		return -EINVAL;

	if (copy_from_user(&kbuf, buf, 4))
		return -EFAULT;

	writel(kbuf, priv->mmio + *off);
	*off += 4;
	return 4;
}

static int edu_open(struct inode *inode, struct file *filp)
{
	struct edu_priv *priv = container_of(filp->private_data,
					     struct edu_priv, mdev);
	filp->private_data = priv;
	return 0;
}

static const struct file_operations edu_fops = {
	.owner   = THIS_MODULE,
	.open    = edu_open,
	.read    = edu_read,
	.write   = edu_write,
};

static int edu_pci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct edu_priv *priv;
	u32 ident;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	priv->pdev = pdev;

	ret = pci_enable_device_mem(pdev);
	if (ret) {
		dev_err(&pdev->dev, "pci_enable_device_mem\n");
		return ret;
	}

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret) {
		dev_err(&pdev->dev, "pci_request_regions\n");
		goto err_disable;
	}

	priv->mmio = pci_ioremap_bar(pdev, BAR);
	if (!priv->mmio) {
		dev_err(&pdev->dev, "pci_ioremap_bar\n");
		ret = -ENOMEM;
		goto err_regions;
	}

	/* Read identification register at offset 0x0. */
	ident = readl(priv->mmio + 0x0);
	dev_info(&pdev->dev, "edu id reg = 0x%x\n", ident);

	/*
	 * No request_irq() / dma_alloc_coherent() / DMA_CMD|DMA_IRQ writes
	 * here: triggering DMA in probe causes a QEMU edu interrupt storm
	 * (core dump / 0-byte serial timeout). irq_handler is defined but
	 * not registered; priv->irq is only recorded for on-demand use.
	 */
	priv->irq = pdev->irq;

	priv->mdev.minor = MISC_DYNAMIC_MINOR;
	priv->mdev.name  = KBUILD_MODNAME;
	priv->mdev.fops  = &edu_fops;

	ret = misc_register(&priv->mdev);
	if (ret) {
		dev_err(&pdev->dev, "misc_register\n");
		goto err_iounmap;
	}

	pci_set_drvdata(pdev, priv);
	dev_info(&pdev->dev, "edu probed (irq %d)\n", priv->irq);
	return 0;

err_iounmap:
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

	/*
	 * probe deliberately did NOT request_irq() (would trigger the QEMU
	 * edu interrupt storm), so there is nothing to free_irq() here.
	 * Freeing an IRQ we never requested trips kernel/irq/manage.c
	 * warnings / oops during rmmod -> with panic=1 that kills QEMU.
	 * Release only what probe actually acquired (paired release).
	 */
	misc_deregister(&priv->mdev);
	iounmap(priv->mmio);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
	dev_info(&pdev->dev, "edu removed\n");
}

static struct pci_driver edu_pci_driver = {
	.name     = KBUILD_MODNAME,
	.id_table = edu_pci_ids,
	.probe    = edu_pci_probe,
	.remove   = edu_pci_remove,
};

module_pci_driver(edu_pci_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU edu PCI driver");
MODULE_AUTHOR("reharness");
