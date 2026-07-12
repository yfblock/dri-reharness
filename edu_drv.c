// SPDX-License-Identifier: GPL-2.0
/*
 * edu_drv.c - Linux PCI driver for the QEMU "edu" educational device.
 *
 * Target kernel: 7.1.0-rc7.  Single-file module (KBUILD_MODNAME="edu_drv").
 *
 * Synthesized from .ris/.dspec/.bind/.facts extracted by reharness from the
 * upstream QEMU edu PCI sample driver.  Follows the prescribed stable code
 * patterns: miscdevice (named mdev), devm + ioremap probe (no DMA command
 * writes / no request_irq in probe to avoid the QEMU edu IRQ storm that can
 * crash QEMU), paired cleanup in remove().
 */

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

/* ------------------------------------------------------------------ */
/* Device / register constants                                         */
/* ------------------------------------------------------------------ */

#define QEMU_VENDOR_ID	0x1234
#define EDU_DEVICE_ID	0x11e8

#define BAR			0

/* BAR0 MMIO registers (B4 = 32-bit). */
#define IO_IRQ_STATUS	0x24
#define IO_IRQ_ACK	0x64
#define IO_DMA_SRC	0x80
#define IO_DMA_DST	0x88
#define IO_DMA_CNT	0x90
#define IO_DMA_CMD	0x98

/* DMA constants. */
#define DMA_BASE	0x40000u
#define DMA_CMD		0x1u
#define DMA_IRQ		0x4u

/* DMA scratch buffer size (bytes). */
#define DMA_BUF_SIZE	4

/* ------------------------------------------------------------------ */
/* Per-device private data                                            */
/* ------------------------------------------------------------------ */

struct edu_priv {
	void __iomem		*mmio;
	int			irq;
	struct pci_dev		*pdev;
	struct miscdevice	mdev;

	/* Optional DMA fields. */
	void			*dma_buf;
	dma_addr_t		dma_handle;
};

/* ------------------------------------------------------------------ */
/* PCI ID table                                                       */
/* ------------------------------------------------------------------ */

static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(QEMU_VENDOR_ID, EDU_DEVICE_ID), },
	{ 0, }
};
MODULE_DEVICE_TABLE(pci, edu_pci_ids);

/* ------------------------------------------------------------------ */
/* Interrupt handler                                                  */
/* ------------------------------------------------------------------ */

static irqreturn_t edu_irq_handler(int irq, void *data)
{
	struct edu_priv *priv = data;
	u32 status;

	if (!priv || !priv->mmio)
		return IRQ_NONE;

	status = readl(priv->mmio + IO_IRQ_STATUS);
	if (status == 0)
		return IRQ_NONE;

	writel(status, priv->mmio + IO_IRQ_ACK);
	return IRQ_HANDLED;
}

/* ------------------------------------------------------------------ */
/* File operations                                                    */
/* ------------------------------------------------------------------ */

static int edu_open(struct inode *inode, struct file *filp)
{
	struct edu_priv *priv = container_of(filp->private_data,
					     struct edu_priv, mdev);
	filp->private_data = priv;
	return 0;
}

static ssize_t edu_read(struct file *filp, char __user *buf, size_t len,
			loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 kbuf;

	if (*off % 4 || len == 0)
		return 0;

	kbuf = readl(priv->mmio + *off);
	if (copy_to_user(buf, &kbuf, 4))
		return -EFAULT;

	*off += 4;
	return 4;
}

static ssize_t edu_write(struct file *filp, const char __user *buf, size_t len,
			 loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 kbuf;

	if (*off % 4)
		return len;

	if (copy_from_user(&kbuf, buf, 4) || len != 4)
		return -EFAULT;

	writel(kbuf, priv->mmio + *off);
	return 4;
}

static const struct file_operations edu_fops = {
	.owner	= THIS_MODULE,
	.open	= edu_open,
	.read	= edu_read,
	.write	= edu_write,
};

/* ------------------------------------------------------------------ */
/* PCI probe / remove                                                 */
/* ------------------------------------------------------------------ */

static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id)
{
	struct edu_priv *priv;
	u32 edu_id;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->pdev = pdev;

	ret = pci_enable_device_mem(pdev);
	if (ret) {
		dev_err(&pdev->dev, "pci_enable_device_mem failed: %d\n", ret);
		return ret;
	}

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret) {
		dev_err(&pdev->dev, "pci_request_regions failed: %d\n", ret);
		goto err_disable;
	}

	priv->mmio = pci_ioremap_bar(pdev, BAR);
	if (!priv->mmio) {
		dev_err(&pdev->dev, "pci_ioremap_bar failed\n");
		ret = -ENOMEM;
		goto err_regions;
	}

	/* Sanity: read the edu identification register at offset 0x0. */
	edu_id = readl(priv->mmio + 0x0);
	dev_info(&pdev->dev, "edu probed (id 0x%x)\n", edu_id);

	priv->irq = pdev->irq;

	priv->mdev.minor = MISC_DYNAMIC_MINOR;
	priv->mdev.name  = KBUILD_MODNAME;	/* /dev/edu_drv */
	priv->mdev.fops  = &edu_fops;

	ret = misc_register(&priv->mdev);
	if (ret) {
		dev_err(&pdev->dev, "misc_register failed: %d\n", ret);
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

	if (!priv)
		return;

	misc_deregister(&priv->mdev);

	if (priv->irq)
		free_irq(priv->irq, priv);

	if (priv->dma_buf)
		dma_free_coherent(&pdev->dev, DMA_BUF_SIZE,
				  priv->dma_buf, priv->dma_handle);

	if (priv->mmio)
		iounmap(priv->mmio);

	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

/* ------------------------------------------------------------------ */
/* PCI driver                                                         */
/* ------------------------------------------------------------------ */

static struct pci_driver edu_pci_driver = {
	.name		= KBUILD_MODNAME,
	.id_table	= edu_pci_ids,
	.probe		= edu_pci_probe,
	.remove		= edu_pci_remove,
};

module_pci_driver(edu_pci_driver);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("reharness");
MODULE_DESCRIPTION("QEMU edu PCI driver (synthesized)");
