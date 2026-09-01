"""Bus-neutral driver profile matching and runtime planning.

Profiles are declarative: ``benchmarks/driver-profile-definitions.json``
defines bus families (callback/resource tokens, identity patterns, manifest
templates, registration contracts).  Plugins can register additional
profiles at runtime.  The translation and experiment runners consume the
resulting data contract and do not need to know individual driver names.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFINITIONS_PATH = Path("benchmarks/driver-profile-definitions.json")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]+")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_ALLOWED_PLACEHOLDERS = frozenset({"driver_name"})

_DECLARATIVE_FIELDS = frozenset({
    "profile_id", "bus", "callback", "resource", "fixture_kind",
    "required_capabilities", "optional_capabilities", "manifest_template",
    "callback_tokens", "resource_tokens", "identity_patterns",
    "device_id_patterns", "required_fixture_fields", "registration_contract",
    "plan_templates", "matrix_required",
})
_DECLARATIVE_REQUIRED = frozenset({
    "profile_id", "bus", "callback", "resource", "fixture_kind",
    "required_capabilities",
})
_REGISTRATION_API_FIELDS = frozenset(
    {"name", "kind", "argument", "type", "table"})


class ProfileMatchError(ValueError):
    """Raised when evidence selects more than one profile equally."""


class ProfileCatalogError(ValueError):
    """Raised when the declarative profile catalog is malformed."""


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
    manifest_template: str | None = None
    required_fixture_fields: tuple[str, ...] = ()
    runtime_overrides: Mapping[str, Any] | None = None
    registration_contract: Mapping[str, Any] | None = None
    subsystem_contracts: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ProfileResolution:
    profile: "DriverTypeProfile | None"
    match: MatchResult | None = None
    plan: ProfilePlan | None = None
    missing_capabilities: tuple[str, ...] = ()

    def summary(self, reason: str = "") -> dict[str, Any]:
        if self.profile is None or self.match is None:
            return {"id": None, "reason": reason}
        return {
            "id": self.profile.profile_id,
            "bus": self.profile.bus,
            "matched_by": self.match.reason,
            "score": self.match.score,
            "reason": reason,
        }


class DriverTypeProfile(Protocol):
    profile_id: str
    bus: str

    def match(self, evidence: Mapping[str, Any]) -> MatchResult | None: ...

    def plan(self, evidence: Mapping[str, Any]) -> ProfilePlan: ...


# ── evidence helpers ──────────────────────────────────────────────────


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
                for f in ("callback", "binding", "name", "table"):
                    value = item.get(f)
                    if isinstance(value, str) and value:
                        keys.add(value)
            elif isinstance(item, str):
                keys.add(item)

    metadata = _mapping(evidence.get("metadata"))
    callback_analysis = _mapping(metadata.get("callback_binding_analysis"))
    nested = callback_analysis.get("bindings")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, Mapping):
                for f in ("callback", "binding", "name", "table"):
                    value = item.get(f)
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
            for f in ("type", "name", "kind", "resource"):
                value = item.get(f)
                if isinstance(value, str) and value:
                    keys.add(value)
    return keys


def _evidence_has(evidence: Mapping[str, Any], *names: str) -> bool:
    bindings = _binding_keys(evidence)
    resources = _resource_keys(evidence)
    identity = _mapping(evidence.get("identity"))
    identity_keys = set(identity)
    for name in names:
        if name in bindings or name in resources or name in identity_keys:
            return True
        if name in evidence:
            return True
    return False


def _render_placeholders(value: Any, identity: Mapping[str, Any]) -> Any:
    """Substitute {driver_name} placeholders from the extracted identity."""
    if isinstance(value, str):
        def sub(match: re.Match) -> str:
            name = match.group(1)
            return str(identity.get(name, ""))
        return _PLACEHOLDER.sub(sub, value)
    if isinstance(value, Mapping):
        return {key: _render_placeholders(item, identity)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        rendered = [_render_placeholders(item, identity) for item in value]
        return type(value)(rendered) if isinstance(value, tuple) else rendered
    return value


# ── declarative (data-driven) profiles ────────────────────────────────


def _check_placeholders(value: Any, where: str) -> None:
    if isinstance(value, str):
        for name in _PLACEHOLDER.findall(value):
            if name not in _ALLOWED_PLACEHOLDERS:
                raise ProfileCatalogError(
                    f"{where} uses unknown placeholder {{{name}}}")
    elif isinstance(value, Mapping):
        for item in value.values():
            _check_placeholders(item, where)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_placeholders(item, where)


def _validate_registration_contract(contract: Any, where: str) -> dict[str, Any]:
    if not isinstance(contract, Mapping):
        raise ProfileCatalogError(f"{where} must be an object")
    root_table = contract.get("root_table")
    if not isinstance(root_table, str) or not _SAFE_ID.fullmatch(root_table):
        raise ProfileCatalogError(f"{where}.root_table is unsafe: {root_table!r}")
    identity_field = contract.get("identity_field")
    if identity_field is not None and (
            not isinstance(identity_field, str)
            or not _SAFE_ID.fullmatch(identity_field)):
        raise ProfileCatalogError(
            f"{where}.identity_field is unsafe: {identity_field!r}")
    apis = contract.get("registration_apis", [])
    if not isinstance(apis, list):
        raise ProfileCatalogError(f"{where}.registration_apis must be a list")
    for index, api in enumerate(apis):
        if (not isinstance(api, Mapping)
                or not _REGISTRATION_API_FIELDS.issubset(api)):
            missing = sorted(_REGISTRATION_API_FIELDS - set(api if isinstance(api, Mapping) else {}))
            raise ProfileCatalogError(
                f"{where}.registration_apis[{index}] is missing field(s): "
                f"{', '.join(missing) if missing else 'not an object'}")
    tables = contract.get("tables", [])
    if not isinstance(tables, list):
        raise ProfileCatalogError(f"{where}.tables must be a list")
    rendered = dict(contract)
    rendered.setdefault("device_id_tables", [])
    if not isinstance(rendered["device_id_tables"], list):
        raise ProfileCatalogError(f"{where}.device_id_tables must be a list")
    return rendered


@dataclass(frozen=True)
class _DeclarativeProfile:
    """A bus profile loaded from driver-profile-definitions.json."""
    profile_id: str
    bus: str
    callback: str
    resource: str
    fixture_kind: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    manifest_template: str | None
    callback_tokens: tuple[str, ...]
    resource_tokens: tuple[str, ...]
    identity_patterns: tuple[str, ...]
    device_id_patterns: tuple[str, ...]
    required_fixture_fields: tuple[str, ...]
    registration_contract: Mapping[str, Any]
    plan_templates: Mapping[str, Any]
    matrix_required: bool = False

    # -- matching ------------------------------------------------------

    def _resource_label(self) -> str:
        prefix = f"{self.bus}_"
        label = (self.resource[len(prefix):]
                 if self.resource.startswith(prefix) else self.resource)
        return label.replace("_", " ")

    def match(self, evidence: Mapping[str, Any]) -> MatchResult | None:
        callback_present = _evidence_has(evidence, self.callback)
        resource_present = _evidence_has(evidence, self.resource)
        bus_present = evidence.get("bus") == self.bus
        if not callback_present and not resource_present and not bus_present:
            return None
        score = (10 if callback_present else 0) + (5 if resource_present else 0)
        score += 3 if bus_present else 0
        if callback_present and resource_present:
            reason = f"{self.bus} callback and {self._resource_label()} evidence"
        elif callback_present:
            reason = f"{self.bus} callback evidence"
        elif resource_present:
            reason = f"{self.bus} {self._resource_label()} evidence"
        else:
            reason = f"explicit {self.bus} bus evidence"
        return MatchResult(self.profile_id, self.bus, reason, score)

    # -- source evidence ------------------------------------------------

    def evidence_from_source(self, source_text: str) -> dict[str, Any]:
        callback_present = any(token in source_text
                               for token in self.callback_tokens)
        resource_present = any(token in source_text
                               for token in self.resource_tokens)
        if not callback_present and not resource_present:
            return {}
        evidence: dict[str, Any] = {"bus": self.bus}
        if callback_present:
            evidence["bindings"] = {self.callback: "source-evidence"}
        if resource_present:
            evidence["resources"] = {self.resource: {"source": True}}

        identity = self._extract_identity(source_text)
        if identity:
            evidence["identity"] = identity
        return evidence

    def _extract_identity(self, text: str) -> dict[str, str]:
        identity: dict[str, str] = {}
        for pattern in self.identity_patterns:
            match = re.search(pattern, text, re.S)
            if match and match.lastindex:
                identity.setdefault("driver_name", match.group(1))
                break
        if self.device_id_patterns:
            vendor, product = self._extract_device_ids(text)
            if vendor is not None:
                identity["vendor_id"] = vendor
                identity["product_id"] = product or ""
        return identity

    @staticmethod
    def _extract_device_ids(text: str) -> tuple[str | None, str | None]:
        defines: dict[str, str] = {}
        for name, value in re.findall(
                r'#define\s+(\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s', text + "\n"):
            defines[name] = value
        for pattern in (
                r"USB_DEVICE\s*\(\s*(0x[0-9A-Fa-f]+|\d+|[A-Za-z_]\w*)\s*,"
                r"\s*(0x[0-9A-Fa-f]+|\d+|[A-Za-z_]\w*)\s*\)",
                r"\.idVendor\s*=\s*(0x[0-9A-Fa-f]+|\d+|[A-Za-z_]\w*).*?"
                r"\.idProduct\s*=\s*(0x[0-9A-Fa-f]+|\d+|[A-Za-z_]\w*)"):
            match = re.search(pattern, text, re.S)
            if not match:
                continue

            def resolve(token: str) -> str | None:
                if token in defines:
                    return defines[token]
                if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", token):
                    return token
                return None

            vendor = resolve(match.group(1))
            product = resolve(match.group(2))
            if vendor is not None and product is not None:
                return vendor, product
        return None, None

    # -- planning --------------------------------------------------------

    def plan(self, evidence: Mapping[str, Any]) -> ProfilePlan:
        identity = _mapping(evidence.get("identity"))
        config: dict[str, Any] = {}
        for name in self.required_fixture_fields:
            if name in identity:
                config[name] = identity[name]
        fixture_templates = _mapping(self.plan_templates)
        for key, value in _mapping(fixture_templates.get("fixture_config")).items():
            rendered = _render_placeholders(value, identity)
            if key in config and isinstance(config[key], dict) and isinstance(rendered, dict):
                config[key].update(rendered)
            else:
                config[key] = rendered
        overrides = _render_placeholders(
            _mapping(fixture_templates.get("runtime_overrides")), identity)
        subsystem_contracts = tuple(
            dict(item) for item in (evidence.get("subsystem_contracts") or ()))
        return ProfilePlan(
            profile_id=self.profile_id,
            bus=self.bus,
            required_capabilities=self.required_capabilities,
            optional_capabilities=self.optional_capabilities,
            runtime_adapter="qemu-profile",
            fixture={"kind": self.fixture_kind, "config": config},
            manifest_template=self.manifest_template,
            required_fixture_fields=self.required_fixture_fields,
            runtime_overrides=overrides,
            registration_contract=dict(self.registration_contract),
            subsystem_contracts=subsystem_contracts,
        )


@dataclass(frozen=True)
class ProfileCatalog:
    """Validated declarative profile definitions."""
    profiles: tuple[Any, ...] = ()


def _validate_declarative(entry: Mapping[str, Any], index: int,
                          repo_root: Path) -> _DeclarativeProfile:
    where = f"profiles[{index}]"
    unknown = sorted(set(entry) - _DECLARATIVE_FIELDS)
    if unknown:
        raise ProfileCatalogError(
            f"{where} declares unknown field(s): {', '.join(unknown)}")
    missing = sorted(_DECLARATIVE_REQUIRED - set(entry))
    if missing:
        raise ProfileCatalogError(
            f"{where} is missing required field(s): {', '.join(missing)}")

    profile_id = entry["profile_id"]
    bus = entry["bus"]
    for name, value in (("profile_id", profile_id), ("bus", bus),
                        ("callback", entry["callback"]),
                        ("resource", entry["resource"]),
                        ("fixture_kind", entry["fixture_kind"])):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ProfileCatalogError(f"{where}.{name} is unsafe: {value!r}")

    def _tokens(field: str, *, required: bool = False) -> tuple[str, ...]:
        raw = entry.get(field, [] if not required else None)
        if raw is None:
            raw = []
        if not isinstance(raw, list) or any(
                not isinstance(item, str) for item in raw):
            raise ProfileCatalogError(f"{where}.{field} must be a list of strings")
        return tuple(raw)

    capabilities = _tokens("required_capabilities")
    if not capabilities:
        raise ProfileCatalogError(
            f"{where}.required_capabilities must be non-empty")

    manifest_template = entry.get("manifest_template")
    if manifest_template is not None:
        if not isinstance(manifest_template, str):
            raise ProfileCatalogError(f"{where}.manifest_template must be a string")
        resolved = (repo_root / manifest_template).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            raise ProfileCatalogError(
                f"{where}.manifest_template {manifest_template!r} points "
                "outside repository") from None

    plan_templates = entry.get("plan_templates", {})
    if not isinstance(plan_templates, Mapping):
        raise ProfileCatalogError(f"{where}.plan_templates must be an object")
    _check_placeholders(plan_templates, f"{where}.plan_templates")

    contract = entry.get("registration_contract")
    if contract is None:
        contract = {"root_table": f"{bus}_driver",
                    "identity_field": "driver_name"}
    contract = _validate_registration_contract(
        contract, f"{where}.registration_contract")

    identity_patterns = _tokens("identity_patterns")
    for pattern in identity_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ProfileCatalogError(
                f"{where}.identity_patterns entry is invalid: {exc}") from exc
    device_id_patterns = _tokens("device_id_patterns")

    matrix_required = entry.get("matrix_required", False)
    if not isinstance(matrix_required, bool):
        raise ProfileCatalogError(f"{where}.matrix_required must be a boolean")

    return _DeclarativeProfile(
        profile_id=profile_id,
        bus=bus,
        callback=entry["callback"],
        resource=entry["resource"],
        fixture_kind=entry["fixture_kind"],
        required_capabilities=capabilities,
        optional_capabilities=_tokens("optional_capabilities"),
        manifest_template=manifest_template,
        callback_tokens=_tokens("callback_tokens"),
        resource_tokens=_tokens("resource_tokens"),
        identity_patterns=identity_patterns,
        device_id_patterns=device_id_patterns,
        required_fixture_fields=_tokens("required_fixture_fields"),
        registration_contract=contract,
        plan_templates=plan_templates,
        matrix_required=matrix_required,
    )


def load_profile_definitions(repo_root: Path | None = None) -> ProfileCatalog:
    """Load and validate the declarative profile catalog."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    path = root / _DEFINITIONS_PATH
    if not path.is_file():
        if root != _REPO_ROOT and (_REPO_ROOT / _DEFINITIONS_PATH).is_file():
            path = _REPO_ROOT / _DEFINITIONS_PATH
            root = _REPO_ROOT
        else:
            raise ProfileCatalogError(
                f"driver profile definitions not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileCatalogError(
            f"cannot read driver profile definitions: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("schema") != 1:
        raise ProfileCatalogError(
            "driver profile definitions must declare schema 1")
    entries = document.get("profiles")
    if not isinstance(entries, list):
        raise ProfileCatalogError(
            "driver profile definitions must contain a profiles array")
    profiles = [_validate_declarative(entry, index, root)
                for index, entry in enumerate(entries)
                if isinstance(entry, Mapping)]
    seen: set[str] = set()
    for profile in profiles:
        if profile.profile_id in seen:
            raise ProfileCatalogError(
                f"duplicate profile id: {profile.profile_id}")
        seen.add(profile.profile_id)
    return ProfileCatalog(tuple(profiles))


def load_profile_plugins(paths: Iterable[Path],
                         registry: "ProfileRegistry") -> None:
    """Register profiles from plugin modules exposing register_profiles()."""
    for raw in paths:
        path = Path(raw)
        module_name = f"reharness_profile_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ProfileCatalogError(f"cannot load profile plugin: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        register = getattr(module, "register_profiles", None)
        if register is None:
            raise ProfileCatalogError(
                f"profile plugin has no register_profiles(): {path}")
        register(registry)


# ── registry ──────────────────────────────────────────────────────────


class ProfileRegistry:
    """Deterministic registry for evidence-backed driver type profiles."""

    def __init__(self, profiles: tuple[DriverTypeProfile, ...] = ()) -> None:
        self._profiles: list[DriverTypeProfile] = list(profiles)

    def register(self, profile: DriverTypeProfile) -> None:
        profile_id = getattr(profile, "profile_id", None)
        if not isinstance(profile_id, str) or not _SAFE_ID.fullmatch(profile_id):
            raise ProfileCatalogError(
                f"profile_id is unsafe: {profile_id!r}")
        if any(item.profile_id == profile_id for item in self._profiles):
            raise ValueError(f"duplicate driver profile: {profile_id}")
        self._profiles.append(profile)

    @property
    def profiles(self) -> tuple[DriverTypeProfile, ...]:
        return tuple(self._profiles)

    def evidence_from_source(self, source_text: str) -> dict[str, Any]:
        """Collect source evidence from every registered profile."""
        merged: dict[str, Any] = {}
        for profile in self._profiles:
            collect = getattr(profile, "evidence_from_source", None)
            if collect is None:
                continue
            evidence = collect(source_text)
            if not isinstance(evidence, Mapping) or not evidence:
                continue
            for key in ("bindings", "resources", "identity"):
                if isinstance(evidence.get(key), Mapping):
                    bucket = dict(merged.setdefault(key, {}))
                    bucket.update(evidence[key])
                    merged[key] = bucket
            if evidence.get("bus"):
                # Later-registered (plugin) profiles override builtin buses.
                merged["bus"] = evidence["bus"]
        return merged

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

    def _validate_plan(self, profile: DriverTypeProfile,
                       plan: Any) -> ProfilePlan:
        if not isinstance(plan, ProfilePlan):
            raise ProfileMatchError(
                f"{profile.profile_id} returned a non-ProfilePlan: "
                f"{type(plan).__name__}")
        if len(set(plan.required_capabilities)) != len(plan.required_capabilities):
            raise ProfileMatchError(
                f"{profile.profile_id} declares duplicate required capabilities")
        if not isinstance(plan.fixture, Mapping):
            raise ProfileMatchError(
                f"{profile.profile_id} fixture must be a mapping")
        if plan.runtime_overrides is not None and not isinstance(
                plan.runtime_overrides, Mapping):
            raise ProfileMatchError(
                f"{profile.profile_id} runtime_overrides must be a mapping")
        if plan.bus != profile.bus:
            raise ProfileMatchError(
                f"{profile.profile_id} plan bus {plan.bus!r} does not match "
                f"profile bus {profile.bus!r}")
        return plan

    def resolve(self, evidence: Mapping[str, Any], *,
                requested: str | None = None,
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

        plan = self._validate_plan(profile, profile.plan(evidence))
        return ProfileResolution(profile=profile, match=result, plan=plan)


def build_default_registry(repo_root: Path | None = None) -> ProfileRegistry:
    """Return a fresh registry from the declarative profile catalog."""
    return ProfileRegistry(load_profile_definitions(repo_root).profiles)


__all__ = [
    "DriverTypeProfile", "MatchResult", "ProfileCatalogError",
    "ProfileMatchError", "ProfilePlan", "ProfileRegistry", "ProfileResolution",
    "build_default_registry", "load_profile_definitions", "load_profile_plugins",
]
