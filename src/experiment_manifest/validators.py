"""Field-name contracts, scalar validators, and repository path rules."""
from __future__ import annotations

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

