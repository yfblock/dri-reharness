# Output Artifact Recommendations

## Goal

Reduce generated output noise and keep only the files that are useful for
reconstructing a driver from extracted artifacts.

For driver reconstruction, the core input should be:

```text
.ris    register interaction sequence
.dspec  backend-independent device/function semantics
.bind   backend-specific mapping
.facts  selected source-derived reconstruction facts
```

Generated C files, traces, scores, and binaries should be treated as derived
artifacts, not as source inputs for reconstruction.

## Recommended Directory Layout

Use a small core output set and move derived files into subdirectories:

```text
output/<driver>/
  <driver>.ris
  <driver>.dspec
  <driver>.bind
  <driver>.facts

  generated/
    harness.c
    baremetal.c
    linux.c

  verify/
    metrics.txt
    score.txt
    harness.trace.txt
```

Do not keep compiled binaries in the main output directory. If a binary is
needed during verification, place it under `verify/tmp/` or `/tmp`.

## Merge Backend Bind Files

Current output uses one `.bind` file per backend, for example:

```text
virtio_mmio.harness.bind
virtio_mmio.baremetal.bind
virtio_mmio.linux.bind
```

These should be merged into one file:

```text
virtio_mmio.bind
```

The merged file should contain multiple backend blocks:

```text
backend harness for device virtio_mmio {
  ...
}

backend baremetal for device virtio_mmio {
  ...
}

backend linux for device virtio_mmio {
  ...
}
```

This keeps backend differences explicit without creating unnecessary files.

## Trim `.facts`

The `.facts` file should contain only facts that help reconstruct the driver.
It should not dump all constants and macros visible through Linux headers.

Keep:

- `source`
- `includes`
- local driver structs and relevant field types
- driver-local constants
- register constants
- status constants
- callback table bindings
- resource acquisition facts
- error paths and return codes
- important helper calls and subsystem registration calls

Drop or filter aggressively:

- `CONFIG_*`
- `KASAN_*`
- `TASK_*`
- `pt_regs_*`
- `CPUINFO_*`
- `BUG_*`
- `TAINT_*`
- architecture offsets
- unrelated kernel-wide constants
- generic header macros not referenced by RIS, dspec, bind, callbacks, or
  resource/error paths

For `virtio_mmio`, useful facts are mainly:

- `VIRTIO_MMIO_*` register constants
- `VIRTIO_STATUS_*` status constants
- `struct virtio_mmio_dev`
- `platform_driver.probe`
- `platform_driver.remove`
- MMIO resource acquisition
- relevant error returns

## Treat Generated C as Derived Output

Generated backend C files are useful for inspection and verification, but they
should not be required inputs for rebuilding a driver:

```text
generated/harness.c
generated/baremetal.c
generated/linux.c
```

The reconstruction pipeline should be able to regenerate these from:

```text
<driver>.ris
<driver>.dspec
<driver>.bind
<driver>.facts
```

## Treat Metrics and Scores as Verification Output

Metrics and readiness scores should be placed under `verify/`:

```text
verify/metrics.txt
verify/score.txt
verify/harness.trace.txt
```

They are useful reports, but they are recomputable and should not be treated as
canonical reconstruction inputs.

## Make Readiness Scoring Stricter

Readiness flags should reflect generated code quality, not only extraction
coverage.

For Linux:

```text
backend_linux_ready = false if:
  generated/linux.c contains TODO
  generated/linux.c has obvious undefined identifiers
  generated/linux.c has not passed a Linux compile check
```

For harness and bare-metal:

```text
backend_harness_ready = true only if:
  generated/harness.c compiles
  trace generation succeeds
  RIS trace equivalence passes

backend_bare_metal_ready = true only if:
  generated/baremetal.c compiles with strict warnings
```

This prevents readiness reports from claiming a backend is ready when the
generated file is still a partial skeleton.

## Priority

Implement in this order:

1. Merge per-backend `.bind` files into one `<driver>.bind`.
2. Move generated C and verification output into `generated/` and `verify/`.
3. Stop saving compiled `.bin` files in the main output directory.
4. Trim `.facts` to reconstruction-relevant information.
5. Tighten readiness scoring using TODO detection, undefined identifier checks,
   and compile results.

