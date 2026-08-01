from __future__ import annotations

from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from verification.runtime_adapters import (  # noqa: E402
    ManifestRuntime,
    RuntimeAdapter,
    RuntimeAdapterError,
    resolve_runtime_adapter,
)


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
