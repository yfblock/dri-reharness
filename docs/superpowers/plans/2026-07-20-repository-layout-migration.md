# Repository Layout Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The approved design explicitly forbids commits in the current dirty worktree, so commit steps are replaced by status/diff checkpoints.

**Goal:** Move every project, benchmark, QA, research, Pi, platform, vendored, and generated directory into the approved responsibility-based hierarchy while preserving all existing commands, imports, paths, and behavior through compatibility entries.

**Architecture:** Canonical content moves to `src/`, `qa/`, `benchmarks/`, `research/`, `platform/`, `vendor/`, `artifacts/`, and responsibility-based script/tool directories. Legacy root paths become symlinks or thin launchers so Python imports, frozen manifests, Kbuild defaults, and user commands continue to work. Each phase is guarded by structural tests and the existing semantic/runtime verification suite.

**Tech Stack:** Git moves and symlinks, Python 3, Bash, Node.js/ES modules, pytest-style direct test invocation, Linux Kbuild, Markdown path auditing.

---

## File structure produced by this plan

- `src/extractor/`: canonical extractor package.
- `src/generator/`: canonical generator package.
- `src/synthesis.py`: canonical Python bundle builder.
- `qa/tests/`: canonical test suite and fixtures.
- `qa/verification/`: canonical oracle and matrix package.
- `qa/native-tests/`: standalone C trace tests and their ignored binaries.
- `benchmarks/drivers/{baseline,holdout,multisource}/`: driver benchmark inputs.
- `scripts/{e2e,qemu,maintenance}/`: shell workflow implementations.
- `tools/pi/`: Pi Node project and dependency tree.
- `tools/{build,source,reporting}/`: non-Pi helpers.
- `research/{paper,experiments,history,reference-success}/`: research assets.
- `platform/kernel/`: kernel configs, patches, and build tree.
- `platform/rootfs/{base,platform,runtime}/`: runtime filesystem trees.
- `vendor/linux/`: Linux git submodule.
- `artifacts/output/`: generated outputs.
- `docs/{architecture,milestones,experiments,retrospectives,plans}/`: categorized documentation.
- `examples/edu/edu_drv.c`: canonical synthesized edu example.
- `tests/test_repository_layout.py` initially, then `qa/tests/test_repository_layout.py`: migration guard.
- `docs/README.md`: directory index and compatibility policy.

## Task 1: Capture the baseline and add a failing layout guard

**Files:**
- Create: `tests/test_repository_layout.py`
- Read: `.gitmodules`
- Read: `.gitignore`
- Read: `tools/e2e_common.sh`
- Read: `package.json`

- [ ] **Step 1: Record authoritative baseline state**

Run:

```bash
git status --short
git submodule status
git diff --check
python3 verification/check_generalization_guard.py
node -e 'import("@earendil-works/pi-coding-agent").then(() => console.log("pi-import: PASS"))'
```

Expected:

- the existing dirty files are visible and retained;
- the Linux gitlink is `acb7500801e98639f6d8c2d796ed9f64cba83d3a`;
- diff check and generalization guard pass;
- Node prints `pi-import: PASS`.

- [ ] **Step 2: Write the failing structural test**

Create `tests/test_repository_layout.py` with:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_DIRS = (
    "src/extractor",
    "src/generator",
    "qa/tests",
    "qa/verification",
    "qa/native-tests",
    "benchmarks/drivers/baseline",
    "benchmarks/drivers/holdout",
    "benchmarks/drivers/multisource",
    "scripts/e2e",
    "scripts/qemu",
    "scripts/maintenance",
    "tools/pi/node_modules/@earendil-works/pi-coding-agent",
    "research/paper",
    "research/experiments",
    "research/history",
    "research/reference-success",
    "platform/kernel",
    "platform/rootfs/base",
    "platform/rootfs/platform",
    "platform/rootfs/runtime",
    "vendor/linux",
    "artifacts/output",
    "examples/edu",
)

