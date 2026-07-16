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

# Driver-private wrappers whose argument layout is semantically equivalent to
# Linux MMIO primitives. The tuple is (device/state arg, offset arg, base
# field); writes additionally identify the value arg. Keeping this explicit
# avoids treating arbitrary functions named read/write as MMIO.
PRIVATE_MMIO_READ_LAYOUTS = {
    "dwc2_readl": (0, 1, "regs"),
}

PRIVATE_MMIO_WRITE_LAYOUTS = {
    "dwc2_writel": (0, 1, 2, "regs"),
}

# Public subsystem accessors with stable, type-defined register contracts.
# Keep these separate from driver-private layouts: this is Linux library
# semantics, not a source-name exception.
SUBSYSTEM_MMIO_READ_LAYOUTS = {
    "sdhci_readb": (0, 1, "ioaddr"),
    "sdhci_readw": (0, 1, "ioaddr"),
    "sdhci_readl": (0, 1, "ioaddr"),
    "sdhci_be32bs_readb": (0, 1, "ioaddr"),
    "sdhci_be32bs_readw": (0, 1, "ioaddr"),
    "sdhci_be32bs_readl": (0, 1, "ioaddr"),
}

SUBSYSTEM_MMIO_WRITE_LAYOUTS = {
    "sdhci_writeb": (0, 1, 2, "ioaddr"),
    "sdhci_writew": (0, 1, 2, "ioaddr"),
    "sdhci_writel": (0, 1, 2, "ioaddr"),
    "sdhci_be32bs_writeb": (0, 1, 2, "ioaddr"),
    "sdhci_be32bs_writew": (0, 1, 2, "ioaddr"),
    "sdhci_be32bs_writel": (0, 1, 2, "ioaddr"),
}

DIRECT_ADDRESS_READ_LAYOUTS = {"gpio_generic_read_reg": 1}
DIRECT_ADDRESS_WRITE_LAYOUTS = {"gpio_generic_write_reg": (2, 1)}

VIRTIO_CONFIG_READ_FNS = {"virtio_cread_le", "virtio_cread_bytes"}
VIRTIO_CONFIG_WRITE_FNS = {"virtio_cwrite_le"}
VIRTQUEUE_READ_FNS = {
    "virtqueue_get_buf": 4,
    "virtqueue_detach_unused_buf": 4,
    "virtqueue_get_vring_size": 12,
}
VIRTQUEUE_WRITE_FNS = {
    "virtqueue_add_inbuf_cache_clean": (3, 0),
    "virtqueue_add_outbuf": (3, 0),
    "virtqueue_kick": (None, 8),
}

SUBSYSTEM_LIBRARY_SUMMARY_FNS = {"gpio_generic_chip_init"}

REGMAP_READ_FNS = {"regmap_read": (0, 1, 2)}
REGMAP_WRITE_FNS = {"regmap_write": (0, 1, 2)}
REGMAP_RMW_FNS = {"regmap_update_bits": (0, 1, 2, 3)}

