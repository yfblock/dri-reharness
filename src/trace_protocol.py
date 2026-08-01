"""Data-driven protocol for comparing original and candidate runtime traces.

The protocol deliberately contains no knowledge of a particular driver or
device.  A trace is an ordered sequence of :class:`TraceEvent` records.  The
manifest may declare a value mask, but values are never masked implicitly.
Legacy serial output (``[rh]`` and ``[trace]`` lines) is accepted as an input
adapter and is converted to the same normalized representation.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


TRACE_FIELDS = (
    "phase",
    "function",
    "kind",
    "width_bits",
    "address",
    "value",
    "sequence",
    "source_op_id",
)
_KINDS = {
    "r": "read",
    "read": "read",
    "w": "write",
    "write": "write",
    "u": "update",
    "update": "update",
    "rmw": "read_modify_write",
    "read_modify_write": "read_modify_write",
}


class TraceProtocolError(ValueError):
    """Raised when input cannot be represented by the trace schema."""


def _integer(value: Any, field: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise TraceProtocolError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise TraceProtocolError(f"{field} must be an integer") from exc
    raise TraceProtocolError(f"{field} must be an integer")


def _mask(value: Any) -> int:
    parsed = _integer(value, "value_mask")
    assert parsed is not None
    if parsed < 0:
        raise TraceProtocolError("value_mask must be non-negative")
    return parsed


@dataclass(frozen=True)
class TraceEvent:
    """One normalized register transaction.

    ``address`` is intentionally an integer offset or a manifest-defined
    symbolic string.  The protocol does not resolve addresses or attach
    device-specific semantics to them.
    """

    phase: str
    function: str
    kind: str
    width_bits: int
    address: int | str
    value: int | None
    sequence: int
    source_op_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, str) or not self.phase:
            raise TraceProtocolError("phase must be a non-empty string")
        if not isinstance(self.function, str) or not self.function:
            raise TraceProtocolError("function must be a non-empty string")
        normalized_kind = _KINDS.get(str(self.kind).strip().lower())
        if normalized_kind is None:
            raise TraceProtocolError(f"unknown trace kind: {self.kind}")
        object.__setattr__(self, "kind", normalized_kind)
        width = _integer(self.width_bits, "width_bits")
        sequence = _integer(self.sequence, "sequence")
        if width is None or width <= 0 or width % 8:
            raise TraceProtocolError("width_bits must be a positive multiple of 8")
        if sequence is None or sequence < 0:
            raise TraceProtocolError("sequence must be a non-negative integer")
        if not isinstance(self.address, (int, str)) or isinstance(self.address, bool):
            raise TraceProtocolError("address must be an integer or string")
        if isinstance(self.address, str) and not self.address:
            raise TraceProtocolError("address string must not be empty")
        if self.value is not None:
            value = _integer(self.value, "value")
            assert value is not None
            if value < 0:
                raise TraceProtocolError("value must be non-negative")
            object.__setattr__(self, "value", value)
        object.__setattr__(self, "width_bits", width)
        object.__setattr__(self, "sequence", sequence)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceEvent":
        if not isinstance(data, Mapping):
            raise TraceProtocolError("trace event must be an object")
        required = set(TRACE_FIELDS) - {"source_op_id"}
        missing = sorted(field for field in required if field not in data)
        if missing:
            raise TraceProtocolError("trace event missing field(s): " + ", ".join(missing))
        unknown = sorted(set(data) - set(TRACE_FIELDS))
        if unknown:
            raise TraceProtocolError("trace event has unknown field(s): " + ", ".join(unknown))
        return cls(**{field: data.get(field) for field in TRACE_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceRun:
    """Events and process outcome captured for one runtime execution."""

    events: tuple[TraceEvent, ...]
    return_code: int = 0
    error: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceRun":
        if not isinstance(data, Mapping):
            raise TraceProtocolError("trace run must be an object")
        events = normalize_trace(data.get("events", []), config=data.get("trace", data))
        return cls(
            events=tuple(events),
            return_code=_integer(data.get("return_code", 0), "return_code") or 0,
            error=None if data.get("error") is None else str(data["error"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "return_code": self.return_code,
            "error": self.error,
        }


@dataclass(frozen=True)
class TraceDivergence:
    """Structured first difference with context for a repair prompt."""

    reason: str
    index: int
    original: TraceEvent | None
    candidate: TraceEvent | None
    prefix: tuple[TraceEvent, ...]
    suffix_original: tuple[TraceEvent, ...] = ()
    suffix_candidate: tuple[TraceEvent, ...] = ()
    original_error: str | None = None
    candidate_error: str | None = None
    original_return_code: int = 0
    candidate_return_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "index": self.index,
            "original": self.original.to_dict() if self.original else None,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "prefix": [item.to_dict() for item in self.prefix],
            "suffix_original": [item.to_dict() for item in self.suffix_original],
            "suffix_candidate": [item.to_dict() for item in self.suffix_candidate],
            "original_error": self.original_error,
            "candidate_error": self.candidate_error,
            "original_return_code": self.original_return_code,
            "candidate_return_code": self.candidate_return_code,
        }


@dataclass(frozen=True)
class TraceComparison:
    equal: bool
    divergence: TraceDivergence | None

    @property
    def reason(self) -> str | None:
        return self.divergence.reason if self.divergence else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "equal": self.equal,
            "reason": self.reason,
            "divergence": self.divergence.to_dict() if self.divergence else None,
        }


def _config_mask(config: Mapping[str, Any] | None) -> int | None:
    if not config:
        return None
    value_mask = config.get("value_mask")
    if value_mask is None:
        masks = config.get("masks")
        if isinstance(masks, Mapping):
            value_mask = masks.get("value")
    return None if value_mask is None else _mask(value_mask)


def normalize_event(event: TraceEvent | Mapping[str, Any], *, value_mask: Any = None,
                    config: Mapping[str, Any] | None = None) -> TraceEvent:
    """Convert one event to the canonical schema, applying only declared masks."""
    if not isinstance(event, TraceEvent):
        event = TraceEvent.from_dict(event)
    mask = _mask(value_mask) if value_mask is not None else _config_mask(config)
    value = event.value if mask is None or event.value is None else event.value & mask
    return TraceEvent(
        phase=event.phase,
        function=event.function,
        kind=event.kind,
        width_bits=event.width_bits,
        address=event.address,
        value=value,
        sequence=event.sequence,
        source_op_id=event.source_op_id,
    )


def normalize_trace(events: Iterable[TraceEvent | Mapping[str, Any]], *,
                    value_mask: Any = None,
                    config: Mapping[str, Any] | None = None,
                    require_order: bool = True) -> list[TraceEvent]:
    """Normalize events and reject duplicate/backward sequence numbers."""
    normalized = [normalize_event(item, value_mask=value_mask, config=config)
                  for item in events]
    if require_order:
        for previous, current in zip(normalized, normalized[1:]):
            if current.sequence <= previous.sequence:
                raise TraceProtocolError(
                    "trace sequence must be strictly increasing "
                    f"({previous.sequence} then {current.sequence})")
    return normalized


def first_divergence(original: Sequence[TraceEvent], candidate: Sequence[TraceEvent], *,
                     context: int = 3) -> TraceDivergence | None:
    """Return the first event mismatch, including bounded prefix and suffix."""
    if context < 0:
        raise ValueError("context must be non-negative")
    limit = min(len(original), len(candidate))
    index = next((i for i in range(limit) if original[i] != candidate[i]), limit)
    if index == len(original) and index == len(candidate):
        return None
    if index == limit:
        reason = "missing_event" if len(original) > len(candidate) else "extra_event"
    else:
        reason = "event_mismatch"
    start = max(0, index - context)
    return TraceDivergence(
        reason=reason,
        index=index,
        original=original[index] if index < len(original) else None,
        candidate=candidate[index] if index < len(candidate) else None,
        prefix=tuple(original[start:index]),
        suffix_original=tuple(original[index + 1:index + 1 + context]),
        suffix_candidate=tuple(candidate[index + 1:index + 1 + context]),
    )


def compare_runs(original: TraceRun, candidate: TraceRun, *, context: int = 3) -> TraceComparison:
    """Compare execution outcome first, then the normalized event sequence."""
    # A runtime error is never an accepted execution, even when both sides
    # happen to fail in the same way.  This keeps the experiment fail-closed;
    # adapters can classify a baseline failure separately as infrastructure.
    if (original.return_code != 0 or candidate.return_code != 0 or
            original.return_code != candidate.return_code or
            original.error is not None or candidate.error is not None or
            original.error != candidate.error):
        divergence = TraceDivergence(
            reason="runtime_error",
            index=0,
            original=original.events[0] if original.events else None,
            candidate=candidate.events[0] if candidate.events else None,
            prefix=(),
            original_error=original.error,
            candidate_error=candidate.error,
            original_return_code=original.return_code,
            candidate_return_code=candidate.return_code,
        )
        return TraceComparison(False, divergence)
    divergence = first_divergence(original.events, candidate.events, context=context)
    if divergence is None:
        return TraceComparison(True, None)
    return TraceComparison(False, divergence)


def compare_traces(original: Iterable[TraceEvent | Mapping[str, Any]],
                   candidate: Iterable[TraceEvent | Mapping[str, Any]], *,
                   config: Mapping[str, Any] | None = None,
                   context: int = 3) -> TraceComparison:
    """Normalize and compare two event sequences with a shared manifest config."""
    left = normalize_trace(original, config=config)
    right = normalize_trace(candidate, config=config)
    return compare_runs(TraceRun(tuple(left)), TraceRun(tuple(right)), context=context)


_FUNCTION_RE = re.compile(r"\[rhfn\]\s+([A-Za-z_]\w*)")
_RH_RE = re.compile(r"\[rh\]\s+(R|W|U|RMW)\s+([^\s]+)(?:\s+([^\s]+))?")
_TRACE_RE = re.compile(
    r"\[trace\s+(\d+)\]\s+(R|W|U|RMW)\s+([^\s]+)(?:\s*=\s*([^\s]+))?")


def parse_trace_text(text: str, *, phase: str = "runtime", width_bits: int = 32,
                     config: Mapping[str, Any] | None = None) -> list[TraceEvent]:
    """Parse structured JSON lines and existing serial trace lines."""
    events: list[TraceEvent] = []
    function = "runtime"
    for line in text.splitlines():
        function_match = _FUNCTION_RE.search(line)
        if function_match:
            function = function_match.group(1)
            continue
        event: TraceEvent | None = None
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, Mapping) and "kind" in value and "sequence" in value:
                event = TraceEvent.from_dict(value)
        if event is None:
            match = _RH_RE.search(line)
            if match:
                kind, raw_address, raw_value = match.groups()
                event = TraceEvent(
                    phase=phase, function=function, kind=kind,
                    width_bits=width_bits, address=_integer(raw_address, "address"),
                    value=None if raw_value is None else _integer(raw_value, "value"),
                    sequence=len(events),
                )
        if event is None:
            match = _TRACE_RE.search(line)
            if match:
                raw_sequence, kind, raw_address, raw_value = match.groups()
                event = TraceEvent(
                    phase=phase, function=function, kind=kind,
                    width_bits=width_bits, address=_integer(raw_address, "address"),
                    value=None if raw_value is None else _integer(raw_value, "value"),
                    sequence=int(raw_sequence),
                )
        if event is not None:
            events.append(normalize_event(event, config=config))
    return normalize_trace(events, config=config)


def load_trace(path: str | Path, *, config: Mapping[str, Any] | None = None) -> TraceRun:
    """Load a JSON trace run or a serial text log."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return TraceRun(tuple(parse_trace_text(text, config=config)))
    if isinstance(document, Mapping):
        run_config = document.get("trace", config)
        return TraceRun.from_dict({**document, "trace": run_config or {}})
    if isinstance(document, list):
        return TraceRun(tuple(normalize_trace(document, config=config)))
    raise TraceProtocolError("trace document must be an object or array")


__all__ = [
    "TRACE_FIELDS", "TraceProtocolError", "TraceEvent", "TraceRun",
    "TraceDivergence", "TraceComparison", "normalize_event", "normalize_trace",
    "parse_trace_text", "load_trace", "first_divergence", "compare_runs",
    "compare_traces",
]
