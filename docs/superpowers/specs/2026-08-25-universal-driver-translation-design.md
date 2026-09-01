# Universal Driver Translation and Verification Design

## Goal

Build an automatic Linux driver translation framework that accepts single-file
and multi-file drivers across bus types, generates a candidate through the
configured LLM, and validates it through the strongest available evidence.
The framework must not encode a particular driver or subsystem in its core
translation loop.

The first runtime-supported bus families are platform, PCI, I2C, SPI, USB,
virtio, and MDIO. The profile boundary is intentionally extensible so
additional Linux driver families can be added without changing the core
pipeline.

## Current Gap

The automatic entry point now resolves seven runtime-ready bus-neutral built-in profiles and
can load additional profiles through the plugin boundary. High-fidelity
regression manifests are kept in the versioned
`benchmarks/profile-catalog.json` data file; they are not driver-name branches
in the normalizer. The remaining gap is breadth of runtime fixtures: a profile
must still declare a fixture and observable contract before a new Linux driver
family can be accepted at runtime.

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
- `usb-generic`: USB device identity, QEMU xHCI/USB-serial fixture, probe,
  control/bulk transfer, negative request, and unload checks.
- `virtio-generic`: Virtio device identity, QEMU block fixture, probe,
  virtqueue transaction, negative request, and unload checks.
- `mdio-generic`: MDIO device identity, synthetic `mii_bus` fixture, register
  read/write, invalid address, probe, binding, and unload checks.

The entries in `benchmarks/profile-catalog.json` are concrete regression inputs
built on the generic PCI and platform implementations. They remain data-backed
regression fixtures, not special branches in the core runner.

Generic matching rules are declared separately in
`benchmarks/driver-profile-definitions.json`. Each definition contains the bus,
callback/resource evidence keys, source tokens, optional identity regexes,
manifest template, fixture identity requirements, and required/optional
capabilities. The loader validates ids, capability names, regex capture groups,
duplicate definitions, and repository-contained template paths before creating
the common `_GenericBusProfile`. The automatic normalizer loads this catalog
from its selected `repo_root`; a missing catalog falls back only to the
repository's pinned default catalog. This makes ordinary new driver families
data-extensible while leaving complex source semantics to the explicit plugin
contract. `profile-catalog.json` remains source-specific regression data and is
never used as the type detector.

Subsystem semantics are a separate overlay registry at
`benchmarks/subsystem-contract-definitions.json`. A contract declares its
subsystem name, callback/resource evidence keys, source tokens, and static
capabilities. Detection returns zero or more matches, so transport and
subsystem are intentionally many-to-many: for example, a platform driver may
also implement GPIO and SDHCI contracts, while an I2C driver may implement a
GPIO expander contract. Matches are copied into `ProfilePlan`, LangGraph
synthesis evidence, and the optional manifest field
`runtime.subsystem_contracts`. They do not create a runtime result; a contract
without a registered provider or fixture remains `inconclusive`.

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

Subsystem test sources use a repository-owned provider catalog at
`benchmarks/subsystem-providers.json`. A provider declares its test kind,
validated executable (or KUnit module), supported subsystem, default test
fields, and required kernel modules. A manifest may reference the provider and
override only data such as device arguments; it cannot replace the provider's
executable with an arbitrary path or command. Unknown providers, kind/source
mismatches, unsupported subsystem use, and missing kernel prerequisites fail at
manifest validation. This keeps Linux kselftest/tool/KUnit integration data
driven while preserving the existing runner boundary.

Existing `runtime.qemu` remains a fixture-specific configuration nested under
the generic runtime plan. This avoids coupling all future adapters to QEMU.

## Translation Flow

1. Normalize a C source, multi-source descriptor, or pinned manifest.
2. Discover local include closure and compute source digest.
3. Extract DeviceSpec, Formal RIS, facts, callback bindings, and readiness.
4. Match profiles using extracted evidence, not only the filename.
5. Reject ambiguous matches. If no profile matches, continue static analysis
   and Kbuild where possible. In LangGraph generation mode, missing runtime
   capabilities do not prevent this static pipeline; final status remains
   `inconclusive` until a profile supplies runtime evidence.
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
   registry module without changing existing CLI output; keep only the
   versioned regression catalog as data.
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
