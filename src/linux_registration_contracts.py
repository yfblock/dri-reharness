"""Validated, data-only Linux registration policies.

The AST oracle consumes the policy returned here instead of maintaining a
second list of Linux framework tables and registration APIs.  Built-in
framework knowledge lives in the repository catalog; a profile may add a
new shape through the same strictly validated data contract.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Mapping


class LinuxRegistrationContractError(ValueError):
    """Raised when a registration catalog or extension is unsafe."""


_CATALOG_NAME = "linux-registration-catalog.json"
_PROFILE_ID_RE = re.compile(r"[A-Za-z0-9_.+-]+\Z")
_CATALOG_FIELDS = frozenset({
    "schema", "tables", "registration_apis", "links",
    "builtin_driver_macros", "legacy_runtime_contracts",
    "irq_attach_apis", "direct_irq_apis",
})
_TABLE_FIELDS = frozenset({"id", "record", "role"})
_API_FIELDS = frozenset({"name", "kind", "argument", "type", "table"})
_LINK_FIELDS = frozenset({"owner_table", "field", "target_table"})
_CONTRACT_FIELDS = frozenset({
    "root_table", "identity_field", "device_id_tables",
    "registration_apis", "tables", "links", "irq_attach_apis",
    "direct_irq_apis",
})
_TABLE_ROLES = frozenset({"root", "device_id", "callback", "object"})
_API_KINDS = frozenset({
    "driver_root", "object_root", "gpio_chip", "miscdevice", "clk_hw",
})
_IDENTITY_FIELDS = frozenset({"driver_name", "registrar", "none"})


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinuxRegistrationContractError(
            f"{field} must be a non-empty string")
    if _PROFILE_ID_RE.fullmatch(value) is None:
        raise LinuxRegistrationContractError(f"{field} is unsafe")
    return value


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise LinuxRegistrationContractError(
            f"{field} contains unknown field(s): {', '.join(extra)}")


def _record_type(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, field)


def _parse_tables(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LinuxRegistrationContractError(f"{field} must be a list")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(raw, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw, _TABLE_FIELDS, item_field)
        table_id = _safe_id(raw.get("id"), f"{item_field}.id")
        if table_id in ids:
            raise LinuxRegistrationContractError(
                f"{item_field}.id is duplicate")
        ids.add(table_id)
        role = _safe_id(raw.get("role"), f"{item_field}.role")
        if role not in _TABLE_ROLES:
            raise LinuxRegistrationContractError(
                f"{item_field}.role is unsupported")
        record = _record_type(raw.get("record"), f"{item_field}.record")
        if role != "callback" and record is None:
            raise LinuxRegistrationContractError(
                f"{item_field}.record is required for {role} tables")
        result.append({"id": table_id, "record": record, "role": role})
    return result


def _parse_apis(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LinuxRegistrationContractError(f"{field} must be a list")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(raw, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw, _API_FIELDS, item_field)
        name = _safe_id(raw.get("name"), f"{item_field}.name")
        if name in names:
            raise LinuxRegistrationContractError(
                f"{item_field}.name is duplicate")
        names.add(name)
        kind = _safe_id(raw.get("kind"), f"{item_field}.kind")
        if kind not in _API_KINDS:
            raise LinuxRegistrationContractError(
                f"{item_field}.kind is unsupported")
        argument = raw.get("argument")
        if isinstance(argument, bool) or not isinstance(argument, int) or argument < 0:
            raise LinuxRegistrationContractError(
                f"{item_field}.argument must be a non-negative integer")
        type_name = raw.get("type")
        if not isinstance(type_name, str) or not type_name.strip():
            raise LinuxRegistrationContractError(
                f"{item_field}.type must be a non-empty string")
        table = _safe_id(raw.get("table"), f"{item_field}.table")
        result.append({
            "name": name, "kind": kind, "arg": argument,
            "type": type_name, "table": table,
        })
    return result


def _parse_links(value: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise LinuxRegistrationContractError(f"{field} must be a list")
    result: list[dict[str, str]] = []
    keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(raw, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw, _LINK_FIELDS, item_field)
        owner = _safe_id(raw.get("owner_table"), f"{item_field}.owner_table")
        field_name = _safe_id(raw.get("field"), f"{item_field}.field")
        target = _safe_id(raw.get("target_table"), f"{item_field}.target_table")
        key = (owner, field_name)
        if key in keys:
            raise LinuxRegistrationContractError(
                f"{item_field} duplicates link {owner}.{field_name}")
        keys.add(key)
        result.append({
            "owner_table": owner, "field": field_name,
            "target_table": target,
        })
    return result


def _index(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LinuxRegistrationContractError(
            f"{field} must be a non-negative integer")
    return value


def _parse_irq_attach_apis(value: Any, field: str) -> dict[str, dict[str, int]]:
    if not isinstance(value, list):
        raise LinuxRegistrationContractError(f"{field} must be a list")
    result: dict[str, dict[str, int]] = {}
    for index, raw in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(raw, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw, frozenset({"name", "parent_arg", "child_arg"}), item_field)
        name = _safe_id(raw.get("name"), f"{item_field}.name")
        if name in result:
            raise LinuxRegistrationContractError(
                f"{item_field}.name is duplicate")
        parent_arg = _index(raw.get("parent_arg"),
                            f"{item_field}.parent_arg")
        child_arg = _index(raw.get("child_arg"),
                           f"{item_field}.child_arg")
        if parent_arg == child_arg:
            raise LinuxRegistrationContractError(
                f"{item_field} parent_arg and child_arg must differ")
        result[name] = {"parent_arg": parent_arg, "child_arg": child_arg}
    return result


def _parse_direct_irq_apis(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise LinuxRegistrationContractError(f"{field} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(raw, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw, frozenset({"name", "handler_args", "data_arg"}), item_field)
        name = _safe_id(raw.get("name"), f"{item_field}.name")
        if name in result:
            raise LinuxRegistrationContractError(
                f"{item_field}.name is duplicate")
        raw_handlers = raw.get("handler_args")
        if (not isinstance(raw_handlers, list) or not raw_handlers
                or any(isinstance(item, bool) or not isinstance(item, int)
                       or item < 0 for item in raw_handlers)):
            raise LinuxRegistrationContractError(
                f"{item_field}.handler_args must be a non-empty list of "
                "non-negative integers")
        if len(set(raw_handlers)) != len(raw_handlers):
            raise LinuxRegistrationContractError(
                f"{item_field}.handler_args contains duplicates")
        result[name] = {
            "handler_args": tuple(raw_handlers),
            "data_arg": _index(raw.get("data_arg"),
                                f"{item_field}.data_arg"),
        }
    return result


def _parse_builtin_driver_macros(
        value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise LinuxRegistrationContractError(f"{field} must be an object")
    result: dict[str, str] = {}
    for raw_name, raw_macro in value.items():
        name = _safe_id(raw_name, f"{field} key")
        macro = _safe_id(raw_macro, f"{field}.{name}")
        if name in result:
            raise LinuxRegistrationContractError(
                f"{field} contains duplicate macro identifier: {name}")
        result[name] = macro
    return result


def _parse_legacy_runtime_contracts(
        value: Any, field: str, *, table_ids: set[str],
        device_id_tables: set[str], root_tables: set[str],
        ) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise LinuxRegistrationContractError(f"{field} must be an object")
    result: dict[str, dict[str, Any]] = {}
    allowed = frozenset({"root_table", "identity_field", "device_id_tables"})
    for raw_bus, raw_contract in value.items():
        bus = _safe_id(raw_bus, f"{field} key")
        item_field = f"{field}.{bus}"
        if not isinstance(raw_contract, Mapping):
            raise LinuxRegistrationContractError(f"{item_field} must be an object")
        _unknown(raw_contract, allowed, item_field)
        root_table = _safe_id(raw_contract.get("root_table"),
                              f"{item_field}.root_table")
        if root_table not in table_ids or root_table not in root_tables:
            raise LinuxRegistrationContractError(
                f"{item_field}.root_table is not a root table: {root_table}")
        identity_field = raw_contract.get("identity_field", "driver_name")
        if identity_field not in _IDENTITY_FIELDS:
            raise LinuxRegistrationContractError(
                f"{item_field}.identity_field is unsupported")
        raw_ids = raw_contract.get("device_id_tables", [])
        if not isinstance(raw_ids, list):
            raise LinuxRegistrationContractError(
                f"{item_field}.device_id_tables must be a list")
        ids: list[str] = []
        for index, raw_id in enumerate(raw_ids):
            table = _safe_id(raw_id, f"{item_field}.device_id_tables[{index}]")
            if table not in device_id_tables:
                raise LinuxRegistrationContractError(
                    f"{item_field}.device_id_tables table is unknown: {table}")
            if table in ids:
                raise LinuxRegistrationContractError(
                    f"{item_field}.device_id_tables contains duplicates")
            ids.append(table)
        result[bus] = {
            "root_table": root_table,
            "identity_field": identity_field,
            "device_id_tables": ids,
        }
    return result


def validate_linux_registration_contract(
        value: Any, *, field: str = "registration contract") -> dict[str, Any]:
    """Validate an inline profile/manifest registration extension.

    The built-in catalog is resolved separately.  This function validates a
    plugin-owned fragment without requiring that plugin to copy the catalog.
    """
    if value is None or value == {}:
        return {}
    if not isinstance(value, Mapping):
        raise LinuxRegistrationContractError(f"{field} must be an object")
    _unknown(value, _CONTRACT_FIELDS, field)
    root_table = _safe_id(value.get("root_table"), f"{field}.root_table")
    identity_field = value.get("identity_field", "driver_name")
    if identity_field not in _IDENTITY_FIELDS:
        raise LinuxRegistrationContractError(
            f"{field}.identity_field must be driver_name, registrar, or none")
    raw_ids = value.get("device_id_tables", [])
    if not isinstance(raw_ids, list):
        raise LinuxRegistrationContractError(
            f"{field}.device_id_tables must be a list")
    device_id_tables: list[str] = []
    for index, item in enumerate(raw_ids):
        table = _safe_id(item, f"{field}.device_id_tables[{index}]")
        if table in device_id_tables:
            raise LinuxRegistrationContractError(
                f"{field}.device_id_tables contains duplicates")
        device_id_tables.append(table)
    tables = _parse_tables(value.get("tables", []), f"{field}.tables")
    apis = _parse_apis(value.get("registration_apis", []),
                       f"{field}.registration_apis")
    links = _parse_links(value.get("links", []), f"{field}.links")
    irq_attach_apis = _parse_irq_attach_apis(
        value.get("irq_attach_apis", []), f"{field}.irq_attach_apis")
    direct_irq_apis = _parse_direct_irq_apis(
        value.get("direct_irq_apis", []), f"{field}.direct_irq_apis")
    table_by_id = {item["id"]: item for item in tables}
    if root_table not in table_by_id and (tables or apis or links):
        raise LinuxRegistrationContractError(
            f"{field}.root_table is missing from declared tables: {root_table}")
    for api in apis:
        if api["table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis table is unknown: {api['table']}")
        record = table_by_id[api["table"]]["record"]
        if record is None or not re.search(
                rf"\bstruct\s+{re.escape(record)}\s*\*\s*\Z", api["type"]):
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis type/table mismatch for {api['name']}")
    for link in links:
        if link["owner_table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.links owner_table is unknown: {link['owner_table']}")
        if link["target_table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.links target_table is unknown: {link['target_table']}")
    declared_device_tables = {
        item["id"] for item in tables if item["role"] == "device_id"
    }
    unknown_device_tables = set(device_id_tables) - declared_device_tables
    if unknown_device_tables and tables:
        raise LinuxRegistrationContractError(
            f"{field}.device_id_tables table is not declared: "
            + ", ".join(sorted(unknown_device_tables)))
    result: dict[str, Any] = {
        "root_table": root_table,
        "identity_field": identity_field,
        "device_id_tables": device_id_tables,
    }
    for key, parsed in (("registration_apis", apis), ("tables", tables),
                        ("links", links), ("irq_attach_apis", irq_attach_apis),
                        ("direct_irq_apis", direct_irq_apis)):
        if parsed:
            if key == "registration_apis":
                result[key] = [{
                    "name": item["name"], "kind": item["kind"],
                    "argument": item["arg"], "type": item["type"],
                    "table": item["table"],
                } for item in parsed]
            elif key in {"irq_attach_apis", "direct_irq_apis"}:
                result[key] = {
                    name: dict(item) for name, item in parsed.items()
                }
            else:
                result[key] = [dict(item) for item in parsed]
        elif key in value:
            result[key] = []
    return result


def _validate_catalog_document(document: Any, field: str) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise LinuxRegistrationContractError(f"{field} must be an object")
    _unknown(document, _CATALOG_FIELDS, field)
    if document.get("schema") != 1:
        raise LinuxRegistrationContractError(f"{field}.schema is unsupported")
    tables = _parse_tables(document.get("tables"), f"{field}.tables")
    table_ids = {item["id"] for item in tables}
    root_tables = {item["id"] for item in tables if item["role"] == "root"}
    device_id_tables = {
        item["id"] for item in tables if item["role"] == "device_id"
    }
    apis = _parse_apis(
        document.get("registration_apis"), f"{field}.registration_apis")
    links = _parse_links(document.get("links"), f"{field}.links")
    irq_attach_apis = _parse_irq_attach_apis(
        document.get("irq_attach_apis", []), f"{field}.irq_attach_apis")
    direct_irq_apis = _parse_direct_irq_apis(
        document.get("direct_irq_apis", []), f"{field}.direct_irq_apis")
    builtin_driver_macros = _parse_builtin_driver_macros(
        document.get("builtin_driver_macros", {}),
        f"{field}.builtin_driver_macros")
    legacy_runtime_contracts = _parse_legacy_runtime_contracts(
        document.get("legacy_runtime_contracts", {}),
        f"{field}.legacy_runtime_contracts", table_ids=table_ids,
        device_id_tables=device_id_tables, root_tables=root_tables)
    for api in apis:
        if api["table"] not in table_ids:
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis table is unknown: {api['table']}")
        record = next(item["record"] for item in tables
                      if item["id"] == api["table"])
        if record is None or not re.search(
                rf"\bstruct\s+{re.escape(record)}\s*\*\s*\Z", api["type"]):
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis type/table mismatch for {api['name']}")
    for link in links:
        if link["owner_table"] not in table_ids:
            raise LinuxRegistrationContractError(
                f"{field}.links owner_table is unknown: {link['owner_table']}")
        if link["target_table"] not in table_ids:
            raise LinuxRegistrationContractError(
                f"{field}.links target_table is unknown: {link['target_table']}")
    return {
        "tables": tables,
        "registration_apis": apis,
        "links": links,
        "builtin_driver_macros": builtin_driver_macros,
        "legacy_runtime_contracts": legacy_runtime_contracts,
        "irq_attach_apis": irq_attach_apis,
        "direct_irq_apis": direct_irq_apis,
    }


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_linux_registration_catalog(
        root: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the repository-owned Linux registration catalog."""
    repo_root = Path(root).resolve() if root is not None else _default_root()
    path = repo_root / "benchmarks" / _CATALOG_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LinuxRegistrationContractError(
            f"cannot read Linux registration catalog: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LinuxRegistrationContractError(
            f"Linux registration catalog is invalid JSON: {path}") from exc
    return _validate_catalog_document(document, "catalog")