LEGACY_LINKS = {
    "extractor": "src/extractor",
    "generator": "src/generator",
    "tests": "qa/tests",
    "verification": "qa/verification",
    "test": "qa/native-tests",
    "paper": "research/paper",
    "experiments": "research/experiments",
    "history": "research/history",
    "success": "research/reference-success",
    "kernel": "platform/kernel",
    "linux": "vendor/linux",
    "output": "artifacts/output",
    "test_rootfs": "platform/rootfs/base",
    "test_rootfs_plat": "platform/rootfs/platform",
    "test_rootfs_run": "platform/rootfs/runtime",
}

LEGACY_FILE_LINKS = {
    "edu_drv.c": "examples/edu/edu_drv.c",
    "recom.md": "docs/plans/output-artifact-recommendations.md",
}


def test_canonical_repository_layout_exists():
    missing = [path for path in CANONICAL_DIRS if not (ROOT / path).exists()]
    assert not missing, missing


def test_legacy_directory_entries_resolve_to_canonical_locations():
    bad = {}
    for legacy, canonical in LEGACY_LINKS.items():
        entry = ROOT / legacy
        if not entry.is_symlink() or entry.resolve() != (ROOT / canonical).resolve():
            bad[legacy] = canonical
    assert not bad, bad


def test_driver_compatibility_tree_preserves_frozen_paths():
    expected = {
        "test": ROOT / "benchmarks/drivers/baseline",
        "holdout": ROOT / "benchmarks/drivers/holdout",
        "multisource": ROOT / "benchmarks/drivers/multisource",
    }
    for name, canonical in expected.items():
        entry = ROOT / "drivers" / name
        assert entry.is_symlink()
        assert entry.resolve() == canonical.resolve()


def test_legacy_file_entries_resolve_to_canonical_files():
    for legacy, canonical in LEGACY_FILE_LINKS.items():
        entry = ROOT / legacy
        assert entry.is_symlink()
        assert entry.resolve() == (ROOT / canonical).resolve()


def test_pi_dependencies_are_owned_by_pi_tool():
    assert not (ROOT / "node_modules").exists()
    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "package-lock.json").exists()
    assert (ROOT / "tools/pi/package.json").is_file()
    assert (ROOT / "tools/pi/package-lock.json").is_file()
```

- [ ] **Step 3: Run the structural test and verify RED**

Run:

```bash
python3 - <<'PY'
from tests.test_repository_layout import (
    test_canonical_repository_layout_exists,
    test_legacy_directory_entries_resolve_to_canonical_locations,
    test_driver_compatibility_tree_preserves_frozen_paths,
    test_legacy_file_entries_resolve_to_canonical_files,
    test_pi_dependencies_are_owned_by_pi_tool,
)
test_canonical_repository_layout_exists()
test_legacy_directory_entries_resolve_to_canonical_locations()
test_driver_compatibility_tree_preserves_frozen_paths()
test_legacy_file_entries_resolve_to_canonical_files()
test_pi_dependencies_are_owned_by_pi_tool()
PY
```

Expected: FAIL because `src/extractor` and the other canonical paths do not yet exist.

- [ ] **Step 4: Save a no-commit checkpoint**

Run:

```bash
git status --short
git diff -- tests/test_repository_layout.py
```

Expected: only the new layout test is added by this task; all pre-existing dirty changes remain.

## Task 2: Move the Pi Node project as one ownership unit

**Files:**
- Move: `package.json` → `tools/pi/package.json`
- Move: `package-lock.json` → `tools/pi/package-lock.json`
- Move: `node_modules/` → `tools/pi/node_modules/`
- Move: `tools/synth.mjs` → `tools/pi/synth.mjs`
- Move: `tools/pi_synth.sh` → `tools/pi/pi_synth.sh`
- Create compatibility links: `tools/synth.mjs`, `tools/pi_synth.sh`
- Modify: `tools/e2e_common.sh`
- Modify: `synthesis.py`

- [ ] **Step 1: Verify all Pi move targets are absent**

Run:

```bash
test ! -e tools/pi
test -f package.json
test -f package-lock.json
test -d node_modules/@earendil-works/pi-coding-agent
test -f tools/synth.mjs
test -f tools/pi_synth.sh
```

Expected: all commands succeed.

- [ ] **Step 2: Move the complete Pi project without copying**

Run:

```bash
mkdir -p tools/pi
git mv package.json tools/pi/package.json
mv package-lock.json tools/pi/package-lock.json
mv node_modules tools/pi/node_modules
git mv tools/synth.mjs tools/pi/synth.mjs
git mv tools/pi_synth.sh tools/pi/pi_synth.sh
ln -s pi/synth.mjs tools/synth.mjs
ln -s pi/pi_synth.sh tools/pi_synth.sh
```

Expected: real Pi content exists only below `tools/pi/`; the two old tool paths are symlinks.

- [ ] **Step 3: Update Pi path discovery**

Modify `tools/e2e_common.sh` so its preflight check is exactly:

```bash
  if [ ! -f "$HERE/tools/pi/node_modules/@earendil-works/pi-coding-agent/package.json" ]; then
    echo "  ✗ Pi SDK 未安装 (cd tools/pi && npm install)"; errors=$((errors+1))
  fi
