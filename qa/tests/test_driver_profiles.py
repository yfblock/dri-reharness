from __future__ import annotations

import json
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from driver_profiles import (  # noqa: E402
    MatchResult,
    ProfileCatalogError,
    ProfileMatchError,
    ProfilePlan,
    ProfileRegistry,
    build_default_registry,
    load_profile_definitions,
    load_profile_plugins,
)


def test_registry_matches_bus_from_extracted_evidence():
    registry = build_default_registry()

    result = registry.match({
        "bindings": {"i2c_driver.probe": "sensor_probe"},
        "resources": {"i2c_client": {}},
    })

    assert result.profile_id == "i2c-generic"
    assert result.reason == "i2c callback and client evidence"


def test_registry_matches_each_initial_bus_family():
    registry = build_default_registry()

    cases = [
        ({"bindings": {"platform_driver.probe": "probe"},
          "resources": {"platform_device": {}}}, "platform-generic"),
        ({"bindings": {"pci_driver.probe": "probe"},
          "resources": {"pci_device": {}}}, "pci-generic"),
        ({"bindings": {"i2c_driver.probe": "probe"},
          "resources": {"i2c_client": {}}}, "i2c-generic"),
        ({"bindings": {"spi_driver.probe": "probe"},
          "resources": {"spi_device": {}}}, "spi-generic"),
        ({"bindings": {"virtio_driver.probe": "probe"},
          "resources": {"virtio_device": {}}}, "virtio-generic"),
    ]

    for evidence, expected in cases:
        assert registry.match(evidence).profile_id == expected


def test_registry_matches_additional_linux_bus_families_from_declarative_catalog():
    registry = build_default_registry()

    cases = [
        ("amba-generic", "amba_driver.probe", "amba_device"),
        ("serdev-generic", "serdev_device_driver.probe", "serdev_device"),
        ("mdio-generic", "mdio_driver.probe", "mdio_device"),
    ]

    for expected, callback, resource in cases:
        result = registry.match({
            "bindings": {callback: "probe"},
            "resources": {resource: {}},
        })
        assert result.profile_id == expected


def test_registry_matches_network_device_subsystem_from_declarative_catalog():
    registry = build_default_registry()

    result = registry.match({
        "bindings": {"net_device_ops": "netdev_ops"},
        "resources": {"net_device": {}},
    })

    assert result.profile_id == "network-generic"
    plan = registry.resolve({
        "bindings": {"net_device_ops": "netdev_ops"},
        "resources": {"net_device": {}},
    }).plan
    assert plan is not None
    assert plan.bus == "network"
    assert plan.fixture["kind"] == "qemu-network"
    assert "subsystem" in plan.required_capabilities
    assert plan.manifest_template == (
        "benchmarks/profile-templates/network-generic.json")
    assert plan.registration_contract == {
        "root_table": "net_device",
        "identity_field": "none",
        "device_id_tables": [],
    }


def test_registry_extracts_network_device_source_evidence():
    registry = build_default_registry()
    source = """
    static const struct net_device_ops demo_netdev_ops = {
        .ndo_open = demo_open,
        .ndo_stop = demo_stop,
        .ndo_start_xmit = demo_xmit,
    };
    static int demo_init(void) {
        struct net_device *dev = alloc_netdev(0, "eth%d", NET_NAME_UNKNOWN,
                                               ether_setup);
        dev->netdev_ops = &demo_netdev_ops;
        return register_netdev(dev);
    }
    """

    evidence = registry.evidence_from_source(source)

    assert evidence["bus"] == "network"
    assert "net_device_ops" in evidence["bindings"]
    assert "net_device" in evidence["resources"]


def test_registry_extracts_amba_driver_name_from_drv_field():
    registry = build_default_registry()
    source = """
    static int demo_probe(struct amba_device *adev,
                          const struct amba_id *id) { return 0; }
    static const struct amba_id demo_ids[] = { { .id = 1, .mask = 1 }, { } };
    static struct amba_driver demo_driver = {
        .drv = { .name = \"demo_amba\" },
        .probe = demo_probe,
        .id_table = demo_ids,
    };
    module_amba_driver(demo_driver);
    """

    evidence = registry.evidence_from_source(source)

    assert evidence["bus"] == "amba"
    assert evidence["identity"]["driver_name"] == "demo_amba"


