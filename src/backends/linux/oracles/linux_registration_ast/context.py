"""Kbuild compile context, DeviceSpec routes, and registration call policy."""
from __future__ import annotations

import hashlib
import shlex
from pathlib import Path
from typing import Any, Mapping

from ast_analyzer.compile_context import (
    _sanitize_arguments,
    read_kbuild_command,
)


def linux_kbuild_compile_context(
        source: Path, command_file: Path) -> tuple[list[str], dict]:
    raw = read_kbuild_command(str(command_file))
    if not raw:
        raise ValueError(f"no saved Kbuild command in {command_file}")
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"invalid saved Kbuild command: {exc}") from exc
    args = list(_sanitize_arguments(
        tokens, str(command_file.parent.resolve()), str(source)))
    encoded = "\0".join(args).encode("utf-8")
    return args, {
        "origin": "kbuild-cmd",
        "provenance": str(command_file.resolve()),
        "raw_command_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "arguments_sha256": hashlib.sha256(encoded).hexdigest(),
        "argument_count": len(args),
    }


# Compatibility for the initial C20 tests and any local callers written
# before the exact Kbuild context helper became part of the public interface.
_compile_context = linux_kbuild_compile_context


def _device_routes(device_spec: Any) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for function in device_spec.functions:
        module = function.ris_ref or function.name
        if module in routes:
            raise ValueError(f"ambiguous DeviceSpec route for {module!r}")
        routes[module] = {
            "function": function.name,
            "ris_ref": function.ris_ref,
            "role": function.role,
            "callback": function.callback_table,
        }
    return routes


def _call_policy(call: dict, source: Path,
                 registration_policy: Mapping[str, Any]
                 ) -> tuple[dict | None, list[str]]:
    callee = call["callee"]
    policy = registration_policy["registration_apis"].get(callee)
    errors: list[str] = []
    if policy is None:
        return None, errors
    if call["callee_in_source"]:
        errors.append("registration callee is shadowed in generated source")
    index = policy["arg"]
    if index >= len(call["arguments"]):
        errors.append("registration call has too few arguments")
    else:
        observed = call["argument_types"][index]
        if observed != policy["type"]:
            errors.append(
                f"registration object type mismatch: {observed!r} != "
                f"{policy['type']!r}")
        if call["arguments"][index] is None:
            errors.append("registration object has no exact AST identity")
    if call["control_depth"]:
        errors.append("registration call is under unsupported control flow")
    return policy, errors
