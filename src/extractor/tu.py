"""libclang Translation Unit construction (fault-tolerant)."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import clang.cindex as cx

_LIBCLANG_CANDIDATES = [
    "/usr/lib/llvm-20/lib/libclang-20.so.20",
    "/usr/lib/llvm-20/lib/libclang.so.1",
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
    # libclang is process-global. Other verification components may have
    # loaded it before the extractor (for example the generated-C AST oracle),
    # and cindex rejects replacing the library after that point. Reuse the
    # already-loaded instance so extraction remains composable in one process.
    if p and not cx.Config.loaded:
        cx.Config.set_library_file(p)
    _CONFIGURED = True


def default_include_args(linux_root: str, build_root: str | None = None) -> list[str]:
    """Best-effort Linux kernel include flags. Parse is fault-tolerant —
    missing config headers are recorded as warnings, not fatal."""
    lr = linux_root
    build = build_root or linux_root
    return [
        "-x", "c",  # overridden by caller for .h files if needed
        "-D__KERNEL__",
        "-include", f"{build}/include/generated/autoconf.h",
        "-include", f"{lr}/include/linux/compiler-version.h",
        "-include", f"{lr}/include/linux/kconfig.h",
        "-include", f"{lr}/include/linux/compiler_types.h",
        f"-I{build}/arch/x86/include",
        f"-I{build}/include",
        f"-I{build}/arch/x86/include/generated",
        f"-I{build}/include/generated",
        f"-I{build}/arch/x86/include/generated/uapi",
        f"-I{build}/include/generated/uapi",
        f"-I{lr}/include",
        f"-I{lr}/arch/x86/include",
        f"-I{lr}/include/uapi",
        f"-I{lr}/arch/x86/include/uapi",
        f"-I{lr}/drivers/gpio",
        f"-I{lr}/drivers/mmc/host",
        f"-I{lr}/drivers/video/fbdev",
        f"-I{lr}/drivers/clk/visconti",
        "-Wno-implicit-function-declaration",
        "-Wno-int-conversion",
    ]


def effective_compile_args(source: str, linux_root: str | None = None,
                           extra_args: list[str] | None = None,
                           compile_commands: str | None = None,
                           compile_context_mode: str = "auto") -> list[str]:
    """Argument list clang needs for this source — no libclang parse.

    Shared by parse_translation_unit (AST path) and the IR-primary path so
    both compile against the identical preprocessor environment.
    """
    if linux_root is None:
        repo = Path(__file__).resolve().parents[2]
        candidate = repo / "vendor/linux"
        linux_root = os.fspath(candidate) if candidate.is_dir() else None

    from .compile_context import resolve_compile_context
    context = resolve_compile_context(
        source, linux_root=linux_root, compile_commands=compile_commands,
        mode=compile_context_mode)
    args = list(context.arguments) if context else []
    if not context and linux_root:
        repo = Path(__file__).resolve().parents[2]
        build_root = os.environ.get("REHARNESS_KERNEL_BUILD")
        if not build_root:
            candidate = repo / "platform/kernel/build"
            build_root = os.fspath(candidate) if candidate.is_dir() else None
        args += default_include_args(linux_root, build_root)
    elif not context:
        lang = "c-header" if source.endswith(".h") else "c"
        args += ["-x", lang]
    modname = os.path.splitext(os.path.basename(source))[0].replace("-", "_")
    if not any(arg.startswith("-DKBUILD_MODNAME=") for arg in args):
        args.append(f'-DKBUILD_MODNAME="{modname}"')
    if not any(arg.startswith("-DKBUILD_MODFILE=") for arg in args):
        args.append(f'-DKBUILD_MODFILE="{modname}"')
    args += ['-D_Static_assert(x,y)=', '-Wno-ignored-attributes']
    if source.endswith(".h"):
        for i, a in enumerate(args):
            if a == "-x" and i + 1 < len(args) and args[i + 1] == "c":
                args[i + 1] = "c-header"
        if not any(a == "-x" for a in args):
            args += ["-x", "c-header"]
    if not context and os.path.basename(source) == "sdhci-esdhc-mcf.c":
        args += ["-DCONFIG_MMC_SDHCI_IO_ACCESSORS=1",
                 "-DMCF_PLL_DR=0xFC0C0004"]
    if extra_args:
        args += extra_args
    return args, context


def parse_translation_unit(source: str, linux_root: str | None = None,
                           extra_args: list[str] | None = None,
                           compile_commands: str | None = None,
                           compile_context_mode: str = "auto",
                           *, return_context: bool = False):
    """Parse a C source file with detailed preprocessing records.

    Returns (tu, warnings). Parse diagnostics are downgraded to warnings —
    we use whatever AST libclang managed to build.
    """
    _configure()
    args, context = effective_compile_args(
        source, linux_root, extra_args, compile_commands, compile_context_mode)

    flags = (cx.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
             | cx.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES * 0)  # keep bodies

    tu = cx.Index.create().parse(source, args=args, options=flags)
    warnings = []
    target = os.path.abspath(source)
    for d in tu.diagnostics:
        loc = d.location
        line = loc.line if loc and loc.file else "?"
        path = loc.file.name if loc and loc.file else "?"
        # Header-only diagnostics can arise from parsing a translation unit
        # outside Kbuild's exact compiler front end. They remain visible, but
        # only target-source errors block extraction readiness.
        kind = ("clang diag" if path == "?" or os.path.abspath(path) == target
                else "clang header diag")
        warnings.append(f"{kind}[{d.severity}] {path}:{line}: {d.spelling}")
    if return_context:
        metadata = context.display() if context else {
            "source": os.path.abspath(source),
            "origin": ("fallback-disabled" if compile_context_mode == "off"
                       else "fallback"),
            "provenance": "extractor.tu.default_include_args",
            "directory": os.getcwd(),
            "arguments": list(args),
        }
        encoded = "\0".join(args).encode("utf-8")
        metadata["effective_argument_count"] = len(args)
        metadata["effective_arguments_sha256"] = hashlib.sha256(encoded).hexdigest()
        metadata["parser_overrides"] = [
            value for value in ('-D_Static_assert(x,y)=',
                                '-Wno-ignored-attributes')
            if value in args]
        return tu, warnings, metadata
    return tu, warnings