def test_serdev_profile_without_fixture_remains_runtime_unavailable():
    registry = build_default_registry()

    profile = next(item for item in registry.profiles
                   if item.profile_id == "serdev-generic")
    plan = profile.plan({})
    assert plan.manifest_template is None
    assert getattr(profile, "matrix_required") is False


def test_amba_profile_has_a_declarative_runtime_fixture():
    registry = build_default_registry()
    profile = next(item for item in registry.profiles
                   if item.profile_id == "amba-generic")
    plan = profile.plan({})

    assert plan.manifest_template == (
        "benchmarks/profile-templates/amba-generic.json")
    assert plan.fixture["kind"] == "qemu-amba"
    assert plan.required_capabilities == (
        "registration", "probe", "subsystem", "unload")
    assert getattr(profile, "matrix_required") is True


def test_mdio_profile_is_runtime_ready_after_fixture_registration():
    registry = build_default_registry()
    profile = next(item for item in registry.profiles
                   if item.profile_id == "mdio-generic")

    assert profile.plan({}).manifest_template is None
    assert profile.matrix_required is True


def test_registry_matches_usb_driver_and_extracts_fixture_identity():
    registry = build_default_registry()
    source = """
    #define TEST_USB_VENDOR 0x0403
    #define TEST_USB_PRODUCT 0x6001
    static const struct usb_device_id ids[] = {
        { USB_DEVICE(TEST_USB_VENDOR, TEST_USB_PRODUCT) }, { }
    };
    static int usb_probe(struct usb_interface *interface,
                         const struct usb_device_id *id) { return 0; }
    static struct usb_driver driver = {
        .name = "reharness_usb_sens",
        .probe = usb_probe,
        .id_table = ids,
    };
    """

    evidence = registry.evidence_from_source(source)
    assert evidence["bus"] == "usb"
    assert "usb_driver.probe" in evidence["bindings"]
    assert "usb_device" in evidence["resources"]
    assert evidence["identity"]["vendor_id"] == "0x0403"
    assert evidence["identity"]["product_id"] == "0x6001"

    resolution = registry.resolve(evidence)
    assert resolution.plan is not None
    assert resolution.plan.profile_id == "usb-generic"
    assert resolution.plan.required_capabilities == (
        "registration", "probe", "transfer", "unload")
    assert resolution.plan.fixture["config"]["vendor_id"] == "0x0403"
    assert resolution.plan.fixture["config"]["product_id"] == "0x6001"


def test_registry_rejects_ambiguous_evidence():
    registry = build_default_registry()

    with pytest.raises(ProfileMatchError, match="ambiguous"):
        registry.match({
            "bindings": {
                "platform_driver.probe": "platform_probe",
                "pci_driver.probe": "pci_probe",
            },
            "resources": {
                "platform_device": {},
                "pci_device": {},
            },
        })


def test_registry_returns_missing_runtime_capability_for_unknown_bus():
    result = build_default_registry().resolve({
        "bindings": {"foo.probe": "probe"},
    })

    assert result.profile is None
    assert result.missing_capabilities == ("runtime_profile",)


def test_profile_plan_is_data_only_and_declares_runtime_capabilities():
    plan = build_default_registry().resolve({
        "bindings": {"spi_driver.probe": "sensor_probe"},
        "resources": {"spi_device": {"modalias": "reharness-sensor"}},
    }).plan

    assert plan is not None
    assert plan.profile_id == "spi-generic"
    assert plan.bus == "spi"
    assert "registration" in plan.required_capabilities
    assert plan.runtime_adapter == "qemu-profile"
    assert plan.fixture["kind"] == "qemu-spi"
    assert plan.registration_contract == {
        "root_table": "spi_driver",
        "identity_field": "driver_name",
        "device_id_tables": ["spi_device_id"],
    }


