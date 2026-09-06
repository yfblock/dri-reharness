"""AST model: target-file functions, call sites, source-text helpers.

libclang gives correct function boundaries, call structure, line numbers,
and control-flow nesting — the structural substrate over which the string-
based dataflow evaluator (dataflow.py) runs.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator
import clang.cindex as cx


_EXPORT_SYMBOL_RE = re.compile(
    r"\bEXPORT_SYMBOL(?:_[A-Za-z0-9_]+)*\s*\(")


def _abs(path: str | None) -> str | None:
    return os.path.abspath(path) if path else None


def in_file(cursor, target_file: str) -> bool:
    f = cursor.location.file
    return f is not None and _abs(f.name) == _abs(target_file)


@lru_cache(maxsize=256)
def _read_source_bytes(path: str, mtime_ns: int, size: int) -> bytes:
    """Read a source file once while its filesystem identity is unchanged."""
    del mtime_ns, size
    with open(path, "rb") as fh:
        return fh.read()


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
        path = os.path.abspath(f.name)
        stat = os.stat(path)
        data = _read_source_bytes(path, stat.st_mtime_ns, stat.st_size)
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
    callee_decl_path: str = ""        # public declaration provenance, if resolved
    callee_result_type: str = ""       # declared result type
    callee_param_types: list[str] = field(default_factory=list)
    # parameter names from the referenced prototype; empty strings when the
    # declaration omits them.  External calls keep no Func body, so the
    # prototype is the only parameter-name provenance.
    callee_param_names: list[str] = field(default_factory=list)


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
    synthetic_role: str = ""
    synthetic_context: str = ""
    synthetic_callback_table: str = ""
    synthetic_return_type: str = "void"
    synthetic_param_types: dict[str, str] = field(default_factory=dict)


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


def _parse_call_args_from_source(call_cursor, callee: str) -> list[str]:
    """Fallback arg parser for calls nested inside macros (e.g. min_t).

    When libclang returns empty argument cursors for a CallExpr embedded
    in a macro expansion, extract arguments from the source file line.
    """
    loc = call_cursor.location
    if loc is None or loc.file is None:
        return []
    try:
        with open(loc.file.name, "r", errors="replace") as fh:
            file_lines = fh.readlines()
    except Exception:
        return []
    line_idx = loc.line - 1
    if line_idx < 0 or line_idx >= len(file_lines):
        return []
    line_text = file_lines[line_idx]
    # Find callee( in the line
    idx = line_text.find(callee)
    if idx < 0:
        return []
    open_paren = line_text.find("(", idx)
    if open_paren < 0:
        return []
    depth = 0
    close = -1
    for i in range(open_paren, len(line_text)):
        if line_text[i] == "(":
            depth += 1
        elif line_text[i] == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close < 0:
        return []
    args_text = line_text[open_paren + 1:close]
    parts = []
    current = []
    d = 0
    for ch in args_text:
        if ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
        if ch == "," and d == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts if parts != [""] else []


def _resolve_arg_text(call_cursor, args: list, callee: str) -> list[str]:
    """Return argument source text, with macro-nested fallback."""
    raw = [source_text(call_cursor.translation_unit, a) for a in args]
    if raw and all(not t.strip() for t in raw):
        parsed = _parse_call_args_from_source(call_cursor, callee)
        if parsed and len(parsed) == len(raw):
            return parsed
    return raw


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
            ref = c.referenced
            if ref is None and children:
                for sub in children[0].walk_preorder():
                    candidate = sub.referenced
                    if (candidate is not None
                            and candidate.kind == cx.CursorKind.FUNCTION_DECL):
                        ref = candidate
                        break
            decl_path = ""
            result_type = ""
            param_types: list[str] = []
            param_names: list[str] = []
            if ref is not None and ref.kind == cx.CursorKind.FUNCTION_DECL:
                loc = ref.location
                if loc is not None and loc.file is not None:
                    decl_path = _abs(loc.file.name) or ""
                result_type = (ref.result_type.spelling
                               if ref.result_type is not None else "")
                for child in ref.get_children():
                    if child.kind != cx.CursorKind.PARM_DECL:
                        continue
                    param_types.append(
                        child.type.spelling if child.type is not None else "")
                    param_names.append(child.spelling or "")
            cs = CallSite(
                name=callee_name(c),
                symbol_id=call_symbol_id(c),
                args=args,
                line=line,
                cursor=c,
                arg_text=_resolve_arg_text(c, args, callee_name(c)),
                callee_text=callee_text,
                callee_decl_path=decl_path,
                callee_result_type=result_type,
                callee_param_types=param_types,
                callee_param_names=param_names,
            )
            calls.append(cs)
    calls.sort(key=lambda c: c.line)
    return calls


def target_functions(tu, target_file: str) -> list[Func]:
    """FUNCTION_DECLs defined in `target_file`."""
    # module_init/module_exit expand to compiler-visible helper definitions in
    # a MODULE Kbuild context.  They are registration metadata, not driver
    # functions, and would otherwise make the analyzed inventory depend on
    # whether the exact Kbuild command was imported.
    synthetic_registration_helpers = {"__inittest", "__exittest"}
    funcs: list[Func] = []
    for c in tu.cursor.walk_preorder():
        if (c.kind == cx.CursorKind.FUNCTION_DECL and c.is_definition()
                and in_file(c, target_file)
                and c.spelling not in synthetic_registration_helpers):
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


def _is_export_symbol_reference(cursor) -> bool:
    """Ignore Linux export metadata when identifying callback roots."""
    location = cursor.location
    if location is None or location.file is None or not location.line:
        return False
    try:
        with open(location.file.name, "r", encoding="utf-8",
                  errors="replace") as fh:
            lines = fh.readlines()
    except Exception:
        return False
    index = location.line - 1
    if index < 0 or index >= len(lines):
        return False
    return bool(_EXPORT_SYMBOL_RE.search(lines[index]))


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
        if _is_export_symbol_reference(c):
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

    def switch_instance_id(cursor):
        location = cursor.location
        if location is None:
            return ""
        source = location.file.name if location.file else ""
        offset = getattr(location, "offset", 0) or 0
        if source and offset:
            return f"{source}:{offset}"
        line = getattr(location, "line", 0) or 0
        column = getattr(location, "column", 0) or 0
        return f"{source}:{line}:{column}"

    def switch_case_value(case_cursor):
        parts = list(case_cursor.get_children())
        if not parts:
            return "", []
        return source_text(case_cursor.translation_unit, parts[0]), parts[1:]

    def switch_case_group(case_cursor):
        """Flatten libclang's nested representation of stacked case labels."""
        values = []
        current = case_cursor
        while current.kind == cx.CursorKind.CASE_STMT:
            value, statements = switch_case_value(current)
            if value:
                values.append(value)
            if (len(statements) == 1
                    and statements[0].kind == cx.CursorKind.CASE_STMT):
                current = statements[0]
                continue
            return values, statements
        return values, []

    def switch_values(node):
        values = []
        for sub in node.walk_preorder():
            if sub.kind == cx.CursorKind.CASE_STMT:
                value, _ = switch_case_value(sub)
                if value and value not in values:
                    values.append(value)
        return values

    def visit_switch_body(body, stack, switch_expr, switch_id):
        values = switch_values(body)
        current = None
        for child in body.get_children():
            if child.kind == cx.CursorKind.CASE_STMT:
                case_values, statements = switch_case_group(child)
                comparisons = [
                    f"({switch_expr}) == ({value})" for value in case_values]
                guard = (" || ".join(f"({item})" for item in comparisons)
                         if comparisons else switch_expr)
                current = {"kind": "cond", "guard": guard,
                           "branch": "case", "switch": switch_expr,
                           "switch_id": switch_id,
                           "case": " | ".join(case_values)}
                yield child, stack
                for statement in statements:
                    yield from visit(statement, stack + [current])
                continue
            if child.kind == cx.CursorKind.DEFAULT_STMT:
                joined = " || ".join(
                    f"(({switch_expr}) == ({value}))" for value in values)
                guard = f"!({joined})" if joined else "1"
                current = {"kind": "cond", "guard": guard,
                           "branch": "default", "switch": switch_expr,
                           "switch_id": switch_id}
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
            switch_id = switch_instance_id(ch)
            yield ch, stack
            yield from visit(parts[0], stack)
            if len(parts) > 1:
                yield from visit_switch_body(
                    parts[1], stack, switch_expr, switch_id)
        elif ch.kind in _CONTROL_PRED_CHILD:
            pred_idx = _CONTROL_PRED_CHILD[ch.kind]
            parts = list(ch.get_children())
            if pred_idx < len(parts):
                cond = source_text(ch.translation_unit, parts[pred_idx])
                init = step = ""
                if ch.kind == cx.CursorKind.FOR_STMT:
                    init = source_text(ch.translation_unit, parts[0]) if parts else ""
                    step = source_text(ch.translation_unit, parts[2]) if len(parts) > 2 else ""
                guard_declarations = {}
                guard_types = {}
                for ref in parts[pred_idx].walk_preorder():
                    if (ref.kind == cx.CursorKind.DECL_REF_EXPR
                            and ref.referenced is not None):
                        guard_declarations[ref.spelling] = \
                            ref.referenced.kind.name
                        try:
                            guard_types[ref.spelling] = \
                                ref.referenced.type.get_canonical().spelling
                        except (AttributeError, TypeError):
                            pass
                # scoped_guard()/class_guard() style macros expand to a
                # run-once for-loop whose init/step carry the macro-call
                # text (init == step).  That is a locking scope, not a data
                # loop: treat it as transparent so the enclosed driver loops
                # are modelled with their own bounds.
                degenerate_macro_scope = (
                    ch.kind == cx.CursorKind.FOR_STMT
                    and init and init == step)
                if degenerate_macro_scope:
                    new_stack = stack
                else:
                    frame = {
                        "kind": "loop",
                        "loop_kind": ch.kind.name.replace("_STMT", "").lower(),
                        "guard": cond,
                        "init": init,
                        "step": step,
                        "guard_declarations": guard_declarations,
                        "guard_types": guard_types,
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
    def terminates(node, *, include_continue: bool = False) -> bool:
        if node.kind == cx.CursorKind.RETURN_STMT:
            return True
        if include_continue and node.kind == cx.CursorKind.CONTINUE_STMT:
            return True
        children = list(node.get_children())
        if node.kind == cx.CursorKind.COMPOUND_STMT:
            return any(terminates(child, include_continue=include_continue)
                       for child in children)
        if node.kind == cx.CursorKind.IF_STMT and len(children) >= 3:
            return (terminates(children[1], include_continue=include_continue)
                    and terminates(children[2],
                                   include_continue=include_continue))
        return False

    def transfer_offsets(node, *, include_continue: bool = False) -> set[int]:
        out = set()
        for cursor in node.walk_preorder():
            if (cursor.kind == cx.CursorKind.RETURN_STMT
                    or (include_continue
                        and cursor.kind == cx.CursorKind.CONTINUE_STMT)):
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

    def proof_safe(condition: str, *, allow_locals: bool = False) -> bool:
        """Accept guards whose dataflow is simple enough to replay safely.

        Loop-transfer guards may refer to scalar locals populated earlier in
        the same iteration.  They only model the surviving path after a
        ``continue``; they do not establish a loop bound or termination proof.
        """
        if (re.search(r"->|\.|\[|\]", condition)
                or re.search(r"\*\s*[A-Za-z_]\w*", condition)):
            return False
        if re.search(r"\b[A-Za-z_]\w*\s*\(", condition):
            return False
        identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", condition))
        return all(allow_locals or name in params or name.isupper()
                   or name in {"true", "false"}
                   for name in identifiers)

    def switch_continuation(statement) -> tuple[str, set[int]] | None:
        parts = list(statement.get_children())
        if len(parts) < 2:
            return None
        selector = source_text(statement.translation_unit, parts[0]).strip()
        block = source_text(statement.translation_unit, parts[1])
        labels = list(re.finditer(r"\b(case\s+([^:]+)|default)\s*:", block))
        if not labels:
            return None
        continuing: list[str] = []
        returning: list[str] = []
        default_returns = False
        has_default = False
        groups: list[list[re.Match]] = []
        current: list[re.Match] = [labels[0]]
        for label in labels[1:]:
            gap = block[current[-1].end():label.start()]
            if gap.strip():
                groups.append(current)
                current = [label]
            else:
                current.append(label)
        groups.append(current)
        terminal_returns = True
        for index, group in enumerate(groups):
            end = (groups[index + 1][0].start()
                   if index + 1 < len(groups) else len(block))
            segment = block[group[-1].end():end]
            terminal_returns &= bool(re.search(r"\breturn\b", segment))
            terminal_returns &= not bool(re.search(
                r"\b(?:goto|break|continue)\b", segment))
            exits = bool(re.search(r"\b(?:return|goto)\b", segment))
            values = [label.group(2) for label in group
                      if label.group(2) is not None]
            if any(label.group(2) is None for label in group):
                has_default = True
                default_returns = exits
            if exits:
                returning.extend(value.strip() for value in values)
            else:
                continuing.extend(value.strip() for value in values)
        if has_default and default_returns and not continuing and terminal_returns:
            return "0", transfer_offsets(parts[1])
        if not proof_safe(selector):
            return None
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

    def if_continuation(statement, *, include_continue: bool = False,
                        allow_locals: bool = False
                        ) -> tuple[str, set[int]] | None:
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
            if not proof_safe(condition, allow_locals=allow_locals):
                return None
            branch_guard = " && ".join(
                [*(f"({item})" for item in prefix), f"({condition})"])
            branches.append((
                branch_guard, parts[1],
                terminates(parts[1], include_continue=include_continue)))
            prefix.append(negate(condition))
            if len(parts) >= 3 and parts[2].kind == cx.CursorKind.IF_STMT:
                current = parts[2]
                continue
            fallback_guard = " && ".join(f"({item})" for item in prefix) or "1"
            fallback = parts[2] if len(parts) >= 3 else None
            branches.append((fallback_guard, fallback,
                             (terminates(fallback,
                                         include_continue=include_continue)
                              if fallback is not None else False)))
            break
        if not any(exits for _guard, _body, exits in branches):
            return None
        surviving = [guard for guard, _body, exits in branches if not exits]
        if not surviving:
            return "0", set().union(*(
                transfer_offsets(body, include_continue=include_continue)
                for _guard, body, exits in branches
                if exits and body is not None))
        transfers = set().union(*(
            transfer_offsets(body, include_continue=include_continue)
            for _guard, body, exits in branches
            if exits and body is not None))
        return " || ".join(f"({guard})" for guard in surviving), transfers

    def loop_continuations(statement) -> list[dict]:
        """Return guards for paths surviving terminal branches in a loop."""
        parts = list(statement.get_children())
        if len(parts) < 2:
            return []
        body = parts[-1]
        statements = (list(body.get_children())
                      if body.kind == cx.CursorKind.COMPOUND_STMT else [body])
        transitions: list[dict] = []
        for child in statements:
            if child.kind != cx.CursorKind.IF_STMT:
                continue
            result = if_continuation(
                child, include_continue=True, allow_locals=True)
            if result is None:
                continue
            guard, transfers = result
            modeled.update(transfers)
            transitions.append({
                "after_offset": getattr(child.extent.end, "offset", 0) or 0,
                "before_offset": getattr(statement.extent.end, "offset", 0) or 0,
                "frame": {
                    "kind": "cond", "guard": guard,
                    "branch": "continuation", "source": "loop-transfer",
                },
            })
        return transitions

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
        elif statement.kind in {
                cx.CursorKind.FOR_STMT, cx.CursorKind.WHILE_STMT,
                cx.CursorKind.DO_STMT}:
            transitions.extend(loop_continuations(statement))
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
