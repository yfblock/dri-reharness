# Profile Plugin Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make profile plugins reusable from source evidence through the generic translation/runtime boundary without silently expanding the default acceptance matrix.

**Architecture:** `ProfileRegistry` owns built-in versus plugin provenance and validates every `ProfilePlan`; `auto_driver` and LangGraph continue to consume the same registry; `run_profile_matrix` requires built-in runtime-ready profiles by default and plugin profiles only when an explicit manifest or `--required-profile` names them. No bus-specific branch is added to the translation or QEMU runner.

**Tech Stack:** Python 3.12, pytest, schema-2 manifests, existing LangGraph workflow, Linux Kbuild, QEMU, and the repository provider catalog.

---

## File Map

- Modify `src/driver_profiles.py`: track built-in profile provenance and validate plugin metadata/plans.
- Modify `qa/verification/run_profile_matrix.py`: derive default requirements only from built-in profiles and fail closed when no explicit plugin acceptance set exists.
- Modify `qa/tests/test_driver_profiles.py`: define red tests for plugin provenance and malformed plans.
- Modify `qa/tests/test_profile_matrix.py`: define red tests for default/plugin requirement selection.
- Modify `qa/tests/test_auto_driver.py`: cover plugin normalization and invalid plugin plan errors.
- Modify `README.md` and `REPRO.md`: document the seven built-in profiles and explicit plugin acceptance rule.

### Task 1: Lock the plugin provenance and plan contract with tests

**Files:**
- Test: `qa/tests/test_driver_profiles.py`
- Test: `qa/tests/test_profile_matrix.py`

- [ ] **Step 1: Add a failing test proving registered plugins are not built-in defaults.**

Add this test to `qa/tests/test_profile_matrix.py`:

```python
def test_plugin_profiles_are_not_added_to_default_acceptance_set():
    from driver_profiles import MatchResult, ProfilePlan, ProfileRegistry
    from verification.run_profile_matrix import default_profile_ids

    class PluginProfile:
        profile_id = "plugin-only"
        bus = "plugin-bus"
        matrix_required = True

        def match(self, evidence):
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, self.bus, ("registration",), (),
                "qemu-profile", {"kind": "qemu-plugin", "config": {}},
            )

    registry = ProfileRegistry()
    registry.register(PluginProfile())

    assert "plugin-only" not in default_profile_ids(
        _paths.REPO_ROOT, registry)
```

- [ ] **Step 2: Add a failing test proving a plugin plan cannot change bus identity.**

Add this test to `qa/tests/test_driver_profiles.py`:

```python
def test_registry_rejects_plugin_plan_with_profile_bus_mismatch():
    class WrongBusProfile:
        profile_id = "wrong-bus-plugin"
        bus = "declared-bus"

        def match(self, evidence):
            if evidence.get("bus") == self.bus:
                return MatchResult(self.profile_id, self.bus, "test", 10)
            return None

        def plan(self, evidence):
            return ProfilePlan(
                self.profile_id, "different-bus", ("registration",), (),
                "qemu-profile", {"kind": "qemu-plugin", "config": {}},
            )

    with pytest.raises(ProfileMatchError, match="wrong-bus-plugin.*bus"):
        ProfileRegistry((WrongBusProfile(),)).resolve({"bus": "declared-bus"})
```

- [ ] **Step 3: Add a failing test for invalid plugin metadata.**

Add a profile whose `profile_id` contains a slash and assert `register()` raises
`ProfileMatchError` or `ProfileCatalogError` with `profile_id` in the message.
Also add a plan with `runtime_overrides="not-a-mapping"` and assert `resolve()`
rejects it before returning a `ProfileResolution`.

- [ ] **Step 4: Run only the new tests and confirm the failures are behavioral.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_profile_matrix.py::test_plugin_profiles_are_not_added_to_default_acceptance_set \
  qa/tests/test_driver_profiles.py::test_registry_rejects_plugin_plan_with_profile_bus_mismatch
```

Expected: both tests fail because the current registry treats every registered
profile as a default profile and `_validate_plan()` does not compare `plan.bus`
or validate `runtime_overrides`.

### Task 2: Implement registry provenance and strict plan validation

**Files:**
- Modify: `src/driver_profiles.py`
- Test: `qa/tests/test_driver_profiles.py`

- [ ] **Step 1: Mark profiles present at registry construction as built-in and later registrations as plugins.**

Change `ProfileRegistry.__init__` to initialize:

```python
self._profiles = list(profiles)
self._builtin_ids = frozenset(
    str(profile.profile_id) for profile in self._profiles
)
```

Add:

```python
@property
def builtin_profiles(self) -> tuple[DriverTypeProfile, ...]:
    return tuple(
        profile for profile in self._profiles
        if profile.profile_id in self._builtin_ids
    )
```

Keep `register()` duplicate detection, but validate that `profile_id` and
`bus` are non-empty safe identifiers before appending. Profiles added by
`register()` remain outside `builtin_profiles`, even when they set
`matrix_required=True`.

- [ ] **Step 2: Extend `_validate_plan()` with profile identity and mapping checks.**

After checking `plan.profile_id`, require `plan.bus == profile.bus`. Validate
that `runtime_overrides` is a `Mapping`, `required_fixture_fields` is a tuple
of non-empty safe identifiers, and `registration_contract` remains a mapping
validated by `_registration_contract()`. Raise `ProfileMatchError` naming the
profile and field. Do not reject a missing `manifest_template`; that state is
needed for a correct `inconclusive` result.

- [ ] **Step 3: Run the registry tests and verify the minimal implementation.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q qa/tests/test_driver_profiles.py
```

