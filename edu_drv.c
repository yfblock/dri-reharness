/*
 * edu_drv.c - Synthesized Linux PCI driver for the QEMU "edu" educational device.
 *
 * Target kernel: 7.1.0-rc7
 *
 * PCI vendor 0x1234 / device 0x11e8. Registered via module_pci_driver.
 *
 * Synthesized from .ris/.dspec/.bind/.facts by reharness. The .ris contract:
 *   module edu_irq_handler: readl(IO_IRQ_STATUS); writel(IO_IRQ_ACK, status)
 *   module edu_read:        val := readl(mmio + *off); copy_to_user
 *   module edu_write:       writel(mmio + *off, val);  copy_from_user
 *   module edu_pci_probe:   dev_id := readl(mmio + IO_ID); misc_register
 *
 * Register offsets (per .dspec / key facts):
 *   IO_ID         0x00
 *   IO_IRQ_STATUS 0x24
 *   IO_IRQ_ACK    0x64
 *   IO_DMA_SRC    0x80
 *   IO_DMA_DST    0x88
 *   IO_DMA_CNT    0x90
 *   IO_DMA_CMD    0x98
 *
 * Stability note (must NOT be broken):
 *   probe() does NOT request_irq, does NOT dma_alloc, and does NOT write
 *   DMA_CMD|DMA_IRQ. Kicking DMA from probe raises an interrupt storm that
 *   wedges/crashes QEMU. probe() only: ioremap + read ID + misc_register.
 *   The irq_handler is provided per the .ris contract but is intentionally
 *   never registered; mark it __maybe_unused so the compiler keeps it.
 */

#include <linux/fs.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/uaccess.h>
#include <linux/io.h>
#include <linux/miscdevice.h>

/* ---- Device / register constants -------------------------------------- */

#define EDU_VENDOR_ID		0x1234
#define EDU_DEVICE_ID		0x11e8

#define IO_ID			0x00
#define IO_IRQ_STATUS		0x24
#define IO_IRQ_ACK		0x64
#define IO_DMA_SRC		0x80
#define IO_DMA_DST		0x88
#define IO_DMA_CNT		0x90
#define IO_DMA_CMD		0x98

/* ---- Per-device private data ------------------------------------------ */

struct edu_priv {
	void __iomem	*mmio;
	int		 irq;
	struct pci_dev	*pdev;
	struct miscdevice mdev;
};

/* ---- Interrupt handler ------------------------------------------------
 *
 * Per .ris module edu_irq_handler:
 *   status := R(B4, priv->mmio.IO_IRQ_STATUS)   -- readl
 *   W(B4, priv->mmio.IO_IRQ_ACK) = status        -- writel
 *
 * Intentionally NOT registered from probe() to avoid the QEMU edu interrupt
 * storm. Kept to satisfy the .ris contract; __maybe_unused silences the
 * unused-function warning.
 */
static irqreturn_t __maybe_unused edu_irq_handler(int irq, void *data)
{
	struct edu_priv *priv = data;
	u32 status;

	status = readl(priv->mmio + IO_IRQ_STATUS);
	if (status == 0)
		return IRQ_NONE;

	writel(status, priv->mmio + IO_IRQ_ACK);
	return IRQ_HANDLED;
}

/* ---- file_operations -------------------------------------------------- */

/*
 * Per .bind: file_operations.open must recover priv via
 *   container_of(file->private_data, struct edu_priv, mdev)
 * (struct miscdevice has no cdev member).
 */
static int edu_open(struct inode *inode, struct file *filp)
{
	struct edu_priv *priv = container_of(filp->private_data,
					     struct edu_priv, mdev);

	filp->private_data = priv;
	return 0;
}

/* Per .ris module edu_read: val := R(B4, priv->mmio + *off[0x0]); copy_to_user. */
static ssize_t edu_read(struct file *filp, char __user *buf,
			size_t len, loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 val;

	if (*off % 4 || len < 4)
		return -EINVAL;

	val = readl(priv->mmio + *off);

	if (copy_to_user(buf, &val, sizeof(val)))
		return -EFAULT;

	*off += 4;
	return 4;
}

/* Per .ris module edu_write: W(B4, priv->mmio + *off[0x0]) = val; copy_from_user. */
static ssize_t edu_write(struct file *filp, const char __user *buf,
			 size_t len, loff_t *off)
{
	struct edu_priv *priv = filp->private_data;
	u32 val;

	if (*off % 4 || len < 4)
		return -EINVAL;

	if (copy_from_user(&val, buf, sizeof(val)))
		return -EFAULT;

	writel(val, priv->mmio + *off);

	*off += 4;
	return 4;
}

static const struct file_operations edu_fops = {
	.owner	= THIS_MODULE,
	.open	= edu_open,
	.read	= edu_read,
	.write	= edu_write,
};

/* ---- PCI probe / remove ---------------------------------------------- */

/*
 * Per .ris module edu_pci_probe and .dspec role probe:
 *   require resources_available
 *   dev_id := R(B4, priv->mmio.IO_ID)
 *   effect initializes_device()
 *   ensure device_state == READY
 *
 * Forbidden in probe (interrupt storm / QEMU core dump):
 *   request_irq, dma_alloc, writel(DMA_CMD|DMA_IRQ).
 */
static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id)
{
	struct edu_priv *priv;
	u32 dev_id;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->pdev = pdev;

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

	priv->mmio = pci_ioremap_bar(pdev, 0);
	if (!priv->mmio) {
		dev_err(&pdev->dev, "cannot ioremap bar 0\n");
		ret = -ENOMEM;
		goto err_regions;
	}

	/* Read the identification register (0x00) per .ris probe. */
	dev_id = readl(priv->mmio + IO_ID);
	dev_info(&pdev->dev, "edu id reg: 0x%x\n", dev_id);

	priv->irq = pdev->irq;

	priv->mdev.minor = MISC_DYNAMIC_MINOR;
	priv->mdev.name  = KBUILD_MODNAME;
	priv->mdev.fops  = &edu_fops;

	ret = misc_register(&priv->mdev);
	if (ret) {
		dev_err(&pdev->dev, "cannot register misc device\n");
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

	misc_deregister(&priv->mdev);
	iounmap(priv->mmio);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

/* ---- PCI driver / module glue ---------------------------------------- */

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

MODULE_AUTHOR("reharness");
MODULE_DESCRIPTION("QEMU edu PCI driver (synthesized)");
MODULE_LICENSE("GPL");
