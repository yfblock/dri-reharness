# Zero-shot v2 frozen baseline

## Frozen points and execution rule

The v2 corpus was committed as `8a23af0` before its first extractor run.  Its
implementation reference remains `936265b`; the extractor and generator tree
objects are respectively `547debb4e800e7018d2d0da07db5c20caf5040ac` and
`6edfa5cd5344e67df5bc8c458600327cf25db0b1`.  No file under either protected
root changed while producing this baseline.

The Linux source commit is
`acb7500801e98639f6d8c2d796ed9f64cba83d3a`.  All 12 translation units used
`--compile-context required` and a command recovered from a real Kbuild `.cmd`
file.  The merged compile database SHA-256 is:

```text
036a4f115dc51743ee0322c3e07e39fb53bf4809cc76922d86ae301cd5a1229a
```

The versioned context report is
`experiments/results/zero-shot-v2-contexts.json`; the baseline matrix is
`experiments/results/zero-shot-v2-matrix.json`.

```text
context report SHA-256: e8282b6d6e31f35e28abc1fab81a936f73478c95d152d2ba20899be21dbd591a
matrix report SHA-256:  4131199f004a150175e109833de0c81f600e2e99a515f784fc620dca53a2eab8
```

## Unmodified baseline result

| Measure | Result |
| --- | ---: |
| Pipeline completed | 12/12 |
| Exact Kbuild context | 12/12 |
| Strict access accounting | 10/12 |
| Cases with recovered hardware operations | 10/12 |
| Harness / bare-metal / Linux all compile | 9/12 |
| Harness strict-ready | 1/12 |
| Bare-metal strict-ready | 1/12 |
| Linux strict-ready | 0/12 |
| All-backend strict-ready | 0/12 |

The complete repository regression passed 110/110 after the artifacts were
produced.

The matrix command returned nonzero because
`all_cases_have_hardware_interactions` is false.  This is a preserved baseline
failure, not an infrastructure failure:

- `gpio-tpic2810` performs device I/O through I2C helpers and yielded zero RIS
  operations;
- `clk-twl6040` performs source-private MFD helper calls and yielded zero RIS
  operations.

Both cases remain in the corpus.  Removing them would violate the preregistered
selection and would bias the result toward already supported access domains.

The only strict-ready result is `clk-loongson2` for harness and bare-metal;
its Linux backend remains blocked by unsupported semantic binding.  Backend
compilation also fails for harness/bare-metal on `sdhci-iproc` and
`sdhci-sprd`, and for Linux on `virtio-pci-common`.  These compile failures are
reported separately from strict readiness.

## Machine-selected first common blocker

The deterministic cluster rule selected:

```text
callback_binding: 4/12
```

Covered cases are:

- `clk-si544`
- `sdhci-milbeaut`
- `sdhci-sprd`
- `virtio-pci-legacy`

`missing_role` covers the same four cases.  The two clusters tie on driver
count, so the frozen category-name tie-breaker selects `callback_binding`.
The umbrella `linux_semantic_binding` cluster covers 10 cases and is excluded
by policy.

The raw evidence requires a more precise interpretation than the blocker
wording suggests.  The analysis already discovers table/field targets:

- `si544_clk_ops.is_prepared -> si544_is_prepared`;
- `sdhci_milbeaut_ops.voltage_switch ->`
  `sdhci_milbeaut_soft_voltage_switch`;
- `sdhci_sprd_ops` and dynamically assigned `mmc_host_ops` fields point to the
  reported SPRD functions;
- `vp_dev->del_vq -> del_vq` in virtio-pci legacy state.

However, that ownership evidence does not consistently reach the formal
function metadata.  The resulting DeviceSpec entries have `role unknown` and
no `callback owner.field`, even when `analysis.json.indirect_call_targets`
contains the qualified mapping.  The common research problem is therefore:

> Propagate typed callback-owner and field evidence from static initializers
> and source-private function-pointer assignments into the formal callback
> binding, independently of whether the field has a predeclared lifecycle
> role.

This formulation covers clock, SDHCI, MMC, and virtio without using a driver
basename or private prefix.  It also distinguishes two questions that the
current score text conflates: “is the callback owner/field known?” and “does
that callback have a supported semantic role?”

Fixing this cluster is not expected by itself to make these four cases
strict-ready.  They retain unsupported access domains, source-unaccounted
sites, subsystem summaries, loops, control flow, or source-oracle blockers.
The first success criterion is removal or refinement of false
`callback_binding` blockers while preserving conservative `missing_role`
where semantics are genuinely unknown.

## Problems encountered while producing the baseline

1. The preregistered pinned x86 build did not enable REGMAP dependencies for
   `clk-si544`.  Kbuild failed before any extractor run for that case.  The
   context recipe was corrected to a fresh x86 `allmodconfig`; the selected
   sources were not changed.
2. Host GNU `ld` could not link LoongArch or AArch64 VDSOs.  The native
   profiles now explicitly require `ld.lld`.
3. Host GNU `objcopy` could not process the AArch64 VDSO.  Context recipes now
   support recorded Kbuild tool overrides and use
   `OBJCOPY=llvm-objcopy-18` for cross-architecture profiles.
4. The matrix acceptance rule correctly exposed two zero-operation cases.  A
   tempting but invalid response would have been to replace them with easier
   drivers or relax the acceptance rule; neither was done.
5. The cluster label alone was insufficient for mechanism selection.  Human
   inspection showed that table target discovery already works, while formal
   metadata propagation is incomplete.  Future automation should report
   “binding discovered but not attached” separately from “binding absent.”

## Model capability observations

The language model was useful for turning the anti-cherry-picking requirement
into a deterministic sampling and clustering protocol, constructing the
versioned artifacts, and tracing evidence across Kbuild, analysis metadata,
DeviceSpec, and readiness reports.  It did not predict all cross-toolchain
requirements correctly: the initial context recipe assumed that a pinned x86
configuration and `ld.lld` alone would be sufficient.  Real Kbuild execution
exposed missing REGMAP configuration and cross-architecture `objcopy` needs.

The more important boundary is semantic.  A machine-readable blocker count
can select the next investigation fairly, but it cannot by itself prove that
all instances share one implementation defect.  Here, source inspection and
artifact comparison were needed to refine “callback without table binding”
into “known owner/field evidence not propagated to formal metadata.”  The
model should therefore propose and implement mechanisms, while completion
continues to depend on frozen selection, negative gates, independent oracles,
mutation tests, and rerun artifacts.

## Next task

Before modifying extractor or generator:

1. add a callback-binding oracle covering the four selected cases;
2. include static table initializers, post-allocation member assignments, and a
   negative function-pointer case that must remain unbound;
3. add mutations that remove the owner, field, or source provenance and require
   the oracle to fail;
4. only then implement generic binding-evidence propagation and rerun v1, v2,
   the main matrix, and existing oracles.

The blocker implementation must be a separate commit from this frozen
baseline.
