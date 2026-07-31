#include <linux/io.h>

extern void __iomem *svf_linked_map_hw(void);

void svf_linked_alias_use(void)
{
	void __iomem *linked_alias = svf_linked_map_hw();

	writel(1, linked_alias + 0x24);
}
