#include <linux/io.h>

#define RETRY_REG 0x18

void goto_backward(void __iomem *base, unsigned int again)
{
err_retry:
	writel(1, base + RETRY_REG);
	if (again)
		goto err_retry;
}
