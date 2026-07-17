# Zero-shot v2 AST callback ownership propagation

## Scope

This stage implements the first machine-selected zero-shot-v2 blocker without
attempting to improve strict-readiness numbers or assign semantics to unknown
callbacks.  The implementation does not inspect driver basenames, compatible
strings, Kconfig names, or source-private function prefixes.

The accepted evidence is limited to libclang AST information:

- the referenced function declaration and source-qualified symbol identity;
- the enclosing structure/union type of a function-pointer field;
- designated and positional structure initializers, including arrays;
- direct assignments to function-pointer structure fields;
- named callback typedefs used as call parameters;
- calls that pass both a structure object and a raw function-pointer argument,
  when the callback parameter name and a function-pointer field in that
  structure type match.

Local function-pointer variables without an owner field remain unbound.

## Binding and semantic role are separate

Every proven binding records:

```text
function
owner/table type
field
binding kind
source file, line, and column
public callback ABI type or private owner
```

This evidence is stored in
`formal.metadata.callback_binding_analysis` and the machine-readable analysis
statistics.  A function may therefore have:

```text
callback owner.field
role unknown
```

That state removes a false `callback entry without table binding` blocker but
retains `missing role`.

Only callback owners in the versioned public kernel callback-type inventory
may enter `BindSpec` or generated callback tables.  A private structure field
can retain a generic role hint for analysis, but the owner type prevents it
from becoming executable backend intent.  Multi-source private callbacks with
RIS operations are emitted as unregistered evidence-only functions so that
cross-TU operation evidence is not lost.

## Covered forms

The frozen v2 cluster exercises four distinct forms:

- `clk_ops` designated initializer;
- `sdhci_ops` designated initializer;
- runtime assignment into `mmc_host_ops` fields;
- runtime assignment into a source-private virtio-pci object field.

Additional regression coverage includes:

- GPIO IRQ dynamic field assignment;
- PM callbacks sharing suspend/freeze/poweroff and resume/thaw/restore fields;
- macro-expanded platform probe registration represented in the AST as a
  structure argument plus raw callback parameter;
- positional arrays of queue callback structures;
- named IRQ callback typedefs;
- local ordinary function-pointer negative controls.

## Result

In zero-shot-v2:

```text
callback_binding: 4/12 -> 0/12
first common blocker: callback_binding -> missing_role
```

The four selected cases still contain exactly the same `missing_role`
evidence as the frozen baseline:

- `clk-si544`
- `sdhci-milbeaut`
- `sdhci-sprd`
- `virtio-pci-legacy`

The differential oracle verifies that the following are unchanged from the
frozen baseline:

- total operations and access accounting for every driver;
- backend compilation for every driver;
- harness, bare-metal, and Linux strict readiness;
- all aggregate counts.

The post-change strict readiness remains H 1/12, B 1/12, Linux 0/12.  The two
pre-existing zero-operation cases remain unchanged, so the matrix command
still returns nonzero for `all_cases_have_hardware_interactions`.

## Regression evidence

- complete test suite: 117 passed, 0 failed;
- zero-shot-v1: 12/12 exact contexts, 12/12 all-backend strict-ready;
- zero-shot-v2: callback cluster removed, missing-role cluster preserved;
- 19-driver matrix: 476 operations; metrics, backend compilation, and strict
  readiness unchanged;
- multi-source matrix: ASPEED vhub, C67X00, and DWC2 all pass original Kbuild
  and all three generated backend compilers.

Artifacts:

- `experiments/results/zero-shot-v2-callback-binding.json`
- `experiments/results/zero-shot-v2-callback-binding-oracle.json`
- `experiments/results/zero-shot-v1-callback-binding.json`
- `experiments/results/matrix-callback-binding.json`
- `experiments/results/multisource-callback-binding.json`

The oracle includes mutations that reintroduce a callback blocker, change a
backend compile result, or remove preserved missing-role evidence.  All three
mutations are detected.

## Problems found during implementation

1. Treating every familiar field name as a semantic callback caused private
   structures named `reset`, `write`, or `irq` to enter public backend tables.
   Owner type must gate executable semantics.
2. PM macros expand one function into several fields.  Alphabetic selection
   chose `freeze`/`restore`, while existing generation supports the canonical
   `suspend`/`resume` contract.  Primary binding now prefers a field equal to
   the established semantic role while preserving alternates as evidence.
3. Facts originally overwrote the selected primary binding with an alternate
   field.  Facts are now evidence-only when a BindSpec entry already exists.
4. Some default, non-native parse contexts omit a partially invalid initializer
   from the AST.  Existing typed SDHCI subsystem summaries continue to supply
   source-private accessor generation; exact holdout contexts recover the AST
   binding directly.
5. Emitting every private unknown callback as an evidence function broke a
   single-TU AHCI compile due to intentionally unsupported expressions.  The
   evidence-only emitter is limited to multi-source internal callbacks, where
   it preserves cross-TU operations without registering a lifecycle table.
6. A custom relative multi-source workdir made Kbuild interpret `M=` relative
   to the kernel build directory.  Reproduction used an absolute workdir; this
   was an experiment invocation issue, not a translation change.

## Next blocker

The next machine-selected blocker is `missing_role` on the same four v2 cases.
It should be handled as a separate stage.  Callback ownership is now known,
but semantic roles such as clock readiness query, SDHCI clock/timing control,
MMC tuning callbacks, and private virtqueue teardown require independent
subsystem contracts and must not be inferred from driver-specific names.
