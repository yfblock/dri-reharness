# Universal Driver Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current driver-specific automation into a manifest-driven translation framework with reusable platform, PCI, I2C, SPI, USB, and virtio profiles and fail-closed capability evidence.

**Architecture:** Keep `ExperimentRunner`, LangGraph, LangChain, and the candidate contract bus-neutral. Add a typed profile registry that converts extracted evidence into a validated profile plan, extend manifests with required/optional capabilities, and implement runtime fixtures behind profile adapters. High-fidelity regression inputs live in `benchmarks/profile-catalog.json`; I2C, SPI, USB, and virtio use synthetic Linux/QEMU fixtures.

**Tech Stack:** Python 3.12, pytest, LangGraph, existing extractor/RIS, Linux Kbuild, QEMU, Linux `i2c-stub` support for I2C negative/transaction fixtures, and a repository-owned synthetic SPI controller fixture.

---

## File Map

- Create `src/driver_profiles.py`: typed profile match/plan contracts and registry.
- Create `benchmarks/profile-catalog.json`: data-backed mappings for high-fidelity regression manifests.
- Modify `src/auto_driver.py`: delegate input/profile resolution to the registry.
- Modify `src/experiment_manifest.py`: parse and serialize profile and capability plans.
- Modify `src/langgraph_workflow/graph.py` and `src/langgraph_workflow/tools.py`: carry profile evidence through the graph without making acceptance decisions.
- Create `qa/verification/profile_runtime.py`: profile runtime adapter implementations and fixture command plans.
- Modify `qa/verification/runtime_adapters.py`: resolve profile runtime adapters through the new registry and keep the existing adapter protocol.
- Modify `scripts/qemu/qemu_run.sh`: consume generic fixture/module declarations from the manifest.
- Create `qa/verification/device-registrar/i2c-registrar.c`: deterministic synthetic I2C adapter/client fixture.
- Create `qa/verification/device-registrar/spi-registrar.c`: deterministic synthetic SPI master/device fixture.
- Modify `platform/kernel/linux-x86_64.config`: enable the kernel capabilities required by the I2C/SPI fixtures.
- Create `benchmarks/drivers/fixtures/reharness-i2c-sensor.c`: representative I2C client driver.
- Create `benchmarks/drivers/fixtures/reharness-spi-sensor.c`: representative SPI client driver.
- Create `benchmarks/experiments/reharness-i2c.json` and `benchmarks/experiments/reharness-spi.json`: profile-owned manifests and tests.
- Test registry behavior in `qa/tests/test_driver_profiles.py`.
- Extend manifest tests in `qa/tests/test_experiment_manifest.py`.
- Extend auto-driver and workflow tests in `qa/tests/test_auto_driver.py` and `qa/tests/test_langgraph_workflow.py`.
- Test adapters and failure semantics in `qa/tests/test_runtime_adapters.py` and `qa/tests/test_profile_runtime.py`.
- Document the support matrix and evidence policy in `README.md` and `REPRO.md`.

### Task 1: Add the Typed Profile Registry

**Files:**
- Create: `src/driver_profiles.py`
- Create: `qa/tests/test_driver_profiles.py`

- [ ] **Step 1: Write the failing registry tests**

```python
def test_registry_matches_bus_from_extracted_evidence():
    registry = build_default_registry()
    result = registry.match({"bindings": {"i2c_driver.probe": "sensor_probe"},
                             "resources": {"i2c_client": {}}})
    assert result.profile_id == "i2c-generic"
    assert result.reason == "i2c callback and client evidence"


def test_registry_rejects_ambiguous_evidence():
    registry = build_default_registry()
    with pytest.raises(ProfileMatchError, match="ambiguous"):
        registry.match({"bindings": {"platform_driver.probe": "p",
                                      "pci_driver.probe": "q"}})


def test_registry_returns_missing_runtime_capability_for_unknown_bus():
    result = build_default_registry().resolve({"bindings": {"foo.probe": "p"}})
    assert result.profile is None
    assert result.missing_capabilities == ("runtime_profile",)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=src:qa pytest -q qa/tests/test_driver_profiles.py`

Expected: collection fails because `driver_profiles` and its registry types do not exist.

- [ ] **Step 3: Implement the profile contracts**

