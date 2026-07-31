# C26: I2C/SMBus transaction runner

The transaction IR now lowers the public I2C/SMBus APIs without treating an
I2C command as an MMIO address. Scalar byte/byte-data/word-data operations,
block operations, and raw master send/receive use transport-specific helpers
with the same receipt and anchor contract as regmap.

Harness and bare-metal provide a deterministic 256-byte device model and emit
`[txn N] id=<op_id> ... transport=i2c_smbus` (or `i2c`) traces. Linux wrappers
delegate to the real `i2c_smbus_*` and `i2c_master_*` APIs and use the same
trace shape through `pr_debug`.

`gpio-tpic2810` is the first zero-RIS holdout covered by the runner: both
`i2c_smbus_write_byte_data` sites now have typed lowering receipts, independent
AST proof, runtime traces, and mutation checks for helper substitution, order,
and count.

Unsupported transports remain rejected by the backend accounting oracle.
Public MFD helpers are covered separately by the C27 runner and declaration
provenance gate.
