"""Cursor-level assignment scanning feeding the dataflow store."""
from __future__ import annotations
import re
import clang.cindex as cx

from .. import mmio
from ..taint import (
    BasePtr, Offset, Const, ReadTaint, SymExpr, Top, AbsVal,
)
from ..ast_model import walk_with_conditions, walk_with_control, source_text
from .expr_eval import _IDENT_RE, _address_base_offset, eval_expr
from .substitution import _substitute_text


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
        if cursor.kind in {
                cx.CursorKind.BINARY_OPERATOR,
                cx.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR}:
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
            "lhs": lhs, "operator": op,
            "rhs": rhs.strip(),
            "line": loc.line if loc else 0,
            "offset": loc.offset if loc else 0,
            "control": [dict(frame) for frame in control],
            "conditions": [frame.get("guard", "") for frame in control
                           if frame.get("guard")],
        })
    assignments.sort(key=lambda entry: (entry["offset"], entry["line"]))
    return assignments


_STATE_LHS_RE = re.compile(
    r"^[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+$")


def _state_assignment_entries(func_cursor, tu,
                               general_assignments: list[dict]) -> list[dict]:
    """Collect persistent member updates for functional-state evidence.

    Local temporaries remain internal dataflow facts. Member assignments and
    increments/decrements are emitted because they change state observed by
    later callbacks or by an inlined helper.
    """
    entries = [
        dict(entry) for entry in general_assignments
        if _STATE_LHS_RE.fullmatch(entry["lhs"].replace(" ", ""))
    ]
    seen = {
        (entry["offset"], entry["lhs"], entry["rhs"])
        for entry in entries
    }
    for cursor, control in walk_with_control(func_cursor):
        if cursor.kind != cx.CursorKind.UNARY_OPERATOR:
            continue
        text = source_text(tu, cursor).strip().rstrip(";").strip()
        match = re.match(
            r"^(?:(\+\+|--)\s*)?"
            r"([A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)+)"
            r"\s*(\+\+|--)?$",
            text)
        if not match:
            continue
        prefix, raw_lhs, suffix = match.groups()
        if not prefix and not suffix:
            continue
        lhs = raw_lhs.replace(" ", "")
        operator = prefix or suffix
        delta = "1" if operator == "++" else "-1"
        rhs = f"({lhs}) + ({delta})"
        loc = cursor.location
        offset = loc.offset if loc else 0
        key = (offset, lhs, rhs)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "lhs": lhs,
            "operator": "+=" if operator == "++" else "-=",
            "rhs": rhs,
            "line": loc.line if loc else 0,
            "offset": offset,
            "control": [dict(frame) for frame in control],
            "conditions": [
                frame.get("guard", "") for frame in control
                if frame.get("guard")
            ],
        })
    entries.sort(key=lambda entry: (entry["offset"], entry["line"]))
    return entries


def _local_value_entries(func_cursor, tu, general_assignments: list[dict],
                         calls: list) -> list[dict]:
    """Keep local assignments that feed a later call argument.

    Most locals are control-flow bookkeeping and should stay out of RIS. A
    local used by an MMIO wrapper argument is different: retaining its binding
    prevents a later state update from changing the meaning of a dereference
    that was evaluated before that update.
    """
    call_text = "\n".join(
        arg for call in calls for arg in (call.arg_text or []))
    entries = []
    for entry in general_assignments:
        lhs = entry["lhs"]
        loop_initializers = {
            frame.get("init", "").split("=", 1)[0].strip()
            for frame in entry.get("control", [])
            if frame.get("kind") == "loop" and "=" in frame.get("init", "")
        }
        if lhs in loop_initializers:
            # The enclosing Loop node owns its induction initializer. Emitting
            # a second ValueBind changes leaf ordering without adding state.
            continue
        if not _IDENT_RE.fullmatch(lhs) or not re.search(
                rf"\b{re.escape(lhs)}\b", call_text):
            continue
        item = dict(entry)
        item["kind"] = "ValueBind"
        entries.append(item)
    return entries