Implement these JSON-compatible dataclasses and protocols:

```python
@dataclass(frozen=True)
class MatchResult:
    profile_id: str
    bus: str
    reason: str
    score: int

@dataclass(frozen=True)
class ProfilePlan:
    profile_id: str
    bus: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    runtime_adapter: str | None
    fixture: Mapping[str, Any]

class DriverTypeProfile(Protocol):
    profile_id: str
    bus: str
    def match(self, evidence: Mapping[str, Any]) -> MatchResult | None: ...
    def plan(self, evidence: Mapping[str, Any]) -> ProfilePlan: ...
```

`ProfileRegistry.match()` must score evidence, reject ties, and never inspect a driver basename. Register `platform-generic`, `pci-generic`, `i2c-generic`, and `spi-generic` with callback/resource predicates. `build_default_registry()` returns a fresh registry so tests cannot leak registrations.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `PYTHONPATH=src:qa pytest -q qa/tests/test_driver_profiles.py`

Expected: all registry matching, ambiguity, and unknown-profile tests pass.

- [ ] **Step 5: Commit the registry boundary**

```bash
git add src/driver_profiles.py qa/tests/test_driver_profiles.py
git commit -m "feat: add generic driver profile registry"
```

### Task 2: Add Manifest Capability and Profile Plans

**Files:**
- Modify: `src/experiment_manifest.py`
- Modify: `qa/tests/test_experiment_manifest.py`

- [ ] **Step 1: Write failing manifest tests**

Add tests requiring this document to round-trip:

```json
"runtime": {
  "adapter": "qemu-platform",
  "profile": "platform-generic",
  "capabilities": {
    "required": ["registration", "probe", "unload"],
    "optional": ["trace"]
  },
  "fixture": {"kind": "qemu-platform", "config": {}}
}
```

Assert duplicate capability IDs, unknown capability names, required/optional overlap, and fixture paths outside the repository raise `ManifestError`.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q qa/tests/test_experiment_manifest.py -k capability`

Expected: the loader rejects `runtime.profile` as an unknown field and the new validation tests fail.

- [ ] **Step 3: Implement typed manifest fields**

Add `RuntimeCapabilitySpec`, `RuntimeCapabilities`, and `RuntimeFixture` dataclasses. Extend `RuntimeSpec` with `profile`, `capabilities`, and `fixture`. Accept old manifests by defaulting profile to `None`, required capabilities to the adapter's existing behavior, and fixture to the existing QEMU policy. Reject unknown statuses and duplicate IDs before constructing the manifest.

Use this validation invariant:

```python
if set(required) & set(optional):
    raise ManifestError("runtime.capabilities required and optional overlap")
if any(item not in KNOWN_CAPABILITIES for item in (*required, *optional)):
    raise ManifestError("runtime.capabilities contains unknown capability")
```

- [ ] **Step 4: Run manifest regression tests**

Run: `pytest -q qa/tests/test_experiment_manifest.py`

Expected: all existing schema-2 tests and the new capability tests pass.

- [ ] **Step 5: Commit manifest support**

```bash
git add src/experiment_manifest.py qa/tests/test_experiment_manifest.py
git commit -m "feat: add profile capability plans to manifests"
```

### Task 3: Route Automatic Input Through the Registry

**Files:**
- Modify: `src/auto_driver.py`
- Modify: `src/langgraph_workflow/graph.py`
- Modify: `src/langgraph_workflow/tools.py`
- Test: `qa/tests/test_auto_driver.py`
- Test: `qa/tests/test_langgraph_workflow.py`

- [ ] **Step 1: Write failing cross-profile tests**

Test that `normalize_input()` returns a profile plan for the existing PCI and platform inputs, preserves the complete GPIO subsystem list, and reports `runtime_profile` for unknown input. Add a graph test asserting `analysis.profile` and `analysis.missing_capabilities` survive normalization and finalization without invoking the LLM when the profile is unavailable.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q qa/tests/test_auto_driver.py qa/tests/test_langgraph_workflow.py -k profile`

Expected: profile-plan fields are absent and the new assertions fail.

- [ ] **Step 3: Replace the hardcoded profile map**

