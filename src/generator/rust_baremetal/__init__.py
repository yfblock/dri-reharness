"""Rust bare-metal backend.

Generates portable Rust register-programming code: device struct with
``base: usize``, read/write wrappers using ``core::ptr::read_volatile``,
per-function RIS bodies. No OS framework glue. Compiles with ``rustc``
on ``no_std`` targets.
"""
from __future__ import annotations
from generator.common import make_freestanding_bind


def generate(formal, device_spec, bind) -> str:
    """Generate rust_baremetal code via LLM."""
    from generator.llm_bridge import generate_via_llm
    return generate_via_llm(formal, device_spec, bind,
                             backend="rust_baremetal")

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with rust_baremetal-specific types, primitives, state."""
    make_freestanding_bind(bind, priv, base_expr, prefix="mmio")

NAME = "rust_baremetal"
LANG = "Rust"
GEN_KWARGS = []
