#include <linux/io.h>

void infeasible_path(void __iomem *base, unsigned int enabled)
{
	if (enabled) {
		if (!enabled)
			writel(1, base);
	}
}
