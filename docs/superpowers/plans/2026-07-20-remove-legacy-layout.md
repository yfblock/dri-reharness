# Remove Legacy Repository Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every repository-owned legacy root entry, make a real root `run.sh` the only public command dispatcher, and restore all active workflows on canonical repository paths.

**Architecture:** Canonical code and data remain under `src/`, `qa/`, `benchmarks/`, `research/`, `platform/`, `vendor/`, `artifacts/`, `scripts/`, and `tools/`. The root dispatcher supplies Python search paths and routes commands to those owners. Tests first define the no-legacy root contract; compatibility entries are deleted only after active code, manifests, scripts, and current documentation stop using them.

**Tech Stack:** Bash, Python 3, libclang-based project tests, JSON manifests, Linux Kbuild/QEMU preflight, Git submodules, Markdown documentation.

**Execution note:** The initial categorized layout is already committed in
`b597c57`, `502f30a`, `84d9a90`, and `592f3c9`. Preserve unrelated working-tree
files, keep the two native-test executables untracked, and commit each task as
an independently verified migration step.

---

## File structure changed by this plan

- `run.sh`: real executable public dispatcher; no longer a symlink.
- `qa/tests/test_repository_layout.py`: canonical-root and removed-entry guard.
- `qa/tests/test_run_dispatcher.py`: public command contract smoke test.
- `qa/tests/_bootstrap.py`: direct-test import bootstrap for relocated packages.
- `qa/verification/repo_paths.py`: canonical Python and repository path discovery.
- `src/extractor/{cli.py,extractor.py,tu.py,alias.py}`: canonical defaults for output, Linux, kernel build, and tools.
- `benchmarks/drivers/{holdout,multisource}/*.json`: canonical relative Linux/build/output paths.
- `scripts/e2e/*.sh`, `scripts/qemu/*.sh`, `scripts/maintenance/log_event.sh`: canonical script calls and runtime paths.
- `tools/e2e_common.sh`, `tools/pi/pi_synth.sh`: canonical helper, registrar, and Pi paths.
- `qa/verification/*.py`, `qa/verification/run_qemu_experiments.sh`: canonical benchmark, tool, output, and QEMU paths.
- `.gitignore`, `README.md`, `REPRO.md`, `PROMPT.md`, `docs/README.md`, `platform/kernel/README.md`, `research/reference-success/**/*.md`: canonical current documentation and ignore rules.
- `docs/plans/original-implementation-plan.md`: relocated former root `plan.md`.
- `artifacts/initramfs/*.cpio.gz`: relocated root initramfs images.
- Legacy root links/directories listed in the approved design: removed.

## Task 1: Capture the current baseline and write failing structural tests

**Files:**
- Modify: `qa/tests/test_repository_layout.py`
- Create: `qa/tests/test_run_dispatcher.py`

- [ ] **Step 1: Record the dirty baseline without changing it**

Run:

```bash
git status --short --branch
git diff --check
git submodule status vendor/linux
find . -maxdepth 1 -mindepth 1 -printf '%y %f -> %l\n' | sort
bash -n scripts/e2e/run.sh scripts/e2e/run_e2e.sh scripts/qemu/qemu_run.sh
./run.sh help
```

Expected: the existing migration changes remain visible; `vendor/linux` reports the pinned gitlink; the root listing still contains legacy links; shell syntax and current help exit successfully.

- [ ] **Step 2: Replace the compatibility-link layout test with the final root contract**

Replace `qa/tests/test_repository_layout.py` with:

