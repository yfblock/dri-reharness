#!/usr/bin/env python3
"""Prove Linux callback registration from generated-C AST structure.

This oracle deliberately does not infer runtime reachability from a callback
name, a DeviceSpec field, a lowering receipt, or a function definition alone.
For the supported v1 shapes it requires an exact operation anchor, the
enclosing generated function, a type-correct callback-field binding, the same
framework object at a recognized registration call, and a registered
platform/PCI probe root.  Unsupported object/dataflow shapes remain explicit
and fail closed.

Thin facade: implementation lives in the ``linux_registration_ast`` package
(support/context/ast_collect/routes/runtime_contract/verify).  This file keeps
the historical import path runnable both as a module and as a direct script
(qa/tests/test_linux_registration_ast_oracle.py invokes it by file path).
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


if __package__ in (None, ""):
    # Direct script execution: make the sibling package importable.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from linux_registration_ast import *  # noqa: F401,F403
    from linux_registration_ast import (  # noqa: F401
        _call_policy,
        _collect_ast,
        _compile_context,
        _device_routes,
        _registered_routes,
        _resolve_local_alias,
        _resolve_local_aliases,
        _runtime_identity_contract,
        _signature,
        _stable_chain,
        _write_report,
        linux_kbuild_compile_context,
        main,
        registration_route_fingerprint,
        verify_linux_registration_ast,
    )
else:
    from backends.linux.oracles.linux_registration_ast import *  # noqa: F401,F403
    from backends.linux.oracles.linux_registration_ast import (  # noqa: F401
        ORACLE,
        SCHEMA,
        _call_policy,
        _collect_ast,
        _compile_context,
        _device_routes,
        _registered_routes,
        _resolve_local_alias,
        _resolve_local_aliases,
        _runtime_identity_contract,
        _signature,
        _stable_chain,
        _write_report,
        linux_kbuild_compile_context,
        main,
        registration_route_fingerprint,
        verify_linux_registration_ast,
    )


if __name__ == "__main__":
    raise SystemExit(main())
