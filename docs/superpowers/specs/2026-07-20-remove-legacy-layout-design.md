# Remove Legacy Repository Layout Design

## Objective

Complete the in-progress repository reorganization by removing every
repository-owned legacy root path and making the categorized directories the
only supported locations. Keep one real root `run.sh` as the public command
dispatcher, update all active code and documentation to canonical paths, and
verify that the extractor, generators, QA workflows, QEMU helpers, and research
tooling still run from the reorganized tree.

This design supersedes the compatibility-link policy in
`docs/superpowers/specs/2026-07-20-repository-layout-design.md`. The canonical
directory ownership established by that design remains valid.

## Root contract

The repository root contains only project metadata, primary documentation,
the public dispatcher, and canonical top-level directories:

```text
.gitignore
.gitmodules
PROMPT.md
README.md
REPRO.md
run.sh
artifacts/
benchmarks/
docs/
examples/
platform/
qa/
research/
scripts/
src/
tools/
vendor/
```

Dot-prefixed agent and editor state such as `.git/`, `.agents/`, `.codex/`, and
`.codegraph` is outside the project layout contract. Generated Python cache
directories are removed and ignored.

The following legacy entries are removed after their callers are migrated:

- directory links and compatibility trees: `drivers`, `experiments`,
  `extractor`, `generator`, `history`, `kernel`, `linux`, `output`, `paper`,
  `success`, `test`, `tests`, `test_rootfs`, `test_rootfs_plat`,
  `test_rootfs_run`, and `verification`;
- file links: `edu_drv.c`, `log_event.sh`, `qemu_edu.sh`, `qemu_platform.sh`,
  `qemu_run.sh`, `recom.md`, `repo_paths.py`, `run_e2e.sh`,
  `run_edu_e2e.sh`, `run_gpio_e2e.sh`, and `synthesis.py`;
- obsolete root-owned files: `plan.md` and the three `initramfs_*.cpio.gz`
  images, after moving them to canonical locations.

`run.sh` is deliberately retained as a real executable file, not a symlink.

## Canonical ownership additions

- `plan.md` moves to `docs/plans/original-implementation-plan.md`.
- `initramfs_edu.cpio.gz`, `initramfs_plat.cpio.gz`, and
  `initramfs_run.cpio.gz` move to `artifacts/initramfs/` with their existing
  basenames.
- `src/extractor/`, `src/generator/`, and `src/synthesis.py` remain the only
  implementation locations.
- `qa/tests/`, `qa/verification/`, and `qa/native-tests/` remain the only QA
  locations.
- driver paths use `benchmarks/drivers/baseline/`,
  `benchmarks/drivers/holdout/`, and `benchmarks/drivers/multisource/`.
- generated output paths use `artifacts/output/`.
- the Linux tree and kernel build assets use `vendor/linux/` and
  `platform/kernel/`.
- rootfs paths use `platform/rootfs/{base,platform,runtime}/`.
- paper, experiment, history, and reference artifacts use their `research/`
  locations.

## Command dispatcher

The current implementation in `scripts/e2e/run.sh` becomes the real root
`run.sh`. It discovers the repository root from its own location, exports
`PYTHONPATH="$ROOT/src:$ROOT/qa:$ROOT"`, and invokes only canonical paths.

Existing public command forms remain available:

```text
./run.sh extract <src> [out.ris]
./run.sh show <ris>
./run.sh spec <src> [out.dspec]
./run.sh gen <src> <backend> [out.c]
./run.sh driver <src> [outdir]
./run.sh facts <src> [out]
./run.sh bundle <src> [backend] [outdir]
./run.sh metrics <src>
./run.sh score <src>
./run.sh reliability [src ...]
./run.sh compare [-j N]
./run.sh demo
./run.sh test
```

The dispatcher also owns the commands previously exposed by root script links:

```text
./run.sh e2e <src> [subsystem] [skip_synth]
./run.sh edu-e2e [skip_synth]
./run.sh gpio-e2e [src] [skip_synth]
./run.sh qemu <module> [qemu options]
./run.sh qemu-edu <module> [timeout]
./run.sh qemu-platform <module> <registrar-target> [timeout]
./run.sh qemu-experiments
./run.sh log-event <message ...>
```

