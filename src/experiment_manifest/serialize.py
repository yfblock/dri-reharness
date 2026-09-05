"""Canonical JSON encoding, digests, manifest loading, trace-field checks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .validators import ManifestError, _repo_root, _TRACE_EVENT_FIELDS
from .specs import ExperimentManifest
from .validate import validate_manifest


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


