# Generic Registration Root Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data-driven registration-root contract for direct Linux framework-object registration and use it to verify the generic network profile without hardcoded network logic.

**Architecture:** Extend the validated Linux registration catalog with an `object_root` API kind, an explicit `none` identity mode, and a typed `net_device.netdev_ops` link. The existing profile registry, manifest builder, runtime adapter, and AST oracle consume these declarations; only the catalog and generic root/link logic change.

**Tech Stack:** Python 3, pytest, JSON catalogs/manifests, libclang AST, Linux Kbuild, QEMU x86_64.

---

### Task 1: Define the failing registration contract tests

**Files:**
- Modify: `qa/tests/test_linux_registration_contracts.py`
- Modify: `qa/tests/test_driver_profiles.py`
- Modify: `qa/tests/test_profile_runtime.py`

- [ ] **Step 1: Add the catalog contract assertions**

Assert that the resolved catalog contains `net_device` as a root table,
`net_device_ops` as a supported callback table, and `register_netdev` as an
`object_root` API with argument `0` and type `struct net_device *`.

- [ ] **Step 2: Add the profile-plan assertions**

Resolve `network-generic` evidence and assert that its plan contains:

```python
assert plan.registration_contract == {
    "root_table": "net_device",
    "identity_field": "none",
    "device_id_tables": [],
}
```

- [ ] **Step 3: Add the manifest assertion**

Load `benchmarks/experiments/reharness-network.json` and assert that
`manifest.runtime.registration.root_table == "net_device"` and its identity
field is `none`.

- [ ] **Step 4: Run the focused tests and confirm RED**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_linux_registration_contracts.py \
  qa/tests/test_driver_profiles.py \
  qa/tests/test_profile_runtime.py
```

Expected result: failures identify the missing network catalog contract and
unsupported `none` identity mode.

### Task 2: Add generic catalog validation for object roots

**Files:**
- Modify: `src/linux_registration_contracts.py`
- Modify: `src/experiment_manifest.py`
- Modify: `src/driver_profiles.py`
- Modify: `benchmarks/linux-registration-catalog.json`
- Modify: `benchmarks/driver-profile-definitions.json`
- Modify: `benchmarks/profile-templates/network-generic.json`
- Modify: `benchmarks/experiments/reharness-network.json`

- [ ] **Step 1: Extend validated enum values**

Allow `object_root` in `_API_KINDS` and `none` in all registration identity
validators. Keep unknown values fail-closed.

- [ ] **Step 2: Add the network catalog entries**

Add the root/callback tables, the `register_netdev` API, and the typed
`netdev_ops` link to the repository catalog. Add the profile's registration
contract with `identity_field: "none"`.

- [ ] **Step 3: Materialize the same contract in the network template and experiment**

Add the `runtime.registration` object to both JSON manifests so direct QEMU
runs and generated manifests use identical semantics.

- [ ] **Step 4: Run the focused contract tests and confirm GREEN**

Run the Task 1 command and expect all selected tests to pass.

### Task 3: Prove object-root callback ownership in the generic AST oracle

**Files:**
- Modify: `qa/verification/linux_registration_ast_oracle.py`
- Modify: `qa/tests/test_linux_registration_ast_oracle.py`

- [ ] **Step 1: Add a failing AST fixture test**

Create temporary stubs for `struct net_device`, `struct net_device_ops`,
`register_netdev`, and module-init wiring. Generate a root object whose
`netdev_ops` points at a static callback table, then assert that
`net_device_ops.ndo_open` is a registered route. Change the registration call
to use an unrelated object and assert the report is incomplete.

- [ ] **Step 2: Run the single AST test and confirm RED**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_linux_registration_ast_oracle.py -k netdev
```

Expected result: the test fails because `object_root` is not yet recognized.

- [ ] **Step 3: Generalize root-call handling**

Use one root-call path for `driver_root` and `object_root`. Require module-init
reachability and exact typed object identity for both. Only add probe/remove
sets for `driver_root`; preserve existing GPIO, misc, clock, SDHCI, and USB
rules unchanged.

- [ ] **Step 4: Skip identity comparison only for explicit `none`**

In `_runtime_identity_contract`, return no identity errors when the declared
identity field is `none`; keep missing/mismatch behavior for `driver_name` and
`registrar`.

- [ ] **Step 5: Run the AST-focused tests and confirm GREEN**

Run the single AST test, then the complete AST oracle module.

### Task 4: Update documentation and matrix expectations

**Files:**
- Modify: `README.md`
- Modify: `REPRO.md`
- Modify: `qa/tests/test_profile_matrix.py`

- [ ] **Step 1: Replace stale seven-profile text**

State that the default runtime-ready matrix contains eight profiles and name
`network-generic`.

- [ ] **Step 2: Document the actual network boundary**

Explain that network verification proves registration, interface lifecycle,
and optional `netdevice.sh` evidence only; it does not prove packet paths or
all networking drivers.

- [ ] **Step 3: Assert the eight-profile required set**

Keep the matrix test data-driven where possible and require
`network-generic` alongside the existing seven profiles.

### Task 5: Verify the framework increment end to end

**Files:**
- No source changes unless a test exposes a contract regression.

- [ ] **Step 1: Run focused profile and registration tests**

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_linux_registration_contracts.py \
  qa/tests/test_linux_registration_ast_oracle.py \
  qa/tests/test_driver_profiles.py \
  qa/tests/test_profile_runtime.py \
  qa/tests/test_profile_matrix.py
```

- [ ] **Step 2: Run the full Python regression suite**

```bash
PYTHONPATH=src:qa:qa/verification pytest -q
```

Expected result: exit code `0` and no failed tests.

- [ ] **Step 3: Run the network strict compile and QEMU profile**

Use the existing `run_profile_matrix.py` network manifest and verify that the
network result is `accepted`, with any `netdevice.sh` failure retained as an
optional failure rather than hidden.

- [ ] **Step 4: Run the complete post-parser-fix matrix**

```bash
PYTHONPATH=src:qa:qa/verification \
python3 qa/verification/run_profile_matrix.py \
  --output artifacts/profile-matrix
```

Verify `matrix.json` reports all eight required profiles as `accepted` and
preserves per-test source reports.
