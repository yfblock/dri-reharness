# C17: generated-C AST operation anchors

## Problem

The C14/C16 receipt gate proves that every Formal register operation has one
matching `op_id/kind/digest` comment.  A comment is not executable semantics:
it can remain after the MMIO statement is deleted, be moved beside another
statement, or coexist with extra unclaimed hardware accesses.

C17 adds a structural bridge from each contract operation to generated C.  Its
first scope is the self-contained harness and bare-metal backends; Linux has
several source-preserved and specialized emitters that still require migration.

## Unique AST anchor

Every common Read, Write and RMW lowering now has this shape:

```c
/* REHARNESS_RIS_OP id=op_7 kind=Write status=lowered digest=... */
__rh_op_op_7: {
    harness_write32(value, address);
}
```

The label is the machine identity.  libclang must observe exactly one
`LabelStmt`, and its direct child must be a `CompoundStmt`.  Invalid or duplicate
operation IDs fail generation.  Unsupported operations receive a rejected
receipt and an empty semantic compound, so they cannot masquerade as lowered.

## Physical primitive ownership

The first AST implementation exposed a pre-existing RMW bug.  Most dataflow
RMW leaves correspond to a source write whose transform depends on a separate,
preceding source Read.  The old generator lowered both the Read op and another
read inside the RMW, duplicating hardware access.

The generation contract now distinguishes:

- `read`: owns one Read primitive;
- `write`: owns one Write primitive;
- `write_from_read`: owns one Write and records `read_op_id`;
- `intrinsic_rmw`: owns one Read followed by one Write.

FTGPIO `op_2 Read -> op_3 write_from_read` now generates exactly one physical
read and one physical write, matching the source.  Backend normalization carries
the recipe only on its deep copy, just like the canonical digest.

Structured trace matching uses the same ownership recipe, preventing a test
oracle from requiring the duplicated read.

## AST leaf oracle

`verification/generated_c_ast_oracle.py` parses generated C with libclang and
checks:

- missing, duplicate, unknown or malformed anchors;
- primitive cardinality and Read/Write direction;
- width, byte order and W1C selection;
- `write_from_read` versus intrinsic RMW ownership;
- parse errors and unsupported expected operations;
- known MMIO primitives outside any operation anchor.

The CLI returns `0` for complete, `2` for semantic mismatch and `3` for
verifier/input failure.  Reports bind the generated source SHA-256 and state
their limited claim scope.

A mutation keeps a valid FTGPIO receipt and anchor but replaces the actual
write with `(void)0`.  The receipt oracle still passes, while the AST oracle
rejects `op_3`.  This is the exact false positive C17 is intended to remove.

## Results

The 19-driver matrix still compiles 18/19 harness, 18/19 bare-metal and 17/19
Linux.  Strict readiness becomes:

| Backend | C16 | C17 |
|---|---:|---:|
| Harness | 5/19 | 4/19 |
| Bare-metal | 5/19 | 4/19 |
| Linux | 3/19 | 3/19 |
| All backends | 3/19 | 3/19 |

`gpio-cadence` is the deliberate downgrade: two Formal Write anchors each
contain an additional `ioread32`, an unmodeled hardware read.  FTGPIO,
gpio-idt3243x, gpio-pl061 and EDU retain harness/bare-metal strict readiness.

## Remaining boundary

The v1 AST oracle does not yet prove address expressions, write values/RMW
transforms, guards, global ordering or call semantics.  Linux is not gated yet:
four manual receipt emitters stack or trail receipts, source-preserved paths
contain unanchored primitives, and synthesized GPIO/IRQ glue introduces extra
MMIO not represented in Formal RIS.

The next implementation order is:

1. migrate Linux EDU, DW APB and Sodaville emitters to one anchor per primitive;
2. reject or formally model every unanchored Linux hardware access;
3. add address/value/RMW equivalence and guard/order checking;
4. introduce Formal RIS `Call` and verify generated callsites, arguments,
   fanout and recursion SCCs.
