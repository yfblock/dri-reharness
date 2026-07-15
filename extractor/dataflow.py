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
import clang.cindex as cx

from . import mmio
from . import taint as T
from .taint import (
    BasePtr, Offset, ReadTaint, Const, SymExpr, Top, AbsVal,
    addr_fixed, addr_offset, addr_indirect, addr_equal, addr_base_of,
    val_to_value_str,
)
from .ast_model import (Func, function_calls, walk_with_conditions,
                        walk_with_control, continuation_guards, source_text)

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
    control_stack: list = field(default_factory=list)  # structured cond/loop frames
    evidence: dict = field(default_factory=dict)    # auditable source provenance


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


def _plain_pointer_assignments(func_cursor, tu, store: dict, macros) -> list[dict]:
    """Collect branch-guarded assignments of local MMIO pointer variables."""
    assignments = []
    for cursor, stack in walk_with_conditions(func_cursor):
        if cursor.kind != cx.CursorKind.BINARY_OPERATOR:
            continue
        text = source_text(tu, cursor).strip().rstrip(";")
        match = re.fullmatch(
            r"([A-Za-z_]\w*)\s*=\s*(?!=)(.+)", text, flags=re.S)
        if not match:
            continue
        lhs, rhs = match.group(1), match.group(2).strip()
        if _address_base_offset(rhs, store, macros) is None:
            continue
        assignments.append({
            "lhs": lhs,
            "rhs": rhs,
            "conditions": [condition for condition in stack if condition],
            "line": cursor.location.line if cursor.location else 0,
        })
    return assignments


def _pointer_assignment_store(assignments: list[dict], before_line: int
                              ) -> dict[str, SymExpr]:
    grouped: dict[str, list[dict]] = {}
    for assignment in assignments:
        if assignment["line"] and assignment["line"] < before_line:
            grouped.setdefault(assignment["lhs"], []).append(assignment)
    out: dict[str, SymExpr] = {}
    for lhs, entries in grouped.items():
        unconditional = [entry for entry in entries if not entry["conditions"]]
        conditional = [entry for entry in entries if entry["conditions"]]
        fallback = unconditional[-1]["rhs"] if unconditional else None
        used: set[int] = set()
        expression = fallback
        for index, entry in enumerate(conditional):
            if index in used:
                continue
            guard = " && ".join(entry["conditions"])
            complement = f"!({guard})"
            pair = next((
                (other_index, other) for other_index, other in enumerate(conditional)
                if other_index != index and other_index not in used
                and " && ".join(other["conditions"]) == complement
            ), None)
            if pair is not None:
                other_index, other = pair
                expression = (f"(({guard}) ? ({entry['rhs']})"
                              f" : ({other['rhs']}))")
                used.update({index, other_index})
                continue
            if expression is not None:
                expression = (f"(({guard}) ? ({entry['rhs']})"
                              f" : ({expression}))")
                used.add(index)
        if expression is not None:
            out[lhs] = SymExpr(expression)
    return out


_GENERAL_ASSIGN_RE = re.compile(
    r"^\s*([A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*)\s*"
    r"(=|\+=|-=|\|=|&=|\^=|<<=|>>=)\s*(?!=)(.+?)\s*;?\s*$", re.S)