```

Modify the `synthesis.py` module docstring to name `tools/pi/synth.mjs` as the canonical implementation while noting that `tools/synth.mjs` is the compatibility entry.

- [ ] **Step 4: Verify Node resolution and old entry compatibility**

Run:

```bash
node -e 'import("./tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/index.js").then(() => console.log("pi-canonical: PASS"))'
node --check tools/pi/synth.mjs
node --check tools/synth.mjs
bash -n tools/pi/pi_synth.sh
bash -n tools/pi_synth.sh
```

Expected: both Node checks and both shell syntax checks pass.

- [ ] **Step 5: Save a no-commit checkpoint**

Run:

```bash
git status --short
git diff -- tools/e2e_common.sh synthesis.py tools/pi tools/synth.mjs tools/pi_synth.sh
```

Expected: Pi files are moved once, compatibility links are visible, and no dependency tree was duplicated.

## Task 3: Categorize documentation and research assets

**Files:**
- Move: `paper/` → `research/paper/`
- Move: `experiments/` → `research/experiments/`
- Move: `history/` → `research/history/`
- Move: `success/` → `research/reference-success/`
- Create compatibility links: `paper`, `experiments`, `history`, `success`
- Move: `docs/*.md` into documented category directories
- Move: `recom.md` → `docs/plans/output-artifact-recommendations.md`
- Move: `edu_drv.c` → `examples/edu/edu_drv.c`
- Create: `docs/README.md`

- [ ] **Step 1: Create documentation and research parents**

Run:

```bash
mkdir -p research docs/architecture docs/milestones docs/experiments docs/retrospectives docs/plans
```

Expected: category directories exist and no source has moved yet.

- [ ] **Step 2: Rename research directories and add compatibility links**

Run:

```bash
git mv paper research/paper
git mv experiments research/experiments
git mv history research/history
git mv success research/reference-success
ln -s research/paper paper
ln -s research/experiments experiments
ln -s research/history history
ln -s research/reference-success success
```

Expected: old paths resolve to the exact canonical directories.

- [ ] **Step 3: Move documentation by responsibility**

Move these files to `docs/retrospectives/`:

```text
engineering-agent-retrospective-v5.md
engineering-agent-retrospective-v6.md
engineering-agent-retrospective-v7.md
engineering-agent-retrospective-v8.md
engineering-agent-retrospective-v9.md
engineering-agent-retrospective-v10.md
```

Move these files to `docs/plans/`:

```text
dwc2-lowering-plan-c18.md
linux-definition-plan-c19.md
llm-limitations.md
zero-shot-v2-plan.md
```

Move `recom.md` to
`docs/plans/output-artifact-recommendations.md` and retain a root `recom.md`
compatibility symlink.

Move these files to `docs/experiments/`:

```text
zero-shot-generalization-v1.md
zero-shot-matrix-c10.md
zero-shot-v2-baseline.md
zero-shot-v2-callback-binding.md
```

Move these files to `docs/architecture/`:

```text
transaction-ir-c24.md
regmap-lowering-c25.md
i2c-lowering-c26.md
mfd-lowering-c27.md
```

Move all remaining top-level milestone documents to `docs/milestones/`:

```text
subsystem-library-summaries-c11.md
gpio-callback-runner-c12.md
strict-readiness-c13.md
generation-lowering-receipts-c14.md
callee-rescue-c15.md
generation-attestation-c16.md
generated-c-ast-anchors-c17.md
linux-registration-attestation-c20.md
generalization-owner-field-contracts-c23.md
```

Use `git mv` for tracked files and `mv` for currently untracked C23–C27 files.

Move the synthesized root example and retain its old entry:

```bash
mkdir -p examples/edu
git mv edu_drv.c examples/edu/edu_drv.c
ln -s examples/edu/edu_drv.c edu_drv.c
```

- [ ] **Step 4: Create the documentation index**

Create `docs/README.md` with:

```markdown
# Documentation index

- `architecture/`: stable transaction and lowering architecture.
- `milestones/`: implementation records C11–C23.
- `experiments/`: frozen zero-shot protocols and results.
- `retrospectives/`: engineering-agent retrospectives.
- `plans/`: forward-looking plans and known limitations.
- `superpowers/`: approved designs and executable implementation plans.

Repository-root compatibility links preserve research paths such as `paper/`
and `experiments/`. Documentation files use their canonical categorized paths.
```

- [ ] **Step 5: Rewrite repository references to categorized docs**

Use exact path substitutions across tracked Markdown, TeX, and Python files:

```text
docs/transaction-ir-c24.md -> docs/architecture/transaction-ir-c24.md
docs/regmap-lowering-c25.md -> docs/architecture/regmap-lowering-c25.md
docs/i2c-lowering-c26.md -> docs/architecture/i2c-lowering-c26.md
docs/mfd-lowering-c27.md -> docs/architecture/mfd-lowering-c27.md
docs/engineering-agent-retrospective-vN.md -> docs/retrospectives/engineering-agent-retrospective-vN.md
docs/zero-shot-*.md -> docs/experiments/<same-name>.md, except zero-shot-v2-plan.md -> docs/plans/zero-shot-v2-plan.md
```

Apply each rewrite with `apply_patch`; do not run an unrestricted global replacement.

- [ ] **Step 6: Verify research compatibility and documentation paths**

Run:

```bash
test -f paper/paper.tex
test -d experiments/results
test -f history/timeline.md
test -f success/NOTE.md
rg -n 'docs/(transaction-ir-c24|regmap-lowering-c25|i2c-lowering-c26|mfd-lowering-c27)\.md' -g '!docs/superpowers/**'
```

Expected: the first four checks pass and `rg` prints no stale architecture-document paths.

## Task 4: Move benchmarks, tests, and verification

**Files:**
- Move: `drivers/test/` → `benchmarks/drivers/baseline/`
- Move: `drivers/holdout/` → `benchmarks/drivers/holdout/`
- Move: `drivers/multisource/` → `benchmarks/drivers/multisource/`
- Replace: `drivers/` with compatibility symlink directory
- Move: `tests/` → `qa/tests/`
- Move: `verification/` → `qa/verification/`
- Move: `test/` → `qa/native-tests/`
- Create compatibility links: `tests`, `verification`

- [ ] **Step 1: Run benchmark and QA baseline checks**

Run:

```bash
python3 verification/check_generalization_guard.py
python3 -m py_compile verification/backend_lowering_oracle.py tests/test_mfd_transaction_lowering.py
```

Expected: both commands pass.

- [ ] **Step 2: Move benchmark content and create the compatibility tree**

Run:

```bash
mkdir -p benchmarks/drivers
git mv drivers/test benchmarks/drivers/baseline
git mv drivers/holdout benchmarks/drivers/holdout
git mv drivers/multisource benchmarks/drivers/multisource
rmdir drivers
mkdir drivers
ln -s ../benchmarks/drivers/baseline drivers/test
ln -s ../benchmarks/drivers/holdout drivers/holdout
ln -s ../benchmarks/drivers/multisource drivers/multisource
```

Expected: `drivers/test/gpio-ftgpio010.c` and both holdout manifests resolve through symlinks.

- [ ] **Step 3: Move QA packages and preserve imports**

Run:

```bash
mkdir -p qa
git mv tests qa/tests
git mv verification qa/verification
git mv test qa/native-tests
ln -s qa/tests tests
ln -s qa/verification verification
ln -s qa/native-tests test
```

Expected: `from verification.backend_lowering_oracle import ...` and `from tests...` continue to resolve from the repository root.

- [ ] **Step 4: Update the layout test root calculation after its canonical move**

Modify `qa/tests/test_repository_layout.py`:

```python
ROOT = Path(__file__).resolve().parents[2]
```

This is required because the real file is now two levels below the root even though `tests/` remains a compatibility symlink.

- [ ] **Step 5: Run QA and benchmark compatibility checks**

Run:

```bash
python3 - <<'PY'
from verification.backend_lowering_oracle import build_generation_contract
from tests.test_repository_layout import test_driver_compatibility_tree_preserves_frozen_paths
test_driver_compatibility_tree_preserves_frozen_paths()
print(build_generation_contract({"driver": "empty", "modules": []})["driver"])
PY
python3 verification/check_generalization_guard.py
```

Expected: prints `empty`, then the guard reports `passed: true`.

## Task 5: Move extractor, generator, and synthesis implementation

**Files:**
- Move: `extractor/` → `src/extractor/`
- Move: `generator/` → `src/generator/`
- Move: `synthesis.py` → `src/synthesis.py`
- Create compatibility links: `extractor`, `generator`, `synthesis.py`

- [ ] **Step 1: Run source-package baseline checks**

Run:

```bash
python3 -m extractor --help
python3 - <<'PY'
import extractor, generator, synthesis
print(extractor.__file__)
print(generator.__file__)
print(synthesis.__file__)
PY
```

Expected: CLI help exits successfully and all three modules import.

- [ ] **Step 2: Move implementation packages and preserve public imports**

Run:

```bash
mkdir -p src
git mv extractor src/extractor
git mv generator src/generator
git mv synthesis.py src/synthesis.py
ln -s src/extractor extractor
ln -s src/generator generator
ln -s src/synthesis.py synthesis.py
```

Expected: canonical files exist below `src/`; root entries are symlinks.

- [ ] **Step 3: Verify imports, CLI, and syntax from compatibility paths**

Run:

```bash
python3 -m extractor --help
python3 -m py_compile extractor/*.py generator/*.py synthesis.py verification/*.py tests/*.py
python3 - <<'PY'
from extractor.extractor import ExtractorConfig, extract_ris
from generator import harness, baremetal, linux
from verification.backend_lowering_oracle import build_generation_contract
print("source-package-imports: PASS")
PY
```

Expected: all commands pass and the final line is `source-package-imports: PASS`.

## Task 6: Reclassify scripts and remaining tools

**Files:**
- Move root E2E scripts into `scripts/e2e/`
- Move root QEMU scripts into `scripts/qemu/`
- Move `log_event.sh` into `scripts/maintenance/`
- Move non-Pi tools into `tools/{build,source,reporting}/`
- Create root/tool compatibility links or wrappers

- [ ] **Step 1: Move root workflow implementations**

Run:

```bash
mkdir -p scripts/e2e scripts/qemu scripts/maintenance
git mv run.sh scripts/e2e/run.sh
git mv run_e2e.sh scripts/e2e/run_e2e.sh
git mv run_edu_e2e.sh scripts/e2e/run_edu_e2e.sh
git mv run_gpio_e2e.sh scripts/e2e/run_gpio_e2e.sh
git mv qemu_run.sh scripts/qemu/qemu_run.sh
git mv qemu_edu.sh scripts/qemu/qemu_edu.sh
git mv qemu_platform.sh scripts/qemu/qemu_platform.sh
git mv log_event.sh scripts/maintenance/log_event.sh
ln -s scripts/e2e/run.sh run.sh
ln -s scripts/e2e/run_e2e.sh run_e2e.sh
ln -s scripts/e2e/run_edu_e2e.sh run_edu_e2e.sh
ln -s scripts/e2e/run_gpio_e2e.sh run_gpio_e2e.sh
ln -s scripts/qemu/qemu_run.sh qemu_run.sh
ln -s scripts/qemu/qemu_edu.sh qemu_edu.sh
ln -s scripts/qemu/qemu_platform.sh qemu_platform.sh
ln -s scripts/maintenance/log_event.sh log_event.sh
```

- [ ] **Step 2: Make canonical scripts root-independent**

For every canonical script, replace parent-count assumptions with this root resolver:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
```

Existing variables such as `HERE` may remain, but repository paths must derive from `ROOT`.

- [ ] **Step 3: Move remaining tools by responsibility**

Use this exact mapping:

```text
tools/prepare_kernel.sh -> tools/build/prepare_kernel.sh
tools/ir_stub.py -> tools/build/ir_stub.py
tools/instrument_mmio.py -> tools/source/instrument_mmio.py
tools/sanitize.py -> tools/source/sanitize.py
tools/trace_match.py -> tools/reporting/trace_match.py
tools/generate_paper_results.py -> tools/reporting/generate_paper_results.py
```

Keep compatibility symlinks at every former `tools/<name>` path. Keep
`tools/e2e_common.sh` in place because it is the shared public E2E library.

- [ ] **Step 4: Verify all shell and Python compatibility entries**

Run:

```bash
bash -n run.sh run_e2e.sh run_edu_e2e.sh run_gpio_e2e.sh
bash -n qemu_run.sh qemu_edu.sh qemu_platform.sh log_event.sh
bash -n tools/e2e_common.sh tools/pi_synth.sh tools/build/prepare_kernel.sh
python3 -m py_compile tools/source/*.py tools/reporting/*.py tools/build/*.py
```

Expected: all syntax checks pass.

## Task 7: Move kernel, rootfs, output, and Linux submodule

**Files:**
- Move: `kernel/` → `platform/kernel/`
- Move: `test_rootfs/` → `platform/rootfs/base/`
- Move: `test_rootfs_plat/` → `platform/rootfs/platform/`
- Move: `test_rootfs_run/` → `platform/rootfs/runtime/`
- Move: `output/` → `artifacts/output/`
- Move submodule: `linux` → `vendor/linux`
- Modify: `.gitmodules`
- Modify: `.gitignore`
- Create compatibility links for every old path

- [ ] **Step 1: Verify large-tree sources and targets**

Run:

```bash
test -d kernel/build
test -d test_rootfs
test -d test_rootfs_plat
test -d test_rootfs_run
test -d output
test -f linux/.git
test ! -e platform/kernel
test ! -e artifacts/output
test ! -e vendor/linux
```

Expected: all commands succeed.

- [ ] **Step 2: Move platform and artifact trees in place**

Run:

```bash
mkdir -p platform/rootfs artifacts
git mv kernel platform/kernel
mv test_rootfs platform/rootfs/base
mv test_rootfs_plat platform/rootfs/platform
mv test_rootfs_run platform/rootfs/runtime
mv output artifacts/output
ln -s platform/kernel kernel
ln -s platform/rootfs/base test_rootfs
ln -s platform/rootfs/platform test_rootfs_plat
ln -s platform/rootfs/runtime test_rootfs_run
ln -s artifacts/output output
```

Expected: same-filesystem renames complete quickly and old paths resolve.

- [ ] **Step 3: Move the Linux submodule with Git awareness**

Run:

```bash
mkdir -p vendor
git mv linux vendor/linux
```

Modify `.gitmodules` to:

```ini
[submodule "linux"]
	path = vendor/linux
	url = https://github.com/torvalds/linux.git
```

Verify or repair the submodule metadata so:

```text
vendor/linux/.git -> ../../.git/modules/linux
.git/modules/linux/config core.worktree -> ../../../vendor/linux
```

Then create:

```bash
ln -s vendor/linux linux
```

- [ ] **Step 4: Update ignore rules for canonical generated locations**

Modify `.gitignore` so it contains:

```gitignore
# Generated RIS output (canonical path plus compatibility entry)
/artifacts/output/
/output

# Pi SDK dependencies live with the Pi tool
/tools/pi/node_modules/
/tools/pi/package-lock.json

# QEMU/build artifacts
/platform/kernel/build/
/kernel/build
/platform/rootfs/
/test_rootfs
/test_rootfs_run
/test_rootfs_plat
```

Retain all existing compiler, LaTeX, editor, and module artifact rules.

- [ ] **Step 5: Verify the submodule and large-tree compatibility paths**

Run:

```bash
git submodule status
git -C vendor/linux rev-parse HEAD
git -C linux rev-parse HEAD
test -f kernel/build/Makefile
test -d output/zero-shot-contexts
```

Expected: both Linux commands print
`acb7500801e98639f6d8c2d796ed9f64cba83d3a`; kernel and output compatibility paths work.

## Task 8: Make the structural guard GREEN and update public documentation

**Files:**
- Modify: `qa/tests/test_repository_layout.py`
- Modify: `README.md`
- Modify: `REPRO.md`
- Modify: `PROMPT.md`
- Modify: `docs/README.md`
- Modify: path-bearing scripts and Python modules found by audit

- [ ] **Step 1: Run the structural guard and inspect remaining failures**

Run:

```bash
python3 - <<'PY'
from tests.test_repository_layout import (
    test_canonical_repository_layout_exists,
    test_legacy_directory_entries_resolve_to_canonical_locations,
    test_driver_compatibility_tree_preserves_frozen_paths,
    test_legacy_file_entries_resolve_to_canonical_files,
    test_pi_dependencies_are_owned_by_pi_tool,
)
test_canonical_repository_layout_exists()
test_legacy_directory_entries_resolve_to_canonical_locations()
test_driver_compatibility_tree_preserves_frozen_paths()
test_legacy_file_entries_resolve_to_canonical_files()
test_pi_dependencies_are_owned_by_pi_tool()
print("repository-layout: PASS")
PY
```

Expected: `repository-layout: PASS`.

- [ ] **Step 2: Add the canonical layout to README**

Add a `Repository layout` section to `README.md` containing:

```markdown
## Repository layout

- `src/`: extractor, generators, and synthesis bundle code.
- `qa/`: automated tests and independent verification/oracles.
- `benchmarks/`: baseline, zero-shot, and multi-source driver inputs.
- `tools/pi/`: Pi coding-agent synthesizer and its local Node dependencies.
- `research/`: paper sources, versioned experiment results, history, and known-good artifacts.
- `platform/`: kernel build assets and test root filesystems.
- `vendor/`: pinned third-party source trees.
- `artifacts/`: regenerable output.

Legacy root paths remain compatibility links during this migration, so
existing commands and imports continue to work.
```

- [ ] **Step 3: Audit and fix canonical path references**

Run:

```bash
rg -n '\b(extractor|generator|verification|tests|drivers|linux|kernel|output|experiments|paper|history|success)/' \
  -g '!vendor/linux/**' -g '!platform/kernel/build/**' \
  -g '!tools/pi/node_modules/**' -g '!artifacts/output/**'
```

For source-owned defaults and documentation, prefer canonical paths. Retain
legacy paths only in explicit compatibility tests, old-command documentation,
or frozen external data whose content hash must not change.

- [ ] **Step 4: Verify Markdown links and root cleanliness**

Run a repository-relative link checker over `README.md`, `REPRO.md`,
`PROMPT.md`, and `docs/**/*.md`. It must reject any local Markdown target that
does not exist. Then run:

```bash
find . -maxdepth 1 -mindepth 1 -printf '%f %y\n' | sort
```

Expected: implementation content is under canonical directories; old names are identifiable links or wrapper files.

## Task 9: Run semantic, build, and compatibility regression

**Files:**
- Test: `qa/tests/test_repository_layout.py`
- Test: `qa/tests/test_regmap_transaction_lowering.py`
- Test: `qa/tests/test_i2c_transaction_lowering.py`
- Test: `qa/tests/test_mfd_transaction_lowering.py`
- Test: `qa/tests/test_extractor.py`

- [ ] **Step 1: Run syntax and import verification**

Run:

```bash
python3 -m py_compile extractor/*.py generator/*.py synthesis.py verification/*.py tests/*.py
python3 -m extractor --help
python3 - <<'PY'
import extractor, generator, verification, synthesis
print("compat-imports: PASS")
PY
```

Expected: all checks pass.

- [ ] **Step 2: Run focused transaction regression**

Run the existing direct-call suite:

```bash
python3 -u - <<'PY'
import tempfile
from pathlib import Path
from tests.test_i2c_transaction_lowering import (
    test_tpic2810_i2c_smbus_runner_all_backends,
    test_i2c_contract_covers_all_public_api_shapes_in_harness_and_baremetal,
)
from tests.test_regmap_transaction_lowering import (
    test_regmap_contract_lowers_scalar_update_bulk_in_harness_and_baremetal,
    test_regmap_ast_oracle_detects_helper_and_order_mutations,
    test_regmap_linux_contract_uses_real_regmap_wrappers,
)
from tests.test_mfd_transaction_lowering import (
    test_twl6040_mfd_runner_all_backends,
    test_mfd_linux_helper_substitution_is_rejected,
)
root = Path(tempfile.mkdtemp(prefix="reharness-layout-regression-"))
for test in (
    test_tpic2810_i2c_smbus_runner_all_backends,
    test_i2c_contract_covers_all_public_api_shapes_in_harness_and_baremetal,
    test_regmap_contract_lowers_scalar_update_bulk_in_harness_and_baremetal,
    test_twl6040_mfd_runner_all_backends,
):
    test(root)
for test in (
    test_regmap_ast_oracle_detects_helper_and_order_mutations,
    test_regmap_linux_contract_uses_real_regmap_wrappers,
    test_mfd_linux_helper_substitution_is_rejected,
):
    test()
print("transaction-regression: PASS")
PY
```

Expected: `transaction-regression: PASS`; the MFD test includes Linux out-of-tree Kbuild when available.

- [ ] **Step 3: Run generalization and submodule verification**

Run:

```bash
python3 verification/check_generalization_guard.py
git submodule status
git -C vendor/linux status --short
```

Expected: guard passes, the pinned SHA is unchanged, and the submodule has no changes.

- [ ] **Step 4: Run Pi and shell compatibility verification**

Run:

```bash
node --check tools/pi/synth.mjs
node --check tools/synth.mjs
node -e 'import("./tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/index.js").then(() => console.log("pi-import: PASS"))'
bash -n run.sh run_e2e.sh run_edu_e2e.sh run_gpio_e2e.sh
bash -n qemu_run.sh qemu_edu.sh qemu_platform.sh tools/pi_synth.sh
```

Expected: all checks pass and Node prints `pi-import: PASS`.

- [ ] **Step 5: Run final integrity audit**

Run:

```bash
git diff --check
git status --short
du -sh vendor/linux platform/kernel tools/pi/node_modules artifacts/output
find . -maxdepth 1 -type l -printf '%f -> %l\n' | sort
```

Expected:

- diff check passes;
- every pre-existing dirty file is still represented at its canonical or compatibility path;
- each large tree exists once at its canonical location;
- compatibility links point to the approved targets;
- no commit has been created.

## Task 10: Optional full matrix verification when contexts are intact

**Files:**
- Generated: `artifacts/output/zero-shot-matrix/`
- Generated: `research/experiments/results/zero-shot-matrix.json`
- Generated: `research/experiments/results/multisource-matrix.json`

- [ ] **Step 1: Check exact-context availability through compatibility paths**

Run:

```bash
test -f output/zero-shot-contexts/compile_commands.json
test -f kernel/build/Makefile
```

Expected: both files exist.

- [ ] **Step 2: Run the frozen matrices**

Run:

```bash
python3 verification/run_zero_shot_matrix.py
python3 verification/run_multisource_matrix.py
```

Expected: commands complete with their existing semantic readiness policy; directory migration introduces no compile/path regression. Existing semantic blockers are allowed only if they match the pre-migration baseline.

- [ ] **Step 3: Compare migration-sensitive results**

Confirm that completed case counts, backend compile results, compile-context provenance, and blocker categories do not regress solely because of missing paths. Record any external-runtime limitation explicitly rather than changing the acceptance rule.
