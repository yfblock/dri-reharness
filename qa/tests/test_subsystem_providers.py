from __future__ import annotations

import json
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401


def _catalog(root: Path, *, executable: str = "suite/tool.c") -> Path:
    path = root / "benchmarks" / "subsystem-providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1,
        "providers": [{
            "id": "linux-test-tool",
            "kind": "tool",
            "subsystems": ["i2c"],
            "executable": executable,
            "required_kernel_modules": ["i2c-dev"],
        }],
    }), encoding="utf-8")
    return path


def _manifest_document(root: Path, *, executable: str | None = None,
                       kind: str | None = None,
                       provider: str = "linux-test-tool",
                       modules: list[str] | None = None) -> dict:
    source = root / "driver.c"
    source.write_text("int driver;\n", encoding="utf-8")
    test_source = root / "suite" / "tool.c"
    test_source.parent.mkdir(parents=True, exist_ok=True)
    test_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    test = {
        "name": "linux-test",
        "provider": provider,
        "args": ["/dev/test"],
    }
    if executable is not None:
        test["executable"] = executable
    if kind is not None:
        test["kind"] = kind
    return {
        "schema": 2,
        "name": "provider-fixture",
        "source": {"path": "driver.c"},
        "compile": {"backend": "linux", "language": "c", "context": "kbuild"},
        "runtime": {
            "adapter": "qemu",
            "qemu": {
                "machine": "q35", "device": "fixture", "bus": "i2c",
                "module": "fixture", "timeout_seconds": 90,
                "kernel_modules": (modules if modules is not None
                                    else ["i2c-dev"]),
            },
        },
        "test": {"subsystem": {"name": "i2c", "tests": [test]}},
        "trace": {
            "fields": ["phase", "function", "kind", "width_bits",
                       "address", "value", "sequence"],
        },
        "limits": {"compile": 3, "runtime": 3, "trace": 3},
    }


def test_provider_materializes_kind_and_executable_from_catalog(tmp_path: Path):
    _catalog(tmp_path)

    from experiment_manifest import load_manifest

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_document(tmp_path)),
                             encoding="utf-8")
    manifest = load_manifest(manifest_path, repo_root=tmp_path)
    test = manifest.test.subsystem.tests[0]

    assert test.kind == "tool"
    assert test.executable == (tmp_path / "suite/tool.c").resolve()
    assert test.provider == "linux-test-tool"


def test_provider_rejects_explicit_kind_mismatch(tmp_path: Path):
    _catalog(tmp_path)

    from experiment_manifest import ManifestError, validate_manifest

    with pytest.raises(ManifestError, match="kind.*linux-test-tool"):
        validate_manifest(_manifest_document(tmp_path, kind="kselftest"),
                          repo_root=tmp_path)


def test_provider_rejects_explicit_executable_mismatch(tmp_path: Path):
    _catalog(tmp_path)
    other = tmp_path / "suite" / "other.c"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    from experiment_manifest import ManifestError, validate_manifest

    with pytest.raises(ManifestError, match="executable.*linux-test-tool"):
        validate_manifest(_manifest_document(
            tmp_path, executable="suite/other.c"), repo_root=tmp_path)


def test_provider_rejects_missing_required_kernel_module(tmp_path: Path):
    _catalog(tmp_path)

    from experiment_manifest import ManifestError, validate_manifest

    with pytest.raises(ManifestError, match="kernel module.*i2c-dev"):
        validate_manifest(_manifest_document(tmp_path, modules=[]),
                          repo_root=tmp_path)


def test_provider_catalog_rejects_unknown_provider_in_catalog_workspace(
        tmp_path: Path):
    _catalog(tmp_path)
    document = _manifest_document(tmp_path, provider="not-registered")

    from experiment_manifest import ManifestError, validate_manifest

    with pytest.raises(ManifestError, match="unknown subsystem test provider"):
        validate_manifest(document, repo_root=tmp_path)



