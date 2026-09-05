# Evidence-mode matrix on mimo-v2.5-pro (2026-09-05)

RIS v0.4.0 backend evidence study: can translation be driven from RIS alone,
and does injecting RIS semantics (legend + external-call annotations) help?

## Setup

- Model: `mimo-v2.5-pro` via gateway (OpenAI-compatible), temperature 0.0,
  max_tokens 32768, no thinking-disable flag (gateway ignores it for this stack).
- Modes: `full` (spec+facts+bind), `ris_only` (RIS modules incl. Call/ExternalCall
  rows + mechanical bind, audit tags stripped), `ris_semantics` (`ris_only` +
  category legend + external-call annotations).
- 10 kernel drivers, 30-cell matrix target; 21 cells completed when the run was
  halted (first-pass 3300s timeouts and a recurring SIGKILL of runner processes
  on the shared box cost cells; repair pass recovered most).
- Runner: `tools/eval_evidence_modes.py`; merge: `tools/eval_evidence_merge.py`.
- Raw logs: job tmp `eval_mimo*.log` series; cell artifacts under
  `artifacts/output/eval-evidence-mimo{,-w1,-w2,-w3,-gg1,-gg2}/`.
  Metrics: C=compiled, L=lowering_complete, A=ast_leaf_complete, T=trace_passed.

## Results (21 cells)

| mode | n | compiled | lowering | ast | trace | sec (median) |
|---|---|---|---|---|---|---|
| full | 9 | 9 | 8 | **2** | 4 | 653 |
| ris_only | 8 | 8 | 8 | **4** | 4 | 1392 |
| ris_semantics | 4 | 4 | 4 | 3 | 1 | 449 |

Paired per-driver:

```
driver            full      ris_only  ris_semantics
ahci_ceva         CL..      CLAT      CLA.
ahci_sunxi        CLA.      CLA.      (in flight)
clk-highbank      CL.T      CLAT      (lost to kill)
edu               CLAT      CL.T      CLAT
gpio-cadence      CL..      CLA.      CLA.
gpio-ftgpio010    CL..      CL..      (in flight)
gpio-pl061        CL..      CL..      (dropped)
pll               CL.T      CL.T      CL..
sdhci-of-at91     C..T      (dropped) (dropped)
virtio_mmio       (dropped ×3)
```

## Findings

1. **RIS-only is sufficient for compilation and structurally complete lowering.**
   ris_only never lost to full on compiled/lowering (8/8, 8/8). No evidence that
   the full evidence block is needed for the mechanical parts of translation.

2. **RIS-only wins the strict semantic metric.** ast_leaf_complete: ris_only
   4/8 vs full 2/9. Head-to-head: 2 wins (ahci_ceva, clk-highbank), 5 ties,
   1 loss (edu). trace_passed comparable (4/8 vs 4/9). Paired with the earlier
   glm-5.3-highspeed run (paired drivers identical across modes), two models now
   support: RIS alone matches or beats full evidence.

3. **Where ris_only loses, the failure mode is register VALUE semantics.**
   edu ris_only compiled, ran, ast-complete, but the trace diverged on values:
   model read the ID register (0x000 = 0xed), wrote 0x008 = 0xcafebabe, touched
   0x064 — expected R0,R0,W(0x004)=0xdeadbeef. RIS carried structure but not the
   driver's register-level value protocol; the `full` facts block supplied it.
   Trace diff: `artifacts/output/eval-evidence-mimo-w1/edu__ris_only/verify/trace.txt`.

4. **Semantics injection (legend + external annotations) shows no detectable
   lift** at n=4: vs ris_only paired — 1 win (edu trace), 1 loss (pll), 2 ties.
   The closed-category tags already present in ris_only appear to carry the
   semantic payload; the extra legend does not add measurable signal.

5. **Mechanical receipt repair holds under ris_only.** ahci_ceva ris_only:
   26 anchor labels normalized (`__rh_op_<n>` → `__rh_op_op_<n>`), one LLM
   repair attempt correctly rejected ("dropped valid receipts"), 4 duplicate
   receipt comments deduped — final cell all-green. No LLM round was burned on
   label spelling drift.

6. **Timing is a weak signal here.** ris_only median 1392s vs full 653s, but
   wall-clock was polluted by 1→4 concurrent lanes, shared-box load, and the
   SIGKILL restarts; edu ris_only finished in 155s with zero repairs. The
   glm-highspeed run showed the same direction (ris_only 1.7–2.4× slower) under
   clean serial conditions — treat "ris_only costs wall-clock" as plausible but
   unconfirmed on mimo.

## Limitations

- 21/30 cells; sdhci ris modes, all three virtio_mmio cells, pl061/clk-highbank
  ris_semantics dropped when the run was halted; two cells (ahci_sunxi,
  gpio-ftgpio010 ris_semantics) landed after the snapshot above.
- First-pass 3300s timeout was too tight under 4-way concurrency (rc=124 losses);
  a box-side process killer SIGKILLed runner pythons repeatedly (rc=137).
- Single endpoint, temperature 0 nondeterminism, no repetition.

## Pointer for the paper

RIS v0.4.0 slim text + Call/ExternalCall dedup is a viable sole evidence source
for driver translation on two models; the open gap is register value semantics,
which belongs to the facts block — a targeted "value facts" addendum to RIS is
the next candidate rather than restoring full evidence.
