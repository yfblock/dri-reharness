"""Frozen dataclasses describing one validated experiment manifest."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
        # Lazy: serialize.py validates via validate.py, which needs this module.
        from .serialize import manifest_digest
        return manifest_digest(self.raw_document if self.raw_document is not None else self)

