"""Subsystem provider catalog: maps provider ids to test executables.

A manifest test item may reference a provider id instead of spelling out the
executable, module, and success pattern.  ``resolve_test`` fills those in from
``benchmarks/subsystem-providers.json`` and validates the request (subsystem
coverage, kind agreement, required kernel modules).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = Path("benchmarks/subsystem-providers.json")

_PROVIDER_FIELDS = frozenset({
    "id", "kind", "subsystems", "executable", "module", "args",
    "default_success_pattern", "required_kernel_modules",
})
_ALLOWED_KINDS = frozenset({"native", "kselftest", "kunit", "tool"})


class ProviderCatalogError(ValueError):
    """Raised when the subsystem provider catalog is malformed."""


@dataclass(frozen=True)
class ProviderEntry:
    id: str
    kind: str
    subsystems: tuple[str, ...]
    executable: str | None = None
    module: str | None = None
    args: tuple[str, ...] = ()
    default_success_pattern: str | None = None
    required_kernel_modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedProvider:
    kind: str
    executable: Path | None = None
    module: str | None = None
    args: tuple[str, ...] = ()
    success_pattern: str | None = None


class ProviderCatalog:
    """Registry of subsystem test providers."""

    def __init__(self, entries: Iterable[ProviderEntry],
                 repo_root: Path) -> None:
        self._entries = {entry.id: entry for entry in entries}
        self._repo_root = repo_root

    @property
    def entries(self) -> tuple[ProviderEntry, ...]:
        return tuple(self._entries.values())

    def __bool__(self) -> bool:
        return bool(self._entries)

    def resolve_test(self, provider_id: str | None, *, subsystem: str,
                     declared_kind: str | None = None,
                     declared_executable: Any = None,
                     declared_module: Any = None,
                     declared_args: Any = (),
                     args_declared: bool = False,
                     declared_success_pattern: str | None = None,
                     success_declared: bool = False,
                     available_kernel_modules: Iterable[str] = (),
                     field: str = "test") -> ResolvedProvider | None:
        """Resolve a provider reference into concrete test parameters.

        Returns ``None`` when no provider is requested or the catalog is
        empty — the manifest's declared fields then stand as-is.
        """
        if provider_id is None:
            return None
        entry = self._entries.get(provider_id)
        if entry is None:
            if not self._entries:
                return None  # no catalog: pass-through (extensibility)
            raise ProviderCatalogError(
                f"{field}.provider {provider_id!r} is not in the provider catalog")
        if subsystem not in entry.subsystems:
            raise ProviderCatalogError(
                f"{field}.provider {provider_id!r} does not serve subsystem "
                f"{subsystem!r} (serves: {', '.join(entry.subsystems)})")
        if declared_kind is not None and declared_kind != entry.kind:
            raise ProviderCatalogError(
                f"{field}.kind {declared_kind!r} conflicts with provider "
                f"{provider_id!r} kind {entry.kind!r}")
        missing = [m for m in entry.required_kernel_modules
                   if m not in set(available_kernel_modules)]
        if missing:
            raise ProviderCatalogError(
                f"{field}.provider {provider_id!r} requires kernel module(s) "
                f"{', '.join(missing)} not declared in runtime kernel_modules")
        executable = ((self._repo_root / entry.executable).resolve()
                      if entry.executable else None)
        module = entry.module or (declared_module if declared_module else None)
        args = tuple(declared_args) if args_declared else entry.args
        success = entry.default_success_pattern
        if success is None and success_declared:
            success = declared_success_pattern
        return ResolvedProvider(kind=entry.kind, executable=executable,
                                module=module, args=args,
                                success_pattern=success)


def load_provider_catalog(repo_root: Path) -> ProviderCatalog:
    """Load the provider catalog from benchmarks/subsystem-providers.json.

    A root without a catalog yields an empty registry: provider references
    pass through with their declared fields (extensibility for out-of-tree
    experiment roots).
    """
    root = Path(repo_root)
    path = root / _CATALOG_PATH
    if not path.is_file():
        return ProviderCatalog((), root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderCatalogError(f"cannot read provider catalog: {exc}") from exc
    if not isinstance(document, dict):
        raise ProviderCatalogError("provider catalog must be an object")
    providers = document.get("providers")
    if not isinstance(providers, list):
        raise ProviderCatalogError(
            "provider catalog must contain a providers array")

    entries: list[ProviderEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(providers):
        where = f"providers[{index}]"
        if not isinstance(item, dict):
            raise ProviderCatalogError(f"{where} must be an object")
        unknown = sorted(set(item) - _PROVIDER_FIELDS)
        if unknown:
            raise ProviderCatalogError(
                f"{where} declares unknown field(s): {', '.join(unknown)}")
        provider_id = item.get("id")
        kind = item.get("kind")
        subsystems = item.get("subsystems")
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderCatalogError(f"{where}.id must be a non-empty string")
        if provider_id in seen:
            raise ProviderCatalogError(f"duplicate provider id: {provider_id}")
        seen.add(provider_id)
        if kind not in _ALLOWED_KINDS:
            raise ProviderCatalogError(
                f"{where}.kind must be one of {sorted(_ALLOWED_KINDS)}")
        if (not isinstance(subsystems, list) or not subsystems
                or any(not isinstance(s, str) or not s for s in subsystems)):
            raise ProviderCatalogError(
                f"{where}.subsystems must be a non-empty list of strings")
        executable = item.get("executable")
        if executable is not None and not isinstance(executable, str):
            raise ProviderCatalogError(f"{where}.executable must be a string")
        module = item.get("module")
        if module is not None and not isinstance(module, str):
            raise ProviderCatalogError(f"{where}.module must be a string")
        args = item.get("args", [])
        if not isinstance(args, list) or any(
                not isinstance(a, str) for a in args):
            raise ProviderCatalogError(f"{where}.args must be a list of strings")
        success = item.get("default_success_pattern")
        if success is not None and not isinstance(success, str):
            raise ProviderCatalogError(
                f"{where}.default_success_pattern must be a string")
        modules = item.get("required_kernel_modules", [])
        if not isinstance(modules, list) or any(
                not isinstance(m, str) or not m for m in modules):
            raise ProviderCatalogError(
                f"{where}.required_kernel_modules must be a list of strings")
        entries.append(ProviderEntry(
            id=provider_id, kind=kind, subsystems=tuple(subsystems),
            executable=executable, module=module, args=tuple(args),
            default_success_pattern=success,
            required_kernel_modules=tuple(modules)))
    return ProviderCatalog(entries, root)


__all__ = ["ProviderCatalog", "ProviderCatalogError", "ProviderEntry",
           "ResolvedProvider", "load_provider_catalog"]
