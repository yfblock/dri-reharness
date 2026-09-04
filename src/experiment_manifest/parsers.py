"""Section parsers turning raw manifest dictionaries into typed specs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from linux_registration_contracts import (  # noqa: E402
    LinuxRegistrationContractError,
    validate_linux_registration_contract,
)
from subsystem_providers import ProviderCatalogError

from .validators import (
    ManifestError, _string, _unknown, _required, _integer, _inside_repo,
    _KNOWN_CAPABILITIES, _QEMU_BINDING_FIELDS, _REGISTRATION_FIELDS,
    _REGISTRATION_IDENTITY_FIELDS, _SAFETY_FIELDS,
    _SUBSYSTEM_CONTRACT_FIELDS, _SUBSYSTEM_CONTRACT_REQUIRED_FIELDS,
    _FIXTURE_FIELDS, _CAPABILITY_FIELDS, _COVERAGE_FIELDS,
)
from .specs import (
    CoverageSpec, QemuBinding, RegistrationContract, RuntimeCapabilities,
    RuntimeFixture, SafetyPolicy, SubsystemTestSpec, SubsystemTestSuite,
)


def _parse_mask(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ManifestError(f"{field} must be an integer mask")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        try:
            result = int(value, 0)
        except ValueError as exc:
            raise ManifestError(f"{field} must be an integer mask") from exc
    else:
        raise ManifestError(f"{field} must be an integer mask")
    if result < 0:
        raise ManifestError(f"{field} must be non-negative")
    return result


def _parse_pci_value(value: Any, field: str) -> int:
    result = _parse_mask(value, field)
    if result > 0xFFFFFFFF:
        raise ManifestError(f"{field} must fit in 32 bits")
    return result


def _parse_safety(document: Any, field: str = "runtime.safety_policy") -> SafetyPolicy:
    if document is None:
        return SafetyPolicy()
    if not isinstance(document, Mapping):
        raise ManifestError(f"{field} must be an object")
    _unknown(document, _SAFETY_FIELDS, field)
    tokens = document.get("forbidden_tokens", [])
    if not isinstance(tokens, list) or any(not isinstance(item, str) or not item for item in tokens):
        raise ManifestError(f"{field}.forbidden_tokens must be a list of non-empty strings")
    action = document.get("action", "reject")
    if action not in {"reject", "rewrite", "allow"}:
        raise ManifestError(f"{field}.action must be reject, rewrite, or allow")
    failure_class = document.get("failure_class", "safety")
    if not isinstance(failure_class, str) or not failure_class.strip():
        raise ManifestError(f"{field}.failure_class must be a non-empty string")
    rules = document.get("rewrite_rules", [])
    if not isinstance(rules, list) or any(not isinstance(item, Mapping) for item in rules):
        raise ManifestError(f"{field}.rewrite_rules must be a list of objects")
    normalized_rules: list[Mapping[str, str]] = []
    for index, rule in enumerate(rules):
        _unknown(rule, {"pattern", "replacement"}, f"{field}.rewrite_rules[{index}]")
        _required(rule, {"pattern", "replacement"}, f"{field}.rewrite_rules[{index}]")
        pattern = _string(rule["pattern"], f"{field}.rewrite_rules[{index}].pattern")
        replacement = _string(rule["replacement"], f"{field}.rewrite_rules[{index}].replacement", nonempty=False)
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ManifestError(f"{field}.rewrite_rules[{index}].pattern is invalid") from exc
        normalized_rules.append({"pattern": pattern, "replacement": replacement})
    return SafetyPolicy(tuple(tokens), action, failure_class, tuple(normalized_rules))


def _parse_capabilities(document: Any) -> RuntimeCapabilities:
    if document is None:
        return RuntimeCapabilities()
    if not isinstance(document, Mapping):
        raise ManifestError("runtime.capabilities must be an object")
    _unknown(document, _CAPABILITY_FIELDS, "runtime.capabilities")
    values: dict[str, tuple[str, ...]] = {}
    for field in ("required", "optional"):
        raw = document.get(field, [])
        if (not isinstance(raw, list)
                or any(not isinstance(value, str) or not value.strip()
                       for value in raw)):
            raise ManifestError(
                f"runtime.capabilities.{field} must be a list of non-empty strings")
        if len(set(raw)) != len(raw):
            raise ManifestError(
                f"runtime.capabilities.{field} contains duplicate capability")
        values[field] = tuple(raw)

    required = values["required"]
    optional = values["optional"]
    unknown = sorted(set(required + optional) - _KNOWN_CAPABILITIES)
    if unknown:
        raise ManifestError(
            "runtime.capabilities contains unknown capability: "
            + ", ".join(unknown))
    overlap = sorted(set(required) & set(optional))
    if overlap:
        raise ManifestError(
            "runtime.capabilities required and optional overlap: "
            + ", ".join(overlap))
    return RuntimeCapabilities(required, optional)


def _parse_registration_contract(
        document: Any) -> RegistrationContract | None:
    if document is None:
        return None
    try:
        normalized = validate_linux_registration_contract(
            document, field="runtime.registration")
    except LinuxRegistrationContractError as exc:
        raise ManifestError(str(exc)) from exc
    extensions = {
        key: value for key, value in normalized.items()
        if key in {"registration_apis", "tables", "links"}
    }
    return RegistrationContract(
        normalized["root_table"], normalized["identity_field"],
        tuple(normalized["device_id_tables"]),
        extensions,
    )


def _parse_subsystem_contracts(document: Any) -> tuple[Mapping[str, Any], ...]:
    if document is None:
        return ()
    if not isinstance(document, list):
        raise ManifestError("runtime.subsystem_contracts must be a list")
    result: list[Mapping[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(document):
        field = f"runtime.subsystem_contracts[{index}]"
        if not isinstance(item, Mapping):
            raise ManifestError(f"{field} must be an object")
        _unknown(item, _SUBSYSTEM_CONTRACT_FIELDS, field)
        _required(item, _SUBSYSTEM_CONTRACT_REQUIRED_FIELDS, field)
        contract_id = _string(item["id"], f"{field}.id")
        subsystem = _string(item["subsystem"], f"{field}.subsystem")
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", contract_id) is None:
            raise ManifestError(f"{field}.id is unsafe")
        if re.fullmatch(r"[A-Za-z0-9_.+-]+", subsystem) is None:
            raise ManifestError(f"{field}.subsystem is unsafe")
        if contract_id in ids:
            raise ManifestError(f"{field}.id is duplicated")
        ids.add(contract_id)
        score = _integer(item["score"], f"{field}.score", minimum=0)
        reason = _string(item["reason"], f"{field}.reason")
        capability_values: dict[str, tuple[str, ...]] = {}
        for capability_field in ("required_capabilities",
                                 "optional_capabilities"):
            raw = item[capability_field]
            if (not isinstance(raw, list)
                    or any(not isinstance(value, str) or not value.strip()
                           for value in raw)):
                raise ManifestError(
                    f"{field}.{capability_field} must be a list of strings")
            if len(set(raw)) != len(raw):
                raise ManifestError(
                    f"{field}.{capability_field} contains duplicate capability")
            capability_values[capability_field] = tuple(raw)
        capabilities = (capability_values["required_capabilities"]
                        + capability_values["optional_capabilities"])
        unknown = sorted(set(capabilities) - _KNOWN_CAPABILITIES)
        if unknown:
            raise ManifestError(
                f"{field} contains unknown capability: {', '.join(unknown)}")
        overlap = sorted(set(capability_values["required_capabilities"])
                         & set(capability_values["optional_capabilities"]))
        if overlap:
            raise ManifestError(
                f"{field} required and optional capabilities overlap: "
                + ", ".join(overlap))
        summary_values: dict[str, tuple[str, ...]] = {}
        for summary_field in ("summary_groups", "summary_contracts"):
            raw = item.get(summary_field, [])
            if (not isinstance(raw, list)
                    or any(not isinstance(value, str) or not value.strip()
                           for value in raw)):
                raise ManifestError(
                    f"{field}.{summary_field} must be a list of strings")
            if len(set(raw)) != len(raw):
                raise ManifestError(
                    f"{field}.{summary_field} contains duplicate value")
            summary_values[summary_field] = tuple(raw)
        candidate_validator = item.get("candidate_validator")
        if candidate_validator is not None:
            candidate_validator = _string(
                candidate_validator, f"{field}.candidate_validator")
            if re.fullmatch(r"[A-Za-z0-9_.+-]+", candidate_validator) is None:
                raise ManifestError(
                    f"{field}.candidate_validator is unsafe")
        result.append({
            "id": contract_id,
            "subsystem": subsystem,
            "reason": reason,
            "score": score,
            "required_capabilities": list(
                capability_values["required_capabilities"]),
            "optional_capabilities": list(
                capability_values["optional_capabilities"]),
            "summary_groups": list(summary_values["summary_groups"]),
            "summary_contracts": list(summary_values["summary_contracts"]),
            **({"candidate_validator": candidate_validator}
               if candidate_validator is not None else {}),
        })
    return tuple(result)


def _parse_qemu_binding(document: Any) -> QemuBinding | None:
    if document is None:
        return None
    if not isinstance(document, Mapping):
        raise ManifestError("runtime.qemu.binding must be an object")
    _unknown(document, _QEMU_BINDING_FIELDS, "runtime.qemu.binding")
    _required(document, {"bus"}, "runtime.qemu.binding")
    bus = _string(document["bus"], "runtime.qemu.binding.bus")
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", bus) is None:
        raise ManifestError("runtime.qemu.binding.bus is unsafe")
    device_glob = document.get("device_glob", "*")
    if not isinstance(device_glob, str) or not device_glob.strip():
        raise ManifestError(
            "runtime.qemu.binding.device_glob must be a non-empty string")
    if re.fullmatch(r"[A-Za-z0-9_.*:+?-]+", device_glob) is None:
        raise ManifestError("runtime.qemu.binding.device_glob is unsafe")
    required = document.get("required", True)
    if not isinstance(required, bool):
        raise ManifestError("runtime.qemu.binding.required must be a boolean")
    return QemuBinding(bus, device_glob, required)


def _json_config(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{field} must be an object")

    def check(item: Any, where: str) -> Any:
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise ManifestError(f"{where} keys must be strings")
            return {key: check(child, f"{where}.{key}")
                    for key, child in item.items()}
        if isinstance(item, list):
            return [check(child, f"{where}[{index}]")
                    for index, child in enumerate(item)]
        raise ManifestError(f"{where} must contain only JSON values")

    return check(value, field)


def _parse_fixture(document: Any, root: Path) -> RuntimeFixture | None:
    if document is None:
        return None
    if not isinstance(document, Mapping):
        raise ManifestError("runtime.fixture must be an object")
    _unknown(document, _FIXTURE_FIELDS, "runtime.fixture")
    _required(document, {"kind", "config"}, "runtime.fixture")
    kind = _string(document["kind"], "runtime.fixture.kind")
    config = _json_config(document["config"], "runtime.fixture.config")
    module_args = config.get("module_args")
    if module_args is not None:
        if (not isinstance(module_args, Mapping)
                or any(re.fullmatch(r"[A-Za-z0-9_.+-]+", str(name)) is None
                       for name in module_args)):
            raise ManifestError(
                "runtime.fixture.config.module_args must map safe module names"
            )
        for module, values in module_args.items():
            if (not isinstance(values, list)
                    or any(not isinstance(value, str)
                           or re.fullmatch(
                               r"[A-Za-z0-9_.+-]+(?:=[A-Za-z0-9_.+-]+)?",
                               value) is None
                           for value in values)):
                raise ManifestError(
                    "runtime.fixture.config.module_args values must be safe arguments"
                )

    raw_assets = document.get("assets", [])
    if (not isinstance(raw_assets, list)
            or any(not isinstance(value, str) or not value.strip()
                   for value in raw_assets)):
        raise ManifestError("runtime.fixture.assets must be a list of paths")
    assets = tuple(_inside_repo(value, root, "runtime.fixture.assets")
                   for value in raw_assets)

    raw_module_sources = document.get("module_sources", [])
    if (not isinstance(raw_module_sources, list)
            or any(not isinstance(value, str) or not value.strip()
                   for value in raw_module_sources)):
        raise ManifestError(
            "runtime.fixture.module_sources must be a list of paths")
    if any(Path(value).suffix.lower() != ".c" for value in raw_module_sources):
        raise ManifestError(
            "runtime.fixture.module_sources must contain C source paths")
    module_sources = tuple(
        _inside_repo(value, root, "runtime.fixture.module_sources")
        for value in raw_module_sources)

    raw_modules = document.get("kernel_modules", [])
    if (not isinstance(raw_modules, list)
            or any(not isinstance(value, str) or not value.strip()
                   or re.fullmatch(r"[A-Za-z0-9_.+-]+", value) is None
                   for value in raw_modules)):
        raise ManifestError(
            "runtime.fixture.kernel_modules must be a list of safe module names")

    raw_commands = document.get("init_commands", [])
    if (not isinstance(raw_commands, list)
            or any(not isinstance(value, str) or not value.strip()
                   or any(char in value for char in ";&|$`<>\n\r")
                   for value in raw_commands)):
        raise ManifestError(
            "runtime.fixture.init_commands contains unsafe command")

    return RuntimeFixture(kind, config, assets, module_sources,
                          tuple(raw_modules), tuple(raw_commands))


def _parse_coverage(document: Any) -> CoverageSpec | None:
    if document is None:
        return None
    if not isinstance(document, Mapping):
        raise ManifestError("test.coverage must be an object")
    _unknown(document, _COVERAGE_FIELDS, "test.coverage")
    required = document.get("required", [])
    callbacks = document.get("callbacks", [])
    for values, field in ((required, "test.coverage.required"),
                          (callbacks, "test.coverage.callbacks")):
        if (not isinstance(values, list)
                or any(not isinstance(value, str) or not value.strip()
                       for value in values)):
            raise ManifestError(f"{field} must be a list of non-empty strings")
        if len(set(values)) != len(values):
            raise ManifestError(f"{field} must not contain duplicates")
    for value in required:
        if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None:
            raise ManifestError(
                "test.coverage.required entries must use safe marker identifiers")
    return CoverageSpec(tuple(required), tuple(callbacks))


