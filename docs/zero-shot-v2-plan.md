# Zero-shot v2 preregistration and task record

## Purpose

`zero-shot-v2` tests whether the mechanisms completed through
`paper-artifact-v9` generalize to a second, untouched corpus.  Its purpose is
not to maximize the readiness numerator.  The corpus must be frozen before the
first extractor run, and the baseline commit must contain no changes under
`extractor/` or `generator/` relative to the frozen implementation commit.

The frozen implementation point is:

- reharness: `936265bdd97297822c371899201e7704245d4745`
- Linux: `acb7500801e98639f6d8c2d796ed9f64cba83d3a`
- extractor tree: `547debb4e800e7018d2d0da07db5c20caf5040ac`
- generator tree: `6edfa5cd5344e67df5bc8c458600327cf25db0b1`

## Selection protocol

Selection uses only repository identity, path, nonblank source size, presence
of a broad hardware/subsystem API token, and Kbuild object constructibility.
No candidate was run through extractor, generator, readiness scoring, or a
generated-backend compiler before the manifest was written.

The candidate pools and quotas are fixed in
`drivers/holdout/zero-shot-v2.json`.  Candidates are excluded if their source
basename appears in zero-shot-v1, the 19-driver main corpus, or a versioned
multi-source corpus.  Eligible files contain 80 through 800 nonblank lines and
at least one pool-specific access/subsystem token.  Within each pool they are
sorted by:

```text
sha256("zero-shot-v2:" + linux-relative-source-path)
```

The first `quota` entries are selected.  The full rank hash and global
selection order are stored per case, making the selection reproducible without
using any readiness result.  The resulting corpus intentionally includes
regmap, MFD, I2C, source-private clock arithmetic, SDHCI accessor wrappers, and
virtio-pci lifecycle code.  These are retained even if the initial pipeline
cannot recover their hardware interactions.

## Baseline protocol

1. Commit the manifest, context recipes, and this preregistration before the
   first extractor run.
2. Run the generalization guard against the v2 manifest.
3. Materialize every compile command from a real Kbuild `.cmd` file and freeze
   the merged database SHA-256 and per-command SHA-256 values.
4. Run the full matrix with `--compile-context required`, without editing
   `extractor/` or `generator/`.
5. Preserve failures, zero-operation cases, diagnostics, fallback evidence,
   backend compilation, and strict readiness as observed.  Compilation is not
   equivalent to strict readiness.
6. Cluster blockers mechanically.  The first common semantic blocker is the
   non-umbrella category covering at least three cases with the largest driver
   count, with category name as the deterministic tie-breaker.
7. Commit and push the baseline artifacts separately.  Any mechanism change
   for the selected blocker belongs in a later commit.

`linux_semantic_binding` is an umbrella blocker and is excluded from first
blocker selection.  Virtio subsystem state must remain subsystem state; it
must not be converted into fake MMIO merely to improve readiness.

## Recommended task sequence after the baseline

1. Explain the machine-selected common blocker using source evidence from all
   covered v2 cases, including at least one negative or non-applicable case.
2. Define a driver-name-agnostic semantic contract and an independent oracle
   before changing lowering or generation.
3. Add mutation tests that fail when provenance, value transforms, path
   predicates, address expressions, lifecycle transitions, or backend runner
   behavior are weakened.
4. Implement the smallest shared mechanism that addresses the cluster.  Do
   not add basename, compatible-string, Kconfig, or private-prefix cases.
5. Re-run v1, v2, the 19-driver matrix, multi-source cases, and all existing
   oracles.  Report movement separately for compile coverage, access
   accounting, and strict readiness.
6. Add a versioned strict-coverage manifest describing which source contracts
   and runtime oracles justify each strict-ready result.
7. Extend differential fuzzing for computed addresses, path-sensitive RMW,
   source-private state, and subsystem callbacks before targeting a larger
   readiness numerator such as 10/19.

The research stopping rule is evidence-based: if the common blocker requires
whole-subsystem emulation, cross-translation-unit ownership recovery, or
unavailable hardware behavior, record that boundary rather than replacing it
with permissive fallback semantics.
