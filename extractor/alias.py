"""SVF-backed MMIO alias analysis via wpa CLI + pysvf.

Integrates SVF's Andersen pointer analysis to find local variables that
alias with known MMIO base pointers (e.g., `priv = data; priv->mmio`
→ priv aliases the struct containing the MMIO base).

Two approaches, tried in order:
  1. pysvf (Python binding): load .bc, run Andersen, query points-to.
     Limited API — may not expose alias query. Falls back to:
  2. wpa CLI: `wpa -ander -print-aliases -print-symbol-table <bc>`
     → parse alias pairs + symbol table → map to C variable names
     via libclang (already loaded by reharness).

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


def _generate_bc(source: str, linux_root: str | None = None,
                 env: dict | None = None) -> str | None:
    """Compile C source to LLVM bitcode (.bc) for SVF analysis.

    Strips MODULE_* macros (they need full kernel build to expand correctly)
    and uses the kernel's generated include paths."""
    here = os.path.dirname(os.path.abspath(__file__))
    linux = linux_root or os.path.normpath(os.path.join(here, "..", "linux"))
    # Fallback to ~/Code/linux (built tree with all generated headers)
    if not os.path.isdir(os.path.join(linux, "arch", "x86", "include", "generated")):
        linux = os.path.expanduser("~/Code/linux")

    modname = os.path.splitext(os.path.basename(source))[0]
    bc_path = tempfile.mktemp(suffix=".bc", prefix="rh_svf_")

    # Strip MODULE_* lines (syntax errors without full kernel build)
    with open(source, "r", errors="replace") as f:
        src_text = f.read()
    stripped = re.sub(r'^\s*MODULE_\w+\s*\([^)]*\)\s*;\s*$', '', src_text, flags=re.M)
    c_path = tempfile.mktemp(suffix=".c", prefix="rh_svf_")
    with open(c_path, "w") as f:
        f.write(stripped)

    args = [
        _CLANG, "-g", "-O0", "-emit-llvm", "-c", "-w",
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
        "-o", bc_path,
    ]
    e = env or os.environ
    r = subprocess.run(args, capture_output=True, text=True, timeout=60, env=e)
    os.unlink(c_path)
    if r.returncode != 0 or not os.path.exists(bc_path):
        return None
    return bc_path


# ── wpa CLI 方式: 解析 -print-aliases + -print-symbol-table ──

_ALIAS_RE = re.compile(r'(MayAlias|NoAlias|PartialAlias|MustAlias)\s+(\S+)\s+--\s+(\S+)')
_VAR_RE = re.compile(r'^var\d+\[([^\]]*)\]')  # var12[@func] → @func 或 空(全局)


def _run_wpa(bc_path: str, env: dict) -> tuple[str, str]:
    """Run wpa -ander -print-aliases -print-symbol-table, return (alias_out, sym_out)."""
    r = subprocess.run(
        [_WPA, "-ander", "-print-aliases", "-print-symbol-table", bc_path],
        capture_output=True, text=True, timeout=120, env=env
    )
    return r.stdout, r.stderr


def _parse_wpa_aliases(output: str, mmio_globals: set[str]) -> set[str]:
    """Parse wpa -print-aliases output, find vars aliasing with mmio_globals.

    Output format:
      MayAlias var12[@vulnerable_process] -- var16[@vulnerable_process]
      MayAlias var4[.str] -- var13[@]
    We look for pairs where one side's function scope contains a known
    mmio_global name, and extract the other side's scope as an alias.
    """
    aliases: set[str] = set()
    for line in output.splitlines():
        m = _ALIAS_RE.match(line.strip())
        if not m:
            continue
        _, left, right = m.groups()
        # Extract scope names (function or global)
        left_scope = _VAR_RE.match(left)
        right_scope = _VAR_RE.match(right)
        left_name = left_scope.group(1).lstrip('@') if left_scope else left
        right_name = right_scope.group(1).lstrip('@') if right_scope else right
        # Check if either side matches a known mmio_global
        for g in mmio_globals:
            if g in left or g in left_name:
                aliases.add(right_name)
            if g in right or g in right_name:
                aliases.add(left_name)
    return aliases


def _parse_wpa_symbol_table(output: str, mmio_globals: set[str]) -> dict[int, str]:
    """Parse wpa -print-symbol-table, return {node_id: c_var_name} for mmio-related nodes.

    Output format:
      16    %3 = call noalias ptr @malloc(...) { "ln": 19, ... }
      117   i64 %0 { 0th arg malloc  }
    We look for lines mentioning mmio_global names or ioremap calls.
    """
    result = {}
    for line in output.splitlines():
        line = line.strip()
        for g in mmio_globals:
            if g in line:
                # Extract node ID (first number)
                m = re.match(r'(\d+)', line)
                if m:
                    result[int(m.group(1))] = g
    return result


# ── pysvf 方式 (尝试) ──

def _try_pysvf(bc_path: str, mmio_globals: set[str]) -> set[str] | None:
    """Try pysvf for alias analysis. Returns None if API insufficient."""
    try:
        import pysvf
        mod = pysvf.buildSVFModule([bc_path])
        pag = pysvf.getPAG()
        pta = pysvf.AndersenWaveDiff(pag)

        # 检查是否有 alias 查询方法
        if not hasattr(pta, 'alias') and not hasattr(pta, 'aliasCheck'):
            return None  # API 不足, 回退到 wpa CLI

        # 如果有 alias 方法, 查询每对变量
        aliases: set[str] = set()
        # TODO: 需要 PAG node 遍历 API 来获取所有变量
        # pysvf 1.0.0.25 的 API 太有限, 暂时回退
        return None
    except Exception:
        return None


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

    # 检查 SVF 可用性
    if not os.path.exists(_WPA) or not os.path.exists(_CLANG):
        return set()

    env = _source_svf_env()

    # 1. 编译 .bc
    bc_path = _generate_bc(source, linux_root, env)
    if bc_path is None:
        return set()

    try:
        # 2. 尝试 pysvf (如果 API 足够)
        pysvf_result = _try_pysvf(bc_path, mmio_globals)
        if pysvf_result is not None:
            return pysvf_result | mmio_globals

        # 3. 回退到 wpa CLI
        stdout, _ = _run_wpa(bc_path, env)

        # 4. 解析 alias pairs
        aliases = _parse_wpa_aliases(stdout, mmio_globals)

        # 5. 也从 symbol table 找 ioremap 结果的别名
        # (ioremap 返回的指针赋值给的结构体成员, 其容器变量也是 MMIO base)
        for line in stdout.splitlines():
            if 'ioremap' in line.lower() or 'pci_iomap' in line.lower():
                # 找到 ioremap 调用 → 其返回值赋给的变量是 MMIO base
                m = re.search(r'(\w+)->(\w+)\s*=', line)
                if m:
                    aliases.add(f"{m.group(1)}->{m.group(2)}")
                    aliases.add(m.group(1))  # 容器也是

        return aliases | mmio_globals

    finally:
        if bc_path and os.path.exists(bc_path):
            os.unlink(bc_path)
