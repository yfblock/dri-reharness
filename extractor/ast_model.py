"""AST model: target-file functions, call sites, source-text helpers.

libclang gives correct function boundaries, call structure, line numbers,
and control-flow nesting — the structural substrate over which the string-
based dataflow evaluator (dataflow.py) runs.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Iterator
import clang.cindex as cx


def _abs(path: str | None) -> str | None:
    return os.path.abspath(path) if path else None


def in_file(cursor, target_file: str) -> bool:
    f = cursor.location.file
    return f is not None and _abs(f.name) == _abs(target_file)


def source_text(tu, cursor) -> str:
    """Source substring covered by `cursor`'s extent.

    libclang `.offset` is a BYTE offset, so the file is read in binary and
    the byte slice is decoded — text-mode reading would misalign offsets
    whenever the file contains CRLF or multibyte characters."""
    try:
        start = cursor.extent.start
        end = cursor.extent.end
        f = start.file
        if f is None:
            return ""
        with open(f.name, "rb") as fh:
            data = fh.read()
        a = start.offset
        b = end.offset
        if a is None or b is None or b < a:
            return ""
        return data[a:b].decode("utf-8", errors="replace")
    except Exception:
        # fallback: token join (token spellings are position-correct)
        return "".join(t.spelling for t in cursor.get_tokens())


@dataclass
class CallSite:
    name: str                       # callee spelling ("" if unresolved)
    symbol_id: str                  # linker/static source-qualified identity
    args: list                      # list of arg cursors
    line: int
    cursor: object
    arg_text: list[str] = field(default_factory=list)  # source text per arg
    callee_text: str = ""             # exact source spelling of callee expression


@dataclass
class Func:
    name: str
    line: int
    cursor: object
    params: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    source_path: str = ""
    symbol_id: str = ""
    module_name: str = ""
    is_static: bool = False


def function_symbol_id(cursor) -> str:
    """Return linker identity, qualifying file-local static functions."""
    if cursor is None or cursor.kind != cx.CursorKind.FUNCTION_DECL:
        return ""
    name = cursor.spelling or ""
    if not name:
        return ""
    if cursor.storage_class == cx.StorageClass.STATIC:
        loc = cursor.location
        path = _abs(loc.file.name) if loc and loc.file else "?"
        return f"{path}::{name}"
    return name


def call_symbol_id(call_cursor) -> str:
    ref = call_cursor.referenced
    if ref is not None and ref.kind == cx.CursorKind.FUNCTION_DECL:
        return function_symbol_id(ref)
    children = list(call_cursor.get_children())
    if children:
        for sub in children[0].walk_preorder():
            ref = sub.referenced
            if ref is not None and ref.kind == cx.CursorKind.FUNCTION_DECL:
                return function_symbol_id(ref)
    return callee_name(call_cursor)


def callee_name(call_cursor) -> str:
    """Resolve the called function's name.

    Descends into the callee subtree (the CallExpr's first child) to find a
    DeclRefExpr, so parenthesized calls like `(helper)()` resolve correctly —
    the callee is an UnexposedExpr/ParenExpr wrapping the DeclRefExpr, and
    `call_cursor.referenced` is None for such forms.
    """
    ref = call_cursor.referenced
    if ref is not None and ref.spelling:
        return ref.spelling
    children = list(call_cursor.get_children())
    if children:
        for sub in children[0].walk_preorder():
            if sub.kind == cx.CursorKind.DECL_REF_EXPR:
                r = sub.referenced
                if r is not None and r.spelling:
                    return r.spelling
                if sub.spelling:   # unresolved/undeclared ref (e.g. macro)
                    return sub.spelling
    return call_cursor.spelling or ""


def call_arguments(call_cursor) -> list:
    return list(call_cursor.get_arguments())


def function_calls(func_cursor) -> list[CallSite]:
    """All CallExpr in a function body, in source order."""
    calls: list[CallSite] = []
    for c in func_cursor.walk_preorder():
        if c.kind == cx.CursorKind.CALL_EXPR:
            args = call_arguments(c)
            children = list(c.get_children())
            callee_text = source_text(c.translation_unit, children[0]).strip() \
                if children else ""
            line = c.location.line if c.location and c.location.file else 0
            cs = CallSite(
                name=callee_name(c),
                symbol_id=call_symbol_id(c),
                args=args,
                line=line,
                cursor=c,
                arg_text=[source_text(c.translation_unit, a) for a in args],
                callee_text=callee_text,
            )
            calls.append(cs)
    calls.sort(key=lambda c: c.line)
    return calls


def target_functions(tu, target_file: str) -> list[Func]:
    """FUNCTION_DECLs defined in `target_file`."""
    funcs: list[Func] = []
    for c in tu.cursor.walk_preorder():
        if (c.kind == cx.CursorKind.FUNCTION_DECL and c.is_definition()
                and in_file(c, target_file)):
            params = []
            for p in c.get_children():
                if p.kind == cx.CursorKind.PARM_DECL:
                    params.append((p.spelling, p.type.spelling if p.type else ""))
            source_path = _abs(c.location.file.name) if c.location.file else ""
            symbol_id = function_symbol_id(c)
            funcs.append(Func(
                name=c.spelling, line=c.location.line, cursor=c, params=params,
                source_path=source_path, symbol_id=symbol_id,
                module_name=c.spelling,
                is_static=c.storage_class == cx.StorageClass.STATIC))
    funcs.sort(key=lambda f: f.line)
    return funcs


def target_mmio_globals(tu, target_file: str) -> list[str]:
    """File-scope pointer variables that hold an MMIO base, e.g.
    `static void __iomem *mmio;`. These are global bases used by callbacks that
    don't receive the device as a parameter (common in char-device drivers).
    Returns the variable names."""
    out: list[str] = []
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.VAR_DECL or not in_file(c, target_file):
            continue
        parent = c.semantic_parent
        if parent is None or parent.kind != cx.CursorKind.TRANSLATION_UNIT:
            continue
        ty = c.type.spelling if c.type else ""
        if "__iomem" in ty or (ty.endswith("*") and "void" in ty):
            out.append(c.spelling)
    return out


def direct_callees(func_cursor) -> set[str]:
    """Names of functions called within `func_cursor` (any file)."""
    out: set[str] = set()
    for cs in function_calls(func_cursor):
        if cs.name:
            out.add(cs.name)
    return out


def callback_entry_functions(tu, target_names: set[str]) -> set[str]:
    """Target functions referenced as function-pointer values (not just called).

    AST-based: a DeclRefExpr referencing a target function that is NOT part of
    any CallExpr's callee subtree is a function-pointer reference (e.g.
    `.irq_ack = foo`, `&foo`, `register_callback(foo)`, or a bare reference in
    a struct initializer). Such functions are entry points and must keep their
    own module (and not be inlined).

    Determines callee-ness by subtree containment (not start-offset equality),
    so parenthesized calls like `(helper)()` are correctly classified as calls
    (the CallExpr starts at `(` but the DeclRefExpr is in its callee subtree).
    Robust against string/char literals — the AST has no DeclRefExpr inside
    strings, so `pr_info("helper failed")` won't misclassify `helper`.
    """
    import clang.cindex as cx

    # collect extents of all DeclRefExpr that serve as a call callee: for each
    # CallExpr, walk its callee subtree (the first child) and record DeclRefExpr.
    call_callee_extents: set[tuple] = set()
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.CALL_EXPR:
            continue
        children = list(c.get_children())
        if not children:
            continue
        callee = children[0]
        for sub in callee.walk_preorder():
            if sub.kind == cx.CursorKind.DECL_REF_EXPR:
                s, e = sub.extent.start, sub.extent.end
                if s.offset is not None and e.offset is not None:
                    call_callee_extents.add((s.offset, e.offset))
        # the callee itself may be a bare DeclRefExpr (not visited by walk if
        # it's the root of the subtree — walk_preorder does yield the root)
        if callee.kind == cx.CursorKind.DECL_REF_EXPR:
            s, e = callee.extent.start, callee.extent.end
            if s.offset is not None and e.offset is not None:
                call_callee_extents.add((s.offset, e.offset))

    entries: set[str] = set()
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.DECL_REF_EXPR:
            continue
        ref = c.referenced
        if (ref is None or ref.kind != cx.CursorKind.FUNCTION_DECL
                or ref.spelling not in target_names):
            continue
        s, e = c.extent.start, c.extent.end
        key = (s.offset, e.offset) if (s.offset is not None and e.offset is not None) else None
        # if this DeclRefExpr is a call callee → it's a call, not a callback
        if key is not None and key in call_callee_extents:
            continue
        entries.add(ref.spelling)
    return entries


def callback_entry_symbols(tu, target_symbols: set[str]) -> set[str]:
    """Source-qualified counterpart of callback_entry_functions."""
    call_callee_extents: set[tuple] = set()
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.CALL_EXPR:
            continue
        children = list(c.get_children())
        if not children:
            continue
        for sub in children[0].walk_preorder():
            if sub.kind == cx.CursorKind.DECL_REF_EXPR:
                start, end = sub.extent.start, sub.extent.end
                if start.offset is not None and end.offset is not None:
                    call_callee_extents.add((start.offset, end.offset))

    entries: set[str] = set()
    for c in tu.cursor.walk_preorder():
        if c.kind != cx.CursorKind.DECL_REF_EXPR:
            continue
        ref = c.referenced
        symbol_id = function_symbol_id(ref)
        if not symbol_id or symbol_id not in target_symbols:
            continue
        start, end = c.extent.start, c.extent.end
        key = ((start.offset, end.offset)
               if start.offset is not None and end.offset is not None else None)
        if key is not None and key in call_callee_extents:
            continue
        entries.add(symbol_id)
    return entries


def walk_with_control(func_cursor) -> Iterator[tuple[object, list[dict]]]:
    """Yield cursors with their structured lexical control stack.

    This remains a conservative structured-C abstraction rather than a full
    CFG, but it distinguishes branch predicates from loops and retains loop
    initialization/step evidence instead of flattening loops into conditions.
    """
    # libclang cursor child ordering for control statements:
    #   IF_STMT:    [cond, then, else]      → cond at index 0
    #   WHILE_STMT: [cond, body]            → cond at index 0
    #   FOR_STMT:   [init, cond, inc, body] → cond at index 1
    #   DO_STMT:    [body, cond]            → cond at index 1
    _CONTROL_PRED_CHILD = {
        cx.CursorKind.IF_STMT: 0,
        cx.CursorKind.WHILE_STMT: 0,
        cx.CursorKind.FOR_STMT: 1,
        cx.CursorKind.DO_STMT: 1,
    }

    def switch_case_value(case_cursor):
        parts = list(case_cursor.get_children())
        if not parts:
            return "", []
        return source_text(case_cursor.translation_unit, parts[0]), parts[1:]

    def switch_values(node):
        values = []
        for sub in node.walk_preorder():
            if sub.kind == cx.CursorKind.CASE_STMT:
                value, _ = switch_case_value(sub)
                if value and value not in values:
                    values.append(value)
        return values

    def visit_switch_body(body, stack, switch_expr):
        values = switch_values(body)
        current = None
        for child in body.get_children():
            if child.kind == cx.CursorKind.CASE_STMT:
                value, statements = switch_case_value(child)
                guard = f"({switch_expr}) == ({value})" if value else switch_expr
                current = {"kind": "cond", "guard": guard,
                           "branch": "case", "switch": switch_expr,
                           "case": value}
                yield child, stack
                for statement in statements:
                    yield from visit(statement, stack + [current])
                continue
            if child.kind == cx.CursorKind.DEFAULT_STMT:
                joined = " || ".join(
                    f"(({switch_expr}) == ({value}))" for value in values)
                guard = f"!({joined})" if joined else "1"
                current = {"kind": "cond", "guard": guard,
                           "branch": "default", "switch": switch_expr}
                yield child, stack
                for statement in child.get_children():
                    yield from visit(statement, stack + [current])
                continue
            active = stack + [current] if current else stack
            yield from visit(child, active)
            if child.kind == cx.CursorKind.BREAK_STMT:
                current = None

    def visit(ch, stack):
        if ch.kind == cx.CursorKind.IF_STMT:
            parts = list(ch.get_children())
            if not parts:
                return
            cond = source_text(ch.translation_unit, parts[0])
            yield (ch, stack)
            yield from visit(parts[0], stack)
            if len(parts) > 1:
                then_stack = stack + [{"kind": "cond", "guard": cond,
                                       "branch": "then"}] if cond else stack
                yield from visit(parts[1], then_stack)
            if len(parts) > 2:
                else_cond = f"!({cond})" if cond else ""
                else_stack = stack + [{"kind": "cond", "guard": else_cond,
                                       "branch": "else"}] if else_cond else stack
                yield from visit(parts[2], else_stack)
        elif ch.kind == cx.CursorKind.SWITCH_STMT:
            parts = list(ch.get_children())
            if not parts:
                return
            switch_expr = source_text(ch.translation_unit, parts[0])
            yield ch, stack
            yield from visit(parts[0], stack)
            if len(parts) > 1:
                yield from visit_switch_body(parts[1], stack, switch_expr)
        elif ch.kind in _CONTROL_PRED_CHILD:
            pred_idx = _CONTROL_PRED_CHILD[ch.kind]
            parts = list(ch.get_children())
            if pred_idx < len(parts):
                cond = source_text(ch.translation_unit, parts[pred_idx])
                init = step = ""
                if ch.kind == cx.CursorKind.FOR_STMT:
                    init = source_text(ch.translation_unit, parts[0]) if parts else ""
                    step = source_text(ch.translation_unit, parts[2]) if len(parts) > 2 else ""
                frame = {
                    "kind": "loop",
                    "loop_kind": ch.kind.name.replace("_STMT", "").lower(),
                    "guard": cond,
                    "init": init,
                    "step": step,
                    "source": source_text(ch.translation_unit, ch),
                }
                new_stack = stack + [frame] if cond else stack
            else:
                new_stack = stack
            yield (ch, new_stack)
            for sub in parts:
                yield from visit(sub, new_stack)
        else:
            yield (ch, stack)
            for sub in ch.get_children():
                yield from visit(sub, stack)

    def walk(node, stack):
        for ch in node.get_children():
            yield from visit(ch, stack)

    yield from walk(func_cursor, [])


def walk_with_conditions(func_cursor) -> Iterator[tuple[object, list[str]]]:
    """Backward-compatible predicate-only view of ``walk_with_control``."""
    for cursor, stack in walk_with_control(func_cursor):
        yield cursor, [frame.get("guard", "") for frame in stack
                       if frame.get("guard")]


def continuation_guards(func_cursor) -> tuple[list[dict], set[int]]:
    """Guards that dominate statements following simple control transfers.

    This is deliberately limited to the function body's top-level sequential
    exits plus resolved forward gotos.  It handles both
    ``if (error) return; MMIO();`` and ``if (skip) goto join; MMIO(); join:``.
    Forward-goto guards have an end offset at the target label so paths merge
    again at the join.  The returned offsets identify transfers covered by
    this model.
    """
    def terminates(node) -> bool:
        if node.kind == cx.CursorKind.RETURN_STMT:
            return True
        children = list(node.get_children())
        if node.kind == cx.CursorKind.COMPOUND_STMT:
            return any(terminates(child) for child in children)
        if node.kind == cx.CursorKind.IF_STMT and len(children) >= 3:
            return terminates(children[1]) and terminates(children[2])
        return False

    def transfer_offsets(node) -> set[int]:
        out = set()
        for cursor in node.walk_preorder():
            if cursor.kind == cx.CursorKind.RETURN_STMT:
                offset = getattr(cursor.location, "offset", 0) or 0
                if offset:
                    out.add(offset)
        return out

    def negate(condition: str) -> str:
        text = condition.strip()
        if text.startswith("!") and not text.startswith("!="):
            inner = text[1:].strip()
            if inner.startswith("(") and inner.endswith(")"):
                inner = inner[1:-1].strip()
            return inner
        return f"!({text})"

    params = {
        child.spelling for child in func_cursor.get_children()
        if child.kind == cx.CursorKind.PARM_DECL and child.spelling
    }

    def proof_safe(condition: str) -> bool:
        """Only prove guards over callback parameters and constants."""
        if (re.search(r"->|\.|\[|\]", condition)
                or re.search(r"\*\s*[A-Za-z_]\w*", condition)):
            return False
        if re.search(r"\b[A-Za-z_]\w*\s*\(", condition):
            return False
        identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", condition))
        return all(name in params or name.isupper()
                   or name in {"true", "false"}
                   for name in identifiers)

    def switch_continuation(statement) -> tuple[str, set[int]] | None:
        parts = list(statement.get_children())
        if len(parts) < 2:
            return None
        selector = source_text(statement.translation_unit, parts[0]).strip()
        if not proof_safe(selector):
            return None
        block = source_text(statement.translation_unit, parts[1])
        labels = list(re.finditer(r"\b(case\s+([^:]+)|default)\s*:", block))
        if not labels:
            return None
        continuing: list[str] = []
        returning: list[str] = []
        default_returns = False
        has_default = False
        for index, label in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(block)
            segment = block[label.end():end]
            exits = bool(re.search(r"\b(?:return|goto)\b", segment))
            value = label.group(2)
            if value is None:
                has_default = True
                default_returns = exits
            elif exits:
                returning.append(value.strip())
            else:
                continuing.append(value.strip())
        if not returning and not default_returns:
            return None
        if default_returns:
            if not continuing:
                return None
            guard = " || ".join(
                f"({selector} == {value})" for value in continuing)
        else:
            if not returning:
                return None
            rejected = " || ".join(
                f"({selector} == {value})" for value in returning)
            guard = f"!({rejected})"
        return guard, transfer_offsets(parts[1])

    def if_continuation(statement) -> tuple[str, set[int]] | None:
        """Compute the surviving path of a safe if/else-if cascade."""
        branches: list[tuple[str, object | None, bool]] = []
        prefix: list[str] = []
        current = statement
        while current is not None and current.kind == cx.CursorKind.IF_STMT:
            parts = list(current.get_children())
            if len(parts) < 2:
                return None
            condition = source_text(
                current.translation_unit, parts[0]).strip()
            if not proof_safe(condition):
                return None
            branch_guard = " && ".join(
                [*(f"({item})" for item in prefix), f"({condition})"])
            branches.append((branch_guard, parts[1], terminates(parts[1])))
            prefix.append(negate(condition))
            if len(parts) >= 3 and parts[2].kind == cx.CursorKind.IF_STMT:
                current = parts[2]
                continue
            fallback_guard = " && ".join(f"({item})" for item in prefix) or "1"
            fallback = parts[2] if len(parts) >= 3 else None
            branches.append((fallback_guard, fallback,
                             terminates(fallback) if fallback is not None else False))
            break
        if not any(exits for _guard, _body, exits in branches):
            return None
        surviving = [guard for guard, _body, exits in branches if not exits]
        if not surviving:
            return "0", set().union(*(
                transfer_offsets(body) for _guard, body, exits in branches
                if exits and body is not None))
        transfers = set().union(*(
            transfer_offsets(body) for _guard, body, exits in branches
            if exits and body is not None))
        return " || ".join(f"({guard})" for guard in surviving), transfers

    body = next((child for child in func_cursor.get_children()
                 if child.kind == cx.CursorKind.COMPOUND_STMT), None)
    if body is None:
        return [], set()
    transitions: list[dict] = []
    modeled: set[int] = set()
    for statement in body.get_children():
        if statement.kind == cx.CursorKind.IF_STMT:
            if_result = if_continuation(statement)
            if if_result is None:
                continue
            surviving_guard, transfers = if_result
            modeled |= transfers
            transitions.append({
                "after_offset": getattr(statement.extent.end, "offset", 0) or 0,
                "frame": {
                    "kind": "cond", "guard": surviving_guard,
                    "branch": "continuation", "source": "early-exit",
                },
            })
        elif statement.kind == cx.CursorKind.SWITCH_STMT:
            switch_result = switch_continuation(statement)
            if switch_result is None:
                continue
            surviving_guard, transfers = switch_result
            modeled |= transfers
            transitions.append({
                "after_offset": getattr(statement.extent.end, "offset", 0) or 0,
                "frame": {
                    "kind": "cond", "guard": surviving_guard,
                    "branch": "continuation", "source": "switch-exit",
                },
            })
        elif statement.kind == cx.CursorKind.RETURN_STMT:
            modeled |= transfer_offsets(statement)
            transitions.append({
                "after_offset": getattr(statement.extent.end, "offset", 0) or 0,
                "frame": {
                    "kind": "cond", "guard": "0",
                    "branch": "unreachable", "source": "early-exit",
                },
            })

    labels = {
        cursor.spelling: (getattr(cursor.location, "offset", 0) or 0)
        for cursor in func_cursor.walk_preorder()
        if cursor.kind == cx.CursorKind.LABEL_STMT and cursor.spelling
    }
    control_by_offset = {
        getattr(cursor.location, "offset", 0) or 0: stack
        for cursor, stack in walk_with_control(func_cursor)
        if cursor.kind == cx.CursorKind.GOTO_STMT
    }
    for cursor in func_cursor.walk_preorder():
        if cursor.kind != cx.CursorKind.GOTO_STMT:
            continue
        text = source_text(cursor.translation_unit, cursor).strip()
        match = re.fullmatch(r"goto\s+([A-Za-z_]\w*)\s*;?", text)
        if not match:
            continue
        source_offset = getattr(cursor.location, "offset", 0) or 0
        target_offset = labels.get(match.group(1), 0)
        if not source_offset or target_offset <= source_offset:
            continue
        stack = control_by_offset.get(source_offset, [])
        taken_parts = [frame.get("guard", "").strip() for frame in stack
                       if frame.get("guard", "").strip()]
        taken_guard = " && ".join(f"({part})" for part in taken_parts) or "1"
        modeled.add(source_offset)
        transitions.append({
            "after_offset": getattr(cursor.extent.end, "offset", 0) or source_offset,
            "before_offset": target_offset,
            "frame": {
                "kind": "cond",
                "guard": negate(taken_guard),
                "branch": "fallthrough",
                "source": "forward-goto",
                "source_guard": taken_guard,
                "target_label": match.group(1),
            },
        })
    transitions.sort(key=lambda item: (
        item.get("after_offset", 0), item.get("before_offset", 1 << 62)))
    return transitions, modeled
