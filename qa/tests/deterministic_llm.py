"""Deterministic LangChain-compatible model for offline QA.

This fixture is intentionally outside ``src``.  It exercises the bridge's
model-injection boundary without making production synthesis silently use
fabricated output when provider credentials are absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeterministicResponse:
    content: str
    response_metadata: dict[str, Any]


class DeterministicModel:
    """Replay a finite response sequence and record every prompt."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.invocations = 0

    def invoke(self, prompt: str) -> DeterministicResponse:
        if not self._responses:
            raise AssertionError("deterministic model response sequence exhausted")
        self.prompts.append(prompt)
        self.invocations += 1
        return DeterministicResponse(
            self._responses.pop(0),
            {"model": "deterministic-qa", "invocation": self.invocations},
        )


__all__ = ["DeterministicModel", "DeterministicResponse"]
