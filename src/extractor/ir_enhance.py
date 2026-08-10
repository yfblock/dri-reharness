"""IR-based MMIO enhancement for the AST extraction pipeline.

Generates LLVM IR at -O1 (which inlines static inline helpers from headers)
and parses the resulting inline asm patterns to discover MMIO operations
that the AST-based extractor might miss.

At -O1, Linux readl/writel are fully inlined to x86 inline-asm:
  Write: tail call void asm sideeffect "movl $0,$1", "r,*m,~{...}"(...)
  Read:  %r = tail call i32 asm sideeffect "movl $1,$0", "=r,*m,~{...}"(...)

The pointer operand traces back through getelementptr to a byte offset from
the MMIO base, which maps directly to register macro offsets.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IRMMIOOp:
    """A single MMIO operation discovered from LLVM IR analysis."""
    kind: str                       # "read" or "write"
    function: str                   # outermost source-level function name
    source_line: int                # source line of the outermost caller
    offset: int | None              # byte offset from MMIO base
    inlined_chain: list[str]        # function names in the inline chain
    ir_line: int = 0                # line number in the .ll file


@dataclass
class IRSummary:
    """Summary of IR-discovered MMIO operations for a source file."""
    ops: list[IRMMIOOp] = field(default_factory=list)
    ops_by_function: dict[str, list[IRMMIOOp]] = field(default_factory=dict)
    ir_generated: bool = False
    error: str | None = None

    def ops_for_function(self, name: str) -> list[IRMMIOOp]:
        """Return all IR-discovered ops attributed to the named function."""
        return self.ops_by_function.get(name, [])

    def missing_from_ast(self, ast_ops: list[dict]) -> list[IRMMIOOp]:
        """Return IR ops whose (function, offset) pair is absent from AST ops."""
        ast_keys: set[tuple[str, int | None]] = set()
        for op in ast_ops:
            ast_keys.add((op.get("function", ""), op.get("offset")))
        return [
            op for op in self.ops
            if (op.function, op.offset) not in ast_keys
        ]


def generate_ir(source, linux_root=None, *, workdir, clang='clang-18',
                compile_commands=None, compile_context_mode='auto',
                opt_level='1'):
    """Compile C source to LLVM IR (.ll) text. Returns path or None."""
    from .compile_context import resolve_compile_context
    from .tu import default_include_args

    repo = Path(__file__).resolve().parents[2]
    linux = linux_root or os.path.join(str(repo), 'vendor/linux')
    build = os.environ.get('REHARNESS_KERNEL_BUILD')
    if not build:
        candidate = repo / 'platform/kernel/build'
        build = str(candidate) if candidate.is_dir() else linux

    modname = os.path.splitext(os.path.basename(source))[0]
    with open(source, 'r', errors='replace') as f:
        src_text = f.read()
    stripped = re.sub(r'^s*MODULE_w+s*([^)]*)s*;s*$', '', src_text, flags=re.M)
    stripped = stripped.replace('__maybe_unused', '')
    c_path = os.path.join(workdir, 'source.c')
    with open(c_path, 'w') as f:
        f.write(stripped)

    ll_path = os.path.join(workdir, 'source.ll')
    context = resolve_compile_context(
        source, linux_root=linux, compile_commands=compile_commands,
        mode=compile_context_mode)
    context_args = list(context.arguments) if context else default_include_args(linux, build)
    parser_defines = []
    if not any(a.startswith('-DKBUILD_MODNAME=') for a in context_args):
        parser_defines.append('-DKBUILD_MODNAME="' + modname + '"')
    if not any(a.startswith('-DKBUILD_MODFILE=') for a in context_args):
        parser_defines.append('-DKBUILD_MODFILE="' + modname + '"')

    args = [
        clang, '-S', '-emit-llvm', '-g', '-O' + opt_level, '-c', '-w',
        '-fdebug-compilation-dir=.',
        '-fdebug-prefix-map=' + workdir + '=.',
        '-I', os.path.dirname(os.path.abspath(source)),
        *context_args, *parser_defines,
        '-D_Static_assert(x,y)=', c_path, '-o', ll_path]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60, env=os.environ)
    if r.returncode != 0 or not os.path.exists(ll_path):
        return None
    return ll_path


# ── IR debug metadata parsing ────────────────────────────────────────

def _parse_metadata(ir_text):
    """Parse LLVM IR debug metadata into a lookup table."""
    meta = {}

    # DILocation (handles both regular and distinct)
    for m in re.finditer(
        r'^(!\d+) = (?:distinct )?!DILocation\(line: (\d+), column: (\d+),'
        r' scope: (!\d+|null)(?:, inlinedAt: (!\d+))?',
        ir_text, re.M):
        meta[m.group(1)] = {
            'line': int(m.group(2)),
            'col': int(m.group(3)),
            'scope': m.group(4),
            'inlinedAt': m.group(5),
        }

    # DISubprogram
    for m in re.finditer(
        r'^(!\d+) = distinct !DISubprogram\(name: "([^"]*)"',
        ir_text, re.M):
        meta.setdefault(m.group(1), {})['name'] = m.group(2)

    # DIFile
    for m in re.finditer(
        r'^(!\d+) = !DIFile\(filename: "([^"]*)", directory: "([^"]*)"',
        ir_text, re.M):
        meta.setdefault(m.group(1), {})['filename'] = m.group(2)
        meta[m.group(1)]['directory'] = m.group(3)

    # DILexicalBlock scope chain
    for m in re.finditer(
        r'^(!\d+) = distinct !DILexicalBlock\(scope: (!\d+)',
        ir_text, re.M):
        meta.setdefault(m.group(1), {})['scope'] = m.group(2)

    return meta


def _resolve_scope_name(meta, scope_id):
    """Follow DILexicalBlock scope chain to find the DISubprogram name."""
    if not scope_id:
        return None
    seen = set()
    current = scope_id
    while current and current not in seen:
        seen.add(current)
        info = meta.get(current)
        if not info:
            return None
        if 'name' in info:
            return info['name']
        current = info.get('scope')
    return None


def _resolve_scope_chain(meta, dbg_id):
    """Walk the full !dbg inlinedAt chain.

    Returns list of (function_name, source_line) from innermost to outermost.
    """
    chain = []
    current = dbg_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        loc = meta.get(current)
        if not loc:
            break
        scope = loc.get('scope')
        name = _resolve_scope_name(meta, scope) if scope else None
        chain.append((name, loc.get('line')))
        current = loc.get('inlinedAt')
    return chain


def _outermost_function(chain):
    """Extract the outermost non-primitive caller function and its line."""
    for name, line in reversed(chain):
        if name and not name.startswith('__') and name not in ('readl', 'writel'):
            return name, line
    if chain:
        return chain[-1]
    return None, None


# ── Offset extraction from IR ────────────────────────────────────────

def _trace_offset(lines, asm_idx, ptr_var):
    """Trace backward from asm instruction to find the GEP byte offset."""
    for j in range(asm_idx - 1, max(0, asm_idx - 15), -1):
        line = lines[j]
        if ptr_var not in line or 'getelementptr' not in line:
            continue
        m = re.search(r'i64 (\d+)', line)
        if m:
            return int(m.group(1))
        break
    return None


# ── Main IR parsing ──────────────────────────────────────────────────

# x86 inline asm signatures for MMIO at -O1
_WRITE_ASM = '"movl $0,$1"'
_READ_ASM = '"movl $1,$0"'


def parse_ir_mmio_ops(ir_path):
    """Parse an LLVM IR file and extract all MMIO operations."""
    with open(ir_path, 'r') as f:
        ir_text = f.read()

    meta = _parse_metadata(ir_text)
    lines = ir_text.splitlines()
    ops = []

    for i, line in enumerate(lines):
        if 'asm sideeffect' not in line:
            continue
        is_write = _WRITE_ASM in line
        is_read = _READ_ASM in line
        if not is_write and not is_read:
            continue

        # Extract pointer operand
        ptr_match = re.search(r'elementtype\(i\d+\) (%\d+)', line)
        ptr_var = ptr_match.group(1) if ptr_match else None

        # Extract !dbg reference
        dbg_match = re.search(r'!dbg (!\d+)', line)
        dbg_id = dbg_match.group(1) if dbg_match else None

        # Resolve inline chain
        chain = _resolve_scope_chain(meta, dbg_id) if dbg_id else []
        func_name, src_line = _outermost_function(chain)

        # Trace offset
        offset = _trace_offset(lines, i, ptr_var) if ptr_var else None

        ops.append(IRMMIOOp(
            kind='write' if is_write else 'read',
            function=func_name or '',
            source_line=src_line or 0,
            offset=offset,
            inlined_chain=[name or '?' for name, _ in chain],
            ir_line=i,
        ))

    return ops


def enhance_from_ir(source, linux_root=None, clang='clang-18', opt_level='1',
                    compile_commands=None, compile_context_mode='auto'):
    """Generate IR, parse MMIO ops, and return an IRSummary."""
    with tempfile.TemporaryDirectory(prefix='reharness_ir_') as workdir:
        ll_path = generate_ir(
            source, linux_root=linux_root, workdir=workdir, clang=clang,
            compile_commands=compile_commands,
            compile_context_mode=compile_context_mode,
            opt_level=opt_level)
        if not ll_path:
            return IRSummary(ir_generated=False, error='IR generation failed')

        ops = parse_ir_mmio_ops(ll_path)

    by_func = {}
    for op in ops:
        fn = op.function or '_unknown'
        by_func.setdefault(fn, []).append(op)

    return IRSummary(ops=ops, ops_by_function=by_func, ir_generated=True)


def enhance_multi_from_ir(sources, linux_root=None, clang='clang-18',
                          opt_level='1', compile_commands=None,
                          compile_context_mode='auto'):
    """Run IR enhancement on multiple source files."""
    results = {}
    for source in sources:
        results[source] = enhance_from_ir(
            source, linux_root=linux_root, clang=clang, opt_level=opt_level,
            compile_commands=compile_commands,
            compile_context_mode=compile_context_mode)
    return results


def ir_mmio_summary(source, linux_root=None, **kwargs):
    """Backward-compatible wrapper. Returns IRSummary."""
    return enhance_from_ir(source, linux_root=linux_root, **kwargs)
