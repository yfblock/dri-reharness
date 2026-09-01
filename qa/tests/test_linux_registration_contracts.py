from __future__ import annotations

import json
from pathlib import Path

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from linux_registration_contracts import (  # noqa: E402
    LinuxRegistrationContractError,
    load_linux_registration_catalog,
    resolve_linux_registration_policy,
)


def test_builtin_catalog_resolves_root_api_tables_and_links():
    root = _paths.REPO_ROOT
    policy = resolve_linux_registration_policy(
        {"root_table": "spi_driver", "device_id_tables": ["spi_device_id"]},
        root=root,
    )

    assert policy["root_tables"] == frozenset({
        "platform_driver", "pci_driver", "i2c_driver", "spi_driver",
        "usb_driver", "virtio_driver", "amba_driver",
        "serdev_device_driver", "mdio_driver", "net_device",
    })
    assert policy["registration_apis"]["__spi_register_driver"] == {
        "kind": "driver_root",
        "arg": 1,
        "type": "struct spi_driver *",
        "table": "spi_driver",
    }
    assert policy["struct_tables"]["spi_driver"] == "spi_driver"
    assert "spi_driver" in policy["supported_callback_tables"]
    assert policy["link_tables"][("platform_driver", "pm")] == "dev_pm_ops"
    assert "spi_device_id" in policy["device_id_tables"]


def test_builtin_catalog_includes_usb_and_virtio_root_registration():
    policy = resolve_linux_registration_policy()

    assert {"usb_driver", "virtio_driver"} <= policy["root_tables"]
    assert policy["registration_apis"]["usb_register_driver"] == {
        "kind": "driver_root", "arg": 0,
        "type": "struct usb_driver *", "table": "usb_driver",
    }
    assert policy["registration_apis"]["register_virtio_driver"] == {
        "kind": "driver_root", "arg": 0,
        "type": "struct virtio_driver *", "table": "virtio_driver",
    }


def test_builtin_catalog_includes_amba_serdev_and_mdio_registration():
    policy = resolve_linux_registration_policy()

    assert {"amba_driver", "serdev_device_driver", "mdio_driver"} <= (
        policy["root_tables"])
    assert policy["registration_apis"]["amba_driver_register"] == {
        "kind": "driver_root", "arg": 0,
        "type": "struct amba_driver *", "table": "amba_driver",
    }
    assert policy["registration_apis"]["serdev_device_driver_register"] == {
        "kind": "driver_root", "arg": 0,
        "type": "struct serdev_device_driver *",
        "table": "serdev_device_driver",
    }
    assert policy["registration_apis"]["mdio_driver_register"] == {
        "kind": "driver_root", "arg": 0,
        "type": "struct mdio_driver *", "table": "mdio_driver",
    }


def test_builtin_catalog_includes_network_object_root_registration():
    policy = resolve_linux_registration_policy()

    assert "net_device" in policy["root_tables"]
    assert "net_device_ops" in policy["supported_callback_tables"]
    assert policy["registration_apis"]["register_netdev"] == {
        "kind": "object_root", "arg": 0,
        "type": "struct net_device *", "table": "net_device",
    }
    assert policy["link_tables"][("net_device", "netdev_ops")] == (
        "net_device_ops")


def test_builtin_catalog_owns_external_module_macro_rewrites():
    policy = resolve_linux_registration_policy()

    assert policy["builtin_driver_macros"]["builtin_platform_driver"] == (
        "module_platform_driver")
    assert policy["builtin_driver_macros"]["builtin_serdev_device_driver"] == (
        "module_serdev_device_driver")


def test_builtin_catalog_owns_legacy_runtime_identity_contracts():
    policy = resolve_linux_registration_policy()

    assert policy["legacy_runtime_contracts"]["platform"] == {
        "root_table": "platform_driver",
        "identity_field": "registrar",
        "device_id_tables": [],
    }
    assert policy["legacy_runtime_contracts"]["i2c"] == {
        "root_table": "i2c_driver",
        "identity_field": "driver_name",
        "device_id_tables": ["i2c_device_id"],
    }
    assert policy["legacy_runtime_contracts"]["amba"]["root_table"] == (
        "amba_driver")


def test_builtin_catalog_owns_irq_argument_contracts():
    policy = resolve_linux_registration_policy()

    assert policy["irq_attach_apis"]["gpio_irq_chip_set_chip"] == {
        "parent_arg": 0, "child_arg": 1,
    }
    assert policy["direct_irq_apis"]["request_threaded_irq"] == {
        "handler_args": (1, 2), "data_arg": 4,
    }


def test_catalog_rejects_duplicate_registration_api(tmp_path: Path):
    document = {
        "schema": 1,
        "tables": [{"id": "foo_driver", "record": "foo_driver", "role": "root"}],
        "registration_apis": [
            {"name": "foo_register", "kind": "driver_root", "argument": 0,
             "type": "struct foo_driver *", "table": "foo_driver"},
            {"name": "foo_register", "kind": "driver_root", "argument": 0,
             "type": "struct foo_driver *", "table": "foo_driver"},
        ],
        "links": [],
    }
    path = tmp_path / "linux-registration-catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(LinuxRegistrationContractError, match="duplicate"):
        load_linux_registration_catalog(tmp_path)


def test_plugin_contract_can_declare_a_new_root_shape_without_oracle_code():
    policy = resolve_linux_registration_policy({
        "root_table": "foo_driver",
        "identity_field": "driver_name",
        "registration_apis": [{
            "name": "foo_register_driver",
            "kind": "driver_root",
            "argument": 0,
            "type": "struct foo_driver *",
            "table": "foo_driver",
        }],
        "tables": [{
            "id": "foo_driver",
            "record": "foo_driver",
            "role": "root",
        }, {
            "id": "foo_ops",
            "record": "foo_ops",
            "role": "callback",
        }],
        "links": [{
            "owner_table": "foo_driver",
            "field": "ops",
            "target_table": "foo_ops",
        }],
    })

    assert policy["registration_apis"]["foo_register_driver"]["arg"] == 0
    assert policy["struct_tables"]["foo_ops"] == "foo_ops"
    assert ("foo_driver", "ops") in policy["link_tables"]
    assert "foo_ops" in policy["supported_callback_tables"]


def test_plugin_contract_rejects_api_table_mismatch():
    with pytest.raises(LinuxRegistrationContractError, match="table"):
        resolve_linux_registration_policy({
            "root_table": "foo_driver",
            "registration_apis": [{
                "name": "foo_register_driver",
                "kind": "driver_root",
                "argument": 0,
                "type": "struct foo_driver *",
                "table": "bar_driver",
            }],
        })
