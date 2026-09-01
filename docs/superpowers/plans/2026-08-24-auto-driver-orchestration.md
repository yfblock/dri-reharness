# Automatic Driver Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn one driver path into a validated Linux generation experiment with an auditable manifest and fail-closed QEMU/subsystem result.

**Architecture:** Add a small input/profile layer ahead of the existing LangGraph and `ExperimentRunner`. The layer normalizes C, multi-source descriptor, and manifest inputs, writes a source-digested manifest, and delegates execution to the existing adapters. Unknown runtime capability produces `inconclusive`, while known profiles require candidate QEMU and trace evidence before acceptance.

**Tech Stack:** Python 3.12, existing `experiment_manifest`, `ExperimentRunner`, LangGraph, libclang extractor, Linux Kbuild, QEMU shell runner, pytest.

---

### Task 1: Add profile and input normalization primitives

**Files:**
- Create: `src/auto_driver.py`
- Test: `qa/tests/test_auto_driver.py`

- [ ] **Step 1: Write failing tests** for `.c` normalization, multi-source descriptor normalization, existing manifest digest validation, profile selection, ambiguity rejection, and unknown-profile `inconclusive` capability reporting.
- [ ] **Step 2: Run** `PYTHONPATH=src:qa python3 -m pytest -q qa/tests/test_auto_driver.py` and observe missing module/API failures.
- [ ] **Step 3: Implement** `normalize_input(path, repo_root, profile=None, output_dir=None)` and `write_generated_manifest(...)`. The function must return a JSON-serializable record containing source files, SHA-256 digests, manifest path, profile id, and missing capabilities. It must reject paths outside the repository and reject changed sources when an existing manifest pins `source.sha256`.
- [ ] **Step 4: Implement** deterministic built-in profiles for `edu-pci` and `ftgpio010-gpio`, using source basename/content signatures and no broad target-specific branches in the runner.
- [ ] **Step 5: Re-run** the focused tests and verify all input/profile cases pass.

### Task 2: Add the automatic CLI boundary

**Files:**
- Modify: `run.sh`
- Create: `qa/verification/run_auto_driver.py`
- Test: `qa/tests/test_run_dispatcher.py`

- [ ] **Step 1: Add** `auto-driver <path> [--profile ID] [--output-dir DIR] [--json-output FILE]` to the dispatcher tests with expected exit code and JSON protocol.
- [ ] **Step 2: Implement** the CLI wrapper. It must normalize the input first, invoke the existing LangGraph experiment mode for a profiled input, and emit `accepted|failed|inconclusive` without swallowing stage artifacts.
- [ ] **Step 3: Return** exit code `0` only for accepted, `1` for candidate/runtime failure, `2` for invalid/infrastructure failure, and `3` for inconclusive capability gaps.
- [ ] **Step 4: Run** dispatcher tests and a dry-run against `benchmarks/drivers/baseline/edu.c`.

### Task 3: Make subsystem profile evidence part of acceptance

**Files:**
- Modify: `src/experiment_manifest.py`
- Modify: `qa/verification/runtime_adapters.py`
- Modify: `scripts/qemu/qemu_run.sh`
- Test: `qa/tests/test_auto_driver.py`
- Test: `qa/tests/test_runtime_adapters.py`

- [ ] **Step 1: Add tests** proving a manifest with subsystem tests executes every declared test and fails when any return code or success pattern is missing.
- [ ] **Step 2: Ensure** the generated manifest persists `test.subsystem`, and the QEMU adapter passes it through the manifest path rather than silently falling back to only the primary exerciser.
- [ ] **Step 3: Ensure** result classification distinguishes `failed` from `inconclusive` and records the missing profile/test evidence.
- [ ] **Step 4: Run** the runtime adapter tests and the manifest protocol tests.

### Task 4: Wire LangGraph to the generated manifest

**Files:**
- Modify: `src/langgraph_workflow/__main__.py`
- Modify: `src/langgraph_workflow/graph.py`
- Modify: `src/langgraph_workflow/state.py`
- Test: `qa/tests/test_langgraph_workflow.py`

- [ ] **Step 1: Add** a test that invokes the workflow with a C path and verifies normalized manifest/profile fields appear in the final state.
- [ ] **Step 2: Add** a normalization node boundary that calls the auto-driver normalizer before analysis; preserve explicit `--experiment-manifest` precedence.
- [ ] **Step 3: Route** unknown profile results to a fail-closed `inconclusive` final state without calling the provider or pretending that QEMU passed.
- [ ] **Step 4: Run** the LangGraph tests with the deterministic model and verify provider model metadata remains `gpt-5.6-luna`.

### Task 5: End-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `REPRO.md`
- Test: `qa/tests/test_auto_driver.py`

- [ ] **Step 1: Document** the one-path command, output contract, profile override, and the distinction between accepted and inconclusive.
- [ ] **Step 2: Run** static checks, focused tests, and the full non-layout test suite.
- [ ] **Step 3: Run** `auto-driver` on `edu.c` with the deterministic/real configured provider as available, then run its generated manifest through QEMU.
- [ ] **Step 4: Verify** the accepted path contains generated source, contract, Kbuild, QEMU candidate, subsystem result, and trace comparison artifacts; verify unknown input returns `3` with explicit missing capabilities.