def _general_assignments(func_cursor, tu) -> list[dict]:
    """Collect ordinary scalar/member assignments with lexical path evidence."""
    assignments: list[dict] = []
    for cursor, control in walk_with_control(func_cursor):
        text = source_text(tu, cursor).strip()
        lhs = op = rhs = None
        if cursor.kind == cx.CursorKind.BINARY_OPERATOR:
            match = _GENERAL_ASSIGN_RE.match(text)
            if match:
                lhs, op, rhs = match.groups()
        elif cursor.kind == cx.CursorKind.VAR_DECL and "=" in text:
            match = re.match(
                rf".*?\b{re.escape(cursor.spelling)}\s*=\s*(.+?)\s*;?\s*$",
                text, re.S)
            if match:
                lhs, op, rhs = cursor.spelling, "=", match.group(1)
        if not lhs or rhs is None:
            continue
        lhs = re.sub(r"\s+", "", lhs)
        # MMIO/ioremap call assignments are modeled by the call interpreter,
        # which also attaches read taint and source evidence.
        calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", rhs))
        if any(mmio.is_mmio_read(name) or mmio.is_mmio_rmw(name)
               or mmio.is_ioremap(name)
               for name in calls):
            continue
        # Do not substitute the result of an arbitrary helper call as though
        # it were an understood scalar expression.  That previously turned
        # e.g. ``deb_div`` into ``DIV_ROUND_CLOSEST(...)`` even though the
        # extractor has no summary for that helper, overstating precision and
        # making otherwise valid backend locals impossible to bind.  Retain a
        # small, explicitly expression-like macro allowlist whose semantics
        # are preserved by the formal expression/code generators.
        expression_macros = {
            "BIT", "BIT_ULL", "GENMASK", "GENMASK_ULL",
            "FIELD_GET", "FIELD_PREP", "lower_32_bits", "upper_32_bits",
        }
        if calls - expression_macros:
            continue
        if op != "=":
            rhs = f"({lhs}) {op[:-1]} ({rhs})"
        loc = cursor.location
        assignments.append({
            "lhs": lhs,
            "rhs": rhs.strip(),
            "line": loc.line if loc else 0,
            "offset": loc.offset if loc else 0,
            "control": [dict(frame) for frame in control],
            "conditions": [frame.get("guard", "") for frame in control
                           if frame.get("guard")],
        })
    assignments.sort(key=lambda entry: (entry["offset"], entry["line"]))
    return assignments


def _abs_expr(value: AbsVal, fallback: str) -> str:
    if isinstance(value, Const):
        return hex(value.n) if value.n >= 0 else str(value.n)
    if isinstance(value, BasePtr):
        return value.base
    if isinstance(value, Offset):
        return f"({value.base}) + ({value.off})" if value.base else str(value.off)
    if isinstance(value, SymExpr):
        return value.text
    return fallback


