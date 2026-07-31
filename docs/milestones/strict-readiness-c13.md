# C13: source-backed strict readiness

## 1. Goal

C12 executed synthesized GPIO callbacks but still interpreted the summarized
RIS as its own reference.  C13 adds source-independent contracts and targets
two previously blocked holdout drivers without driver-name or basename rules:

- model the sequential `gpio-mmio` shadow state (`sdata` and `sdir`);
- admit public SDHCI accessors only when source structure excludes private
  read/write overrides;
- prove the Altera interrupt loop as a masked W1C drain under an explicit
  quiescence assumption;
- preserve MMIO reads embedded directly in callback return expressions.

## 2. GPIO source differential

Formal RIS now has `StateRead`, `StateWrite`, `OutputWrite`, and `Return`.
The GPIO lowering snapshots and updates `sdata/sdir`, preserves set/clear and
direction ordering, handles `set_multiple`, `dirin` inversion, return values,
and output parameters.  `verification/gpio_mmio_source_oracle.py` implements
the corresponding `gpio-mmio.c` behavior independently of generated code.

Six source configurations pass: TS4800, GE, FTGPIO, Cadence, IDT3243x, and
Sodaville.  Six mutations are rejected: stale shadow state, incorrect
`set_multiple` value, reversed direction/data order, missing `dirin`
inversion, incorrect byte order, and swapped SET/CLR registers.  The original
TS4800 and GE strict-ready results survive this stronger gate.

The claim is sequential callback equivalence for the exercised public GPIO
contract.  It does not prove spinlock behavior, concurrent callbacks,
pinctrl delegation, or every Linux GPIO lifecycle transition.

## 3. SDHCI public-accessor boundary

The compile-context importer now retains `--target=<triple>`, removing the
false NPCM parser error caused by using the host target with ARM headers.
NPCM is accepted only when all recovered RIS leaves are direct public
`sdhci_accessor` operations, the source binds through `sdhci_pltfm_init`, its
`sdhci_pltfm_data` objects omit `.ops`, and the pinned platform ops omit
private read/write overrides.

The source oracle admits NPCM and rejects mutations to its accessor contract.
Dove and HLWD remain rejected because their private accessors or external core
callbacks cross this boundary.  This is not a proof of the complete SDHCI host
lifecycle.

## 4. Masked W1C drain

Altera contains an interrupt loop whose guard reads `EDGE_CAP` and `IRQ_MASK`,
computes their intersection, and writes that exact status back to the pending
register.  The extractor recognizes only this structured pattern and records:

- `proof_kind = masked_w1c_drain`;
- two explicit guard reads and `pending & mask` guard value;
- W1C write semantics on the same pending address;
- `max_iterations = 1` under the assumption that no new pending bits arrive
  while the generated handler drains the snapshot.

Harness fake MMIO implements W1C clearing and executes a second guard read.
Bare-metal deployment keeps an ordinary volatile write, while its host-oracle
mode uses the same fake-MMIO semantics.  Contract and runtime oracles check the
two reads, acknowledge value/address, clear, and terminating reread.  A
mutation that redirects the acknowledge to the mask register is rejected.
Arbitrary `while` loops are not classified as bounded.

## 5. Direct return lowering

An MMIO read inside `return !!(readl(DATA) & BIT(offset));` previously emitted
only an unbound `Read`, so generated Altera callbacks returned the raw register
through backend fallback logic.  The dataflow layer now binds such reads to a
stable temporary and emits an explicit `Return` expression.  Inlined callee
returns are consumed as call values rather than becoming premature caller
returns.  All three generated backends now return normalized zero or one.

## 6. Results and boundary

| Metric | C12 | C13 |
|---|---:|---:|
| tests | 101 | 107 |
| zero-shot harness strict-ready | 5/12 | 7/12 |
| zero-shot bare-metal strict-ready | 5/12 | 7/12 |
| zero-shot Linux strict-ready | 5/12 | 7/12 |
| exact compile contexts | 12/12 | 12/12 |
| all three backends compile | 12/12 | 12/12 |

The two new strict-ready cases are `gpio-altera` and `sdhci-npcm`.  This gain
does not imply whole-driver equivalence: Altera's non-MMIO IRQ dispatch side
effects remain outside the register-interaction claim, and NPCM remains inside
the no-private-accessor boundary.  The remaining five cases retain explicit
subsystem, address, loop, or external-callback blockers.