def test_generic_profiles_use_profile_owned_manifest_templates():
    registry = build_default_registry()

    plans = {
        profile.profile_id: profile.plan({})
        for profile in registry.profiles
        if profile.profile_id in {"platform-generic", "i2c-generic", "spi-generic"}
    }

    assert plans["platform-generic"].manifest_template == (
        "benchmarks/profile-templates/platform-generic.json")
    assert plans["i2c-generic"].manifest_template == (
        "benchmarks/profile-templates/i2c-generic.json")
    assert plans["spi-generic"].manifest_template == (
        "benchmarks/profile-templates/spi-generic.json")


def test_builtin_profile_templates_use_bus_neutral_runtime_adapter():
    root = Path(__file__).resolve().parents[2]
    registry = build_default_registry()
    templates = {
        profile.manifest_template
        for profile in registry.profiles
        if profile.manifest_template is not None
    }
    for relative in templates:
        template = root / relative
        document = json.loads(template.read_text(encoding="utf-8"))
        assert document["runtime"]["adapter"] == "qemu-profile"


def test_virtio_profile_declares_queue_runtime_contract():
    resolution = build_default_registry().resolve({
        "bindings": {"virtio_driver.probe": "probe"},
        "resources": {"virtio_device": {}},
    })

    assert resolution.plan is not None
    assert resolution.plan.profile_id == "virtio-generic"
    assert "transfer" in resolution.plan.required_capabilities
    assert resolution.plan.fixture["kind"] == "qemu-virtio"
    assert resolution.plan.manifest_template == (
        "benchmarks/profile-templates/virtio-generic.json")


def test_usb_and_virtio_profiles_declare_linux_registration_identity():
    registry = build_default_registry()
    expected = {
        "usb-generic": ("usb_driver", "driver_name", []),
        "virtio-generic": ("virtio_driver", "driver_name", []),
    }

    for profile_id, contract in expected.items():
        profile = next(item for item in registry.profiles
                       if item.profile_id == profile_id)
        assert profile.plan({}).registration_contract == {
            "root_table": contract[0],
            "identity_field": contract[1],
            "device_id_tables": contract[2],
        }


class _UsbProfile:
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
        if (evidence.get("bus") == "usb"
                and "usb_driver.probe" in evidence.get("bindings", {})):
            from driver_profiles import MatchResult
            return MatchResult(self.profile_id, self.bus,
                               "usb profile evidence", 20)
        return None

    def plan(self, evidence):
        return ProfilePlan(
            profile_id=self.profile_id,
            bus=self.bus,
            required_capabilities=("registration", "probe", "unload"),
            optional_capabilities=(),
            runtime_adapter="test-usb",
            fixture={"kind": "test-usb", "config": {}},
        )


def test_registry_collects_source_evidence_from_registered_profile():
    registry = ProfileRegistry((_UsbProfile(),))

    evidence = registry.evidence_from_source("struct usb_driver sensor_driver;")

    assert evidence["bus"] == "usb"
    assert registry.match(evidence).profile_id == "usb-generic"


def test_profile_plugin_registers_without_modifying_default_registry(tmp_path):
    plugin = tmp_path / "usb_profile_plugin.py"
    plugin.write_text(
        """
from driver_profiles import MatchResult, ProfilePlan

class UsbPluginProfile:
    profile_id = 'usb-plugin'
    bus = 'usb'
    def evidence_from_source(self, source_text):
        return {'bus': 'usb', 'bindings': {'usb_driver.probe': True}}
    def match(self, evidence):
        if evidence.get('bus') == 'usb':
            return MatchResult(self.profile_id, self.bus, 'plugin', 100)
        return None
    def plan(self, evidence):
        return ProfilePlan(self.profile_id, self.bus, ('registration',), (),
                           'qemu-usb', {'kind': 'qemu-usb', 'config': {}})

def register_profiles(registry):
    registry.register(UsbPluginProfile())
""",
        encoding="utf-8",
    )

    registry = build_default_registry()
    load_profile_plugins((plugin,), registry)

    assert registry.match({"bus": "usb"}).profile_id == "usb-plugin"
    assert all(profile.profile_id != "usb-plugin"
               for profile in build_default_registry().profiles)


