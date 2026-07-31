#include <linux/io.h>

void __iomem *svf_linked_map_hw(void)
{
	return ioremap(0x2000, 0x100);
}