def _merge_policy(
        catalog: Mapping[str, Any], extension: Mapping[str, Any] | None,
        field: str) -> dict[str, Any]:
    tables = [dict(item) for item in catalog["tables"]]
    apis = [dict(item) for item in catalog["registration_apis"]]
    links = [dict(item) for item in catalog["links"]]
    builtin_driver_macros = dict(catalog["builtin_driver_macros"])
    irq_attach_apis = {
        name: dict(item) for name, item in catalog["irq_attach_apis"].items()
    }
    direct_irq_apis = {
        name: dict(item) for name, item in catalog["direct_irq_apis"].items()
    }
    legacy_runtime_contracts = {
        bus: dict(contract)
        for bus, contract in catalog["legacy_runtime_contracts"].items()
    }
    if extension is not None:
        if not isinstance(extension, Mapping):
            raise LinuxRegistrationContractError(f"{field} must be an object")
        _unknown(extension, _CONTRACT_FIELDS, field)
        extension_tables = _parse_tables(extension.get("tables", []), f"{field}.tables")
        extension_apis = _parse_apis(
            extension.get("registration_apis", []),
            f"{field}.registration_apis")
        extension_links = _parse_links(extension.get("links", []), f"{field}.links")
        extension_irq_attach = _parse_irq_attach_apis(
            extension.get("irq_attach_apis", []),
            f"{field}.irq_attach_apis")
        extension_direct_irq = _parse_direct_irq_apis(
            extension.get("direct_irq_apis", []),
            f"{field}.direct_irq_apis")
        existing_tables = {item["id"] for item in tables}
        duplicates = existing_tables & {item["id"] for item in extension_tables}
        if duplicates:
            raise LinuxRegistrationContractError(
                f"{field}.tables duplicates catalog table(s): "
                + ", ".join(sorted(duplicates)))
        existing_apis = {item["name"] for item in apis}
        duplicates = existing_apis & {item["name"] for item in extension_apis}
        if duplicates:
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis duplicates catalog API(s): "
                + ", ".join(sorted(duplicates)))
        tables.extend(extension_tables)
        apis.extend(extension_apis)
        links.extend(extension_links)
        duplicate_irq = set(irq_attach_apis) & set(extension_irq_attach)
        if duplicate_irq:
            raise LinuxRegistrationContractError(
                f"{field}.irq_attach_apis duplicates catalog API(s): "
                + ", ".join(sorted(duplicate_irq)))
        duplicate_direct = set(direct_irq_apis) & set(extension_direct_irq)
        if duplicate_direct:
            raise LinuxRegistrationContractError(
                f"{field}.direct_irq_apis duplicates catalog API(s): "
                + ", ".join(sorted(duplicate_direct)))
        irq_attach_apis.update(extension_irq_attach)
        direct_irq_apis.update(extension_direct_irq)

    table_by_id = {item["id"]: item for item in tables}
    for api in apis:
        if api["table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis table is unknown: {api['table']}")
        record = table_by_id[api["table"]]["record"]
        if record is None or not re.search(
                rf"\bstruct\s+{re.escape(record)}\s*\*\s*\Z", api["type"]):
            raise LinuxRegistrationContractError(
                f"{field}.registration_apis type/table mismatch for {api['name']}")
    link_by_key: dict[tuple[str, str], str] = {}
    for link in links:
        if link["owner_table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.links owner_table is unknown: {link['owner_table']}")
        if link["target_table"] not in table_by_id:
            raise LinuxRegistrationContractError(
                f"{field}.links target_table is unknown: {link['target_table']}")
        key = (link["owner_table"], link["field"])
        if key in link_by_key:
            raise LinuxRegistrationContractError(
                f"{field}.links duplicates link: "
                f"{link['owner_table']}.{link['field']}")
        link_by_key[key] = link["target_table"]

    root_tables = frozenset(item["id"] for item in tables
                            if item["role"] == "root")
    device_id_tables = frozenset(item["id"] for item in tables
                                 if item["role"] == "device_id")
    struct_tables = {
        item["record"]: item["id"] for item in tables
        if item["record"] is not None
    }
    supported = frozenset(item["id"] for item in tables
                          if item["role"] in {"root", "callback"})
    return {
        "root_tables": root_tables,
        "device_id_tables": device_id_tables,
        "supported_callback_tables": supported,
        "struct_tables": struct_tables,
        "registration_apis": {item["name"]: {
            key: value for key, value in item.items() if key != "name"
        } for item in apis},
        "link_tables": link_by_key,
        "tables": table_by_id,
        "builtin_driver_macros": builtin_driver_macros,
        "legacy_runtime_contracts": legacy_runtime_contracts,
        "irq_attach_apis": irq_attach_apis,
        "direct_irq_apis": direct_irq_apis,
    }


