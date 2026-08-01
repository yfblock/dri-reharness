# Manifest Policy Migration Design

## Goal

Move PCI identity, DMA safety behavior, and QEMU experiment details out of
generic code and legacy shell entry points into validated experiment manifests.
The migration removes the old EDU/platform compatibility scripts entirely.

## Scope

The migration covers the two existing manifest-backed experiments and all
generic paths that currently select behavior from driver names, EDU constants,
or fixed QEMU suites. Linux callback semantic tables remain because they
describe stable kernel APIs rather than a particular device.

## Design

### Manifest policy sections

Each manifest gets three explicit policy sections:

* `runtime.pci_identity` declares vendor/device/subsystem identity when the
  runtime uses PCI. The generator and adapters consume these values as facts;
  no driver-name lookup is permitted.
* `runtime.safety_policy` declares forbidden operations/tokens, sanitizer
  action (`reject` or `rewrite`), and the failure class to report. The source
  sanitizer is generic and only evaluates this policy.
* `runtime.qemu` declares machine, device model, bus, module, probe pattern,
  test executable/arguments, success marker, and timeout. The QEMU runner and
  deterministic verification script iterate manifests rather than embedding
  EDU or GPIO branches.

The manifest loader rejects unknown fields, invalid regular expressions,
relative paths that escape the repository, and policies that omit required
fields for their selected bus.

### Generator and sanitizer

PCI metadata is read from the loaded `DeviceSpec`/manifest facts. The Linux
generator has no `device_spec.name == ...` branch and never owns a PCI ID
constant. The sanitizer accepts a policy object and scans configured tokens;
it does not know `IO_DMA_CMD`, `DMA_IRQ`, EDU, or any other device-specific
symbol.

### Runtime orchestration

`qemu_run.sh` accepts one manifest-derived configuration object and performs
the same generic lifecycle for PCI and platform devices. The deterministic
QEMU suite discovers manifests, builds each declared source and test, invokes
the generic runner, and records results keyed by manifest name. Missing or
invalid policy is a hard failure.

The legacy `qemu_edu.sh`, `qemu_platform.sh`, `run_edu_e2e.sh`, and
`run_gpio_e2e.sh` files are deleted. `run.sh` exposes only the manifest entry
point and no demo/device-specific aliases.

### Failure behavior

Policy validation and infrastructure failures stop before compilation. A
sanitizer rejection is reported as a structured safety failure. QEMU timeout,
probe failure, test failure, and trace mismatch retain the manifest name,
policy digest, serial log, and first divergent event for Pi repair.

## Testing

Tests cover manifest round-trips and invalid policy rejection, PCI identity
propagation, generic sanitizer behavior, absence of legacy scripts and device
constants in generic paths, manifest iteration in the QEMU suite, and the
existing static/QEMU regression suites.

## Acceptance criteria

1. Adding an experiment requires only a manifest and declared source/test
   assets; no Python or shell orchestration changes are needed.
2. No generic runner, sanitizer, generator, or Pi bridge contains EDU/FTGPIO
   names, private register constants, or fixed PCI IDs.
3. Legacy compatibility scripts and demo aliases are absent.
4. Existing EDU and FTGPIO experiments pass from their manifests, and focused
   plus full regression tests report no new failures.
