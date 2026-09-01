from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qa" / "verification"))

from auto_driver import AutoDriverError, normalize_input, resolve_profile
from experiment_manifest import load_manifest
import run_auto_driver


def test_auto_driver_bootstraps_verification_import_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [item for item in sys.path
                                        if item != str(ROOT / "qa")])

    run_auto_driver._bootstrap_import_paths()



def test_builtin_regression_profiles_are_loaded_from_data_catalog():
    import auto_driver

    catalog_path = ROOT / "benchmarks/profile-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = {item["profile_id"] for item in catalog["profiles"]}

    assert entries == {"edu-pci", "ftgpio010-gpio"}
    source = Path(auto_driver.__file__).read_text(encoding="utf-8")
    assert '"edu-pci"' not in source
    assert '"ftgpio010-gpio"' not in source


def test_normalize_c_generates_pinned_manifest_for_known_profile(tmp_path):
    result = normalize_input(
        ROOT / "benchmarks/drivers/baseline/edu.c",
        repo_root=ROOT,
        output_dir=tmp_path,
    )

    assert result["input_kind"] == "c"
    assert result["profile"]["id"] == "edu-pci"
    assert result["profile_plan"]["id"] == "pci-generic"
    assert result["profile_plan"]["bus"] == "pci"
    manifest_path = Path(result["manifest"])
    manifest = load_manifest(manifest_path, repo_root=ROOT)
    assert manifest.source.sha256 == hashlib.sha256(
        (ROOT / "benchmarks/drivers/baseline/edu.c").read_bytes()
    ).hexdigest()
    assert manifest.runtime.qemu.device == "edu"
    assert manifest.runtime.profile == "pci-generic"
    assert manifest.test.executable is None
    assert manifest.test.subsystem is not None
    assert manifest.test.subsystem.tests[0].success_pattern == "EDU_TRACE_OK"


def test_normalize_ftgpio_preserves_complete_coverage_contract(tmp_path):
    result = normalize_input(
        ROOT / "benchmarks/drivers/baseline/gpio-ftgpio010.c",
        repo_root=ROOT,
        output_dir=tmp_path,
    )

    manifest = load_manifest(result["manifest"], repo_root=ROOT)

    assert result["profile_plan"]["id"] == "platform-generic"
    assert result["profile_plan"]["bus"] == "platform"
    assert result["profile_plan"]["subsystem_contracts"][0]["id"] == (
        "gpio-generic"
    )
    assert manifest.runtime.profile == "platform-generic"
    assert manifest.runtime.subsystem_contracts[0]["subsystem"] == "gpio"
    assert manifest.test.coverage is not None
    assert "line_event" in manifest.test.coverage.required
    assert "gpio_irq_chip.parent_handler" in manifest.test.coverage.callbacks
    assert manifest.test.subsystem is not None
    assert len(manifest.test.subsystem.tests) == 11


def test_normalize_multisource_descriptor_preserves_descriptor_and_is_inconclusive(
    tmp_path,
):
    result = normalize_input(
        ROOT / "benchmarks/drivers/multisource/dw-apb-ssi.json",
        repo_root=ROOT,
        output_dir=tmp_path,
    )

    assert result["input_kind"] == "descriptor"
    assert result["source"]["path"].endswith("dw-apb-ssi.json")
    assert result["profile"]["base"] == "platform-generic"
    assert result["status"] == "inconclusive"
    assert result["missing_capabilities"] == ["runtime_identity"]
    assert result["manifest"] is None


def test_normalize_multisource_descriptor_derives_bus_evidence_from_all_sources(
    tmp_path,
):
    descriptor = ROOT / "qa/tests/fixtures/spi-client.json"

    result = normalize_input(
        descriptor, repo_root=ROOT, output_dir=tmp_path)

    assert result["input_kind"] == "descriptor"
    assert result["profile"]["base"] == "spi-generic"
    assert result["profile_plan"]["bus"] == "spi"
    assert result["status"] == "ready"
    manifest = load_manifest(result["manifest"], repo_root=ROOT)
    assert manifest.runtime.qemu.module == "spi_client"
    assert manifest.runtime.fixture is not None
    assert manifest.runtime.fixture.config["module_args"]["spi-registrar"] == [
        "modalias=fixture_spi_client"
    ]


