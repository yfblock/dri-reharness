# Generic Test-Source Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile manifest-declared Linux subsystem tests with guest evidence and use the strict report for generic runtime capability decisions.

**Architecture:** Add a pure report builder under `qa/verification` that accepts manifest test specs and parsed guest records. Integrate it once in `QemuProfileRuntime`; keep provider validation, QEMU execution, and bus/profile selection in their existing layers.

**Tech Stack:** Python 3.12, pytest, existing schema-2 manifests, QEMU marker protocol, and the existing capability report.

---

### Task 1: Lock the reconciliation contract with failing tests

**Files:**
- Create: `qa/tests/test_subsystem_test_reporting.py`
- Modify: `qa/tests/test_profile_runtime.py`

- [x] **Step 1: Write tests for required and optional evidence.**

```python
def test_required_tests_need_exact_pass_evidence():
    manifest_tests = (SimpleNamespace(name="transaction", kind="native",
                                      provider=None, required=True),)
    report = build_subsystem_test_report(
        manifest_tests,
        [{"name": "transaction", "status": "pass",
          "success": True, "return_code": 0}],
    )
    assert report["status"] == "accepted"
    assert report["tests"][0]["kind"] == "native"


def test_missing_or_unexpected_required_evidence_is_inconclusive():
    manifest_tests = (SimpleNamespace(name="declared", kind="tool",
                                      provider="linux-tool", required=True),)
    report = build_subsystem_test_report(
        manifest_tests,
        [{"name": "not-declared", "status": "pass",
          "success": True, "return_code": 0}],
    )
    assert report["status"] == "inconclusive"
    assert report["missing_required"] == ["declared"]
    assert report["unexpected_observed"] == ["not-declared"]


def test_required_failure_and_optional_failure_are_distinguished():
    manifest_tests = (
        SimpleNamespace(name="required", kind="kunit", provider="clock",
                         required=True),
        SimpleNamespace(name="optional", kind="kselftest", provider="gpio",
                         required=False),
    )
    report = build_subsystem_test_report(
        manifest_tests,
        [{"name": "required", "status": "fail", "success": False,
          "return_code": 1},
         {"name": "optional", "status": "fail", "success": False,
          "return_code": 1}],
    )
    assert report["status"] == "failed"
    assert report["failed_required"] == ["required"]
    assert report["optional_failures"] == ["optional"]
    assert report["declared"]["by_kind"] == {"kselftest": 1, "kunit": 1}
```

- [x] **Step 2: Run the focused tests and verify RED.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q qa/tests/test_subsystem_test_reporting.py
```

Expected: collection fails because the new report module and function do not
exist.

- [x] **Step 3: Add tests for duplicate names and runtime capability mapping.**

Append these report tests:

```python
def test_duplicate_declared_or_observed_names_are_inconclusive():
    declared = (
        SimpleNamespace(name="same", kind="native", provider=None,
                         required=True),
        SimpleNamespace(name="same", kind="tool", provider="tool",
                         required=True),
    )
    report = build_subsystem_test_report(
        declared,
        [{"name": "same", "status": "pass", "success": True,
          "return_code": 0},
         {"name": "same", "status": "pass", "success": True,
          "return_code": 0}],
    )
    assert report["status"] == "inconclusive"
    assert report["duplicate_declared"] == ["same"]
    assert report["duplicate_observed"] == ["same"]
```

Update the existing `test_qemu_profile_runtime_maps_passing_subsystem_tests_to_transaction`
fake manifest to use
`SimpleNamespace(name="i2c-transaction", kind="native", provider=None,
required=True)` and add:

```python
assert result["test_source_report"]["status"] == "accepted"
assert result["payload"]["test_source_report"]["declared"]["total"] == 1
```

- [x] **Step 4: Run the focused tests and verify the failures are behavioral.**

- [ ] **Step 4: Run the focused tests and verify the failures are behavioral.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_subsystem_test_reporting.py \
  qa/tests/test_profile_runtime.py
```

Expected: collection succeeds, the new report import/function tests fail, and
the existing runtime tests fail only where strict declaration matching is not
yet implemented.

### Task 2: Implement the pure test-source report

**Files:**
- Create: `qa/verification/subsystem_test_reporting.py`
- Test: `qa/tests/test_subsystem_test_reporting.py`

- [x] **Step 1: Implement exact name reconciliation.**

Create `qa/verification/subsystem_test_reporting.py` with this public shape:

