"""Freestanding-backend BindSpec population (harness/baremetal/rust)."""
from __future__ import annotations

from extractor.spec import TypeMap, PrimitiveMap, StateMap, ExportMap


_C_KEYWORDS = {
    "auto", "char", "const", "double", "enum", "extern", "float", "for",
    "int", "long", "register", "restrict", "short", "signed", "static",
    "struct", "typedef", "union", "unsigned", "void", "volatile", "while",
}


def make_freestanding_bind(bind, priv: str, base_expr: str, *,
                           prefix: str = "mmio", exports=None) -> None:
    """Populate bind for freestanding C backends (harness, baremetal, rust_baremetal).

    These backends share identical type mappings and state mappings.
    Only the primitive function name prefix differs (e.g. harness_read32
   vs mmio_read32).
   """
    p = prefix
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "uintptr_t"),
        TypeMap("LogicalIRQ", "unsigned int"),
        TypeMap("UInt", "uint32_t"),
        TypeMap("UIntPtr", "uint32_t *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", f"{p}_read32"),
        PrimitiveMap("MmioWrite", "B4", f"{p}_write32"),
        PrimitiveMap("MmioRead", "B2", f"{p}_read16"),
        PrimitiveMap("MmioWrite", "B2", f"{p}_write16"),
        PrimitiveMap("MmioRead", "B1", f"{p}_read8"),
        PrimitiveMap("MmioWrite", "B1", f"{p}_write8"),
        PrimitiveMap("MmioWriteW1C", "B4", f"{p}_write_w1c32"),
        PrimitiveMap("MmioWriteW1C", "B2", f"{p}_write_w1c16"),
        PrimitiveMap("MmioWriteW1C", "B1", f"{p}_write_w1c8"),
        PrimitiveMap("MmioReadBE", "B2", f"{p}_read16be"),
        PrimitiveMap("MmioWriteBE", "B2", f"{p}_write16be"),
        PrimitiveMap("MmioReadBE", "B4", f"{p}_read32be"),
        PrimitiveMap("MmioWriteBE", "B4", f"{p}_write32be"),
   ]
    bind.state = [StateMap("dev.base", "dev->base")]
    if exports:
        for fn in exports:
            bind.exports.append(ExportMap(fn.role, f"{fn.name}"))
