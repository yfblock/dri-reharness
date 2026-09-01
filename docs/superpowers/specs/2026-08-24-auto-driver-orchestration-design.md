# Automatic Driver Orchestration Design

## Goal

Given one driver path, automatically normalize its source description, generate
a Linux driver with the configured `gpt-5.6-luna` provider, and validate the
result through static contracts, Kbuild, QEMU, subsystem APIs, and trace
comparison. The system must fail closed when it cannot prove runtime support.

## Scope

The entry point accepts either:

- a single C source path; or
- an existing multi-source driver descriptor JSON (`sources`), or an existing
  experiment manifest JSON (`schema: 2`).

Single-source input gets a generated, persisted manifest. Existing manifests
remain authoritative and are copied into the run artifact only after source
digest validation.

The first built-in runtime profiles are `edu-pci` and `ftgpio010-gpio`, because
the repository already has QEMU devices, registration setup, exercisers, and
trace oracles for them. Unknown drivers still receive extraction, generation,
compile, contract, and safety checks, but their result is `inconclusive` unless
the caller supplies a runtime profile or manifest. An unknown device is never
represented as a successful QEMU run.

## Data Flow

```text
driver path
  -> input normalizer
  -> source inventory and digest
  -> profile resolver
  -> generated manifest
  -> LangGraph analysis/generation
  -> contract + Kbuild
  -> baseline/candidate runtime
  -> subsystem tests
  -> trace comparison
  -> accepted | failed | inconclusive artifact
```

The generated manifest is the audit boundary. It records the source digest,
selected profile, runtime adapter, test commands, trace policy, and explicit
missing capabilities. The runner consumes only the validated manifest.

## Runtime Profiles

A profile is data plus a deterministic matcher. It defines:

- a profile id and match reason;
- QEMU machine/device/bus and optional registrar;
- module name and PCI identity when required;
- one or more subsystem test executables and success patterns;
- trace settings and exercised calls;
- whether the profile can prove a complete runtime result.

Profiles are selected by source basename and source-content signatures. A
caller may override selection with `--profile`. Profile selection is recorded
in the manifest; ambiguous matches fail instead of choosing arbitrarily.

## Result Contract

The CLI emits JSON with:

- `status`: `accepted`, `failed`, or `inconclusive`;
- `manifest`: generated or supplied manifest path;
- `profile`: selected profile and evidence;
- `stages`: persisted stage summaries and artifact paths;
- `failure` or `missing_capabilities` when the result is not accepted.

Exit codes are stable:

- `0`: accepted;
- `1`: generated/compiled/runtime candidate failed;
- `2`: invalid input or infrastructure failure;
- `3`: inconclusive because no runtime profile/test evidence exists.

## Safety and Completeness

Static contract, Linux registration AST, source digest, Kbuild, module load,
subsystem test success, and trace equality are independent gates. Passing a
subset produces a partial stage record, never `accepted`. A baseline run may
prove the test harness and QEMU model, but acceptance additionally requires the
generated candidate to pass the same gates.

