# Data-Driven Closed-Loop Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace target-specific e2e branching with a manifest-driven loop that compares original and candidate register traces and feeds structured failures to Pi.

**Architecture:** A validated experiment manifest supplies runtime/test facts. A Python orchestrator owns the stage state machine and emits structured artifacts. Pi remains a replaceable synthesis bridge; deterministic extractors and verifiers remain the authority for acceptance.

**Tech Stack:** Python 3, existing `repo_paths` helpers, JSON manifests, shell/QEMU runners, existing lowering/trace oracles, Pi Node SDK bridge.

---

### Task 1: Evidence and manifest contract

**Files:**
- Create: `src/experiment_manifest.py`
- Create: `src/experiment_protocol.py`
- Test: `qa/tests/test_experiment_manifest.py`
- Test: `qa/tests/test_experiment_protocol.py`
- Create: `benchmarks/experiments/edu.json`
- Create: `benchmarks/experiments/ftgpio010.json`

- [ ] Write tests that reject unknown manifest fields, repository-escaping paths, missing runtime/test sections, invalid iteration limits, and malformed trace fields.
- [ ] Write tests that round-trip stage records and classify `extraction`, `contract`, `compile`, `runtime`, `trace`, and `infrastructure` failures.
- [ ] Implement typed manifest loading/validation with stable canonical JSON and SHA-256 digest.
- [ ] Implement protocol helpers for stage records, structured feedback, trace events, and first-divergence reports.
- [ ] Add EDU and FTGPIO manifests by moving only existing experiment facts out of scripts.
- [ ] Run `python3 qa/tests/test_experiment_manifest.py` and `python3 qa/tests/test_experiment_protocol.py`.

### Task 2: Generic synthesis-loop runner

**Files:**
- Create: `src/experiment_runner.py`
- Create: `qa/verification/run_experiment.py`
- Test: `qa/tests/test_experiment_runner.py`

- [ ] Write tests for stage ordering, append-only iteration records, compile retry, runtime retry, trace retry, exhausted limits, and fail-closed infrastructure errors.
- [ ] Implement runner interfaces for extractor/bundler, Pi bridge, compiler, baseline runner, candidate runner, and trace comparator.
- [ ] Make every stage consume manifest/evidence data and return structured protocol records; prohibit subprocess output parsing outside adapters.
- [ ] Persist `experiment.json`, `iterations/NN-<stage>.json`, and final acceptance status under the experiment output directory.
- [ ] Run the focused runner tests with no external Pi credentials by injecting fake adapters.

### Task 3: Pi bridge and structured repair prompts

**Files:**
- Modify: `src/synthesis.py`
- Modify: `tools/pi/synth.mjs`
- Modify: `tools/pi/pi_synth.sh`
- Test: `qa/tests/test_pi_bridge_protocol.py`

- [ ] Write tests that prove the bridge accepts an evidence package and structured failure JSON without inspecting a driver basename.
- [ ] Add a machine-readable request envelope containing manifest digest, evidence digest, current candidate, failure class, failure payload, and remaining budget.
- [ ] Make Pi return code plus optional test scenario in a stable envelope; reject missing code or malformed scenario output.
- [ ] Preserve raw model output only as diagnostics and never use it as an acceptance signal.
- [ ] Run bridge tests with a fake Node command and the existing Python bundle generator.

### Task 4: Original/candidate trace execution

**Files:**
- Create: `src/trace_protocol.py`
- Modify: `tools/reporting/trace_match.py`
- Create: `qa/verification/trace_compare.py`
- Test: `qa/tests/test_trace_protocol.py`
- Test: `qa/tests/test_trace_compare.py`

- [ ] Write tests for event normalization, value masking rules declared by the manifest, first mismatch detection, missing/extra events, runtime-error comparison, and sequence ordering.
- [ ] Implement one normalized trace schema for original and candidate executions.
- [ ] Make the comparator report a structured prefix/suffix mismatch suitable for Pi repair.
- [ ] Keep source RIS comparison as a secondary invariant; the primary runtime decision must compare original and candidate under the same test scenario.
- [ ] Run trace tests against existing EDU and FTGPIO trace fixtures.

### Task 5: Manifest-backed QEMU adapters

**Files:**
- Create: `qa/verification/runtime_adapters.py`
- Modify: `scripts/qemu/qemu_run.sh`
- Modify: `scripts/e2e/run_e2e.sh`
- Test: `qa/tests/test_runtime_adapters.py`
- Test: `qa/tests/test_no_hardcoding.py`

- [ ] Write adapter contract tests for command construction, serial-log capture, timeout classification, and exit-status handling.
- [ ] Move EDU/FTGPIO launch facts and exerciser paths into manifests/adapters without changing their observable commands.
- [ ] Replace `detect_subsystem` and the large prompt/constraint `case` in `run_e2e.sh` with manifest loading and generic runner calls.
- [ ] Add a no-hardcoding scanner covering driver basenames, PCI IDs, private register constants, callback names, and subsystem branch labels in generic runner/Pi files.
- [ ] Run adapter and no-hardcoding tests plus the existing QEMU experiment suite.

### Task 6: Integration, migration, and audit

**Files:**
- Modify: `run.sh`
- Modify: `README.md`
- Modify: `docs/experiments/zero-shot-v2-callback-binding.md`
- Create: `docs/experiments/data-driven-closed-loop.md`
- Test: `qa/tests/test_run_dispatcher.py`

- [ ] Add `./run.sh experiment <manifest>` as the public entry point and retain `e2e` only as a compatibility wrapper.
- [ ] Document the manifest schema, stage artifacts, failure classes, and original-versus-candidate trace semantics.
- [ ] Run EDU and FTGPIO through manifests, then run the 19-driver static matrix and zero-shot guard.
- [ ] Run `git diff --check`, the full test suite, QEMU experiments, and the no-hardcoding audit.
- [ ] Review all changed files, commit focused changes, and record residual blockers separately from implementation specialization.

