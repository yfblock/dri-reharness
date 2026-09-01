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
    PciIdentity,
    SafetyPolicy,
    canonical_json,
    load_manifest,
    manifest_digest,
    validate_manifest,
)


def _document(tmp_path: Path) -> dict:
    source = tmp_path / "driver.c"
    source.write_text("int driver;\n", encoding="utf-8")
    return {
        "schema": 2,
        "name": "fixture",
        "source": {"path": str(source.relative_to(tmp_path))},
        "compile": {"backend": "linux", "language": "c", "context": "kbuild"},
        "runtime": {
            "adapter": "qemu",
            "qemu": {
                "machine": "q35",
                "device": "fixture",
                "bus": "pci",
                "module": "fixture_drv",
                "timeout_seconds": 90,
            },
            "pci_identity": {"vendor": "0x1234", "device": "0x5678"},
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
        assert manifest.manifest_path == path.resolve()
        assert manifest_digest(document) == manifest.digest


def test_runtime_policy_sections_round_trip():
    root = _paths.REPO_ROOT
    manifest = load_manifest(root / "benchmarks" / "experiments" / "edu.json", repo_root=root)
    assert isinstance(manifest.runtime.pci_identity, PciIdentity)
    assert manifest.runtime.pci_identity.vendor == 0x1234
    assert isinstance(manifest.runtime.safety_policy, SafetyPolicy)
    assert "IO_DMA_CMD" in manifest.runtime.safety_policy.forbidden_tokens
    assert manifest.runtime.qemu.bus == "pci"


def test_manifest_round_trips_declarative_registration_contract(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["registration"] = {
        "root_table": "spi_driver",
        "identity_field": "driver_name",
        "device_id_tables": ["spi_device_id"],
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.registration is not None
    assert manifest.runtime.registration.root_table == "spi_driver"
    assert manifest.runtime.registration.identity_field == "driver_name"
    assert manifest.runtime.registration.device_id_tables == ("spi_device_id",)
    assert manifest.to_dict()["runtime"]["registration"] == {
        **document["runtime"]["registration"],
        "device_id_tables": ["spi_device_id"],
    }


def test_manifest_round_trips_plugin_registration_shape(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["registration"] = {
        "root_table": "watchdog_driver",
        "identity_field": "driver_name",
        "registration_apis": [{
            "name": "watchdog_register_driver",
            "kind": "driver_root",
            "argument": 0,
            "type": "struct watchdog_driver *",
            "table": "watchdog_driver",
        }],
        "tables": [{
            "id": "watchdog_driver",
            "record": "watchdog_driver",
            "role": "root",
        }],
        "links": [],
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.registration is not None
    rendered = manifest.to_dict()["runtime"]["registration"]
    assert rendered["root_table"] == "watchdog_driver"
    assert rendered["registration_apis"] == document["runtime"]["registration"][
        "registration_apis"]
    assert rendered["tables"] == document["runtime"]["registration"]["tables"]


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (lambda value: value.update({"root_table": "../unsafe"}), "unsafe"),
        (lambda value: value.update({"identity_field": "bus"}),
         "identity_field"),
        (lambda value: value.update({"device_id_tables": ["spi_device_id", "spi_device_id"]}),
         "duplicates"),
    ],
)
def test_manifest_rejects_invalid_registration_contract(tmp_path: Path,
                                                         mutation, expected):
    document = _document(tmp_path)
    registration = {
        "root_table": "spi_driver",
        "identity_field": "driver_name",
        "device_id_tables": ["spi_device_id"],
    }
    mutation(registration)
    document["runtime"]["registration"] = registration

    with pytest.raises(ManifestError, match=expected):
        validate_manifest(document, repo_root=tmp_path)


def test_qemu_policy_round_trips_generic_binding_and_device_launch_mode(
        tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["qemu"].update({
        "launch_device": False,
        "qemu_args": [
            "-drive", "if=none,id=drive0,driver=null-co,size=1M",
            "-device", "virtio-blk-pci,drive=drive0",
        ],
        "binding": {
            "bus": "virtio",
            "device_glob": "*",
            "required": True,
        },
    })

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.qemu.launch_device is False
    assert manifest.runtime.qemu.qemu_args[-1] == "virtio-blk-pci,drive=drive0"
    assert manifest.runtime.qemu.binding.bus == "virtio"
    assert manifest.runtime.qemu.binding.device_glob == "*"
    assert manifest.runtime.qemu.binding.required is True
    rendered = manifest.to_dict()["runtime"]["qemu"]
    assert rendered["launch_device"] is False
    assert rendered["binding"] == {
        "bus": "virtio", "device_glob": "*", "required": True}


@pytest.mark.parametrize(
    "binding,expected",
    [
        ({"bus": "virtio/bad"}, "binding.bus"),
        ({"bus": "virtio", "device_glob": "../*"},
         "binding.device_glob"),
        ({"bus": "virtio", "required": "yes"}, "binding.required"),
    ],
)
def test_manifest_rejects_unsafe_generic_qemu_binding(
        tmp_path: Path, binding, expected: str):
    document = _document(tmp_path)
    document["runtime"]["qemu"]["binding"] = binding

    with pytest.raises(ManifestError, match=expected):
        validate_manifest(document, repo_root=tmp_path)


def test_runtime_profile_capabilities_and_fixture_round_trip(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"].update({
        "profile": "platform-generic",
        "capabilities": {
            "required": ["registration", "probe", "unload"],
            "optional": ["trace"],
        },
        "fixture": {"kind": "qemu-platform", "config": {}},
        "subsystem_contracts": [{
            "id": "gpio-generic",
            "subsystem": "gpio",
            "reason": "gpio source evidence",
            "score": 5,
            "required_capabilities": ["static_analysis"],
            "optional_capabilities": ["trace"],
            "summary_groups": ["gpio_generic"],
            "summary_contracts": ["linux.gpio_generic_chip_config"],
        }],
    })

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.profile == "platform-generic"
    assert manifest.runtime.capabilities.required == (
        "registration", "probe", "unload")
    assert manifest.runtime.capabilities.optional == ("trace",)
    assert manifest.runtime.fixture.kind == "qemu-platform"
    assert manifest.runtime.subsystem_contracts[0]["id"] == "gpio-generic"
    assert manifest.runtime.subsystem_contracts[0]["summary_groups"] == [
        "gpio_generic"]
    assert manifest.runtime.subsystem_contracts[0]["summary_contracts"] == [
        "linux.gpio_generic_chip_config"]
    assert manifest.to_dict()["runtime"]["fixture"] == {
        "kind": "qemu-platform", "config": {}}


def test_manifest_rejects_malformed_subsystem_contract(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["subsystem_contracts"] = [{
        "id": "gpio-generic",
        "subsystem": "gpio",
        "reason": "source",
        "score": 1,
        "unexpected": True,
    }]

    with pytest.raises(ManifestError, match="subsystem_contracts.*unknown field"):
        validate_manifest(document, repo_root=tmp_path)


@pytest.mark.parametrize(
    "capabilities,expected",
    [
        ({"required": ["probe", "probe"]}, "duplicate"),
        ({"required": ["not-a-capability"]}, "unknown capability"),
        ({"required": ["probe"], "optional": ["probe"]}, "overlap"),
    ],
)
def test_manifest_rejects_invalid_runtime_capabilities(
        tmp_path: Path, capabilities, expected: str):
    document = _document(tmp_path)
    document["runtime"]["capabilities"] = capabilities

    with pytest.raises(ManifestError, match=expected):
        validate_manifest(document, repo_root=tmp_path)


def test_manifest_rejects_fixture_assets_outside_repository(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["fixture"] = {
        "kind": "qemu-platform",
        "config": {},
        "assets": ["../../outside-fixture.ko"],
    }

    with pytest.raises(ManifestError, match="repository"):
        validate_manifest(document, repo_root=tmp_path)


def test_runtime_fixture_round_trips_repository_owned_module_sources(
        tmp_path: Path):
    document = _document(tmp_path)
    source = tmp_path / "fixture-registrar.c"
    source.write_text("int fixture_registrar;\n", encoding="utf-8")
    document["runtime"]["fixture"] = {
        "kind": "qemu-i2c",
        "config": {},
        "module_sources": [source.name],
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.fixture.module_sources == (source.resolve(),)
    assert manifest.to_dict()["runtime"]["fixture"]["module_sources"] == [
        "fixture-registrar.c"]


def test_manifest_validates_profile_fixture_module_arguments(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["fixture"] = {
        "kind": "qemu-i2c",
        "config": {
            "module_args": {"i2c-registrar": ["client_type=generic_sensor"]},
        },
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.fixture.config["module_args"] == {
        "i2c-registrar": ["client_type=generic_sensor"]}


def test_manifest_rejects_unsafe_profile_fixture_module_arguments(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["fixture"] = {
        "kind": "qemu-i2c",
        "config": {"module_args": {"i2c-registrar": ["x=$(id)"]}},
    }

    with pytest.raises(ManifestError, match="module_args"):
        validate_manifest(document, repo_root=tmp_path)


def test_manifest_supports_linux_subsystem_tests_without_native_exerciser(tmp_path: Path):
    document = _document(tmp_path)
    subsystem_test = tmp_path / "gpio-kselftest"
    subsystem_test.write_text("#!/bin/sh\n", encoding="utf-8")
    document["test"] = {
        "subsystem": {
            "name": "gpio",
            "tests": [{
                "name": "gpio-kselftest",
                "executable": str(subsystem_test.relative_to(tmp_path)),
                "args": ["--chip", "/dev/gpiochip0"],
                "success_pattern": "GPIO_SUBSYSTEM_PASS",
            }],
        },
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.test.executable is None
    assert manifest.test.subsystem is not None
    assert manifest.test.subsystem.name == "gpio"
    assert manifest.test.subsystem.tests[0].executable == subsystem_test.resolve()
    assert manifest.test.to_dict(root=tmp_path)["subsystem"]["tests"][0]["name"] == "gpio-kselftest"


def test_manifest_declares_kunit_and_kselftest_subsystem_test_kinds(
        tmp_path: Path):
    document = _document(tmp_path)
    kselftest = tmp_path / "gpio-selftest"
    kselftest.write_text("#!/bin/sh\n", encoding="utf-8")
    document["runtime"]["qemu"]["kernel_modules"] = ["fixture_kunit"]
    document["test"] = {
        "subsystem": {
            "name": "fixture",
            "tests": [
                {
                    "name": "kselftest-api",
                    "kind": "kselftest",
                    "executable": str(kselftest.relative_to(tmp_path)),
                    "success_pattern": "ok",
                },
                {
                    "name": "kunit-suite",
                    "kind": "kunit",
                    "module": "fixture_kunit",
                    "success_pattern": "ok 1 - fixture",
                },
            ],
        },
    }

    manifest = validate_manifest(document, repo_root=tmp_path)
    tests = manifest.test.subsystem.tests

    assert tests[0].kind == "kselftest"
    assert tests[0].executable == kselftest.resolve()
    assert tests[1].kind == "kunit"
    assert tests[1].module == "fixture_kunit"
    assert tests[1].executable is None
    rendered = manifest.to_dict()["test"]["subsystem"]["tests"]
    assert rendered[0]["kind"] == "kselftest"
    assert rendered[1]["module"] == "fixture_kunit"


def test_manifest_round_trips_extensible_test_provider_and_required_flag(
        tmp_path: Path):
    document = _document(tmp_path)
    helper = tmp_path / "spidev-test.c"
    helper.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    document["test"] = {
        "subsystem": {
            "name": "spi",
            "tests": [{
                "name": "linux-spidev-tool",
                "kind": "tool",
                "provider": "linux-spidev",
                "required": False,
                "executable": str(helper.relative_to(tmp_path)),
                "args": ["--device", "/dev/spidev0.0"],
            }],
        },
    }

    manifest = validate_manifest(document, repo_root=tmp_path)
    test = manifest.test.subsystem.tests[0]

    assert test.provider == "linux-spidev"
    assert test.required is False
    rendered = manifest.to_dict()["test"]["subsystem"]["tests"][0]
    assert rendered["provider"] == "linux-spidev"
    assert rendered["required"] is False


@pytest.mark.parametrize("provider", ["", "of/spidev", "$(id)"])
def test_manifest_rejects_unsafe_test_provider(tmp_path: Path, provider: str):
    document = _document(tmp_path)
    helper = tmp_path / "test.c"
    helper.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    document["test"] = {
        "subsystem": {
            "name": "spi",
            "tests": [{
                "name": "tool",
                "provider": provider,
                "executable": str(helper.relative_to(tmp_path)),
            }],
        },
    }

    with pytest.raises(ManifestError, match="provider"):
        validate_manifest(document, repo_root=tmp_path)


def test_manifest_subsystem_tests_can_declare_assets_and_kernel_modules(tmp_path: Path):
    document = _document(tmp_path)
    helper = tmp_path / "gpio-chip-info"
    helper.write_text("binary-placeholder\n", encoding="utf-8")
    script = tmp_path / "gpio-sim.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    document["runtime"]["qemu"]["kernel_modules"] = ["gpio-sim"]
    document["test"] = {
        "subsystem": {
            "name": "gpio",
            "tests": [{
                "name": "gpio-sim",
                "executable": str(script.relative_to(tmp_path)),
                "assets": [str(helper.relative_to(tmp_path))],
                "success_pattern": "GPIO gpio-sim test PASS",
            }],
        },
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.runtime.qemu.kernel_modules == ("gpio-sim",)
    assert manifest.test.subsystem.tests[0].assets == (helper.resolve(),)
    rendered = manifest.to_dict()["test"]["subsystem"]["tests"][0]
    assert rendered["assets"] == ["gpio-chip-info"]


def test_manifest_parses_explicit_subsystem_coverage_contract(tmp_path: Path):
    document = _document(tmp_path)
    document["test"]["coverage"] = {
        "required": ["chip_info", "v2_single_line", "irq_event"],
        "callbacks": ["gpio_chip.get", "irq_chip.irq_set_type"],
    }

    manifest = validate_manifest(document, repo_root=tmp_path)

    assert manifest.test.coverage.required == (
        "chip_info", "v2_single_line", "irq_event")
    assert manifest.test.coverage.callbacks == (
        "gpio_chip.get", "irq_chip.irq_set_type")
    assert manifest.to_dict()["test"]["coverage"]["required"] == [
        "chip_info", "v2_single_line", "irq_event"]


def test_manifest_rejects_invalid_linux_subsystem_test_pattern(tmp_path: Path):
    document = _document(tmp_path)
    document["test"]["subsystem"] = {
        "name": "gpio",
        "tests": [{
            "name": "gpio-kselftest",
            "executable": "README.md",
            "success_pattern": "[",
        }],
    }
    with pytest.raises(ManifestError, match="success_pattern"):
        validate_manifest(document, repo_root=tmp_path)


def test_nested_pci_policy_requires_identity(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"] = {
        "adapter": "qemu",
        "qemu": {"machine": "q35", "device": "x", "bus": "pci",
                 "module": "x", "timeout_seconds": 10},
    }
    with pytest.raises(ManifestError, match="pci_identity"):
        validate_manifest(document, repo_root=tmp_path)


def test_schema_one_is_rejected_instead_of_being_compatibility_parsed(tmp_path: Path):
    document = _document(tmp_path)
    document["schema"] = 1
    with pytest.raises(ManifestError, match="unsupported manifest schema"):
        validate_manifest(document, repo_root=tmp_path)


def test_flat_runtime_policy_is_rejected(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"] = {
        "adapter": "qemu",
        "machine": "q35",
        "device": "fixture",
        "bus": "pci",
        "module": "fixture_drv",
        "timeout_seconds": 90,
    }
    with pytest.raises(ManifestError, match="unknown field|runtime.qemu"):
        validate_manifest(document, repo_root=tmp_path)


def test_runtime_spec_exposes_only_nested_policy_sections(tmp_path: Path):
    manifest = validate_manifest(_document(tmp_path), repo_root=tmp_path)
    assert not hasattr(manifest.runtime, "machine")
    assert not hasattr(manifest.runtime, "device")
    assert not hasattr(manifest.runtime, "bus")
    assert not hasattr(manifest.runtime, "module")
    assert not hasattr(manifest.runtime, "timeout_seconds")
    assert not hasattr(manifest.runtime, "probe_pattern")
    assert not hasattr(manifest.runtime, "registrar")
    assert not hasattr(manifest.runtime, "qemu_args")


def test_invalid_safety_rewrite_pattern_rejected(tmp_path: Path):
    document = _document(tmp_path)
    document["runtime"]["safety_policy"] = {
        "forbidden_tokens": ["TOKEN"], "action": "rewrite",
        "rewrite_rules": [{"pattern": "[", "replacement": ""}],
    }
    with pytest.raises(ManifestError, match="pattern"):
        validate_manifest(document, repo_root=tmp_path)