def test_spi_descriptor_fixture_uses_a_valid_transfer_payload():
    source = (ROOT / "qa/tests/fixtures/spi-client.c").read_text(
        encoding="utf-8")

    assert ".tx_buf" in source or ".rx_buf" in source


def test_normalize_generic_i2c_source_materializes_profile_owned_manifest(tmp_path):
    source = ROOT / "benchmarks/drivers/fixtures/reharness-i2c-sensor.c"

    result = normalize_input(source, repo_root=ROOT, output_dir=tmp_path)

    assert result["status"] == "ready"
    assert result["profile_plan"]["id"] == "i2c-generic"
    manifest = load_manifest(result["manifest"], repo_root=ROOT)
    assert manifest.runtime.qemu.module == "reharness_i2c_sensor"
    assert manifest.runtime.fixture is not None
    assert manifest.runtime.fixture.config["module_args"]["i2c-registrar"] == [
        "client_type=reharness_i2c_sens"
    ]
    assert manifest.runtime.registration.root_table == "i2c_driver"
    assert manifest.runtime.registration.device_id_tables == ("i2c_device_id",)


def test_normalize_generic_usb_source_materializes_identity_fixture(tmp_path):
    source = tmp_path / "renamed-usb-driver.c"
    source.write_text(
        "#define TEST_VENDOR 0x0403\n"
        "#define TEST_PRODUCT 0x6001\n"
        "static const struct usb_device_id ids[] = {\n"
        " { USB_DEVICE(TEST_VENDOR, TEST_PRODUCT) }, { } };\n"
        "static struct usb_driver driver = {\n"
        " .name = \"renamed_usb_sens\", .probe = usb_probe,\n"
        " .id_table = ids };\n",
        encoding="utf-8",
    )

    result = normalize_input(source, repo_root=tmp_path,
                             output_dir=tmp_path / "out")

    assert result["status"] == "ready"
    assert result["profile_plan"]["id"] == "usb-generic"
    manifest = load_manifest(result["manifest"], repo_root=tmp_path)
    assert manifest.runtime.profile == "usb-generic"
    assert manifest.runtime.fixture.config["vendor_id"] == "0x0403"
    assert manifest.runtime.fixture.config["product_id"] == "0x6001"
    assert manifest.runtime.qemu.module == "renamed_usb_driver"


def test_normalize_usb_source_without_device_id_is_inconclusive(tmp_path):
    source = tmp_path / "usb-without-id.c"
    source.write_text(
        "static struct usb_driver driver = { .name = \"missing_id\" };\n",
        encoding="utf-8",
    )

    result = normalize_input(source, repo_root=tmp_path,
                             output_dir=tmp_path / "out")

    assert result["status"] == "inconclusive"
    assert result["profile_plan"]["id"] == "usb-generic"
    assert result["missing_capabilities"] == ["runtime_vendor_id"]


def test_normalize_generic_platform_source_materializes_registrar_manifest(tmp_path):
    source = ROOT / "benchmarks/drivers/baseline/sdhci-esdhc-mcf.c"

    result = normalize_input(source, repo_root=ROOT, output_dir=tmp_path)

    assert result["status"] == "ready"
    assert result["profile_plan"]["id"] == "platform-generic"
    manifest = load_manifest(result["manifest"], repo_root=ROOT)
    assert manifest.runtime.qemu.registrar == "sdhci-esdhc-mcf"
    assert manifest.runtime.qemu.module == "sdhci_esdhc_mcf"
    assert manifest.runtime.qemu.binding.device_glob == "sdhci-esdhc-mcf"
    assert manifest.runtime.fixture.config["module_args"]["device-registrar"] == [
        "target=sdhci-esdhc-mcf"
    ]