Make `auto_driver.resolve_profile()` call `build_default_registry().resolve()` using extracted evidence. Keep `PROFILES` only as a compatibility view loaded from `benchmarks/profile-catalog.json`; no concrete driver id or source path may be embedded in `auto_driver.py`. `_manifest_for_profile()` must serialize the returned `ProfilePlan` and preserve all template tests and coverage declarations.

The graph must carry this shape:

```python
{
    "profile": {"id": "pci-generic", "bus": "pci"},
    "capabilities": {"required": ["registration", "probe"]},
    "missing_capabilities": [],
}
```

- [ ] **Step 4: Run cross-profile tests**

Run: `pytest -q qa/tests/test_auto_driver.py qa/tests/test_langgraph_workflow.py`

Expected: existing edu/GPIO behavior remains green and unknown inputs remain explicitly inconclusive.

- [ ] **Step 5: Commit registry integration**

```bash
git add src/auto_driver.py src/langgraph_workflow/graph.py src/langgraph_workflow/tools.py qa/tests/test_auto_driver.py qa/tests/test_langgraph_workflow.py
git commit -m "feat: route automation through generic driver profiles"
```

### Task 4: Add Generic Capability Reporting and Runtime Resolution

**Files:**
- Create: `qa/verification/profile_runtime.py`
- Modify: `qa/verification/runtime_adapters.py`
- Modify: `scripts/qemu/qemu_run.sh`
- Create: `qa/tests/test_profile_runtime.py`
- Modify: `qa/tests/test_runtime_adapters.py`

- [ ] **Step 1: Write failing runtime capability tests**

Test a fake runtime plan that returns pass/fail/inconclusive capability rows, assert required failure yields `failed`, and assert unavailable fixture yields `inconclusive`. Test that profile resolution is selected from `manifest.runtime.profile`, while legacy `qemu` adapter manifests still resolve unchanged.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q qa/tests/test_profile_runtime.py qa/tests/test_runtime_adapters.py -k capability`

Expected: the profile runtime module is missing and the new classification assertions fail.

- [ ] **Step 3: Implement the profile runtime protocol**

Create:

```python
class ProfileRuntime(Protocol):
    def run(self, manifest, candidate, scenario, role) -> Mapping[str, Any]: ...

def required_capability_failure(report, required):
    missing = [name for name in required
               if report.get(name, {}).get("status") != "pass"]
    return missing
```

Wrap existing `QemuRuntimeAdapter` as `QemuProfileRuntime`, add `StaticKbuildRuntime` for no-fixture profiles, and return a common report containing `capabilities`, `evidence`, `failure`, and `inconclusive`. Do not move candidate compilation or LLM calls into the profile runtime.

- [ ] **Step 4: Make the shell runner fixture-generic**

Extend manifest loading to emit validated arrays for `fixture.kernel_modules`, `fixture.assets`, and `fixture.init_commands`. Reject init commands containing shell metacharacters outside the manifest's trusted adapter output. Keep existing `QEMU_RUN_DONE`, coverage, warning, Oops, binding, and unload checks.

- [ ] **Step 5: Run runtime regression tests**

Run: `pytest -q qa/tests/test_profile_runtime.py qa/tests/test_runtime_adapters.py`

Expected: all existing QEMU protocol tests and new capability report tests pass.

- [ ] **Step 6: Commit generic runtime reporting**

```bash
git add qa/verification/profile_runtime.py qa/verification/runtime_adapters.py scripts/qemu/qemu_run.sh qa/tests/test_profile_runtime.py qa/tests/test_runtime_adapters.py
git commit -m "feat: add capability-based profile runtime results"
```

### Task 5: Implement the I2C Profile Fixture

**Files:**
- Create: `qa/verification/device-registrar/i2c-registrar.c`
- Modify: `platform/kernel/linux-x86_64.config`
- Create: `benchmarks/drivers/fixtures/reharness-i2c-sensor.c`
- Create: `benchmarks/experiments/reharness-i2c.json`
- Test: `qa/tests/test_profile_runtime.py`
- Test: `qa/tests/test_experiment_manifest.py`

- [ ] **Step 1: Write fixture contract tests**

Assert the I2C manifest declares `i2c-generic`, requires `registration`, `probe`, `transaction`, and `unload`, and names only repository-owned fixture modules and tests. Assert the registrar source creates an adapter, registers one deterministic client address, and removes both in reverse order.

- [ ] **Step 2: Enable and build the required kernel support**

Change the kernel config from `# CONFIG_I2C_STUB is not set` to `CONFIG_I2C_STUB=m` and enable `CONFIG_I2C_CHARDEV=y` only if the declared userspace test requires `/dev/i2c-*`. Run:

