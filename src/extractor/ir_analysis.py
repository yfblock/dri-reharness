"""Macro reverse-lookup: constant value → semantic name via clang -dM.

Part of the IR-primary extraction path: GEP gives register offsets, this
module maps them back to the driver's own ``#define`` names.  Kernel-header
macros are filtered out by the caller (ir_primary keeps only driver-local
definitions).

Instruction-level IR analysis lives in ir_text_analyzer (pure text); the
earlier llvmlite-based analyzer was superseded by it and removed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def export_macro_table(source: Path, *,
                       include_dirs: list[str] | None = None,
                       defines: dict[str, str] | None = None,
                       clang: str = "clang-18",
                       use_kernel_flags: bool = True) -> dict[str, str]:
    """Export the full macro definition table via clang -dM -E.

    With use_kernel_flags, preprocess under the same compile arguments the
    AST/IR paths use, so config-dependent macros match the analyzed build.
    """
    args = [clang, "-dM", "-E"]
    if use_kernel_flags:
        try:
            from ast_analyzer import effective_compile_args
            base, _ = effective_compile_args(str(source))
            args += base
        except Exception:
            pass
    for d in (include_dirs or []):
        args += ["-I", d]
    for k, v in (defines or {}).items():
        args.append(f"-D{k}={v}" if v else f"-D{k}")
    args.append(str(source))
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    table: dict[str, str] = {}
    for line in result.stdout.splitlines():
        m = re.match(r'#define\s+(\w+)\s+(.+)', line)
        if m:
            table[m.group(1)] = m.group(2).strip()
    return table


def eval_macro(name: str, table: dict[str, str],
               _expanding: set[str] | None = None) -> int | None:
    """Recursively evaluate a macro to an integer value."""
    _expanding = _expanding or set()
    if name in _expanding:
        return None
    _expanding.add(name)
    expr = table.get(name)
    if expr is None:
        return None
    result = expr
    for tok in re.findall(r'\b\w+\b', expr):
        if tok in table and tok not in _expanding:
            sub = eval_macro(tok, table, _expanding.copy())
            if sub is not None:
                result = result.replace(tok, f"({sub})", 1)
    try:
        return int(eval(result, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception:
        return None


def build_reverse_index(macro_table: dict[str, str]) -> dict[int, list[str]]:
    """Build a reverse lookup: constant_value → [macro_names].

    Prefers the most specific (longest definition chain) name.
    """
    index: dict[int, list[str]] = {}
    for name in macro_table:
        if name.startswith("__"):
            continue
        v = eval_macro(name, macro_table)
        if v is not None:
            v &= 0xFFFFFFFF
            index.setdefault(v, []).append(name)
    for names in index.values():
        names.sort(key=lambda n: len(macro_table.get(n, "")), reverse=True)
    return index


__all__ = ["export_macro_table", "eval_macro", "build_reverse_index"]
