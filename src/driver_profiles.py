"""Bus-neutral driver profile matching and runtime planning.

Profiles describe what evidence is required to select a runtime adapter.  The
translation and experiment runners consume the resulting data contract and do
not need to know individual driver names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class ProfileMatchError(ValueError):
    """Raised when evidence selects more than one profile equally."""


@dataclass(frozen=True)
class MatchResult:
    profile_id: str
    bus: str
    reason: str
    score: int


@dataclass(frozen=True)
class ProfilePlan:
    profile_id: str
    bus: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    runtime_adapter: str | None
    fixture: Mapping[str, Any]


@dataclass(frozen=True)
class ProfileResolution:
    profile: "DriverTypeProfile | None"
    match: MatchResult | None = None
    plan: ProfilePlan | None = None
    missing_capabilities: tuple[str, ...] = ()


class DriverTypeProfile(Protocol):
    profile_id: str
    bus: str

    def match(self, evidence: Mapping[str, Any]) -> MatchResult | None:
        ...

    def plan(self, evidence: Mapping[str, Any]) -> ProfilePlan:
        ...


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _binding_keys(evidence: Mapping[str, Any]) -> set[str]:
    raw = evidence.get("bindings")
    keys: set[str] = set()
    if isinstance(raw, Mapping):
        keys.update(str(key) for key in raw)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, Mapping):
                for field in ("callback", "binding", "name", "table"):
                    value = item.get(field)
                    if isinstance(value, str) and value:
                        keys.add(value)
            elif isinstance(item, str):
                keys.add(item)

    # Extractor metadata commonly nests callback bindings below this field.
    metadata = _mapping(evidence.get("metadata"))
    callback_analysis = _mapping(metadata.get("callback_binding_analysis"))
    nested = callback_analysis.get("bindings")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, Mapping):
                for field in ("callback", "binding", "name", "table"):
                    value = item.get(field)
                    if isinstance(value, str) and value:
                        keys.add(value)

    return keys


def _resource_keys(evidence: Mapping[str, Any]) -> set[str]:
    raw = evidence.get("resources")
    keys: set[str] = set()
    if isinstance(raw, Mapping):
        keys.update(str(key) for key in raw)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            for field in ("type", "name", "kind", "resource"):
                value = item.get(field)
                if isinstance(value, str) and value:
                    keys.add(value)

    return keys


def _evidence_has(evidence: Mapping[str, Any], *names: str) -> bool:
    bindings = _binding_keys(evidence)
    resources = _resource_keys(evidence)
    identity = evidence.get("identity")
    identity_keys = set(_mapping(identity))
    for name in names:
        if name in bindings or name in resources or name in identity_keys:
            return True
        if name in evidence:
            return True
    return False


@dataclass(frozen=True)
class _GenericBusProfile:
    profile_id: str
    bus: str
    callback: str
    resource: str
    fixture_kind: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...] = ("subsystem", "trace")

    def match(self, evidence: Mapping[str, Any]) -> MatchResult | None:
        callback_present = _evidence_has(evidence, self.callback)
        resource_present = _evidence_has(evidence, self.resource)
        bus_present = evidence.get("bus") == self.bus
        if not callback_present and not resource_present and not bus_present:
            return None

        # A callback is the strongest signal; a resource or explicit bus can
        # supplement evidence from partial extraction results.
        score = (10 if callback_present else 0) + (5 if resource_present else 0)
        score += 3 if bus_present else 0
        if callback_present and resource_present:
            reason = f"{self.bus} callback and {self._resource_label()} evidence"
        elif callback_present:
            reason = f"{self.bus} callback evidence"
        elif resource_present:
            reason = f"{self.bus} resource evidence"
        else:
            reason = f"explicit {self.bus} bus evidence"
        return MatchResult(self.profile_id, self.bus, reason, score)

    def _resource_label(self) -> str:
        prefix = f"{self.bus}_"
        label = self.resource[len(prefix):] if self.resource.startswith(prefix) else self.resource
        return label.replace("_", " ")

    def plan(self, evidence: Mapping[str, Any]) -> ProfilePlan:
        return ProfilePlan(
            profile_id=self.profile_id,
            bus=self.bus,
            required_capabilities=self.required_capabilities,
            optional_capabilities=self.optional_capabilities,
            runtime_adapter="qemu-profile",
            fixture={"kind": self.fixture_kind, "config": {}},
        )


class ProfileRegistry:
    """Deterministic registry for evidence-backed driver type profiles."""

    def __init__(self, profiles: tuple[DriverTypeProfile, ...] = ()) -> None:
        self._profiles: list[DriverTypeProfile] = list(profiles)

    def register(self, profile: DriverTypeProfile) -> None:
        if any(item.profile_id == profile.profile_id for item in self._profiles):
            raise ValueError(f"duplicate driver profile: {profile.profile_id}")
        self._profiles.append(profile)

    @property
    def profiles(self) -> tuple[DriverTypeProfile, ...]:
        return tuple(self._profiles)

    def match(self, evidence: Mapping[str, Any]) -> MatchResult:
        if not isinstance(evidence, Mapping):
            raise TypeError("driver profile evidence must be a mapping")
        matches = [item for profile in self._profiles
                   if (item := profile.match(evidence)) is not None]
        if not matches:
            raise ProfileMatchError("no driver profile matches the evidence")
        highest = max(item.score for item in matches)
        winners = [item for item in matches if item.score == highest]
        if len(winners) != 1:
            ids = ", ".join(sorted(item.profile_id for item in winners))
            raise ProfileMatchError(f"ambiguous driver profiles: {ids}")
        return winners[0]

    def _profile_by_id(self, profile_id: str) -> DriverTypeProfile:
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return profile
        raise ProfileMatchError(f"unknown driver profile: {profile_id}")

    def resolve(self, evidence: Mapping[str, Any], *, requested: str | None = None,
                allow_unknown: bool = True) -> ProfileResolution:
        if requested is not None:
            profile = self._profile_by_id(requested)
            result = profile.match(evidence)
            if result is None:
                raise ProfileMatchError(
                    f"requested profile {requested} does not match the evidence")
        else:
            try:
                result = self.match(evidence)
            except ProfileMatchError as exc:
                if not allow_unknown or "no driver profile" not in str(exc):
                    raise
                return ProfileResolution(
                    profile=None, missing_capabilities=("runtime_profile",))
            profile = self._profile_by_id(result.profile_id)

        return ProfileResolution(profile=profile, match=result,
                                 plan=profile.plan(evidence))


def build_default_registry() -> ProfileRegistry:
    """Return a fresh registry containing the initial supported bus families."""
    return ProfileRegistry((
        _GenericBusProfile(
            profile_id="platform-generic", bus="platform",
            callback="platform_driver.probe", resource="platform_device",
            fixture_kind="qemu-platform",
            required_capabilities=("registration", "probe", "unload")),
        _GenericBusProfile(
            profile_id="pci-generic", bus="pci",
            callback="pci_driver.probe", resource="pci_device",
            fixture_kind="qemu-pci",
            required_capabilities=("registration", "probe", "unload")),
        _GenericBusProfile(
            profile_id="i2c-generic", bus="i2c",
            callback="i2c_driver.probe", resource="i2c_client",
            fixture_kind="qemu-i2c",
            required_capabilities=("registration", "probe", "transaction", "unload")),
        _GenericBusProfile(
            profile_id="spi-generic", bus="spi",
            callback="spi_driver.probe", resource="spi_device",
            fixture_kind="qemu-spi",
            required_capabilities=("registration", "probe", "transfer", "unload")),
    ))


__all__ = [
    "DriverTypeProfile", "MatchResult", "ProfileMatchError", "ProfilePlan",
    "ProfileRegistry", "ProfileResolution", "build_default_registry",
]
