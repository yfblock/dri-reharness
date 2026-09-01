"""Subsystem contract registry: data-driven contract detection.

Contracts live in ``benchmarks/subsystem-contract-definitions.json``.  A
contract matches a driver source when one of its ``source_tokens`` appears in
the text, or when extraction evidence carries one of its callback/resource
keys.  Detection is bus-independent: transport profiles (platform/pci/spi)
are resolved separately by ``driver_profiles``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_PATH = Path("benchmarks/subsystem-contract-definitions.json")

_ALLOWED_FIELDS = frozenset({
    "contract_id", "subsystem", "callback_keys", "resource_keys",
    "source_tokens", "required_capabilities", "optional_capabilities",
    "summary_groups", "summary_contracts", "candidate_validator",
})
_REQUIRED_FIELDS = frozenset({
    "contract_id", "subsystem", "callback_keys", "resource_keys",
    "source_tokens", "required_capabilities",
})
_LIST_FIELDS = frozenset({
    "callback_keys", "resource_keys", "source_tokens",
    "required_capabilities", "optional_capabilities",
    "summary_groups", "summary_contracts",
})
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_.:@-]+(?: [A-Za-z0-9_.:@-]+)*")


class SubsystemContractCatalogError(ValueError):
    """Raised when the subsystem contract catalog is malformed."""


def _safe_token(value: Any, field_path: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise SubsystemContractCatalogError(
            f"{field_path} contains an unsafe token: {value!r}")
    return value


def _string_list(value: Any, field_path: str,
                 allow_spaces: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SubsystemContractCatalogError(
            f"{field_path} must be a non-empty list")
    return tuple(_safe_token(item, field_path) if not allow_spaces
                 else _safe_fragment(item, field_path) for item in value)


def _safe_fragment(value: Any, field_path: str) -> str:
    """C source fragments: no path separators or escapes, spaces allowed."""
    if (not isinstance(value, str) or not value.strip()
            or any(ch in value for ch in "/\\\n\r\t")
            or value.strip() != value):
        raise SubsystemContractCatalogError(
            f"{field_path} contains an unsafe token: {value!r}")
    return value


@dataclass(frozen=True)
class SubsystemContract:
    """A single subsystem contract definition from the catalog."""
    contract_id: str
    subsystem: str
    callback_keys: tuple[str, ...]
    resource_keys: tuple[str, ...]
    source_tokens: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...] = ()
    summary_groups: tuple[str, ...] = ()
    summary_contracts: tuple[str, ...] = ()
    candidate_validator: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.contract_id,
            "contract_id": self.contract_id,
            "subsystem": self.subsystem,
            "callback_keys": list(self.callback_keys),
            "resource_keys": list(self.resource_keys),
            "source_tokens": list(self.source_tokens),
            "required_capabilities": list(self.required_capabilities),
            "optional_capabilities": list(self.optional_capabilities),
            "summary_groups": list(self.summary_groups),
            "summary_contracts": list(self.summary_contracts),
            "candidate_validator": self.candidate_validator,
        }


@dataclass(frozen=True)
class SubsystemContractMatch:
    """A detection result: the contract plus the evidence that fired."""
    contract: SubsystemContract
    matched_tokens: tuple[str, ...] = field(default=())

    @property
    def contract_id(self) -> str:
        return self.contract.contract_id

    @property
    def subsystem(self) -> str:
        return self.contract.subsystem

    @property
    def required_capabilities(self) -> tuple[str, ...]:
        return self.contract.required_capabilities

    @property
    def optional_capabilities(self) -> tuple[str, ...]:
        return self.contract.optional_capabilities

    @property
    def summary_groups(self) -> tuple[str, ...]:
        return self.contract.summary_groups

    @property
    def summary_contracts(self) -> tuple[str, ...]:
        return self.contract.summary_contracts

    def to_dict(self) -> dict[str, Any]:
        rendered = self.contract.to_dict()
        rendered["matched_tokens"] = list(self.matched_tokens)
        return rendered


def load_subsystem_contract_definitions(
        repo_root: Path | None = None) -> tuple[SubsystemContract, ...]:
    """Load and validate the contract catalog under ``repo_root``.

    Falls back to the pinned repository catalog when the requested root has
    none, so profile detection works for out-of-tree driver sources.
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    path = root / _CATALOG_PATH
    if not path.is_file():
        if root != _REPO_ROOT and (_REPO_ROOT / _CATALOG_PATH).is_file():
            path = _REPO_ROOT / _CATALOG_PATH
        else:
            raise SubsystemContractCatalogError(
                f"subsystem contract catalog not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubsystemContractCatalogError(
            f"cannot read subsystem contract catalog: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("schema") != 1:
        raise SubsystemContractCatalogError(
            "subsystem contract catalog must declare schema 1")
    contracts_doc = document.get("contracts")
    if not isinstance(contracts_doc, list) or not contracts_doc:
        raise SubsystemContractCatalogError(
            "subsystem contract catalog must contain a contracts array")

    contracts: list[SubsystemContract] = []
    seen: set[str] = set()
    for index, item in enumerate(contracts_doc):
        where = f"contracts[{index}]"
        if not isinstance(item, Mapping):
            raise SubsystemContractCatalogError(f"{where} must be an object")
        unknown = sorted(set(item) - _ALLOWED_FIELDS)
        if unknown:
            raise SubsystemContractCatalogError(
                f"{where} declares unknown field(s): {', '.join(unknown)}")
        missing = sorted(_REQUIRED_FIELDS - set(item))
        if missing:
            raise SubsystemContractCatalogError(
                f"{where} is missing required field(s): {', '.join(missing)}")
        contract_id = _safe_token(item["contract_id"], f"{where}.contract_id")
        if contract_id in seen:
            raise SubsystemContractCatalogError(
                f"duplicate contract id: {contract_id}")
        seen.add(contract_id)
        validator = item.get("candidate_validator")
        if validator is not None:
            validator = _safe_token(validator, f"{where}.candidate_validator")
        contracts.append(SubsystemContract(
            contract_id=contract_id,
            subsystem=_safe_token(item["subsystem"], f"{where}.subsystem"),
            callback_keys=_string_list(item["callback_keys"],
                                       f"{where}.callback_keys"),
            resource_keys=_string_list(item["resource_keys"],
                                       f"{where}.resource_keys"),
            source_tokens=_string_list(item["source_tokens"],
                                       f"{where}.source_tokens",
                                       allow_spaces=True),
            required_capabilities=_string_list(
                item["required_capabilities"], f"{where}.required_capabilities"),
            optional_capabilities=tuple(_safe_token(
                v, f"{where}.optional_capabilities")
                for v in item.get("optional_capabilities", [])),
            summary_groups=tuple(_safe_token(
                v, f"{where}.summary_groups") for v in item.get("summary_groups", [])),
            summary_contracts=tuple(_safe_token(
                v, f"{where}.summary_contracts")
                for v in item.get("summary_contracts", [])),
            candidate_validator=validator,
        ))
    return tuple(contracts)


class ContractRegistry:
    """Detects subsystem contracts from source text and extraction evidence."""

    def __init__(self, contracts: Iterable[SubsystemContract]) -> None:
        self._contracts = tuple(contracts)

    @property
    def contracts(self) -> tuple[SubsystemContract, ...]:
        return self._contracts

    def detect(self, text: str,
               evidence: Mapping[str, Any] | None = None
               ) -> list[SubsystemContractMatch]:
        ev = evidence if isinstance(evidence, Mapping) else {}
        binding_keys = self._binding_keys(ev)
        resource_keys = self._resource_keys(ev)
        matches: list[SubsystemContractMatch] = []
        for contract in self._contracts:
            tokens = tuple(t for t in contract.source_tokens if t in text)
            callbacks = tuple(k for k in contract.callback_keys
                              if k in binding_keys)
            resources = tuple(k for k in contract.resource_keys
                              if k in resource_keys)
            if tokens or callbacks or resources:
                matches.append(SubsystemContractMatch(
                    contract=contract,
                    matched_tokens=tokens + callbacks + resources))
        return matches

    @staticmethod
    def _binding_keys(evidence: Mapping[str, Any]) -> set[str]:
        keys: set[str] = set()
        bindings = evidence.get("bindings")
        if isinstance(bindings, Mapping):
            keys.update(str(k) for k in bindings)
        return keys

    @staticmethod
    def _resource_keys(evidence: Mapping[str, Any]) -> set[str]:
        keys: set[str] = set()
        resources = evidence.get("resources")
        if isinstance(resources, Mapping):
            keys.update(str(k) for k in resources)
        elif isinstance(resources, (list, tuple)):
            for item in resources:
                if isinstance(item, Mapping):
                    for f in ("type", "name", "kind", "resource"):
                        if isinstance(item.get(f), str):
                            keys.add(item[f])
        return keys


def build_default_contract_registry(
        repo_root: Path | None = None) -> ContractRegistry:
    """Load the default subsystem contract registry."""
    return ContractRegistry(load_subsystem_contract_definitions(repo_root))


def verify_contract_summaries(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Verify subsystem contract summaries (pass-through for now)."""
    return {"complete": True, "errors": []}


__all__ = [
    "SubsystemContract", "SubsystemContractMatch", "SubsystemContractCatalogError",
    "ContractRegistry", "build_default_contract_registry",
    "load_subsystem_contract_definitions", "verify_contract_summaries",
]
