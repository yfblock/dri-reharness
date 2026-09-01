"""Reconcile manifest subsystem tests with structured guest evidence."""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def _declared_row(item: Any) -> dict[str, Any]:
    name = getattr(item, "name", None)
    kind = getattr(item, "kind", "native")
    provider = getattr(item, "provider", None)
    required = getattr(item, "required", True)
    return {
        "name": name if isinstance(name, str) else "",
        "kind": kind if isinstance(kind, str) else "native",
        "provider": provider if isinstance(provider, str) else None,
        "required": required if isinstance(required, bool) else True,
    }


def _declared_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    kinds = Counter(str(row["kind"]) for row in rows)
    providers = Counter(
        str(row["provider"]) for row in rows
        if isinstance(row.get("provider"), str)
    )
    return {
        "total": len(rows),
        "required": sum(1 for row in rows if row["required"]),
        "optional": sum(1 for row in rows if not row["required"]),
        "by_kind": dict(sorted(kinds.items())),
        "by_provider": dict(sorted(providers.items())),
    }


def _observed_status(row: Mapping[str, Any]) -> str:
    if (row.get("status") == "pass" and row.get("success") is True
            and row.get("return_code") == 0):
        return "pass"
    if (row.get("status") == "fail" or row.get("success") is False
            or row.get("return_code") not in (None, 0)):
        return "failed"
    return "inconclusive"