def test_normalize_existing_manifest_pins_source_digest(tmp_path):
    source = tmp_path / "edu.c"
    source.write_text("int edu_driver(void) { return 0; }\n", encoding="utf-8")
    executable = tmp_path / "test-driver"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    document = {
        "schema": 2, "name": "pinned", "source": {"path": "edu.c", "sha256": digest},
        "compile": {"backend": "linux", "language": "c", "context": "kbuild"},
        "runtime": {"adapter": "qemu", "pci_identity": {"vendor": "0x1234", "device": "0x11e8"},
                     "qemu": {"machine": "pc", "device": "edu", "bus": "pci",
                              "module": "edu_drv", "timeout_seconds": 90}},
        "test": {"executable": "test-driver"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }
    path = tmp_path / "pinned.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = normalize_input(path, repo_root=tmp_path, output_dir=tmp_path / "out")

    assert result["input_kind"] == "manifest"
    assert result["status"] == "ready"
    assert result["manifest"] == str(path.resolve())
    assert result["source"]["sha256"] == digest


def test_normalize_rejects_pinned_manifest_when_source_changed(tmp_path):
    source = tmp_path / "edu.c"
    source.write_text("int edu_driver(void) { return 0; }\n", encoding="utf-8")
    executable = tmp_path / "test-driver"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    document = {
        "schema": 2, "name": "pinned", "source": {"path": "edu.c", "sha256": "0" * 64},
        "compile": {"backend": "linux", "language": "c", "context": "kbuild"},
        "runtime": {"adapter": "qemu", "pci_identity": {"vendor": "0x1234", "device": "0x11e8"},
                     "qemu": {"machine": "pc", "device": "edu", "bus": "pci",
                              "module": "edu_drv", "timeout_seconds": 90}},
        "test": {"executable": "test-driver"},
        "trace": {"fields": ["phase", "function", "kind", "width_bits", "address", "value", "sequence"]},
        "limits": {"compile": 1, "runtime": 1, "trace": 1},
    }
    path = tmp_path / "pinned.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(AutoDriverError, match="source digest mismatch"):
        normalize_input(path, repo_root=tmp_path, output_dir=tmp_path / "out")


def test_profile_override_rejects_unknown_profile():
    with pytest.raises(AutoDriverError, match="unknown runtime profile"):
        resolve_profile(
            ROOT / "benchmarks/drivers/baseline/edu.c",
            repo_root=ROOT,
            requested="does-not-exist",
        )


def test_unknown_driver_reports_missing_runtime_capabilities():
    result = normalize_input(
        ROOT / "benchmarks/drivers/baseline/sdhci-esdhc-mcf.c",
        repo_root=ROOT,
        output_dir=ROOT / "artifacts" / "langgraph" / "test-auto-driver",
    )

    assert result["status"] == "ready"
    assert result["profile"]["id"] == "platform-generic"
    assert result["profile_plan"]["bus"] == "platform"
    assert result["missing_capabilities"] == []


def test_normalize_matches_i2c_from_api_evidence_not_source_name(tmp_path):
    source = tmp_path / "renamed_sensor.c"
    source.write_text(
        """
        struct i2c_driver sensor_driver;
        static int sensor_probe(struct i2c_client *client) { return 0; }
        static const struct i2c_device_id sensor_ids[] = { { "sensor" } };
        module_i2c_driver(sensor_driver);
        """,
        encoding="utf-8",
    )

    result = normalize_input(source, repo_root=tmp_path,
                             output_dir=tmp_path / "out")

    assert result["status"] == "ready"
    assert result["profile"]["id"] == "i2c-generic"
    assert result["profile_plan"]["id"] == "i2c-generic"
    assert result["profile_plan"]["bus"] == "i2c"
    assert result["missing_capabilities"] == []


def test_auto_driver_cli_dry_run_emits_normalized_json(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "qa/verification/run_auto_driver.py"),
        str(ROOT / "benchmarks/drivers/baseline/edu.c"),
        "--dry-run",
        "--output-dir",
        str(tmp_path),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True,
                            capture_output=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["profile"]["id"] == "edu-pci"
    assert Path(payload["manifest"]).is_file()


def test_auto_driver_cli_dry_run_accepts_generic_spi_profile(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "qa/verification/run_auto_driver.py"),
        str(ROOT / "qa/tests/fixtures/spi-client.json"),
        "--dry-run",
        "--output-dir",
        str(tmp_path),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True,
                            capture_output=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["profile"]["id"] == "spi-generic"
    assert Path(payload["manifest"]).is_file()


def test_auto_driver_cli_returns_inconclusive_for_unknown_runtime(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "qa/verification/run_auto_driver.py"),
        str(ROOT / "benchmarks/drivers/multisource/dw-apb-ssi.json"),
        "--dry-run",
        "--output-dir",
        str(tmp_path),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True,
                            capture_output=True, check=False)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "inconclusive"
    assert payload["missing_capabilities"] == ["runtime_identity"]


