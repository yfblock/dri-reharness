# C14: RIS-to-backend lowering receipts

## Problem

The source-to-RIS side already accounts source access sites, stable `op_id`
values and provenance.  The generated C previously discarded those IDs for
normal Read, Write and ReadModifyWrite operations.  Compilation and the
harness offset subsequence check therefore could not distinguish a complete
lowering from one that silently omitted, duplicated or rejected an operation.

This is particularly unsafe for LLM-assisted generation: a model can produce
plausible framework glue while deleting an inconvenient hardware access or
adding a familiar but source-unsupported action.  A successful compile is not
evidence that the RIS contract was preserved.

## Mechanism

Every generated register operation now carries a machine-readable receipt:

```c
/* REHARNESS_RIS_OP id=op_7 kind=Write status=lowered digest=0123456789abcdef */
```

The digest is computed from the canonical Formal RIS operation before backend
normalization.  It includes operation kind, width, address and value/transform
structure, but excludes absolute source paths.  Unsupported operations receive
`status=rejected` rather than disappearing.

`qa/verification/backend_lowering_oracle.py` independently compares the
generated receipts with `generation-contract.json` and rejects:

- missing or duplicate operation IDs;
- unknown IDs;
- rejected operations;
- kind or canonical digest mismatches;
- duplicate IDs in the source contract.

The driver pipeline writes one lowering report per backend and strict
readiness requires that backend's report to be complete.  LLM bundles now also
contain canonical `<driver>.formal.json`, `generation-contract.json`, `.facts`
and the readiness/blocker report; the end-to-end prompt includes all of them.

## Mutation evidence

The unit oracle mutates a valid harness in five ways: delete a receipt,
duplicate it, forge an unknown ID, change its status to rejected and replace
its digest.  All five mutations must fail the gate.  FTGPIO010 produces 35/35
receipts for each of the harness, bare-metal and Linux backends.

## Newly exposed boundary

DW APB illustrates why this gate is needed.  Harness and bare-metal account for
48/48 register operations.  The Linux banked specialization initially lacked
22 receipts even though it compiled.  Adding receipts at the source-validated
specialized callbacks and bank initialization reduced this to three genuine
unresolved mappings:

- two operations from the folded double-edge trigger helper;
- one input-register read synthesized by the GPIO library contract but omitted
  by the specialized Linux initialization.

Linux strict readiness is therefore conservatively withheld until those
operations are either mapped to concrete generated statements or justified by
an independent specialization proof.  The gate intentionally prefers this
visible regression over preserving an unsupported 12/12 headline.

The same audit exposed two further real omissions in the 19-driver matrix:

- EDU Linux glue emits file read/write and probe operations but omits the two
  RIS operations in its IRQ handler because the current safe QEMU profile does
  not request the IRQ;
- Cadence Linux remove glue omits one source register write.

Sodaville initially reported four missing operations, but all four were
present in a source-preserving IRQ specialization and only lacked receipts.
Adding function-local receipts restored its complete result.  This distinction
is frozen in a regression test: specialized-but-present operations must pass,
while the EDU and Cadence omissions must remain visible.

With C14 enabled, a fresh matrix run gives harness 6/19, bare-metal 6/19,
Linux 4/19 and all-backend strict 4/19.  Zero-shot v1 remains 12/12 compiled;
harness and bare-metal are 12/12 strict, while Linux and all-backend strict are
7/12.  The five Linux holdout gaps are `clk-fixed-mmio`, `clk-moxart`,
`gpio-dwapb`, `clk-nspire` and `sdhci-npcm`.

## Scope and remaining work

Receipt bijection proves lowering accounting, not C semantic equivalence.  A
comment can still be copied next to an incorrect statement.  The next verifier
must parse generated C independently and check primitive width, byte order,
address, value/RMW transform and enclosing guards against the canonical
contract.  Runtime traces should then move from offset subsequences to exact
op-ID traces for exercised paths.
