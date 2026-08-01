# MFD transaction lowering (C27)

The transaction IR now covers public MFD register helpers in addition to
regmap and I2C/SMBus transports.  Extraction remains fail-closed: a helper is
accepted only when clang resolves its declaration under `include/linux/mfd/`
and the suffix/signature matches the generic register-helper contract.

The contract preserves the transport handle and selector separately.  For
masked helpers, `set_bits` and `clear_bits` become `TransactionUpdate` nodes
with an explicit `helper_contract` and the resolved public `helper_symbol`.
The source evidence retains the declaration path, so a source-private helper
with the same name cannot satisfy the contract.

All three backends now expose the same lowering boundary:

- harness and bare-metal use the deterministic `reharness_mfd_*` state model;
- Linux emits a validated public MFD header include, a private `mfd` handle,
  and the resolved helper call;
- private transaction leaves that are not registered Linux callbacks are
  emitted as `__rh_transaction_<function>` audit runners, keeping their
  anchors visible without claiming lifecycle registration.

The independent transaction AST oracle is backend-aware for MFD wrappers and
public helpers.  The runtime trace uses `transport=mfd`, and the mutation
suite rejects helper substitution, trace reordering, and count changes.  The
`clk-twl6040` holdout now exercises two updates (`set_bits` followed by
`clear_bits`) across all three lowering paths.

With the repository's `platform/kernel/build` tree available, the generated Linux
module also passes an out-of-tree Kbuild compile.  This verifies that the
proven public MFD prototypes and generated `mfd` state field are accepted by
the kernel compiler, not merely by text matching.
