"""Abstract expression evaluation and MMIO address resolution."""
from __future__ import annotations
import re
from typing import Optional

from .ops import BASE_FIELDS
from ..taint import (
    BasePtr, Offset, Const, SymExpr, Top, AbsVal,
    addr_fixed, addr_offset, addr_indirect,
)


_CAST_RE = re.compile(
    r"^\s*\(\s*(?:unsigned\s+|signed\s+|const\s+|volatile\s+|struct\s+|enum\s+)*"
    r"(?:u\d+|s\d+|u8|u16|u32|u64|int|long|short|char|void|size_t|__u\d+|le\d+|be\d+)"
    r"(?:\s*\*+)?\s*\)\s*(.+)$", re.S
)


def _strip_parens(t: str) -> str:
    t = t.strip()
    while t.startswith("(") and t.endswith(")"):
        # verify balanced
        depth = 0
        balanced_outer = True
        for i, ch in enumerate(t):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(t) - 1:
                    balanced_outer = False
                    break
        if balanced_outer:
            t = t[1:-1].strip()
        else:
            break
    return t


def _strip_casts(t: str) -> str:
    while True:
        m = _CAST_RE.match(t)
        if not m:
            break
        t = m.group(1).strip()
    return _strip_parens(t)


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` at paren depth 0, ignoring sep inside ()/[] and
    inside multi-char tokens like -> << >>."""
    parts = []
    depth = 0
    cur = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "([":
            depth += 1
            cur += ch
            i += 1
            continue
        if ch in ")]":
            depth -= 1
            cur += ch
            i += 1
            continue
        if depth == 0 and text[i:i + len(sep)] == sep:
            # avoid matching inside -> / << / >> when sep is - or < or >
            if sep == "-" and i + 1 < n and text[i + 1] == ">":
                cur += ch
                i += 1
                continue
            if sep == ">" and i - 1 >= 0 and text[i - 1] == "-":
                cur += ch
                i += 1
                continue
            if (sep in {"<", ">"}
                    and ((i > 0 and text[i - 1] == sep)
                         or (i + 1 < n and text[i + 1] == sep)
                         or (i + 1 < n and text[i + 1] == "="))):
                cur += ch
                i += 1
                continue
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p for p in parts if p.strip() != ""] or [text]


_MEMBER_RE = re.compile(r"^(\w+)(?:->|\.)(\w+)$")
_CHAINED_MEMBER_RE = re.compile(
    r"^[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+$")
_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
_HEX_RE = re.compile(r"^0[xX][0-9a-fA-F]+$")
_DEC_RE = re.compile(r"^\d+$")
_BIT_RE = re.compile(r"^BIT\s*\(\s*(\d+)\s*\)$", re.I)


def eval_expr(text: str, store: dict, macros) -> AbsVal:
    """Evaluate an expression string to an AbsVal."""
    t = _strip_casts(text).strip()
    if not t:
        return Top()

    # BIT(n)
    m = _BIT_RE.match(t)
    if m:
        return Const(1 << int(m.group(1)))

    # additive: A + B  /  A - B  (resolve base+offset)
    plus_parts = _split_top(t, "+")
    if len(plus_parts) > 1:
        vals = [eval_expr(p, store, macros) for p in plus_parts]
        return _combine_add(vals)

    minus_parts = _split_top(t, "-")
    if len(minus_parts) > 1:
        vals = [eval_expr(p, store, macros) for p in minus_parts]
        return _combine_sub(vals)

    # bitwise OR / AND / shift on constants → Const, else SymExpr
    for sep in ("|", "&", "<<", ">>"):
        parts = _split_top(t, sep)
        if len(parts) > 1:
            vals = [eval_expr(p, store, macros) for p in parts]
            if all(isinstance(v, Const) for v in vals):
                n = vals[0].n
                for v in vals[1:]:
                    if sep == "|":
                        n |= v.n
                    elif sep == "&":
                        n &= v.n
                    elif sep == "<<":
                        n <<= v.n
                    else:
                        n >>= v.n
                return Const(n)
            return SymExpr(_strip_casts(text))

    # unary ~
    if t.startswith("~"):
        inner = eval_expr(t[1:], store, macros)
        if isinstance(inner, Const):
            return Const(~inner.n & 0xFFFFFFFF)
        return SymExpr(_strip_casts(text))

    # hex / dec literal
    if _HEX_RE.match(t):
        return Const(int(t, 16))
    if _DEC_RE.match(t):
        return Const(int(t))

    # member access: var->field / var.field
    m = _MEMBER_RE.match(t)
    if m:
        var, fld = m.group(1), m.group(2)
        fld_low = fld.lower()
        # field that holds the MMIO base (base, pll_base, io_base, regs, ...)
        if fld in BASE_FIELDS or "base" in fld_low or fld_low in ("regs", "reg"):
            return BasePtr(f"{var}->{fld}")
        # chained member or known store value
        key = f"{var}->{fld}"
        if key in store:
            return store[key]
        return SymExpr(t)

    # Nested aggregate base, e.g. dev->hpi.base or card->port.regs.  Preserve
    # the complete source path as the MMIO base instead of degrading the whole
    # address to an opaque string.
    if _CHAINED_MEMBER_RE.match(t):
        field = re.split(r"->|\.", t)[-1]
        fld_low = field.lower()
        if field in BASE_FIELDS or "base" in fld_low or fld_low in ("regs", "reg"):
            return BasePtr(t)
        if t in store:
            return store[t]
        return SymExpr(t)

    # identifier
    if _IDENT_RE.match(t):
        if t in store:
            return store[t]
        if t in macros:
            off = macros.offset(t)
            if off is not None:
                return Offset("", off, reg_name=t)
        return SymExpr(t)

    return SymExpr(t)


def _combine_add(vals: list[AbsVal]) -> AbsVal:
    base: Optional[str] = None
    reg_name: Optional[str] = None
    off = 0
    have_const = False
    have_base = False
    for v in vals:
        if isinstance(v, BasePtr):
            base = v.base
            have_base = True
        elif isinstance(v, Offset):
            if not have_base:
                base = v.base
                have_base = True
            off += v.off
            if v.reg_name:
                reg_name = v.reg_name
        elif isinstance(v, Const):
            off += v.n
            have_const = True
        elif isinstance(v, SymExpr):
            # a bare identifier in an additive address expression is the
            # MMIO base (e.g. `mmio + REG`). Treat it as BasePtr.
            if not have_base and (_IDENT_RE.match(v.text) or _MEMBER_RE.match(v.text)):
                base = v.text
                have_base = True
            else:
                return Top()
        else:
            return Top()
    if have_base:
        return Offset(base or "", off, reg_name)
    if have_const:
        return Const(off)
    return Top()


def _combine_sub(vals: list[AbsVal]) -> AbsVal:
    first = vals[0]
    if isinstance(first, (BasePtr, Offset)):
        base = first.base if isinstance(first, BasePtr) else first.base
        off = 0 if isinstance(first, BasePtr) else first.off
        reg_name = first.reg_name if isinstance(first, Offset) else None
        for v in vals[1:]:
            if isinstance(v, Const):
                off -= v.n
            else:
                return Top()
        return Offset(base or "", off, reg_name)
    if all(isinstance(v, Const) for v in vals):
        n = vals[0].n
        for v in vals[1:]:
            n -= v.n
        return Const(n)
    return Top()


def resolve_addr(text: str, store: dict, macros) -> tuple[dict, Optional[str]]:
    """Resolve an MMIO address argument to (RegAddr dict, reg_name)."""
    v = eval_expr(text, store, macros)

    if isinstance(v, BasePtr):
        return addr_offset(v.base, 0), None
    if isinstance(v, Offset):
        if v.base:
            return addr_offset(v.base, v.off), v.reg_name
        # bare macro/const with no base → treat as fixed offset
        return addr_fixed(v.off if v.off >= 0 else 0), v.reg_name
    if isinstance(v, Const):
        return addr_fixed(v.n), None

    # A local pointer can be assigned in mutually exclusive branches before
    # the MMIO call.  Preserve the branch-selected offset as a computed ITE
    # instead of degrading the local variable to base+0.
    resolved_text = v.text if isinstance(v, SymExpr) else text
    ternary = _split_ternary_expr(resolved_text)
    if ternary is not None:
        guard, then_text, else_text = ternary
        then_parts = _address_base_offset(then_text, store, macros)
        else_parts = _address_base_offset(else_text, store, macros)
        if (then_parts is not None and else_parts is not None
                and then_parts[0] == else_parts[0]):
            base = then_parts[0]
            dynamic = (f"(({guard}) ? ({then_parts[1]})"
                       f" : ({else_parts[1]}))")
            return addr_indirect(base, 0, dynamic), None

    # Symbolic offset on a base: preserve the full dynamic offset expression.
    # The former representation kept only the base and silently discarded
    # terms such as (1 << (offset + 2)) or offset + i.
    text = resolved_text
    plus = _split_top(_strip_casts(text), "+")
    if len(plus) > 1:
        base = None
        dynamic: list[str] = []
        for part in plus:
            value = eval_expr(part, store, macros)
            if base is None and isinstance(value, BasePtr):
                base = value.base
            else:
                dynamic.append(part.strip())
        if base is not None and dynamic:
            return addr_indirect(base, 0, " + ".join(dynamic)), None

    # fallback: keep the symbolic base string as Offset{base: text, offset:0}
    return addr_offset(_strip_casts(text), 0), None


def _split_ternary_expr(text: str) -> tuple[str, str, str] | None:
    text = _strip_parens(text)
    depth = 0
    question = -1
    nested = 0
    for index, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and char == "?":
            if question < 0:
                question = index
            else:
                nested += 1
        elif depth == 0 and char == ":" and question >= 0:
            if nested:
                nested -= 1
            else:
                return (text[:question].strip(),
                        text[question + 1:index].strip(),
                        text[index + 1:].strip())
    return None


def _address_base_offset(text: str, store: dict, macros
                         ) -> tuple[str, str] | None:
    parts = _split_top(_strip_casts(text), "+")
    if len(parts) < 2:
        return None
    base = None
    offsets = []
    for part in parts:
        value = eval_expr(part, store, macros)
        if base is None and isinstance(value, BasePtr):
            base = value.base
        else:
            offsets.append(part.strip())
    if base is None or not offsets:
        return None
    return base, " + ".join(offsets)
