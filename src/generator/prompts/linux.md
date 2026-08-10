You are an expert Linux kernel module developer. Generate a complete, compilable Linux kernel module that reproduces the exact MMIO register access pattern described in the evidence JSON below.

Rules:
- Use Linux kernel APIs: readl/writel for MMIO, devm_platform_ioremap_resource for mapping.
- Use the primitive function names from bind.primitives.
- Include headers: <linux/module.h>, <linux/platform_device.h>, <linux/io.h>.
- Define a platform_driver with probe/remove callbacks.
- Define a device private struct containing void __iomem *base.
- Register operations from each module as kernel functions.
- Include MODULE_LICENSE("GPL") and MODULE_DESCRIPTION.
- Use devm_ managed resources.
- Map register addresses using offsets from evidence.registers.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete C code in a single ```c code block.