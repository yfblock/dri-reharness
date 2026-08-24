# Universal Driver Translation and Verification Design

## Goal

Build an automatic Linux driver translation framework that accepts single-file
and multi-file drivers across bus types, generates a candidate through the
configured LLM, and validates it through the strongest available evidence.
The framework must not encode a particular driver or subsystem in its core
translation loop.

The first runtime-supported bus families are platform, PCI, I2C, and SPI.
USB and virtio can be added as profiles without changing the core pipeline.

## Current Gap

The existing automatic entry point resolves only `edu-pci` and
`ftgpio010-gpio`. Unknown inputs can be analyzed but cannot select a runtime
profile. The existing `ExperimentRunner` is already mostly generic, while
manifest construction, registration validation, QEMU setup, and subsystem
tests are still profile-owned data mixed with a small number of assumptions.

The new design preserves the existing closed-loop runner and LangGraph state
model, but makes profile selection and runtime capability explicit.

## Design Principles

1. Source analysis and candidate generation are bus-neutral.
2. Runtime evidence is capability-based, not inferred from a driver name.
3. A missing runtime model produces `inconclusive`, never `accepted`.
4. Profiles are declarative where possible and executable only at explicit
   adapter boundaries.
5. Every accepted result records source, evidence, candidate, compile,
   registration, runtime, subsystem, unload, and comparison artifacts.
6. A new bus profile must be testable without changing `ExperimentRunner`,
   `LangGraph`, or the LLM bridge.

## Architecture

```text
source / descriptor / manifest
  -> InputNormalizer
  -> SourceInventory + source digest
  -> Extractor -> DeviceSpec + Formal RIS + facts
  -> ProfileRegistry.match(evidence)
  -> ManifestPlanner(profile, evidence)
  -> LangGraph generation workflow
  -> candidate contract + safety + registration checks
  -> declared compiler backend
  -> profile runtime adapter
  -> subsystem tests + unload + trace/oracle comparison
  -> accepted | failed | inconclusive
```

The profile registry is the only component that knows how a bus is detected or
how a runtime fixture is created. The runner consumes protocols already used
by `ExperimentRunner`:

- `Extractor`: produce normalized evidence;
- `PiBridge`: synthesize or repair a candidate;
- `Compiler`: compile the declared candidate layout;
- `ContractVerifier`: check source and registration contracts;
- `RuntimeRunner`: execute a profile-selected scenario;
- `TraceComparator`: compare declared observable behavior.

## Profile Contract

Each profile is a small object registered by bus family and capability. It
does not contain a driver name switch in the runner.

```python
class DriverTypeProfile(Protocol):
    profile_id: str
    bus: str

    def match(self, evidence: Mapping[str, Any]) -> MatchResult: ...
    def plan_manifest(self, evidence: Mapping[str, Any]) -> ProfilePlan: ...
    def validate_registration(
        self, candidate: Candidate, evidence: Mapping[str, Any]
    ) -> RegistrationReport: ...
    def build_runtime(self, plan: ProfilePlan) -> RuntimeRunner | None: ...
```

`ProfilePlan` contains only data: bus, module name, source layout, compile
context, runtime requirements, subsystem tests, coverage IDs, callback IDs,
and comparison policy. `RuntimeRunner` owns command construction and returns
the common structured result protocol.

The initial registry entries are:

- `platform-generic`: platform resources, registrar fixture, optional QEMU
  platform device, Kbuild and registration AST checks;
- `pci-generic`: PCI identity, QEMU PCI device, BAR/IRQ resource checks;
- `i2c-generic`: I2C client identity, virtual I2C adapter/fixture, client
  probe/remove and SMBus/I2C transaction checks;
- `spi-generic`: SPI device identity, virtual SPI controller/fixture, probe/
  remove and transfer checks.

`edu-pci` and `ftgpio010-gpio` become concrete data profiles built on the PCI
and platform implementations. They remain regression fixtures, not special
branches in the core runner.

## Capability Matrix

Runtime proof is represented as capabilities instead of a single boolean.

