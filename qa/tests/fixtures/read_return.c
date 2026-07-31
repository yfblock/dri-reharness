#include <linux/io.h>

#define RETURN_REG 0x28

static u32 read_return_helper(void __iomem *base)
{
	return readl(base + RETURN_REG);
}

void read_return_update(void __iomem *base, u32 mask)
{
	u32 value = read_return_helper(base);

	writel(value | mask, base + RETURN_REG);
}
