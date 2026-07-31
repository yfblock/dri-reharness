# Repository Layout Reorganization Design

## Objective

Reorganize every repository-owned, vendored, generated, experimental, and
runtime directory into a clear responsibility-based hierarchy without
changing extractor, generator, verification, synthesis, Kbuild, QEMU, paper,
or benchmark behavior.

The migration must preserve the current dirty worktree. It must not discard,
rewrite, or accidentally commit unrelated changes already present.

## Design principles

1. Physical ownership should be obvious from the real location of a file.
2. Existing public commands and Python import names must continue to work.
3. Large generated or external trees must not be copied; they are renamed on
   the same filesystem.
4. Compatibility paths are explicit migration interfaces, not duplicate
   sources of truth.
5. Every migration batch must be independently reversible and verified before
   the next batch starts.
6. Generated artifacts, benchmark inputs, third-party sources, and framework
   implementation must remain separate.

## Target top-level layout

```text
reharness/
├── src/
│   ├── extractor/                 # Python extraction/formalization package
│   ├── generator/                 # Harness, bare-metal, Linux generators
│   └── synthesis.py               # Python synthesis bundle assembly
├── qa/
│   ├── tests/                     # Automated tests and small source fixtures
│   ├── verification/              # Oracles, matrices, guards, reports
│   └── native-tests/              # Standalone C trace tests and binaries
├── benchmarks/
│   └── drivers/
│       ├── baseline/              # Former drivers/test
│       ├── holdout/               # Frozen zero-shot manifests
│       └── multisource/           # Multi-translation-unit manifests
├── scripts/
│   ├── e2e/                       # End-to-end driver synthesis workflows
│   ├── qemu/                      # QEMU launch and judging entry points
│   └── maintenance/               # Logging and repository maintenance
├── tools/
│   ├── pi/                        # Pi SDK synthesizer and local Node project
│   │   ├── package.json
│   │   ├── package-lock.json
│   │   ├── node_modules/
│   │   ├── synth.mjs
│   │   └── pi_synth.sh
│   ├── build/                     # Kernel preparation/build helpers
│   ├── source/                    # Source sanitizing/instrumentation helpers
│   └── reporting/                 # Trace and paper-result generation helpers
├── research/
│   ├── paper/                     # LaTeX source and generated paper PDF
│   ├── experiments/               # Versioned experiment results
│   ├── history/                   # Historical logs and timeline
│   └── reference-success/         # Known-good generated examples
├── platform/
│   ├── kernel/                    # Kernel configs, patches, and ignored build
│   └── rootfs/
│       ├── base/
│       ├── platform/
│       └── runtime/
├── vendor/
│   └── linux/                     # Pinned Linux git submodule
├── artifacts/
│   └── output/                    # Ignored generated RIS/backend artifacts
├── examples/
│   └── edu/                       # User-facing synthesized edu example
├── docs/
│   ├── architecture/
│   ├── milestones/
│   ├── experiments/
│   ├── retrospectives/
│   ├── plans/
│   └── superpowers/               # Design and implementation plans
├── README.md
├── REPRO.md
└── PROMPT.md
```

`corpora/` is deliberately not used. The driver collection is a reproducible
evaluation benchmark, so `benchmarks/drivers/` communicates its role more
clearly.

## Exact ownership mapping