```json
{
  "static_analysis": "pass",
  "generation_contract": "pass",
  "kbuild": "pass",
  "registration": "pass",
  "probe": "pass",
  "subsystem": "pass",
  "unload": "pass",
  "trace": "pass"
}
```

Each capability has `status`, `evidence`, and optional `failure`. A result is
`accepted` only when all capabilities required by the selected profile are
`pass`. A profile may explicitly omit `trace` or `subsystem` only when its
manifest declares the omission and the final result is downgraded to
`inconclusive`; omission cannot be silently treated as success.

## Manifest Boundary

The schema-2 manifest remains the serialized audit boundary. Its existing
fields remain compatible, with the following generic additions:

```json
{
  "runtime": {
    "profile": "platform-generic",
    "capabilities": {
      "required": ["registration", "probe", "unload"],
      "optional": ["trace"]
    },
    "fixture": {
      "kind": "qemu-platform",
      "config": {}
    }
  }
}
```

The profile id is recorded separately from the source name. The manifest
loader rejects unknown capability statuses, duplicate IDs, paths outside the
repository, and a required capability with no declared evidence producer.

Existing `runtime.qemu` remains a fixture-specific configuration nested under
the generic runtime plan. This avoids coupling all future adapters to QEMU.

## Translation Flow

1. Normalize a C source, multi-source descriptor, or pinned manifest.
2. Discover local include closure and compute source digest.
3. Extract DeviceSpec, Formal RIS, facts, callback bindings, and readiness.
4. Match profiles using extracted evidence, not only the filename.
5. Reject ambiguous matches. If no profile matches, continue static analysis
   and Kbuild where possible, then return `inconclusive` with missing runtime
   capabilities.
6. Generate a portable candidate (`code` or validated multi-file `files`).
7. Run generic safety, generation-contract, compile, and registration gates.
8. Run the profile runtime plan and every declared subsystem test.
9. Compare declared traces/oracles when required, unload all test modules, and
   persist the complete capability report.

Repair feedback is structured by capability and remains independent of the
LLM provider. A repair request includes the candidate digest, failed stage,
failure class, exact evidence excerpt, and bounded repair requirements.

## Failure and Security Policy

- Invalid input, source digest mismatch, unsafe candidate paths, or malformed
  profile plans fail before generation.
- Candidate code violating the manifest safety policy is rejected.
- Runtime timeout, kernel Oops, kernel warning, failed subsystem test, failed
  unload, or missing required marker is a failed capability.
- Unsupported bus or unavailable fixture is `inconclusive`, not `accepted`.
- A profile cannot execute arbitrary commands from model output. Commands come
  from validated repository manifests and registered adapter implementations.

## Testing Strategy

The framework requires tests at four levels:

1. **Registry tests:** match platform, PCI, I2C, SPI, ambiguous input, and
   unknown input deterministically.
2. **Manifest tests:** serialize profile/capability plans and reject invalid
   or incomplete plans.
3. **Runner contract tests:** inject fake adapters and prove the same runner
   handles every profile without target-specific branches.
4. **Runtime tests:** keep `edu-pci` and `ftgpio010-gpio` QEMU regressions,
   and add I2C/SPI fixture tests that prove probe, transaction behavior, and
   unload. Each profile must include at least one negative test.

The acceptance matrix must contain at least one representative driver per
initial bus family and report results independently. A GPIO-only pass is not
valid evidence for PCI, I2C, or SPI support.

## Migration

1. Extract profile matching and plan construction from `auto_driver.py` into a
   registry module without changing existing CLI output.
2. Add the capability report while preserving the current `accepted`,
   `failed`, and `inconclusive` top-level statuses.
3. Convert the two existing profiles to registry entries and prove their
   QEMU regressions are unchanged.
4. Add generic I2C and SPI fixture adapters and representative manifests.
5. Add cross-profile workflow tests and update documentation with the support
   matrix and evidence rules.

## Non-Goals

- The first implementation does not promise hardware-in-the-loop validation.
- It does not ask the LLM to invent runtime commands or kernel fixtures.
- It does not make every Linux kernel subsystem semantically equivalent; each
  profile declares the observable contract it can prove.