def resolve_linux_registration_policy(
        contract: Mapping[str, Any] | None = None,
        *, root: str | Path | None = None) -> dict[str, Any]:
    """Resolve built-in and plugin-declared registration semantics."""
    catalog = load_linux_registration_catalog(root)
    extension = contract if isinstance(contract, Mapping) else None
    if extension is not None:
        extension = validate_linux_registration_contract(
            extension, field="registration contract")
    policy = _merge_policy(catalog, extension, "registration contract")
    if extension is None:
        return policy

    root_table = _safe_id(extension.get("root_table"),
                           "registration contract.root_table")
    identity_field = extension.get("identity_field", "driver_name")
    if identity_field not in _IDENTITY_FIELDS:
        raise LinuxRegistrationContractError(
            "registration contract.identity_field must be driver_name, registrar, or none")
    if root_table not in policy["root_tables"]:
        raise LinuxRegistrationContractError(
            f"registration contract.root_table is not a declared root table: {root_table}")
    raw_ids = extension.get("device_id_tables", [])
    if not isinstance(raw_ids, list):
        raise LinuxRegistrationContractError(
            "registration contract.device_id_tables must be a list")
    for index, table in enumerate(raw_ids):
        table_id = _safe_id(table, f"registration contract.device_id_tables[{index}]")
        if table_id not in policy["device_id_tables"]:
            raise LinuxRegistrationContractError(
                f"registration contract.device_id_tables table is unknown: {table_id}")
    return policy


__all__ = [
    "LinuxRegistrationContractError",
    "load_linux_registration_catalog",
    "resolve_linux_registration_policy",
    "validate_linux_registration_contract",
]
