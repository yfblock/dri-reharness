"""Bare-metal C backend (plan Milestone 6, Backend B).

Generates portable freestanding register-programming functions: device struct
with `uintptr_t base`, read32/write32 wrappers, per-function RIS bodies. No
Linux framework glue. Compiles with `cc -ffreestanding`.
"""
from __future__ import annotations
from backends.common import make_freestanding_bind
from extractor.spec import ExportMap


def generate(formal: dict, device_spec, bind, **kwargs) -> str:
    """Generate baremetal code via LLM."""
    from backends.llm_bridge import generate_via_llm
    return generate_via_llm(formal, device_spec, bind,
                             backend="baremetal", **kwargs)

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with baremetal-specific types, primitives, state, exports."""
    make_freestanding_bind(bind, priv, base_expr, prefix="mmio")
    for fn in device_spec.functions:
        bind.exports.append(ExportMap(fn.role, f"{device_spec.name}_{fn.role}"))

NAME = "baremetal"
LANG = "C"
GEN_KWARGS = []