```python
from __future__ import annotations

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
    "platform/rootfs/base",
    "platform/rootfs/platform",
    "platform/rootfs/runtime",
    "qa/native-tests",
    "qa/tests",
    "qa/verification",
    "research/experiments",
    "research/history",
    "research/paper",
    "research/reference-success",
    "scripts/e2e",
    "scripts/maintenance",
    "scripts/qemu",
    "src/extractor",
    "src/generator",
    "tools/pi",
    "vendor/linux",
)

LEGACY_ROOT_ENTRIES = (
    "drivers", "edu_drv.c", "experiments", "extractor", "generator",
    "history", "kernel", "linux", "log_event.sh", "output", "paper",
    "qemu_edu.sh", "qemu_platform.sh", "qemu_run.sh", "recom.md",
    "repo_paths.py", "run_e2e.sh", "run_edu_e2e.sh", "run_gpio_e2e.sh",
    "success", "synthesis.py", "test", "test_rootfs",
    "test_rootfs_plat", "test_rootfs_run", "tests", "verification",
    "plan.md", "initramfs_edu.cpio.gz", "initramfs_plat.cpio.gz",
    "initramfs_run.cpio.gz", "__pycache__",
)

ALLOWED_ROOT_ENTRIES = {
    ".agents", ".codegraph", ".codex", ".git", ".gitignore",
    ".gitmodules", "PROMPT.md", "README.md", "REPRO.md", "artifacts",
    "benchmarks", "docs", "examples", "platform", "qa", "research",
    "run.sh", "scripts", "src", "tools", "vendor",
}

ACTIVE_SUFFIXES = {
    ".c", ".config", ".h", ".json", ".md", ".py", ".sh", ".tex",
    ".toml", ".yaml", ".yml",
}
REFERENCE_EXCLUSIONS = (
    ".git/", "artifacts/", "docs/superpowers/", "research/history/",
    "research/experiments/results/", "tools/pi/node_modules/", "vendor/linux/",
)
LEGACY_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:"
    r"\./run_(?:e2e|edu_e2e|gpio_e2e)\.sh|"
    r"bash qemu_(?:run|edu|platform)\.sh|"
    r"python3 verification/|"
    r"verification/run_qemu_experiments\.sh|"
    r"drivers/(?:test|holdout|multisource)/|"
    r"tests/fixtures/|"
    r"test/(?:edu|gpio)_trace_test|"
    r"output/|kernel/build/|experiments/results/|"
    r"paper/(?:generated_results\.tex|paper\.pdf)|"
    r"\(cd paper\b|\.\./\.\./linux/"
    r")"
)


def test_canonical_repository_layout_exists():
    missing = [path for path in CANONICAL_DIRS if not (ROOT / path).exists()]
    assert not missing, missing


def test_legacy_root_entries_are_absent():
    present = [path for path in LEGACY_ROOT_ENTRIES
               if (ROOT / path).exists() or (ROOT / path).is_symlink()]
    assert not present, present


def test_root_run_sh_is_a_real_executable_file():
    entry = ROOT / "run.sh"
    assert entry.is_file()
    assert not entry.is_symlink()
    assert stat.S_IMODE(entry.stat().st_mode) & stat.S_IXUSR


def test_linux_submodule_uses_the_canonical_path():
    text = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    assert "path = vendor/linux" in text
    assert "path = linux" not in text


def test_root_contains_only_the_public_contract():
    unexpected = sorted(path.name for path in ROOT.iterdir()
                        if path.name not in ALLOWED_ROOT_ENTRIES)
    assert not unexpected, unexpected


def test_relocated_root_plan_exists():
    assert (ROOT / "docs/plans/original-implementation-plan.md").is_file()


def test_active_files_use_canonical_repository_paths():
    violations = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in ACTIVE_SUFFIXES:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative == "qa/tests/test_repository_layout.py":
            continue
        if any(relative.startswith(prefix) for prefix in REFERENCE_EXCLUSIONS):
            continue
        for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = LEGACY_REFERENCE.search(line)
            if match:
                violations.append(f"{relative}:{number}: {match.group(0)}")
    assert not violations, "\n".join(violations)


def _run_standalone() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
```

- [ ] **Step 3: Add a failing dispatcher contract test**

Create `qa/tests/test_run_dispatcher.py` with:

```python
from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COMMANDS = (
    "extract", "spec", "gen", "driver", "facts", "bundle", "metrics",
    "score", "reliability", "compare", "test", "e2e", "edu-e2e",
    "gpio-e2e", "qemu", "qemu-edu", "qemu-platform",
    "qemu-experiments", "log-event",
)


def test_help_lists_every_public_command():
    result = subprocess.run(
        [str(ROOT / "run.sh"), "help"], cwd=ROOT,
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    missing = [command for command in EXPECTED_COMMANDS
               if command not in result.stdout]
    assert not missing, missing


def test_unknown_command_fails():
    result = subprocess.run(
        [str(ROOT / "run.sh"), "not-a-command"], cwd=ROOT,
        capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "unknown command" in result.stdout + result.stderr


if __name__ == "__main__":
    test_help_lists_every_public_command()
    test_unknown_command_fails()
    print("2 passed, 0 failed")
```

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```bash
python3 qa/tests/test_repository_layout.py
python3 qa/tests/test_run_dispatcher.py
```

Expected: the layout test fails because legacy entries and root artifacts still exist; the dispatcher test fails because QEMU, specialized E2E, and maintenance commands are not yet listed.

- [ ] **Step 5: Commit the final-layout contract tests**

Run:

```bash
git diff --check -- qa/tests/test_repository_layout.py qa/tests/test_run_dispatcher.py
git status --short -- qa/tests/test_repository_layout.py qa/tests/test_run_dispatcher.py
git add qa/tests/test_repository_layout.py qa/tests/test_run_dispatcher.py
git commit -m "test: define canonical repository contract"
```

Expected: only the intended tests are committed; they remain RED until the
later migration tasks remove the compatibility layout.

## Task 2: Establish canonical Python import and repository paths

