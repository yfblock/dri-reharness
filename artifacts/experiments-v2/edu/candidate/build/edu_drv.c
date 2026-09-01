#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/pci.h>
#include <linux/interrupt.h>

#define IO_ID          0x00
#define IO_IRQ_STATUS  0x24
#define IO_IRQ_ACK     0x64

struct driver_priv {
	void __iomem *base;
	void __iomem *mmio;
	struct miscdevice misc;
	struct device *dev;
	struct pci_dev *pdev;
	int irq;
};

static irqreturn_t edu_irq_handler(int irq, void *data)
{
	{ static char __rhcov_fn_edu_irq_handler = 0; if (!__rhcov_fn_edu_irq_handler) { __rhcov_fn_edu_irq_handler = 1; pr_info("[rhcov] edu_irq_handler\n"); } }
	struct driver_priv *priv = data;
	void __iomem *base = priv->base;
	u32 status;

	(void)irq;
	(void)base;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=6ee0d5150dc81aea5ec0044875c9a24c5723166ebddc5af940c8b859308a30ab */
	__rh_op_op_2: {
		status = readl(priv->mmio + IO_IRQ_STATUS);
	}

	/* REHARNESS_RIS_OP id=op_3 kind=Write status=lowered digest=6ee0d5150dc81aea5ec0044875c9a24c5723166ebddc5af940c8b859308a30ab */
	__rh_op_op_3: {
		writel(status, priv->mmio + IO_IRQ_ACK);
	}

	return IRQ_HANDLED;
}

static int edu_open(struct inode *inode, struct file *filp)
{
	{ static char __rhcov_fn_edu_open = 0; if (!__rhcov_fn_edu_open) { __rhcov_fn_edu_open = 1; pr_info("[rhcov] edu_open\n"); } }
	struct miscdevice *misc = filp->private_data;
	struct driver_priv *priv;

	(void)inode;
	priv = container_of(misc, struct driver_priv, misc);
	filp->private_data = priv;
	return 0;
}

static ssize_t edu_read(struct file *filp, char __user *buf,
			unsigned long count, loff_t *off)
{
	{ static char __rhcov_fn_edu_read = 0; if (!__rhcov_fn_edu_read) { __rhcov_fn_edu_read = 1; pr_info("[rhcov] edu_read\n"); } }
	struct driver_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	(void)base;
	if ((*off & 3) || count < 4)
		return -EINVAL;

	/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=6ee0d5150dc81aea5ec0044875c9a24c5723166ebddc5af940c8b859308a30ab */
	__rh_op_op_5: {
		val = readl(priv->mmio + *off);
	}

	if (copy_to_user(buf, &val, 4))
		return -EFAULT;
	*off += 4;
	return 4;
}

static ssize_t edu_write(struct file *filp, const char __user *buf,
			 unsigned long count, loff_t *off)
{
	{ static char __rhcov_fn_edu_write = 0; if (!__rhcov_fn_edu_write) { __rhcov_fn_edu_write = 1; pr_info("[rhcov] edu_write\n"); } }
	struct driver_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	(void)base;
	if ((*off & 3) || count < 4)
		return -EINVAL;
	if (copy_from_user(&val, buf, 4))
		return -EFAULT;

	/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=6ee0d5150dc81aea5ec0044875c9a24c5723166ebddc5af940c8b859308a30ab */
	__rh_op_op_8: {
		writel(val, priv->mmio + *off);
	}

	*off += 4;
	return 4;
}

static const struct file_operations edu_fops = {
	.owner = THIS_MODULE,
	.open = edu_open,
	.read = edu_read,
	.write = edu_write,
	.llseek = default_llseek,
};

static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id)
{
	{ static char __rhcov_fn_edu_pci_probe = 0; if (!__rhcov_fn_edu_pci_probe) { __rhcov_fn_edu_pci_probe = 1; pr_info("[rhcov] edu_pci_probe\n"); } }
	struct driver_priv *priv;
	u32 dev_id;
	int ret;

	(void)id;
	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->dev = &pdev->dev;
	priv->pdev = pdev;
	pci_set_drvdata(pdev, priv);

	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable;

	priv->base = pci_ioremap_bar(pdev, 0);
	priv->mmio = priv->base;
	if (!priv->mmio) {
		ret = -ENOMEM;
		goto err_regions;
	}

	/* REHARNESS_RIS_OP id=op_11 kind=Read status=lowered digest=6ee0d5150dc81aea5ec0044875c9a24c5723166ebddc5af940c8b859308a30ab */
	__rh_op_op_11: {
		dev_id = readl(priv->mmio + IO_ID);
	}
	(void)dev_id;

	priv->irq = pdev->irq;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &edu_fops;
	priv->misc.parent = &pdev->dev;

	ret = misc_register(&priv->misc);
	if (ret)
		goto err_iounmap;

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
	{ static char __rhcov_fn_edu_pci_remove = 0; if (!__rhcov_fn_edu_pci_remove) { __rhcov_fn_edu_pci_remove = 1; pr_info("[rhcov] edu_pci_remove\n"); } }
	struct driver_priv *priv = pci_get_drvdata(pdev);

	if (!priv)
		return;
	misc_deregister(&priv->misc);
	if (priv->mmio)
		iounmap(priv->mmio);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(0x1234, 0x11e8) },
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
MODULE_DESCRIPTION("EDU PCI MMIO driver harness");

