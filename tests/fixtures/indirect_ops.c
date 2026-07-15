#include <linux/io.h>

#define INDIRECT_REG 0x18

struct indirect_ops {
	void (*emit)(void __iomem *base, u32 value);
};

static void indirect_emit(void __iomem *base, u32 value)
{
	writel(value, base + INDIRECT_REG);
}

static const struct indirect_ops local_ops = {
	.emit = indirect_emit,
};

void indirect_caller(void __iomem *base)
{
	local_ops.emit(base, 7);
}
