"""Shared C-emission helpers for all backends."""

from __future__ import annotations
import re
from extractor.spec import TypeMap, PrimitiveMap, StateMap, ExportMap

_VAR_ID = re.compile(r"^[A-Za-z_]\w*$")
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


_C_KEYWORDS = {
    "auto", "char", "const", "double", "enum", "extern", "float", "for",
    "int", "long", "register", "restrict", "short", "signed", "static",
    "struct", "typedef", "union", "unsigned", "void", "volatile", "while",
}


def make_freestanding_bind(bind, priv: str, base_expr: str, *,
                           prefix: str = "mmio", exports=None) -> None:
    """Populate bind for freestanding C backends (harness, baremetal, rust_baremetal).

    These backends share identical type mappings and state mappings.
    Only the primitive function name prefix differs (e.g. harness_read32
   vs mmio_read32).
   """
    p = prefix
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "uintptr_t"),
        TypeMap("LogicalIRQ", "unsigned int"),
        TypeMap("UInt", "uint32_t"),
        TypeMap("UIntPtr", "uint32_t *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", f"{p}_read32"),
        PrimitiveMap("MmioWrite", "B4", f"{p}_write32"),
        PrimitiveMap("MmioRead", "B2", f"{p}_read16"),
        PrimitiveMap("MmioWrite", "B2", f"{p}_write16"),
        PrimitiveMap("MmioRead", "B1", f"{p}_read8"),
        PrimitiveMap("MmioWrite", "B1", f"{p}_write8"),
        PrimitiveMap("MmioWriteW1C", "B4", f"{p}_write_w1c32"),
        PrimitiveMap("MmioWriteW1C", "B2", f"{p}_write_w1c16"),
        PrimitiveMap("MmioWriteW1C", "B1", f"{p}_write_w1c8"),
        PrimitiveMap("MmioReadBE", "B2", f"{p}_read16be"),
        PrimitiveMap("MmioWriteBE", "B2", f"{p}_write16be"),
        PrimitiveMap("MmioReadBE", "B4", f"{p}_read32be"),
        PrimitiveMap("MmioWriteBE", "B4", f"{p}_write32be"),
   ]
    bind.state = [StateMap("dev.base", "dev->base")]
    if exports:
        for fn in exports:
            bind.exports.append(ExportMap(fn.role, f"{fn.name}"))
