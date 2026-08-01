from __future__ import annotations

import json

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from experiment_protocol import (  # noqa: E402
    FailureClass,
    Feedback,
    StageRecord,
    TraceEvent,
    first_divergence,
    normalize_trace,
)


def _event(sequence: int, value: int = 1, **kwargs) -> TraceEvent:
    return TraceEvent(
        phase="probe", function="driver_probe", kind="read", width_bits=32,
        address=0x10, value=value, sequence=sequence, **kwargs,
    )


def test_stage_record_round_trip_and_feedback_classification():
    record = StageRecord(
        stage="compile", iteration=2, status="failed",
        manifest_digest="a" * 64, payload={"exit_code": 1},
    )
    restored = StageRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert restored == record
    feedback = Feedback.from_failure(FailureClass.COMPILE, "compiler error", {"stderr": "bad"})
    assert feedback.failure_class is FailureClass.COMPILE
    assert feedback.retryable is True
    assert Feedback.from_failure(FailureClass.EXTRACTION, "bad input", {}).retryable is False


def test_trace_event_round_trip_and_normalization_masks_values():
    event = _event(0, 0x100000001, source_op_id="op-1")
    restored = TraceEvent.from_dict(event.to_dict())
    assert restored == event
    normalized = normalize_trace([event], value_mask=0xffffffff)
    assert normalized[0].value == 1


def test_trace_event_rejects_malformed_fields():
    with pytest.raises(ValueError, match="width_bits"):
        TraceEvent.from_dict({**_event(0).to_dict(), "width_bits": 7})
    with pytest.raises(ValueError, match="sequence"):
        TraceEvent.from_dict({**_event(0).to_dict(), "sequence": -1})
    with pytest.raises(ValueError, match="kind"):
        TraceEvent.from_dict({**_event(0).to_dict(), "kind": "wat"})


def test_first_divergence_reports_mismatch_and_context_prefix():
    original = [_event(0, 1), _event(1, 2), _event(2, 3)]
    candidate = [_event(0, 1), _event(1, 9), _event(2, 3)]
    report = first_divergence(original, candidate, context=1)
    assert report.index == 1
    assert report.reason == "event_mismatch"
    assert report.original == original[1]
    assert report.candidate == candidate[1]
    assert report.prefix == (original[0],)


@pytest.mark.parametrize("original,candidate,reason", [
    ([_event(0)], [], "missing_event"),
    ([], [_event(0)], "extra_event"),
])
def test_first_divergence_reports_missing_and_extra_events(original, candidate, reason):
    report = first_divergence(original, candidate)
    assert report.reason == reason


def test_first_divergence_returns_none_when_traces_match():
    assert first_divergence([_event(0)], [_event(0)]) is None
