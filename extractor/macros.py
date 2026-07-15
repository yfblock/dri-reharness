"""#define register-offset table — replaces driver-harness's hardcoded virtio_map.

Collects macro definitions from the translation unit's preprocessing record
AND a regex fallback over the raw source (robust against incomplete parsing).
Resolves register names like GPIO_INT_EN → 0x20, and value macros like
BIT(n), mask expressions, etc.
"""
from __future__ import annotations
import re
import os
import clang.cindex as cx

_HEX = r"0[xX][0-9a-fA-F]+"
_DEC = r"\d+"


def _eval_int_expr(text: str) -> int | None:
    """Evaluate a simple integer macro value: 0x20, (1<<5), 0x1|0x2, ~0x0, BIT(3)."""
    t = text.strip()
    if not t:
        return None
    # Kernel register definitions commonly carry C integer suffixes (U, L,
    # UL, ULL).  Python's int/eval reject them, but they do not change the
    # mathematical value needed by the RIS register map.
    t = re.sub(r"\b(0[xX][0-9a-fA-F]+|\d+)(?:[uU][lL]{0,2}|[lL]{1,2}[uU]?)\b",
               r"\1", t)
    # BIT(n) → 1 << n
    m = re.fullmatch(r"BIT\s*\(\s*(\d+)\s*\)", t, re.I)
    if m:
        return 1 << int(m.group(1))
    m = re.fullmatch(r"\(\s*1\s*<<\s*(\d+)\s*\)", t, re.I)
    if m:
        return 1 << int(m.group(1))
    # ~0x0 / ~0 → all-ones (width dependent; use 0xFFFFFFFF as pipeline.py does)
    if re.fullmatch(r"~\s*(0[xX]0+|0+)", t):
        return 0xFFFFFFFF
    # try direct int
    try:
        return int(t, 0)
    except ValueError:
        pass
    # strip outer parens
    if t.startswith("(") and t.endswith(")"):
        return _eval_int_expr(t[1:-1])
    # simple binary expr of hex/dec with | & + - << >> ~ () — try directly
    import warnings
    try:
        safe = re.sub(r"\b0[xX][0-9a-fA-F]+\b", lambda m: str(int(m.group(0), 16)), t)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            val = eval(safe, {"__builtins__": {}}, {})
        if isinstance(val, int):
            return val
    except Exception:
        return None
    return None


class MacroTable:
    """name -> (offset:int|None, raw_expr:str)."""

    def __init__(self):
        self._tab: dict[str, tuple[int | None, str]] = {}

    def add(self, name: str, raw_expr: str):
        if not name or name in self._tab:
            return
        val = _eval_int_expr(raw_expr)
        self._tab[name] = (val, raw_expr.strip())

    def offset(self, name: str) -> int | None:
        e = self._tab.get(name)
        return e[0] if e else None

    def raw(self, name: str) -> str | None:
        e = self._tab.get(name)
        return e[1] if e else None

    def __contains__(self, name):
        return name in self._tab

    def names(self):
        return list(self._tab.keys())

    def __len__(self):
        return len(self._tab)


_DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*(?:/\*.*)?$"
)


def collect_from_source(source_text: str) -> MacroTable:
    """Regex fallback: parse #define NAME <int-expr> from raw source text."""
    tab = MacroTable()
    for line in source_text.splitlines():
        m = _DEFINE_RE.match(line)
        if m:
            name, expr = m.group(1), m.group(2)
            # only keep ones that evaluate to an int (register offsets / masks)
            if _eval_int_expr(expr) is not None:
                tab.add(name, expr)
    return tab


def collect_from_tu(tu, target_file: str | None = None) -> MacroTable:
    """Walk macro definitions in the TU.

    By default collects from ALL files (the driver's own #defines plus those
    pulled in via #include <linux/...>, e.g. VIRTIO_MMIO_* from
    include/uapi/linux/virtio_mmio.h). Only object-like macros whose value
    evaluates to an integer are kept (register offsets / masks).
    """
    tab = MacroTable()
    tgt = os.path.abspath(target_file) if target_file else None
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.MACRO_DEFINITION:
            continue
        toks = [t.spelling for t in c.get_tokens()]
        if not toks:
            continue
        name = c.spelling
        expr_toks = toks[1:]
        if expr_toks and expr_toks[0] == name:
            expr_toks = expr_toks[1:]
        # skip function-like macros: NAME ( args )
        if len(expr_toks) >= 1 and expr_toks[0] == "(":
            continue
        expr = " ".join(expr_toks)
        # only keep if it evaluates to an int (filter config/feature flags noise too)
        if _eval_int_expr(expr) is None:
            continue
        tab.add(name, expr)
    return tab


def build(tu, source_path: str, source_text: str) -> MacroTable:
    """Merge TU-collected macros (target file) with the regex source fallback.

    The source fallback catches anything libclang's preprocessing record
    missed; the TU gives accurate file attribution."""
    tab = collect_from_tu(tu, source_path)
    src_tab = collect_from_source(source_text)
    for name in src_tab.names():
        if name not in tab:
            off = src_tab.offset(name)
            tab.add(name, src_tab.raw(name) or "")
    return tab
