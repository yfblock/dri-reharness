# Manifest Policy Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move PCI identity, DMA safety policy, and QEMU experiment facts into validated manifests and remove legacy device-specific scripts.

**Architecture:** The existing manifest loader becomes the single source of runtime policy. Generic generator, sanitizer, QEMU, and deterministic verification code consume typed policy values; no target basename or private device constant selects behavior. Legacy wrappers are removed.

**Tech Stack:** Python 3, JSON manifests, Bash, pytest, existing Linux/QEMU build helpers.

---

### Task 1: Extend manifest policy schema

**Files:**
- Modify: `src/experiment_manifest.py`
- Modify: `benchmarks/experiments/edu.json`
- Modify: `benchmarks/experiments/ftgpio010.json`
- Test: `qa/tests/test_experiment_manifest.py`

- [ ] **Step 1: Write failing policy validation tests**

```python
def test_pci_identity_and_safety_policy_round_trip(tmp_path):
    manifest = load_manifest(tmp_path / "edu.json")
    assert manifest.runtime.pci_identity.device == "edu"
    assert manifest.runtime.safety_policy.action in {"reject", "rewrite"}

def test_qemu_policy_rejects_missing_success_marker(tmp_path):
    payload = valid_manifest_payload()
    del payload["runtime"]["qemu"]["success_pattern"]
    with pytest.raises(ManifestError):
        load_manifest(write_json(tmp_path / "bad.json", payload))
```

- [ ] **Step 2: Run focused tests and verify they fail because fields are absent**

Run: `pytest -q qa/tests/test_experiment_manifest.py -k 'policy'`

Expected: FAIL with missing `pci_identity`, `safety_policy`, or `qemu` attributes.

- [ ] **Step 3: Implement typed policy records and strict validation**

Add `PciIdentity`, `SafetyPolicy`, and `QemuPolicy` dataclasses. Parse them from `runtime`, require `qemu.success_pattern`, require a PCI identity for `bus == "pci"`, and include all policy fields in canonical digest computation.

- [ ] **Step 4: Add policy values to both manifests and rerun tests**

Run: `pytest -q qa/tests/test_experiment_manifest.py`

Expected: all manifest tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/experiment_manifest.py benchmarks/experiments/edu.json benchmarks/experiments/ftgpio010.json qa/tests/test_experiment_manifest.py
git commit -m "feat: add manifest runtime policies"
```

### Task 2: Make PCI generation and source sanitization policy-driven

**Files:**
- Modify: `src/generator/linux.py`
- Modify: `tools/source/sanitize.py`
- Test: `qa/tests/test_no_hardcoding.py`
- Test: `qa/tests/test_sanitize.py`

- [ ] **Step 1: Write failing tests for policy-driven sanitization and PCI facts**

```python
def test_sanitizer_rejects_configured_forbidden_token(tmp_path):
    source = tmp_path / "driver.c"
    source.write_text("void f(void) { IO_DMA_CMD(1); }\n")
    policy = SafetyPolicy(forbidden_tokens=("IO_DMA_CMD",), action="reject", failure_class="safety")
    with pytest.raises(SafetyPolicyError):
        sanitize_source(source, policy)

def test_generic_modules_contain_no_edu_or_private_dma_constants():
    for path in ("src/generator/linux.py", "tools/source/sanitize.py"):
        text = Path(path).read_text()
        assert "device_spec.name == \"edu\"" not in text
        assert "IO_DMA_CMD" not in text
```

- [ ] **Step 2: Run tests to confirm the current hard-coded behavior fails the assertions**

Run: `pytest -q qa/tests/test_sanitize.py qa/tests/test_no_hardcoding.py -k 'sanitize or edu or dma'`

Expected: FAIL on the existing EDU branch or missing policy API.

- [ ] **Step 3: Replace device-name branching with manifest/device facts**

Delete the Linux generator EDU branch and have PCI identity fields flow from `DeviceSpec` facts supplied by the caller. Change sanitizer entry points to accept a `SafetyPolicy`, iterate `forbidden_tokens`, apply the declared action, and return structured failure metadata.

- [ ] **Step 4: Run focused generator and sanitizer tests**

Run: `pytest -q qa/tests/test_sanitize.py qa/tests/test_no_hardcoding.py qa/tests/test_generator_linux.py`

Expected: PASS with no device-specific constants in generic modules.

- [ ] **Step 5: Commit**

```bash
git add src/generator/linux.py tools/source/sanitize.py qa/tests/test_sanitize.py qa/tests/test_no_hardcoding.py
git commit -m "refactor: drive PCI and DMA behavior from policy"
```

### Task 3: Make QEMU execution and deterministic suite manifest-only

**Files:**
- Modify: `scripts/qemu/qemu_run.sh`
- Modify: `qa/verification/run_qemu_experiments.sh`
- Test: `qa/tests/test_runtime_adapters.py`
- Test: `qa/tests/test_no_hardcoding.py`

- [ ] **Step 1: Write failing tests for manifest iteration and policy command construction**

```python
def test_qemu_command_uses_manifest_values_without_driver_branches():
    command = build_qemu_command(load_manifest("benchmarks/experiments/edu.json"))
    assert "edu" in command
    assert "qemu_edu.sh" not in command

