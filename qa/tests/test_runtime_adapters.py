from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from verification.runtime_adapters import (  # noqa: E402
    ManifestCompiler,
    ManifestExtractor,
    ManifestComparator,
    ManifestRuntime,
    RuntimeAdapter,
    RuntimeAdapterError,
    resolve_runtime_adapter,
)


def _trace(path: Path, values: list[int], *, addresses: list[int] | None = None) -> None:
    events = []
    for index, value in enumerate(values):
        events.append({
            "phase": "probe", "function": "runtime_probe", "kind": "read",
            "width_bits": 32,
            "address": (addresses or [0x10] * len(values))[index],
            "value": value, "sequence": index,
        })
    path.write_text(json.dumps({"events": events}), encoding="utf-8")


def test_runtime_command_is_manifest_driven(tmp_path: Path, monkeypatch):
    # The command construction is exercised through a harmless subprocess
    # replacement; no device-specific branch is involved.
    captured = {}

    class Completed:
        returncode = 0
        stdout = '{"events": []}'
        stderr = ''

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Completed()

    monkeypatch.setattr("verification.runtime_adapters.subprocess.run", fake_run)
    from experiment_manifest import validate_manifest
    root = Path(__file__).resolve().parents[2]
    manifest = validate_manifest({
        "schema": 2, "name": "adapter-test", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "qemu", "qemu": {
            "machine": "test-machine", "device": "test-device", "bus": "test-bus",
            "module": "test-module", "timeout_seconds": 7,
            "probe_pattern": "ready", "registrar": "target"}},
        "test": {"executable": "README.md", "args": ["arg"]},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=root)
    result = ManifestRuntime(root).run(manifest, None, [], "baseline")
    assert result["ok"]
    assert captured["command"][:4] == ["bash", "scripts/qemu/qemu_run.sh", "test-module", "--bus"]
    assert "test-bus" in captured["command"]
    assert "test-device" in captured["command"]
    assert "--timeout" in captured["command"]


def test_qemu_adapter_ids_resolve_through_registry(tmp_path: Path):
    qemu = resolve_runtime_adapter("qemu", tmp_path, tmp_path)
    platform = resolve_runtime_adapter("qemu-platform", tmp_path, tmp_path)

    assert type(qemu) is type(platform)


def test_unknown_runtime_adapter_fails_closed_before_subprocess(tmp_path: Path, monkeypatch):
    from experiment_manifest import validate_manifest

    manifest = validate_manifest({
        "schema": 2, "name": "unknown-adapter", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "does-not-exist", "qemu": {
            "machine": "test-machine", "device": "test-device", "bus": "test-bus",
            "module": "test-module", "timeout_seconds": 7,
        }},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=Path(__file__).resolve().parents[2])
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unknown adapters must be rejected before execution")

    monkeypatch.setattr("verification.runtime_adapters.subprocess.run", fail_if_called)
    try:
        ManifestRuntime(tmp_path).run(manifest, None, [], "baseline")
    except RuntimeAdapterError as exc:
        assert "does-not-exist" in str(exc)
    else:
        raise AssertionError("expected RuntimeAdapterError")
    assert not called


def test_manifest_runtime_dispatches_registered_adapter(tmp_path: Path):
    from experiment_manifest import validate_manifest

    manifest = validate_manifest({
        "schema": 2, "name": "custom-adapter", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "custom-test", "qemu": {
            "machine": "test-machine", "device": "test-device", "bus": "test-bus",
            "module": "test-module", "timeout_seconds": 7,
        }},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=Path(__file__).resolve().parents[2])
    calls = []

    class CustomAdapter(RuntimeAdapter):
        def run(self, manifest, candidate, scenario, role):
            calls.append((manifest.name, role))
            return {"ok": True, "value": "custom", "payload": {"role": role}}

    registry = {"custom-test": CustomAdapter}
    result = ManifestRuntime(tmp_path, registry=registry).run(manifest, None, [], "candidate")

    assert result["ok"]
    assert calls == [("custom-adapter", "candidate")]


