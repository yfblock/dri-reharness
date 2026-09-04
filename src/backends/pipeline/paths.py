"""Small shared helpers for the multi-backend pipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _is_subsequence(sub, seq) -> bool:
    it = iter(seq)
    return all(item in it for item in sub)


def _pipeline_success(readiness: dict) -> bool:
    """Return success only when every generated backend is strictly ready."""
    return all(readiness.get(key) is True for key in (
        "backend_harness_ready", "backend_bare_metal_ready",
        "backend_linux_ready"))


_ORACLE_FILES = {
    "gpio": "gpio-mmio-source-oracle.json",
    "sdhci": "sdhci-accessor-oracle.json",
    "virtio": "virtio-state-oracle.json",
    "w1c": "w1c-drain-oracle.json",
    "transaction": "transaction-ir-oracle.json",
}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]  # src/backends/pipeline/paths.py -> repo root


def _transaction_source_paths(source: str | os.PathLike[str]) -> list[str]:
    descriptor = Path(source).resolve()
    if descriptor.suffix.lower() != ".json":
        return [str(descriptor)]
    try:
        document = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [str(descriptor)]
    entries = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return [str(descriptor)]
    return [str((descriptor.parent / item).resolve())
            for item in entries if isinstance(item, str) and item.strip()]
