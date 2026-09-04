"""Manifest runtime-identity comparison against the registered root object."""
from __future__ import annotations

from typing import Any, Mapping

from linux_registration_contracts import resolve_linux_registration_policy


def _runtime_identity_contract(
        ast: dict, routes: list[dict], runtime_identity: Mapping[str, Any] | None
        ) -> tuple[list[str], list[dict[str, Any]]]:
    """Compare manifest runtime identity with the registered root object."""
    if not isinstance(runtime_identity, Mapping):
        return [], []
    declared = runtime_identity.get("registration")
    if isinstance(declared, Mapping):
        root_table = declared.get("root_table")
        identity_field = declared.get("identity_field", "driver_name")
        device_id_tables = declared.get("device_id_tables", [])
        if (not isinstance(root_table, str)
                or not isinstance(identity_field, str)
                or not isinstance(device_id_tables, list)):
            return [], []
    else:
        # Compatibility for schema-2 manifests written before registration
        # contracts became profile-owned data.
        bus = runtime_identity.get("bus")
        legacy_contracts = resolve_linux_registration_policy().get(
            "legacy_runtime_contracts", {})
        legacy = (legacy_contracts.get(bus)
                  if isinstance(bus, str)
                  and isinstance(legacy_contracts, Mapping) else None)
        if not isinstance(legacy, Mapping):
            return [], []
        root_table = legacy.get("root_table")
        identity_field = legacy.get("identity_field", "driver_name")
        device_id_tables = legacy.get("device_id_tables", [])
    if identity_field == "none":
        return [], []
    expected_name = runtime_identity.get(identity_field)
    identity_error = ("registrar_name" if identity_field == "registrar"
                      else "driver_name")
    if not isinstance(expected_name, str) or not expected_name:
        return [], []

    root_usrs = {
        (route.get("registration") or {}).get("object", {}).get("root_usr")
        for route in routes
        if route.get("callback") == f"{root_table}.probe"
        and (route.get("registration") or {}).get("kind") == "driver_root"
    }
    observed = [
        dict(item) for item in ast.get("identity_bindings", [])
        if item.get("table") == root_table
        and item.get("owner", {}).get("root_usr") in root_usrs
    ]
    errors: list[str] = []
    names = sorted({item.get("value") for item in observed
                    if isinstance(item.get("value"), str)})
    if not names:
        errors.append(f"{identity_error}_missing")
    elif expected_name not in names:
        errors.append(f"{identity_error}_mismatch")
    for id_table in device_id_tables:
        if not isinstance(id_table, str) or not id_table:
            continue
        id_names = sorted({item.get("value") for item in ast.get(
            "identity_bindings", [])
            if item.get("table") == id_table
            and isinstance(item.get("value"), str)})
        if not id_names:
            errors.append(f"{id_table.removesuffix('_device_id')}_id_name_missing")
        elif expected_name not in id_names:
            errors.append(f"{id_table.removesuffix('_device_id')}_id_name_mismatch")
    return errors, observed
