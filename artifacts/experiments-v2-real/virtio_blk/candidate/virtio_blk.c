#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/pci.h>

struct driver_priv {
	void __iomem *base;
	struct miscdevice misc;
	struct device *dev;
};

static int virtio_blk_open(struct inode *inode, struct file *file)
{
	struct miscdevice *misc = file->private_data;
	struct driver_priv *priv;

	priv = container_of(misc, struct driver_priv, misc);
	file->private_data = priv;
	return 0;
}

static ssize_t virtio_blk_read(struct file *file, char __user *buf,
			       size_t count, loff_t *ppos)
{
	struct driver_priv *priv = file->private_data;
	u32 val;

	if (*ppos < 0 || (*ppos & 3) || count < 4)
		return -EINVAL;

	val = readl(priv->base + *ppos);
	if (copy_to_user(buf, &val, 4))
		return -EFAULT;

	*ppos += 4;
	return 4;
}

static ssize_t virtio_blk_write(struct file *file, const char __user *buf,
				 size_t count, loff_t *ppos)
{
	struct driver_priv *priv = file->private_data;
	u32 val;

	if (*ppos < 0 || (*ppos & 3) || count < 4)
		return -EINVAL;

	if (copy_from_user(&val, buf, 4))
		return -EFAULT;

	writel(val, priv->base + *ppos);
	*ppos += 4;
	return 4;
}

static const struct file_operations virtio_blk_fops = {
	.owner = THIS_MODULE,
	.open = virtio_blk_open,
	.read = virtio_blk_read,
	.write = virtio_blk_write,
};

static int virtio_blk_probe(struct pci_dev *pdev,
			    const struct pci_device_id *id)
{
	struct driver_priv *priv;
	void __iomem *base;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable_device;

	base = pci_ioremap_bar(pdev, 0);
	if (!base) {
		ret = -ENOMEM;
		goto err_release_regions;
	}

	priv->base = base;
	priv->dev = &pdev->dev;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &virtio_blk_fops;
	priv->misc.parent = &pdev->dev;

	pci_set_drvdata(pdev, priv);

	ret = misc_register(&priv->misc);
	if (ret)
		goto err_iounmap;

	return 0;

err_iounmap:
	pci_iounmap(pdev, priv->base);
err_release_regions:
	pci_release_regions(pdev);
err_disable_device:
	pci_disable_device(pdev);
	return ret;
}

static void virtio_blk_remove(struct pci_dev *pdev)
{
	struct driver_priv *priv = pci_get_drvdata(pdev);

	if (!priv)
		return;

	misc_deregister(&priv->misc);
	pci_iounmap(pdev, priv->base);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

static struct pci_driver virtio_blk_driver = {
	.name = KBUILD_MODNAME,
	.probe = virtio_blk_probe,
	.remove = virtio_blk_remove,
};

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("virtio_blk PCI MMIO harness");

module_pci_driver(virtio_blk_driver);
