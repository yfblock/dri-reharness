#include <linux/io.h>

#define EARLY_REG 0x20

void early_return(void __iomem *base, unsigned int enabled)
{
	if (!enabled)
		return;

	writel(1, base + EARLY_REG);
}
