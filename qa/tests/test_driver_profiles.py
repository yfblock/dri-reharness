from __future__ import annotations

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from driver_profiles import (  # noqa: E402
    ProfileMatchError,
    build_default_registry,
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
    ]

    for evidence, expected in cases:
        assert registry.match(evidence).profile_id == expected


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