The implementation scripts remain under `scripts/e2e/`, `scripts/qemu/`, and
`scripts/maintenance/`. They call `run.sh` or other scripts through absolute
canonical paths derived from the repository root, never through removed root
aliases.

## Python imports and path discovery

Moving the packages below `src/` and `qa/` means repository commands may no
longer rely on the current working directory exposing `extractor`, `generator`,
or `verification` as top-level directories.

- `run.sh` supplies the canonical `PYTHONPATH` for all public commands.
- standalone QA scripts use `qa/verification/repo_paths.py` to add `src/` and
  `qa/` when invoked directly.
- tests import production modules from `src/` and QA helpers from `qa/`.
- subprocesses inherit the canonical Python path or construct it explicitly.
- user-facing help text and Python defaults name `vendor/linux/`,
  `platform/kernel/`, `benchmarks/drivers/`, and `artifacts/output/`.

No packaging-system conversion is included. Installing the project as a wheel
or introducing a new namespace package remains out of scope.

## Reference migration policy

Active source, shell scripts, tests, manifests, current documentation, build
configuration, and ignore rules are rewritten to canonical paths. This
includes paths embedded in shell heredocs and subprocess argument lists.

Frozen experiment JSON, historical logs, and previously generated evidence may
retain old absolute or repository-relative paths because those strings record
the environment in which the evidence was produced. They are not executable
path contracts. The path audit excludes these immutable records but includes
the code that creates future records.

Multi-source manifests and holdout definitions are updated only when a field is
an executable repository path. Their semantic contents, source hashes, Linux
revision, and benchmark membership must remain unchanged.

## Structural guard

`qa/tests/test_repository_layout.py` is updated to assert:

1. every canonical directory and required entry exists;
2. no listed legacy root entry exists, including as a symlink;
3. root `run.sh` is a regular executable file;
4. `.gitmodules` points to `vendor/linux`;
5. active project files do not refer to removed root paths;
6. the three initramfs images and original plan exist only at their canonical
   destinations.

The reference scanner uses explicit exclusions for `.git/`, `vendor/linux/`,
`tools/pi/node_modules/`, generated artifacts, frozen experiment results, and
historical logs. It reports the file, line, and legacy token for every active
violation.

## Migration sequence

1. Record the dirty worktree and establish a clean behavioral baseline without
   modifying existing user changes.
2. Add or update structural tests so they fail while legacy entries remain.
3. Move the root dispatcher and root-owned files to their final locations.
4. Rewrite Python, shell, manifest, build, and current documentation paths in
   focused batches.
5. Run focused tests after each batch and repair path discovery at the owning
   boundary.
6. Remove all legacy entries only after the active-reference audit is empty.
7. Run the complete repository verification set and inspect the final root and
   Git diff.

## Failure handling

- The migration works with the current dirty tree and does not reset, clean,
  or revert existing changes.
- A canonical destination must exist and contain the expected content before a
  legacy entry is removed.
- A failed reference audit or focused test blocks deletion of the affected
  compatibility entry.
- Frozen evidence is never rewritten merely to make a textual path search
  empty.
- QEMU or LLM-dependent checks that cannot run because of unavailable external
  dependencies are reported separately; their local syntax and preflight
  checks must still pass.

## Verification

Completion requires fresh evidence for all applicable checks:

- shell syntax for `run.sh` and every script under `scripts/`;
- `./run.sh help` and dispatcher argument/error behavior;
- repository layout structural tests;
- zero-shot specialization guard;
- the complete core test suite through `./run.sh test`;
- extraction, specification, and all three generator backends on a baseline
  driver using canonical input and output paths;
- focused reliability/oracle smoke checks that do not regenerate frozen
  evidence unintentionally;
- Python byte-compilation for `src/` and `qa/`;
- Pi script and Node module resolution checks;
- Linux submodule path and pinned revision checks;
- Markdown/current-command reference audit;
- `git diff --check` and a final root listing proving that no legacy entry
  remains.

## Non-goals

- Changing extraction, formalization, generation, or verification semantics.
- Recomputing or normalizing frozen research evidence.
- Updating the pinned Linux revision or Node dependencies.
- Replacing the shell dispatcher with Make, a Python CLI package, or another
  task runner.
- Removing dot-prefixed agent/editor state owned by the local development
  environment.
