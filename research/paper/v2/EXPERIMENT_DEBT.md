# Deferred Experiment Debt

This revision deliberately does not invent new measurements. The following
claims remain outside the evidence currently reported in `v2` and require new
system runs before they can be strengthened.

| Claim needing evidence | Required experiment | Current status |
| --- | --- | --- |
| RIS extraction is complete/accurate | Stratified manual labels or source-vs-target differential traces for operation kind, address, width, value, order, guard, callback, and state flow | Not run |
| The gate blocks unsafe extra accesses | Mutation tests adding DMA/IRQ/MMIO operations, duplicate accesses, wrong base, and wrong write values; static and QEMU gates must reject them | Not run |
| Guard/control-flow preservation | Branch-directed inputs covering both paths and guard mutations, with path predicates checked against runtime observations | Not run |
| LLM synthesis 成功率/可复现性 | Fixed model/version/prompt/temperature/seed, repeated trials on held-out eligible drivers, first-pass and repair pass rates, cost and latency | Partially run: repeated-trial studies (DW + gpio-cadence) and a 21/30-cell evidence-mode matrix are reported in RQ6; repeated sampling and multi-model coverage still pending |
| Benefit over alternatives | Direct raw-source LLM, C2Rust/translation baseline, deterministic emitter, and ablations for IR, functional state, receipts, and repair | Not run |
| Rust backend equivalence | Fixed target/toolchain/dependency versions, Rust AST/HIR receipt checks, no-std linking, and emulator or hardware execution | Not run |
| Typed transaction correctness | Real regmap, I2C/SMBus, and MFD drivers with selector, width, error, cache/update, and ordering checks | Not run |
| Multi-source semantic scalability | Precision/recall and runtime/memory curves over larger modules, plus at least one multi-source runtime differential validation | Not run |
| Reproducible corpus accounting | Publish the complete driver/module list, source revisions, Linux 内核 / Clang / LLVM / QEMU / GCC / Rust versions, target triples, and per-driver failure records | Not run |
| Inter-procedural cutoff coverage | Measure calls at and beyond the depth-3 limit and verify every truncated path becomes a readiness blocker | Not run |

The current paper therefore reports artifact compilation, internal readiness
heuristics, two deterministic QEMU slices, and one non-repeated LLM case study;
it does not report any of the stronger claims in the first column as measured
results.
