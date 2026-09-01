"""Reviewable intermediate artifacts for the IR-primary extraction chain.

One driver → one directory under ``artifacts/intermediates/<stem>/`` holding
every stage in reading order, all text formats (LLVM IR text, JSON) so a
human can inspect and hand-edit them:

    01-ir.ll            compiled LLVM IR (-g -O1, kernel flags)
    02-macros.json      driver-local macro table + constant→name reverse index
    03-ir-facts.json    IR analysis facts (MMIO ops: lines/offsets/widths/
                        variable names/value chains/ambiguity candidates)
    04-ast-formal.json  pure-AST formal (the supplement layer, pre-merge)
    05-merged-ris.json  final hybrid RIS (join evidence in every op)
    06-stats.json       extraction stats (method, counts, quality inputs)

Regenerate with:  ./run.sh intermediates <driver.c>
Root override:    REHARNESS_INTERMEDIATES=/path
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ROOT = _REPO_ROOT / "artifacts" / "intermediates"


def intermediates_root() -> Path:
    """Root directory for intermediate artifacts (env-overridable)."""
    env = os.environ.get("REHARNESS_INTERMEDIATES")
    root = Path(env) if env else _DEFAULT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def intermediate_dir(source: str | Path) -> Path:
    """Per-driver intermediate directory (created on demand)."""
    path = intermediates_root() / Path(source).stem
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload) -> Path:
    import json
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + "\n", encoding="utf-8")
    return path


__all__ = ["intermediates_root", "intermediate_dir", "write_json"]
