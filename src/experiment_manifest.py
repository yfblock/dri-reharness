"""Typed, repository-scoped experiment manifests.

The manifest is deliberately small and data-only.  Keeping validation here
means orchestration code can consume a trusted object instead of repeatedly
interpreting loosely typed JSON dictionaries.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


class ManifestError(ValueError):
    """Raised when an experiment manifest is malformed or unsafe."""


ManifestValidationError = ManifestError


_TOP_FIELDS = {"schema", "name", "source", "compile", "runtime", "test", "trace", "limits"}
_SOURCE_FIELDS = {"path", "sha256"}
_COMPILE_FIELDS = {"backend", "language", "context"}
_RUNTIME_FIELDS = {
    "adapter", "machine", "device", "bus", "module", "timeout_seconds",
    "probe_pattern", "registrar", "qemu_args",
}
_TEST_FIELDS = {"executable", "args", "actions", "success_pattern"}
_TRACE_FIELDS = {"fields", "value_mask", "address_mask", "normalize_function", "instrument"}
_LIMIT_FIELDS = {"compile", "runtime", "trace", "total"}
_TRACE_EVENT_FIELDS = {
    "phase", "function", "kind", "width_bits", "address", "value", "sequence", "source_op_id",
}
_TRACE_KINDS = {
    "read", "write", "rmw", "readmodifywrite", "read_modify_write", "r", "w", "return", "error",
}


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
class RuntimeSpec:
    adapter: str
    machine: str
    device: str
    bus: str
    module: str
    timeout_seconds: int
    probe_pattern: str | None = None
    registrar: str | None = None
    qemu_args: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "adapter": self.adapter, "machine": self.machine, "device": self.device,
            "bus": self.bus, "module": self.module, "timeout_seconds": self.timeout_seconds,
        }
        if self.probe_pattern is not None:
            result["probe_pattern"] = self.probe_pattern
        if self.registrar is not None:
            result["registrar"] = self.registrar
        if self.qemu_args:
            result["qemu_args"] = list(self.qemu_args)
        return result


@dataclass(frozen=True)
class TestSpec:
    executable: Path
    args: tuple[str, ...] = ()
    actions: tuple[Mapping[str, Any], ...] = ()
    success_pattern: str | None = None

    def to_dict(self, *, root: Path | None = None) -> dict[str, Any]:
        executable: Path | str = self.executable
        if root is not None:
            try:
                executable = self.executable.resolve().relative_to(root.resolve())
            except ValueError:
                pass
        result: dict[str, Any] = {"executable": str(executable), "args": list(self.args)}
        if self.actions:
            result["actions"] = [dict(action) for action in self.actions]
        if self.success_pattern is not None:
            result["success_pattern"] = self.success_pattern
        return result


@dataclass(frozen=True)
class TraceSpec:
    fields: tuple[str, ...]
    value_mask: int | None = None
    address_mask: int | None = None
    normalize_function: bool = True
    instrument: bool = False

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

    def to_dict(self) -> dict[str, Any]:
        root = self.repo_root
        return {
            "schema": self.schema,
            "name": self.name,
            "source": self.source.to_dict(root=root),
            "compile": self.compile.to_dict(),
            "runtime": self.runtime.to_dict(),
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


def validate_manifest(document: Mapping[str, Any], *, repo_root: str | os.PathLike[str] | Path | None = None,
                      manifest_dir: str | os.PathLike[str] | Path | None = None) -> ExperimentManifest:
    if not isinstance(document, Mapping):
        raise ManifestError("manifest must be a JSON object")
    _unknown(document, _TOP_FIELDS, "manifest")
    _required(document, _TOP_FIELDS, "manifest")
    schema = _integer(document["schema"], "schema", minimum=1)
    if schema != 1:
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
    _required(runtime_doc, {"adapter", "machine", "device", "bus", "module", "timeout_seconds"}, "runtime")
    qemu_args = runtime_doc.get("qemu_args", [])
    if not isinstance(qemu_args, list) or any(not isinstance(item, str) for item in qemu_args):
        raise ManifestError("runtime.qemu_args must be a list of strings")
    runtime = RuntimeSpec(
        adapter=_string(runtime_doc["adapter"], "runtime.adapter"),
        machine=_string(runtime_doc["machine"], "runtime.machine"),
        device=_string(runtime_doc["device"], "runtime.device"),
        bus=_string(runtime_doc["bus"], "runtime.bus"),
        module=_string(runtime_doc["module"], "runtime.module"),
        timeout_seconds=_integer(runtime_doc["timeout_seconds"], "runtime.timeout_seconds", minimum=1),
        probe_pattern=None if runtime_doc.get("probe_pattern") is None else _string(runtime_doc["probe_pattern"], "runtime.probe_pattern"),
        registrar=None if runtime_doc.get("registrar") is None else _string(runtime_doc["registrar"], "runtime.registrar"),
        qemu_args=tuple(qemu_args),
    )

    test_doc = document["test"]
    if not isinstance(test_doc, Mapping):
        raise ManifestError("test must be an object")
    _unknown(test_doc, _TEST_FIELDS, "test")
    _required(test_doc, {"executable"}, "test")
    args = test_doc.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ManifestError("test.args must be a list of strings")
    actions = test_doc.get("actions", [])
    if not isinstance(actions, list) or any(not isinstance(item, Mapping) for item in actions):
        raise ManifestError("test.actions must be a list of objects")
    executable = _inside_repo(test_doc["executable"], root, "test.executable")
    success_pattern = test_doc.get("success_pattern")
    if success_pattern is not None:
        success_pattern = _string(success_pattern, "test.success_pattern")
    test = TestSpec(executable, tuple(args), tuple(dict(item) for item in actions), success_pattern)

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
    trace = TraceSpec(trace.fields, trace.value_mask, trace.address_mask,
                      trace.normalize_function, instrument)

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
    return validate_manifest(document, repo_root=root, manifest_dir=manifest_path.parent)


def validate_trace_fields(fields: Any) -> tuple[str, ...]:
    """Validate a trace field declaration independently of a full manifest."""
    if not isinstance(fields, list) or any(field not in _TRACE_EVENT_FIELDS for field in fields):
        raise ManifestError("trace.fields contains invalid trace field")
    return tuple(fields)
