#include <linux/io.h>

#define WRAP_STATUS 0x10

static u32 wrapper_read(void __iomem *base, unsigned int offset)
{
	return readl(base + offset);
}

void wrapper_caller(void __iomem *base)
{
	u32 value = wrapper_read(base, WRAP_STATUS);

	(void)value;
}
