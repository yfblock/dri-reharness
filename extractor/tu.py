"""libclang Translation Unit construction (fault-tolerant)."""
from __future__ import annotations
import os
import clang.cindex as cx

_LIBCLANG_CANDIDATES = [
    "/usr/lib/llvm-18/lib/libclang-18.so.18",
    "/usr/lib/llvm-18/lib/libclang.so.1",
    "/lib/x86_64-linux-gnu/libclang-18.so.18",
    "libclang-18.so.18",
    "libclang.so.1",
]

_CONFIGURED = False


def locate_libclang() -> str | None:
    for p in _LIBCLANG_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _configure():
    global _CONFIGURED
    if _CONFIGURED:
        return
    p = locate_libclang()
    if p:
        cx.Config.set_library_file(p)
    _CONFIGURED = True


def default_include_args(linux_root: str) -> list[str]:
    """Best-effort Linux kernel include flags. Parse is fault-tolerant —
    missing config headers are recorded as warnings, not fatal."""
    lr = linux_root
    return [
        "-x", "c",
        "-D__KERNEL__",
        f"-I{lr}/include",
        f"-I{lr}/arch/x86/include",
        f"-I{lr}/arch/x86/include/generated",
        f"-I{lr}/include/uapi",
        f"-I{lr}/arch/x86/include/uapi",
        f"-I{lr}/arch/x86/include/generated/uapi",
        "-Wno-implicit-function-declaration",
        "-Wno-int-conversion",
    ]


def parse_translation_unit(source: str, linux_root: str | None = None,
                           extra_args: list[str] | None = None):
    """Parse a C source file with detailed preprocessing records.

    Returns (tu, warnings). Parse diagnostics are downgraded to warnings —
    we use whatever AST libclang managed to build.
    """
    _configure()
    if linux_root is None:
        # reharness/linux symlink → ../driver-harness/linux
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.normpath(os.path.join(here, "..", "linux"))
        linux_root = cand if os.path.isdir(cand) else None

    args = []
    if linux_root:
        args += default_include_args(linux_root)
    else:
        args += ["-x", "c"]
    if extra_args:
        args += extra_args

    flags = (cx.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
             | cx.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES * 0)  # keep bodies

    tu = cx.Index.create().parse(source, args=args, options=flags)
    warnings = []
    for d in tu.diagnostics:
        loc = d.location
        line = loc.line if loc and loc.file else "?"
        warnings.append(f"clang diag[{d.severity}] {loc.file.name if loc and loc.file else '?'}:{line}: {d.spelling}")
    return tu, warnings
