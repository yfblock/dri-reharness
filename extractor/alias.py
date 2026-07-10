"""SVF-backed MMIO alias analysis (plan: integrate SVF for alias tracking).

Two-pass approach:
  1. svf-mmio-alias (C++ tool) runs SVF's VFG traversal on the driver's LLVM IR,
     outputs JSON: {global: [{func, loc: "ln:N"}, ...]} — source lines where the
     global is loaded/used.
  2. This module parses the JSON and uses libclang AST (already loaded by reharness)
     to find the C variable name at each source line (the LHS of the assignment
     that loads the global). Those variables are MMIO base aliases.

The result is a set of variable names that should be treated as BasePtr in
reharness's dataflow, in addition to the globals themselves.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from typing import Optional

SVF_BIN = os.environ.get(
    "SVF_BIN",
    "/home/yfblock/Code/SVF/Release-build/bin/svf-mmio-alias",
)
CLANG = os.environ.get("CLANG", "clang-20")

_LINE_RE = re.compile(r'"ln":\s*(\d+)')


def _generate_ir(source: str, linux_root: Optional[str] = None) -> str:
    """Compile C source to optimized LLVM IR with debug info.

    Uses the kernel tree's build environment (autoconf.h, kconfig.h, etc.)
    to produce valid IR for SVF analysis. Suppresses gcc/clang struct layout
    differences via _Static_assert disabling."""
    here = os.path.dirname(os.path.abspath(__file__))
    linux = linux_root or os.path.normpath(os.path.join(here, "..", "linux"))
    modname = os.path.splitext(os.path.basename(source))[0]
    args = [
        CLANG, "-g", "-O1", "-emit-llvm", "-S", "-c", source,
        "-nostdinc",
        f"-I{linux}/arch/x86/include",
        f"-I{linux}/arch/x86/include/generated",
        f"-I{linux}/include",
        f"-I{linux}/arch/x86/include/uapi",
        f"-I{linux}/arch/x86/include/generated/uapi",
        f"-I{linux}/include/uapi",
        f"-I{linux}/include/generated/uapi",
        f"-include", f"{linux}/include/linux/compiler-version.h",
        f"-include", f"{linux}/include/linux/kconfig.h",
        f"-include", f"{linux}/include/linux/compiler_types.h",
        "-D__KERNEL__", "-DCC_USING_FENTRY",
        f"-DKBUILD_MODNAME=\"{modname}\"",
        f"-DKBUILD_MODFILE=\"{source}\"",
        "-D_Static_assert(x,y)=",
        "-Wno-everything", "-Wno-error",
        "-o", "-",
    ]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return ""   # IR generation failed — skip SVF
    return r.stdout


def _run_svf(ir_text: str) -> dict:
    """Run svf-mmio-alias on LLVM IR text, return parsed JSON."""
    if not ir_text.strip():
        return {}
    # write IR to temp file
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".ll", delete=False) as tf:
        tf.write(ir_text)
        ir_path = tf.name
    try:
        r = subprocess.run([SVF_BIN, ir_path], capture_output=True, text=True, timeout=60)
        # SVF prints stats to stdout mixed with JSON — extract the JSON block
        out = r.stdout
        start = out.rfind("\n{")
        if start >= 0:
            json_text = out[start + 1:]
        else:
            json_text = out
        return json.loads(json_text)
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}
    finally:
        os.unlink(ir_path)


def _parse_line(loc_str: str) -> Optional[int]:
    """Extract line number from SVF's source location string."""
    m = _LINE_RE.search(loc_str)
    return int(m.group(1)) if m else None


def _find_lhs_var_at_line(tu, target_file: str, line: int) -> Optional[str]:
    """Use libclang to find the LHS variable assigned at the given source line.

    Looks for a DeclStmt or BinaryOperator(=) whose location is on `line`,
    and returns the variable name being assigned.
    """
    import clang.cindex as cx
    tgt = os.path.abspath(target_file)

    for cursor in tu.cursor.walk_preorder():
        f = cursor.location.file
        if not f or os.path.abspath(f.name) != tgt:
            continue
        if cursor.location.line != line:
            continue
        # DeclStmt with init (e.g., `void *p = mmio_global;`)
        if cursor.kind == cx.CursorKind.VAR_DECL:
            children = list(cursor.get_children())
            if children:   # has initializer
                return cursor.spelling
        # BinaryOperator assignment (e.g., `p = mmio_global;`)
        if cursor.kind == cx.CursorKind.BINARY_OPERATOR:
            # check it's an assignment
            tokens = list(cursor.get_tokens())
            if tokens and any(t.spelling == "=" for t in tokens):
                lhs = cursor.get_children()
                first = next(lhs, None)
                if first and first.kind in (cx.CursorKind.DECL_REF_EXPR,
                                            cx.CursorKind.MEMBER_REF):
                    return first.spelling or (first.referenced.spelling
                                              if first.referenced else None)
    return None


def find_mmio_aliases(source: str, tu, linux_root: Optional[str] = None) -> set[str]:
    """Find all C variable names that alias an MMIO base global.

    Returns a set of variable names (including the globals themselves) that
    should be treated as BasePtr in reharness's dataflow.
    """
    if not os.path.exists(SVF_BIN):
        return set()

    ir = _generate_ir(source, linux_root)
    svf_result = _run_svf(ir)
    if not svf_result:
        return set()

    aliases: set[str] = set()
    for global_name, use_locs in svf_result.items():
        aliases.add(global_name)
        for ul in use_locs:
            line = _parse_line(ul.get("loc", ""))
            if line is None:
                continue
            var = _find_lhs_var_at_line(tu, source, line)
            if var:
                aliases.add(var)
                # Also handle member access: g->base → add g
                if "->" in var:
                    aliases.add(var.split("->")[0])
                elif "." in var:
                    aliases.add(var.split(".")[0])

    return aliases