**Files:**
- Modify: `qa/verification/repo_paths.py`
- Create: `qa/tests/_bootstrap.py`
- Modify: `qa/tests/test_backend_lowering_plan.py`
- Modify: `qa/tests/test_dataflow_read_return.py`
- Modify: `qa/tests/test_device_spec_json.py`
- Modify: `qa/tests/test_extractor.py`
- Modify: `qa/tests/test_generated_c_ast_oracle.py`
- Modify: `qa/tests/test_linux_registration_ast_oracle.py`
- Modify: `qa/tests/test_metrics_c20_readiness.py`
- Modify: `qa/tests/test_repository_paths.py`

- [ ] **Step 1: Add failing tests for canonical path installation**

Add these tests to `qa/tests/test_repository_paths.py`:

```python
def test_repository_python_paths_are_canonical():
    from verification.repo_paths import QA_ROOT, SOURCE_ROOT

    assert SOURCE_ROOT == Path(__file__).resolve().parents[2] / "src"
    assert QA_ROOT == Path(__file__).resolve().parents[1]


def test_holdout_manifest_uses_canonical_linux_relative_path():
    import json
    from verification.repo_paths import REPO_ROOT

    manifest = json.loads((
        REPO_ROOT / "benchmarks/drivers/holdout/zero-shot-v1.json"
    ).read_text(encoding="utf-8"))
    assert manifest["cases"][0]["source"].startswith(
        "../../../vendor/linux/")
```

Replace the compatibility-path test with:

```python
def test_canonical_relative_paths_resolve_without_symlinks():
    from verification.repo_paths import REPO_ROOT, resolve_logical

    base = REPO_ROOT / "benchmarks/drivers/holdout"
    resolved = resolve_logical(base, "../../../vendor/linux/README")
    assert resolved == (REPO_ROOT / "vendor/linux/README").resolve()
```

Run:

```bash
PYTHONPATH=src:qa python3 -c 'from qa.tests import test_repository_paths as t; t.test_repository_python_paths_are_canonical()'
```

Expected: FAIL because `SOURCE_ROOT` and `QA_ROOT` do not exist yet.

- [ ] **Step 2: Install canonical paths from `repo_paths.py`**

Add `import sys` and replace the constant block with:

```python
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
    for path in (QA_ROOT, SOURCE_ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


install_python_paths()
```

- [ ] **Step 3: Add a direct-test bootstrap**

Create `qa/tests/_bootstrap.py` with:

```python
from __future__ import annotations

from pathlib import Path
import sys


QA_ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_ROOT = QA_ROOT / "verification"
if str(VERIFICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(VERIFICATION_ROOT))

from repo_paths import (  # noqa: E402,F401
    ARTIFACT_OUTPUT_ROOT,
    EXPERIMENT_RESULTS_ROOT,
    KERNEL_BUILD_ROOT,
    LINUX_ROOT,
    QA_ROOT as CANONICAL_QA_ROOT,
    REPO_ROOT,
    ROOT_STR,
    SOURCE_ROOT,
    resolve_logical,
)
```

Replace imports in the seven listed tests exactly as follows:

```python
# test_extractor.py
from _bootstrap import ROOT_STR as REHARNESS, resolve_logical

# test_backend_lowering_plan.py, test_dataflow_read_return.py,
# test_device_spec_json.py, test_generated_c_ast_oracle.py,
# test_linux_registration_ast_oracle.py, test_metrics_c20_readiness.py
from _bootstrap import REPO_ROOT as REHARNESS
```

Remove `sys.path.insert(0, REHARNESS)` lines because
`repo_paths.install_python_paths()` now installs `src/` and `qa/`.

Add this standalone runner to `qa/tests/test_repository_paths.py`:

```python
def _run_standalone() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
```

- [ ] **Step 4: Verify direct imports without root compatibility links**

Run:

```bash
PYTHONPATH= python3 qa/tests/test_device_spec_json.py
PYTHONPATH= python3 -c 'import sys; sys.path.insert(0, "qa/verification"); import repo_paths; import extractor, generator, verification; print("canonical-imports: PASS")'
```

Expected: both commands exit 0 and print `canonical-imports: PASS`.

- [ ] **Step 5: Commit canonical Python path discovery**

Run:

```bash
git diff --check -- qa/verification/repo_paths.py qa/tests
git status --short -- qa/verification/repo_paths.py qa/tests
git add qa/verification/repo_paths.py qa/tests/_bootstrap.py \
  qa/tests/test_backend_lowering_plan.py qa/tests/test_dataflow_read_return.py \
  qa/tests/test_device_spec_json.py qa/tests/test_extractor.py \
  qa/tests/test_generated_c_ast_oracle.py \
  qa/tests/test_linux_registration_ast_oracle.py \
  qa/tests/test_metrics_c20_readiness.py qa/tests/test_repository_paths.py
git commit -m "refactor: use canonical Python repository paths"
```