def _buffer_write_entries(func_cursor, tu) -> list[dict]:
    """Collect pointer-target assignments such as ``*rx = rxw``."""
    entries = []
    for cursor, control in walk_with_control(func_cursor):
        if cursor.kind not in {
                cx.CursorKind.BINARY_OPERATOR,
                cx.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR}:
            continue
        text = source_text(tu, cursor).strip()
        match = re.match(r"^(\*.+?)\s*=\s*(.+?)\s*;?$", text, re.S)
        if not match:
            continue
        target, value = match.groups()
        target = target.strip()
        if not target.startswith("*"):
            continue
        loc = cursor.location
        extent_end = cursor.extent.end
        entries.append({
            "kind": "OutputWrite",
            "target": target,
            "value": value.strip(),
            "line": loc.line if loc else 0,
            # Use the end of the assignment so calls in the RHS (for
            # example ``*rx = readl(base)``) are emitted first.
            "offset": (extent_end.offset if extent_end else
                       (loc.offset if loc else 0)),
            "control": [dict(frame) for frame in control],
            "conditions": [frame.get("guard", "") for frame in control
                           if frame.get("guard")],
        })
    entries.sort(key=lambda entry: (entry["offset"], entry["line"]))
    return entries


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


def _resolved_argument(arg: str, store: dict, macros) -> str:
    token = arg.strip()
    if _IDENT_RE.fullmatch(token) and macros.offset(token) is not None:
        return token
    return _abs_expr(eval_expr(arg, store, macros), arg)


def _general_assignment_store(assignments: list[dict], before_offset: int,
                              initial: dict, macros,
                              *, include_compound: bool = False) -> dict:
    store = dict(initial)
    for entry in assignments:
        if entry["offset"] and entry["offset"] >= before_offset:
            break
        if entry.get("operator") != "=" and not include_compound:
            continue
        lhs = entry["lhs"]
        # Preserve acyclic temporaries inside loops (bank offsets, array
        # selectors, context pointers), but keep induction variables and
        # self-dependent accumulators symbolic until a loop fixpoint exists.
        loop_frames = [frame for frame in entry["control"]
                       if frame.get("kind") == "loop"]
        if loop_frames:
            marker = "__reharness_self_reference"
            induction = any(
                _substitute_text(
                    " ".join((frame.get("init", ""),
                              frame.get("step", ""))), {lhs: marker})
                != " ".join((frame.get("init", ""), frame.get("step", "")))
                for frame in loop_frames)
            self_dependent = (
                _substitute_text(entry["rhs"], {lhs: marker}) != entry["rhs"])
            if induction or self_dependent:
                continue
        # A local assignment after an MMIO read may update the value before a
        # wrapper write. Keep the read taint as the producer; _rmw_transform
        # reconstructs the intervening expression from source order.
        if isinstance(store.get(lhs), ReadTaint):
            continue
        scalar_mapping = {
            name: _abs_expr(item, name) for name, item in store.items()
            if _IDENT_RE.fullmatch(name) and not isinstance(item, Top)
        }
        rhs = _substitute_text(entry["rhs"], scalar_mapping) or entry["rhs"]
        value = eval_expr(rhs, store, macros)
        if isinstance(value, Top):
            value = SymExpr(rhs)
        loop_guards = {frame.get("guard", "") for frame in loop_frames}
        conditions = [
            condition for condition in entry["conditions"]
            if condition and condition not in loop_guards
            and "scoped_guard" not in condition
            and "gpio_generic_lock" not in condition]
        # A loop-carried assignment cannot be represented as one exact scalar
        # state without a fixpoint. Keep its expression but mark it with the
        # loop guard so downstream reliability remains conservative.
        if conditions:
            old = store.get(lhs, SymExpr(lhs))
            guard = " && ".join(f"({condition})" for condition in conditions)
            store[lhs] = SymExpr(
                f"(({guard}) ? ({_abs_expr(value, rhs)})"
                f" : ({_abs_expr(old, lhs)}))")
        else:
            store[lhs] = value
    return store