| Current path | Canonical path | Compatibility requirement |
| --- | --- | --- |
| `extractor/` | `src/extractor/` | Root `extractor` symlink preserves imports and `python -m extractor` |
| `generator/` | `src/generator/` | Root `generator` symlink preserves imports |
| `synthesis.py` | `src/synthesis.py` | Root forwarding module or symlink preserves callers |
| `tests/` | `qa/tests/` | Root `tests` symlink preserves test paths |
| `verification/` | `qa/verification/` | Root `verification` symlink preserves imports and commands |
| `test/` | `qa/native-tests/` | Root `test` symlink preserves standalone trace-test paths |
| `drivers/test/` | `benchmarks/drivers/baseline/` | Root `drivers/` compatibility directory links `test`, `holdout`, and `multisource` to canonical locations |
| `drivers/holdout/` | `benchmarks/drivers/holdout/` | Frozen manifest contents and hashes remain unchanged |
| `drivers/multisource/` | `benchmarks/drivers/multisource/` | Existing manifest-relative paths remain valid through compatibility path |
| `tools/synth.mjs` | `tools/pi/synth.mjs` | Old tool path forwards to canonical entry |
| `tools/pi_synth.sh` | `tools/pi/pi_synth.sh` | Old shell entry remains executable |
| root `package*.json` | `tools/pi/package*.json` | No root Node project remains |
| root `node_modules/` | `tools/pi/node_modules/` | Pi script resolves its adjacent dependencies directly |
| remaining `tools/*` | responsibility subdirectories under `tools/` | Stable wrappers retained only for documented commands |
| root `run*.sh` | `scripts/e2e/` | Root wrappers preserve old commands |
| root `qemu*.sh` | `scripts/qemu/` | Root wrappers preserve old commands |
| `log_event.sh` | `scripts/maintenance/log_event.sh` | Root wrapper retained |
| root `edu_drv.c` | `examples/edu/edu_drv.c` | Root compatibility link retained |
| root `recom.md` | `docs/plans/output-artifact-recommendations.md` | Root compatibility link retained |
| `paper/` | `research/paper/` | Root `paper` link preserves LaTeX commands and references |
| `experiments/` | `research/experiments/` | Root link preserves report paths |
| `history/` | `research/history/` | Root link preserves historical references |
| `success/` | `research/reference-success/` | Root link preserves known-good paths |
| `kernel/` | `platform/kernel/` | Root link preserves `kernel/build` and Kbuild defaults |
| `test_rootfs/` | `platform/rootfs/base/` | Root link retained |
| `test_rootfs_plat/` | `platform/rootfs/platform/` | Root link retained |
| `test_rootfs_run/` | `platform/rootfs/runtime/` | Root link retained |
| `linux` submodule | `vendor/linux/` | `.gitmodules` updated; root `linux` link preserves source paths |
| `output/` | `artifacts/output/` | Root link preserves CLI defaults and historical commands |
| `docs/*.md` | categorized `docs/` subdirectories | Every Markdown link is rewritten and checked |

The canonical path contains the only real content. Compatibility paths are
links or forwarding launchers and must never contain independent copies.

## Python package and command compatibility

The current code imports top-level packages such as `extractor`, `generator`,
and `verification`. Moving them below `src/` and `qa/` without a compatibility
layer would change Python module discovery for hundreds of commands.

During this migration:

- root compatibility symlinks preserve the current package names;
- internal code may continue using the established absolute imports;
- `python3 -m extractor` remains valid from the repository root;
- scripts calculate the repository root from their own canonical path rather
  than assuming a fixed number of parent directories;
- no packaging-system conversion is included in this task.

Converting the project to one installable namespace package would be a
separate behavioral migration and is intentionally out of scope.

## Pi/Node ownership

Pi is a self-contained tool, not a repository-wide JavaScript application.
Its package manifest, lock file, dependency tree, JavaScript entry point, and
shell adapter therefore move together to `tools/pi/`.

`tools/pi/synth.mjs` resolves
`@earendil-works/pi-coding-agent` from `tools/pi/node_modules` using normal
Node resolution. E2E preflight checks the same canonical location. Existing
commands using `tools/synth.mjs` or `tools/pi_synth.sh` continue through
compatibility entries.

## Linux submodule and build assets

`linux` is a pinned git submodule, not a plain vendored directory. Migration
must use a submodule-aware move, update `.gitmodules` from `linux` to
`vendor/linux`, and verify that the gitlink still points to
`acb7500801e98639f6d8c2d796ed9f64cba83d3a`.

The ignored `kernel/build` tree, rootfs trees, Node dependencies, and output
artifacts are large. They are renamed in place and never copied. Before every
move the exact source and target are resolved and checked; an existing target
causes a fail-closed stop.

