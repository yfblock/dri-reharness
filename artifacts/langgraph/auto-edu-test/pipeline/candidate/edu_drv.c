#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pci.h>

/* === reharness MMIO trace instrumentation (file-local, after includes) === */
static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
#undef readb
#define readb(p)    ({ u8  __v = __raw_readb(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writeb
#define writeb(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writeb((v),(p)); })
#undef readw
#define readw(p)    ({ u16 __v = __raw_readw(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writew
#define writew(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writew((v),(p)); })
#undef ioread32
#define ioread32(p)    ({ u32 __v = __raw_readl(p);  pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef iowrite32
#define iowrite32(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })
/* === end instrumentation === */

#define IO_ID          0x00000000
#define IO_IRQ_STATUS  0x00000024
#define IO_IRQ_ACK     0x00000064

#define EDU_VENDOR_ID  0x1234
#define EDU_DEVICE_ID  0x11e8

struct driver_priv {
	void __iomem *base;
	void __iomem *mmio;
	struct miscdevice misc;
	struct device *dev;
	struct pci_dev *pdev;
	int irq;
};

static int edu_open(struct inode *inode, struct file *filp);
static long edu_read(struct file *filp, char __user *buf,
		     size_t count, loff_t *off);
static long edu_write(struct file *filp, const char __user *buf,
		      size_t count, loff_t *off);
static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id);
static void edu_pci_remove(struct pci_dev *pdev);

static const struct file_operations edu_fops = {
	.owner = THIS_MODULE,
	.open = edu_open,
	.read = edu_read,
	.write = edu_write,
};

static u32 edu_irq_handler(struct driver_priv *priv)
{
	RH_TRACE_FN("edu_irq_handler");
	void __iomem *base = priv->base;
	u32 status;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=58c605e506ad0c2b */
	__rh_op_op_2: {
		status = readl(base + IO_IRQ_STATUS);
	}

	/* REHARNESS_RIS_OP id=op_3 kind=Write status=lowered digest=f479e9c3cf35a289 */
	__rh_op_op_3: {
		writel(status, base + IO_IRQ_ACK);
	}

	return status;
}

static int edu_open(struct inode *inode, struct file *filp)
{
	RH_TRACE_FN("edu_open");
	struct miscdevice *misc = filp->private_data;
	struct driver_priv *priv;

	if (!misc)
		return -ENODEV;

	priv = container_of(misc, struct driver_priv, misc);
	filp->private_data = priv;
	return 0;
}

static long edu_read(struct file *filp, char __user *buf,
		     size_t count, loff_t *off)
{
	RH_TRACE_FN("edu_read");
	struct driver_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if (!priv || !off || (*off & 3) || count < sizeof(val))
		return -EINVAL;

	/* REHARNESS_RIS_OP id=op_5 kind=Read status=lowered digest=dbf046aef312a382 */
	__rh_op_op_5: {
		val = readl(priv->mmio + *off);
	}

	if (copy_to_user(buf, &val, sizeof(val)))
		return -EFAULT;

	*off += 4;
	return 4;
}

static long edu_write(struct file *filp, const char __user *buf,
		      size_t count, loff_t *off)
{
	RH_TRACE_FN("edu_write");
	struct driver_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if (!priv || !off || (*off & 3) || count < sizeof(val))
		return -EINVAL;

	if (copy_from_user(&val, buf, sizeof(val)))
		return -EFAULT;

	/* REHARNESS_RIS_OP id=op_8 kind=Write status=lowered digest=a145d50fd28e9830 */
	__rh_op_op_8: {
		writel(val, priv->mmio + *off);
	}

	*off += 4;
	return 4;
}

static int edu_pci_probe(struct pci_dev *pdev,
			 const struct pci_device_id *id)
{
	RH_TRACE_FN("edu_pci_probe");
	struct driver_priv *priv;
	void __iomem *base;
	u32 dev_id;
	int ret;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable;

	base = pci_ioremap_bar(pdev, 0);
	RH_SET_BASE(base);
	if (!base) {
		ret = -ENOMEM;
		goto err_regions;
	}

	priv->base = base;
	priv->mmio = base;
	priv->dev = &pdev->dev;

	priv->pdev = pdev;

	if (priv->mmio != 0) {
		ret = 0;
		if (ret == 0) {
			/* REHARNESS_RIS_OP id=op_11 kind=Read status=lowered digest=4b8a9ab4cb9122ff */
			__rh_op_op_11: {
				dev_id = readl(priv->mmio + IO_ID);
			}
			(void)dev_id;
		}
	}

	priv->irq = pdev->irq;
	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &edu_fops;
	priv->misc.parent = &pdev->dev;

	pci_set_drvdata(pdev, priv);

	ret = misc_register(&priv->misc);
	if (ret)
		goto err_iounmap;

	return 0;

err_iounmap:
	pci_iounmap(pdev, priv->mmio);
err_regions:
	pci_release_regions(pdev);
err_disable:
	pci_disable_device(pdev);
	return ret;
}

static void edu_pci_remove(struct pci_dev *pdev)
{
	RH_TRACE_FN("edu_pci_remove");
	struct driver_priv *priv = pci_get_drvdata(pdev);

	if (!priv)
		return;

	misc_deregister(&priv->misc);
	pci_iounmap(pdev, priv->mmio);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(EDU_VENDOR_ID, EDU_DEVICE_ID) },
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
MODULE_DESCRIPTION("EDU PCI MMIO driver");
