"""Typed, repository-scoped experiment manifests.

The manifest is deliberately small and data-only.  Keeping validation here
means orchestration code can consume a trusted object instead of repeatedly
interpreting loosely typed JSON dictionaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from subsystem_providers import ProviderCatalogError, load_provider_catalog
from linux_registration_contracts import (  # noqa: E402
    LinuxRegistrationContractError,
    validate_linux_registration_contract,
)


class ManifestError(ValueError):
    """Raised when an experiment manifest is malformed or unsafe."""


ManifestValidationError = ManifestError


_TOP_FIELDS = {"schema", "name", "source", "compile", "runtime", "test", "trace", "limits"}
_SOURCE_FIELDS = {"path", "sha256"}
_COMPILE_FIELDS = {"backend", "language", "context"}
_RUNTIME_FIELDS = {
    "adapter", "pci_identity", "safety_policy", "qemu", "profile",
    "capabilities", "fixture", "subsystem_contracts", "registration",
}
_PCI_FIELDS = {"vendor", "device", "subsystem_vendor", "subsystem_device", "class_code"}
_SAFETY_FIELDS = {"forbidden_tokens", "action", "failure_class", "rewrite_rules"}
_QEMU_FIELDS = {"machine", "device", "bus", "module", "timeout_seconds",
                "probe_pattern", "registrar", "qemu_args", "kernel_modules",
                "launch_device", "binding"}
_QEMU_BINDING_FIELDS = {"bus", "device_glob", "required"}
_CAPABILITY_FIELDS = {"required", "optional"}
_REGISTRATION_FIELDS = {
    "root_table", "identity_field", "device_id_tables",
    "registration_apis", "tables", "links",
}
_REGISTRATION_IDENTITY_FIELDS = {"driver_name", "registrar", "none"}
_SUBSYSTEM_CONTRACT_FIELDS = {
    "id", "subsystem", "reason", "score", "required_capabilities",
    "optional_capabilities", "summary_groups", "summary_contracts",
    "candidate_validator",
}
_SUBSYSTEM_CONTRACT_REQUIRED_FIELDS = {
    "id", "subsystem", "reason", "score", "required_capabilities",
    "optional_capabilities",
}
_FIXTURE_FIELDS = {
    "kind", "config", "assets", "module_sources", "kernel_modules",
    "init_commands",
}
_TEST_FIELDS = {"executable", "args", "actions", "success_pattern", "subsystem", "coverage"}
_SUBSYSTEM_FIELDS = {"name", "tests"}
_SUBSYSTEM_TEST_FIELDS = {
    "name", "kind", "module", "provider", "required", "executable", "args",
    "success_pattern", "assets",
}
_COVERAGE_FIELDS = {"required", "callbacks"}
_TRACE_FIELDS = {"fields", "value_mask", "address_mask", "normalize_function", "instrument", "exercised_calls"}
_LIMIT_FIELDS = {"compile", "runtime", "trace", "total"}
_TRACE_EVENT_FIELDS = {
    "phase", "function", "kind", "width_bits", "address", "value", "sequence", "source_op_id",
}
_TRACE_KINDS = {
    "read", "write", "rmw", "readmodifywrite", "read_modify_write", "r", "w", "return", "error",
}
_KNOWN_CAPABILITIES = frozenset({
    "static_analysis", "generation_contract", "kbuild", "registration",
    "probe", "subsystem", "unload", "trace", "transaction", "transfer",
})


def _unknown(document: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(document) - allowed)
    if extra:
        raise ManifestError(f"{where} contains unknown field(s): {', '.join(extra)}")


def _required(document: Mapping[str, Any], fields: set[str], where: str) -> None:
    missing = sorted(fields - set(document))
    if missing:
        raise ManifestError(f"{where} missing required field(s): {', '.join(missing)}")


def _string(value: Any, field: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ManifestError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        if field.startswith("limits."):
            raise ManifestError(f"iteration limit {field} must be at least {minimum}")
        raise ManifestError(f"{field} must be at least {minimum}")
    return value


def _repo_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / ".gitmodules").is_file() and (candidate / "README.md").is_file():
            return candidate
    return start.resolve()


def _inside_repo(path_value: Any, repo_root: Path, field: str) -> Path:
    raw = _string(path_value, field)
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ManifestError(f"{field} resolves outside repository: {raw}") from exc
    return resolved


def _hex_digest(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _string(value, field).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ManifestError(f"{field} must be a SHA-256 hex digest")
    return text


@dataclass(frozen=True)
class SourceSpec:
    path: Path
    sha256: str | None = None

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        path = self.path
        if root is not None:
            try:
                path = path.resolve().relative_to(root.resolve())
            except ValueError:
                pass
        result: dict[str, Any] = {"path": str(path)}
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result


@dataclass(frozen=True)
class CompileSpec:
    backend: str
    language: str
    context: str

    def to_dict(self) -> dict[str, str]:
        return {"backend": self.backend, "language": self.language, "context": self.context}


@dataclass(frozen=True)
class PciIdentity:
    vendor: int | str
    device: int | str
    subsystem_vendor: int | str | None = None
    subsystem_device: int | str | None = None
    class_code: int | str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"vendor": self.vendor, "device": self.device}
        for field in ("subsystem_vendor", "subsystem_device", "class_code"):
            value = getattr(self, field)
            if value is not None:
                result[field] = value
        return result


@dataclass(frozen=True)
class SafetyPolicy:
    forbidden_tokens: tuple[str, ...] = ()
    action: str = "reject"
    failure_class: str = "safety"
    rewrite_rules: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "forbidden_tokens": list(self.forbidden_tokens),
            "action": self.action,
            "failure_class": self.failure_class,
        }
        if self.rewrite_rules:
            result["rewrite_rules"] = [dict(rule) for rule in self.rewrite_rules]
        return result


@dataclass(frozen=True)
class RuntimeCapabilities:
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"required": list(self.required)}
        if self.optional:
            result["optional"] = list(self.optional)
        return result


@dataclass(frozen=True)
class RegistrationContract:
    """Declarative Linux registration identity semantics for a profile."""

    root_table: str
    identity_field: str = "driver_name"
    device_id_tables: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "root_table": self.root_table,
            "identity_field": self.identity_field,
            "device_id_tables": list(self.device_id_tables),
        }
        result.update({str(key): value for key, value in self.extensions.items()})
        return result


@dataclass(frozen=True)
class RuntimeFixture:
    kind: str
    config: Mapping[str, Any]
    assets: tuple[Path, ...] = ()
    module_sources: tuple[Path, ...] = ()
    kernel_modules: tuple[str, ...] = ()
    init_commands: tuple[str, ...] = ()

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "config": {str(key): value for key, value in self.config.items()},
        }
        if self.assets:
            rendered: list[str] = []
            for asset in self.assets:
                value: Path | str = asset
                if root is not None:
                    try:
                        value = asset.resolve().relative_to(root.resolve())
                    except ValueError:
                        pass
                rendered.append(str(value))
            result["assets"] = rendered
        if self.module_sources:
            rendered_sources: list[str] = []
            for source in self.module_sources:
                value: Path | str = source
                if root is not None:
                    try:
                        value = source.resolve().relative_to(root.resolve())
                    except ValueError:
                        pass
                rendered_sources.append(str(value))
            result["module_sources"] = rendered_sources
        if self.kernel_modules:
            result["kernel_modules"] = list(self.kernel_modules)
        if self.init_commands:
            result["init_commands"] = list(self.init_commands)
        return result


@dataclass(frozen=True)
class QemuPolicy:
    machine: str
    device: str
    bus: str
    module: str
    timeout_seconds: int
    probe_pattern: str | None = None
    registrar: str | None = None
    qemu_args: tuple[str, ...] = ()
    kernel_modules: tuple[str, ...] = ()
    launch_device: bool = False
    binding: "QemuBinding | None" = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "machine": self.machine, "device": self.device, "bus": self.bus,
            "module": self.module, "timeout_seconds": self.timeout_seconds,
            "launch_device": self.launch_device,
        }
        if self.probe_pattern is not None:
            result["probe_pattern"] = self.probe_pattern
        if self.registrar is not None:
            result["registrar"] = self.registrar
        if self.qemu_args:
            result["qemu_args"] = list(self.qemu_args)
        if self.kernel_modules:
            result["kernel_modules"] = list(self.kernel_modules)
        if self.binding is not None:
            result["binding"] = self.binding.to_dict()
        return result


@dataclass(frozen=True)
class QemuBinding:
    """Manifest-owned sysfs binding assertion for a runtime fixture."""

    bus: str
    device_glob: str = "*"
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "bus": self.bus,
            "device_glob": self.device_glob,
            "required": self.required,
        }


@dataclass(frozen=True)
class RuntimeSpec:
    adapter: str
    qemu: QemuPolicy
    pci_identity: PciIdentity | None = None
    safety_policy: SafetyPolicy = SafetyPolicy()
    profile: str | None = None
    capabilities: RuntimeCapabilities = RuntimeCapabilities()
    fixture: RuntimeFixture | None = None
    subsystem_contracts: tuple[Mapping[str, Any], ...] = ()
    registration: RegistrationContract | None = None

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"adapter": self.adapter, "qemu": self.qemu.to_dict(),
                                  "safety_policy": self.safety_policy.to_dict()}
        if self.pci_identity is not None:
            result["pci_identity"] = self.pci_identity.to_dict()
        if self.profile is not None:
            result["profile"] = self.profile
        if self.capabilities.required or self.capabilities.optional:
            result["capabilities"] = self.capabilities.to_dict()
        if self.fixture is not None:
            result["fixture"] = self.fixture.to_dict(root=root)
        if self.subsystem_contracts:
            result["subsystem_contracts"] = [dict(item)
                                               for item in self.subsystem_contracts]
        if self.registration is not None:
            result["registration"] = self.registration.to_dict()
        return result


@dataclass(frozen=True)
class SubsystemTestSpec:
    name: str
    executable: Path | None
    kind: str = "native"
    module: str | None = None
    args: tuple[str, ...] = ()
    success_pattern: str | None = None
    assets: tuple[Path, ...] = ()
    provider: str | None = None
    required: bool = True

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        executable: Path | str | None = self.executable
        if executable is not None and root is not None:
            try:
                executable = executable.resolve().relative_to(root.resolve())
            except ValueError:
                pass
        result: dict[str, Any] = {
            "name": self.name,
            "args": list(self.args),
        }
        if self.kind != "native":
            result["kind"] = self.kind
        if self.provider is not None:
            result["provider"] = self.provider
        if not self.required:
            result["required"] = False
        if self.module is not None:
            result["module"] = self.module
        if executable is not None:
            result["executable"] = str(executable)
        if self.success_pattern is not None:
            result["success_pattern"] = self.success_pattern
        if self.assets:
            result["assets"] = []
            for asset in self.assets:
                value: Path | str = asset
                if root is not None:
                    try:
                        value = asset.resolve().relative_to(root.resolve())
                    except ValueError:
                        pass
                result["assets"].append(str(value))
        return result


@dataclass(frozen=True)
class SubsystemTestSuite:
    name: str
    tests: tuple[SubsystemTestSpec, ...]

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "tests": [test.to_dict(root=root) for test in self.tests],
        }


@dataclass(frozen=True)
class CoverageSpec:
    """Explicit guest-observable API and callback coverage contract."""

    required: tuple[str, ...] = ()
    callbacks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": list(self.required),
            "callbacks": list(self.callbacks),
        }


@dataclass(frozen=True)
class TestSpec:
    executable: Path | None
    args: tuple[str, ...] = ()
    actions: tuple[Mapping[str, Any], ...] = ()
    success_pattern: str | None = None
    subsystem: SubsystemTestSuite | None = None
    coverage: CoverageSpec | None = None

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        executable: Path | str | None = self.executable
        if executable is not None and root is not None:
            try:
                executable = executable.resolve().relative_to(root.resolve())
            except ValueError:
                pass
        result: dict[str, Any] = {"args": list(self.args)}
        if self.executable is not None:
            result["executable"] = str(executable)
        if self.actions:
            result["actions"] = [dict(action) for action in self.actions]
        if self.success_pattern is not None:
            result["success_pattern"] = self.success_pattern
        if self.subsystem is not None:
            result["subsystem"] = self.subsystem.to_dict(root=root)
        if self.coverage is not None:
            result["coverage"] = self.coverage.to_dict()
        return result


@dataclass(frozen=True)
class TraceSpec:
    fields: tuple[str, ...]
    value_mask: int | None = None
    address_mask: int | None = None
    normalize_function: bool = True
    instrument: bool = False
    exercised_calls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"fields": list(self.fields)}
        if self.value_mask is not None:
            result["value_mask"] = hex(self.value_mask)
        if self.address_mask is not None:
            result["address_mask"] = hex(self.address_mask)
        if not self.normalize_function:
            result["normalize_function"] = False
        if self.instrument:
            result["instrument"] = True
        if self.exercised_calls:
            result["exercised_calls"] = list(self.exercised_calls)
        return result


@dataclass(frozen=True)
class IterationLimits:
    compile: int
    runtime: int
    trace: int
    total: int | None = None

    def to_dict(self) -> dict[str, int]:
        result = {"compile": self.compile, "runtime": self.runtime, "trace": self.trace}
        if self.total is not None:
            result["total"] = self.total
        return result


@dataclass(frozen=True)
class ExperimentManifest:
    schema: int
    name: str
    source: SourceSpec
    compile: CompileSpec
    runtime: RuntimeSpec
    test: TestSpec
    trace: TraceSpec
    limits: IterationLimits
    repo_root: Path | None = None
    raw_document: Mapping[str, Any] | None = None
    manifest_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        root = self.repo_root
        return {
            "schema": self.schema,
            "name": self.name,
            "source": self.source.to_dict(root=root),
            "compile": self.compile.to_dict(),
            "runtime": self.runtime.to_dict(root=root),
            "test": self.test.to_dict(root=root),
            "trace": self.trace.to_dict(),
            "limits": self.limits.to_dict(),
        }

    @property
    def digest(self) -> str:
        return manifest_digest(self.raw_document if self.raw_document is not None else self)


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


def validate_manifest(document: Mapping[str, Any], *, repo_root: str | os.PathLike[str] | Path | None = None,
                      manifest_dir: str | os.PathLike[str] | Path | None = None) -> ExperimentManifest:
    if not isinstance(document, Mapping):
        raise ManifestError("manifest must be a JSON object")
    _unknown(document, _TOP_FIELDS, "manifest")
    _required(document, _TOP_FIELDS, "manifest")
    schema = _integer(document["schema"], "schema", minimum=1)
    if schema != 2:
        raise ManifestError(f"unsupported manifest schema: {schema}")
    name = _string(document["name"], "name")
    root = Path(repo_root).resolve() if repo_root is not None else _repo_root(Path.cwd())
    base = Path(manifest_dir).resolve() if manifest_dir is not None else root

    source_doc = document["source"]
    if isinstance(source_doc, str):
        source_doc = {"path": source_doc}
    if not isinstance(source_doc, Mapping):
        raise ManifestError("source must be an object")
    _unknown(source_doc, _SOURCE_FIELDS, "source")
    _required(source_doc, {"path"}, "source")
    source_path = _inside_repo(source_doc["path"], root, "source.path")
    # Relative paths are repository-relative; accepting a manifest-local path
    # when it exists keeps temporary and generated manifests convenient.
    if not source_path.exists() and not Path(str(source_doc["path"])).is_absolute():
        local = (base / str(source_doc["path"])).resolve()
        try:
            local.relative_to(root)
        except ValueError:
            pass
        else:
            source_path = local
    source = SourceSpec(source_path, _hex_digest(source_doc.get("sha256"), "source.sha256"))

    compile_doc = document["compile"]
    if not isinstance(compile_doc, Mapping):
        raise ManifestError("compile must be an object")
    _unknown(compile_doc, _COMPILE_FIELDS, "compile")
    _required(compile_doc, _COMPILE_FIELDS, "compile")
    compile_spec = CompileSpec(*(_string(compile_doc[field], f"compile.{field}") for field in ("backend", "language", "context")))

    runtime_doc = document["runtime"]
    if not isinstance(runtime_doc, Mapping):
        raise ManifestError("runtime must be an object")
    _unknown(runtime_doc, _RUNTIME_FIELDS, "runtime")
    _required(runtime_doc, {"adapter", "qemu"}, "runtime")
    qemu_doc = runtime_doc.get("qemu")
    if not isinstance(qemu_doc, Mapping):
        raise ManifestError("runtime.qemu must be an object")
    _unknown(qemu_doc, _QEMU_FIELDS, "runtime.qemu")
    _required(qemu_doc, {"machine", "device", "bus", "module", "timeout_seconds"}, "runtime.qemu")
    qemu_args = qemu_doc.get("qemu_args", [])
    if not isinstance(qemu_args, list) or any(not isinstance(item, str) for item in qemu_args):
        raise ManifestError("runtime.qemu.qemu_args must be a list of strings")
    kernel_modules = qemu_doc.get("kernel_modules", [])
    if (not isinstance(kernel_modules, list)
            or any(not isinstance(item, str) or not item.strip()
                   or re.fullmatch(r"[A-Za-z0-9_.+-]+", item) is None
                   for item in kernel_modules)):
        raise ManifestError(
            "runtime.qemu.kernel_modules must be a list of safe module names")
    launch_device = qemu_doc.get("launch_device", False)
    if not isinstance(launch_device, bool):
        raise ManifestError("runtime.qemu.launch_device must be a boolean")
    probe_pattern = qemu_doc.get("probe_pattern")
    if probe_pattern is not None:
        probe_pattern = _string(probe_pattern, "runtime.qemu.probe_pattern")
        try:
            re.compile(probe_pattern)
        except re.error as exc:
            raise ManifestError("runtime.qemu.probe_pattern is invalid") from exc
    registrar = qemu_doc.get("registrar")
    if registrar is not None:
        registrar = _string(registrar, "runtime.qemu.registrar")
    binding = _parse_qemu_binding(qemu_doc.get("binding"))
    qemu = QemuPolicy(
        machine=_string(qemu_doc["machine"], "runtime.qemu.machine"),
        device=_string(qemu_doc["device"], "runtime.qemu.device"),
        bus=_string(qemu_doc["bus"], "runtime.qemu.bus"),
        module=_string(qemu_doc["module"], "runtime.qemu.module"),
        timeout_seconds=_integer(qemu_doc["timeout_seconds"], "runtime.qemu.timeout_seconds", minimum=1),
        probe_pattern=probe_pattern,
        registrar=registrar,
        qemu_args=tuple(qemu_args),
        kernel_modules=tuple(kernel_modules),
        launch_device=launch_device,
        binding=binding,
    )
    pci_doc = runtime_doc.get("pci_identity")
    if pci_doc is not None:
        if not isinstance(pci_doc, Mapping):
            raise ManifestError("runtime.pci_identity must be an object")
        _unknown(pci_doc, _PCI_FIELDS, "runtime.pci_identity")
        _required(pci_doc, {"vendor", "device"}, "runtime.pci_identity")
        pci = PciIdentity(
            vendor=_parse_pci_value(pci_doc["vendor"], "runtime.pci_identity.vendor"),
            device=_parse_pci_value(pci_doc["device"], "runtime.pci_identity.device"),
            subsystem_vendor=None if pci_doc.get("subsystem_vendor") is None else _parse_pci_value(pci_doc["subsystem_vendor"], "runtime.pci_identity.subsystem_vendor"),
            subsystem_device=None if pci_doc.get("subsystem_device") is None else _parse_pci_value(pci_doc["subsystem_device"], "runtime.pci_identity.subsystem_device"),
            class_code=None if pci_doc.get("class_code") is None else _parse_pci_value(pci_doc["class_code"], "runtime.pci_identity.class_code"),
        )
    else:
        pci = None
    if qemu.bus == "pci" and pci is None:
        raise ManifestError("runtime.pci_identity is required for PCI QEMU policy")
    profile = runtime_doc.get("profile")
    if profile is not None:
        profile = _string(profile, "runtime.profile")
        if re.fullmatch(r"[A-Za-z0-9_.:-]+", profile) is None:
            raise ManifestError("runtime.profile must be a safe profile identifier")
    capabilities = _parse_capabilities(runtime_doc.get("capabilities"))
    fixture = _parse_fixture(runtime_doc.get("fixture"), root)
    subsystem_contracts = _parse_subsystem_contracts(
        runtime_doc.get("subsystem_contracts"))
    registration = _parse_registration_contract(
        runtime_doc.get("registration"))
    try:
        provider_registry = load_provider_catalog(root)
    except ProviderCatalogError as exc:
        raise ManifestError(str(exc)) from exc
    runtime = RuntimeSpec(
        adapter=_string(runtime_doc["adapter"], "runtime.adapter"),
        qemu=qemu,
        pci_identity=pci,
        safety_policy=_parse_safety(runtime_doc.get("safety_policy")),
        profile=profile,
        capabilities=capabilities,
        fixture=fixture,
        subsystem_contracts=subsystem_contracts,
        registration=registration,
    )

    test_doc = document["test"]
    if not isinstance(test_doc, Mapping):
        raise ManifestError("test must be an object")
    _unknown(test_doc, _TEST_FIELDS, "test")
    subsystem_doc = test_doc.get("subsystem")
    if "executable" not in test_doc and subsystem_doc is None:
        raise ManifestError("test requires executable or subsystem")
    args = test_doc.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ManifestError("test.args must be a list of strings")
    actions = test_doc.get("actions", [])
    if not isinstance(actions, list) or any(not isinstance(item, Mapping) for item in actions):
        raise ManifestError("test.actions must be a list of objects")
    executable = None
    if "executable" in test_doc:
        executable = _inside_repo(test_doc["executable"], root, "test.executable")
        if not executable.exists() and not Path(str(test_doc["executable"])).is_absolute():
            local = (base / str(test_doc["executable"])).resolve()
            try:
                local.relative_to(root)
            except ValueError:
                pass
            else:
                executable = local
    success_pattern = test_doc.get("success_pattern")
    if success_pattern is not None:
        success_pattern = _string(success_pattern, "test.success_pattern")

    subsystem = None
    if subsystem_doc is not None:
        if not isinstance(subsystem_doc, Mapping):
            raise ManifestError("test.subsystem must be an object")
        _unknown(subsystem_doc, _SUBSYSTEM_FIELDS, "test.subsystem")
        _required(subsystem_doc, _SUBSYSTEM_FIELDS, "test.subsystem")
        subsystem_name = _string(subsystem_doc["name"], "test.subsystem.name")
        subsystem_tests = subsystem_doc["tests"]
        if (not isinstance(subsystem_tests, list) or not subsystem_tests
                or any(not isinstance(item, Mapping) for item in subsystem_tests)):
            raise ManifestError("test.subsystem.tests must be a non-empty list of objects")
        parsed_tests: list[SubsystemTestSpec] = []
        for index, item in enumerate(subsystem_tests):
            field = f"test.subsystem.tests[{index}]"
            _unknown(item, _SUBSYSTEM_TEST_FIELDS, field)
            _required(item, {"name"}, field)
            test_name = _string(item["name"], f"{field}.name")
            kind_declared = "kind" in item
            test_kind = item.get("kind", "native")
            if not isinstance(test_kind, str) or test_kind not in {
                    "native", "kselftest", "kunit", "tool"}:
                raise ManifestError(
                    f"{field}.kind must be native, kselftest, kunit, or tool")
            test_provider = item.get("provider")
            if test_provider is not None:
                test_provider = _string(test_provider, f"{field}.provider")
                if re.fullmatch(r"[A-Za-z0-9_.+-]+", test_provider) is None:
                    raise ManifestError(f"{field}.provider is unsafe")
            test_required = item.get("required", True)
            if not isinstance(test_required, bool):
                raise ManifestError(f"{field}.required must be a boolean")
            test_module = item.get("module")
            test_args = item.get("args", [])
            if (not isinstance(test_args, list)
                    or any(not isinstance(value, str) for value in test_args)):
                raise ManifestError(f"{field}.args must be a list of strings")
            args_declared = "args" in item
            test_success = item.get("success_pattern")
            if test_success is not None:
                test_success = _string(test_success, f"{field}.success_pattern")
                try:
                    re.compile(test_success)
                except re.error as exc:
                    raise ManifestError(
                        f"{field}.success_pattern is invalid") from exc

            test_executable = None
            if "executable" in item:
                test_executable = _inside_repo(
                    item["executable"], root, f"{field}.executable")
                if (not test_executable.exists()
                        and not Path(str(item["executable"])).is_absolute()):
                    local = (base / str(item["executable"])).resolve()
                    try:
                        local.relative_to(root)
                    except ValueError:
                        pass
                    else:
                        test_executable = local

            declared_modules = set(qemu.kernel_modules)
            if fixture is not None:
                declared_modules.update(fixture.kernel_modules)
                declared_modules.update(
                    Path(path).stem for path in fixture.module_sources)
            try:
                resolved_provider = provider_registry.resolve_test(
                    test_provider,
                    subsystem=subsystem_name,
                    declared_kind=test_kind if kind_declared else None,
                    declared_executable=test_executable,
                    declared_module=test_module,
                    declared_args=tuple(test_args),
                    args_declared=args_declared,
                    declared_success_pattern=test_success,
                    success_declared="success_pattern" in item,
                    available_kernel_modules=declared_modules,
                    field=field,
                )
            except ProviderCatalogError as exc:
                raise ManifestError(str(exc)) from exc
            if resolved_provider is not None:
                test_kind = resolved_provider.kind
                test_executable = resolved_provider.executable
                test_module = resolved_provider.module
                test_args = list(resolved_provider.args)
                test_success = resolved_provider.success_pattern

            if test_kind == "kunit":
                if "executable" in item:
                    raise ManifestError(
                        f"{field}.kunit must not declare executable")
                test_module = _string(test_module, f"{field}.module")
                if re.fullmatch(r"[A-Za-z0-9_.+-]+", test_module) is None:
                    raise ManifestError(f"{field}.module is unsafe")
                if test_module not in declared_modules:
                    raise ManifestError(
                        f"{field}.module must be declared in runtime kernel_modules")
                test_executable = None
            elif test_executable is None:
                if test_provider is None:
                    raise ManifestError(
                        f"{field} requires executable for {test_kind} test")
                # Provider test the catalog could not resolve (empty catalog
                # at this root): deferred — the pipeline resolves or skips.
            if test_kind == "kunit" and test_success is None:
                raise ManifestError(
                    f"{field}.success_pattern is required for kunit test")
            raw_assets = item.get("assets", [])
            if (not isinstance(raw_assets, list)
                    or any(not isinstance(value, str) or not value.strip()
                           for value in raw_assets)):
                raise ManifestError(f"{field}.assets must be a list of paths")
            assets = tuple(_inside_repo(value, root, f"{field}.assets")
                           for value in raw_assets)
            parsed_tests.append(SubsystemTestSpec(
                name=test_name, executable=test_executable, kind=test_kind,
                module=test_module, args=tuple(test_args),
                success_pattern=test_success, assets=assets,
                provider=test_provider, required=test_required))
        subsystem = SubsystemTestSuite(subsystem_name, tuple(parsed_tests))
    if subsystem is not None:
        # Subsystem tests replace the native exerciser: no dual dispatch.
        executable = None
    coverage = _parse_coverage(test_doc.get("coverage"))
    test = TestSpec(executable, tuple(args), tuple(dict(item) for item in actions),
                    success_pattern, subsystem, coverage)

    trace_doc = document["trace"]
    if not isinstance(trace_doc, Mapping):
        raise ManifestError("trace must be an object")
    _unknown(trace_doc, _TRACE_FIELDS, "trace")
    _required(trace_doc, {"fields"}, "trace")
    fields = trace_doc["fields"]
    if not isinstance(fields, list) or not fields or any(item not in _TRACE_EVENT_FIELDS for item in fields):
        raise ManifestError("trace.fields contains invalid trace field")
    if len(set(fields)) != len(fields):
        raise ManifestError("trace.fields must not contain duplicates")
    required_trace = {"phase", "function", "kind", "width_bits", "address", "value", "sequence"}
    if not required_trace.issubset(fields):
        raise ManifestError("trace.fields missing required trace field")
    trace = TraceSpec(
        tuple(fields),
        None if trace_doc.get("value_mask") is None else _parse_mask(trace_doc["value_mask"], "trace.value_mask"),
        None if trace_doc.get("address_mask") is None else _parse_mask(trace_doc["address_mask"], "trace.address_mask"),
        trace_doc.get("normalize_function", True),
    )
    if not isinstance(trace.normalize_function, bool):
        raise ManifestError("trace.normalize_function must be boolean")
    instrument = trace_doc.get("instrument", False)
    if not isinstance(instrument, bool):
        raise ManifestError("trace.instrument must be boolean")
    exercised_calls = trace_doc.get("exercised_calls", [])
    if not isinstance(exercised_calls, list) or any(not isinstance(item, str) or not item.strip() for item in exercised_calls):
        raise ManifestError("trace.exercised_calls must be a list of non-empty strings")
    trace = TraceSpec(trace.fields, trace.value_mask, trace.address_mask,
                      trace.normalize_function, instrument, tuple(exercised_calls))

    limits_doc = document["limits"]
    if not isinstance(limits_doc, Mapping):
        raise ManifestError("limits must be an object")
    _unknown(limits_doc, _LIMIT_FIELDS, "limits")
    _required(limits_doc, {"compile", "runtime", "trace"}, "limits")
    values = {field: _integer(limits_doc[field], f"limits.{field}", minimum=1) for field in ("compile", "runtime", "trace")}
    if "total" in limits_doc:
        values["total"] = _integer(limits_doc["total"], "limits.total", minimum=1)
    limits = IterationLimits(**values)
    return ExperimentManifest(schema, name, source, compile_spec, runtime, test, trace, limits, root, dict(document))


def _json_value(value: Any) -> Any:
    if isinstance(value, ExperimentManifest):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Encode JSON with stable ordering and no insignificant whitespace."""
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_digest(value: Any) -> str:
    if isinstance(value, ExperimentManifest):
        document = value.raw_document if value.raw_document is not None else value.to_dict()
    else:
        document = value
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


canonical_manifest_json = canonical_json
canonical_digest = manifest_digest


def load_manifest(path: str | os.PathLike[str] | Path, *, repo_root: str | os.PathLike[str] | Path | None = None) -> ExperimentManifest:
    manifest_path = Path(path).resolve()
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    root = Path(repo_root).resolve() if repo_root is not None else _repo_root(manifest_path.parent)
    manifest = validate_manifest(document, repo_root=root, manifest_dir=manifest_path.parent)
    return ExperimentManifest(
        manifest.schema, manifest.name, manifest.source, manifest.compile,
        manifest.runtime, manifest.test, manifest.trace, manifest.limits,
        manifest.repo_root, manifest.raw_document, manifest_path,
    )


def validate_trace_fields(fields: Any) -> tuple[str, ...]:
    """Validate a trace field declaration independently of a full manifest."""
    if not isinstance(fields, list) or any(field not in _TRACE_EVENT_FIELDS for field in fields):
        raise ManifestError("trace.fields contains invalid trace field")
    return tuple(fields)
