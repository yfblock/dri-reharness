from __future__ import annotations


def test_subsystem_modules_expose_shared_private_helpers():
    from extractor.subsystem import gpio, sdhci, virtio

    for module in (gpio, sdhci, virtio):
        assert hasattr(module, "_base_store")
        assert hasattr(module, "_summary_evidence")
        assert hasattr(module, "_GPIO_CONFIG_FIELDS")
