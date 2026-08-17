# V2 Academic Figures Design

## Goal

Add three academic-style vector figures to `research/paper/v2/` that make the evaluation boundary and evidence scope easier to interpret without introducing unsupported claims or manually duplicated measurements.

## Visual Direction

Use a restrained blue-orange palette throughout the new figures:

- Blue (`#1d4ed8`) denotes deterministic compilation or source-level evidence.
- Orange (`#f97316`) denotes strict readiness or propagated RIS evidence.
- Neutral gray denotes axes, annotations, limitations, and unselected states.

Figures remain vector-based TikZ graphics, use accessible contrast, avoid gradients and decorative elements, and include `\\Description{...}` text for PDF accessibility. Existing `tikz` and `xcolor` packages in `main.tex` are sufficient.

## Figure 1: Compilation Versus Strict Readiness

### Purpose and placement

Insert a grouped bar chart in the Evaluation section immediately before or after the readiness table (`sections_6_8.tex`, RQ3--RQ4). The chart should make the compilation/readiness gap visible at a glance.

### Data

Use generated macros from `generated_results.tex`, not hard-coded values in prose:

| Backend | Compilation | Strict readiness | Denominator |
| --- | ---: | ---: | ---: |
| Harness | `\\HarnessCompileCount` | `\\HarnessReadyCount` | `\\EvalDrivers` |
| Bare-metal | `\\BaremetalCompileCount` | `\\BaremetalReadyCount` | `\\EvalDrivers` |
| Linux | `\\LinuxCompileCount` | `\\LinuxReadyCount` | `\\EvalDrivers` |

The current generated values are 19/4, 19/4, and 18/2. The y-axis is bounded at 19 and labelled “drivers (of 19)”. Blue bars represent compilation and orange bars represent strict artifact readiness. Include a compact legend and a note in the caption that readiness is limited to the modeled contract and exercised checks.

### Claim boundary

The figure must not imply that a compiling artifact is semantically equivalent or that a non-ready artifact is unusable for all purposes. Its caption should state that compilation is necessary but not sufficient for the reported strict readiness gate.

## Figure 2: Verification Scope Matrix

### Purpose and placement

Insert a two-column matrix/flow figure in the Verification subsection (`sections_6_8.tex`, near the description of the gate). It should show the ordered checks and explicitly separate checked properties from properties outside the gate.

### Structure

The left side is a downward flow with four blue/orange stages:

1. Compilation.
2. Receipt accounting (exactly-once recognized operations).
3. AST primitive-shape and callback attestation checks.
4. Exercised-path trace comparison.

The right side is a neutral gray “Not established by this gate” panel listing:

- arbitrary addresses and values outside recognized evidence;
- guard equivalence for every input;
- global cross-operation ordering beyond exercised traces;
- extra accesses and unmodeled side effects;
- DMA, interrupt races, and lifecycle/concurrency behavior.

Use a dashed boundary around the whole figure labelled “bounded evidence contract”. Add a red/orange warning line at the bottom: “does not establish whole-driver equivalence”. The figure should fit one ACM column when resized and remain legible at normal PDF zoom.

### Claim boundary

The caption must say that the left column enumerates checks implemented by the current artifact and the right column records explicit non-claims. It must not use terms such as “proof” or “complete verification”.

## Figure 3: Multi-Source MMIO Evidence Expansion

### Purpose and placement

Insert a grouped bar chart in the multi-source evaluation subsection (`sections_6_8.tex`, next to `MultiSourceResultsTable`). Use a logarithmic y-axis because `dwc2` dominates the range.

### Data

The chart compares source MMIO counts with propagated RIS MMIO counts for the three modules:

| Module | Source MMIO | RIS MMIO |
| --- | ---: | ---: |
| aspeed-vhub | 101 | 154 |
| c67x00 | 2 | 32 |
| dwc2 | 804 | 3608 |

Values should be defined in `generated_results.tex` as small data macros or passed through a local TikZ table. Keep the chart values synchronized with `MultiSourceResultsTable`; do not introduce a second manually maintained result source if a generated macro is practical.

### Claim boundary

The caption must explicitly state that propagation counts indicate recorded evidence after multi-source analysis; they are not precision/recall measurements and do not establish a complete hardware-access footprint. The log axis must be labelled clearly so the visual comparison is not mistaken for a linear ratio.

## Integration and validation

- Add stable labels `fig:readiness-gap`, `fig:verification-scope`, and `fig:multisource-mmio`.
- Add nearby prose references using `Figure~\\ref{...}` and keep captions self-contained.
- Preserve the existing architecture figure and table macros.
- Compile sequentially with `pdflatex research/paper/v2/main.tex` twice from its directory.
- Run `git diff --check` and inspect the generated PDF page count and log for undefined references.
- If a figure causes overflow, reduce only its TikZ dimensions or font sizes; do not remove limitation text.

## Out of scope

No new experiments, measurements, bibliography entries, backend behavior, or semantic verification claims are part of this figure addition. Missing experimental evidence remains recorded in `research/paper/v2/EXPERIMENT_DEBT.md` for later work.
