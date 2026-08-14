"""Userspace harness backend (plan Milestone 6, Backend A).

Generates a self-contained C harness with a fake MMIO region and trace logging,
so RIS behavior can be executed and compared without kernel deps. Compiles
with plain `cc`.
"""
from __future__ import annotations
from generator.common import make_freestanding_bind


def generate(formal: dict, device_spec, bind) -> str:
    """Generate harness code via LLM."""
    from generator.llm_bridge import generate_via_llm
    return generate_via_llm(formal, device_spec, bind,
                             backend="harness")

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with harness-specific types, primitives, and state."""
    make_freestanding_bind(bind, priv, base_expr, prefix="harness")

NAME = "harness"
LANG = "C"
GEN_KWARGS = []
