from __future__ import annotations

from types import SimpleNamespace

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from subsystem_test_reporting import (  # noqa: E402
    build_subsystem_test_report,
)


def test_required_tests_need_exact_pass_evidence():
    manifest_tests = (SimpleNamespace(
        name="transaction", kind="native", provider=None, required=True),)

    report = build_subsystem_test_report(
        manifest_tests,
        [{"name": "transaction", "kind": "native", "required": True,
          "status": "pass", "success": True, "return_code": 0}],
    )

    assert report["status"] == "accepted"
    assert report["tests"][0]["kind"] == "native"
    assert report["tests"][0]["provider"] is None


def test_missing_or_unexpected_required_evidence_is_inconclusive():
    manifest_tests = (SimpleNamespace(
        name="declared", kind="tool", provider="linux-tool", required=True),)

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
    assert report["declared"]["by_provider"] == {"clock": 1, "gpio": 1}


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


def test_malformed_observed_record_is_inconclusive_without_crashing():
    declared = (SimpleNamespace(name="transaction", kind="native",
                                provider=None, required=True),)

    report = build_subsystem_test_report(declared, ["not-an-object"])

    assert report["status"] == "inconclusive"
    assert report["missing_required"] == ["transaction"]
    assert report["observed"]["total"] == 1


def test_guest_metadata_mismatch_is_inconclusive_and_auditable():
    declared = (SimpleNamespace(name="transaction", kind="tool",
                                provider="linux-tool", required=True),)

    report = build_subsystem_test_report(
        declared,
        [{"name": "transaction", "kind": "native",
          "provider": "other-tool", "required": False,
          "status": "pass", "success": True, "return_code": 0}],
    )

    assert report["status"] == "inconclusive"
    assert report["inconclusive_required"] == ["transaction"]
    assert report["metadata_mismatches"] == [{
        "name": "transaction",
        "fields": {
            "kind": {"expected": "tool", "observed": "native"},
            "provider": {"expected": "linux-tool", "observed": "other-tool"},
            "required": {"expected": True, "observed": False},
        },
    }]


def test_missing_guest_metadata_cannot_upgrade_an_optional_test_to_pass():
    declared = (SimpleNamespace(name="optional", kind="kselftest",
                                provider="linux-gpio", required=False),)

    report = build_subsystem_test_report(
        declared,
        [{"name": "optional", "status": "pass",
          "success": True, "return_code": 0}],
    )

    assert report["status"] == "inconclusive"
    assert report["metadata_mismatches"] == [{
        "name": "optional",
        "fields": {
            "kind": {"expected": "kselftest", "observed": None},
            "provider": {"expected": "linux-gpio", "observed": None},
            "required": {"expected": False, "observed": None},
        },
    }]
