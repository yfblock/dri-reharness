"""Source-analysis helpers shared by verification oracles.

Originally part of the retired rules generator; only ``source_function``
survives as a consumer-facing contract (paper evidence oracles extract
named function bodies from C sources).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def source_function(source: str, name: str) -> dict[str, Any] | None:
    """Extract a named file-scope function definition from C source.

    Returns ``{"name", "start_line", "end_line", "text"}`` or ``None``.
    Handles multi-line signatures; matches the identifier exactly (a
    following ``(`` with no ``;`` before the body).
    """
    pattern = re.compile(
        r"^[ \t]*(?:[A-Za-z_][\w \t\*]*?[ \t\*])?"      # return type
        + re.escape(name) + r"[ \t]*\(",                  # exact name + paren
        re.M)
    lines = source.splitlines(keepends=True)
    for match in pattern.finditer(source):
        # Discard calls/declarations: scan forward for the opening brace
        # without hitting a ';' first.
        depth = 0
        start_index = source.count("\n", 0, match.start())
        i = match.end() - 1
        while i < len(source):
            ch = source[i]
            if ch == ";":
                break
            if ch == "{":
                depth = 1
                i += 1
                break
            i += 1
        else:
            continue
        if depth != 1:
            continue
        # Walk the body to the matching close brace.
        in_string = None
        while i < len(source) and depth > 0:
            ch = source[i]
            if in_string:
                if ch == in_string and source[i - 1] != "\\":
                    in_string = None
            elif ch in "\"'":
                in_string = ch
            elif ch == "/" and source[i:i + 2] == "//":
                nl = source.find("\n", i)
                i = nl if nl != -1 else len(source)
                continue
            elif ch == "/" and source[i:i + 2] == "/*":
                end = source.find("*/", i)
                i = end + 2 if end != -1 else len(source)
                continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        if depth != 0:
            continue
        end_index = source.count("\n", 0, i - 1)
        return {
            "name": name,
            "start_line": start_index + 1,
            "end_line": end_index + 1,
            "text": "".join(lines[start_index:end_index + 1]).strip(),
        }
    return None


__all__ = ["source_function"]
