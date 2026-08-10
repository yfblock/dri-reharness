"""Bare-metal C backend (plan Milestone 6, Backend B).

Generates portable freestanding register-programming functions: device struct
with `uintptr_t base`, read32/write32 wrappers, per-function RIS bodies. No
Linux framework glue. Compiles with `cc -ffreestanding`.
"""
from __future__ import annotations
from extractor.formal import walk_leaf_ops
from extractor.spec import TypeMap, PrimitiveMap, StateMap, ExportMap



def generate(formal: dict, device_spec, bind) -> str:
    """Generate baremetal code via LLM."""
    from generator.llm_bridge import generate_via_llm
    return generate_via_llm(formal, device_spec, bind,
                             backend="baremetal")

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with baremetal-specific types, primitives, state, exports."""
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "uintptr_t"),
        TypeMap("LogicalIRQ", "unsigned int"),
        TypeMap("UInt", "uint32_t"),
        TypeMap("UIntPtr", "uint32_t *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", "mmio_read32"),
        PrimitiveMap("MmioWrite", "B4", "mmio_write32"),
        PrimitiveMap("MmioRead", "B2", "mmio_read16"),
        PrimitiveMap("MmioWrite", "B2", "mmio_write16"),
        PrimitiveMap("MmioRead", "B1", "mmio_read8"),
        PrimitiveMap("MmioWrite", "B1", "mmio_write8"),
        PrimitiveMap("MmioWriteW1C", "B4", "mmio_write_w1c32"),
        PrimitiveMap("MmioWriteW1C", "B2", "mmio_write_w1c16"),
        PrimitiveMap("MmioWriteW1C", "B1", "mmio_write_w1c8"),
        PrimitiveMap("MmioReadBE", "B2", "mmio_read16be"),
        PrimitiveMap("MmioWriteBE", "B2", "mmio_write16be"),
        PrimitiveMap("MmioReadBE", "B4", "mmio_read32be"),
        PrimitiveMap("MmioWriteBE", "B4", "mmio_write32be"),
    ]
    bind.state = [StateMap("dev.base", "dev->base")]
    for fn in device_spec.functions:
        bind.exports.append(ExportMap(fn.role, f"{device_spec.name}_{fn.role}"))

# Backend registration
NAME = "baremetal"
LANG = "C"
GEN_KWARGS = []
