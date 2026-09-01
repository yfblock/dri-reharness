from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runner_and_llm_bridge_have_no_target_literals_or_branches():
    synthesis_module = next(ROOT.glob("src/synth*.py"))
    paths = [synthesis_module]
    forbidden = ("gpio-ftgpio010", "0x1234", "0x11e8", "IO_DMA_CMD", "detect_subsystem")
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not any(token in text for token in forbidden)
    assert "subsystem" not in text.lower()


def test_generator_and_sanitizer_consume_policy_without_private_constants():
    linux_dir = ROOT / "src" / "backends" / "linux"
    linux_paths = sorted(linux_dir.glob("*.py")) if linux_dir.is_dir() else [ROOT / "src" / "backends" / "linux.py"]
    paths = linux_paths + [ROOT / "tools" / "source" / "sanitize.py"]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "device_spec.name == \"edu\"" not in text
    assert "IO_DMA_CMD" not in text
    assert "DMA_IRQ" not in text


def _qemu_runner_source() -> str:
    return (ROOT / "qa" / "verification" / "qemu_run.py").read_text(
        encoding="utf-8")


def test_qemu_runner_uses_manifest_device_and_binding_protocols():
    source = _qemu_runner_source()
    assert "spec.device" in source and "launch_device" in source
    assert "binding_bus" in source and "binding_required" in source
    assert "success_pattern" in source


def test_qemu_runner_accepts_invocation_local_module_artifact_root():
    source = _qemu_runner_source()
    assert "RH_QEMU_MODULE_OUTPUT_ROOT" in source


def test_qemu_runner_does_not_infer_success_from_exerciser_name():
    source = _qemu_runner_source()
    # 成功只由 manifest 的 success_pattern / 协议标记决定, 不看名字
    assert "success_pattern" in source
    assert "exerciser.endswith" not in source
