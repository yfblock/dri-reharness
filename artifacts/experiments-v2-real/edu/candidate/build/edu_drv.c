#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/pci.h>
#include <linux/mutex.h>

#ifndef IO_ID
#define IO_ID 0
#endif
#ifndef IO_IRQ_STATUS
#define IO_IRQ_STATUS 36
#endif
#ifndef IO_IRQ_ACK
#define IO_IRQ_ACK 100
#endif

struct driver_priv {
	void __iomem *base;
	void __iomem *mmio;
	struct miscdevice misc;
	struct device *dev;
	struct pci_dev *pdev;
	int irq;
	const char *misc_name;
	bool misc_registered;
};

static DEFINE_MUTEX(edu_misc_lock);

static void edu_irq_handler(struct driver_priv *priv)
{
	{ static char __rhcov_fn_edu_irq_handler = 0; if (!__rhcov_fn_edu_irq_handler) { __rhcov_fn_edu_irq_handler = 1; pr_info("[rhcov] edu_irq_handler\n"); } }
	void __iomem *base = priv->base;
	u32 status;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=cba7cb9c854f7b2b379a6926e70a55e7bde349cd29e6920161fe4611ae263ae3 */
__rh_op_op_2: {
		status = readl(priv->mmio + IO_IRQ_STATUS);
	}

	/* REHARNESS_RIS_OP id=op_3 kind=Write status=lowered digest=cba7cb9c854f7b2b379a6926e70a55e7bde349cd29e6920161fe4611ae263ae3 */
__rh_op_op_3: {
		writel(status, priv->mmio + IO_IRQ_ACK);
	}

	(void)base;
}

static int edu_open(struct inode *inode, struct file *file)
{
	{ static char __rhcov_fn_edu_open = 0; if (!__rhcov_fn_edu_open) { __rhcov_fn_edu_open = 1; pr_info("[rhcov] edu_open\n"); } }
	struct miscdevice *misc = file->private_data;
	struct driver_priv *priv;

	(void)inode;
	priv = container_of(misc, struct driver_priv, misc);
	file->private_data = priv;
	return 0;
}

static long edu_read(struct file *filp, char __user *buf,
			     size_t count, loff_t *off)
{
	{ static char __rhcov_fn_edu_read = 0; if (!__rhcov_fn_edu_read) { __rhcov_fn_edu_read = 1; pr_info("[rhcov] edu_read\n"); } }
	void __iomem *base;
	struct driver_priv *priv = filp->private_data;
	u32 val;

	if ((*off & 3) || count < 4)
		return -EINVAL;

	base = priv->base;
	/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=cba7cb9c854f7b2b379a6926e70a55e7bde349cd29e6920161fe4611ae263ae3 */
__rh_op_op_5: {
		val = readl(priv->mmio + *off);
	}
	if (copy_to_user(buf, &val, 4))
		return -EFAULT;
	*off += 4;
	(void)base;
	return 4;
}

static long edu_write(struct file *filp, const char __user *buf,
			      size_t count, loff_t *off)
{
	{ static char __rhcov_fn_edu_write = 0; if (!__rhcov_fn_edu_write) { __rhcov_fn_edu_write = 1; pr_info("[rhcov] edu_write\n"); } }
	void __iomem *base;
	struct driver_priv *priv = filp->private_data;
	u32 val;

	if ((*off & 3) || count < 4)
		return -EINVAL;
	if (copy_from_user(&val, buf, 4))
		return -EFAULT;

	base = priv->base;
	/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=cba7cb9c854f7b2b379a6926e70a55e7bde349cd29e6920161fe4611ae263ae3 */
__rh_op_op_8: {
		writel(val, priv->mmio + *off);
	}
	*off += 4;
	(void)base;
	return 4;
}

static const struct file_operations edu_fops = {
	.owner = THIS_MODULE,
	.open = edu_open,
	.read = edu_read,
	.write = edu_write,
};

static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id)
{
	{ static char __rhcov_fn_edu_pci_probe = 0; if (!__rhcov_fn_edu_pci_probe) { __rhcov_fn_edu_pci_probe = 1; pr_info("[rhcov] edu_pci_probe\n"); } }
	struct driver_priv *priv;
	void __iomem *base;
	int ret;
	u32 dev_id;
	char *fallback_name = NULL;

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

	base = pci_ioremap_bar(pdev, 0);
	if (!base) {
		ret = -ENOMEM;
		goto err_regions;
	}
	priv->base = base;
	priv->mmio = base;

	edu_irq_handler(priv);

	if (priv->mmio) {
		/* REHARNESS_RIS_OP id=op_11 kind=Read status=lowered digest=cba7cb9c854f7b2b379a6926e70a55e7bde349cd29e6920161fe4611ae263ae3 */
__rh_op_op_11: {
			dev_id = readl(priv->mmio + IO_ID);
		}
		(void)dev_id;
	}

	priv->irq = pdev->irq;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.fops = &edu_fops;

	mutex_lock(&edu_misc_lock);
	priv->misc_name = KBUILD_MODNAME;
	priv->misc.name = priv->misc_name;
	ret = misc_register(&priv->misc);
	if (ret == -EBUSY) {
		fallback_name = devm_kasprintf(&pdev->dev, GFP_KERNEL,
					       "%s-%s", KBUILD_MODNAME,
					       pci_name(pdev));
		if (!fallback_name) {
			mutex_unlock(&edu_misc_lock);
			ret = -ENOMEM;
			goto err_iounmap;
		}
		priv->misc_name = fallback_name;
		priv->misc.name = priv->misc_name;
		ret = misc_register(&priv->misc);
	}
	mutex_unlock(&edu_misc_lock);
	if (ret)
		goto err_iounmap;
	priv->misc_registered = true;
	return 0;

err_iounmap:
	iounmap(priv->base);
	priv->base = NULL;
	priv->mmio = NULL;
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
	if (priv->misc_registered) {
		misc_deregister(&priv->misc);
		priv->misc_registered = false;
	}
	if (priv->base) {
		iounmap(priv->base);
		priv->base = NULL;
		priv->mmio = NULL;
	}
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

/* QEMU's EDU device identity; avoid binding unrelated PCI functions. */
static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(0x1234, 0x11e8) },
	{ }
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
MODULE_DESCRIPTION("EDU PCI MMIO harness driver");