def test_repository_manifests_use_provider_ids_as_the_source_of_test_kind():
    from experiment_manifest import load_manifest

    root = _paths.REPO_ROOT
    manifest = load_manifest(root / "benchmarks/experiments/ftgpio010.json",
                             repo_root=root)
    tests = {item.provider: item for item in manifest.test.subsystem.tests
             if item.provider is not None}

    assert set(tests) == {"linux-gpio-chip-info", "linux-gpio-line-name"}
    assert all(item.kind == "kselftest" for item in tests.values())



def test_auto_generated_i2c_and_spi_manifests_preserve_linux_tool_providers(
        tmp_path: Path):
    from auto_driver import normalize_input
    from experiment_manifest import load_manifest

    root = _paths.REPO_ROOT
    expected = {
        "reharness-i2c-sensor.c": "linux-i2c-dev",
        "reharness-spi-sensor.c": "linux-spidev",
    }
    for filename, provider in expected.items():
        result = normalize_input(
            root / "benchmarks/drivers/fixtures" / filename,
            repo_root=root, output_dir=tmp_path / filename,
        )
        manifest = load_manifest(result["manifest"], repo_root=root)
        providers = {item.provider for item in manifest.test.subsystem.tests
                     if item.provider is not None}
        assert provider in providers


def test_kunit_provider_requires_a_module_and_forbids_executable(tmp_path: Path):
    catalog = tmp_path / "benchmarks" / "subsystem-providers.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps({
        "schema": 1,
        "providers": [{
            "id": "linux-clock-kunit",
            "kind": "kunit",
            "subsystems": ["clock"],
            "module": "clk-test",
            "default_success_pattern": "ok [0-9]+ -",
        }],
    }), encoding="utf-8")

    from subsystem_providers import load_provider_catalog

    provider = load_provider_catalog(tmp_path).get("linux-clock-kunit")
    assert provider is not None
    assert provider.module == "clk-test"
    assert provider.executable is None

    catalog.write_text(json.dumps({
        "schema": 1,
        "providers": [{
            "id": "linux-clock-kunit",
            "kind": "kunit",
            "subsystems": ["clock"],
            "executable": "suite/clock.c",
            "module": "clk-test",
        }],
    }), encoding="utf-8")
    (tmp_path / "suite").mkdir(exist_ok=True)
    (tmp_path / "suite/clock.c").write_text("", encoding="utf-8")

    from subsystem_providers import ProviderCatalogError

    with pytest.raises(ProviderCatalogError, match="requires module and forbids executable"):
        load_provider_catalog(tmp_path)


def test_repository_catalog_declares_clock_kunit_provider():
    from subsystem_providers import load_provider_catalog

    provider = load_provider_catalog(_paths.REPO_ROOT).get("linux-clock-kunit")
    assert provider is not None
    assert provider.kind == "kunit"
    assert provider.module == "clk-test"
    assert provider.executable is None
    assert provider.required_kernel_modules == ("clk-test",)
    assert provider.default_success_pattern == "ok [0-9]+( |-|$)"


def test_repository_catalog_declares_linux_usbtest_tool_provider():
    from subsystem_providers import load_provider_catalog

    provider = load_provider_catalog(_paths.REPO_ROOT).get("linux-usbtest")
    assert provider is not None
    assert provider.kind == "tool"
    assert provider.subsystems == ("usb",)
    assert provider.module == "usbtest"
    assert provider.executable == (
        _paths.REPO_ROOT / "vendor/linux/tools/usb/testusb.c"
    ).resolve()
    assert provider.required_kernel_modules == ("usbtest",)


def test_repository_catalog_declares_linux_network_selftest_provider():
    from subsystem_providers import load_provider_catalog

    provider = load_provider_catalog(_paths.REPO_ROOT).get(
        "linux-netdevice-selftest")
    assert provider is not None
    assert provider.kind == "kselftest"
    assert provider.subsystems == ("network",)
    assert provider.executable == (
        _paths.REPO_ROOT / "vendor/linux/tools/testing/selftests/net/netdevice.sh"
    ).resolve()