Expected: only Python bootstrap/path files changed in this task.

## Task 3: Convert manifests, extractor defaults, and QA code to canonical paths

**Files:**
- Modify: `benchmarks/drivers/holdout/zero-shot-v1.json`
- Modify: `benchmarks/drivers/holdout/zero-shot-v1-contexts.json`
- Modify: `benchmarks/drivers/holdout/zero-shot-v2.json`
- Modify: `benchmarks/drivers/holdout/zero-shot-v2-contexts.json`
- Modify: `benchmarks/drivers/multisource/aspeed-vhub.json`
- Modify: `benchmarks/drivers/multisource/c67x00.json`
- Modify: `benchmarks/drivers/multisource/dwc2.json`
- Modify: `src/extractor/cli.py`
- Modify: `src/extractor/extractor.py`
- Modify: `src/extractor/tu.py`
- Modify: `src/extractor/alias.py`
- Modify: `src/synthesis.py`
- Modify: `qa/verification/check_generalization_guard.py`
- Modify: `qa/verification/compare.py`
- Modify: `qa/verification/gpio_mmio_source_oracle.py`
- Modify: `qa/verification/run_matrix.py`
- Modify: `qa/tests/test_i2c_transaction_lowering.py`
- Modify: `qa/tests/test_mfd_transaction_lowering.py`
- Modify: `qa/tests/test_regmap_transaction_lowering.py`
- Modify: `qa/tests/test_extractor.py`

- [ ] **Step 1: Update manifest paths without changing frozen hashes or membership**

Apply these exact path transformations to holdout and multi-source manifests:

```text
../../linux/                  -> ../../../vendor/linux/
kernel/build                  -> platform/kernel/build
output/zero-shot-contexts/    -> artifacts/output/zero-shot-contexts/
```

Do not change `source_sha256`, `linux_commit`, case IDs, case order, Kconfig
symbols, Linux-internal object targets such as `drivers/gpio/*.o`, selection
hashes, or benchmark membership.

Verify the semantic fields remain stable:

```bash
git diff --word-diff=plain -- benchmarks/drivers/holdout benchmarks/drivers/multisource
python3 -m json.tool benchmarks/drivers/holdout/zero-shot-v1.json >/dev/null
python3 -m json.tool benchmarks/drivers/multisource/c67x00.json >/dev/null
```

Expected: the diff contains path-prefix changes only; JSON parsing succeeds.

- [ ] **Step 2: Make extractor output and repository discovery canonical**

Use `artifacts/output/ris.ris` as the default in
`src/extractor/extractor.py` and every corresponding CLI default/help string in
`src/extractor/cli.py`. Replace generated defaults as follows:

```python
out = args.output or f"artifacts/output/{res.formal['driver']}_{args.backend}.c"
outdir = args.outdir or f"artifacts/output/{name}"
outdir = args.outdir or (
    f"artifacts/output/{res.formal['driver']}.bundle-{args.backend}")
```

Change Linux help text to `default: repository vendor/linux submodule`.

In `src/extractor/tu.py`, derive defaults from the repository root:

```python
repo = Path(__file__).resolve().parents[2]
cand = repo / "vendor/linux"
linux_root = str(cand) if cand.is_dir() else None
default_build = repo / "platform/kernel/build"
```

Add `from pathlib import Path` if absent.

In `src/extractor/alias.py`, use:

```python
repo = Path(__file__).resolve().parents[2]
tools_dir = repo / "tools/build"
linux = linux_root or os.fspath(repo / "vendor/linux")
default_build = repo / "platform/kernel/build"
```

Pass `os.fspath(tools_dir / "ir_stub.py")` where the IR stub script is
invoked. Add `from pathlib import Path` if absent.

Update `src/synthesis.py` to name `scripts/e2e/run_e2e.sh` and
`tools/pi/synth.mjs` only; remove references to compatibility entries.

- [ ] **Step 3: Convert QA executable paths**

Make these exact replacements:

```text
ROOT / "drivers" / "holdout"       -> ROOT / "benchmarks/drivers/holdout"
ROOT / "drivers" / "test"          -> ROOT / "benchmarks/drivers/baseline"
ROOT / "drivers" / "multisource"   -> ROOT / "benchmarks/drivers/multisource"
"drivers/test/gpio-ftgpio010.c"     -> "benchmarks/drivers/baseline/gpio-ftgpio010.c"
"tests/fixtures/"                   -> "qa/tests/fixtures/"
Path("kernel/build")                -> Path("platform/kernel/build")
`output/experiment-matrix/`          -> `artifacts/output/experiment-matrix/`
`experiments/results/`               -> `research/experiments/results/`
```

