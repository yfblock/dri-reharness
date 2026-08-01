# C20: Linux generated-AST and registration attestation

## Problem

C19 deliberately stopped at definition authorization.  A lowering receipt can
prove that an operation was emitted into a generated function, but it cannot
prove that the function is the target of a callback field, that the callback
object is the object passed to a framework registration API, or that the
registration is rooted at module initialization.  Treating those distinct
claims as one `lowered` bit made an unregistered `__maybe_unused` definition
look stronger than the available evidence.

C20 adds two independent generated-C AST authorities and reconciles them in
`backend-lowering-plan-v3`:

1. `generated-c-ast-leaf-v1` proves the required candidate operation anchors
   and their leaf MMIO primitive shapes;
2. `linux-registration-ast-v1` proves a supported callback-registration route
   from the same generated translation unit;
3. plan v3 intersects both proven operation-ID sets with the canonical strict
   candidate set.  Neither report can independently authorize an operation.

Linux strict completion therefore requires lowering/definition alignment,
required-subset AST completion, registration completion, and a successful v3
reconciliation.  Missing evidence remains fail-closed.

## Design identity chain

The v1 proof is an identity chain, not a name-matching heuristic:

```text
generation contract op_id
  -> unique __rh_op_<op_id> AST label and direct compound
  -> enclosing generated function USR
  -> DeviceSpec ris_ref/function and callback owner
  -> type-correct callback field binding to the same function USR
  -> exact framework-object AST path and field USRs
  -> straight-line assignment/attachment before registration
  -> recognized registration call with the exact object and argument type
  -> registered platform_driver/pci_driver probe root
  -> module_init-expanded __inittest reference
```

Every registration route has a stable fingerprint over callback identity,
target USR, field/owner identity and registration chain.  The registration
report and required-subset AST report also carry the generated-C SHA-256 and
exact Kbuild context digest.  Plan v3 independently reads the actual generated
C and `.o.cmd`, then requires both reports to match that third-party
artifact/context authority.  It rejects jointly forged SHA or context claims
as well as mismatched drivers, schemas, oracles, operation sets, route
fingerprints and counts.  It independently rebuilds the canonical plan, so
mutating a candidate plan's runtime fields cannot manufacture authority.
When the canonical plan has no blocker and could actually become strict, v3
also reruns both AST oracles from the artifact and requires exact report
equality.  Thus a jointly forged route with a recomputed fingerprint still
fails independent reverification.  Canonically blocked drivers such as DWC2
remain non-strict without paying that duplicate parse cost.

The exact saved Kbuild `.cmd` file supplies the libclang parse context.  A
missing or malformed command is not replaced by guessed include flags.

## Supported v1 shapes

The first version intentionally supports a narrow, structurally checkable
subset:

- `platform_driver` and `pci_driver` roots registered from module init;
- root-table callbacks, especially `probe`, bound by typed designated
  initializer;
- straight-line `gpio_chip` registration inside an already registered probe;
- typed dynamic `gpio_chip` and nested `gpio_irq_chip` callback assignments
  before registration of the exact owner object;
- `irq_chip` attachment through `gpio_irq_chip_set_chip()` with exact parent
  and child object identity and ordering;
- direct IRQ handler arguments to the recognized request-IRQ APIs inside a
  registered probe;
- both global initializer and local assignment bindings when the target
  function, signature, object path and registration chain are unambiguous.

Registration calls that are shadowed by a generated source-local function,
occur under unsupported control flow, have the wrong canonical argument type,
or use a different object are rejected.

## Explicitly unsupported boundary

V1 does not infer through banked/aliasing object dataflow, arbitrary container
or array fanout, clock match-data fanout, SDHCI platform-data attachment,
misc/file-operations registration, or USB endpoint/gadget/HCD lifecycle.
Callback-table families such as `clk_ops`, `dev_pm_ops`, `file_operations`,
`sdhci_ops`, `usb_ep_ops`, `usb_gadget_ops` and `hc_driver` may be recognized
as AST types for diagnostics, but they are not registration-authorized by v1.

Most importantly, this stage does **not** prove that the kernel invokes a
registered callback, that guards and paths inside it have the intended
semantics, or that callback arguments, temporal ordering and device lifecycle
match the original driver.  Definition shape and registration identity are
necessary assurance layers, not full runtime equivalence.