def _metadata_mismatch(declared: Mapping[str, Any],
                       observed: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in ("kind", "provider", "required"):
        expected = declared[name]
        if name == "provider" and expected is None and name not in observed:
            continue
        actual = observed.get(name)
        if name not in observed or actual != expected:
            fields[name] = {"expected": expected, "observed": actual}
    return fields


def build_subsystem_test_report(
        declared: Sequence[Any],
        observed: Sequence[Mapping[str, Any] | Any],
        ) -> dict[str, Any]:
    """Return a JSON-compatible, fail-closed test-source reconciliation."""
    declared_rows = [_declared_row(item) for item in declared]
    observed_rows: list[dict[str, Any]] = []
    malformed_observed: list[int] = []
    for index, item in enumerate(observed):
        if isinstance(item, Mapping):
            observed_rows.append(dict(item))
        else:
            malformed_observed.append(index)

    declared_names = [str(row["name"]) for row in declared_rows]
    observed_names = [row.get("name") for row in observed_rows]
    duplicate_declared = sorted({
        name for name in declared_names if declared_names.count(name) > 1
    })
    duplicate_observed = sorted({
        name for name in observed_names
        if isinstance(name, str) and observed_names.count(name) > 1
    })

    observed_by_name: dict[str, dict[str, Any]] = {}
    for row in observed_rows:
        name = row.get("name")
        if isinstance(name, str) and name not in observed_by_name:
            observed_by_name[name] = row

    tests: list[dict[str, Any]] = []
    missing_required: list[str] = []
    failed_required: list[str] = []
    inconclusive_required: list[str] = []
    optional_failures: list[str] = []
    metadata_mismatches: list[dict[str, Any]] = []
    for declared_row in declared_rows:
        name = declared_row["name"]
        observed_row = observed_by_name.get(name)
        result = {**declared_row, "observed": observed_row}
        if observed_row is None:
            result["status"] = "missing"
            if declared_row["required"]:
                missing_required.append(name)
        else:
            status = _observed_status(observed_row)
            mismatch = _metadata_mismatch(declared_row, observed_row)
            if mismatch:
                metadata_mismatches.append({
                    "name": name,
                    "fields": mismatch,
                })
                if status == "pass":
                    status = "inconclusive"
            result["status"] = status
            if declared_row["required"]:
                if status == "failed":
                    failed_required.append(name)
                elif status != "pass":
                    inconclusive_required.append(name)
            elif status == "failed":
                optional_failures.append(name)
        tests.append(result)

    observed_named = {
        name for name in observed_names if isinstance(name, str)
    }
    unexpected_observed = sorted(observed_named - set(declared_names))
    evidence_gap = bool(
        missing_required or inconclusive_required or unexpected_observed
        or duplicate_declared or duplicate_observed or malformed_observed
        or metadata_mismatches
    )
    status = ("failed" if failed_required else
              "inconclusive" if evidence_gap else "accepted")

    return {
        "status": status,
        "declared": _declared_counts(declared_rows),
        "observed": {
            "total": len(observed_rows) + len(malformed_observed),
            "names": sorted(observed_named),
        },
        "tests": tests,
        "missing_required": sorted(missing_required),
        "failed_required": sorted(failed_required),
        "inconclusive_required": sorted(inconclusive_required),
        "unexpected_observed": unexpected_observed,
        "optional_failures": sorted(optional_failures),
        "duplicate_declared": duplicate_declared,
        "duplicate_observed": duplicate_observed,
        "malformed_observed": malformed_observed,
        "metadata_mismatches": metadata_mismatches,
    }


__all__ = ["build_subsystem_test_report"]


import re

_SUBSYSTEM_NAME_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_NAME=([^\n]*)")
_SUBSYSTEM_KIND_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_KIND=([^\n]*)")
_SUBSYSTEM_PROVIDER_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_PROVIDER=([^\n]*)")
_SUBSYSTEM_REQUIRED_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_REQUIRED=([01])")
_SUBSYSTEM_RC_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_RC=(-?\d+)")
_SUBSYSTEM_SUCCESS_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_SUCCESS=([01])")
_SUBSYSTEM_STATUS_RE = re.compile(
    r"REHARNESS_SUBSYSTEM_TEST_(\d+)_STATUS=([^\n]+)")
_COVERAGE_RE = re.compile(
    r"REHARNESS_COVERAGE_([A-Za-z0-9_.:-]+)=(pass|fail|inconclusive)")
_INSMOD_RC_RE = re.compile(
    r"REHARNESS_(REGISTRAR|DRIVER)_INSMOD_RC=(-?\d+)")
_DRIVER_RMMOD_RC_RE = re.compile(
    r"REHARNESS_DRIVER_RMMOD_RC=(-?\d+)")
_FIXTURE_RMMOD_RC_RE = re.compile(
    r"REHARNESS_RUNTIME_FIXTURE_MODULE_(\d+)_RMMOD_RC=(-?\d+)")
_FIXTURE_INSMOD_RC_RE = re.compile(
    r"REHARNESS_RUNTIME_FIXTURE_MODULE_(\d+)_INSMOD_RC=(-?\d+)")
_KERNEL_MODULE_AVAILABLE_RE = re.compile(
    r"REHARNESS_KERNEL_MODULE_(\d+)_AVAILABLE=([01])")
_KERNEL_MODULE_INSMOD_RE = re.compile(
    r"REHARNESS_KERNEL_MODULE_(\d+)_INSMOD_RC=(-?\d+)")
_DRIVER_PROBE_BOUND_RE = re.compile(
    r"REHARNESS_DRIVER_PROBE_BOUND=([01])")
_OOPS_RE = re.compile(
    r"(?:Oops:|\bBUG:|Unable to handle|general protection|"
    r"Kernel panic - not syncing)", re.IGNORECASE)
_KERNEL_WARNING_RE = re.compile(
    r"WARNING:\s+(?:CPU:\s+\d+\s+PID:\s+\d+\s+at\s+|"
    r"[A-Za-z0-9_.-]+/[^\s:]+:\d+\s+at\s+)", re.IGNORECASE)
_KTAP_NOT_OK_RE = re.compile(
    r"(?:^|\s)not ok\s+[0-9]+(?:\s|$)", re.IGNORECASE)
_SUBSYSTEM_TEST_SECTION_RE = re.compile(
    r"=== Linux subsystem test (\d+) ===(?P<body>.*?)(?="
    r"=== Linux subsystem test \d+ ===|=== rmmod |=== QEMU_RUN_DONE ===|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_KSELFTEST_FAILURE_MARKER_RE = re.compile(
    r"^\s*(?:FAIL|ERROR):", re.IGNORECASE | re.MULTILINE)


def _subsystem_test_failure_markers(output: str) -> set[int]:
    """Return kselftest sections with standard failure markers.

    Some upstream shell selftests print FAIL: ... but still return zero.
    Limit this fallback to the section emitted for one manifest test so a
    kernel log line cannot fail an unrelated test entry.
    """
    failed: set[int] = set()
    for match in _SUBSYSTEM_TEST_SECTION_RE.finditer(output or ""):
        if _KSELFTEST_FAILURE_MARKER_RE.search(match.group("body")):
            failed.add(int(match.group(1)))
    return failed




def parse_subsystem_test_results(output: str) -> list[dict[str, Any]]:
    """Extract the bounded per-test result protocol emitted by the guest."""
    text = output or ""
    names = {
        int(match.group(1)): match.group(2)
        for match in _SUBSYSTEM_NAME_RE.finditer(text)
    }
    kinds = {
        int(match.group(1)): match.group(2).strip().lower()
        for match in _SUBSYSTEM_KIND_RE.finditer(text)
    }
    providers = {
        int(match.group(1)): match.group(2).strip()
        for match in _SUBSYSTEM_PROVIDER_RE.finditer(text)
    }
    required = {
        int(match.group(1)): match.group(2) == "1"
        for match in _SUBSYSTEM_REQUIRED_RE.finditer(text)
    }
    success = {
        int(match.group(1)): match.group(2) == "1"
        for match in _SUBSYSTEM_SUCCESS_RE.finditer(text)
    }
    statuses = {
        int(match.group(1)): match.group(2).strip().lower()
        for match in _SUBSYSTEM_STATUS_RE.finditer(text)
    }
    results: dict[int, dict[str, Any]] = {}
    for match in _SUBSYSTEM_RC_RE.finditer(text):
        index = int(match.group(1))
        result = results.setdefault(index, {
            "index": index,
            "name": names.get(index, f"test-{index}"),
            "return_code": int(match.group(2)),
        })
        result["name"] = names.get(index, result["name"])
        result["return_code"] = int(match.group(2))
        if index in kinds:
            result["kind"] = kinds[index]
        if index in providers and providers[index]:
            result["provider"] = providers[index]
        if index in required:
            result["required"] = required[index]
        if index in success:
            result["success"] = success[index]
        if index in statuses:
            result["status"] = statuses[index]
    failure_markers = _subsystem_test_failure_markers(text)
    for index, result in results.items():
        if result.get("kind") == "kselftest" and index in failure_markers:
            result["failure_marker"] = True
            result["return_code"] = 1
            result["status"] = "fail"
    return [results[index] for index in sorted(results)]
