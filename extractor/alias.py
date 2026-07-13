"""SVF-backed MMIO alias analysis via wpa CLI + IR stubbing.

Integrates SVF's Andersen pointer analysis to find local variables that
alias with known MMIO base pointers (e.g., `priv = data; priv->mmio`
→ priv aliases the struct containing the MMIO base).

Pipeline:
  1. Compile C → LLVM .ll (clang -S -emit-llvm)
  2. IR stub: replace opaque declare with define stubs (tools/ir_stub.py)
  3. llvm-as: .ll → .bc
  4. wpa -ander -print-aliases -print-symbol-table <bc>
  5. Parse symbol table: var_id → {func, source_line, ir_text}
  6. Parse alias pairs: find MayAlias with MMIO base origin vars
  7. Cross-reference: map alias var IDs → C variable names via source line + libclang

The result is a set of variable names that should be treated as BasePtr
in reharness's dataflow, in addition to the globals themselves.
"""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from typing import Optional

# SVF 工具路径
_SVF_SETUP = os.path.expanduser("~/SVF/setup.sh")
_WPA = os.path.expanduser("~/SVF/Release-build/bin/wpa")
_CLANG = os.path.expanduser("~/SVF/llvm-21.1.0.obj/bin/clang")
_LLVM_AS = os.path.expanduser("~/SVF/llvm-21.1.0.obj/bin/llvm-as")


