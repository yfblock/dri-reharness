# Generated driver examples

These files are deterministic outputs from the current reharness pipeline,
using `benchmarks/drivers/baseline/edu.c` as input.

Regenerate with:

```bash
./run.sh gen benchmarks/drivers/baseline/edu.c harness examples/edu/edu_harness.c
./run.sh gen benchmarks/drivers/baseline/edu.c baremetal examples/edu/edu_baremetal.c
./run.sh gen benchmarks/drivers/baseline/edu.c linux examples/edu/edu_linux.c
```

| File | Backend | Description |
| --- | --- | --- |
| `edu_harness.c` | Userspace harness | Fake MMIO + trace logging, compiles with `cc -Wall` |
| `edu_baremetal.c` | Bare-metal | Portable C, compiles with `cc -ffreestanding -c` |
| `edu_linux.c` | Linux kernel module | Platform/PCI driver, builds via Kbuild |