def test_auto_driver_routes_static_generation_without_runtime_manifest(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_workflow(request, *, repo_root, profile_registry):
        calls.append(dict(request))
        return {"status": "inconclusive"}

    monkeypatch.setitem(
        sys.modules,
        "langgraph_workflow.graph",
        type("GraphModule", (), {"run_workflow": staticmethod(fake_workflow)}),
    )

    payload = run_auto_driver._workflow_result(
        {
            "source": {"path": "driver.c"},
            "manifest": None,
        },
        backend="linux",
        request="translate driver",
        output_dir="/tmp/reharness-test-output",
        profile_registry=object(),
    )

    assert payload["status"] == "inconclusive"
    assert calls[0]["mode"] == "generation"
    assert "experiment_manifest" not in calls[0]


def test_normalize_accepts_an_injected_profile_registry_without_core_changes(
    tmp_path,
):
    from driver_profiles import MatchResult, ProfilePlan, ProfileRegistry

    class UsbProfile:
        profile_id = "usb-generic"
        bus = "usb"

        def evidence_from_source(self, source_text):
            if "struct usb_driver" not in source_text:
                return {}
            return {
                "bus": "usb",
                "bindings": {"usb_driver.probe": "source-evidence"},
                "resources": {"usb_device": {"source": True}},
            }

        def match(self, evidence):
            return (MatchResult(self.profile_id, self.bus,
                                "usb profile evidence", 20)
                    if evidence.get("bus") == "usb" else None)

        def plan(self, evidence):
            return ProfilePlan(
                profile_id=self.profile_id,
                bus=self.bus,
                required_capabilities=("registration", "probe", "unload"),
                optional_capabilities=(),
                runtime_adapter="test-usb",
                fixture={"kind": "test-usb", "config": {}},
            )

    source = tmp_path / "renamed_usb_driver.c"
    source.write_text(
        "struct usb_driver sensor_driver;\n"
        "static int sensor_probe(void *device) { return 0; }\n",
        encoding="utf-8",
    )

    result = normalize_input(
        source, repo_root=tmp_path, output_dir=tmp_path / "out",
        profile_registry=ProfileRegistry((UsbProfile(),)),
    )

    assert result["status"] == "inconclusive"
    assert result["profile"]["id"] == "usb-generic"
    assert result["missing_capabilities"] == ["runtime_manifest"]


def test_profile_runtime_overrides_materialize_without_bus_specific_logic(
        tmp_path,
):
    from auto_driver import DriverProfile, _manifest_for_profile
    from driver_profiles import ProfilePlan

    source = tmp_path / "usb.c"
    source.write_text("struct usb_driver driver;\n", encoding="utf-8")
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({
            "runtime": {
                "adapter": "qemu-profile",
                "qemu": {"machine": "pc", "device": "usb-virtual"},
            },
            "test": {},
        }),
        encoding="utf-8",
    )
    plan = ProfilePlan(
        profile_id="usb-generic",
        bus="usb",
        required_capabilities=("registration",),
        optional_capabilities=(),
        runtime_adapter="qemu-usb",
        fixture={"kind": "qemu-usb", "config": {}},
        manifest_template=str(template),
        runtime_overrides={"qemu": {"registrar": "usb-fixture"}},
    )
    profile = DriverProfile("usb-generic", template, "usb-generic", plan)

    rendered = _manifest_for_profile(profile, source, tmp_path, plan)

    assert rendered["runtime"]["adapter"] == "qemu-usb"
    assert rendered["runtime"]["qemu"]["registrar"] == "usb-fixture"


