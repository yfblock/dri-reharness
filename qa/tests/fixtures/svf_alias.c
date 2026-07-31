#include <linux/io.h>

void svf_alias_probe(void)
{
	void __iomem *base = ioremap(0x1000, 0x100);
	void __iomem *alias = base;

	writel(1, alias + 0x20);
}
