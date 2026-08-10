#include "edu_linux.h"


static int edu_open(struct inode *inode, struct file *file)
{
	struct edu_priv *g = container_of(file->private_data, struct edu_priv, misc);
	file->private_data = g;
	return 0;
}

static ssize_t edu_read(struct file *file, char __user *buf, size_t len, loff_t *off)
{
	struct edu_priv *g = file->private_data;
	u32 value;
	if ((*off & 3) || len < sizeof(value))
		return -EINVAL;
	/* REHARNESS_RIS_OP id=op_3 kind=Read status=lowered digest=dbf046aef312a382 */
	value = readl(g->base + *off);
	if (copy_to_user(buf, &value, sizeof(value)))
		return -EFAULT;
	*off += sizeof(value);
	return sizeof(value);
}

static ssize_t edu_write(struct file *file, const char __user *buf, size_t len, loff_t *off)
{
	struct edu_priv *g = file->private_data;
	u32 value;
	if ((*off & 3) || len < sizeof(value))
		return -EINVAL;
	if (copy_from_user(&value, buf, sizeof(value)))
		return -EFAULT;
	/* REHARNESS_RIS_OP id=op_4 kind=Write status=lowered digest=a145d50fd28e9830 */
	writel(value, g->base + *off);
	*off += sizeof(value);
	return sizeof(value);
}

static const struct file_operations edu_fops = {
	.owner = THIS_MODULE,
	.open = edu_open,
	.read = edu_read,
	.write = edu_write,
};

static int edu_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct edu_priv *g;
	int ret;
	(void)id;
	g = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);
	if (!g)
		return -ENOMEM;
	g->dev = &pdev->dev;
	g->pdev = pdev;
	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;
	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable;
	g->base = pci_ioremap_bar(pdev, 0);
	if (!g->base) {
		ret = -ENOMEM;
		goto err_regions;
}
	pci_set_drvdata(pdev, g);
	u32 dev_id = 0;
	void __iomem *base = g->base;
	/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=4b8a9ab4cb9122ff */
	__rh_op_op_5: {
		dev_id = readl(base + IO_ID);
		(void)dev_id;
	}
	g->misc.minor = MISC_DYNAMIC_MINOR;
	g->misc.name = KBUILD_MODNAME;
	g->misc.fops = &edu_fops;
	ret = misc_register(&g->misc);
	if (ret)
		goto err_iounmap;
	dev_info(&pdev->dev, "edu probed\n");
	return 0;
err_iounmap:
	iounmap(g->base);
err_regions:
	pci_release_regions(pdev);
err_disable:
	pci_disable_device(pdev);
	return ret;
}

static void edu_remove(struct pci_dev *pdev)
{
	struct edu_priv *g = pci_get_drvdata(pdev);
	misc_deregister(&g->misc);
	iounmap(g->base);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

static const struct pci_device_id edu_ids[] = {
	{ PCI_DEVICE(0x1234, 0x11e8) },
	{ }
};
MODULE_DEVICE_TABLE(pci, edu_ids);

static struct pci_driver edu_driver = {
	.name = "edu",
	.id_table = edu_ids,
	.probe = edu_probe,
	.remove = edu_remove,
};
module_pci_driver(edu_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("reharness generated driver for edu");
