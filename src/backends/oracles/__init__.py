"""Generator-side oracle plugins (family-coupled) + the plugin registry.

Adding a new backend or device family means working in ONE area:

* family oracle  -> drop ``src/backends/oracles/<kind>_oracle.py``
                    and register the kind in ``FAMILY_ORACLES`` below;
* backend oracle -> drop it under ``src/backends/<backend>/oracles/``
                    and list the module in ``BACKEND_ORACLES``.

``backends.pipeline`` resolves plugins only through this registry, so new
platforms never require touching the orchestration graph.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

# kind -> plugin module (dotted path under src/backends)
FAMILY_ORACLES: dict[str, str] = {
    "sdhci": "backends.oracles.sdhci_accessor_oracle",
    "virtio": "backends.oracles.virtio_state_oracle",
    "w1c": "backends.oracles.w1c_drain_oracle",
    "transaction": "backends.oracles.transaction_ir_oracle",
}

# backend -> plugin modules (always run when that backend is generated)
BACKEND_ORACLES: dict[str, list[str]] = {
    "linux": [
        "backends.linux.oracles.linux_registration_ast_oracle",
        "backends.linux.oracles.gpio_mmio_source_oracle",
    ],
}


def load(dotted: str) -> Any:
    """Import one plugin module by dotted path (lazy, Python-cached)."""
    return importlib.import_module(dotted)


def family_kinds() -> list[str]:
    return sorted(FAMILY_ORACLES)


def backend_modules(backend: str) -> list[Any]:
    return [load(name) for name in BACKEND_ORACLES.get(backend, ())]


def verify(kind: str, function: str, *args: Any, **kwargs: Any) -> Any:
    """Resolve and call a family plugin entry point by kind + function."""
    module = load(FAMILY_ORACLES[kind])
    return getattr(module, function)(*args, **kwargs)