```bash
./tools/build/prepare_kernel.sh build
make -C qa/verification/device-registrar KERNELDIR="$PWD/platform/kernel/build"
```

Expected: the kernel contains the I2C core and the fixture module builds without warnings.

- [ ] **Step 3: Implement deterministic I2C registrar and client fixture**

Register an `i2c_adapter` whose `master_xfer` returns a fixed register map and records transfer count, then register an `i2c_client` with a stable name/address. Expose a read-only misc control device that triggers a bounded transaction for the subsystem test. On unload, unregister the client, adapter, and control device and emit structured markers.

- [ ] **Step 4: Add representative I2C driver and manifest tests**

The fixture driver must use `module_i2c_driver`, match the declared client name, read one register during probe, expose a small sysfs value, and remove cleanly. Its manifest must declare at least one successful transaction test and one invalid-address negative test.

- [ ] **Step 5: Run the I2C compile and QEMU test**

Run:

```bash
pytest -q qa/tests/test_profile_runtime.py -k i2c
./run.sh experiment benchmarks/experiments/reharness-i2c.json
```

Expected: static contract, Kbuild, registration, probe, transaction, negative test, unload, and required markers pass. Missing `i2c-stub` or fixture support must produce `inconclusive`, never `accepted`.

- [ ] **Step 6: Commit the I2C profile**

```bash
git add qa/verification/device-registrar/i2c-registrar.c platform/kernel/linux-x86_64.config benchmarks/drivers/fixtures/reharness-i2c-sensor.c benchmarks/experiments/reharness-i2c.json qa/tests/test_profile_runtime.py qa/tests/test_experiment_manifest.py
git commit -m "feat: add generic I2C translation fixture"
```

### Task 6: Implement the SPI Profile Fixture

**Files:**
- Create: `qa/verification/device-registrar/spi-registrar.c`
- Modify: `platform/kernel/linux-x86_64.config`
- Create: `benchmarks/drivers/fixtures/reharness-spi-sensor.c`
- Create: `benchmarks/experiments/reharness-spi.json`
- Test: `qa/tests/test_profile_runtime.py`

- [ ] **Step 1: Write SPI fixture contract tests**

Assert the SPI manifest declares `spi-generic`, requires `registration`, `probe`, `transfer`, and `unload`, and that the registrar owns a synthetic `spi_controller` and one `spi_device` with a stable modalias. Assert the negative test records a transfer error without leaving the device registered.

- [ ] **Step 2: Enable SPI kernel support**

Change the kernel config from `# CONFIG_SPI is not set` to `CONFIG_SPI=y`, `CONFIG_SPI_MASTER=y`, and `CONFIG_SPI_LOOPBACK_TEST=m` when the in-tree loopback test is used. Run `./tools/build/prepare_kernel.sh build` and verify the resulting config before compiling fixtures.

- [ ] **Step 3: Implement the synthetic SPI controller**

Register a `spi_controller` with a deterministic `transfer_one_message` implementation that copies TX bytes into RX bytes, increments a transfer counter, and returns a configured error for the negative scenario. Register the `spi_device` after the controller and unregister the device before the controller during cleanup.

- [ ] **Step 4: Add representative SPI driver and manifest**

The fixture driver must use `module_spi_driver`, match the declared modalias, execute one multi-transfer message during probe or a control ioctl, expose its transfer result, and remove cleanly. The manifest must include one successful transfer, one multi-transfer test, and one controlled error test.

- [ ] **Step 5: Run SPI tests and QEMU**

Run:

```bash
pytest -q qa/tests/test_profile_runtime.py -k spi
./run.sh experiment benchmarks/experiments/reharness-spi.json
```

Expected: all required capability markers pass and `rmmod` succeeds. A missing SPI kernel capability is reported as `inconclusive`.

- [ ] **Step 6: Commit the SPI profile**

