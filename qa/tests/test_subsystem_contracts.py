from __future__ import annotations

import json

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from subsystem_contracts import (  # noqa: E402
    SubsystemContractCatalogError,
    build_default_contract_registry,
    load_subsystem_contract_definitions,
)


def test_contract_registry_detects_multiple_independent_subsystems():
    registry = build_default_contract_registry()

    matches = registry.detect(
        """
        struct gpio_chip chip;
        static const struct clk_ops clock_ops = { 0 };
        gpiochip_add_data(&chip, NULL);
        clk_register(NULL, NULL);
        """,
        evidence={
            "bindings": {"gpio_chip.set": "set_value"},
            "resources": {"clk_hw": {}},
        },
    )

    assert {item.contract_id for item in matches} == {
        "gpio-generic", "clock-generic",
    }
    assert all(item.required_capabilities for item in matches)


def test_contract_match_carries_data_driven_summary_declarations():
    matches = build_default_contract_registry().detect(
        "struct gpio_chip chip; gpiochip_add_data(&chip, NULL);",
    )

    gpio = next(item for item in matches if item.contract_id == "gpio-generic")
    assert gpio.summary_groups == ("gpio_generic",)
    assert gpio.summary_contracts == ("linux.gpio_generic_chip_config",)


def test_contract_detection_is_independent_of_transport_bus():
    matches = build_default_contract_registry().detect(
        "struct sdhci_ops ops; sdhci_add_host(host, mmc);",
        evidence={"bus": "pci"},
    )

    assert [item.contract_id for item in matches] == ["sdhci-generic"]
    assert matches[0].subsystem == "sdhci"


def test_contract_catalog_rejects_unknown_fields_and_unsafe_paths(tmp_path):
    catalog_dir = tmp_path / "benchmarks"
    catalog_dir.mkdir()
    base = {
        "contract_id": "test-contract",
        "subsystem": "test",
        "callback_keys": ["test.ops"],
        "resource_keys": ["test_device"],
        "source_tokens": ["struct test_ops"],
        "required_capabilities": ["static_analysis"],
    }
    base["unexpected"] = True
    (catalog_dir / "subsystem-contract-definitions.json").write_text(
        json.dumps({"schema": 1, "contracts": [base]}), encoding="utf-8"
    )

    with pytest.raises(SubsystemContractCatalogError, match="unknown field"):
        load_subsystem_contract_definitions(tmp_path)


def test_platform_profile_plan_carries_subsystem_contracts(tmp_path):
    source = tmp_path / "renamed-platform.c"
    source.write_text(
        """
        struct gpio_chip chip;
        static int probe(void) { return gpiochip_add_data(&chip, 0); }
        static struct platform_driver driver = {
            .driver = { .name = "generic-gpio" }, .probe = probe,
        };
        module_platform_driver(driver);
        """,
        encoding="utf-8",
    )

    from auto_driver import resolve_profile

    profile = resolve_profile(source, repo_root=tmp_path)

    assert profile is not None
    assert profile.plan.subsystem_contracts[0]["id"] == "gpio-generic"
    assert profile.plan.subsystem_contracts[0]["subsystem"] == "gpio"
