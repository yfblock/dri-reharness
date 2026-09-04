"""Text/address substitution, pure-call inlining, and op instantiation."""
from __future__ import annotations
import re
from typing import Optional

from ..taint import addr_offset
from .funcs import FuncExtraction, _pure_return_functions, _split_text_args
from .ops import Op


def _expand_pure_calls(text: str, inline_cache: Optional[dict]) -> str:
    """Inline understood scalar helpers inside an expression string."""
    pure = _pure_return_functions(inline_cache)
    if not text or not pure:
        return text
    value = text
    for _round in range(16):
        candidates: list[tuple[int, int, int, FuncExtraction]] = []
        for name, extraction in pure.items():
            for match in re.finditer(rf"\b{re.escape(name)}\s*\(", value):
                open_paren = value.find("(", match.start())
                depth = 0
                close = None
                for index in range(open_paren, len(value)):
                    if value[index] == "(":
                        depth += 1
                    elif value[index] == ")":
                        depth -= 1
                        if depth == 0:
                            close = index
                            break
                if close is not None:
                    candidates.append((match.start(), close, open_paren,
                                       extraction))
        if not candidates:
            break
        start, close, open_paren, extraction = max(
            candidates, key=lambda item: item[0])
        args = _split_text_args(value[open_paren + 1:close])
        if len(args) != len(extraction.params):
            break
        replacement = _substitute_text(
            extraction.return_expr, dict(zip(extraction.params, args)))
        if not replacement:
            break
        value = value[:start] + f"({replacement})" + value[close + 1:]
    return value


def _expand_numeric_macros(text: str, macros) -> str:
    if not text or macros is None:
        return text
    values: dict[str, str] = {}
    for name in set(re.findall(r"\b[A-Za-z_]\w*\b", text)):
        offset = macros.offset(name)
        if offset is not None:
            values[name] = hex(offset) if offset >= 0 else str(offset)
    return _substitute_text(text, values) or text


def _expand_addr_numeric_macros(addr: dict, macros) -> dict:
    if "Indirect" in addr and addr["Indirect"].get("expr"):
        addr["Indirect"]["expr"] = _expand_numeric_macros(
            addr["Indirect"]["expr"], macros)
    return addr


_ADDRESS_OF_MEMBER_RE = re.compile(
    r"\((?P<address>&[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w+)*)\)->")


def _normalise_address_of_member(text: str) -> str:
    """Normalize ``(&object)->field`` after pointer-argument substitution."""
    return _ADDRESS_OF_MEMBER_RE.sub(
        lambda match: match.group("address")[1:] + ".", text)


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
        replacement = mapping.get(match.group(0), match.group(0))
        # An address-of argument substituted into ``param->field`` needs
        # parentheses before the member operator.  Normalize that temporary
        # form after the whole token substitution so the expression parser
        # sees the original object member rather than a top-level ``&``.
        if (replacement.lstrip().startswith("&")
                and text[match.end():].lstrip().startswith("->")):
            return f"({replacement})"
        return replacement

    return _normalise_address_of_member(pattern.sub(replace, text))


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


def _instantiate_op(op: Op, mapping: dict[str, str], macros=None,
                    inline_cache: Optional[dict] = None,
                    inline_context: Optional[str] = None) -> Op:
    import copy
    out = copy.copy(op)
    out.evidence = copy.deepcopy(op.evidence)
    out.transaction = copy.deepcopy(op.transaction)
    for key in ("target", "selector", "count", "buffer", "value",
                "result", "changed_result", "update_mask", "update_value"):
        if out.transaction.get(key) is not None:
            out.transaction[key] = _substitute_text(
                str(out.transaction[key]), mapping)
    out.addr = _substitute_addr(op.addr, mapping)
    out.var = _substitute_text(op.var, mapping)
    out.state_field = _substitute_text(op.state_field, mapping)
    if "Indirect" in out.addr and out.addr["Indirect"].get("expr"):
        original_expr = out.addr["Indirect"]["expr"]
        expanded = _expand_pure_calls(
            original_expr, inline_cache)
        token = expanded.strip()
        offset = macros.offset(token) if macros is not None else None
        if offset is not None:
            out.addr = addr_offset(
                out.addr["Indirect"].get("base_reg", ""), offset)
            out.reg_name = token
        else:
            out.addr["Indirect"]["expr"] = (
                _expand_numeric_macros(expanded, macros)
                if expanded != original_expr else expanded)
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
        if inline_context and not copied.get("inline_origin"):
            copied["inline_origin"] = inline_context
        if copied.get("switch_id") and inline_context:
            copied["switch_id"] = (
                f"{copied['switch_id']}@{inline_context}")
        out.control_stack.append(copied)
    out.var = _substitute_text(op.var, mapping)
    return out
