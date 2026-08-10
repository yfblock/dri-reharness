"""Backend registry for code generators.

Each backend (harness, baremetal, linux, rust_baremetal, ...) registers itself
at import time.  The registry is consulted by:
  - cli.py: to enumerate available backends (--backend choices)
  - spec.py: to dispatch default_bind() to the backend's make_bind()
  - synthesis module: same dispatch

A backend module must expose:
  NAME       - str, the backend identifier (e.g. "harness")
  generate() - (formal, device_spec, bind, **gen_kwargs) -> str
  make_bind() - (device_spec, bind: BindSpec, priv: str, base_expr: str) -> None
  GEN_KWARGS - list[str] of optional kwargs generate() accepts
  LANG       - str, output language for display (e.g. "C", "Rust")

To add a new backend, drop a .py file into src/generator/ that defines these
attributes.  Auto-discovery picks it up on first access.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Dict, List

_REGISTRY: Dict[str, Any] = {}
_DISCOVERY_DONE = False


def register(module) -> None:
    """Register a backend module."""
    name = getattr(module, "NAME", None)
    if not isinstance(name, str) or not name:
        raise ValueError(
            f"{module.__name__}: backend module must define NAME")
    if not hasattr(module, "generate"):
        raise ValueError(
            f"{module.__name__}: backend module must define generate()")
    _REGISTRY[name] = module


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)


def get_backend(name: str):
    """Return the registered module for *name*, auto-discovering if needed."""
    _ensure_discovery()
    mod = _REGISTRY.get(name)
    if mod is None:
        raise KeyError(
            f"Unknown backend '{name}'. Available: {sorted(_REGISTRY)}")
    return mod


def list_backends() -> Dict[str, Any]:
    """Return {name: module} for all registered backends."""
    _ensure_discovery()
    return dict(_REGISTRY)


def backend_names() -> List[str]:
    """Return a sorted list of all registered backend names."""
    _ensure_discovery()
    return sorted(_REGISTRY)


# Internal: modules that are infrastructure, not backends
_INFRA_MODULES = frozenset({"__init__", "registry", "common", "subsystem_runner"})


def _ensure_discovery() -> None:
    """Import every module in the generator package once."""
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE:
        return
    _DISCOVERY_DONE = True
    try:
        import generator as _pkg
    except ImportError:
        return
    for _finder, modname, _ispkg in pkgutil.iter_modules(_pkg.__path__):
        if modname in _INFRA_MODULES:
            continue
        try:
            mod = importlib.import_module(f"generator.{modname}")
            if hasattr(mod, "NAME") and hasattr(mod, "generate"):
                if mod.NAME not in _REGISTRY:
                    _REGISTRY[mod.NAME] = mod
        except Exception:
            pass  # skip modules that fail to import


def reset_discovery() -> None:
    """Force re-discovery on next access (testing convenience)."""
    global _DISCOVERY_DONE
    _DISCOVERY_DONE = False
    _REGISTRY.clear()
