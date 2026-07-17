# C19: Linux definition plans and runtime-registration boundary

## Problem

C18 could explain harness/bare-metal operations hidden below unsupported
loops, but Linux still reported one undifferentiated missing set.  More
importantly, a Linux lowering receipt proves only that an operation appears in
some generated function definition.  It does not prove that the function is
placed in a registered callback table, connected to probe glue, or reachable
with the correct call arguments.

The multi-source audit exposed the scale of that distinction:

| Driver | Contract ops | Linux receipts | Missing |
|---|---:|---:|---:|
| C67X00 | 32 | 26 | 6 |
| ASPEED vHub | 154 | 133 | 21 |
| DWC2 | 3608 | 2100 | 1508 |

Separate read-only inspection found receipt-bearing definitions that were not
proven registered in all three modules.  Those exploratory counts are not
used as verifier evidence; C19 therefore makes no per-operation runtime-root
claim until a versioned registration/callsite oracle exists.

## Versioned DeviceSpec JSON

`device_spec_to_dict()` and `device_spec_from_dict()` provide a strict schema-1
machine representation alongside the human-readable `.dspec`.  It preserves
all state, resources, registers, function signatures, source bindings,
effects, RIS references and callback ownership.  Unknown fields/schema,
wrong nested types, non-finite/non-JSON effect detail and mutable aliases are
rejected.  Callback ownership is internally consistent
(`callback_table != null` requires `is_callback_entry=true`), and the Linux
plan also requires the DeviceSpec driver identity to match Formal RIS.

The driver pipeline and LLM bundle now include:

```text
<driver>.device-spec.json
```

The Linux plan CLI requires this versioned document rather than parsing
`.dspec` text with regular expressions.

## Definition receipt authorization

`backend-lowering-plan-v2` keeps two separate axes:

1. definition/receipt authorization;
2. runtime registration proof.

Linux operations are classified as:

- `candidate_definition_emit`;
- `definition_evidence_only`;
- `blocked_unsupported_loop`;
- `blocked_linux_lifecycle_stub`;
- `blocked_linux_lifecycle_unimplemented`;
- `blocked_linux_root_unreachable`.

Loop blockers have priority over lifecycle/root blockers, retaining all
cross-backend structural evidence.  Candidate and evidence-only definitions
may own receipts; blocked operations may not.  The plan is reconciled against
the actual lowering report, so a blocked operation with a receipt or an
authorized operation without one fails closed.

Absence of that report is also fail-closed: plan classification can still be
inspected, but `definition_alignment_complete`, `lowering_complete` and
`strict_complete` cannot become true without generated-C receipt evidence.
The report schema, required fields, completion flag, counts and operation-ID
lists are validated before authorization reconciliation.

Candidate plan schema, policy, summary, route, disposition, authorization and
runtime fields are all compared with an independently rebuilt canonical plan.
Mutating a blocker into a candidate or claiming runtime registration fails.

## Multi-source results

The definition-level authorization sets exactly match generated receipts:

| Driver | Authorized | Blocked | Definition alignment |
|---|---:|---:|:---:|
| C67X00 | 26 | 6 loop | yes |
| ASPEED vHub | 133 | 10 loop + 3 lifecycle + 8 root | yes |
| DWC2 | 2100 | 426 loop + 184 lifecycle + 898 root | yes |

DWC2's 2100 authorized operations comprise 2023 definition candidates and 77
private evidence-only operations.  They are not reported as runtime-lowered:
every authorized Linux entry retains `runtime_registration_proven=false`.

## Readiness consequence

Compilation is unchanged: the main matrix still compiles H/B/Linux at
18/19, 18/19 and 17/19, and all three multi-source modules remain 3/3.
Strict readiness becomes:

| Matrix | Harness | Bare-metal | Linux | All backends |
|---|---:|---:|---:|---:|
| 19-driver | 4/19 | 4/19 | 0/19 | 0/19 |
| zero-shot v1 | 7/12 | 7/12 | 0/12 | 0/12 |

This is an assurance correction, not a code-generation regression.  Linux
definitions continue to compile; they no longer receive a runtime-equivalence
claim without independent evidence.

Extraction-only scoring is likewise fail-closed: without generated backend
compile/lowering/attestation results, all backend strict flags remain false.
`llm_synthesis_ready` stays a separate pre-generation eligibility signal.

## Next proof obligation

The next stage should parse generated Linux AST and prove:

- callback table initializer/assignment ownership;
- table registration from probe/driver glue;
- callback target identity and signature;
- callsite arguments, guards and ordering;
- lifecycle reachability for remove/shutdown/PM;
- no unregistered `__maybe_unused` definition is counted as a runtime root.

That registration/callsite attestation can upgrade individual
`candidate_definition_emit` routes without weakening the fail-closed default.
