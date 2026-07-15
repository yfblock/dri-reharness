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
    # Some drivers wrap register offsets in an identity macro to document the
    # address space (DWC2 uses HSOTG_REG(x)). Preserve the symbolic register
    # name while evaluating its numeric offset.
    m = re.fullmatch(r"HSOTG_REG\s*\((.+)\)", t, re.I)
    if m:
        return _eval_int_expr(m.group(1))
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

    def merge(self, other: "MacroTable") -> list[str]:
        """Merge another translation unit's integer macros.

        Returns names whose numeric definitions conflict.  The first
        definition is retained so callers can report the ambiguity instead of
        silently changing the register map according to source ordering.
        """
        conflicts: list[str] = []
        for name in other.names():
            if name in self:
                if self.offset(name) != other.offset(name):
                    conflicts.append(name)
                continue
            self.add(name, other.raw(name) or "")
        return conflicts


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
    line_cache: dict[str, list[str]] = {}
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
        # Distinguish `#define F(x) ...` from object-like definitions whose
        # value merely starts with parentheses (`#define FLAG (1 << 3)`).
        # Token streams omit whitespace, so inspect the spelling line.
        function_like = False
        loc_file = c.location.file
        if loc_file and c.location.line:
            try:
                if loc_file.name not in line_cache:
                    with open(loc_file.name, "r", encoding="utf-8",
                              errors="replace") as fh:
                        line_cache[loc_file.name] = fh.readlines()
                line = line_cache[loc_file.name][c.location.line - 1]
                function_like = bool(re.match(
                    rf"^\s*#\s*define\s+{re.escape(name)}\(", line))
            except (OSError, IndexError):
                pass
        if function_like:
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
