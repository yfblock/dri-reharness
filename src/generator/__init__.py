"""Backend code generators (plan Milestone 6).

Each generator consumes (formal RIS, DeviceSpec, BindSpec) and emits C:
  - harness:   userspace harness with fake MMIO + trace logging
  - baremetal: portable freestanding C
  - linux:     Linux driver skeleton (with TODOs where semantics are incomplete)

Common C-emission helpers live in common.py.
"""
from .common import ops_to_c, expr_to_c  # noqa: F401

from .registry import (  # noqa: F401
    register, unregister, get_backend, list_backends, backend_names,
)
