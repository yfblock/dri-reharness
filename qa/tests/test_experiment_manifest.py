from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from experiment_manifest import (  # noqa: E402
    ManifestError,
    ExperimentManifest,
    canonical_json,
    load_manifest,
    manifest_digest,
    validate_manifest,
)


def _document(tmp_path: Path) -> dict:
    source = tmp_path / "driver.c"
    source.write_text("int driver;\n", encoding="utf-8")
    return {
        "schema": 1,
        "name": "fixture",
        "source": {"path": str(source.relative_to(tmp_path))},
        "compile": {"backend": "linux", "language": "c", "context": "kbuild"},
        "runtime": {
            "adapter": "qemu",
            "machine": "q35",
            "device": "fixture",
            "bus": "pci",
            "module": "fixture_drv",
            "timeout_seconds": 90,
        },
        "test": {"executable": "qa/native-tests/edu_trace_test", "args": ["/dev/fixture_drv"]},
        "trace": {
            "fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"],
            "value_mask": "0xffffffff",
        },
        "limits": {"compile": 3, "runtime": 3, "trace": 3},
    }


def test_manifest_loads_typed_and_resolves_paths_inside_repository(tmp_path: Path):
    document = _document(tmp_path)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    manifest = load_manifest(path, repo_root=tmp_path)
    assert isinstance(manifest, ExperimentManifest)
    assert manifest.name == "fixture"
    assert manifest.source.path == (tmp_path / "driver.c").resolve()
    assert manifest.limits.compile == 3


def test_manifest_digest_is_stable_for_mapping_order(tmp_path: Path):
    document = _document(tmp_path)
    reordered = {key: document[key] for key in reversed(document)}
    assert canonical_json(document) == canonical_json(reordered)
    assert manifest_digest(document) == manifest_digest(reordered)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda d: d.update({"unexpected": True}), "unknown field"),
        (lambda d: d["source"].update({"path": "../../outside.c"}), "repository"),
        (lambda d: d.pop("runtime"), "runtime"),
        (lambda d: d.pop("test"), "test"),
        (lambda d: d["limits"].update({"compile": 0}), "iteration"),
        (lambda d: d["trace"].update({"fields": ["not-a-trace-field"]}), "trace"),
    ],
)
def test_manifest_rejects_invalid_documents(tmp_path: Path, mutation, expected: str):
    document = _document(tmp_path)
    mutation(document)
    with pytest.raises(ManifestError, match=expected):
        validate_manifest(document, repo_root=tmp_path)


def test_manifest_rejects_unknown_nested_fields(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["unknown"] = "nope"
    with pytest.raises(ManifestError, match="unknown field"):
        validate_manifest(document, repo_root=tmp_path)


def test_repository_manifests_are_valid():
    root = _paths.REPO_ROOT
    for name in ("edu.json", "ftgpio010.json"):
        path = root / "benchmarks" / "experiments" / name
        document = json.loads(path.read_text(encoding="utf-8"))
        manifest = load_manifest(path, repo_root=root)
        assert manifest.name
        assert manifest_digest(document) == manifest.digest