UNSUPPORTED_REGISTER_FNS = {
    "regmap_bulk_read", "regmap_bulk_write", "regmap_raw_read",
    "regmap_raw_write", "memcpy_fromio", "memcpy_toio", "memset_io",
    "ioread32_rep", "iowrite32_rep", "pci_read_config_dword",
    "pci_write_config_dword",
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


def effective_access_name(name: str, callee_text: str = "") -> str:
    """Recover source-level macro accessors from libclang-expanded calls."""
    compact = (callee_text or "").lstrip()
    if name == "set" and compact.startswith("virtio_cwrite_le("):
        return "virtio_cwrite_le"
    if name == "__virtio_cread_many" and compact.startswith("virtio_cread_le("):
        return "virtio_cread_le"
    return name


def _split_call_args(text: str) -> list[str]:
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        return []
    body = text[start + 1:end]
    out: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        if char == "," and depth == 0:
            out.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    out.append("".join(current).strip())
    return out


def access_args(name: str, call) -> list[str]:
    if name in {"virtio_cread_le", "virtio_cwrite_le"}:
        parsed = _split_call_args(call.callee_text)
        if parsed:
            return parsed
    return list(call.arg_text)


def infer_call_width(name: str, call=None) -> int:
    if name == "virtio_cread_bytes":
        return 1
    if name in {"virtio_cread_le", "virtio_cwrite_le"} and call is not None:
        temp_name = ("virtio_cread_v" if name == "virtio_cread_le"
                     else "virtio_cwrite_v")
        for cursor in call.cursor.walk_preorder():
            if cursor.spelling != temp_name or cursor.type is None:
                continue
            size = cursor.type.get_size()
            if size in {1, 2, 4, 8}:
                return int(size)
    if name == "gpio_generic_read_reg" and call is not None:
        size = call.cursor.type.get_size() if call.cursor.type is not None else -1
        if size in {1, 2, 4, 8}:
            return int(size)
    return infer_width(name)


def is_mmio_read(name: str) -> bool:
    return (name in MMIO_READ_FNS or name in PRIVATE_MMIO_READ_LAYOUTS
            or name in SUBSYSTEM_MMIO_READ_LAYOUTS
            or name in DIRECT_ADDRESS_READ_LAYOUTS
            or name in VIRTIO_CONFIG_READ_FNS
            or name in VIRTQUEUE_READ_FNS
            or name in REGMAP_READ_FNS)


def is_mmio_write(name: str) -> bool:
    return (name in MMIO_WRITE_FNS or name in PRIVATE_MMIO_WRITE_LAYOUTS
            or name in SUBSYSTEM_MMIO_WRITE_LAYOUTS
            or name in DIRECT_ADDRESS_WRITE_LAYOUTS
            or name in VIRTIO_CONFIG_WRITE_FNS
            or name in VIRTQUEUE_WRITE_FNS
            or name in REGMAP_WRITE_FNS)


def is_mmio_rmw(name: str) -> bool:
    return name in REGMAP_RMW_FNS


def is_unsupported_register_access(name: str) -> bool:
    return name in UNSUPPORTED_REGISTER_FNS


def access_domain(name: str) -> str:
    if name in REGMAP_READ_FNS or name in REGMAP_WRITE_FNS or name in REGMAP_RMW_FNS:
        return "regmap"
    if name in VIRTIO_CONFIG_READ_FNS or name in VIRTIO_CONFIG_WRITE_FNS:
        return "virtio_config"
    if name in VIRTQUEUE_READ_FNS or name in VIRTQUEUE_WRITE_FNS:
        return "virtqueue"
    return "mmio"


def summary_kind(name: str) -> str | None:
    if (name in SUBSYSTEM_MMIO_READ_LAYOUTS
            or name in SUBSYSTEM_MMIO_WRITE_LAYOUTS):
        return "sdhci_accessor"
    if name in DIRECT_ADDRESS_READ_LAYOUTS or name in DIRECT_ADDRESS_WRITE_LAYOUTS:
        return "gpio_generic_accessor"
    if name in VIRTIO_CONFIG_READ_FNS or name in VIRTIO_CONFIG_WRITE_FNS:
        return "virtio_config"
    if name in VIRTQUEUE_READ_FNS or name in VIRTQUEUE_WRITE_FNS:
        return "virtqueue"
    if name in SUBSYSTEM_LIBRARY_SUMMARY_FNS:
        return "gpio_generic_chip"
    return None


def is_library_summary_call(name: str) -> bool:
    return name in SUBSYSTEM_LIBRARY_SUMMARY_FNS


def read_addr_expr(name: str, args: list[str]) -> str:
    if name == "virtio_cread_le" and len(args) >= 3:
        return f"{args[0]} + offsetof({args[1]}, {args[2]})"
    if name == "virtio_cread_bytes" and len(args) >= 2:
        return f"{args[0]} + {args[1]}"
    if name in VIRTQUEUE_READ_FNS and args:
        return f"{args[0]} + {VIRTQUEUE_READ_FNS[name]}"
    direct_arg = DIRECT_ADDRESS_READ_LAYOUTS.get(name)
    if direct_arg is not None:
        return args[direct_arg] if direct_arg < len(args) else ""
    regmap = REGMAP_READ_FNS.get(name)
    if regmap is not None:
        state_arg, offset_arg, _result_arg = regmap
        if max(regmap) >= len(args):
            return ""
        return f"{args[state_arg]} + {args[offset_arg]}"
    layout = (PRIVATE_MMIO_READ_LAYOUTS.get(name)
              or SUBSYSTEM_MMIO_READ_LAYOUTS.get(name))
    if layout is None:
        return args[0] if args else ""
    state_arg, offset_arg, base_field = layout
    if max(state_arg, offset_arg) >= len(args):
        return ""
    return f"{args[state_arg]}->{base_field} + {args[offset_arg]}"


def write_value_addr(name: str, args: list[str]) -> tuple[str, str]:
    if name == "virtio_cwrite_le" and len(args) >= 4:
        value = args[3].strip().lstrip("&*").strip()
        return value, f"{args[0]} + offsetof({args[1]}, {args[2]})"
    queue = VIRTQUEUE_WRITE_FNS.get(name)
    if queue is not None and args:
        value_arg, offset = queue
        value = "1" if value_arg is None else (
            args[value_arg] if value_arg < len(args) else "")
        return value, f"{args[0]} + {offset}"
    direct = DIRECT_ADDRESS_WRITE_LAYOUTS.get(name)
    if direct is not None:
        value_arg, address_arg = direct
        if max(value_arg, address_arg) >= len(args):
            return "", ""
        return args[value_arg], args[address_arg]
    regmap = REGMAP_WRITE_FNS.get(name)
    if regmap is not None:
        state_arg, offset_arg, value_arg = regmap
        if max(regmap) >= len(args):
            return "", ""
        return args[value_arg], f"{args[state_arg]} + {args[offset_arg]}"
    layout = (PRIVATE_MMIO_WRITE_LAYOUTS.get(name)
              or SUBSYSTEM_MMIO_WRITE_LAYOUTS.get(name))
    if layout is None:
        if len(args) >= 2:
            return args[0], args[1]
        return (args[0] if args else ""), ""
    state_arg, value_arg, offset_arg, base_field = layout
    if max(state_arg, value_arg, offset_arg) >= len(args):
        return "", ""
    addr = f"{args[state_arg]}->{base_field} + {args[offset_arg]}"
    return args[value_arg], addr


def read_result_var(name: str, args: list[str], lhs: str | None) -> str | None:
    if name == "virtio_cread_le" and len(args) >= 4:
        return args[3].strip().lstrip("&*").strip()
    if name == "virtio_cread_bytes" and len(args) >= 3:
        return args[2].strip().lstrip("&*").strip()
    regmap = REGMAP_READ_FNS.get(name)
    if regmap is None:
        return lhs
    result_arg = regmap[2]
    if result_arg >= len(args):
        return lhs
    return args[result_arg].strip().lstrip("&*").strip()


def rmw_parts(name: str, args: list[str]) -> tuple[str, str, str] | None:
    layout = REGMAP_RMW_FNS.get(name)
    if layout is None or max(layout) >= len(args):
        return None
    state_arg, offset_arg, mask_arg, value_arg = layout
    address = f"{args[state_arg]} + {args[offset_arg]}"
    return address, args[mask_arg], args[value_arg]


def is_delay(name: str) -> bool:
    return name in DELAY_FNS


def is_ioremap(name: str) -> bool:
    return name in IOREMAP_FNS


def is_framework(name: str) -> bool:
    return name in FRAMEWORK_FNS
