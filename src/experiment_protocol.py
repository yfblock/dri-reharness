"""Structured records exchanged by the data-driven experiment runner."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence


class FailureClass(str, Enum):
    EXTRACTION = "extraction"
    CONTRACT = "contract"
    COMPILE = "compile"
    RUNTIME = "runtime"
    TRACE = "trace"
    INFRASTRUCTURE = "infrastructure"


_STAGES = {"extract", "synthesize", "compile", "baseline", "candidate", "compare", "repair", "runtime", "trace"}
_STATUSES = {"pending", "running", "passed", "failed", "skipped"}


def _string(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _check_unknown(document: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(document) - allowed)
    if extra:
        raise ValueError(f"{where} contains unknown field(s): {', '.join(extra)}")


@dataclass(frozen=True)
class StageRecord:
    stage: str
    iteration: int
    status: str
    manifest_digest: str | None = None
    evidence_digest: str | None = None
    payload: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
            raise ValueError(f"unknown stage: {self.stage}")
        _integer(self.iteration, "iteration", 1)
        if self.status not in _STATUSES:
            raise ValueError(f"unknown stage status: {self.status}")
        for field in ("manifest_digest", "evidence_digest"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or len(value) != 64
                                      or any(char not in "0123456789abcdefABCDEF" for char in value)):
                raise ValueError(f"{field} must be a SHA-256 digest")
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"stage": self.stage, "iteration": self.iteration, "status": self.status}
        if self.manifest_digest is not None:
            result["manifest_digest"] = self.manifest_digest
        if self.evidence_digest is not None:
            result["evidence_digest"] = self.evidence_digest
        if self.payload is not None:
            result["payload"] = dict(self.payload)
        return result

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "StageRecord":
        _check_unknown(document, {"stage", "iteration", "status", "manifest_digest", "evidence_digest", "payload"}, "stage record")
        required = {"stage", "iteration", "status"}
        missing = required - set(document)
        if missing:
            raise ValueError(f"stage record missing required field(s): {', '.join(sorted(missing))}")
        return cls(**dict(document))


@dataclass(frozen=True)
class Feedback:
    failure_class: FailureClass
    message: str
    details: Mapping[str, Any]
    retryable: bool | None = None
    stage: str | None = None
    iteration: int | None = None

    def __post_init__(self) -> None:
        kind = self.failure_class if isinstance(self.failure_class, FailureClass) else FailureClass(self.failure_class)
        object.__setattr__(self, "failure_class", kind)
        _string(self.message, "message")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be an object")
        if self.retryable is None:
            object.__setattr__(self, "retryable", kind in {FailureClass.COMPILE, FailureClass.RUNTIME, FailureClass.TRACE})
        elif not isinstance(self.retryable, bool):
            raise ValueError("retryable must be boolean")
        if self.iteration is not None:
            _integer(self.iteration, "iteration", 1)

    @classmethod
    def from_failure(cls, failure_class: FailureClass | str, message: str,
                     details: Mapping[str, Any] | None = None, *, stage: str | None = None,
                     iteration: int | None = None) -> "Feedback":
        kind = failure_class if isinstance(failure_class, FailureClass) else FailureClass(failure_class)
        return cls(kind, _string(message, "message"), dict(details or {}), None, stage, iteration)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "failure_class": self.failure_class.value,
            "message": self.message,
            "details": dict(self.details),
            "retryable": self.retryable,
        }
        if self.stage is not None:
            result["stage"] = self.stage
        if self.iteration is not None:
            result["iteration"] = self.iteration
        return result

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "Feedback":
        _check_unknown(document, {"failure_class", "message", "details", "retryable", "stage", "iteration"}, "feedback")
        for field in ("failure_class", "message", "details", "retryable"):
            if field not in document:
                raise ValueError(f"feedback missing required field: {field}")
        kind = FailureClass(document["failure_class"])
        details = document["details"]
        if not isinstance(details, Mapping):
            raise ValueError("feedback.details must be an object")
        if not isinstance(document["retryable"], bool):
            raise ValueError("feedback.retryable must be boolean")
        return cls(kind, _string(document["message"], "message"), dict(details), document["retryable"],
                   document.get("stage"), document.get("iteration"))


@dataclass(frozen=True)
class TraceEvent:
    phase: str
    function: str
    kind: str
    width_bits: int
    address: int
    value: int
    sequence: int
    source_op_id: str | None = None

    def __post_init__(self) -> None:
        _string(self.phase, "phase")
        _string(self.function, "function")
        if self.kind.lower() not in {
            "read", "write", "rmw", "readmodifywrite", "read_modify_write", "r", "w", "return", "error",
        }:
            raise ValueError(f"unknown trace kind: {self.kind}")
        width = _integer(self.width_bits, "width_bits", 1)
        if width % 8:
            raise ValueError("width_bits must be a multiple of 8")
        _integer(self.address, "address", 0)
        _integer(self.value, "value", 0)
        _integer(self.sequence, "sequence", 0)
        if self.source_op_id is not None:
            _string(self.source_op_id, "source_op_id")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "phase": self.phase, "function": self.function, "kind": self.kind,
            "width_bits": self.width_bits, "address": self.address,
            "value": self.value, "sequence": self.sequence,
        }
        if self.source_op_id is not None:
            result["source_op_id"] = self.source_op_id
        return result

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "TraceEvent":
        _check_unknown(document, {"phase", "function", "kind", "width_bits", "address", "value", "sequence", "source_op_id"}, "trace event")
        required = {"phase", "function", "kind", "width_bits", "address", "value", "sequence"}
        missing = required - set(document)
        if missing:
            raise ValueError(f"trace event missing required field(s): {', '.join(sorted(missing))}")
        return cls(**dict(document))


@dataclass(frozen=True)
class TraceDivergence:
    index: int
    reason: str
    original: TraceEvent | None
    candidate: TraceEvent | None
    prefix: tuple[TraceEvent, ...]
    suffix: tuple[TraceEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "reason": self.reason,
            "original": None if self.original is None else self.original.to_dict(),
            "candidate": None if self.candidate is None else self.candidate.to_dict(),
            "prefix": [event.to_dict() for event in self.prefix],
            "suffix": [event.to_dict() for event in self.suffix],
        }


def normalize_trace(events: Iterable[TraceEvent | Mapping[str, Any]], *, value_mask: int | None = None,
                    address_mask: int | None = None, function_normalizer: Callable[[str], str] | None = None
                    ) -> tuple[TraceEvent, ...]:
    """Normalize raw events into the canonical comparison representation."""
    if value_mask is not None and (isinstance(value_mask, bool) or value_mask < 0):
        raise ValueError("value_mask must be non-negative")
    if address_mask is not None and (isinstance(address_mask, bool) or address_mask < 0):
        raise ValueError("address_mask must be non-negative")
    normalized: list[TraceEvent] = []
    for item in events:
        event = item if isinstance(item, TraceEvent) else TraceEvent.from_dict(item)
        normalized.append(TraceEvent(
            phase=event.phase,
            function=function_normalizer(event.function) if function_normalizer else event.function,
            kind=event.kind.lower(), width_bits=event.width_bits,
            address=event.address if address_mask is None else event.address & address_mask,
            value=event.value if value_mask is None else event.value & value_mask,
            sequence=event.sequence, source_op_id=event.source_op_id,
        ))
    return tuple(normalized)


def first_divergence(original: Sequence[TraceEvent | Mapping[str, Any]],
                     candidate: Sequence[TraceEvent | Mapping[str, Any]], *, context: int = 2
                     ) -> TraceDivergence | None:
    """Return the first mismatch, including a bounded matching prefix."""
    if isinstance(context, bool) or context < 0:
        raise ValueError("context must be non-negative")
    left = tuple(item if isinstance(item, TraceEvent) else TraceEvent.from_dict(item) for item in original)
    right = tuple(item if isinstance(item, TraceEvent) else TraceEvent.from_dict(item) for item in candidate)
    limit = min(len(left), len(right))
    index = next((position for position in range(limit) if left[position] != right[position]), limit)
    if index == len(left) == len(right):
        return None
    if index == len(right):
        reason = "missing_event"
    elif index == len(left):
        reason = "extra_event"
    else:
        reason = "event_mismatch"
    start = max(0, index - context)
    end = min(max(len(left), len(right)), index + context + 1)
    suffix = tuple(left[index + 1:end]) if index < len(left) else tuple()
    return TraceDivergence(index, reason, left[index] if index < len(left) else None,
                           right[index] if index < len(right) else None,
                           tuple(left[start:index]), suffix)


def compare_traces(original: Sequence[TraceEvent | Mapping[str, Any]],
                   candidate: Sequence[TraceEvent | Mapping[str, Any]], *, value_mask: int | None = None,
                   address_mask: int | None = None,
                   function_normalizer: Callable[[str], str] | None = None,
                   context: int = 2) -> TraceDivergence | None:
    """Normalize both traces and return their first divergence."""
    return first_divergence(
        normalize_trace(original, value_mask=value_mask, address_mask=address_mask,
                        function_normalizer=function_normalizer),
        normalize_trace(candidate, value_mask=value_mask, address_mask=address_mask,
                        function_normalizer=function_normalizer),
        context=context,
    )


def classify_failure(stage: str, *, infrastructure: bool = False) -> FailureClass:
    if infrastructure:
        return FailureClass.INFRASTRUCTURE
    try:
        return FailureClass(stage)
    except ValueError:
        return FailureClass.CONTRACT


# Friendly aliases used by adapters and callers that prefer descriptive names.
StructuredFeedback = Feedback
TraceMismatch = TraceDivergence
StageResult = StageRecord
