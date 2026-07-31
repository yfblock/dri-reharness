#include <linux/io.h>

#define VALUE_REG 0x20

void path_state(void __iomem *base, unsigned int select)
{
	u32 value = 1;

	if (select)
		value = 2;
	writel(value, base + VALUE_REG);
}