Expected: all registry tests pass, including the new provenance, bus mismatch,
metadata, duplicate-capability, and fixture validation cases.

### Task 3: Make matrix selection fail closed for plugin-only runs

**Files:**
- Modify: `qa/verification/run_profile_matrix.py`
- Test: `qa/tests/test_profile_matrix.py`

- [ ] **Step 1: Change `default_profile_ids()` to use `builtin_profiles`.**

When the selected registry exposes `builtin_profiles`, derive the sorted IDs
only from that tuple and `matrix_required=True`. Preserve the fallback for a
third-party registry object that exposes only `profiles`.

- [ ] **Step 2: Prevent an empty implicit acceptance set.**

In `select_required_profiles()`, when `manifest_paths is None`, `explicit is
None`, and the selected registry has no built-in runtime-ready profiles, return
`["runtime_profile"]` instead of an empty list. This makes a plugin-only run
inconclusive rather than vacuously accepted. Explicit manifests and explicit
`--required-profile plugin-only` continue to select the plugin profile.

- [ ] **Step 3: Update the old custom-registry expectation.**

Change the existing test that expects `plugin-runtime` from an injected
registry to assert `default_profile_ids()` is empty for a registry containing
only a profile registered after construction, and assert
`select_required_profiles([], manifest_paths=None, explicit=None)` returns
`["runtime_profile"]`.

- [ ] **Step 4: Run matrix unit tests.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q qa/tests/test_profile_matrix.py
```

Expected: the default requirement remains the seven built-in profiles, an
explicit manifest still selects exactly its discovered plugin profile, and a
plugin-only implicit run is inconclusive.

### Task 4: Prove the shared plugin-to-manifest boundary

**Files:**
- Test: `qa/tests/test_auto_driver.py`
- Test: `qa/tests/test_profile_matrix.py`

- [ ] **Step 1: Add a plugin normalization test using the repository EDU template.**

Create a temporary plugin whose `evidence_from_source()` recognizes
`struct pci_driver`, whose `match()` returns `test-pci-plugin`, and whose
`plan()` returns `ProfilePlan(..., manifest_template=<absolute path to
`benchmarks/profile-templates/pci-generic.json`>)`. Call `normalize_input()`
with `profile_registry=registry` and assert the generated manifest records
`runtime.profile == "test-pci-plugin"`, the source digest is pinned, and all
provider/executable paths remain repository-scoped.

- [ ] **Step 2: Add invalid provider/template regression tests.**

Use a generated template containing a subsystem provider whose executable is
outside the repository and assert `normalize_input()` raises `AutoDriverError`
from manifest validation. Use a plan template path outside the trusted root and
assert the normalization result is rejected before any pipeline call.

- [ ] **Step 3: Run the plugin-focused tests.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_auto_driver.py -k 'plugin or provider' \
  qa/tests/test_profile_matrix.py -k 'plugin or explicit'
```

Expected: plugin normalization and explicit matrix discovery pass, while path
and provider injection are rejected.

### Task 5: Run the external-plugin QEMU smoke and update documentation

**Files:**
- Modify: `README.md`
- Modify: `REPRO.md`
- Review: `src/langgraph_workflow/`
- Review: `src/auto_driver.py`
- Review: `qa/verification/run_profile_matrix.py`

- [ ] **Step 1: Run the existing repository-owned EDU fixture through a temporary plugin.**

Generate a manifest with the plugin, then execute:

```bash
PYTHONPATH=src:qa:qa/verification python3 qa/verification/run_profile_matrix.py \
  --profile-plugin /absolute/path/to/plugin.py \
  --manifest /absolute/path/to/generated/manifest.json \
  --required-profile test-pci-plugin \
  --output /tmp/reharness-plugin-matrix
```

Expected: `matrix.json` has one required profile, status `accepted`, one
successful QEMU result, probe/binding evidence, declared test markers, unload
success, and no Oops/warning markers. The runner source contains no plugin or
driver-name conditional.

- [ ] **Step 2: Update the support and extension documentation.**

Replace stale six-profile statements with seven runtime-ready built-ins; state
that plugins are explicit extensions, that no-argument matrix execution does
not include plugin profiles, and that a plugin fixture proves only its declared
observable contract.

- [ ] **Step 3: Run the focused framework regression and static checks.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_driver_profiles.py qa/tests/test_auto_driver.py \
  qa/tests/test_profile_matrix.py qa/tests/test_profile_runtime.py \
  qa/tests/test_langgraph_workflow.py
git diff --check
bash -n run.sh scripts/qemu/qemu_run.sh qa/verification/run_qemu_experiments.sh
python3 -m compileall -q src qa
```

Expected: focused tests and static checks exit successfully. Any unrelated
frozen extractor failures must be reported separately and must not weaken the
plugin boundary or acceptance gates.
