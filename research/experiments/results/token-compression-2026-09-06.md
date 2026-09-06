# LLM token compression: measured deltas (2026-09-06)

Output-side (mechanical scaffold) and input-side (alias tables, evidence-JSON
dedup, audit-tag strip) compression landed on `langgraph` as fcd2b70, fc79331,
b1eb8af, d1de0d1. This note records the measurements behind those commits so
the paper cites versioned numbers. Small-n smoke; single endpoint; no
repetition.

## Output side: mechanical scaffold (fc79331)

The harness backend now emits part 00 (includes, register `#define`s from the
register map, the 64 KiB backing window, 16 self-tracing MMIO primitives,
untraced raw readers) deterministically; the LLM emits only part 01 (driver
struct, stubs, module functions, `main()`).

Live before/after pairs — same driver, same evidence mode, same model
(mimo-v2.5-pro, temperature 0), generated-output character counts
(`generated/harness.c` before, `generated/part-01.c` after):

| driver | mode | before | after | delta |
|---|---|---|---|---|
| ahci_ceva | full | 22372 | 14367 | −35.8% |
| ahci_ceva | ris_only | 18327 | 16996 | −7.3% |
| edu | full | 9470 | 3942 | −58.4% |
| edu | ris_only | 8796 | 6627 | −24.7% |

Before-pairs from the 2026-09-05 evidence-mode run
(`artifacts/output/eval-evidence-mimo*/`), after-pairs from the scaffold smoke
(`artifacts/output/scaffold-smoke-2026-09-06/`). The fixed scaffold text is
6.1–6.4 k characters — identical for every driver — which was 29–64% of the
pre-change output depending on driver size. All 4 after-cells pass the full
gate (compile, lowering receipts, AST leaf, exercised trace); 1 LLM call per
cell, zero repair rounds. Offline strip-estimate across the 23 completed
historical evidence-mode cells predicted −14.4% average; the live pairs above
bracket it (−7.3% to −58.4%).

Remaining output is driver-proper: receipts (~17% of part 01; the oracle's
marker regex fixes their shape) and driver structs/stubs.

## Input side

- **RIS alias tables** (fcd2b70): second render pass aliases register symbol
  paths repeated 2+ times to `REG<n>` and Call/ExternalCall rows repeated
  across 2+ modules to `C<n>`/`E<n>`, with a table header; positive-gain guard
  skips singletons. RIS block −5% to −24% (highbank 7866→6042 chars). Measured
  by offline prompt assembly over the frozen extraction cache.
- **Evidence-JSON dedup** (b1eb8af): ris_only mode drops per-module
  `calls`/`external_calls` from the JSON (the RIS text block already carries
  every row); modules serialize name-only. ris_only prompts −20% to −21%
  (ceva 19.0k→15.1k chars), offline prompt-assembly measurement.
- **Audit-tag strip** (d1de0d1): the LLM render drops `[Exact]/[Conservative]`
  reliability tags (~10% of RIS text); `@op_N` ids and receipt digests stay.
  Human-audit `.ris` dumps keep full tags.

## Method caveats

- Offline prompt-assembly numbers rebuild the prompt from the frozen formal
  cache rather than re-querying the endpoint; live smoke cells confirm the
  direction at the cell level.
- Single endpoint, temperature 0, one trial per cell; wall-clock not
  comparable across runs (shared box).
- Input measurements are character counts, not tokenizer-exact token counts.

Related: `evidence-modes-mimo-2026-09-05.md` (mode matrix on the same frozen
corpus), `tools/eval_evidence_modes.py` (runner).
