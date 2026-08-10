You are an expert Linux kernel module developer. Generate a complete, compilable Linux kernel module that reproduces the exact MMIO register access pattern described in the evidence JSON below.

## CRITICAL: Module-to-Function Mapping

Every entry in evidence.modules MUST be generated as a separate C function. Do NOT skip, merge, or omit any module. The function name must match the module name exactly. Each function takes "struct driver_priv *priv" and uses "void __iomem *base = priv->base;" to access MMIO.

For each module's ops array:
- "kind":"write" -> writel(value, base + REGISTER_NAME)
- "kind":"read" -> variable = readl(base + REGISTER_NAME)
- "kind":"cond" -> if (guard) { ...then... } else { ...else... }
- "kind":"loop" -> while/for loop with body
- "kind":"return" -> return value

Where the address shows "base + REGISTER_NAME", use the register name as-is (it is a #define constant).
- "kind":"tx_write" -> regmap write. Use: regmap_write(regmap, SELECTOR, payload). Declare a static struct regmap *regmap at the top of the function if any tx_* ops appear. The target field is the regmap handle name.
- "kind":"tx_update" -> regmap update. Use: regmap_update_bits(regmap, SELECTOR, mask, value).
- "kind":"tx_read" -> regmap read. Use: regmap_read(regmap, SELECTOR, &var).
For regmap operations, add #include <linux/regmap.h> and declare a dummy static struct regmap pointer for each unique target name. Since this is a harness, use NULL or a placeholder for the regmap pointer.

## Bus Type Detection

Check evidence.bus_type:
- If "pci": use pci_driver, pci_enable_device_mem, pci_request_regions, pci_ioremap_bar, pci_set_drvdata, module_pci_driver. Include <linux/pci.h>.
- If "platform" (default): use platform_driver, devm_platform_ioremap_resource, module_platform_driver. Include <linux/platform_device.h>.

## Required Components

1. Includes: <linux/module.h>, <linux/io.h>, <linux/fs.h>, <linux/uaccess.h>, <linux/miscdevice.h>, <linux/slab.h>, <linux/err.h>, <linux/of.h>, plus bus-specific headers.

2. Driver private struct containing:
   - void __iomem *base (the MMIO base address)
   - struct miscdevice misc (for user-space access)
   - struct device *dev

3. MMIO trace instrumentation (REQUIRED): Add after includes, before any function:
static void __iomem *__rh_mmio_base;
#define RH_SET_BASE(b) do { __rh_mmio_base = (b); pr_info("[rhbase] %px
", (void __iomem *)(b)); } while (0)
#define RH_TRACE_FN(name) pr_info("[rhfn] %s
", (name))
#define rh_off(p) ((unsigned long)((const void __iomem *)(p) - __rh_mmio_base))
#undef readl
#define readl(p) ({ u32 __v = __raw_readl(p); pr_info("[rh] R 0x%lx 0x%x
", rh_off(p), __v); __v; })
#undef writel
#define writel(v,p) ({ pr_info("[rh] W 0x%lx 0x%x
", rh_off(p), (u32)(v)); __raw_writel((v),(p)); })

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
   - Call EVERY module function in order, each preceded by RH_TRACE_FN("function_name")
   - misc_register with KBUILD_MODNAME
   - Proper error handling

6. Remove function (return void for platform_driver): call the remove/suspend module functions if they exist, then misc_deregister.

7. PCI identity: If evidence.pci_identity exists with vendor/device, create pci_device_id table.

8. Module boilerplate: MODULE_LICENSE("GPL"), MODULE_DESCRIPTION, module_pci_driver or module_platform_driver.

## Constants
If evidence.constants exist, define them as macros. These include register offset macros (e.g. DW_SPI_SSIENR = 0x08).

## Rules
- Use readl/writel for MMIO access (B4 width), readw/writew for B2 width.
- EVERY module in evidence.modules must become a separate function. No exceptions.
- The probe function must call ALL module functions in order.
- Use register macro names directly (e.g. writel(0, base + DW_SPI_SSIENR)).
- Use devm_ managed resources where possible.
- Include error handling.
- Do NOT invent or skip register accesses. Every op in every module must appear.
- Transaction (tx_*) operations represent regmap/I2C bus accesses, not MMIO. Generate them as regmap_* calls with placeholder pointers. Include #include <linux/regmap.h> when any tx_* op is present.

Driver name: __DRIVER_NAME__

Evidence JSON:
```json
__EVIDENCE__
```

Generate the complete C code in a single ```c code block.