```bash
git add qa/verification/device-registrar/spi-registrar.c platform/kernel/linux-x86_64.config benchmarks/drivers/fixtures/reharness-spi-sensor.c benchmarks/experiments/reharness-spi.json qa/tests/test_profile_runtime.py
git commit -m "feat: add generic SPI translation fixture"
```

### Task 7: Cross-Profile Acceptance Matrix and Documentation

**Files:**
- Create: `qa/verification/run_profile_matrix.py`
- Create: `qa/tests/test_profile_matrix.py`
- Modify: `README.md`
- Modify: `REPRO.md`

- [ ] **Step 1: Write matrix protocol tests**

Assert the matrix runner executes each manifest independently, records `accepted`, `failed`, or `inconclusive`, preserves each output directory, and returns nonzero when a required profile unexpectedly downgrades or passes without its required capabilities.

- [ ] **Step 2: Implement the matrix runner**

Accept explicit manifest paths, run each through the same `ExperimentRunner` adapter factory, and write one JSON result containing manifest digest, profile id, bus, capability statuses, artifact directory, and failure. Do not infer profiles from filenames inside the matrix runner.

- [ ] **Step 3: Update user-facing documentation**

Document:

```bash
./run.sh auto-driver <driver.c> --backend linux
./run.sh profile-matrix benchmarks/experiments/edu.json \
  benchmarks/experiments/ftgpio010.json \
  benchmarks/experiments/reharness-i2c.json \
  benchmarks/experiments/reharness-spi.json
```

Explain that `accepted` requires every profile-required capability, while `inconclusive` means translation/static evidence exists but runtime proof is unavailable.

- [ ] **Step 4: Run the full acceptance matrix**

Run:

```bash
pytest -q qa/tests/test_driver_profiles.py qa/tests/test_profile_runtime.py qa/tests/test_profile_matrix.py qa/tests/test_experiment_manifest.py qa/tests/test_auto_driver.py qa/tests/test_langgraph_workflow.py qa/tests/test_runtime_adapters.py
python3 qa/verification/run_profile_matrix.py benchmarks/experiments/edu.json benchmarks/experiments/ftgpio010.json benchmarks/experiments/reharness-i2c.json benchmarks/experiments/reharness-spi.json
```

Expected: every available fixture profile has independent accepted evidence; any unavailable fixture is explicitly inconclusive and is not counted as accepted.

- [ ] **Step 5: Commit matrix and documentation**

```bash
git add qa/verification/run_profile_matrix.py qa/tests/test_profile_matrix.py README.md REPRO.md
git commit -m "feat: add cross-profile translation acceptance matrix"
```

### Task 8: Final Verification and Requirement Audit

**Files:**
- Review: `docs/superpowers/specs/2026-08-25-universal-driver-translation-design.md`
- Review: all manifests and matrix results

- [ ] **Step 1: Run syntax and repository checks**

Run: `git diff --check && bash -n scripts/qemu/qemu_run.sh qa/verification/run_qemu_experiments.sh`

- [ ] **Step 2: Run all focused and cross-profile tests**

Run: `pytest -q qa/tests/test_driver_profiles.py qa/tests/test_profile_runtime.py qa/tests/test_profile_matrix.py qa/tests/test_experiment_manifest.py qa/tests/test_auto_driver.py qa/tests/test_langgraph_workflow.py qa/tests/test_runtime_adapters.py`

- [ ] **Step 3: Verify independent runtime evidence**

For each profile, inspect its final JSON and QEMU log. Confirm the profile id, source digest, generated candidate, compile receipt, registration report, every required capability marker, negative test, no Oops/warning, and successful unload. Do not infer I2C/SPI support from the PCI/platform logs.

- [ ] **Step 4: Audit the generic boundary**

Search the core modules for concrete profile identifiers:

```bash
rg -n "edu-pci|ftgpio010|reharness-i2c|reharness-spi" src/experiment_runner.py src/langgraph_workflow qa/verification/profile_runtime.py
```

Expected: no driver-specific conditional branches in the core runner or LangGraph topology; identifiers appear only in profile data, fixtures, tests, and documented regression inputs.

- [ ] **Step 5: Record the final support matrix**

Persist the matrix result under `research/experiments/results/profile-matrix.json` and report any profile whose required capability is `inconclusive` rather than claiming universal acceptance.
