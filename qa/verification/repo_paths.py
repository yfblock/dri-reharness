"""Stable repository path discovery for relocated QA modules."""
from __future__ import annotations

import os
from pathlib import Path
import sys


_LOADED_MODULE = sys.modules[__name__]
_MODULE_NAMES = ("repo_paths", "verification.repo_paths")
for _module_name in _MODULE_NAMES:
    _existing_module = sys.modules.get(_module_name)
    if (_existing_module is not None
            and _existing_module is not _LOADED_MODULE):
        raise RuntimeError(
            f"{_module_name} already refers to a different module")
for _module_name in _MODULE_NAMES:
    sys.modules[_module_name] = _LOADED_MODULE


def find_repo_root(start: str | Path = __file__) -> Path:
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if ((candidate / ".gitmodules").is_file()
                and (candidate / "README.md").is_file()):
            return candidate
    raise RuntimeError(f"cannot locate reharness repository root from {start}")


def resolve_logical(base: str | Path, relative: str | Path) -> Path:
    """Resolve ``relative`` against ``base`` following compatibility symlinks.

    The base is resolved to its real filesystem location before ``..``
    segments in ``relative`` are collapsed. This keeps manifest resolution
    stable when callers provide a path containing symbolic links.
    """
    base_resolved = Path(os.fspath(base)).resolve()
    joined = os.path.join(os.fspath(base_resolved), os.fspath(relative))
    return Path(joined).resolve()


REPO_ROOT = find_repo_root()
ROOT = REPO_ROOT
ROOT_STR = str(REPO_ROOT)
SOURCE_ROOT = REPO_ROOT / "src"
QA_ROOT = REPO_ROOT / "qa"
LINUX_ROOT = (REPO_ROOT / "vendor/linux").resolve()
KERNEL_BUILD_ROOT = REPO_ROOT / "platform/kernel/build"
ARTIFACT_OUTPUT_ROOT = REPO_ROOT / "artifacts/output"
EXPERIMENT_RESULTS_ROOT = REPO_ROOT / "research/experiments/results"


def install_python_paths() -> None:
    canonical = {SOURCE_ROOT.resolve(), QA_ROOT.resolve()}

    def resolves_to_canonical(entry: object) -> bool:
        try:
            value = os.fspath(entry)
        except TypeError:
            return False
        try:
            return Path(value or os.curdir).resolve() in canonical
        except OSError:
            return False

    sys.path[:] = [entry for entry in sys.path
                   if not resolves_to_canonical(entry)]
    sys.path[:0] = [str(SOURCE_ROOT), str(QA_ROOT)]


install_python_paths()
