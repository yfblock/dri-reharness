# C24: typed regmap/I2C/MFD transaction IR

## Why this boundary exists

The previous RIS representation treated `regmap_*` calls as if a regmap
handle plus a register number were an MMIO address.  That made the operation
visible for accounting, but it erased the transport boundary and kept all
regmap accesses `Unsupported`.  I2C helper calls and public MFD register
helpers were not represented at all, which produced zero-operation holdouts.

C24 introduces three typed leaves:

- `TransactionRead`: target handle, optional register/command selector, and a
  scalar or buffer payload;
- `TransactionWrite`: the corresponding write payload;
- `TransactionUpdate`: a masked update with explicit mask, value, and
  `masked_replace` semantics.

The target and selector are independent expressions.  They are never folded
into `RegAddr`, and selector constants are recorded in a separate
`transaction_map`, not in the MMIO `register_map`.

## Generic contracts

The extractor recognizes public, type-defined APIs rather than driver names:

- scalar and bulk/raw `regmap_*` operations;
- scalar SMBus byte/word helpers plus byte/block and raw I2C transfers;
- MFD helpers whose declaration is proven by libclang to reside below
  `include/linux/mfd/` and whose suffix/signature is the narrow generic
  `_reg_read`, `_reg_write`, `_set_bits`, or `_clear_bits` contract.

Private functions with similar names remain unknown.  This is a provenance
gate, not a name allowlist for individual drivers.

Every transaction leaf receives the same source site identity, declaration
provenance, transport, payload kind, and source order used by MMIO leaves.
Accounting closes recognized transaction sites while transport-specific
backend validation remains a separate gate.

## Backend and readiness policy

Harness, bare-metal, and Linux now lower regmap (C25), I2C/SMBus (C26), and
public MFD helpers (C27) through transport-specific receipts, AST anchors, and
runtime traces. Linux MFD helpers additionally require a public header
provenance path and are emitted as unregistered audit runners when the source
function is a private leaf. Whole-program assurance still requires the
transaction-validation and callback-registration gates.

## Independent oracle

`qa/verification/transaction_ir_oracle.py` reconstructs public regmap and scalar
SMBus contracts directly from source text.  The transaction AST oracle also
checks MFD helper shape against the frozen declaration-provenance contract;
the mutation suite rejects helper substitution, transport/selector/kind
changes, order changes, and trace count drift.

## Holdout effect (focused extraction)

| Case | Before | C24 result |
| --- | --- | --- |
| `clk-si544` | regmap operations blocked/partly absent | 19 typed regmap transactions |
| `gpio-lp87565` | regmap GPIO operations blocked | 8 typed regmap transactions |
| `gpio-tpic2810` | zero RIS | I2C/SMBus writes with B1 payloads |
| `clk-twl6040` | zero RIS from source-private MFD helpers | 2 public MFD masked updates |

These results improve source accounting and semantic coverage, not strict
backend readiness.  Exact frozen zero-shot matrix regeneration is still
required before updating the published aggregate numbers.

## Verification performed

- zero-shot-v1 and zero-shot-v2 generalization guards pass;
- typed regmap, I2C, MFD positive cases and private-name negative case pass;
- source transaction mutation oracle passes 4/4 mutation checks;
- generated-C AST suite remains 8/8;
- the non-heavy core extraction subset passes 135/135, including all existing
  MMIO, callback, lowering, readiness, and provenance tests exercised in this
  bounded run.
