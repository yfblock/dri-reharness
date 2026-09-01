"""Serializable state carried between LangGraph nodes."""
from __future__ import annotations

from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    input: dict[str, Any]
    normalized: dict[str, Any]
    inventory: dict[str, Any]
    analysis: dict[str, Any]
    pipeline_plan: dict[str, Any]
    pipeline_result: dict[str, Any]
    status: str
    translation_status: str
    translation_eligible: bool
    error: dict[str, Any]
    failure: dict[str, Any]
    events: list[dict[str, Any]]
