from __future__ import annotations

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from trace_protocol import (  # noqa: E402
    TraceEvent,
    TraceProtocolError,
    compare_runs,
    compare_traces,
    first_divergence,
    normalize_event,
    normalize_trace,
    parse_trace_text,
)


def event(sequence: int, value: int = 1, **overrides) -> TraceEvent:
    fields = {
        "phase": "probe",
        "function": "runtime_probe",
        "kind": "read",
        "width_bits": 32,
        "address": 0x10,
        "value": value,
        "sequence": sequence,
    }
    fields.update(overrides)
    return TraceEvent(**fields)


def test_normalization_uses_manifest_value_mask_and_canonical_kind():
    normalized = normalize_event(
        {**event(0, 0x100000001).to_dict(), "kind": "R"},
        config={"value_mask": "0xffffffff"},
    )
    assert normalized.kind == "read"
    assert normalized.value == 1


def test_unmasked_values_are_not_silently_changed():
    assert normalize_event(event(0, 0x100000001)).value == 0x100000001


def test_parse_existing_serial_lines_into_one_schema():
    events = parse_trace_text("""
[rhfn] runtime_probe
[rh] R 0x10 0x00000001
[rh] W 0x14 0x00000002
[trace 2] R 0x18 = 0x00000003
""")
    assert [(item.kind, item.address, item.value, item.sequence)
            for item in events] == [
                ("read", 0x10, 1, 0),
                ("write", 0x14, 2, 1),
                ("read", 0x18, 3, 2),
            ]
    assert all(item.function == "runtime_probe" for item in events)


def test_sequence_order_is_an_invariant():
    with pytest.raises(TraceProtocolError, match="strictly increasing"):
        normalize_trace([event(2), event(1)])


@pytest.mark.parametrize(
    ("original", "candidate", "reason"),
    [([event(0)], [], "missing_event"), ([], [event(0)], "extra_event")],
)
def test_first_divergence_reports_missing_and_extra(original, candidate, reason):
    report = first_divergence(original, candidate)
    assert report is not None
    assert report.reason == reason
    assert report.index == 0


def test_first_divergence_has_prefix_and_suffix_context():
    original = [event(0), event(1, 2), event(2, 3), event(3, 4)]
    candidate = [event(0), event(1, 9), event(2, 3), event(3, 4)]
    report = first_divergence(original, candidate, context=1)
    assert report is not None
    assert report.reason == "event_mismatch"
    assert report.index == 1
    assert report.prefix == (original[0],)
    assert report.suffix_original == (original[2],)
    assert report.suffix_candidate == (candidate[2],)


def test_runtime_error_is_compared_before_events():
    result = compare_runs(
        type("Run", (), {"events": (event(0),), "return_code": 0, "error": None})(),
        type("Run", (), {"events": (event(0),), "return_code": 139, "error": "segfault"})(),
    )
    assert not result.equal
    assert result.reason == "runtime_error"
    assert result.divergence is not None
    assert result.divergence.candidate_error == "segfault"


def test_compare_traces_applies_the_same_manifest_rules_to_both_sides():
    left = [{**event(0, 0x100000001).to_dict()}]
    right = [{**event(0, 1).to_dict()}]
    assert compare_traces(left, right, config={"value_mask": "0xffffffff"}).equal
