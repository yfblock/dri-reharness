#include <linux/io.h>

#define SWITCH_REG 0x10

void switch_paths(void __iomem *base, unsigned int mode)
{
	switch (mode) {
	case 1:
		writel(1, base + SWITCH_REG);
		break;
	case 2:
		writel(2, base + SWITCH_REG);
		break;
	default:
		writel(0, base + SWITCH_REG);
		break;
	}
}
