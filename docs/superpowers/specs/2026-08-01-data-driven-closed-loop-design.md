# Data-Driven Closed-Loop Synthesis Design

## Goal

Turn reharness into a data-driven experiment loop that extracts a static
register contract, asks Pi to synthesize the target driver and tests, and
iterates on compile, QEMU, and original-versus-candidate register-trace
feedback without driver-name, subsystem, or device-register special cases in
the generic orchestrator.

## Current Gap

The repository already has RIS extraction, bundle assembly, Pi synthesis, a
compile repair loop, QEMU execution, and trace matching. The remaining
specialization is concentrated in `scripts/e2e/run_e2e.sh`: it detects
subsystems with source-name heuristics, embeds EDU register constants, selects
fixed test executables, and emits subsystem-specific prompts and constraints.
The current trace path mainly checks a candidate against RIS; it does not yet
provide one common protocol for running the original and candidate drivers
under the same generated test scenario.

## Design

### 1. Experiment manifest is the only target-specific input

Each experiment is described by a versioned JSON manifest. The manifest may
declare source paths, compile context, target backend/language, QEMU machine
and device model, module/registration details, test actions, trace fields, and
iteration limits. These values are experiment data and are not selected by
`if driver == ...`, basename tests, or subsystem branches in the orchestrator.

The generic runner loads and validates the manifest, resolves all paths inside
the repository, and refuses unknown fields or missing required fields. A
device-specific runtime adapter may exist, but it is selected by an explicit
manifest adapter id and has no access to the driver's basename as a semantic
signal.

### 2. Evidence package

Static analysis produces a single immutable evidence package containing:

- `formal.ris` and `formal.json` for ordered register operations;
- `device.dspec`, `device-spec.json`, and backend bind data;
- exact compile-context provenance;
- source facts and readiness blockers;
- generation contract with one authorized receipt per RIS operation;
- the experiment manifest digest and source digest.

Pi receives this package plus a machine-readable repair request. The prompt
may render these files, but the acceptance gates consume structured files,
not natural-language claims.

### 3. Closed-loop stages

The runner executes the following state machine:

1. `extract`: build and validate the evidence package;
2. `synthesize`: ask Pi for target code and a test scenario derived from the
   package and manifest;
3. `compile`: compile the candidate and emit `compile_failure.json` on error;
4. `baseline`: build/instrument the original driver and run the generated test
   scenario to produce a normalized trace;
5. `candidate`: run the candidate with the same scenario and produce the same
   trace schema;
6. `compare`: compare normalized events, values, ordering, return status, and
   runtime errors;
7. `repair`: send only structured failures plus the current candidate back to
   Pi, then return to `compile`.

Every stage writes an append-only iteration record. A candidate is accepted
only when the generation contract, compilation, runtime result, and trace
comparison all pass.

### 4. Trace protocol

The common trace event contains `phase`, `function`, `kind`, `width_bits`,
`address`, `value`, `sequence`, and optional `source_op_id`. Normalization is
performed before comparison so original and translated implementations can
use different symbol names while preserving register behavior. A mismatch
must identify the first divergent event and include the surrounding prefix for
Pi repair.

### 5. No-hardcoding invariant

The generic runner and Pi bridge must not contain driver basenames, compatible
strings, PCI IDs, private register names, fixed callback names, or subsystem
branches. A repository guard scans those modules and checks that all target
facts originate from the loaded manifest/evidence package. Existing adapters
are allowed only when referenced by manifest data and covered by adapter-level
contract tests.

### 6. Failure and termination rules

Failures are classified as `extraction`, `contract`, `compile`, `runtime`,
`trace`, or `infrastructure`. Only compile/runtime/trace failures are sent to
Pi for repair. Extraction, contract, and infrastructure failures stop the run
with an actionable report. Iteration limits come from the manifest; exhausted
runs preserve all evidence and return a nonzero status.

## Acceptance Criteria

- The generic runner can execute an experiment solely from a manifest and
  generated evidence package.
- Compile failures, QEMU failures, and trace mismatches are structured and can
  be fed back to Pi without parsing ad-hoc subsystem output.
- Original and candidate executions use the same test scenario and normalized
  trace schema.
- No target-specific constants or source-name branches remain in the generic
  runner or Pi bridge.
- Existing EDU and FTGPIO QEMU experiments continue to pass through manifests.
- Existing static, lowering, and regression tests pass; new tests cover
  manifest validation, no-hardcoding scanning, trace normalization, mismatch
  reporting, and iteration termination.

