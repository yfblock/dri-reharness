"""JSON-serializable state for the generation subgraph."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_dicts(left: dict[str, Any] | None,
                right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class GenerationState(TypedDict, total=False):
    """Generation pipeline subgraph state (all values JSON)."""
    name: str
    source: str
    outdir: str
    backend_order: list[str]
    generation_contract: dict[str, Any]
    device_spec_document: dict[str, Any]
    oracle_reports: Annotated[dict[str, Any], merge_dicts]
    gen_results: Annotated[dict[str, Any], merge_dicts]
    backend_results: Annotated[dict[str, Any], merge_dicts]
    bind_displays: Annotated[dict[str, Any], merge_dicts]
    return_code: int
    status: str
    result: dict[str, Any] | None
