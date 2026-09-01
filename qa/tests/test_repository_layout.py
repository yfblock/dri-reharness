from __future__ import annotations

import ast
import configparser
import os
from pathlib import Path
import re
import stat


ROOT = Path(__file__).resolve().parents[2]

CANONICAL_DIRS = (
    "artifacts/output",
    "benchmarks/drivers/baseline",
    "benchmarks/drivers/holdout",
    "benchmarks/drivers/multisource",
    "docs",
    "examples/edu",
    "platform/kernel",
    "qa/native-tests",
    "qa/tests",
    "qa/verification",
    "research/experiments",
    "research/history",
    "research/paper",
    "research/reference-success",
    "src/extractor",
    "src/backends",
    "vendor/linux",
)

PYTHON_ROOT_VARIABLE_NAMES = {
    "here", "project_dir", "project_root", "reharness", "reharness_root",
    "repo_root", "repository_root", "root",
}

ALLOWED_ROOT_ENTRIES = {
    ".agents", ".claude", ".codegraph", ".codex", ".env", ".env.example",
    ".git", ".gitignore", ".gitmodules", ".omp", ".pi", ".pytest_cache",
    ".superpowers", "PROMPT.md", "README.md", "REPRO.md", "artifacts",
    "benchmarks", "dev-docs", "docs", "examples", "platform", "qa",
    "config.toml", "records", "research", "requirements-langgraph.txt",
    "run.sh", "scripts", "src", "tools", "vendor", "vocabulary.md",
    ".venv", ".worktrees",
}

ACTIVE_SUFFIXES = {
    ".c", ".config", ".h", ".json", ".md", ".py", ".sh", ".tex",
    ".toml", ".yaml", ".yml",
}
ACTIVE_FILENAMES = {".gitignore", ".gitmodules", "Makefile"}




def _submodule_paths(text: str) -> tuple[str, ...]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return tuple(
        parser.get(section, "path")
        for section in parser.sections()
        if section.startswith("submodule ")
    )











def test_canonical_repository_layout_exists():
    invalid = [path for path in CANONICAL_DIRS
               if not (ROOT / path).is_dir() or (ROOT / path).is_symlink()]
    assert not invalid, invalid



def test_root_run_sh_is_a_real_executable_file():
    entry = ROOT / "run.sh"
    assert entry.is_file()
    assert not entry.is_symlink()
    assert stat.S_IMODE(entry.stat().st_mode) & stat.S_IXUSR


def test_linux_submodule_uses_the_canonical_path():
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    assert _submodule_paths(text) == ("vendor/linux",)


def test_root_contains_only_the_public_contract():
    unexpected = sorted(path.name for path in ROOT.iterdir()
                        if path.name not in ALLOWED_ROOT_ENTRIES)
    assert not unexpected, unexpected


def test_relocated_root_plan_exists():
    assert (ROOT / "docs/plans/original-implementation-plan.md").is_file()



def _run_standalone() -> int:
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for name, test in tests:
        try:
            test()
        except Exception as error:
            failed += 1
            print(f"FAIL {name}: {type(error).__name__}: {error}")
        else:
            print(f"PASS {name}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
