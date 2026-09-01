from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from experiment_manifest import load_manifest  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COVERAGE = {
    "chip_info",
    "line_info",
    "v2_single_line",
    "v2_multi_line",
    "v2_values",
    "v1_single_line",
    "config_flags",
    "config_debounce",
    "error_paths",
    "line_event",
    "lifecycle",
}
EXPECTED_CALLBACKS = {
    "gpio_chip.get",
    "gpio_chip.get_multiple",
    "gpio_chip.set",
    "gpio_chip.set_multiple",
    "gpio_chip.direction_input",
    "gpio_chip.direction_output",
    "gpio_chip.get_direction",
    "gpio_chip.set_config",
    "irq_chip.irq_ack",
    "irq_chip.irq_mask",
    "irq_chip.irq_unmask",
    "irq_chip.irq_set_type",
    "gpio_irq_chip.parent_handler",
}


def test_ftgpio_manifest_declares_complete_gpio_coverage_matrix():
    path = ROOT / "benchmarks/experiments/ftgpio010.json"
    manifest = load_manifest(path, repo_root=ROOT)

    assert manifest.test.coverage is not None
    assert set(manifest.test.coverage.required) == EXPECTED_COVERAGE
    assert set(manifest.test.coverage.callbacks) == EXPECTED_CALLBACKS

    subsystem = manifest.test.subsystem
    assert subsystem is not None
    names = {item.name for item in subsystem.tests}
    assert names == {
        "gpio-chip-info",
        "gpio-line-info",
        "gpio-v2-basic",
        "gpio-v2-multi-line",
        "gpio-v1-compat",
        "gpio-config",
        "gpio-errors",
        "gpio-events",
        "gpio-lifecycle",
        "linux-gpio-chip-info",
        "linux-gpio-line-name",
    }


def test_ftgpio_manifest_reuses_linux_gpio_selftest_helpers():
    from experiment_manifest import load_manifest

    manifest = load_manifest(
        ROOT / "benchmarks/experiments/ftgpio010.json", repo_root=ROOT)
    by_provider = {item.provider: item
                   for item in manifest.test.subsystem.tests
                   if item.provider is not None}
    assert set(by_provider) == {"linux-gpio-chip-info", "linux-gpio-line-name"}
    for item in by_provider.values():
        assert item.kind == "kselftest"
        assert item.executable is not None
        assert "selftests/gpio" in str(item.executable)


def test_ftgpio_manifest_uses_only_repository_native_gpio_assets():
    document = json.loads(
        (ROOT / "benchmarks/experiments/ftgpio010.json").read_text(
            encoding="utf-8"))
    tests = document["test"]["subsystem"]["tests"]

    for item in tests:
        if "executable" not in item:
            continue
        if "executable" not in item:
            continue
        executable = ROOT / item["executable"]
        assert executable.is_file(), item["executable"]
        assert executable.suffix == ".c"


def test_qemu_kernel_enables_both_gpio_character_device_abis():
    config = (ROOT / "platform/kernel/linux-x86_64.config").read_text(
        encoding="utf-8")

    assert "CONFIG_GPIO_CDEV=y" in config
    assert "CONFIG_GPIO_CDEV_V1=y" in config


def test_gpio_registrar_provides_a_clock_for_debounce_testing():
    source = (ROOT / "qa/verification/device-registrar/device-registrar.c").read_text(
        encoding="utf-8")

    assert "clk_register_fixed_rate" in source
    assert "clkdev_create" in source
    assert "module_param(clock_rate" in source


def test_gpio_registrar_can_find_generated_chips_with_a_different_label():
    source = (ROOT / "qa/verification/device-registrar/device-registrar.c").read_text(
        encoding="utf-8")

    assert "gpio_device_find(NULL" in source


def test_gpio_registrar_injects_parent_irq_from_irq_work_context():
    source = (ROOT / "qa/verification/device-registrar/device-registrar.c").read_text(
        encoding="utf-8")

    assert "irq_work_queue" in source
    assert "wait_for_completion" in source


def test_gpio_registrar_injects_child_irq_from_irq_work_context():
    source = (ROOT / "qa/verification/device-registrar/device-registrar.c").read_text(
        encoding="utf-8")

    assert "gpio_event_work_fn" in source
    assert "gpio_event_domain" in source
    assert "init_irq_work(&gpio_parent_work, gpio_event_work_fn)" in source