def test_manifest_comparator_rejects_register_trace_mutation_and_reports_first_divergence(tmp_path: Path):
    from experiment_manifest import validate_manifest

    root = Path(__file__).resolve().parents[2]
    manifest = validate_manifest({
        "schema": 2, "name": "trace-gate", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "qemu", "qemu": {
            "machine": "test", "device": "test", "bus": "test", "module": "test",
            "timeout_seconds": 1}},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=root)
    baseline, candidate = tmp_path / "baseline.json", tmp_path / "candidate.json"
    _trace(baseline, [1, 2, 3])
    _trace(candidate, [1, 9, 3])

    result = ManifestComparator().compare(manifest, baseline, candidate)

    assert result["ok"] is False
    feedback = result["feedback"]
    assert feedback["failure_class"] == "trace"
    assert feedback["details"]["divergence"]["index"] == 1
    assert feedback["details"]["divergence"]["original"]["value"] == 2
    assert feedback["details"]["divergence"]["candidate"]["value"] == 9


def test_manifest_comparator_accepts_non_register_changes_when_trace_is_unchanged(tmp_path: Path):
    from experiment_manifest import validate_manifest

    root = Path(__file__).resolve().parents[2]
    manifest = validate_manifest({
        "schema": 2, "name": "trace-gate-equal", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "qemu", "qemu": {
            "machine": "test", "device": "test", "bus": "test", "module": "test",
            "timeout_seconds": 1}},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=root)
    baseline, candidate = tmp_path / "baseline.json", tmp_path / "candidate.json"
    _trace(baseline, [1, 2])
    _trace(candidate, [1, 2])
    assert ManifestComparator().compare(manifest, baseline, candidate)["ok"] is True


def test_manifest_compiler_preserves_quoted_command_arguments(tmp_path: Path, monkeypatch):
    from experiment_manifest import validate_manifest

    root = Path(__file__).resolve().parents[2]
    manifest = validate_manifest({
        "schema": 2, "name": "quoted-command", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c",
                     "context": 'command: compiler --label "value with spaces" --output {output}'},
        "runtime": {"adapter": "qemu", "qemu": {
            "machine": "test", "device": "test", "bus": "test", "module": "quoted",
            "timeout_seconds": 1}},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=root)
    captured = {}

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Completed()

    monkeypatch.setattr("verification.runtime_adapters.sanitize_source", lambda *args, **kwargs: None)
    monkeypatch.setattr("verification.runtime_adapters.subprocess.run", fake_run)
    result = ManifestCompiler(root, tmp_path).compile(manifest, {"code": "int init_module(void) { return 0; }"})

    assert result["ok"] is True
    assert captured["command"][:3] == ["compiler", "--label", "value with spaces"]
    assert captured["command"][3] == "--output"


def test_manifest_extractor_uses_fresh_evidence_directory_per_run(tmp_path: Path, monkeypatch):
    from experiment_manifest import validate_manifest

    root = Path(__file__).resolve().parents[2]
    manifest = validate_manifest({
        "schema": 2, "name": "evidence-isolation", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "qemu", "qemu": {
            "machine": "test", "device": "test", "bus": "test", "module": "evidence",
            "timeout_seconds": 1}},
        "test": {"executable": "README.md"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }, repo_root=root)

    class Completed:
        returncode = 0
        stderr = ""

    def fake_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        (output / "marker.formal.json").write_text("{}\n", encoding="utf-8")
        return Completed()

    monkeypatch.setattr("verification.runtime_adapters.subprocess.run", fake_run)
    extractor = ManifestExtractor(root, tmp_path)
    first = extractor.extract(manifest)
    second = extractor.extract(manifest)

    assert first["ok"] and second["ok"]
    first_dir = Path(first["value"]["directory"])
    second_dir = Path(second["value"]["directory"])
    assert first_dir != second_dir
    assert first_dir.is_dir() and second_dir.is_dir()