def _general_assignment_store(assignments: list[dict], before_offset: int,
                              initial: dict, macros) -> dict:
    store = dict(initial)
    for entry in assignments:
        if entry["offset"] and entry["offset"] >= before_offset:
            break
        # Loop-carried state requires a fixpoint.  Applying the initializer as
        # a guarded scalar assignment at every operation incorrectly froze the
        # induction variable (e.g. ``i`` became ``i < 4 ? 0 : i``).  Leave it
        # symbolic; the formal Loop node carries the exact induction semantics
        # when a bound is proved, or remains conservative otherwise.
        if any(frame.get("kind") == "loop" for frame in entry["control"]):
            continue
        lhs = entry["lhs"]
        value = eval_expr(entry["rhs"], store, macros)
        conditions = [condition for condition in entry["conditions"] if condition]
        # A loop-carried assignment cannot be represented as one exact scalar
        # state without a fixpoint. Keep its expression but mark it with the
        # loop guard so downstream reliability remains conservative.
        if conditions:
            old = store.get(lhs, SymExpr(lhs))
            guard = " && ".join(f"({condition})" for condition in conditions)
            store[lhs] = SymExpr(
                f"(({guard}) ? ({_abs_expr(value, entry['rhs'])})"
                f" : ({_abs_expr(old, lhs)}))")
        else:
            store[lhs] = value
    return store


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
    out.evidence = copy.deepcopy(op.evidence)
    out.addr = _substitute_addr(op.addr, mapping)
    out.value = _substitute_text(op.value, mapping)
    out.condition = _substitute_text(op.condition, mapping)
    out.cond_stack = [
        _substitute_text(condition, mapping) or condition
        for condition in op.cond_stack]
    out.control_stack = []
    for frame in op.control_stack:
        copied = dict(frame)
        for key in ("guard", "init", "step"):
            if copied.get(key):
                copied[key] = _substitute_text(copied[key], mapping)
        out.control_stack.append(copied)
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
                     mmio_alias_facts: Optional[dict[str, dict]] = None,
                     wrapper_summaries: Optional[dict[str, dict]] = None,
                     indirect_targets: Optional[dict[str, str]] = None,
                     callback_entries: Optional[set[str]] = None,
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

    pointer_assignments = _plain_pointer_assignments(
        func.cursor, tu, store, macros)
    general_assignments = _general_assignments(func.cursor, tu)
    continuation, _modeled_exits = continuation_guards(func.cursor)

    calls = function_calls(func.cursor)
    result.calls = calls

    def evidence_for(cs, kind: str, addr: dict,
                     source_address: str = "") -> dict:
        from .accounting import callsite_evidence
        evidence = callsite_evidence(func, cs, kind)
        base = addr_base_of(addr) or ""
        for alias, fact in (mmio_alias_facts or {}).items():
            referenced = bool(re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                source_address or ""))
            if (base == alias or base.startswith(alias + "->")
                    or base.startswith(alias + ".") or referenced):
                evidence["alias_provenance"] = {"name": alias, **fact}
                break
        return evidence

    # map line → structured lexical control stack
    line_to_cond: dict[int, list[str]] = {}
    line_to_control: dict[int, list[dict]] = {}
    for cursor, stack in walk_with_control(func.cursor):
        if cursor.location and cursor.location.file:
            ln = cursor.location.line
            filtered_stack = [
                frame for frame in stack
                if "scoped_guard" not in frame.get("guard", "")
                and "gpio_generic_lock" not in frame.get("guard", "")
            ]
            if filtered_stack:
                line_to_control.setdefault(ln, filtered_stack)
                line_to_cond.setdefault(
                    ln, [frame.get("guard", "") for frame in filtered_stack
                         if frame.get("guard")])

    for cs in calls:
        name = cs.name
        if not name or name in _CONTROL_KW:
            continue
        if name in (extra_blacklist or set()):
            continue
        cond = None
        cond_stack = []
        control_stack = []
        if cs.line in line_to_cond:
            st = [c for c in line_to_cond[cs.line]
                  if "scoped_guard" not in c and "gpio_generic_lock" not in c]
            if st:
                cond_stack = list(st)
                cond = st[-1]
        if cs.line in line_to_control:
            control_stack = [dict(frame) for frame in line_to_control[cs.line]]

        call_offset = (cs.cursor.location.offset
                       if cs.cursor.location is not None else 0)
        for transition in continuation:
            if transition["after_offset"] and transition["after_offset"] <= call_offset:
                frame = dict(transition["frame"])
                control_stack.insert(0, frame)
                if frame.get("guard"):
                    cond_stack.insert(0, frame["guard"])
                    cond = cond or frame["guard"]

        lhs = _bind_lhs(source_lines or [], cs.line, name)
        call_store = dict(store)
        call_store.update(_general_assignment_store(
            general_assignments, call_offset, call_store, macros))
        call_store.update(_pointer_assignment_store(
            pointer_assignments, cs.line))

        # ioremap → taint LHS as BasePtr
        if mmio.is_ioremap(name):
            if lhs:
                store[_norm_key(lhs)] = BasePtr(lhs)
            continue

        if mmio.is_mmio_read(name):
            addr_arg = mmio.read_addr_expr(name, cs.arg_text)
            addr, reg_name = resolve_addr(addr_arg, call_store, macros)
            op = Op(
                kind="Read", addr=addr, width=mmio.infer_width(name),
                value=None, condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                reg_name=reg_name,
                var=mmio.read_result_var(name, cs.arg_text, lhs) or None,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
                evidence=evidence_for(cs, "read", addr, addr_arg),
            )
            result.ops.append(op)
            result_var = mmio.read_result_var(name, cs.arg_text, lhs)
            if result_var:
                key = _norm_key(result_var)
                store[key] = ReadTaint(addr=addr, reg_name=reg_name)
                read_origins[key] = (addr, cs.line)
                read_initial[key] = _read_initial_transform(
                    key, cs, source_lines or [], tu)
            continue

        if mmio.is_mmio_rmw(name):
            parts = mmio.rmw_parts(name, cs.arg_text)
            if parts is None:
                result.warnings.append(
                    f"cannot decode register RMW call {name} at line {cs.line}")
                continue
            address_text, mask_text, update_text = parts
            addr, reg_name = resolve_addr(address_text, call_store, macros)
            transform = (f"((__old & ~({mask_text})) | "
                         f"(({update_text}) & ({mask_text})))")
            result.ops.append(Op(
                kind="ReadModifyWrite", addr=addr,
                width=mmio.infer_width(name), value=transform,
                condition=cond, cond_stack=cond_stack,
                control_stack=control_stack, reg_name=reg_name,
                var="__old", source_loc=f"{func.name}:{cs.line}",
                line=cs.line,
                evidence=evidence_for(cs, "rmw", addr, address_text)))
            continue

        if mmio.is_mmio_write(name):
            # Generic Linux writel(val, addr), plus explicitly modeled
            # driver-private wrappers such as dwc2_writel(state, val, off).
            val_text, addr_text = mmio.write_value_addr(name, cs.arg_text)
            addr, reg_name = resolve_addr(addr_text, call_store, macros)
            val = eval_expr(val_text, call_store, macros)
            kind = "Write"
            value = val_to_value_str(val) or val_text.strip() or None
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
                control_stack=control_stack,
                reg_name=reg_name,
                var=rmw_var,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
                evidence=evidence_for(cs, "write", addr, addr_text),
            )
            result.ops.append(op)
            continue

        if mmio.is_delay(name):
            arg = cs.arg_text[0] if cs.arg_text else "0"
            ns = _parse_delay_ns(name, arg)
            op = Op(
                kind="Delay", addr=addr_fixed(0), width=0,
                value=str(ns), condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                intent="Synchronization",
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
            )
            op._delay_ns = ns  # type: ignore[attr-defined]
            result.ops.append(op)
            continue

        from .indirect import resolve_indirect_call
        indirect_target = resolve_indirect_call(cs, indirect_targets or {})
        callee_key = indirect_target or cs.symbol_id or name
        resolved_name = indirect_target or name
        inlined = ((inline_cache or {}).get(callee_key)
                   or (inline_cache or {}).get(resolved_name))
        summary = ((wrapper_summaries or {}).get(callee_key)
                   or (wrapper_summaries or {}).get(resolved_name))
        # A function registered as a callback is an independent entry point.
        # A direct C call to it must not duplicate its MMIO body in another
        # module.  An actual indirect ops-table dispatch is different: the
        # call-site semantics depend on resolving that target, so propagation
        # remains enabled for ``indirect_target``.
        if (not indirect_target
                and callee_key in (callback_entries or set())):
            inlined = None
            summary = None
        if (inlined is None or depth >= max_depth) and summary is not None:
            import copy
            mapping = {
                param: arg for param, arg in zip(
                    summary.get("params", []), cs.arg_text)
                if param and arg
            }
            address_text = _substitute_text(
                summary.get("address"), mapping) or ""
            addr, reg_name = resolve_addr(address_text, call_store, macros)
            evidence = copy.deepcopy(summary.get("evidence", {}))
            evidence["origin"] = "wrapper_summary"
            evidence.setdefault("summarized_at", []).append({
                "function": func.name, "line": cs.line,
                "callee": resolved_name, "source_loc": func.source_path,
                "indirect_expression": cs.callee_text if indirect_target else None,
            })
            if summary["kind"] == "Read":
                op = Op(
                    kind="Read", addr=addr, width=summary["width"],
                    value=None, condition=cond, cond_stack=cond_stack,
                    control_stack=control_stack, reg_name=reg_name,
                    var=lhs or None, evidence=evidence,
                    source_loc=f"{func.name}:{cs.line} (summary {resolved_name})",
                    line=cs.line)
                result.ops.append(op)
                if lhs:
                    key = _norm_key(lhs)
                    store[key] = ReadTaint(addr=addr, reg_name=reg_name)
                    read_origins[key] = (addr, cs.line)
                    read_initial[key] = key
            else:
                raw_value = _substitute_text(
                    summary.get("value"), mapping) or ""
                abstract_value = eval_expr(raw_value, call_store, macros)
                value = val_to_value_str(abstract_value) or raw_value or None
                result.ops.append(Op(
                    kind="Write", addr=addr, width=summary["width"],
                    value=value, condition=cond, cond_stack=cond_stack,
                    control_stack=control_stack, reg_name=reg_name,
                    evidence=evidence,
                    source_loc=f"{func.name}:{cs.line} (summary {resolved_name})",
                    line=cs.line))
            continue

        # framework → ignore (filtered)
        if not include_framework and mmio.is_framework(name):
            continue

        # wrapper function inlining
        if inlined is not None and depth < max_depth:
            if inlined.ops:
                mapping = {
                    param: arg for param, arg in zip(inlined.params, cs.arg_text)
                    if param and arg
                }
                for op in inlined.ops:
                    o2 = _instantiate_op(op, mapping, macros)
                    o2.condition = cond or o2.condition
                    o2.cond_stack = cond_stack + o2.cond_stack
                    o2.control_stack = control_stack + o2.control_stack
                    o2.source_loc = f"{func.name}:{cs.line} (↳ {op.source_loc})"
                    o2.evidence.setdefault("inlined_at", []).append({
                        "function": func.name,
                        "line": cs.line,
                        "callee": resolved_name,
                        "indirect_expression": cs.callee_text
                        if indirect_target else None,
                    })
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
