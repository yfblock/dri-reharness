"""Side table mapping slim RIS anchors back to source locations.

RIS 0.4.0 removes inline ``file:line`` annotations from the rendered
text so the language stays small for LLM consumption; locations remain
first-class data in this table instead.  Consumers that need provenance
(a human auditing a module, a repair round that wants to quote the
original statement) resolve anchors on demand — nothing is lost, it is
just no longer shipped inside the module text by default.
"""
from __future__ import annotations

from .formal import walk_leaf_ops


def _anchor_entry(source, line: int, column: int) -> dict | None:
    if not isinstance(source, str) or not source:
        return None
    return {
        "source": source.rsplit("/", 1)[-1],
        "source_path": source,
        "line": int(line or 0),
        "column": int(column or 0),
    }


def build_source_map(formal: dict) -> dict:
    """Index every location-bearing RIS node by a stable anchor key.

    Keys: op ids (``op_42``), ``call:<module>:<index>`` and
    ``ext:<module>:<index>`` for the module's Call/ExternalCall nodes
    (index = position in the module's list, stable for a given build).
    """
    anchors: dict[str, dict] = {}
    for module in formal.get("modules") or []:
        name = module.get("name", "?")
        for op in walk_leaf_ops(module.get("ops") or []):
            body = next((value for value in op.values()
                         if isinstance(value, dict)), None)
            if not body:
                continue
            op_id = body.get("op_id")
            evidence = body.get("evidence") or {}
            entry = _anchor_entry(evidence.get("source"),
                                  evidence.get("line", 0),
                                  evidence.get("column", 0))
            if isinstance(op_id, str) and entry:
                anchors[op_id] = entry
        for index, call in enumerate(module.get("calls") or []):
            callsite = call.get("callsite") or {}
            entry = _anchor_entry(callsite.get("source_path"),
                                  callsite.get("line", 0),
                                  callsite.get("column", 0))
            if entry:
                anchors[f"call:{name}:{index}"] = entry
        for index, external in enumerate(module.get("external_calls") or []):
            callsite = external.get("callsite") or {}
            entry = _anchor_entry(callsite.get("source_path"),
                                  callsite.get("line", 0),
                                  callsite.get("column", 0))
            if entry:
                anchors[f"ext:{name}:{index}"] = entry
    return {"schema": 1, "anchors": anchors}


def lookup_source(source_map: dict | None,
                  anchors: list[str]) -> dict[str, str]:
    """Resolve anchors to ``file:line`` strings for LLM pass-through.

    Unknown anchors are simply absent from the result — callers render
    what resolved and never fail on a stale key.
    """
    table = (source_map or {}).get("anchors") or {}
    out: dict[str, str] = {}
    for anchor in anchors:
        entry = table.get(anchor)
        if entry:
            out[anchor] = f"{entry.get('source')}:{entry.get('line', 0)}"
    return out


__all__ = ["build_source_map", "lookup_source"]
