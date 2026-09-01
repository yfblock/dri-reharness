#include <linux/module.h>
#include <linux/io.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/err.h>
#include <linux/of.h>
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

static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p) ({ u32 __v = __raw_readl(p); pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })

#define EDU_VENDOR_ID 4660
#define EDU_DEVICE_ID 4584
#define DMA_BASE 262144
#define DMA_CMD 1
#define DMA_IRQ 4
#define IO_APIC_DEFAULT_PHYS_BASE 4273995776
#define IO_APIC_SLOT_SIZE 1024
#define IO_BITMAP_BITS 65536
#define IO_INTEGRITY_CHK_APPTAG 4
#define IO_INTEGRITY_CHK_GUARD 1
#define IO_INTEGRITY_CHK_REFTAG 2
#define IO_SPACE_LIMIT 65535

#define IO_ID 0x0
#define IO_IRQ_STATUS 36
#define IO_IRQ_ACK 100

struct edu_priv {
	void __iomem *base;
	struct miscdevice misc;
	struct device *dev;
	struct pci_dev *pdev;
	int irq;
};

static int edu_irq_handler(struct edu_priv *priv)
{
	RH_TRACE_FN("edu_irq_handler");
	void __iomem *base = priv->base;
	u32 status;

	/* REHARNESS_RIS_OP id=op_2 kind=Read status=lowered digest=58c605e506ad0c2b */
	status = readl(base + IO_IRQ_STATUS);

	/* REHARNESS_RIS_OP id=op_3 kind=Write status=lowered digest=f479e9c3cf35a289 */
	writel(status, base + IO_IRQ_ACK);

	return 0;
}

static int edu_open(struct inode *inode, struct file *filp)
{
	RH_TRACE_FN("edu_open");
	struct edu_priv *priv = container_of(filp->private_data, struct edu_priv, misc);
	filp->private_data = priv;
	return 0;
}

static ssize_t edu_read(struct file *filp, char __user *buf, size_t count, loff_t *ppos)
{
	RH_TRACE_FN("edu_read");
	struct edu_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if ((*ppos & 3) || count < 4)
		return -EINVAL;

	/* REHARNESS_RIS_OP id=op_6 kind=Read status=lowered digest=dbf046aef312a382 */
	val = readl(base + *ppos);

	if (copy_to_user(buf, &val, 4))
		return -EFAULT;

	*ppos += 4;
	return 4;
}

static ssize_t edu_write(struct file *filp, const char __user *buf, size_t count, loff_t *ppos)
{
	RH_TRACE_FN("edu_write");
	struct edu_priv *priv = filp->private_data;
	void __iomem *base = priv->base;
	u32 val;

	if ((*ppos & 3) || count < 4)
		return -EINVAL;

	if (copy_from_user(&val, buf, 4))
		return -EFAULT;

	/* REHARNESS_RIS_OP id=op_9 kind=Write status=lowered digest=a145d50fd28e9830 */
	writel(val, base + *ppos);

	*ppos += 4;
	return 4;
}

static const struct file_operations edu_fops = {
	.owner = THIS_MODULE,
	.open = edu_open,
	.read = edu_read,
	.write = edu_write,
	.llseek = default_llseek,
};

static int edu_pci_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	RH_TRACE_FN("edu_pci_probe");
	struct edu_priv *priv;
	int ret;
	void __iomem *base;
	u32 dev_id;

	priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	priv->dev = &pdev->dev;
	priv->pdev = pdev;
	priv->irq = pdev->irq;

	ret = pci_enable_device_mem(pdev);
	if (ret)
		return ret;

	ret = pci_request_regions(pdev, KBUILD_MODNAME);
	if (ret)
		goto err_disable;

	base = pci_ioremap_bar(pdev, 0);
	RH_SET_BASE(base);
	priv->base = base;
	if (!base) {
		ret = -ENOMEM;
		goto err_regions;
	}


	edu_irq_handler(priv);

	/* REHARNESS_RIS_OP id=op_12 kind=Read status=lowered digest=4b8a9ab4cb9122ff */
	dev_id = readl(base + IO_ID);

	priv->misc.minor = MISC_DYNAMIC_MINOR;
	priv->misc.name = KBUILD_MODNAME;
	priv->misc.fops = &edu_fops;
	priv->misc.parent = &pdev->dev;


	ret = misc_register(&priv->misc);
	if (ret)
		goto err_iounmap;

	pci_set_drvdata(pdev, priv);
	return 0;

err_iounmap:
	pci_iounmap(pdev, base);
err_regions:
	pci_release_regions(pdev);
err_disable:
	pci_disable_device(pdev);
	return ret;
}

static void edu_pci_remove(struct pci_dev *pdev)
{
	RH_TRACE_FN("edu_pci_remove");
	struct edu_priv *priv = pci_get_drvdata(pdev);

	if (!priv)
		return;

	misc_deregister(&priv->misc);
	if (priv->base)
		pci_iounmap(pdev, priv->base);
	pci_release_regions(pdev);
	pci_disable_device(pdev);
}

static const struct pci_device_id edu_pci_ids[] = {
	{ PCI_DEVICE(EDU_VENDOR_ID, EDU_DEVICE_ID) },
	{ 0, }
};
MODULE_DEVICE_TABLE(pci, edu_pci_ids);

static struct pci_driver edu_pci_driver = {
	.name = KBUILD_MODNAME,
	.id_table = edu_pci_ids,
	.probe = edu_pci_probe,
	.remove = edu_pci_remove,
};

static int __init edu_init(void)
{
	RH_TRACE_FN("edu_init");
	return pci_register_driver(&edu_pci_driver);
}

static void __exit edu_exit(void)
{
	RH_TRACE_FN("edu_exit");
	pci_unregister_driver(&edu_pci_driver);
}

module_init(edu_init);
module_exit(edu_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("edu target implementation");