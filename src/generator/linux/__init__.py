from __future__ import annotations
from extractor.spec import (TypeMap, PrimitiveMap, StateMap, CallbackMap,
                            PUBLIC_CALLBACK_TYPES, _field_for_role)

NAME = "linux"
LANG = "C"
GEN_KWARGS = ["facts", "pci_identity"]


def generate(formal: dict, device_spec, bind, **kwargs) -> str:
    from generator.llm_bridge import generate_via_llm
    pci_identity = kwargs.get("pci_identity")
    facts = kwargs.get("facts")
    extra = {}
    if pci_identity:
        extra["pci_identity"] = pci_identity
        extra["bus_type"] = "pci"
    else:
        extra["bus_type"] = "platform"
    return generate_via_llm(formal, device_spec, bind,
                             backend="linux", facts=facts, **extra)


def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    bind.includes = ["<linux/io.h>", "<linux/platform_device.h>"]
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "void __iomem *"),
        TypeMap("LogicalIRQ", "struct irq_data *"),
        TypeMap("UInt", "u32"),
        TypeMap("UIntPtr", "unsigned long *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", "readl"),
        PrimitiveMap("MmioWrite", "B4", "writel"),
        PrimitiveMap("MmioRead", "B2", "readw"),
        PrimitiveMap("MmioWrite", "B2", "writew"),
        PrimitiveMap("MmioRead", "B1", "readb"),
        PrimitiveMap("MmioWrite", "B1", "writeb"),
        PrimitiveMap("MmioWriteW1C", "B4", "writel"),
        PrimitiveMap("MmioWriteW1C", "B2", "writew"),
        PrimitiveMap("MmioWriteW1C", "B1", "writeb"),
        PrimitiveMap("MmioReadBE", "B2", "ioread16be"),
        PrimitiveMap("MmioWriteBE", "B2", "iowrite16be"),
        PrimitiveMap("MmioReadBE", "B4", "ioread32be"),
        PrimitiveMap("MmioWriteBE", "B4", "iowrite32be"),
    ]
    bind.state = [StateMap("dev.base", base_expr)]
    for fn in device_spec.functions:
        if (fn.is_callback_entry and fn.callback_table
                and fn.role not in {"unknown", "helper"}
                and fn.callback_table.split(".", 1)[0]
                in PUBLIC_CALLBACK_TYPES):
            if "." in fn.callback_table:
                bind.callbacks.append(CallbackMap(fn.callback_table, fn.name))
            else:
                f = _field_for_role(fn.role)
                if f:
                    bind.callbacks.append(CallbackMap(
                        f"{fn.callback_table}.{f}", fn.name))
        elif fn.role == "probe":
            bind.callbacks.append(CallbackMap("platform_driver.probe", fn.name))
        elif fn.role == "remove":
            bind.callbacks.append(CallbackMap("platform_driver.remove", fn.name))
