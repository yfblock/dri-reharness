#include <linux/io.h>

#define FIRST_REG 0x10
#define SECOND_REG 0x14

void goto_control(void __iomem *base, unsigned int skip)
{
	if (skip)
		goto out;

	writel(1, base + FIRST_REG);
out:
	writel(2, base + SECOND_REG);
}
