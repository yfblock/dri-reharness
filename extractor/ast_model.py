"""AST model: target-file functions, call sites, source-text helpers.

libclang gives correct function boundaries, call structure, line numbers,
and control-flow nesting — the structural substrate over which the string-
based dataflow evaluator (dataflow.py) runs.
"""
from __future__ import annotations
import os
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
    args: list                      # list of arg cursors
    line: int
    cursor: object
    arg_text: list[str] = field(default_factory=list)  # source text per arg


@dataclass
class Func:
    name: str
    line: int
    cursor: object
    params: list[tuple[str, str]] = field(default_factory=list)  # (name, type)


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
            line = c.location.line if c.location and c.location.file else 0
            cs = CallSite(
                name=callee_name(c),
                args=args,
                line=line,
                cursor=c,
                arg_text=[source_text(c.translation_unit, a) for a in args],
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
            funcs.append(Func(name=c.spelling, line=c.location.line,
                              cursor=c, params=params))
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


def walk_with_conditions(func_cursor) -> Iterator[tuple[object, list[str]]]:
    """Yield (cursor, condition_stack) for statements in source order.

    condition_stack is the list of enclosing branch/loop predicate source
    strings (path-insensitive — every op inside an `if(cond)` gets `cond`).
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

    def visit(ch, stack):
        if ch.kind == cx.CursorKind.IF_STMT:
            parts = list(ch.get_children())
            if not parts:
                return
            cond = source_text(ch.translation_unit, parts[0])
            yield (ch, stack)
            yield from visit(parts[0], stack)
            if len(parts) > 1:
                then_stack = stack + [cond] if cond else stack
                yield from visit(parts[1], then_stack)
            if len(parts) > 2:
                else_cond = f"!({cond})" if cond else ""
                else_stack = stack + [else_cond] if else_cond else stack
                yield from visit(parts[2], else_stack)
        elif ch.kind in _CONTROL_PRED_CHILD:
            pred_idx = _CONTROL_PRED_CHILD[ch.kind]
            parts = list(ch.get_children())
            if pred_idx < len(parts):
                cond = source_text(ch.translation_unit, parts[pred_idx])
                new_stack = stack + [cond] if cond else stack
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
