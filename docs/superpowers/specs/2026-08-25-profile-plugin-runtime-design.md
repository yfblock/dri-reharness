# Profile Plugin Runtime Closure Design

## Goal

Make a user-supplied driver profile a complete extension of the automatic
translation framework: source evidence selects the plugin profile, the
profile materializes a validated manifest, and the generic profile matrix can
execute that manifest and return `accepted`, `failed`, or `inconclusive`
without adding bus-specific logic to the core runner.

## Scope

This change covers the extension boundary and one end-to-end regression using
an injected test profile. It does not claim that the built-in QEMU fixtures
cover every Linux subsystem path. The seven runtime-ready built-in profiles
remain the default regression matrix; AMBA and serdev remain recognized but
runtime-inconclusive until they receive trusted fixtures. Additional bus
families can be supplied through the same plugin boundary.

The plugin contract is:

- a Python module exposing `register_profiles(registry)`;
- a `DriverTypeProfile` implementation providing source evidence, matching,
  and a `ProfilePlan`;
- a `ProfilePlan.manifest_template` that points to a repository-owned or
  explicitly supplied schema-2 manifest template;
- fixture, capability, provider, and runtime identity data expressed only
  through the plan/template, not through core runner conditionals.

The registry validates every plan before it reaches normalization or runtime:
profile ids cannot collide with built-ins, required and optional capabilities
cannot overlap, fixtures must be mappings, manifest and executable paths must
remain within the trusted repository or current generated-artifact root, and
subsystem providers must come from the provider catalog. A plugin may inspect
source evidence and return data, but it cannot inject shell commands, replace
provider executables, or bypass the generic candidate/compile/runtime gates.

If a driver derives a user-visible device name from `KBUILD_MODNAME`, the
profile must declare the build/runtime module identity in
`runtime_overrides.qemu.module`; the normalizer must not infer that identity
from the input filename.

Absolute and repository-relative template paths are already supported by the
normalizer. This change hardens the plan boundary and makes the matrix consume
the same registry; it does not duplicate that existing path behavior. The
normalizer, LangGraph workflow, and profile matrix each receive the same
registry instance for a run so matching and validation cannot drift between
stages.

The default matrix requires all built-in profiles whose catalog entry declares
`matrix_required=true`. When an explicit manifest is supplied without
`--required-profile`, the matrix requires exactly the unique profiles found in
those manifests. A plugin profile is never silently added to the default
acceptance set.

## Data Flow

```text
driver source + plugin
  -> ProfileRegistry evidence/match
  -> ProfilePlan + manifest template
  -> validated schema-2 manifest
  -> generic profile matrix
  -> Kbuild + QEMU + manifest-owned tests
  -> accepted | failed | inconclusive
```

`run_auto_driver.py --profile-plugin PATH` remains the public normalization
entry point. `run_profile_matrix.py --profile-plugin PATH --manifest PATH`
loads the same registry for source/profile discovery. When explicit manifests
are supplied without `--required-profile`, the matrix requires exactly the
profiles discovered in those manifests; the no-argument command requires all
profiles in the built-in registry. Callers can override this with repeatable
`--required-profile` arguments.

External manifest paths are allowed when their source and all referenced
assets remain repository-scoped, or when the path is the generated manifest
for the current run. The result records the absolute artifact location and
the manifest/source digests, so a plugin cannot silently change the input
after normalization.

## Failure Policy

- A plugin with no matching evidence is treated as an unknown runtime and
  returns `inconclusive`.
- A matching plugin without a valid template, identity, fixture, or required
  capability returns `inconclusive`; it never becomes `accepted` through a
  dry-run.
- A duplicate profile id, malformed `ProfilePlan`, unknown provider, path
  escape, or unsupported runtime adapter is an input/configuration failure and
  returns `failed` before the LLM or QEMU is invoked.
- A generated manifest that fails schema validation returns `invalid` before
  compilation.
- A runtime/build/test failure is `failed`.
- The matrix is fail-closed: every required profile must have exactly one
  accepted result and no failed or inconclusive result.

## Verification

Unit tests will cover plugin plan validation, duplicate/path/provider rejection,
explicit required-profile selection, external manifest discovery, and
preservation of the built-in default matrix behavior. A smoke run will use a
temporary plugin profile and an existing repository-owned QEMU fixture to prove
the complete registry-to-QEMU path without adding a driver-name branch. The
smoke result must contain the profile id, source and manifest digests, compile
receipt, binding/probe evidence, required subsystem markers, successful unload,
and no Oops or warning markers. Existing built-in profile QEMU results and
manifest tests must remain green.
