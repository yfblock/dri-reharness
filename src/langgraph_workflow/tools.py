"""Tools used by the LangGraph orchestration layer.

The tools keep the graph thin and delegate domain behavior to existing
reharness modules.  Their returned values are JSON-serializable so graph
checkpoints never contain live AST, subprocess, or adapter objects.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


def _repo_path(value: Any, repo_root: Path, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path")
    candidate = (Path(value) if Path(value).is_absolute()
                else repo_root / value).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} resolves outside repository: {value}") from exc
    return candidate


def _output_path(value: Any, repo_root: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output_dir must be a non-empty path")
    path = Path(value)
    return (path if path.is_absolute() else repo_root / path).resolve()


def _experiment_manifest_path(value: Any, repo_root: Path,
                             output_dir: Path) -> Path:
    """Allow only repository manifests or the auto-driver output manifest."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("experiment_manifest must be a non-empty path")
    candidate = (Path(value) if Path(value).is_absolute()
                 else repo_root / value).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        expected = (output_dir / "manifest.json").resolve()
        if candidate != expected:
            raise ValueError(
                "experiment_manifest resolves outside repository and is not "
                f"the generated manifest {expected}: {value}") from exc
    return candidate


def normalize_request(raw: Mapping[str, Any], *, repo_root: str | Path,
                      profile_registry: Any = None) -> dict[str, Any]:
    """Validate and normalize a user request without running the pipeline."""
    if not isinstance(raw, Mapping):
        raise ValueError("workflow input must be an object")
    root = Path(repo_root).resolve()
    source_value = raw.get("source")
    if source_value is None:
        source_value = raw.get("driver")
    source = _repo_path(source_value, root, "source")
    if not source.is_file():
        raise ValueError(f"source does not exist: {source}")

    output_value = raw.get("output_dir")
    output = (_output_path(output_value, root)
              if output_value is not None else
              root / "artifacts" / "langgraph" / source.stem)

    experiment_value = raw.get("experiment_manifest")
    if experiment_value is None:
        experiment_value = raw.get("manifest")
    experiment_manifest = None
    if experiment_value is not None:
        experiment_manifest = _experiment_manifest_path(
            experiment_value, root, output)
        if not experiment_manifest.is_file():
            raise ValueError(
                f"experiment_manifest does not exist: {experiment_manifest}")

    mode = raw.get("mode")
    if mode is None:
        mode = "experiment" if experiment_manifest is not None else "analysis"
    if mode not in {"analysis", "generation", "experiment"}:
        raise ValueError("mode must be analysis, generation, or experiment")
    if mode == "experiment" and experiment_manifest is None:
        raise ValueError("experiment mode requires experiment_manifest")

    backend = raw.get("backend", "linux")
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError("backend must be a non-empty string")
    experiment_backends = raw.get("experiment_backends")
    if experiment_backends is not None:
        if (not isinstance(experiment_backends, list) or not experiment_backends
                or any(not isinstance(item, str) or not item.strip()
                       for item in experiment_backends)):
            raise ValueError(
                "experiment_backends must be a list of non-empty strings")
        experiment_backends = [item.strip() for item in experiment_backends]
    request = raw.get("request", "analyze and run the driver pipeline")

    profile: dict[str, Any] | None = None
    profile_plan: dict[str, Any] | None = None
    subsystem_contracts: list[dict[str, Any]] = []
    missing_capabilities: list[str] = ["runtime_profile"]
    # Profile matching consumes source-derived API evidence.  Descriptors are
    # resolved after their complete file inventory is available.
    is_descriptor = False
    if source.suffix.lower() == ".json":
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read source descriptor: {source}") from exc
        is_descriptor = isinstance(document, Mapping) and isinstance(
            document.get("sources"), list)
    if source.suffix.lower() == ".c" or is_descriptor:
        if str(root / "src") not in sys.path:
            sys.path.insert(0, str(root / "src"))
        from auto_driver import (AutoDriverError, resolve_profile,
                                 runtime_manifest_gaps)
        from subsystem_contracts import build_default_contract_registry

        source_parts: list[str] = []
        try:
            if source.suffix.lower() == ".c":
                source_parts.append(source.read_text(
                    encoding="utf-8", errors="replace"))
            else:
                document = json.loads(source.read_text(encoding="utf-8"))
                for item in document.get("sources", []):
                    if isinstance(item, str):
                        source_parts.append((source.parent / item).read_text(
                            encoding="utf-8", errors="replace"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            source_parts = []
        detected_contracts = tuple(
            item.to_dict() for item in build_default_contract_registry(root).detect(
                "\n".join(source_parts)))
        try:
            selected = resolve_profile(
                source, repo_root=root, profile_registry=profile_registry)
        except AutoDriverError as exc:
            raise ValueError(f"cannot resolve driver profile: {exc}") from exc
        if selected is not None:
            profile = selected.summary("source API evidence")
            plan = selected.plan
            profile_plan = {
                "id": plan.profile_id,
                "bus": plan.bus,
                "required_capabilities": list(plan.required_capabilities),
                "optional_capabilities": list(plan.optional_capabilities),
                "runtime_adapter": plan.runtime_adapter,
                "fixture": dict(plan.fixture),
                "manifest_template": plan.manifest_template,
                "required_fixture_fields": list(plan.required_fixture_fields),
                "runtime_overrides": dict(plan.runtime_overrides),
                "subsystem_contracts": [dict(item)
                                        for item in plan.subsystem_contracts],
            }
            subsystem_contracts = [dict(item)
                                   for item in plan.subsystem_contracts]
            missing_capabilities = runtime_manifest_gaps(selected, plan)
        if not subsystem_contracts:
            subsystem_contracts = [dict(item) for item in detected_contracts]
    return {
        "request": request,
        "source": str(source),
        "experiment_manifest": (str(experiment_manifest)
                                 if experiment_manifest is not None else None),
        "backend": backend,
        "mode": mode,
        "output_dir": str(output.resolve()),
        "profile": profile,
        "profile_plan": profile_plan,
        "subsystem_contracts": subsystem_contracts,
        "missing_capabilities": missing_capabilities,
        "experiment_backends": experiment_backends,
    }


def _source_entries(source: Path) -> tuple[str, list[Path]]:
    if source.suffix.lower() != ".json":
        return source.stem, [source]
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read source manifest: {source}") from exc
    if not isinstance(document, Mapping):
        raise ValueError(f"source manifest must be an object: {source}")
    entries = document.get("sources")
    if isinstance(entries, list):
        if not entries or any(not isinstance(item, str) or not item.strip()
                              for item in entries):
            raise ValueError("source manifest sources must be non-empty strings")
        return str(document.get("name") or source.stem), [
            (source.parent / item).resolve() for item in entries]
    source_field = document.get("source")
    if isinstance(source_field, Mapping) and isinstance(source_field.get("path"), str):
        return str(document.get("name") or source.stem), [
            (source.parent / source_field["path"]).resolve()]
    raise ValueError(
        f"source JSON must contain sources[]; use experiment_manifest for experiment JSON: {source}")


def _digest_files(files: list[Path], descriptor: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(descriptor).encode("utf-8"))
    digest.update(b"\0")
    digest.update(descriptor.read_bytes())
    digest.update(b"\0")
    for path in files:
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def discover_driver_files(request: Mapping[str, Any], *, repo_root: str | Path) -> dict[str, Any]:
    """Resolve every source listed by a C file or multi-source manifest."""
    root = Path(repo_root).resolve()
    source = _repo_path(request.get("source"), root, "source")
    driver, files = _source_entries(source)
    checked: list[Path] = []
    for path in files:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"driver file resolves outside repository: {path}") from exc
        if not path.is_file():
            raise ValueError(f"driver file does not exist: {path}")
        checked.append(path)
    return {
        "driver": driver,
        "descriptor": str(source),
        "files": [str(path) for path in checked],
        "file_count": len(checked),
        "digest": _digest_files(checked, source),
    }


def _artifact_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_synthesis_evidence(formal: Mapping[str, Any], device_spec: Any,
                             bind: Any, facts: Any,
                             *, inventory: Mapping[str, Any],
                             readiness: Mapping[str, Any] | None,
                             bundle_dir: str | Path,
                             bundle_digest: str,
                             contract_verification: Mapping[str, Any] | None = None,
                             ) -> dict[str, Any]:
    """Build the bounded semantic payload sent to a model provider.

    Artifact paths remain available for contract verification, but providers
    cannot read the local filesystem.  The compact generator evidence format
    therefore travels in the request envelope as the source of truth.
    """
    if not isinstance(inventory.get("files"), list):
        raise ValueError("inventory.files must be a list")
    from backends.llm_bridge import build_evidence_json

    payload = json.loads(build_evidence_json(formal, device_spec, bind, facts))
    payload.update({
        "directory": str(Path(bundle_dir).resolve()),
        "digest": bundle_digest,
        "source_files": [str(item) for item in inventory["files"]],
        "source_digest": str(inventory.get("digest", "")),
        "readiness": dict(readiness or {}),
        "bundle": {
            "directory": str(Path(bundle_dir).resolve()),
            "digest": bundle_digest,
        },
    })
    if isinstance(contract_verification, Mapping):
        payload["subsystem_contract_verification"] = dict(
            contract_verification)
    return payload


def analyze_driver_files(request: Mapping[str, Any], inventory: Mapping[str, Any], *,
                         repo_root: str | Path) -> dict[str, Any]:
    """Run the existing extractor over the complete source descriptor."""
    root = Path(repo_root).resolve()
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    # synthesis imports verification modules at import time.  Register the
    # repository QA namespace before importing the synthesis service.
    verification_root = root / "qa"
    if not verification_root.is_dir():
        verification_root = Path(__file__).resolve().parents[2] / "qa"
    if str(verification_root) not in sys.path:
        sys.path.insert(0, str(verification_root))
    verification_modules = verification_root / "verification"
    if str(verification_modules) not in sys.path:
        sys.path.insert(0, str(verification_modules))
    from extractor import ExtractorConfig, extract_ris
    from extractor.spec import default_bind
    from synthesis import build_bundle

    evidence_dir = Path(request["output_dir"]) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    config = ExtractorConfig(
        source=str(inventory["descriptor"]),
        output=str(evidence_dir / f"{inventory['driver']}.ris"),
        driver_name=inventory["driver"],
    )
    result = extract_ris(config)
    # Keep source-shape validation independent from extraction internals while
    # making its result part of the formal evidence consumed by readiness.
    from backends.oracles.transaction_ir_oracle import verify_transaction_sources

    transaction_validation = verify_transaction_sources(
        result.formal, list(inventory["files"]))
    result.formal.setdefault("metadata", {})[
        "transaction_validation"] = transaction_validation
    profile_plan = request.get("profile_plan")
    contracts = (request.get("subsystem_contracts")
                 or (profile_plan.get("subsystem_contracts", [])
                     if isinstance(profile_plan, Mapping) else []))
    from subsystem_contract_verification import verify_contract_summaries

    contract_verification = verify_contract_summaries(
        result.formal, contracts)
    bundle_dir = Path(build_bundle(
        result, request["backend"], str(evidence_dir)))
    files = sorted(str(path) for path in bundle_dir.iterdir() if path.is_file())
    bundle_digest = _artifact_digest(bundle_dir)
    readiness = None
    try:
        from extractor.metrics import score
        readiness = score(result.device_spec, result.formal,
                          result.warnings, result.facts)
        if isinstance(readiness, Mapping):
            readiness = dict(readiness)
            readiness["subsystem_contract_verification"] = contract_verification
    except Exception as exc:  # metrics must not hide extraction evidence
        readiness = {"error": f"{type(exc).__name__}: {exc}"}
    synthesis_evidence = build_synthesis_evidence(
        result.formal, result.device_spec,
        default_bind(result.device_spec, request["backend"]), result.facts,
        inventory=inventory, readiness=readiness,
        bundle_dir=bundle_dir, bundle_digest=bundle_digest,
        contract_verification=contract_verification)
    synthesis_evidence["profile_plan"] = profile_plan
    return {
        "driver": inventory["driver"],
        "files": list(inventory["files"]),
        "source_digest": inventory["digest"],
        "stats": result.stats,
        "warnings": list(result.warnings),
        "readiness": readiness,
        "subsystem_contract_verification": contract_verification,
        "evidence": {
            "directory": str(bundle_dir),
            "files": files,
            "digest": bundle_digest,
        },
        "synthesis_evidence": synthesis_evidence,
    }


def _pipeline_failure(exc: Exception, *, stage: str) -> dict[str, Any]:
    """Convert an exception at the imperative pipeline boundary to JSON."""
    return {
        "failure_class": "infrastructure",
        "message": str(exc) or type(exc).__name__,
        "details": {"exception": type(exc).__name__},
        "retryable": False,
        "stage": stage,
    }