```python
def build_subsystem_test_report(
        declared: Sequence[Any], observed: Sequence[Mapping[str, Any]],
        ) -> dict[str, Any]:
    declared_rows = [_declared_row(item) for item in declared]
    observed_rows = [dict(item) for item in observed
                     if isinstance(item, Mapping)]
    declared_names = [row["name"] for row in declared_rows]
    observed_names = [row.get("name") for row in observed_rows]
    duplicate_declared = sorted({name for name in declared_names
                                 if declared_names.count(name) > 1})
    duplicate_observed = sorted({name for name in observed_names
                                 if isinstance(name, str)
                                 and observed_names.count(name) > 1})
    observed_by_name = {row["name"]: row for row in observed_rows
                        if isinstance(row.get("name"), str)}
    tests = []
    missing_required = []
    failed_required = []
    inconclusive_required = []
    optional_failures = []
    for row in declared_rows:
        observed_row = observed_by_name.get(row["name"])
        merged = {**row, "observed": observed_row}
        if observed_row is None:
            merged["status"] = "missing"
            if row["required"]:
                missing_required.append(row["name"])
        else:
            status = _observed_status(observed_row)
            merged["status"] = status
            if row["required"]:
                if status == "failed":
                    failed_required.append(row["name"])
                elif status != "pass":
                    inconclusive_required.append(row["name"])
            elif status != "pass":
                optional_failures.append(row["name"])
        tests.append(merged)
    unexpected = sorted(set(name for name in observed_names
                            if isinstance(name, str)) - set(declared_names))
    declared_counts = _declared_counts(declared_rows)
    explicit_failure = bool(failed_required)
    evidence_gap = bool(missing_required or inconclusive_required
                        or unexpected or duplicate_declared
                        or duplicate_observed)
    status = ("failed" if explicit_failure else
              "inconclusive" if evidence_gap else "accepted")
    return {
        "status": status,
        "declared": declared_counts,
        "observed": {"total": len(observed_rows),
                      "names": sorted(name for name in observed_names
                                       if isinstance(name, str))},
        "tests": tests,
        "missing_required": sorted(missing_required),
        "failed_required": sorted(failed_required),
        "inconclusive_required": sorted(inconclusive_required),
        "unexpected_observed": unexpected,
        "optional_failures": sorted(optional_failures),
        "duplicate_declared": duplicate_declared,
        "duplicate_observed": duplicate_observed,
    }
```

Implement `_declared_row`, `_declared_counts`, and `_observed_status` as pure
helpers; reject a non-mapping observed item by treating it as an unnamed
inconclusive observation rather than raising from the runtime path.

- [x] **Step 2: Implement fail-closed status classification.**

Use the following predicate in `_observed_status`:

```python
if (row.get("status") == "pass" and row.get("success") is True
        and row.get("return_code") == 0):
    return "pass"
if (row.get("status") == "fail" or row.get("success") is False
        or row.get("return_code") not in (None, 0)):
    return "failed"
return "inconclusive"
```

Required explicit failures take precedence over the report-level
`inconclusive` status; all other missing, malformed, skipped, unexpected, and
duplicate evidence remains inconclusive.

- [x] **Step 3: Run report tests and verify GREEN.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q qa/tests/test_subsystem_test_reporting.py
```

Expected: all report contract tests pass.

### Task 3: Integrate the report into generic profile runtime

**Files:**
- Modify: `qa/verification/profile_runtime.py`
- Test: `qa/tests/test_profile_runtime.py`

- [x] **Step 1: Replace loose subsystem summarization.**

Call the report builder from `QemuProfileRuntime.run()` using
`manifest.test.subsystem.tests` and `payload["subsystem_tests"]`. Set
`subsystem`, `transaction`, and `transfer` capability rows to the report
status when requested. Do not infer a pass when the payload has no declared
test evidence.

- [x] **Step 2: Preserve the structured report.**

Add the report under result `test_source_report` and payload
`test_source_report`; retain the existing raw `subsystem_tests` list for
compatibility.

- [x] **Step 3: Run runtime tests and verify GREEN.**

Run:

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_subsystem_test_reporting.py \
  qa/tests/test_profile_runtime.py
```

Expected: all report and profile-runtime tests pass.

### Task 4: Verify the framework boundary and documentation

**Files:**
- Modify: `README.md`
- Modify: `REPRO.md`
- Test: `qa/tests/test_profile_matrix.py`

- [x] **Step 1: Add matrix report assertions.**

Assert that accepted profile results include a test-source report with
declared/observed counts, and that a missing required guest marker becomes
`inconclusive` rather than accepted.

- [x] **Step 2: Document the report boundary.**

State that provider catalog entries describe test sources but do not imply
coverage; only exact declared-and-observed evidence participates in required
capability acceptance. Keep the explicit limitation that one fixture per
profile is not whole-subsystem validation.

- [x] **Step 3: Run focused and static verification.**

```bash
PYTHONPATH=src:qa:qa/verification pytest -q \
  qa/tests/test_subsystem_test_reporting.py \
  qa/tests/test_profile_runtime.py \
  qa/tests/test_profile_matrix.py \
  qa/tests/test_subsystem_providers.py
git diff --check
python3 -m compileall -q src qa
```

Expected: all focused tests and static checks pass. The existing full extractor
regression remains separately reported if it contains unrelated frozen
failures.
