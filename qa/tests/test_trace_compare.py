from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from trace_protocol import TraceEvent  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "qa" / "verification" / "trace_compare.py"


def _write_trace(path: Path, values: list[int], *, error=None, return_code=0):
    events = [TraceEvent(
        phase="probe", function="runtime_probe", kind="read", width_bits=32,
        address=0x10, value=value, sequence=index,
    ).to_dict() for index, value in enumerate(values)]
    path.write_text(json.dumps({
        "events": events, "error": error, "return_code": return_code,
    }), encoding="utf-8")


def test_cli_reports_structured_equal_result(tmp_path: Path):
    original, candidate = tmp_path / "original.json", tmp_path / "candidate.json"
    _write_trace(original, [1, 2])
    _write_trace(candidate, [1, 2])
    result = subprocess.run(
        [sys.executable, str(TOOL), str(original), str(candidate)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["equal"] is True
    assert report["comparison"]["divergence"] is None


def test_cli_reports_first_mismatch_for_pi_repair(tmp_path: Path):
    original, candidate = tmp_path / "original.json", tmp_path / "candidate.json"
    _write_trace(original, [1, 2, 3])
    _write_trace(candidate, [1, 9, 3])
    result = subprocess.run(
        [sys.executable, str(TOOL), str(original), str(candidate)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["equal"] is False
    divergence = report["comparison"]["divergence"]
    assert divergence["reason"] == "event_mismatch"
    assert divergence["index"] == 1
    assert divergence["original"]["value"] == 2
    assert divergence["candidate"]["value"] == 9


def test_cli_uses_manifest_declared_value_mask(tmp_path: Path):
    original, candidate = tmp_path / "original.json", tmp_path / "candidate.json"
    manifest = tmp_path / "manifest.json"
    _write_trace(original, [0x100000001])
    _write_trace(candidate, [1])
    manifest.write_text(json.dumps({"trace": {"value_mask": "0xffffffff"}}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(TOOL), str(original), str(candidate), "--manifest", str(manifest)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_classifies_malformed_input_as_infrastructure_error(tmp_path: Path):
    original, candidate = tmp_path / "original.json", tmp_path / "candidate.json"
    original.write_text(json.dumps({"events": [{"kind": "read"}]}), encoding="utf-8")
    _write_trace(candidate, [1])
    result = subprocess.run(
        [sys.executable, str(TOOL), str(original), str(candidate)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["comparison"]["reason"] == "infrastructure_error"
