#include <linux/io.h>

void control_flow(void __iomem *base, unsigned int count)
{
	unsigned int i;

	for (i = 0; i < count; i++) {
		if (i & 1)
			writel(i, base + i * 4);
		else
			writel(0, base + i * 4);
	}
}
