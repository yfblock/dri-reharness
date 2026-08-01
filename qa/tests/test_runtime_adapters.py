from __future__ import annotations

from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from verification.runtime_adapters import ManifestRuntime  # noqa: E402


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
        "schema": 1, "name": "adapter-test", "source": {"path": "README.md"},
        "compile": {"backend": "linux", "language": "c", "context": "test"},
        "runtime": {"adapter": "qemu", "machine": "test-machine", "device": "test-device",
                     "bus": "test-bus", "module": "test-module", "timeout_seconds": 7,
                     "probe_pattern": "ready", "registrar": "target"},
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
