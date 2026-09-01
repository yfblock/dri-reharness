"""Auto-driver: profile detection, request normalization, and manifest materialization.

Profile matching is declarative (``driver_profiles``) and pinned regression
drivers are mapped to their experiment manifests through
``benchmarks/profile-catalog.json`` — no driver name is special-cased in
code.  This module builds source-derived evidence and materializes runtime
manifests for ``langgraph_workflow.tools`` and the ``auto-driver`` CLI.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from driver_profiles import (ProfileMatchError, ProfilePlan, ProfileRegistry,
                             ProfileResolution, build_default_registry)
from subsystem_contracts import (ContractRegistry,
                                 build_default_contract_registry)


class AutoDriverError(ValueError):
    """Raised when automatic driver normalization fails closed."""


_REPO_ROOT = Path(__file__).resolve().parents[1]
_PINNED_CATALOG_PATH = Path("benchmarks/profile-catalog.json")

_DEFAULT_REGISTRY: ProfileRegistry | None = None
_DEFAULT_CONTRACTS: ContractRegistry | None = None


def _default_registry() -> ProfileRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY


def _default_contracts() -> ContractRegistry:
    global _DEFAULT_CONTRACTS
    if _DEFAULT_CONTRACTS is None:
        _DEFAULT_CONTRACTS = build_default_contract_registry()
    return _DEFAULT_CONTRACTS


# ── pinned regression profiles (data-driven) ──────────────────────────


@dataclass(frozen=True)
class DriverProfile:
    """A concrete profile: pinned entry or generic match."""
    profile_id: str
    manifest_template: Path | None
    base_profile_id: str | None
    plan: ProfilePlan | None


def _load_pinned_catalog(repo_root: Path) -> list[dict[str, str]]:
    path = repo_root / _PINNED_CATALOG_PATH
    if not path.is_file():
        path = _REPO_ROOT / _PINNED_CATALOG_PATH
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = document.get("profiles") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _pinned_profile(source: Path, repo_root: Path) -> DriverProfile | None:
    resolved = source.resolve()
    for entry in _load_pinned_catalog(repo_root):
        pinned_source = (repo_root / entry["source"]).resolve()
        if pinned_source != resolved:
            continue
        manifest = repo_root / entry["manifest"]
        return DriverProfile(
            profile_id=entry["profile_id"],
            manifest_template=manifest,
            base_profile_id=entry.get("base_profile_id"),
            plan=None)
    return None


# ── source kinds ──────────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _source_texts(files: list[Path]) -> list[str]:
    texts: list[str] = []
    for path in files:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return texts


def _descriptor_sources(descriptor: Path) -> list[Path]:
    document = _read_json(descriptor) or {}
    entries = document.get("sources")
    if not isinstance(entries, list):
        return []
    return [(descriptor.parent / item).resolve()
            for item in entries if isinstance(item, str)]


# ── identity & manifest materialization ───────────────────────────────


def _module_name(stem: str) -> str:
    return stem.replace("-", "_")


def _manifest_for_profile(profile: DriverProfile, source: Path,
                          output_dir: Path, plan: ProfilePlan | None) -> dict[str, Any]:
    """Instantiate a profile's manifest template for a concrete source.

    runtime.adapter comes from the plan; qemu.module prefers an explicit
    runtime override, then the source-derived module name.
    """
    template_path = profile.manifest_template
    document: dict[str, Any] = {}
    if template_path is not None and Path(template_path).is_file():
        loaded = _read_json(Path(template_path))
        if loaded is not None:
            document = json.loads(json.dumps(loaded))  # deep copy

    effective_plan = plan or profile.plan
    runtime = document.setdefault("runtime", {})
    if effective_plan is not None:
        runtime["adapter"] = effective_plan.runtime_adapter
        runtime["profile"] = effective_plan.profile_id
        runtime["fixture"] = json.loads(json.dumps(dict(effective_plan.fixture)))
        if effective_plan.registration_contract is not None:
            runtime["registration"] = dict(effective_plan.registration_contract)
        overrides = effective_plan.runtime_overrides or {}
        for key, value in overrides.items():
            if (isinstance(value, Mapping) and isinstance(runtime.get(key), Mapping)):
                merged_section = dict(runtime[key])
                merged_section.update(value)
                runtime[key] = merged_section
            else:
                runtime[key] = value

    qemu = runtime.setdefault("qemu", {})
    stem = source.stem if source.suffix == ".c" else source.name
    override_module = None
    if effective_plan is not None and isinstance(
            effective_plan.runtime_overrides, Mapping):
        qemu_overrides = effective_plan.runtime_overrides.get("qemu")
        if isinstance(qemu_overrides, Mapping) and qemu_overrides.get("module"):
            override_module = qemu_overrides["module"]
    if override_module:
        qemu["module"] = override_module
    else:
        qemu["module"] = _module_name(stem)

    document.setdefault("schema", 2)
    source_doc = document.setdefault("source", {})
    source_doc["path"] = str(source)
    return document


def _materialize(document: dict[str, Any], output_dir: Path,
                 name_hint: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def _pin_source_sha256(document: dict[str, Any], source: Path,
                       repo_root: Path) -> None:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source_doc = document.setdefault("source", {})
    source_doc["sha256"] = digest

def _manifest_contract(match: Any) -> dict[str, Any]:
    """Render a contract match in experiment-manifest runtime form."""
    tokens = getattr(match, "matched_tokens", ()) or ()
    return {
        "id": match.contract_id,
        "subsystem": match.subsystem,
        "reason": ("source tokens: " + ", ".join(tokens)) if tokens
                  else "subsystem contract detection",
        "score": 100,
        "required_capabilities": list(match.required_capabilities),
        "optional_capabilities": list(match.optional_capabilities),
        "summary_groups": list(match.summary_groups),
        "summary_contracts": list(match.summary_contracts),
    }

# ── profile resolution ────────────────────────────────────────────────


class ResolvedProfile:
    """ProfileResolution wrapper carrying identity-derived capability gaps."""

    def __init__(self, resolution: ProfileResolution,
                 missing: tuple[str, ...]) -> None:
        self._resolution = resolution
        self.missing = missing

    @property
    def resolution(self) -> ProfileResolution:
        return self._resolution

    @property
    def profile(self):
        return self._resolution.profile

    @property
    def plan(self) -> ProfilePlan | None:
        return self._resolution.plan

    @property
    def match(self):
        return self._resolution.match

    def summary(self, reason: str = "") -> dict[str, Any]:
        return self._resolution.summary(reason)


def resolve_profile(source: Path, *, repo_root: Path | None = None,
                    root: Path | None = None,
                    registry: ProfileRegistry | None = None,
                    profile_registry: ProfileRegistry | None = None,
                    requested: str | None = None
                    ) -> ResolvedProfile | None:
    """Match a driver source against the profile registry.

    Returns ``None`` when no transport profile matches — subsystem-only
    drivers are legitimate and must not fail normalization.
    """
    repo = Path(root if repo_root is None else repo_root)
    reg = registry or profile_registry
    if reg is None:
        try:
            reg = build_default_registry(repo)
        except Exception:
            reg = _default_registry()

    files = ([Path(source)] if source.suffix.lower() != ".json"
             or not _descriptor_sources(Path(source))
             else _descriptor_sources(Path(source)))
    texts = _source_texts(files)
    if not texts:
        raise AutoDriverError(f"source does not exist or is empty: {source}")
    text = "\n".join(texts)

    evidence = reg.evidence_from_source(text)
    contracts = _default_contracts().detect(text, evidence=evidence)
    if contracts:
        evidence["subsystem_contracts"] = [c.to_dict() for c in contracts]

    try:
        if requested is not None:
            resolution = reg.resolve(evidence, requested=requested,
                                     allow_unknown=False)
        else:
            resolution = reg.resolve(evidence, allow_unknown=True)
    except ProfileMatchError as exc:
        message = str(exc)
        if requested is not None and "unknown driver profile" in message:
            raise AutoDriverError(f"unknown runtime profile: {requested}") from exc
        if "ambiguous" in message or "requested profile" in message:
            raise AutoDriverError(message) from exc
        return None
    if resolution.profile is None or resolution.plan is None:
        return None
    identity = evidence.get("identity") if isinstance(
        evidence.get("identity"), Mapping) else {}
    return ResolvedProfile(resolution,
                           tuple(_identity_missing(resolution.plan, identity)))


def runtime_manifest_gaps(resolution: Any,
                          plan: ProfilePlan | None = None) -> list[str]:
    """Missing runtime capabilities a manifest must still provide."""
    missing = getattr(resolution, "missing", None)
    if missing:
        return list(missing)
    if resolution is None or getattr(resolution, "profile", None) is None:
        return ["runtime_profile"]
    return []


# ── normalization entry point ─────────────────────────────────────────


def _identity_missing(plan: ProfilePlan,
                      identity: Mapping[str, Any]) -> list[str]:
    """Missing runtime capabilities for identity/materialization."""
    if plan.manifest_template is None:
        return ["runtime_manifest"]
    if not plan.required_fixture_fields:
        return []  # identity-independent template
    if not identity:
        return ["runtime_identity"]
    for field_name in plan.required_fixture_fields:
        if field_name not in identity:
            return [f"runtime_{field_name}"]
    return []


def normalize_input(source: Path, *, repo_root: Path,
                    output_dir: Path | None = None,
                    profile_registry: ProfileRegistry | None = None,
                    profile: str | None = None,
                    ) -> dict[str, Any]:
    """Normalize a driver request into a pinned or materialized manifest."""
    source = Path(source)
    repo = Path(repo_root)
    if not source.is_file():
        raise AutoDriverError(f"source does not exist: {source}")
    out = Path(output_dir) if output_dir is not None else (
        repo / "artifacts" / "auto-driver" / source.stem)

    document = _read_json(source) if source.suffix.lower() == ".json" else None

    # ── manifest-kind input: validate the pinned digest ──────────────
    if document is not None and "sources" not in document and "schema" in document:
        src_doc = document.get("source") or {}
        src_path = src_doc.get("path")
        if not isinstance(src_path, str):
            raise AutoDriverError(f"manifest source.path is required: {source}")
        resolved = (source.parent / src_path).resolve()
        if not resolved.is_file():
            raise AutoDriverError(f"pinned source does not exist: {resolved}")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        declared = src_doc.get("sha256")
        if declared is not None and declared != digest:
            raise AutoDriverError(
                f"source digest mismatch for {resolved}: pinned "
                f"{declared} != actual {digest}")
        return {
            "input_kind": "manifest",
            "status": "ready",
            "source": {"path": str(resolved), "sha256": digest},
            "profile": None,
            "profile_plan": None,
            "manifest": str(source.resolve()),
            "missing_capabilities": [],
            "output_dir": str(out),
        }

    # ── descriptor / C input ─────────────────────────────────────────
    is_descriptor = document is not None and isinstance(
        document.get("sources"), list)
    input_kind = "descriptor" if is_descriptor else "c"
    files = (_descriptor_sources(source) if is_descriptor
             else [source.resolve()])
    name_hint = (str(document.get("name") or source.stem)
                 if is_descriptor else source.stem)
    texts = _source_texts(files)
    if not texts:
        raise AutoDriverError(f"source does not exist or is empty: {source}")
    text = "\n".join(texts)

    # pinned regression profiles (data catalog, no code special-casing);
    # plugin-augmented registries and explicit profile requests take
    # precedence over the pinned catalog.
    _has_plugin_profiles = False
    if profile_registry is not None:
        try:
            builtin_ids = {p.profile_id for p in build_default_registry(repo).profiles}
            _has_plugin_profiles = any(
                p.profile_id not in builtin_ids
                for p in profile_registry.profiles)
        except Exception:
            _has_plugin_profiles = True
    if (not is_descriptor and profile is None and not _has_plugin_profiles):
        pinned = _pinned_profile(source.resolve(), repo)
        if pinned is not None and pinned.manifest_template is not None:
            loaded = _read_json(pinned.manifest_template)
            if loaded is not None:
                base_plan = None
                try:
                    base_registry = profile_registry or build_default_registry(repo)
                    base_profile = next(
                        (p for p in base_registry.profiles
                         if p.profile_id == pinned.base_profile_id), None)
                    if base_profile is not None:
                        base_plan = base_profile.plan(
                            {"identity": {"driver_name": name_hint}})
                except Exception:
                    base_plan = None
                runtime = loaded.setdefault("runtime", {})
                if pinned.base_profile_id:
                    runtime["profile"] = pinned.base_profile_id
                # Subsystem tests replace the native exerciser: a pinned
                # manifest's native test section is rendered as the first
                # subsystem test so no dual dispatch happens at runtime.
                test_doc = loaded.get("test")
                if (isinstance(test_doc, dict) and "executable" in test_doc
                        and "subsystem" not in test_doc):
                    entry = {key: value for key, value in test_doc.items()
                             if key not in ("actions",)}
                    entry.setdefault("name", f"{name_hint}-native")
                    loaded["test"] = {"subsystem": {
                        "name": name_hint,
                        "tests": [entry]}}
                _pin_source_sha256(loaded, source.resolve(), repo)
                pinned_contracts = [_manifest_contract(c)
                                    for c in _default_contracts().detect(text)]
                if pinned_contracts:
                    runtime["subsystem_contracts"] = pinned_contracts
                path = _materialize(loaded, out, pinned.profile_id)
                plan_dict = None
                if base_plan is not None:
                    plan_dict = {
                        "id": base_plan.profile_id,
                        "bus": base_plan.bus,
                        "required_capabilities": list(base_plan.required_capabilities),
                        "optional_capabilities": list(base_plan.optional_capabilities),
                        "runtime_adapter": base_plan.runtime_adapter,
                        "fixture": dict(base_plan.fixture),
                        "manifest_template": base_plan.manifest_template,
                        "required_fixture_fields": list(base_plan.required_fixture_fields),
                        "runtime_overrides": dict(base_plan.runtime_overrides or {}),
                        "subsystem_contracts": pinned_contracts or [
                            dict(item) for item in base_plan.subsystem_contracts],
                    }
                return {
                    "input_kind": input_kind,
                    "status": "ready",
                    "source": {"path": str(source.resolve())},
                    "profile": {"id": pinned.profile_id,
                                "base": pinned.base_profile_id},
                    "profile_plan": plan_dict,
                    "manifest": str(path),
                    "missing_capabilities": [],
                    "output_dir": str(out),
                }

    # generic declarative profiles
    registry = profile_registry or build_default_registry(repo)
    evidence = registry.evidence_from_source(text)
    contracts = _default_contracts().detect(text, evidence=evidence)
    if contracts:
        evidence["subsystem_contracts"] = [c.to_dict() for c in contracts]

    try:
        resolution = registry.resolve(
            evidence, requested=profile, allow_unknown=profile is None)
    except ProfileMatchError as exc:
        raise AutoDriverError(str(exc)) from exc

    if resolution.profile is None or resolution.plan is None:
        return {
            "input_kind": input_kind,
            "status": "inconclusive",
            "source": {"path": str(source.resolve())},
            "profile": None,
            "profile_plan": None,
            "manifest": None,
            "missing_capabilities": ["runtime_profile"],
            "output_dir": str(out),
        }

    plan = resolution.plan
    template: Path | None = None
    if plan.manifest_template:
        template = Path(plan.manifest_template)
        if not template.is_absolute():
            candidate = (repo / plan.manifest_template)
            template = (candidate if candidate.is_file()
                        else (_REPO_ROOT / plan.manifest_template)).resolve()
        try:
            template.resolve().relative_to(repo.resolve())
        except ValueError:
            try:
                template.resolve().relative_to(_REPO_ROOT.resolve())
            except ValueError:
                raise AutoDriverError(
                    f"manifest template {template} is outside repository root "
                    f"{repo}") from None
    identity = evidence.get("identity") if isinstance(
        evidence.get("identity"), Mapping) else {}
    profile_entry: dict[str, Any] = {"id": plan.profile_id}
    if is_descriptor:
        profile_entry["base"] = plan.profile_id
    missing = _identity_missing(plan, identity)

    plan_dict = {
        "id": plan.profile_id,
        "bus": plan.bus,
        "required_capabilities": list(plan.required_capabilities),
        "optional_capabilities": list(plan.optional_capabilities),
        "runtime_adapter": plan.runtime_adapter,
        "fixture": dict(plan.fixture),
        "manifest_template": plan.manifest_template,
        "required_fixture_fields": list(plan.required_fixture_fields),
        "runtime_overrides": dict(plan.runtime_overrides or {}),
        "subsystem_contracts": [dict(item) for item in plan.subsystem_contracts],
    }

    manifest_path = None
    if not missing and template is not None:
        driver_profile = DriverProfile(plan.profile_id, template, None, plan)
        document = _manifest_for_profile(driver_profile, files[0], out, plan)
        src_doc = document.setdefault("source", {})
        src_doc["path"] = str(files[0])
        src_doc["sha256"] = hashlib.sha256(
            files[0].read_bytes()).hexdigest()
        manifest_path = _materialize(document, out, name_hint)

    return {
        "input_kind": input_kind,
        "status": "ready" if not missing else "inconclusive",
        "source": {"path": str(source.resolve())},
        "profile": profile_entry,
        "profile_plan": plan_dict,
        "manifest": str(manifest_path) if manifest_path else None,
        "missing_capabilities": missing,
        "output_dir": str(out),
    }


__all__ = ["AutoDriverError", "DriverProfile", "normalize_input",
           "resolve_profile", "_manifest_for_profile"]
