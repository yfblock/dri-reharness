"""Header/source splitting for single-file generated drivers."""
from __future__ import annotations

import re

_STRUCT_END_RE = re.compile(r"^};\s*$")


def split_header_source(code: str, driver_name: str, backend: str) -> tuple[str, str]:
    """Split a single-file generated driver into a .h and .c pair.

    The header receives everything up to and including the device-private
    struct definition (macros, inline helpers, register defines, struct)
    plus an include guard.  The source file receives an include of the
    header followed by the function implementations, callback tables and
    entry point.
    """
    # Some models wrap one section of a pair in a second Markdown fence even
    # after the outer code block has been extracted.  Standalone fences are
    # transport syntax, not C/Rust source, and must not enter the header.
    code = re.sub(r"(?m)^\s*```(?:c|cpp|rust)?\s*$\n?", "", code)
    lines = code.split("\n")
    first_struct_end = -1
    depth = 0
    for i, line in enumerate(lines):
        depth += line.count("{") - line.count("}")
        if depth == 0 and _STRUCT_END_RE.match(line):
            first_struct_end = i
            break
    if first_struct_end < 0:
        return "", code
    raw_guard = f"REHARNESS_{driver_name.upper()}_{backend.upper()}_H"
    guard = re.sub(r"\W", "_", raw_guard)
    header_body = "\n".join(lines[:first_struct_end + 1])
    source_body = "\n".join(lines[first_struct_end + 1:])
    header = (f"#ifndef {guard}\n#define {guard}\n\n"
              + header_body + f"\n\n#endif /* {guard} */\n")
    safe_name = re.sub(r"\W", "_", f"{driver_name}_{backend}")
    source = f'#include "{safe_name}.h"\n\n' + source_body

    return header, source

def generate_pair(backend_module, formal: dict, device_spec, bind,
                  **kwargs) -> tuple[str, str]:
    """Call a backend generate() and split into (.h, .c) strings."""
    code = backend_module.generate(formal, device_spec, bind, **kwargs)
    backend_name = backend_module.__name__.split(".")[-1]
    return split_header_source(code, device_spec.name, backend_name)