def test_deterministic_suite_discovers_all_manifests():
    text = Path("qa/verification/run_qemu_experiments.sh").read_text()
    assert "for manifest" in text or "glob" in text
    assert '"edu"' not in text
    assert '"gpio-ftgpio010"' not in text
```

- [ ] **Step 2: Run tests and verify fixed suite literals are detected**

Run: `pytest -q qa/tests/test_runtime_adapters.py qa/tests/test_no_hardcoding.py -k 'qemu or deterministic'`

Expected: FAIL while the suite has explicit EDU/FTGPIO blocks.

- [ ] **Step 3: Implement manifest-backed command construction and iteration**

Expose a single adapter function that maps validated `QemuPolicy` to `qemu_run.sh` arguments. Iterate `benchmarks/experiments/*.json`, derive build/module/test paths from each manifest, and write result keys from `manifest.name`.

- [ ] **Step 4: Run adapter tests and deterministic shell syntax checks**

Run: `pytest -q qa/tests/test_runtime_adapters.py qa/tests/test_no_hardcoding.py` and `bash -n scripts/qemu/qemu_run.sh qa/verification/run_qemu_experiments.sh`.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/qemu/qemu_run.sh qa/verification/run_qemu_experiments.sh qa/tests/test_runtime_adapters.py qa/tests/test_no_hardcoding.py
git commit -m "refactor: run QEMU experiments from manifests"
```

### Task 4: Delete legacy wrappers and migrate public dispatch

**Files:**
- Delete: `scripts/qemu/qemu_edu.sh`
- Delete: `scripts/qemu/qemu_platform.sh`
- Delete: `scripts/e2e/run_edu_e2e.sh`
- Delete: `scripts/e2e/run_gpio_e2e.sh`
- Modify: `run.sh`
- Modify: `README.md`
- Test: `qa/tests/test_run_dispatcher.py`

- [ ] **Step 1: Write failing tests that old commands are absent and manifest entry works**

```python
def test_dispatcher_exposes_manifest_experiment_only():
    text = Path("run.sh").read_text()
    assert "experiment" in text
    assert "qemu-edu" not in text
    assert "run_edu_e2e.sh" not in text
```

- [ ] **Step 2: Run the test to verify it fails on current compatibility aliases**

Run: `pytest -q qa/tests/test_run_dispatcher.py -k 'manifest or legacy'`

Expected: FAIL because legacy commands are still present.

- [ ] **Step 3: Remove wrappers and old dispatch aliases**

Delete the four scripts, remove demo/device-specific branches from `run.sh`, and document `./run.sh experiment <manifest>` as the sole experiment entry point.

- [ ] **Step 4: Run dispatch and shell checks**

Run: `pytest -q qa/tests/test_run_dispatcher.py` and `bash -n run.sh`.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -u scripts/qemu scripts/e2e run.sh README.md qa/tests/test_run_dispatcher.py
git commit -m "refactor: remove legacy device scripts"
```

### Task 5: Full verification and audit

**Files:**
- Modify: `docs/experiments/data-driven-closed-loop.md`

- [ ] **Step 1: Run focused policy and no-hardcoding tests**

Run: `pytest -q qa/tests/test_experiment_manifest.py qa/tests/test_sanitize.py qa/tests/test_runtime_adapters.py qa/tests/test_no_hardcoding.py qa/tests/test_run_dispatcher.py`.

Expected: PASS.

- [ ] **Step 2: Run deterministic QEMU experiments from manifests**

Run: `bash qa/verification/run_qemu_experiments.sh`.

Expected: `QEMU_EXPERIMENTS_OK`.

- [ ] **Step 3: Run the complete regression suite and record pre-existing dirty artifact failures separately**

Run: `pytest -q` and `git diff --check`.

Expected: no new failures; any dirty research result mismatch remains documented and is not reverted.

- [ ] **Step 4: Update migration documentation with residual domain API tables**

Document that Linux callback/API maps remain intentional semantic knowledge and are not device hardcoding.

- [ ] **Step 5: Commit final audit**

```bash
git add docs/experiments/data-driven-closed-loop.md
git commit -m "docs: record manifest policy migration verification"
```