def test_registry_rejects_plugin_returning_non_profile_plan():
    class InvalidPlanProfile:
        profile_id = "invalid-plan"
        bus = "usb"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                from driver_profiles import MatchResult
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return {"profile_id": self.profile_id}

    registry = ProfileRegistry((InvalidPlanProfile(),))

    with pytest.raises(ProfileMatchError, match="invalid-plan.*ProfilePlan"):
        registry.resolve({"bus": "usb"})


def test_registry_rejects_duplicate_plugin_capabilities():
    class DuplicateCapabilityProfile:
        profile_id = "duplicate-capability"
        bus = "usb"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                from driver_profiles import MatchResult
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, self.bus,
                ("registration", "registration"), (),
                "test-usb", {"kind": "test-usb", "config": {}},
            )

    registry = ProfileRegistry((DuplicateCapabilityProfile(),))

    with pytest.raises(ProfileMatchError, match="duplicate-capability.*required"):
        registry.resolve({"bus": "usb"})


def test_registry_rejects_plugin_with_non_mapping_fixture():
    class InvalidFixtureProfile:
        profile_id = "invalid-fixture"
        bus = "usb"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                from driver_profiles import MatchResult
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, self.bus, ("registration",), (),
                "test-usb", "not-a-fixture",
            )

    registry = ProfileRegistry((InvalidFixtureProfile(),))

    with pytest.raises(ProfileMatchError, match="invalid-fixture.*fixture"):
        registry.resolve({"bus": "usb"})


def test_registry_rejects_plugin_plan_with_profile_bus_mismatch():
    class WrongBusProfile:
        profile_id = "wrong-bus-plugin"
        bus = "declared-bus"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, "different-bus", ("registration",), (),
                "qemu-profile", {"kind": "qemu-plugin", "config": {}},
            )

    with pytest.raises(ProfileMatchError, match="wrong-bus-plugin.*bus"):
        ProfileRegistry((WrongBusProfile(),)).resolve({"bus": "declared-bus"})


def test_registry_rejects_plugin_with_unsafe_profile_id():
    class UnsafeProfile:
        profile_id = "unsafe/plugin"
        bus = "plugin-bus"

    with pytest.raises(ProfileCatalogError, match="profile_id"):
        ProfileRegistry().register(UnsafeProfile())


def test_registry_rejects_plugin_plan_with_non_mapping_runtime_overrides():
    class InvalidOverridesProfile:
        profile_id = "invalid-overrides"
        bus = "plugin-bus"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, self.bus, ("registration",), (),
                "qemu-profile", {"kind": "qemu-plugin", "config": {}},
                runtime_overrides="not-a-mapping",
            )

    with pytest.raises(ProfileMatchError, match="invalid-overrides.*runtime_overrides"):
        ProfileRegistry((InvalidOverridesProfile(),)).resolve({"bus": "plugin-bus"})


