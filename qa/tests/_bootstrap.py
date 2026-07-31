from __future__ import annotations

from pathlib import Path
import sys


_BOOTSTRAP_QA_ROOT = Path(__file__).resolve().parents[1]


def _is_bootstrap_qa_root(entry: object) -> bool:
    try:
        return Path(entry or ".").resolve() == _BOOTSTRAP_QA_ROOT
    except (OSError, TypeError):
        return False


sys.path[:] = [entry for entry in sys.path
               if not _is_bootstrap_qa_root(entry)]
sys.path.insert(0, str(_BOOTSTRAP_QA_ROOT))

from verification import repo_paths as _repo_paths  # noqa: E402

# Relocated QA modules still use the historical top-level import name.
_existing_repo_paths = sys.modules.get("repo_paths")
if (_existing_repo_paths is not None
        and _existing_repo_paths is not _repo_paths):
    raise RuntimeError("repo_paths was imported with a duplicate identity")
sys.modules["repo_paths"] = _repo_paths

from verification.repo_paths import (  # noqa: E402,F401
    ARTIFACT_OUTPUT_ROOT,
    EXPERIMENT_RESULTS_ROOT,
    KERNEL_BUILD_ROOT,
    LINUX_ROOT,
    QA_ROOT,
    REPO_ROOT,
    ROOT_STR,
    SOURCE_ROOT,
    resolve_logical,
)

if QA_ROOT != _BOOTSTRAP_QA_ROOT:
    raise RuntimeError(
        f"bootstrap QA root {_BOOTSTRAP_QA_ROOT} does not match {QA_ROOT}")
