"""Read-modify-write recovery: LHS binding and source-order mutation replay."""
from __future__ import annotations
import re
from typing import Optional

from .. import mmio
from ..ast_model import source_text
from .expr_eval import _IDENT_RE, _MEMBER_RE, _strip_casts
from .ops import Op


def _assign_target(lhs_text: str) -> Optional[str]:
    """From an assignment LHS, the store key to bind."""
    lhs = lhs_text.strip()
    if _MEMBER_RE.match(lhs) or _IDENT_RE.match(lhs):
        return lhs
    return None


_LHS_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*(?:->|\.)\s*\w+)*)\s*=\s*(?!=)")
_LHS_CONT_RE = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*(?:->|\.)\s*\w+)*)\s*=\s*$")
_DECL_LHS_RE = re.compile(
    r"^\s*(?:[A-Za-z_]\w*\s+)+(?:\*+\s*)?([A-Za-z_]\w*)\s*=\s*(?!=)")


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
    declaration = _DECL_LHS_RE.match(line)
    if declaration and call_name and call_name in line:
        return declaration.group(1)
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


def _has_classified_read_provenance(op: Op | None) -> bool:
    """Whether ``op`` came from a read accepted by the MMIO classifier."""
    if op is None or op.kind != "Read":
        return False

    def classified(evidence: dict) -> bool:
        access_name = evidence.get("effective_callee") or evidence.get("callee")
        if (evidence.get("access_kind") == "read"
                and isinstance(access_name, str)
                and mmio.is_mmio_read(access_name)):
            return True
        # Wrapper summaries preserve the definition-level callsite evidence
        # under ``wrapper_definition``.  Treat that nested proof as equivalent
        # to a direct read, while still rejecting a helper merely named like a
        # read API or an unproven synthetic operation.
        nested = evidence.get("wrapper_definition")
        return isinstance(nested, dict) and classified(nested)

    return classified(op.evidence or {})


def _proven_return_read_var(return_expr: str | None,
                            ops: list[Op]) -> str | None:
    """Find the unique classified Read value returned without transformation.

    This closes provenance through wrappers such as ``return low_read()`` and
    ``value = low_read(); return value`` after their callees have been
    expanded.  Equality is deliberately limited to casts/parentheses: boolean
    transforms, arithmetic, and unrelated read-named API calls are not direct
    register-read returns.
    """
    if not return_expr:
        return None
    returned = _strip_casts(return_expr)
    candidates = {
        op.var for op in ops
        if op.var and _strip_casts(op.var) == returned
        and _has_classified_read_provenance(op)
    }
    return next(iter(candidates)) if len(candidates) == 1 else None