def test_profile_runtime_override_preserves_declared_module_identity(tmp_path):
    from auto_driver import DriverProfile, _manifest_for_profile
    from driver_profiles import ProfilePlan

    source = tmp_path / "renamed.c"
    source.write_text("struct usb_driver driver;\n", encoding="utf-8")
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({
            "runtime": {
                "qemu": {"machine": "pc", "device": "usb-virtual",
                         "module": "template_module"},
            },
            "test": {},
        }),
        encoding="utf-8",
    )
    plan = ProfilePlan(
        profile_id="usb-generic",
        bus="usb",
        required_capabilities=("registration",),
        optional_capabilities=(),
        runtime_adapter="qemu-usb",
        fixture={"kind": "qemu-usb", "config": {}},
        manifest_template=str(template),
        runtime_overrides={"qemu": {"module": "fixture_module"}},
    )
    profile = DriverProfile("usb-generic", template, "usb-generic", plan)

    rendered = _manifest_for_profile(profile, source, tmp_path, plan)

    assert rendered["runtime"]["qemu"]["module"] == "fixture_module"


def test_auto_driver_cli_loads_profile_plugin_and_fails_closed_without_fixture(
        tmp_path, capsys,
):
    plugin = tmp_path / "usb_profile_plugin.py"
    plugin.write_text(
        """
from driver_profiles import MatchResult, ProfilePlan

class UsbPluginProfile:
    profile_id = 'usb-plugin'
    bus = 'usb'
    def evidence_from_source(self, source_text):
        if 'struct spi_driver' not in source_text:
            return {}
        return {'bus': 'usb', 'bindings': {'usb_driver.probe': True}}
    def match(self, evidence):
        return (MatchResult(self.profile_id, self.bus, 'plugin', 100)
                if evidence.get('bus') == 'usb' else None)
    def plan(self, evidence):
        return ProfilePlan(self.profile_id, self.bus, ('registration',), (),
                           'qemu-usb', {'kind': 'qemu-usb', 'config': {}})

def register_profiles(registry):
    registry.register(UsbPluginProfile())
""",
        encoding="utf-8",
    )

    exit_code = run_auto_driver.main([
        str(ROOT / "qa/tests/fixtures/spi-client.json"),
        "--profile-plugin", str(plugin), "--dry-run",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert payload["status"] == "inconclusive"
    assert payload["profile"]["id"] == "usb-plugin"
    assert payload["missing_capabilities"] == ["runtime_manifest"]


def test_auto_driver_cli_materializes_template_backed_external_profile(tmp_path):
    command = [
        sys.executable,
        str(ROOT / "qa/verification/run_auto_driver.py"),
        str(ROOT / "benchmarks/drivers/baseline/edu.c"),
        "--profile-plugin",
        str(ROOT / "qa/tests/fixtures/test_pci_profile_plugin.py"),
        "--dry-run",
        "--output-dir",
        str(tmp_path),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True,
                            capture_output=True, check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["profile"]["id"] == "test-pci-plugin"
    manifest = load_manifest(payload["manifest"], repo_root=ROOT)
    assert manifest.runtime.profile == "test-pci-plugin"
    assert manifest.runtime.qemu.module == "edu_drv"


def test_normalize_rejects_plugin_manifest_template_outside_trusted_root(tmp_path):
    from driver_profiles import MatchResult, ProfilePlan, ProfileRegistry

    source = tmp_path / "plugin_driver.c"
    source.write_text("struct pci_driver plugin_driver;\n", encoding="utf-8")
    outside_template = tmp_path.parent / "outside-plugin-template.json"
    outside_template.write_text("{}\n", encoding="utf-8")

    class OutsideTemplateProfile:
        profile_id = "outside-template-plugin"
        bus = "pci"

        def evidence_from_source(self, source_text):
            if "struct pci_driver" not in source_text:
                return {}
            return {"bus": "pci", "bindings": {"pci_driver.probe": True}}

        def match(self, evidence):
            if evidence.get("bus") != self.bus:
                return None
            return MatchResult(self.profile_id, self.bus, "test", 100)

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, self.bus, ("registration",), (),
                "qemu-profile", {"kind": "qemu-pci", "config": {}},
                manifest_template=str(outside_template),
            )

    with pytest.raises(AutoDriverError, match="manifest template.*outside"):
        normalize_input(
            source, repo_root=tmp_path, output_dir=tmp_path / "out",
            profile_registry=ProfileRegistry((OutsideTemplateProfile(),)),
        )