## Documentation classification

- `architecture/`: stable architecture and semantic-boundary documents;
- `milestones/`: C10–C27 implementation milestone records;
- `experiments/`: zero-shot protocols, baselines, and measured reports;
- `retrospectives/`: engineering-agent retrospective documents;
- `plans/`: forward-looking implementation plans and limitations;
- `superpowers/`: this design and its executable migration plan.

All repository-relative Markdown links, shell command examples, paper input
paths, and result-generation paths must be updated. A link/path audit rejects
references to removed canonical locations unless they intentionally test a
compatibility entry.

## Migration phases

### Phase 1: Baseline and migration guard

Record the dirty worktree, submodule commit, relevant file hashes, supported
commands, focused transaction tests, generalization guard, and Linux MFD
Kbuild result. Add a structural test describing the target layout and required
compatibility paths. The test must fail before migration.

### Phase 2: Low-risk documentation and research assets

Create category directories, move documentation and research assets, rewrite
links, and verify paper/result paths. Compatibility links remain for top-level
research directories.

### Phase 3: Pi and tools

Move the complete Pi Node project together, split remaining tools by
responsibility, install compatibility entry points, and test Node module
resolution and E2E preflight.

### Phase 4: Benchmarks and QA

Move driver benchmarks, tests, and verification code. Preserve old import and
manifest paths through compatibility links. Run source oracle, mutation,
matrix guard, and focused transaction suites.

### Phase 5: Framework implementation

Move extractor, generator, and synthesis implementation. Verify Python module
imports, CLI help, extraction, all three backends, and Kbuild.

### Phase 6: External and generated trees

Move the Linux submodule, kernel assets, rootfs trees, and output artifacts.
Update `.gitmodules`, ignore rules, defaults, scripts, and documentation.
Verify the submodule SHA, exact compile contexts, QEMU path discovery, and
output generation.

### Phase 7: Root entry points and final audit

Move root scripts to their canonical directories, leave thin compatibility
wrappers, and audit the final root. Run the full proportional regression set
and verify that compatibility paths resolve to the canonical files.

## Failure handling and rollback

- Every phase starts with target-nonexistence and source-existence checks.
- Tracked moves and compatibility entries are reviewed before proceeding.
- Content is never copied into a second source of truth; the migration uses
  same-filesystem renames, so rollback is the inverse rename.
- If a phase fails verification, later phases do not start.
- Existing user changes are identified by path before movement and must remain
  byte-for-byte present at their new canonical location.
- No automatic commit, reset, checkout, clean, or destructive recursive delete
  is permitted during the migration.

## Verification requirements

The migration is complete only when all of the following hold:

1. The canonical target tree exists and contains every original file.
2. The old documented CLI and shell entry points still execute.
3. `extractor`, `generator`, and `verification` imports still resolve.
4. Python syntax compilation passes for project packages and tests.
5. Regmap, I2C/SMBus, and MFD focused lowering/runtime/mutation tests pass.
6. Linux MFD generated output passes out-of-tree Kbuild.
7. The zero-shot generalization guard passes.
8. The Linux submodule remains at the pinned commit and is not dirty.
9. Pi SDK import resolution and E2E preflight find `tools/pi/node_modules`.
10. Repository-relative Markdown links and script path references resolve.
11. `git diff --check` passes and the pre-existing dirty changes remain present.
12. No large tree was duplicated during migration.

Full zero-shot and multi-source matrix regeneration is run if its existing
compile contexts remain available after the move. If an external runtime or
credential prevents an optional QEMU/LLM execution, the structural preflight
must still pass and the limitation is reported rather than silently ignored.

## Non-goals

- Redesigning extractor/generator behavior.
- Changing transaction IR or backend lowering semantics.
- Removing compatibility paths in the same change.
- Publishing a new Python package namespace.
- Reinstalling or upgrading Pi dependencies.
- Updating the pinned Linux submodule revision.
- Committing the existing dirty worktree.
