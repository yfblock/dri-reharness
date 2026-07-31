void opaque_access(volatile unsigned int *reg)
{
	unsigned int value = *reg;

	*reg = value | 1;
	__asm__ volatile("" ::: "memory");
}