In `qa/verification/check_generalization_guard.py`, keep manifest labels
`extractor` and `generator` stable for frozen-tree keys, but map them to
canonical directories when reading current files:

```python
PROTECTED_ROOT_PATHS = {
    "extractor": "src/extractor",
    "generator": "src/generator",
}
```

Use `PROTECTED_ROOT_PATHS.get(relative_root, relative_root)` in
`_protected_root_changed`, `_specialization_inventory`, and the final protected
source scan. This preserves `extractor_tree`/`generator_tree` frozen metadata.

- [ ] **Step 4: Run focused canonical-path tests**

Run:

```bash
PYTHONPATH=src:qa python3 qa/verification/check_generalization_guard.py
PYTHONPATH=src:qa python3 qa/tests/test_repository_paths.py
PYTHONPATH=src:qa python3 qa/tests/test_extractor.py
```

Expected: the guard passes; repository path tests pass; the standalone extractor suite reports zero failures.

- [ ] **Step 5: Commit canonical executable paths**

Run:

```bash
git diff --check -- src qa benchmarks
git status --short -- src qa benchmarks
git add src qa benchmarks
git commit -m "refactor: use canonical paths in code and manifests"
```

Expected: no whitespace errors and no frozen result/history files changed.

## Task 4: Promote `run.sh` to the real dispatcher

**Files:**
- Replace: `run.sh`
- Remove: `scripts/e2e/run.sh`

- [ ] **Step 1: Replace the root symlink with the dispatcher implementation**

Move the current `scripts/e2e/run.sh` content into a real root `run.sh` and
remove `scripts/e2e/run.sh`. Its setup block must be:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/qa${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python3}"
OUTPUT_ROOT="$ROOT/artifacts/output"
```

Keep the existing extractor command behavior, but use canonical defaults:

```bash
cmd_extract() {
  local src="${1:-}" out="${2:-$OUTPUT_ROOT/ris.ris}"
  [ -n "$src" ] || { echo "usage: $0 extract <src> [out.ris]"; exit 1; }
  mkdir -p "$(dirname "$out")"
  "$PY" -m extractor extract -s "$src" -o "$out"
}

cmd_reliability() { "$PY" qa/verification/reliability_report.py "$@"; }
cmd_compare() { "$PY" qa/verification/compare.py "$@"; }
cmd_e2e() { bash scripts/e2e/run_e2e.sh "$@"; }
cmd_edu_e2e() { bash scripts/e2e/run_edu_e2e.sh "$@"; }
cmd_gpio_e2e() { bash scripts/e2e/run_gpio_e2e.sh "$@"; }
cmd_qemu() { bash scripts/qemu/qemu_run.sh "$@"; }
cmd_qemu_edu() { bash scripts/qemu/qemu_edu.sh "$@"; }
cmd_qemu_platform() { bash scripts/qemu/qemu_platform.sh "$@"; }
cmd_qemu_experiments() { bash qa/verification/run_qemu_experiments.sh "$@"; }
cmd_log_event() { bash scripts/maintenance/log_event.sh "$@"; }