def _source_svf_env() -> dict:
    """Source SVF setup.sh and return the env dict."""
    r = subprocess.run(f"bash -c 'source {_SVF_SETUP} Release 2>/dev/null && env'",
                       shell=True, capture_output=True, text=True)
    env = dict(os.environ)
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def _generate_stubbed_bc(source: str, linux_root: str | None = None,
                        env: dict | None = None) -> str | None:
    """Compile C → .ll → IR stub → .bc for SVF analysis.

    Strips MODULE_* macros, strips __maybe_unused (prevents function
    elimination), applies IR stubbing (tools/ir_stub.py), then llvm-as.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    tools_dir = os.path.normpath(os.path.join(here, "..", "tools"))
    linux = linux_root or os.path.normpath(os.path.join(here, "..", "linux"))
    if not os.path.isdir(os.path.join(linux, "arch", "x86", "include", "generated")):
        linux = os.path.expanduser("~/Code/linux")

    modname = os.path.splitext(os.path.basename(source))[0]

    # Strip MODULE_* lines + __maybe_unused (prevents function elimination)
    with open(source, "r", errors="replace") as f:
        src_text = f.read()
    stripped = re.sub(r'^\s*MODULE_\w+\s*\([^)]*\)\s*;\s*$', '', src_text, flags=re.M)
    stripped = stripped.replace('__maybe_unused', '')
    c_path = tempfile.mktemp(suffix=".c", prefix="rh_svf_")
    with open(c_path, "w") as f:
        f.write(stripped)

    ll_path = tempfile.mktemp(suffix=".ll", prefix="rh_svf_")
    bc_path = tempfile.mktemp(suffix=".bc", prefix="rh_svf_")

    # 1. clang → .ll
    args = [
        _CLANG, "-S", "-emit-llvm", "-g", "-O0", "-c", "-w",
        f"-I{linux}/arch/x86/include",
        f"-I{linux}/arch/x86/include/generated",
        f"-I{linux}/include",
        f"-I{linux}/arch/x86/include/uapi",
        f"-I{linux}/include/uapi",
        f"-I{linux}/arch/x86/include/generated/uapi",
        f"-I{linux}/include/generated/uapi",
        f"-include", f"{linux}/include/linux/compiler-version.h",
        f"-include", f"{linux}/include/linux/kconfig.h",
        f"-include", f"{linux}/include/linux/compiler_types.h",
        "-D__KERNEL__",
        f"-DKBUILD_MODNAME=\"{modname}\"",
        "-D_Static_assert(x,y)=",
        c_path,
        "-o", ll_path,
    ]
    e = env or os.environ
    r = subprocess.run(args, capture_output=True, text=True, timeout=60, env=e)
    os.unlink(c_path)
    if r.returncode != 0 or not os.path.exists(ll_path):
        return None

    # 2. IR stub
    try:
        import sys
        sys.path.insert(0, tools_dir)
        from ir_stub import stub_ir
        with open(ll_path, "r", errors="replace") as f:
            ll_text = f.read()
        stubbed = stub_ir(ll_text)
        with open(ll_path, "w") as f:
            f.write(stubbed)
    except Exception:
        pass  # stub 失败则用原始 .ll

    # 3. llvm-as → .bc
    r2 = subprocess.run([_LLVM_AS, ll_path, "-o", bc_path],
                       capture_output=True, text=True, timeout=30, env=e)
    os.unlink(ll_path)
    if r2.returncode != 0 or not os.path.exists(bc_path):
        return None
    return bc_path


# ── wpa 输出解析 ──

_ALIAS_RE = re.compile(r'(MayAlias|NoAlias|PartialAlias|MustAlias)\s+(\S+)\s+--\s+(\S+)')
_VAR_RE = re.compile(r'^var(\d+)\[([^\]]*)\]')
_SYM_LINE_RE = re.compile(r'^(\d+)\s+(.*)')


def _run_wpa(bc_path: str, env: dict) -> str:
    """Run wpa -ander -print-aliases -print-symbol-table, return stdout."""
    r = subprocess.run(
        [_WPA, "-ander", "-print-aliases", "-print-symbol-table", bc_path],
        capture_output=True, text=True, timeout=120, env=env
    )
    return r.stdout


def _parse_symbol_table(output: str) -> dict[int, dict]:
    """Parse wpa -print-symbol-table → {var_id: {func, line, ir_text}}."""
    result = {}
    for line in output.splitlines():
        m = _SYM_LINE_RE.match(line.strip())
        if not m:
            continue
        vid = int(m.group(1))
        ir_text = m.group(2)
        # 提取函数名: varN[@func] 或 define ... @func(
        func = ""
        vm = _VAR_RE.search(ir_text)
        if vm:
            scope = vm.group(2)
            func = scope.split('@')[-1] if '@' in scope else scope
        # 提取源行号: { "ln": N, "fl": "..." }
        ln_m = re.search(r'"ln":\s*(\d+)', ir_text)
        line_num = int(ln_m.group(1)) if ln_m else 0
        result[vid] = {"func": func, "line": line_num, "ir": ir_text}
    return result


def _find_mmio_origin_vars(symbol_table: dict, mmio_globals: set[str]) -> set[int]:
    """Find var IDs that are MMIO base origins (ioremap/malloc calls or mmio_globals)."""
    origins = set()
    for vid, info in symbol_table.items():
        ir = info["ir"]
        # ioremap/malloc call → fresh MMIO base
        if any(kw in ir for kw in ['ioremap', 'pci_ioremap_bar', 'devm_ioremap',
                                    'malloc', 'devm_kmalloc', 'devm_kzalloc']):
            origins.add(vid)
        # Known mmio_global name in IR
        for g in mmio_globals:
            if g in ir:
                origins.add(vid)
    return origins


def _map_var_to_c_name(symbol_table: dict, vid: int, source: str, tu) -> str | None:
    """Map a SVF var ID to a C variable name via source line + libclang."""
    info = symbol_table.get(vid, {})
    line = info.get("line", 0)
    if line == 0:
        return None
    return _find_lhs_var_at_line(tu, source, line)


def _find_lhs_var_at_line(tu, target_file: str, line: int) -> str | None:
    """Use libclang to find the LHS variable assigned at the given source line."""
    import clang.cindex as cx
    tgt = os.path.abspath(target_file)
    for cursor in tu.cursor.walk_preorder():
        f = cursor.location.file
        if not f or os.path.abspath(f.name) != tgt:
            continue
        if cursor.location.line != line:
            continue
        if cursor.kind == cx.CursorKind.VAR_DECL:
            children = list(cursor.get_children())
            if children:
                return cursor.spelling
        if cursor.kind == cx.CursorKind.BINARY_OPERATOR:
            tokens = list(cursor.get_tokens())
            if tokens and any(t.spelling == "=" for t in tokens):
                lhs = cursor.get_children()
                first = next(lhs, None)
                if first and first.kind in (cx.CursorKind.DECL_REF_EXPR,
                                            cx.CursorKind.MEMBER_REF):
                    name = first.spelling or (first.referenced.spelling
                                              if first.referenced else None)
                    if name:
                        # 容器: g->base → 返回 g 和 g->base
                        if "->" in name or "." in name:
                            return name
                        return name
    return None


def _parse_wpa_aliases(output: str, symbol_table: dict,
                     mmio_origin_vars: set[int], source: str, tu) -> set[str]:
    """Parse MayAlias pairs, find vars aliasing with MMIO origins,
    map back to C variable names."""
    aliases: set[str] = set()

    for line in output.splitlines():
        m = _ALIAS_RE.match(line.strip())
        if not m:
            continue
        kind, left, right = m.groups()
        if kind != "MayAlias":
            continue

        # Extract var IDs
        left_m = _VAR_RE.match(left)
        right_m = _VAR_RE.match(right)
        if not left_m or not right_m:
            continue
        left_id = int(left_m.group(1))
        right_id = int(right_m.group(1))

        # 如果一侧是 MMIO origin, 另一侧是别名
        alias_id = None
        if left_id in mmio_origin_vars and right_id not in mmio_origin_vars:
            alias_id = right_id
        elif right_id in mmio_origin_vars and left_id not in mmio_origin_vars:
            alias_id = left_id

        if alias_id is not None:
            # 映射回 C 变量名
            c_name = _map_var_to_c_name(symbol_table, alias_id, source, tu)
            if c_name:
                aliases.add(c_name)
                # 容器: priv->mmio → 加 priv 和 priv->mmio
                if "->" in c_name:
                    aliases.add(c_name)
                    aliases.add(c_name.split("->")[0])
                elif "." in c_name:
                    aliases.add(c_name)
                    aliases.add(c_name.split(".")[0])

    return aliases


# ── 主接口 ──

def find_mmio_aliases(source: str, tu, linux_root: str | None = None,
                      mmio_globals: set[str] | None = None) -> set[str]:
    """Find C variable names that alias MMIO base pointers using SVF.

    Args:
        source: C source file path
        tu: libclang TranslationUnit (already parsed by reharness)
        linux_root: Linux kernel source root for include paths
        mmio_globals: set of known MMIO base variable names from reharness

    Returns:
        Set of variable names to treat as BasePtr in dataflow.
    """
    if mmio_globals is None:
        mmio_globals = set()

    if not os.path.exists(_WPA) or not os.path.exists(_CLANG):
        return set()

    env = _source_svf_env()

    # 1. 编译 .ll → stub → .bc
    bc_path = _generate_stubbed_bc(source, linux_root, env)
    if bc_path is None:
        return set()

    try:
        # 2. 运行 wpa
        stdout = _run_wpa(bc_path, env)

        # 3. 解析 symbol table
        sym_tab = _parse_symbol_table(stdout)

        # 4. 找 MMIO origin var IDs
        origin_vars = _find_mmio_origin_vars(sym_tab, mmio_globals)

        # 5. 解析 alias pairs → C 变量名
        aliases = _parse_wpa_aliases(stdout, sym_tab, origin_vars, source, tu)

        return aliases | mmio_globals

    except Exception:
        return mmio_globals  # 出错时返回原始 globals

    finally:
        if bc_path and os.path.exists(bc_path):
            os.unlink(bc_path)