def test_declarative_profile_definition_adds_profile_without_python_registration(tmp_path):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    (catalog_dir / "driver-profile-definitions.json").write_text(
        """
        {
          "schema": 1,
          "profiles": [
            {
              "profile_id": "watchdog-generic",
              "bus": "platform",
              "callback": "watchdog_ops.start",
              "resource": "watchdog_device",
              "fixture_kind": "qemu-platform",
              "required_capabilities": ["registration", "probe", "unload"],
              "optional_capabilities": ["subsystem"],
              "callback_tokens": ["struct watchdog_ops"],
              "resource_tokens": ["struct watchdog_device"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    registry = build_default_registry(tmp_path)

    result = registry.match({
        "bindings": {"watchdog_ops.start": "start"},
        "resources": {"watchdog_device": {}},
    })

    assert result.profile_id == "watchdog-generic"
    assert load_profile_definitions(tmp_path).profiles[-1].profile_id == (
        "watchdog-generic"
    )


def test_declarative_profile_plan_templates_support_an_arbitrary_bus(tmp_path):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    (catalog_dir / "driver-profile-definitions.json").write_text(
        json.dumps({
            "schema": 1,
            "profiles": [{
                "profile_id": "watchdog-generic",
                "bus": "watchdog",
                "callback": "watchdog_driver.probe",
                "resource": "watchdog_device",
                "fixture_kind": "qemu-watchdog",
                "required_capabilities": ["registration"],
                "callback_tokens": ["struct watchdog_driver"],
                "resource_tokens": ["struct watchdog_device"],
                "required_fixture_fields": ["driver_name"],
                "plan_templates": {
                    "fixture_config": {
                        "registrar_target": "{driver_name}",
                        "module_args": {
                            "watchdog-registrar": [
                                "target={driver_name}"
                            ]
                        }
                    },
                    "runtime_overrides": {
                        "qemu": {
                            "registrar": "{driver_name}",
                            "binding": {
                                "bus": "watchdog",
                                "device_glob": "{driver_name}"
                            }
                        }
                    }
                }
            }],
        }),
        encoding="utf-8",
    )

    registry = build_default_registry(tmp_path)
    profile = registry.profiles[0]
    plan = profile.plan({"identity": {"driver_name": "watchdog0"}})

    assert plan.fixture["config"] == {
        "driver_name": "watchdog0",
        "registrar_target": "watchdog0",
        "module_args": {"watchdog-registrar": ["target=watchdog0"]},
    }
    assert plan.runtime_overrides["qemu"]["binding"] == {
        "bus": "watchdog", "device_glob": "watchdog0"
    }


def test_declarative_profile_can_extend_linux_registration_shape(tmp_path):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    registration = {
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
    (catalog_dir / "driver-profile-definitions.json").write_text(
        json.dumps({
            "schema": 1,
            "profiles": [{
                "profile_id": "watchdog-generic",
                "bus": "watchdog",
                "callback": "watchdog_driver.probe",
                "resource": "watchdog_device",
                "fixture_kind": "qemu-watchdog",
                "required_capabilities": ["registration"],
                "registration_contract": registration,
            }],
        }),
        encoding="utf-8",
    )

    plan = load_profile_definitions(tmp_path).profiles[0].plan({})

    assert plan.registration_contract == {
        **registration,
        "device_id_tables": [],
    }


def test_normalizer_uses_declarative_profile_catalog_from_repo_root(tmp_path):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    (catalog_dir / "driver-profile-definitions.json").write_text(
        json.dumps({
            "schema": 1,
            "profiles": [{
                "profile_id": "watchdog-generic",
                "bus": "platform",
                "callback": "watchdog_ops.start",
                "resource": "watchdog_device",
                "fixture_kind": "qemu-platform",
                "required_capabilities": ["registration"],
                "callback_tokens": ["struct watchdog_ops"],
                "resource_tokens": ["struct watchdog_device"],
            }],
        }),
        encoding="utf-8",
    )
    source = tmp_path / "renamed.c"
    source.write_text(
        "struct watchdog_ops ops; struct watchdog_device device;\n",
        encoding="utf-8",
    )

    from auto_driver import normalize_input

    result = normalize_input(source, repo_root=tmp_path,
                             output_dir=tmp_path / "out")

    assert result["profile"]["id"] == "watchdog-generic"
    assert result["status"] == "inconclusive"
    assert result["missing_capabilities"] == ["runtime_manifest"]


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("unexpected", True, "unknown field"),
        ("manifest_template", "../outside.json", "outside repository"),
        ("plan_templates", {
            "fixture_config": {"target": "{untrusted_field}"}
        }, "unknown placeholder"),
        ("registration_contract", {
            "root_table": "../outside"
        }, "root_table is unsafe"),
        ("registration_contract", {
            "root_table": "watchdog_driver",
            "registration_apis": [{"name": "watchdog_register"}],
        }, "registration_apis"),
    ],
)
def test_declarative_profile_definition_fails_closed(tmp_path, field, value, message):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    entry = {
        "profile_id": "unsafe-profile",
        "bus": "platform",
        "callback": "unsafe.probe",
        "resource": "unsafe_device",
        "fixture_kind": "qemu-platform",
        "required_capabilities": ["registration"],
        field: value,
    }
    (catalog_dir / "driver-profile-definitions.json").write_text(
        json.dumps({"schema": 1, "profiles": [entry]}), encoding="utf-8"
    )

    with pytest.raises(ProfileCatalogError, match=message):
        load_profile_definitions(tmp_path)