cmd_demo() {
  cmd_extract benchmarks/drivers/baseline/gpio-ftgpio010.c \
    "$OUTPUT_ROOT/demo/gpio-ftgpio010.ris"
}
```

The `test` command must use canonical paths and execute the new structural
tests:

```bash
cmd_test() {
  "$PY" qa/verification/check_generalization_guard.py
  "$PY" qa/tests/test_repository_layout.py
  "$PY" qa/tests/test_run_dispatcher.py
  "$PY" qa/tests/test_repository_paths.py
  "$PY" qa/tests/test_extractor.py
  "$PY" qa/tests/test_generated_c_ast_oracle.py
  "$PY" qa/tests/test_linux_registration_ast_oracle.py
  "$PY" qa/tests/test_backend_lowering_plan.py
  "$PY" qa/tests/test_metrics_c20_readiness.py
  "$PY" qa/tests/test_dataflow_read_return.py
  "$PY" qa/tests/test_device_spec_json.py
}
```

Add `edu-e2e`, `gpio-e2e`, `qemu`, `qemu-edu`, `qemu-platform`,
`qemu-experiments`, and `log-event` to both help text and the `case` dispatch.
Retain `pipeline` as an alias of `extract`.

- [ ] **Step 2: Verify executable mode and dispatcher GREEN**

Run:

```bash
chmod +x run.sh
test -f run.sh
test ! -L run.sh
test ! -e scripts/e2e/run.sh
bash -n run.sh
python3 qa/tests/test_run_dispatcher.py
./run.sh help
```

Expected: all checks pass and help lists every public command.

- [ ] **Step 3: Commit the public dispatcher**

Run:

```bash
git diff --check -- run.sh scripts/e2e
git status --short -- run.sh scripts/e2e
git add run.sh scripts/e2e/run.sh
git commit -m "refactor: promote root command dispatcher"
```

Expected: root `run.sh` is a regular executable and the duplicate dispatcher no longer exists.

## Task 5: Convert shell, QEMU, and tool implementations to canonical paths

**Files:**
- Modify: `scripts/e2e/run_e2e.sh`
- Modify: `scripts/e2e/run_edu_e2e.sh`
- Modify: `scripts/e2e/run_gpio_e2e.sh`
- Modify: `scripts/qemu/qemu_run.sh`
- Modify: `scripts/qemu/qemu_edu.sh`
- Modify: `scripts/qemu/qemu_platform.sh`
- Modify: `scripts/maintenance/log_event.sh`
- Modify: `tools/e2e_common.sh`
- Modify: `tools/pi/pi_synth.sh`
- Modify: `qa/verification/run_qemu_experiments.sh`

- [ ] **Step 1: Rewrite E2E defaults and internal calls**

In `scripts/e2e/run_e2e.sh`, use:

```bash
KERNELDIR="${KERNELDIR:-$HERE/platform/kernel/build}"
BUNDLE="$HERE/artifacts/output/$BASE"
DRVDIR="$HERE/artifacts/output/${MODULE}"
EXERCISER="$HERE/qa/native-tests/gpio_trace_test"
EXERCISER="$HERE/qa/native-tests/edu_trace_test"
source "$HERE/tools/e2e_common.sh"
"$HERE/run.sh" test
"$HERE/run.sh" bundle "$SRC" linux "$BUNDLE"
python3 "$HERE/qa/verification/backend_lowering_oracle.py"
python3 "$HERE/tools/reporting/trace_match.py"
bash "$HERE/scripts/qemu/qemu_run.sh"
```

Keep the existing subsystem behavior and arguments; only path ownership
changes. Set the EDU and GPIO wrapper defaults to:

```bash
benchmarks/drivers/baseline/edu.c
benchmarks/drivers/baseline/gpio-ftgpio010.c
```

- [ ] **Step 2: Rewrite QEMU and experiment paths**

In `scripts/qemu/qemu_run.sh`, use:

```bash
KERNELDIR="${KERNELDIR:-$PROJECT_DIR/platform/kernel/build}"
REGISTRAR_KO="${REGISTRAR_KO:-$PROJECT_DIR/qa/verification/device-registrar/device-registrar.ko}"
OUTPUT_DIR="$PROJECT_DIR/artifacts/output/$MODULE_NAME"
```

Use canonical rootfs paths under `platform/rootfs/` and canonical initramfs
images under `artifacts/initramfs/` for every archive input/output reference.

In `qemu_edu.sh` and `qemu_platform.sh`, pass exercisers as
`qa/native-tests/edu_trace_test` and `qa/native-tests/gpio_trace_test`.

In `qa/verification/run_qemu_experiments.sh`, replace:

```text
./tools/prepare_kernel.sh      -> ./tools/build/prepare_kernel.sh
bash qemu_run.sh               -> bash scripts/qemu/qemu_run.sh
python3 tools/instrument_mmio.py -> python3 tools/source/instrument_mmio.py
python3 tools/trace_match.py    -> python3 tools/reporting/trace_match.py
```

- [ ] **Step 3: Rewrite shared tool and maintenance paths**

In `tools/e2e_common.sh`, use:

```text
$HERE/qa/verification/device-registrar
$HERE/tools/source/sanitize.py
$HERE/tools/source/instrument_mmio.py
$HERE/tools/pi/pi_synth.sh
```

In `tools/pi/pi_synth.sh`, set:

```bash
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
```

and invoke `node "$HERE/synth.mjs"`.

In `scripts/maintenance/log_event.sh`, write only to:

```bash
LOG="$ROOT/research/history/timeline.md"
ENTRY="$ROOT/research/history/${STAMP}.txt"
```

- [ ] **Step 4: Run shell and local dependency verification**

Run:

```bash
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
bash -n tools/e2e_common.sh tools/pi/pi_synth.sh qa/verification/run_qemu_experiments.sh
node --check tools/pi/synth.mjs
node -e 'import("./tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/index.js").then(() => console.log("pi-import: PASS"))'
```

Expected: every syntax check exits 0 and Node prints `pi-import: PASS`.

- [ ] **Step 5: Commit canonical shell and tool paths**

Run:

```bash
git diff --check -- scripts tools qa/verification/run_qemu_experiments.sh
git status --short -- scripts tools qa/verification/run_qemu_experiments.sh
git add scripts tools qa/verification/run_qemu_experiments.sh
git commit -m "refactor: migrate shell workflows to canonical paths"
```

Expected: no shell syntax or whitespace errors.

## Task 6: Relocate remaining root files, update current documentation, and remove legacy entries

**Files:**
- Move: `plan.md` -> `docs/plans/original-implementation-plan.md`
- Move: `initramfs_edu.cpio.gz` -> `artifacts/initramfs/initramfs_edu.cpio.gz`
- Move: `initramfs_plat.cpio.gz` -> `artifacts/initramfs/initramfs_plat.cpio.gz`
- Move: `initramfs_run.cpio.gz` -> `artifacts/initramfs/initramfs_run.cpio.gz`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `REPRO.md`
- Modify: `PROMPT.md`
- Modify: `docs/README.md`
- Modify: `platform/kernel/README.md`
- Modify: `research/reference-success/NOTE.md`
- Modify: `research/reference-success/ftgpio010/NOTE.md`
- Remove: all approved legacy root entries except `run.sh`

- [ ] **Step 1: Move ignored/untracked root-owned files without copying**

Run source/target guards first:

```bash
test -f plan.md
test ! -e docs/plans/original-implementation-plan.md
mkdir -p artifacts/initramfs
```

Then rename each initramfs source that exists to the approved destination on
the same filesystem. Verify byte identity by recording `sha256sum` before and
after each move.

Expected: the plan exists at its canonical path; no root copy remains; each
initramfs image that existed before the step exists below `artifacts/initramfs/`.

- [ ] **Step 2: Simplify ignore rules to canonical locations**

Update `.gitignore` to keep only canonical patterns:

```gitignore
/artifacts/output/
/artifacts/initramfs/
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
/qa/native-tests/edu_trace_test
/qa/native-tests/gpio_trace_test
/platform/kernel/build/
/platform/rootfs/
/research/paper/*.aux
/research/paper/*.log
/research/paper/*.out
/research/paper/*.fls
/research/paper/*.fdb_latexmk
/research/paper/comment.cut
/tools/pi/node_modules/
/tools/pi/package-lock.json
```

Retain the existing editor/OS and kernel-module artifact patterns. Remove
ignore entries for `output`, `kernel/build`, `paper`, `test_rootfs*`, root
initramfs files, root `plan.md`, and root native-test binaries.

- [ ] **Step 3: Update current documentation and examples**

Apply these command/path transformations in the listed current documents:

```text
./tools/prepare_kernel.sh                -> ./tools/build/prepare_kernel.sh
drivers/test/                            -> benchmarks/drivers/baseline/
drivers/holdout/                         -> benchmarks/drivers/holdout/
drivers/multisource/                     -> benchmarks/drivers/multisource/
verification/                            -> qa/verification/
tests/                                   -> qa/tests/
test/                                    -> qa/native-tests/
output/                                  -> artifacts/output/
kernel/build/                            -> platform/kernel/build/
linux/                                   -> vendor/linux/ when it means the repository tree
experiments/results/                     -> research/experiments/results/
paper/generated_results.tex             -> research/paper/generated_results.tex
paper/paper.pdf                          -> research/paper/paper.pdf
python3 tools/generate_paper_results.py  -> python3 tools/reporting/generate_paper_results.py
(cd paper &&                             -> (cd research/paper &&
verification/run_qemu_experiments.sh     -> ./run.sh qemu-experiments
```

Replace compatibility-policy sections with the final root contract and
`./run.sh help`. Do not rewrite historical files under `research/history/`,
frozen JSON under `research/experiments/results/`, or the superseded design and
plan documents.

- [ ] **Step 4: Remove all approved legacy root entries**

Before deletion, verify every directory compatibility entry is a symlink or a
directory containing only symlinks. Then remove exactly:

```text
drivers
edu_drv.c
experiments
extractor
generator
history
kernel
linux
log_event.sh
output
paper
qemu_edu.sh
qemu_platform.sh
qemu_run.sh
recom.md
repo_paths.py
run_e2e.sh
run_edu_e2e.sh
run_gpio_e2e.sh
success
synthesis.py
test
test_rootfs
test_rootfs_plat
test_rootfs_run
tests
verification
```

Remove generated `__pycache__` directories after all Python checks. Do not
remove `.git`, `.agents`, `.codex`, or `.codegraph`.

- [ ] **Step 5: Run the final structural test and verify GREEN**

Run:

```bash
python3 qa/tests/test_repository_layout.py
python3 qa/tests/test_run_dispatcher.py
find . -maxdepth 1 -mindepth 1 -printf '%y %f -> %l\n' | sort
```

Expected: both tests pass; the root listing matches the approved contract; no listed legacy entry remains.

- [ ] **Step 6: Commit root cleanup and current documentation**

Run:

```bash
git diff --check
git status --short
git add -A .gitignore README.md REPRO.md PROMPT.md docs platform \
  research/reference-success artifacts run.sh
git commit -m "refactor: remove legacy repository layout"
```

Expected: the final root contract and documentation are committed without the
ignored native-test executables or frozen research evidence.

## Task 7: Run complete verification and audit the final migration

**Files:**
- Verify only; modify owning files only if a check exposes a path regression.

- [ ] **Step 1: Verify shell, Python, Node, and submodule integrity**

Run:

```bash
bash -n run.sh
find scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
bash -n tools/e2e_common.sh tools/pi/pi_synth.sh qa/verification/run_qemu_experiments.sh
PYTHONPYCACHEPREFIX=/tmp/reharness-pyc python3 -m compileall -q src qa
node --check tools/pi/synth.mjs
git submodule status vendor/linux
git -C vendor/linux status --short
git -C vendor/linux rev-parse HEAD
```

Expected: all syntax/byte-compilation checks exit 0; the Linux submodule is clean and remains at `acb7500801e98639f6d8c2d796ed9f64cba83d3a`.

- [ ] **Step 2: Run the complete project test entry**

Run:

```bash
./run.sh test
```

Expected: the zero-shot guard and every listed standalone suite exit 0; `test_extractor.py` reports zero failures.

- [ ] **Step 3: Run canonical CLI smoke tests for all deterministic backends**

Run:

```bash
rm -rf /tmp/reharness-layout-smoke
mkdir -p /tmp/reharness-layout-smoke
./run.sh extract benchmarks/drivers/baseline/gpio-ftgpio010.c /tmp/reharness-layout-smoke/ftgpio.ris
./run.sh spec benchmarks/drivers/baseline/gpio-ftgpio010.c /tmp/reharness-layout-smoke/ftgpio.dspec
./run.sh gen benchmarks/drivers/baseline/edu.c harness /tmp/reharness-layout-smoke/edu-harness.c
./run.sh gen benchmarks/drivers/baseline/edu.c baremetal /tmp/reharness-layout-smoke/edu-baremetal.c
./run.sh gen benchmarks/drivers/baseline/edu.c linux /tmp/reharness-layout-smoke/edu-linux.c
test -s /tmp/reharness-layout-smoke/ftgpio.ris
test -s /tmp/reharness-layout-smoke/ftgpio.dspec
test -s /tmp/reharness-layout-smoke/edu-harness.c
test -s /tmp/reharness-layout-smoke/edu-baremetal.c
test -s /tmp/reharness-layout-smoke/edu-linux.c
```

Expected: every command exits 0 and every output file is non-empty.

- [ ] **Step 4: Run active path-reference audits**

Run targeted searches excluding immutable evidence and external/generated trees:

```bash
rg -n --hidden \
  -g '!.git/**' -g '!vendor/linux/**' -g '!tools/pi/node_modules/**' \
  -g '!artifacts/**' -g '!research/experiments/results/**' \
  -g '!research/history/**' \
  -g '!docs/superpowers/specs/2026-07-20-repository-layout-design.md' \
  -g '!docs/superpowers/plans/2026-07-20-repository-layout-migration.md' \
  '(\./run_(e2e|edu_e2e|gpio_e2e)\.sh|\bqemu_(run|edu|platform)\.sh|python3 verification/|verification/run_qemu_experiments\.sh|\bdrivers/(test|holdout|multisource)/|\boutput/|\bkernel/build/|\bexperiments/results/|\(cd paper\b|\bpaper/(generated_results\.tex|paper\.pdf))' \
  README.md REPRO.md PROMPT.md docs platform qa scripts src tools benchmarks research/reference-success
```

Expected: no active repository-root compatibility references. Linux-internal
paths such as `drivers/gpio/*.o`, comments describing upstream Linux paths, and
the new design document are not failures.

- [ ] **Step 5: Run optional local runtime checks when prerequisites exist**

Run:

```bash
if test -f platform/kernel/build/arch/x86/boot/bzImage; then
  make -C qa/verification/device-registrar \
    KERNELDIR="$PWD/platform/kernel/build"
else
  echo "SKIP registrar: built kernel unavailable"
fi
if command -v qemu-system-x86_64 >/dev/null && \
   test -f platform/kernel/build/arch/x86/boot/bzImage; then
  ./run.sh qemu-experiments
else
  echo "SKIP QEMU: qemu-system-x86_64 or built kernel unavailable"
fi
```

Expected: the registrar builds when the kernel tree is available; QEMU reports
`QEMU_EXPERIMENTS_OK` when QEMU and the built kernel are available. If either
prerequisite is absent, record the skipped check explicitly rather than
claiming it passed.

- [ ] **Step 6: Perform the final evidence audit**

Run:

```bash
git diff --check
git status --short --branch
find . -maxdepth 1 -mindepth 1 -printf '%y %f -> %l\n' | sort
find . -type d -name __pycache__ -print
```

Expected: `git diff --check` exits 0; the root matches the contract; no Python
cache directory remains; status contains no accidental changes to frozen
results, history, or the Linux submodule.