## Positive and boundary results

FTGPIO is the supported positive control.  Its Linux required subset has
35 strict candidates; all 35 have valid generated-C leaf AST evidence and all
35 have an exact supported registration route.  The effective Linux plan is
therefore 35/35 strict for this case.

DWC2 is the large negative boundary:

| Axis | Result |
|---|---:|
| Contract register operations | 3608 |
| Harness/bare-metal lowered | 3182 |
| Harness/bare-metal blocked by unsupported loops | 426 |
| Linux definition-authorized | 2100 |
| Linux blocked | 1508 |
| Linux strict definition candidates | 2023 |
| Required-subset AST proven | 2023/2023 |
| Registration proven | 62/2023 |
| Linux strict | false |

The 2100 Linux-authorized operations are the 2023 strict definition candidates
plus 77 evidence-only operations.  The 1508 blocked operations retain the C19
partition: 426 loop, 184 lifecycle and 898 missing-root operations.  Perfect
2023/2023 leaf AST coverage does not override the 62/2023 registration result;
the effective plan remains fail-closed.  In particular, C20 does not claim to
solve DWC2 USB endpoint, gadget, HCD or dual-role lifecycle.

## Fail-closed mutations

The regression suite covers these mutation classes:

- missing or wrong-schema/oracle/driver AST and registration reports;
- different—or jointly forged—generated-C SHA/Kbuild context, required subset,
  operation set or count claims;
- missing, duplicate, malformed or wrong-function operation anchors;
- missing/shadowed module root registration or a root not referenced by
  module init;
- wrong callback owner, target, signature, object identity or registration
  argument type;
- callback assignment after registration, controlled registration, or wrong
  GPIO/IRQ attachment object;
- empty, changed or inconsistent route IDs and route fingerprints;
- registration claims for blocked or evidence-only operations;
- candidate-plan runtime fields, dispositions, authorization sets or receipt
  reconciliation mutated away from independently rebuilt evidence.

Each mutation keeps Linux strict completion false and reports the failed
authority layer rather than silently falling back to definition receipts.

## Reproduction

Run the complete repository test entry point (173 tests: 132 core, 8
generated-C AST, 5 Linux registration AST, 20 lowering-plan, 1 C20 readiness,
2 read-provenance and 5 DeviceSpec JSON):

```bash
./run.sh test
```

The focused C20 runners are:

```bash
python3 qa/tests/test_linux_registration_ast_oracle.py
python3 qa/tests/test_backend_lowering_plan.py
python3 qa/tests/test_metrics_c20_readiness.py
```

The effective v3 plan can be independently reconstructed with the generated
artifact and Kbuild context as authorities:

```bash
python3 qa/verification/backend_lowering_plan.py \
  --formal <output>/<driver>.formal.json \
  --contract <output>/generation-contract.json \
  --backend linux \
  --device-spec-json <output>/<driver>.device-spec.json \
  --lowering-report <output>/verify/linux-lowering.json \
  --runtime-attestation <output>/verify/linux-registration-ast.json \
  --ast-leaf-report <output>/verify/linux-ast-leaf.json \
  --generated-artifact <output>/verify/tmp/linux-module/<module>.c \
  --kbuild-cmd <output>/verify/tmp/linux-module/.<module>.o.cmd \
  --output <output>/verify/linux-lowering-plan.json
```

The normal driver pipeline writes the three Linux assurance artifacts under
`<output>/verify/`:

```text
linux-ast-leaf.json
linux-registration-ast.json
linux-lowering-plan.json
```

The registration oracle can also be reproduced directly with the exact saved
Kbuild command:

```bash
python3 qa/verification/linux_registration_ast_oracle.py \
  --contract <output>/generation-contract.json \
  --device-spec-json <output>/<driver>.device-spec.json \
  --lowering-plan <output>/verify/linux-lowering-plan.json \
  --generated <output>/verify/tmp/linux-module/<module>.c \
  --kbuild-cmd <output>/verify/tmp/linux-module/.<module>.o.cmd \
  --output <output>/verify/linux-registration-ast.json
```

For an end-to-end regenerated result, use `./run.sh driver <source> <output>`;
the pipeline compiles the Linux module first, obtains its real `.cmd` context,
runs both AST authorities, and then rebuilds the effective v3 plan.
