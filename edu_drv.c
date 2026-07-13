// SPDX-License-Identifier: GPL-2.0
/*
 * edu_drv.c - Linux PCI driver for QEMU edu device (0x1234:0x11e8)
 *
 * Synthesized from .ris/.dspec/.bind by reharness.
 * Target kernel: 7.1.0-rc7
 *
 * Constraints honored:
 *   - PCI driver 0x1234:0x11e8 via module_pci_driver
 *   - file_operations.open uses container_of(file->private_data,
 *       struct edu_priv, mdev); miscdevice has no cdev member
 *   - misc device name = KBUILD_MODNAME, node /dev/edu_drv
 *   - .ris semantics: readl/writel + copy_to/from_user
 *   - probe does NO DMA / NO request_irq (would trigger QEMU edu
 *       interrupt storm -> core dump); probe only ioremap + read id
 *       + misc_register
 */

#include <linux/module.h>
#include <linux/pci.h>
#include <linux/io.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/slab.h>

#define EDU_VENDOR_ID		0x1234
#define EDU_DEVICE_ID		0x11e8

/* Register offsets (from .facts / .dspec) */
#define IO_ID			0x00
#define IO_IRQ_STATUS		0x24
#define IO_IRQ_ACK		0x64
#define IO_DMA_SRC		0x80
#define IO_DMA_DST		0x88
#define IO_DMA_CNT		0x90
#define IO_DMA_CMD		0x98

struct edu_priv {
	void __iomem		*mmio;
	struct miscdevice	mdev;
};

/* ---- .ris: edu_irq_handler ---- */
static irqreturn_t edu_irq_handler(int irq, void *data)
{
	struct edu_priv *priv = data;
	u32 status;

	/* status := R(B4, priv->mmio + IO_IRQ_STATUS) */
	status = readl(priv->mmio + IO_IRQ_STATUS);

	/* W(B4, priv->mmio + IO_IRQ_ACK) = status */
	writel(status, priv->mmio + IO_IRQ_ACK);

	return IRQ_HANDLED;
}

/* ---- .ris: edu_read ---- */
static ssize_t edu_read(struct file *file, char __user *buf, size_t len,
			loff_t *off)
{
	struct edu_priv *priv = container_of(file->private_data,
					     struct edu_priv, mdev);
	u32 val;

	/* val := R(B4, priv->mmio + *off) */
	val = readl(priv->mmio + *off);

	if (copy_to_user(buf, &val, sizeof(val)))
		return -EFAULT;

	*off += sizeof(val);
	return sizeof(val);
}

/* ---- .ris: edu_write ---- */
static ssize_t edu_write(struct file *file, const char __user *buf, size_t len,
			 loff_t *off)
{
	struct edu_priv *priv = container_of(file->private_data,
					     struct edu_priv, mdev);
	u32 val;

	if (copy_from_user(&val, buf, sizeof(val)))
		return -EFAULT;

	/* W(B4, priv->mmio + *off) = val */
	writel(val, priv->mmio + *off);

	*off += sizeof(val);
	return sizeof(val);
}

static int edu_open(struct inode *inode, struct file *file)
{
	/*
	 * misc framework sets file->private_data to &mdev on open;
	 * edu_read/edu_write recover priv via container_of. Nothing
	 * else to do here.
	 */
	return 0;
}

static const struct file_operations edu_fops = {
	.owner		= THIS_MODULE,
	.read		= edu_read,
	.write		= edu_write,
	.open		= edu_open,
};

/* ---- .ris: edu_pci_probe ---- */
static int edu_pci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct edu_priv *priv;
	u32 dev_id;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	/* require resources_available */
	ret = pci_enable_device_mem(pdev);
	if (ret) {
		dev_err(&pdev->dev, "cannot enable device\n");
		return ret;
	}

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret) {
		dev_err(&pdev->dev, "cannot request regions\n");
		goto err_disable;
	}

	/* bind base: MmioBase from priv->mmio */
	priv->mmio = pci_ioremap_bar(pdev, 0);
	if (!priv->mmio) {
		dev_err(&pdev->dev, "cannot ioremap bar 0\n");
		ret = -ENOMEM;
		goto err_regions;
	}

	pci_set_master(pdev);
	pci_set_drvdata(pdev, priv);

	/* dev_id := R(B4, priv->mmio.IO_ID) */
	dev_id = readl(priv->mmio + IO_ID);
	dev_info(&pdev->dev, "edu device id: 0x%x\n", dev_id);

	/*
	 * NO DMA, NO request_irq here (constraint).
	 * The irq_handler symbol is kept for completeness but is not
	 * registered in probe to avoid the QEMU edu interrupt storm.
	 */

	priv->mdev.minor	= MISC_DYNAMIC_MINOR;
	priv->mdev.name		= KBUILD_MODNAME;
	priv->mdev.fops		= &edu_fops;
	/* node appears as /dev/edu_drv via module name */

	ret = misc_register(&priv->mdev);
	if (ret) {
		dev_err(&pdev->dev, "cannot register misc device\n");
		goto err_iounmap;
	}

	/* ensure device_state == READY */
	dev_info(&pdev->dev, "edu probe complete\n");
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
	.name		= KBUILD_MODNAME,
	.id_table	= edu_pci_ids,
	.probe		= edu_pci_probe,
	.remove		= edu_pci_remove,
};

module_pci_driver(edu_pci_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QEMU edu PCI driver (reharness synthesized)");
MODULE_AUTHOR("reharness");
