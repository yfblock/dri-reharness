# C25: regmap transaction lowering contract

The regmap slice now has one backend-independent lowering ABI:

```c
reharness_regmap_read(target, selector, &value)
reharness_regmap_write(target, selector, value)
reharness_regmap_update(target, selector, mask, value)
reharness_regmap_bulk_read(target, selector, buffer, count)
reharness_regmap_bulk_write(target, selector, buffer, count)
```

Formal `TransactionRead`, `TransactionWrite`, and `TransactionUpdate` leaves
carry a stable semantic digest and are emitted exactly once under
`__rh_txn_<op_id>` anchors. Harness and bare-metal use the deterministic
regmap state model; Linux delegates to the real `regmap_*` APIs. All three
backends emit the same transaction receipt fields (`id`, `kind`, `transport`,
`status`, `digest`).

`qa/verification/regmap_transaction_ast_oracle.py` independently checks helper
shape, anchor cardinality, and transaction order. Harness/bare-metal traces
use `[txn N]` records; Linux wrappers use the equivalent `pr_debug` record.
The mutation suite covers helper substitution and trace-order/count changes.

The contract remains fail-closed for transports without a runner. I2C/SMBus is
covered by C26 and public MFD helpers by C27; unrelated transports still
retain rejected receipts.
