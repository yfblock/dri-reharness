"""Flow-sensitive intra-procedural dataflow + taint tracking.

Walks each function's calls in source order, maintaining an abstract store
(var -> AbsVal). At each MMIO call it resolves the address argument to a
RegAddr via the store + macro table, records branch conditions, and detects
read-modify-write patterns (readl→modify→writel on the same address).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

from . import mmio
from . import taint as T
from .taint import (
    BasePtr, Offset, ReadTaint, Const, SymExpr, Top, AbsVal,
    addr_fixed, addr_offset, addr_indirect, addr_equal,
)
from .ast_model import Func, function_calls, walk_with_conditions, source_text

BASE_FIELDS = {"base", "base_addr", "regs", "io_base", "mmio_base",
               "reg_base", "virtbase", "base0", "base1"}

_CONTROL_KW = {"if", "for", "while", "switch", "return", "sizeof", "typeof"}


@dataclass
class Op:
    kind: str                       # Read | Write | ReadModifyWrite | Delay
    addr: dict
    width: int
    value: Optional[str] = None
    condition: Optional[str] = None
    intent: str = "Unknown"
    source_loc: Optional[str] = None
    reg_name: Optional[str] = None  # resolved register macro name (internal)
    line: int = 0
    var: Optional[str] = None       # Read LHS variable (for formal `x := R(...)`)
    cond_stack: list = field(default_factory=list)  # full branch predicate stack


# ── expression evaluation ────────────────────────────────────────────

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
            if sep == "<" and i + 1 < n and text[i + 1] == "<":
                cur += ch
                i += 1
                continue
            if sep == ">" and i - 1 >= 0 and text[i - 1] == ">":
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

    # Symbolic offset on a base: preserve the full dynamic offset expression.
    # The former representation kept only the base and silently discarded
    # terms such as (1 << (offset + 2)) or offset + i.
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


# ── function extraction ──────────────────────────────────────────────

@dataclass
class FuncExtraction:
    name: str
    params: list[str] = field(default_factory=list)
    ops: list[Op] = field(default_factory=list)
    calls: list = field(default_factory=list)   # CallSite list (for call graph)
    warnings: list[str] = field(default_factory=list)


def _substitute_text(text: Optional[str], mapping: dict[str, str]) -> Optional[str]:
    if not text or not mapping:
        return text
    names = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(name) for name in names) + r")\b")

    def replace(match):
        before = text[:match.start()].rstrip()
        # A field token named like a parameter is not a parameter reference.
        if before.endswith(("->", ".")):
            return match.group(0)
        return mapping.get(match.group(0), match.group(0))

    return pattern.sub(replace, text)


def _substitute_addr(addr: dict, mapping: dict[str, str]) -> dict:
    import copy
    out = copy.deepcopy(addr)
    if "Offset" in out:
        out["Offset"]["base"] = _substitute_text(
            out["Offset"].get("base"), mapping) or ""
    elif "Indirect" in out:
        out["Indirect"]["base_reg"] = _substitute_text(
            out["Indirect"].get("base_reg"), mapping) or ""
        if out["Indirect"].get("expr"):
            out["Indirect"]["expr"] = _substitute_text(
                out["Indirect"]["expr"], mapping)
    return out


def _instantiate_op(op: Op, mapping: dict[str, str], macros=None) -> Op:
    import copy
    out = copy.copy(op)
    out.addr = _substitute_addr(op.addr, mapping)
    out.value = _substitute_text(op.value, mapping)
    out.condition = _substitute_text(op.condition, mapping)
    out.cond_stack = [
        _substitute_text(condition, mapping) or condition
        for condition in op.cond_stack]
    out.var = _substitute_text(op.var, mapping)
    indirect = out.addr.get("Indirect")
    if indirect and macros is not None:
        expr = (indirect.get("expr") or "").strip()
        offset = macros.offset(expr) if expr else None
        if offset is not None:
            out.addr = addr_offset(indirect.get("base_reg", ""), offset)
            out.reg_name = expr
    return out


def _assign_target(lhs_text: str) -> Optional[str]:
    """From an assignment LHS, the store key to bind."""
    lhs = lhs_text.strip()
    if _MEMBER_RE.match(lhs) or _IDENT_RE.match(lhs):
        return lhs
    return None


_LHS_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*(?:->|\.)\s*\w+)*)\s*=\s*(?!=)")
_LHS_CONT_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*(?:->|\.)\s*\w+)*)\s*=\s*$")


def _bind_lhs(source_lines: list[str], call_line: int, call_name: str) -> Optional[str]:
    """Find the LHS variable assigned by a call on `call_line`.

    Handles `var = call(...)` on one line and `var =\n  call(...)` across two.
    """
    if call_line <= 0 or call_line > len(source_lines):
        return None
    line = source_lines[call_line - 1]
    # same line: var = callname(
    m = _LHS_RE.match(line)
    if m and call_name and call_name in line:
        lhs = m.group(1).replace(" ", "")
        return lhs
    # continuation: previous line ends with `var =`
    if call_line > 1:
        prev = source_lines[call_line - 2]
        m2 = _LHS_CONT_RE.match(prev)
        if m2:
            return m2.group(1).replace(" ", "")
    return None


def _norm_key(lhs: str) -> str:
    return lhs.replace(" ", "")


_MUTATION_OP = re.compile(
    r"\b{var}\s*(<<=|>>=|\|=|&=|\^=|\+=|-=|=)\s*([^;]+);"
)


def _apply_mutation(expr: str, op: str, rhs: str) -> str:
    op_map = {"|=": "|", "&=": "&", "^=": "^", "+=": "+", "-=": "-",
              "<<=": "<<", ">>=": ">>"}
    rhs = rhs.strip()
    return rhs if op == "=" else f"({expr} {op_map[op]} ({rhs}))"


def _switch_rmw_transform(var: str, between: str, initial: str) -> Optional[str]:
    """Build a nested conditional expression for switch-dependent mutations."""
    sm = re.search(r"\bswitch\s*\(\s*([^()]+?)\s*\)\s*\{", between)
    if not sm:
        return None
    selector = sm.group(1).strip()
    start = sm.end() - 1
    depth = 0
    end = None
    for i in range(start, len(between)):
        if between[i] == "{":
            depth += 1
        elif between[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return None
    block = between[start + 1:end]
    labels = list(re.finditer(r"\b(case\s+([^:]+)|default)\s*:", block))
    if not labels:
        return None
    pattern = re.compile(_MUTATION_OP.pattern.format(var=re.escape(var)))
    branches: list[tuple[list[str], str]] = []
    pending: list[str] = []
    fallback = initial
    for idx, label in enumerate(labels):
        seg_end = labels[idx + 1].start() if idx + 1 < len(labels) else len(block)
        segment = block[label.end():seg_end]
        case_name = label.group(2)
        changes = pattern.findall(segment)
        if case_name is None:
            expr = initial
            for op, rhs in changes:
                expr = _apply_mutation(expr, op, rhs)
            fallback = expr
            pending.clear()
            continue
        pending.append(case_name.strip())
        if not changes and "break" not in segment and "return" not in segment:
            continue
        expr = initial
        for op, rhs in changes:
            expr = _apply_mutation(expr, op, rhs)
        branches.append((pending[:], expr))
        pending.clear()
    expr = fallback
    for case_names, branch_expr in reversed(branches):
        guard = " || ".join(f"({selector} == {name})" for name in case_names)
        expr = f"(({guard}) ? ({branch_expr}) : ({expr}))"
    return expr


def _rmw_transform(var: str, read_line: int, write_line: int,
                   source_lines: list[str], line_conditions: dict[int, list[str]],
                   initial: str | None = None) -> Optional[str]:
    """Recover straight-line and branch-dependent mutations as ITEs."""
    between = "\n".join(source_lines[read_line: max(read_line, write_line - 1)])
    pattern = re.compile(_MUTATION_OP.pattern.format(var=re.escape(var)))
    base = initial or var
    switch_expr = _switch_rmw_transform(var, between, base)
    if switch_expr is not None:
        return switch_expr
    matches = list(pattern.finditer(between))
    if not matches:
        return base
    unconditional: list[tuple[str, str]] = []
    conditional: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    for match in matches:
        line = read_line + between[:match.start()].count("\n") + 1
        stack = tuple(c for c in line_conditions.get(line, [])
                      if "scoped_guard" not in c and "gpio_generic_lock" not in c)
        item = (match.group(1), match.group(2))
        if stack:
            conditional.setdefault(stack, []).append(item)
        else:
            unconditional.append(item)
    expr = base
    for op, rhs in unconditional:
        expr = _apply_mutation(expr, op, rhs)
    for stack, changes in reversed(list(conditional.items())):
        branch = base
        for op, rhs in changes:
            branch = _apply_mutation(branch, op, rhs)
        guard = " && ".join(f"({c})" for c in stack)
        expr = f"(({guard}) ? ({branch}) : ({expr}))"
    return expr


def _read_initial_transform(lhs: str, cs, source_lines: list[str], tu) -> str:
    """Preserve operations wrapped around a read call on its assignment line."""
    if cs.line <= 0 or cs.line > len(source_lines):
        return lhs
    line = source_lines[cs.line - 1]
    m = re.search(rf"\b{re.escape(lhs)}\s*=\s*(.+);", line)
    if not m:
        return lhs
    rhs = m.group(1).strip()
    call = source_text(tu, cs.cursor).strip()
    if call and call in rhs:
        return rhs.replace(call, lhs, 1)
    return lhs


def extract_function(func: Func, macros, tu, *,
                     source_lines: Optional[list[str]] = None,
                     inline_cache: Optional[dict] = None,
                     mmio_globals: Optional[list[str]] = None,
                     depth: int = 0, max_depth: int = 3,
                     condition: Optional[str] = None,
                     include_framework: bool = False,
                     extra_blacklist: Optional[set[str]] = None) -> FuncExtraction:
    """Extract register ops for one function (with wrapper inlining)."""
    result = FuncExtraction(
        name=func.name, params=[name for name, _type in func.params if name])
    store: dict[str, AbsVal] = {}
    read_origins: dict[str, tuple[dict, int]] = {}
    read_initial: dict[str, str] = {}
    # seed file-scope MMIO base globals (e.g. `static void __iomem *mmio`)
    for g in (mmio_globals or []):
        store[g] = BasePtr(g)
    # seed params — iomem/pointer params are MMIO base candidates
    for pname, ptype in func.params:
        if not pname:
            continue
        if ptype and ("__iomem" in ptype or "void *" in ptype or ptype.endswith("*")):
            store[pname] = BasePtr(pname)
        else:
            store[pname] = SymExpr(pname)

    calls = function_calls(func.cursor)
    result.calls = calls

    # map line → condition stack (path-insensitive: innermost branch pred)
    line_to_cond: dict[int, list[str]] = {}
    for cursor, stack in walk_with_conditions(func.cursor):
        if cursor.location and cursor.location.file:
            ln = cursor.location.line
            if stack:
                line_to_cond.setdefault(ln, stack)

    for cs in calls:
        name = cs.name
        if not name or name in _CONTROL_KW:
            continue
        if name in (extra_blacklist or set()):
            continue
        cond = None
        cond_stack = []
        if cs.line in line_to_cond:
            st = [c for c in line_to_cond[cs.line]
                  if "scoped_guard" not in c and "gpio_generic_lock" not in c]
            if st:
                cond_stack = list(st)
                cond = st[-1]

        lhs = _bind_lhs(source_lines or [], cs.line, name)

        # ioremap → taint LHS as BasePtr
        if mmio.is_ioremap(name):
            if lhs:
                store[_norm_key(lhs)] = BasePtr(lhs)
            continue

        if mmio.is_mmio_read(name):
            addr_arg = mmio.read_addr_expr(name, cs.arg_text)
            addr, reg_name = resolve_addr(addr_arg, store, macros)
            op = Op(
                kind="Read", addr=addr, width=mmio.infer_width(name),
                value=None, condition=cond, cond_stack=cond_stack,
                reg_name=reg_name, var=lhs or None,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
            )
            result.ops.append(op)
            if lhs:
                key = _norm_key(lhs)
                store[key] = ReadTaint(addr=addr, reg_name=reg_name)
                read_origins[key] = (addr, cs.line)
                read_initial[key] = _read_initial_transform(
                    key, cs, source_lines or [], tu)
            continue

        if mmio.is_mmio_write(name):
            # Generic Linux writel(val, addr), plus explicitly modeled
            # driver-private wrappers such as dwc2_writel(state, val, off).
            val_text, addr_text = mmio.write_value_addr(name, cs.arg_text)
            addr, reg_name = resolve_addr(addr_text, store, macros)
            val = eval_expr(val_text, store, macros)
            kind = "Write"
            value = val_text.strip() or None
            rmw_var = None
            # RMW: value is a read-taint of the SAME address
            if isinstance(val, ReadTaint) and addr_equal(val.addr, addr):
                kind = "ReadModifyWrite"
                key = _norm_key(val_text.strip())
                origin = read_origins.get(key)
                if origin and addr_equal(origin[0], addr):
                    rmw_var = key
                    value = _rmw_transform(
                        key, origin[1], cs.line, source_lines or [],
                        line_to_cond, read_initial.get(key))
            op = Op(
                kind=kind, addr=addr, width=mmio.infer_width(name),
                value=value, condition=cond, cond_stack=cond_stack,
                reg_name=reg_name,
                var=rmw_var,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
            )
            result.ops.append(op)
            continue

        if mmio.is_delay(name):
            arg = cs.arg_text[0] if cs.arg_text else "0"
            ns = _parse_delay_ns(name, arg)
            op = Op(
                kind="Delay", addr=addr_fixed(0), width=0,
                value=str(ns), condition=cond, cond_stack=cond_stack,
                intent="Synchronization",
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
            )
            op._delay_ns = ns  # type: ignore[attr-defined]
            result.ops.append(op)
            continue

        # framework → ignore (filtered)
        if not include_framework and mmio.is_framework(name):
            continue

        # wrapper function inlining
        callee_key = cs.symbol_id or name
        inlined = ((inline_cache or {}).get(callee_key)
                   or (inline_cache or {}).get(name))
        if inlined is not None and depth < max_depth:
            if inlined.ops:
                mapping = {
                    param: arg for param, arg in zip(inlined.params, cs.arg_text)
                    if param and arg
                }
                for op in inlined.ops:
                    o2 = _instantiate_op(op, mapping, macros)
                    o2.condition = cond or o2.condition
                    o2.cond_stack = cond_stack or o2.cond_stack
                    o2.source_loc = f"{func.name}:{cs.line} (↳ {op.source_loc})"
                    result.ops.append(o2)

    return result


def _parse_delay_ns(name: str, arg: str) -> int:
    try:
        n = int(arg, 0)
    except Exception:
        return 0
    if name in ("mdelay", "msleep", "ssleep"):
        return n * 1_000_000
    if name == "udelay":
        return n * 1000
    if name == "ndelay":
        return n
    return n
