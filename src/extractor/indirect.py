"""Conservative resolution of source-local function-pointer table calls."""
from __future__ import annotations

import re


def _norm(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    return text


def infer_indirect_targets(source_text: str, known_functions: set[str]
                           ) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    initializer = re.compile(
        r"\b(?:static\s+)?(?:const\s+)?struct\s+[A-Za-z_]\w*\s+"
        r"([A-Za-z_]\w*)\s*=\s*\{(?P<body>.*?)\}\s*;", re.S)
    for match in initializer.finditer(source_text):
        table = match.group(1)
        for field, function in re.findall(
                r"\.([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)",
                match.group("body")):
            if function not in known_functions:
                continue
            for key in (f"{table}.{field}", f"{table}->{field}", field):
                candidates.setdefault(key, set()).add(function)
    for root, field, function in re.findall(
            r"\b([A-Za-z_]\w*)\s*(?:->|\.)\s*([A-Za-z_]\w*)\s*=\s*"
            r"&?\s*([A-Za-z_]\w*)\s*;", source_text):
        if function not in known_functions:
            continue
        for key in (f"{root}.{field}", f"{root}->{field}", field):
            candidates.setdefault(key, set()).add(function)
    return {_norm(key): next(iter(values)) for key, values in candidates.items()
            if len(values) == 1}


def resolve_indirect_call(call, targets: dict[str, str]) -> str | None:
    callee = _norm(getattr(call, "callee_text", ""))
    if callee in targets:
        return targets[callee]
    field = re.split(r"->|\.", callee)[-1] if callee else call.name
    return targets.get(field)
