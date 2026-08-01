# C18: DWC2 lowering plan and canonical recipe provenance

## Why DWC2 still failed strict generation checks

A fresh C17 run generated and compiled all three DWC2 backends, but harness and
bare-metal reported 426 missing lowering receipts/AST anchors.  Linux reported
1508.  Treating those numbers as one generic omission would mix three different
causes: unsupported loop control, backend root/lifecycle reachability, and an
actual primitive-ownership drift.

The DWC2 contract contains 3608 register operations.  Independent structural
classification proves this exact harness/bare-metal partition:

| Disposition | Operations |
|---|---:|
| lowered | 3182 |
| blocked by unsupported loop | 426 |
| total/accounted | 3608 |

All 426 blocked IDs exactly match the previous H/B missing set.  They occur
under 34 Conservative/unproved `for`, `while`, or `do` loops.  Only two belong
to the C15 rescued frontier; callee rescue is not their general cause.

## Independent backend lowering plan

`qa/verification/backend_lowering_plan.py` walks canonical Formal RIS without
importing a generator or reading generated receipts.  For harness and
bare-metal it records exactly one entry per register op with:

- module, op ID and kind;
- `lowered` or `blocked_unsupported_loop` disposition;
- all enclosing loop contexts and the decisive blocking loop;
- a stable, explicit reason.

The verifier checks the plan against both Formal and the frozen generation
contract.  Duplicate, missing or unknown IDs, module/kind drift, malformed
blocked entries, or a candidate relabeling `blocked` as `lowered` fail closed.
An accounted blocker gives `accounting_complete=true` but keeps
`lowering_complete=false`.  Blocked entries do not authorize a receipt or AST
anchor, so the mechanism cannot improve readiness by pretending an unproved
loop executes once.

The deterministic driver pipeline writes:

```text
verify/harness-lowering-plan.json
verify/baremetal-lowering-plan.json
```

Readiness diagnostics use the plan to distinguish planned control blockers
from unexplained missing operations.  Strict readiness is unchanged.

## Canonical primitive ownership survives backend rewrites

C17 also exposed DWC2 `op_905`: the frozen contract expected an intrinsic RMW
(`Read + Write`), while generated C contained only a Write.  Probe
success-path selection had flattened sibling forward-goto regions and then
recomputed `lowering_recipes()`.  A same-name, same-address read from another
region was incorrectly selected as the producer.

Backends now derive recipes from the original canonical module before any
success-path or control-structure rewrite.  The frozen recipe is explicitly
carried through normalization and final `ops_to_c()` emission for harness,
bare-metal, and Linux.

## MMIO read-return provenance

The upstream dataflow cause was a loose name-based heuristic.  If an inlined
callee return expression contained any call whose name matched `*read*`, the
last MMIO Read in that callee could be rebound to the caller assignment.  In
DWC2, `device_property_read_bool()` caused the `dwc2_force_mode()` register read
variable to become an unrelated outer `retval`.

`FuncExtraction` now records a `return_read_var` only when the complete return
expression is a read primitive accepted by the MMIO classifier.  Caller-side
rebinding additionally checks the instantiated operation's read provenance and
classified callee.  That provenance is closed through proven wrapper-summary
returns and `local = read_wrapper(); return local` without using function-name
patterns.  The multi-TU call-graph fingerprint includes `return_read_var`, so a
provenance-only fixed-point improvement cannot be mistaken for convergence.
Ordinary property/configuration helpers no longer capture an unrelated MMIO
read, while true nested `value = mmio_read_helper()` chains remain supported.

After both fixes, fresh DWC2 evidence is:

```text
op_904: Read GUSBCFG -> gusbcfg
op_905: write_from_read, read_op_id=op_904, one Write primitive
H/B AST primitive mismatches: 1 -> 0
H/B loop-blocked operations: 426 (unchanged, now explicitly classified)
three generated backends: compile successfully
```

## Remaining boundary

C18 does not prove the 34 loops, DWC2 callsite multiplicity, endpoint/HCD
lifecycle, 286 unsafe dynamic addresses, or Linux's 1082 additional
backend-root/lifecycle omissions.  The next durable steps remain Formal `Call`
plus a callsite verifier, loop/Poll semantics, Linux root/lifecycle planning,
and address/value/guard/order verification.
