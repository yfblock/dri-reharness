#include <linux/io.h>

void bounded_loop(void __iomem *base)
{
	unsigned int i;

	for (i = 0; i < 4; i++)
		writel(i, base + i * 4);
}
