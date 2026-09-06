"""AST analyzer: libclang parsing and the structural model over it.

The public API this package exports (import from the package root):

Parsing (``tu`` / ``compile_context``):
  - :func:`locate_libclang` — find a loadable libclang shared object
  - :func:`default_include_args` — kernel-aware include flags
  - :func:`effective_compile_args` — compile args for one source file
  - :func:`parse_translation_unit` — parse C into a libclang TU
  - :class:`CompileContext` / :func:`resolve_compile_context` /
    :func:`compile_context_identity` — compile_commands.json / kbuild
    command resolution feeding those args

Structural model (``model``):
  - :class:`Func` / :class:`CallSite` — function and call-site records
  - :func:`target_functions`, :func:`target_mmio_globals`,
    :func:`callback_entry_symbols` — file-level targets
  - :func:`function_calls`, :func:`direct_callees`,
    :func:`call_arguments`, :func:`callee_name`,
    :func:`function_symbol_id`, :func:`call_symbol_id` — call structure
  - :func:`source_text`, :func:`in_file` — source-text helpers
  - :func:`walk_with_control`, :func:`walk_with_conditions`,
    :func:`continuation_guards` — control-flow-aware cursors

The extractor package (``extractor``) and the verification oracles
import this API; nothing here imports back from extractor.
"""
from .tu import (
    default_include_args,
    effective_compile_args,
    locate_libclang,
    parse_translation_unit,
)
from .compile_context import (
    CompileContext,
    compile_context_identity,
    kbuild_cmd_path,
    read_kbuild_command,
    resolve_compile_context,
)
from .model import (
    CallSite,
    Func,
    callback_entry_symbols,
    call_arguments,
    call_symbol_id,
    callee_name,
    continuation_guards,
    direct_callees,
    function_calls,
    function_symbol_id,
    in_file,
    source_text,
    target_functions,
    target_mmio_globals,
    walk_with_conditions,
    walk_with_control,
)

__all__ = [
    "CallSite",
    "CompileContext",
    "Func",
    "callback_entry_symbols",
    "call_arguments",
    "call_symbol_id",
    "callee_name",
    "compile_context_identity",
    "continuation_guards",
    "default_include_args",
    "direct_callees",
    "effective_compile_args",
    "function_calls",
    "function_symbol_id",
    "in_file",
    "kbuild_cmd_path",
    "locate_libclang",
    "parse_translation_unit",
    "read_kbuild_command",
    "resolve_compile_context",
    "source_text",
    "target_functions",
    "target_mmio_globals",
    "walk_with_conditions",
    "walk_with_control",
]
