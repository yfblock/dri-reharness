"""FuncExtraction result model plus scalar-helper return summaries."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional
import clang.cindex as cx

from ast_analyzer import Func, walk_with_control, source_text
from .ops import Op


@dataclass
class FuncExtraction:
    name: str
    params: list[str] = field(default_factory=list)
    return_expr: str | None = None
    return_read_var: str | None = None
    ops: list[Op] = field(default_factory=list)
    calls: list = field(default_factory=list)   # CallSite list (for call graph)
    warnings: list[str] = field(default_factory=list)


def _path_return_expr(func: Func, tu) -> str | None:
    """Summarize branch returns as one conservative conditional value.

    The accepted shape has one final unconditional fallback and only lexical
    condition frames.  Loops, gotos, and missing fallbacks remain opaque.
    """
    sites: list[tuple[int, str, list[str]]] = []
    for cursor, control in walk_with_control(func.cursor):
        if cursor.kind != cx.CursorKind.RETURN_STMT:
            continue
        match = re.fullmatch(
            r"return\s+(.+?)\s*;?", source_text(tu, cursor).strip(), re.S)
        if not match:
            continue
        if any(frame.get("kind") != "cond" for frame in control):
            return None
        guards = [frame.get("guard", "").strip() for frame in control]
        if any(not guard for guard in guards):
            return None
        sites.append((cursor.location.offset or 0, match.group(1).strip(), guards))
    if not sites:
        return None
    if len({expr for _offset, expr, _guards in sites}) == 1:
        return sites[0][1]
    fallback = [site for site in sites if not site[2]]
    if len(fallback) != 1:
        return None
    fallback_site = fallback[0]
    if fallback_site[0] != max(site[0] for site in sites):
        return None
    value = fallback_site[1]
    branches = [site for site in sites if site is not fallback_site]
    for _offset, branch, guards in reversed(branches):
        guard = " && ".join(f"({item})" for item in guards)
        value = f"(({guard}) ? ({branch}) : ({value}))"
    return value


def _pure_return_functions(inline_cache: Optional[dict]
                           ) -> dict[str, FuncExtraction]:
    groups: dict[str, list[FuncExtraction]] = {}
    seen: set[int] = set()
    for extraction in (inline_cache or {}).values():
        if id(extraction) in seen:
            continue
        seen.add(id(extraction))
        if extraction.return_expr and not extraction.ops:
            groups.setdefault(extraction.name, []).append(extraction)
    pure = {name: values[0] for name, values in groups.items()
            if len(values) == 1}
    changed = True
    while changed:
        changed = False
        for name, extraction in list(pure.items()):
            if any(call.name not in pure
                   or not re.search(
                       rf"\b{re.escape(call.name)}\s*\(",
                       extraction.return_expr or "")
                   for call in extraction.calls):
                pure.pop(name)
                changed = True
    return pure


def _split_text_args(body: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        if char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    args.append("".join(current).strip())
    return args if args != [""] else []
