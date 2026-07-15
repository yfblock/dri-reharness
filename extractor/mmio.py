"""MMIO primitive recognition — mirrors driver-harness src/extractor/mmio.rs.

Identifies Linux MMIO read/write/delay calls and infers access width from
the function-name suffix (readl→4, readw→2, readb→1, readq→8).
"""
from __future__ import annotations

MMIO_READ_FNS = {
    "readb", "readw", "readl", "readq",
    "ioread8", "ioread16", "ioread32", "ioread64",
    "__raw_readb", "__raw_readw", "__raw_readl", "__raw_readq",
    "__readb", "__readw", "__readl", "__readq",
    "inb", "inw", "inl",
    "readb_relaxed", "readw_relaxed", "readl_relaxed", "readq_relaxed",
}

MMIO_WRITE_FNS = {
    "writeb", "writew", "writel", "writeq",
    "iowrite8", "iowrite16", "iowrite32", "iowrite64",
    "__raw_writeb", "__raw_writew", "__raw_writel", "__raw_writeq",
    "__writeb", "__writew", "__writel", "__writeq",
    "outb", "outw", "outl",
    "writeb_relaxed", "writew_relaxed", "writel_relaxed", "writeq_relaxed",
}

DELAY_FNS = {"mdelay", "udelay", "ndelay", "msleep", "ssleep"}

# Functions that return an MMIO base pointer (taint sources).
IOREMAP_FNS = {
    "ioremap", "ioremap_wc", "ioremap_uc", "ioremap_cache", "ioremap_nocache",
    "devm_ioremap", "devm_ioremap_resource", "devm_ioremap_resource_byname",
    "devm_platform_ioremap_resource", "devm_platform_ioremap_resource_byname",
    "of_iomap", "pci_iomap", "pcim_iomap", "devm_pci_iomap",
    "pci_ioremap_bar", "pci_ioremap_wc_bar",
}

FRAMEWORK_FNS = {
    # Memory allocation
    "kmalloc", "kzalloc", "kcalloc", "kfree", "krealloc",
    "devm_kmalloc", "devm_kzalloc", "devm_kfree",
    "dma_alloc_coherent", "dma_free_coherent", "dma_alloc_attrs",
    "dma_map_single", "dma_unmap_single", "dma_map_sg", "dma_unmap_sg",
    # Locking
    "spin_lock", "spin_unlock", "spin_lock_irqsave", "spin_unlock_irqrestore",
    "spin_lock_irq", "spin_unlock_irq",
    "mutex_lock", "mutex_unlock", "mutex_trylock",
    "down_read", "up_read", "down_write", "up_write",
    # Interrupts
    "request_irq", "free_irq", "request_threaded_irq",
    "enable_irq", "disable_irq", "disable_irq_nosync",
    "tasklet_schedule", "tasklet_init",
    # Framework registration
    "platform_driver_register", "platform_driver_unregister",
    "register_chrdev", "unregister_chrdev",
    "register_netdev", "unregister_netdev",
    "alloc_chrdev_region", "unregister_chrdev_region",
    # Device / resource
    "platform_get_resource", "platform_get_irq",
    "devm_request_irq", "devm_request_mem_region",
    "of_property_read_u32", "of_property_read_string",
    "device_property_read_u32", "device_property_read_string",
    # Printing
    "pr_info", "pr_err", "pr_warn", "pr_debug", "pr_notice",
    "dev_info", "dev_err", "dev_warn", "dev_dbg",
    "printk", "dump_stack",
    # Misc
    "module_init", "module_exit",
    "kthread_create", "kthread_run", "kthread_stop",
    "wait_for_completion", "complete",
    "schedule", "wait_event",
    "clk_prepare", "clk_enable", "clk_unprepare", "clk_disable",
    "clk_prepare_enable", "clk_disable_unprepare",
    "pm_runtime_get_sync", "pm_runtime_put_sync",
}


def infer_width(name: str) -> int:
    if name.endswith("64") or name.endswith("q"):
        return 8
    if name.endswith("32") or name.endswith("l"):
        return 4
    if name.endswith("16") or name.endswith("w"):
        return 2
    if name.endswith("8") or name.endswith("b"):
        return 1
    return 4


def is_mmio_read(name: str) -> bool:
    return name in MMIO_READ_FNS


def is_mmio_write(name: str) -> bool:
    return name in MMIO_WRITE_FNS


def is_delay(name: str) -> bool:
    return name in DELAY_FNS


def is_ioremap(name: str) -> bool:
    return name in IOREMAP_FNS


def is_framework(name: str) -> bool:
    return name in FRAMEWORK_FNS
