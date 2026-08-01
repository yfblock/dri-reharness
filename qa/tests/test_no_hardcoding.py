from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runner_and_pi_bridge_have_no_target_literals_or_branches():
    synthesis_module = next(ROOT.glob("src/synth*.py"))
    paths = [ROOT / "src" / "experiment_runner.py", synthesis_module,
             ROOT / "tools" / "pi" / "synth.mjs", ROOT / "tools" / "pi" / "pi_synth.sh"]
    forbidden = ("gpio-ftgpio010", "0x1234", "0x11e8", "IO_DMA_CMD", "detect_subsystem")
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not any(token in text for token in forbidden)
    assert "subsystem" not in text.lower()


def test_e2e_entrypoint_is_manifest_only_compatibility_dispatch():
    entrypoint = ROOT / "scripts" / "e2e" / "run_e2e.sh"
    text = entrypoint.read_text(encoding="utf-8")
    forbidden = (
        "detect_subsystem", "QEMU_DEVICE", "REGISTRAR_TARGET", "EXERCISER",
        "TRACE_EXERCISED", "0x1234", "0x11e8", "IO_DMA_CMD",
    )
    assert not any(token in text for token in forbidden)
    assert "manifest_for_source" in text
    assert 'exec "$ROOT/run.sh" experiment "$manifest" "$@"' in text


def test_e2e_source_form_resolves_manifest_before_delegating():
    entrypoint = ROOT / "scripts" / "e2e" / "run_e2e.sh"
    source = "benchmarks/drivers/baseline/edu.c"
    result = subprocess.run([str(entrypoint), source, "--help"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "manifest" in (result.stdout + result.stderr).lower()
