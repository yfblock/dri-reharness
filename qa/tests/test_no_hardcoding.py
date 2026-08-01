from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runner_and_pi_bridge_have_no_target_literals_or_branches():
    synthesis_module = next(ROOT.glob("src/synth*.py"))
    paths = [ROOT / "src" / "experiment_runner.py", synthesis_module,
             ROOT / "tools" / "pi" / "synth.mjs", ROOT / "tools" / "pi" / "pi_synth.sh"]
    forbidden = ("gpio-ftgpio010", "0x1234", "0x11e8", "IO_DMA_CMD", "detect_subsystem")
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert not any(token in text for token in forbidden)
    assert "subsystem" not in text.lower()
