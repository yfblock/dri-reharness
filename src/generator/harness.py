"""Userspace harness backend (plan Milestone 6, Backend A).

Generates a self-contained C harness with a fake MMIO region and trace logging,
so RIS behavior can be executed and compared without kernel deps. Compiles
with plain `cc`.
"""
from __future__ import annotations
from extractor.spec import TypeMap, PrimitiveMap, StateMap




def generate(formal: dict, device_spec, bind) -> str:
    """Generate harness code via LLM."""
    from generator.llm_bridge import generate_via_llm
    return generate_via_llm(formal, device_spec, bind,
                             backend="harness")

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with harness-specific types, primitives, and state."""
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "uintptr_t"),
        TypeMap("LogicalIRQ", "unsigned int"),
        TypeMap("UInt", "uint32_t"),
        TypeMap("UIntPtr", "uint32_t *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", "harness_read32"),
        PrimitiveMap("MmioWrite", "B4", "harness_write32"),
        PrimitiveMap("MmioRead", "B2", "harness_read16"),
        PrimitiveMap("MmioWrite", "B2", "harness_write16"),
        PrimitiveMap("MmioRead", "B1", "harness_read8"),
        PrimitiveMap("MmioWrite", "B1", "harness_write8"),
        PrimitiveMap("MmioWriteW1C", "B4", "harness_write_w1c32"),
        PrimitiveMap("MmioWriteW1C", "B2", "harness_write_w1c16"),
        PrimitiveMap("MmioWriteW1C", "B1", "harness_write_w1c8"),
        PrimitiveMap("MmioReadBE", "B2", "harness_read16be"),
        PrimitiveMap("MmioWriteBE", "B2", "harness_write16be"),
        PrimitiveMap("MmioReadBE", "B4", "harness_read32be"),
        PrimitiveMap("MmioWriteBE", "B4", "harness_write32be"),
    ]
    bind.state = [StateMap("dev.base", "dev->base")]

# Backend registration
NAME = "harness"
LANG = "C"
GEN_KWARGS = []
