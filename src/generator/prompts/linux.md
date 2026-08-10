You are an expert Linux kernel module developer. Generate a complete, compilable Linux kernel module that reproduces the exact MMIO register access pattern described in the evidence JSON below.

## Bus Type Detection

Check evidence.bus_type:
- If "pci": use pci_driver, pci_enable_device_mem, pci_request_regions, pci_ioremap_bar, pci_set_drvdata, module_pci_driver. Include <linux/pci.h>.
- If "platform" (default): use platform_driver, devm_platform_ioremap_resource, module_platform_driver. Include <linux/platform_device.h>.

## Required Components

1. Includes: <linux/module.h>, <linux/io.h>, <linux/fs.h>, <linux/uaccess.h>, <linux/miscdevice.h>, <linux/slab.h>, <linux/err.h>, plus bus-specific headers.

2. Driver private struct containing:
   - void __iomem *base (the MMIO base address)
   - struct miscdevice misc (for user-space access)
   - struct device *dev

3. MMIO trace instrumentation (REQUIRED): Add after includes, before any function:
static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px\n", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s\n", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p) ({ u32 __v = __raw_readl(p); pr_info("[rh] R 0x%lx 0x%x\n", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x\n", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })

4. file_operations with open, read, write:
   - open: store priv in file->private_data
   - read: use the file position (*ppos) as the MMIO offset. Read 4 bytes: val = readl(base + *ppos); copy_to_user(buf, &val, 4); *ppos += 4; return 4;
   - write: use the file position (*ppos) as the MMIO offset. Write 4 bytes: copy_from_user(&val, buf, 4); writel(val, base + *ppos); *ppos += 4; return 4;
   - Both read and write must check alignment: if (*ppos & 3) or count < 4, return -EINVAL.

5. Probe function:
   - devm_kzalloc for priv struct
   - PCI: pci_enable_device_mem, pci_request_regions, pci_ioremap_bar(pdev, 0)
   - Platform: devm_platform_ioremap_resource(pdev, 0)
   - RH_SET_BASE(base)
   - RH_TRACE_FN(function_name)
   - Execute register accesses from evidence.modules
   - misc_register with KBUILD_MODNAME
   - Proper error handling with goto labels

6. Remove function: misc_deregister, cleanup (iounmap for PCI, release_regions for PCI)

7. PCI identity: If evidence.pci_identity exists with vendor/device, create pci_device_id table.

8. Module boilerplate: MODULE_LICENSE("GPL"), MODULE_DESCRIPTION, module_pci_driver or module_platform_driver.

## Constants
If evidence.constants exist, define them as macros.

## Rules
- Use readl/writel for MMIO access.
- Use devm_ managed resources where possible.
- Include error handling.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete C code in a single ```c code block.
