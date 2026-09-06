"""Shared helpers for subsystem summary inference."""
from __future__ import annotations

import copy
import re
from collections import defaultdict

import clang.cindex as cx

from .. import mmio
from ..accounting import callsite_evidence
from ast_analyzer import Func, function_calls, source_text, walk_with_control
from ..dataflow import (FuncExtraction, Op, _abs_expr, _expand_numeric_macros,
                       _substitute_text, eval_expr, resolve_addr)
from ..taint import (BasePtr, Const, SymExpr, Top, addr_base_of, addr_fixed,
                    addr_indirect, addr_offset)


_GPIO_CONFIG_FIELDS = {"sz", "dat", "set", "clr", "dirout", "dirin", "flags"}



def _split_initializer(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth:
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _compound_config_fields(text: str, config: str) -> list[dict]:
    pattern = re.compile(
        rf"\b{re.escape(config)}\s*=\s*"
        rf"\(\s*struct\s+gpio_generic_chip_config\s*\)\s*\{{")
    match = pattern.search(text)
    if not match:
        return []
    start = match.end() - 1
    depth = 0
    end = None
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return []
    out = []
    for part in _split_initializer(text[start + 1:end]):
        field = re.match(r"\.\s*([A-Za-z_]\w*)\s*=\s*(.+)", part, re.S)
        if field and field.group(1) in _GPIO_CONFIG_FIELDS:
            out.append({
                "field": field.group(1),
                "expr": field.group(2).strip(),
                "conditions": [],
                "control": [],
            })
    return out


def _direct_config_fields(func: Func, config: str, tu) -> list[dict]:
    out = []
    assignment = re.compile(
        rf"^\s*{re.escape(config)}\s*\.\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*;?\s*$",
        re.S)
    for cursor, stack in walk_with_control(func.cursor):
        if cursor.kind != cx.CursorKind.BINARY_OPERATOR:
            continue
        match = assignment.match(source_text(tu, cursor))
        if not match or match.group(1) not in _GPIO_CONFIG_FIELDS:
            continue
        controls = [copy.deepcopy(frame) for frame in stack]
        out.append({
            "field": match.group(1),
            "expr": match.group(2).strip(),
            "conditions": [frame.get("guard", "") for frame in controls
                           if frame.get("guard")],
            "control": controls,
        })
    return out


def _config_fields(func: Func, config: str, tu) -> dict[str, list[dict]]:
    text = source_text(tu, func.cursor)
    entries = (_compound_config_fields(text, config)
               + _direct_config_fields(func, config, tu))
    fields: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for entry in entries:
        key = (entry["field"], entry["expr"], tuple(entry["conditions"]))
        if key in seen:
            continue
        seen.add(key)
        fields[entry["field"]].append(entry)
    return dict(fields)


def _base_store(func: Func, tu, macros) -> dict:
    store = {}
    for name, ctype in func.params:
        if name and "*" in (ctype or ""):
            store[name] = BasePtr(name)
    text = source_text(tu, func.cursor)
    ioremap_names = sorted(mmio.IOREMAP_FNS, key=len, reverse=True)
    if ioremap_names:
        pattern = re.compile(
            r"\b([A-Za-z_]\w*)\s*=\s*(?:"
            + "|".join(re.escape(name) for name in ioremap_names)
            + r")\s*\(")
        for match in pattern.finditer(text):
            store[match.group(1)] = BasePtr(match.group(1))
    assignment = re.compile(
        r"(?m)^\s*(?:[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*\s+)?"
        r"(?:\*+\s*)?([A-Za-z_]\w*)\s*=\s*([^;]+);$")
    for match in assignment.finditer(text):
        lhs, rhs = match.groups()
        if re.search(r"\b[A-Za-z_]\w*\s*\(", rhs):
            continue
        mapping = {
            name: _abs_expr(value, name) for name, value in store.items()
            if re.fullmatch(r"[A-Za-z_]\w*", name)
            and not isinstance(value, Top)
        }
        expanded = _substitute_text(rhs.strip(), mapping) or rhs.strip()
        expanded = _expand_numeric_macros(expanded, macros)
        value = eval_expr(expanded, store, macros)
        store[lhs] = SymExpr(expanded) if isinstance(value, Top) else value
    return store


def _constant_width(entries: list[dict], macros) -> int:
    if not entries:
        return 4
    value = eval_expr(entries[-1]["expr"], {}, macros)
    return value.n if isinstance(value, Const) and value.n in {1, 2, 4, 8} else 4


def _summary_evidence(func: Func, call, width: int, callback: str,
                      domain: str = "mmio") -> dict:
    evidence = callsite_evidence(
        func, call, "summary", effective_name="gpio_generic_chip_init")
    evidence.update({
        "width_bytes": width,
        "access_domain": domain,
        "library_callback": callback,
        "summary_contract": "linux.gpio_generic_chip_config",
    })
    return evidence


def _op_for_entry(kind: str, entry: dict, store: dict, macros, width: int,
                  evidence: dict, *, value: str | None = None,
                  var: str | None = None) -> Op:
    address, register = resolve_addr(entry["expr"], store, macros)
    conditions = list(entry.get("conditions", []))
    return Op(
        kind=kind, addr=address, width=width, value=value,
        condition=conditions[-1] if conditions else None,
        cond_stack=conditions,
        control_stack=copy.deepcopy(entry.get("control", [])),
        reg_name=register, var=var,
        evidence=copy.deepcopy(evidence),
        source_loc=f"subsystem gpio_generic_chip_init:{evidence['line']}",
        line=evidence["line"],
    )


def _semantic_op(kind: str, evidence: dict, width: int, *,
                 field: str | None = None, value: str | None = None,
                 var: str | None = None) -> Op:
    semantic_evidence = copy.deepcopy(evidence)
    semantic_evidence["access_domain"] = "source_state"
    return Op(
        kind=kind, addr={}, width=width, value=value, var=var,
        state_field=field, evidence=semantic_evidence,
        source_loc=f"subsystem gpio_generic_chip_init:{evidence['line']}",
        line=evidence["line"],
    )


def _semantic_for_entry(kind: str, entry: dict, evidence: dict, width: int, *,
                        field: str | None = None, value: str | None = None,
                        var: str | None = None) -> Op:
    op = _semantic_op(
        kind, evidence, width, field=field, value=value, var=var)
    conditions = list(entry.get("conditions", []))
    op.condition = conditions[-1] if conditions else None
    op.cond_stack = conditions
    op.control_stack = copy.deepcopy(entry.get("control", []))
    return op


def _conditional_entry(entry: dict, guard: str) -> dict:
    conditioned = copy.deepcopy(entry)
    conditioned.setdefault("conditions", []).append(guard)
    conditioned.setdefault("control", []).append({
        "kind": "cond", "guard": guard, "source": "subsystem-summary",
    })
    return conditioned


def _direction_variant_model(fields: dict[str, list[dict]], owner: Func, tu
                             ) -> dict | None:
    """Recognize one case/default selector choosing dirin versus dirout."""
    dirin = fields.get("dirin", [])
    dirout = fields.get("dirout", [])
    if len(dirin) != 1 or len(dirout) != 1:
        return None
    # A polarity selector is only sufficient when both branches name the
    # same physical direction register.  If the branches select different
    # addresses, one Boolean cannot preserve both the address and polarity
    # choice and the generic variant must remain unsupported.
    if dirin[0].get("expr", "").strip() != dirout[0].get("expr", "").strip():
        return None
    in_control = (dirin[0].get("control") or [{}])[-1]
    out_control = (dirout[0].get("control") or [{}])[-1]
    switch = in_control.get("switch")
    if (not switch or switch != out_control.get("switch")
            or {in_control.get("branch"), out_control.get("branch")}
            != {"case", "default"}):
        return None
    # dirin is the exceptional/inverted configuration.  Only accept a source
    # assignment whose selector can be rebound without inventing firmware ABI.
    condition = (dirin[0].get("conditions") or [""])[-1]
    variable = switch.strip()
    text = source_text(tu, owner.cursor)
    assignments = list(re.finditer(
        rf"\b{re.escape(variable)}\s*=\s*(.+?)\s*;", text, re.S))
    if not assignments:
        return None
    source_expr = assignments[-1].group(1).strip()
    # Resolve simple local aliases such as `np = pdev->dev.of_node`.
    for name in sorted(set(re.findall(r"\b[A-Za-z_]\w*\b", source_expr))):
        aliases = list(re.finditer(
            rf"\b{re.escape(name)}\s*=\s*([^;]+?)\s*;", text, re.S))
        if aliases and name != variable:
            rhs = aliases[-1].group(1).strip()
            source_expr = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
                f"({rhs})", source_expr)
    case_value = re.search(r"(?:==|!=)\s*\(?\s*([0-9]+)\s*\)?", condition)
    if (case_value is None or not re.fullmatch(
            r"of_alias_get_id\s*\(\s*\(?\s*pdev->dev\.of_node\s*\)?\s*,\s*"
            r'"[A-Za-z0-9_-]+"\s*\)', source_expr)):
        return None
    value = int(case_value.group(1), 10)
    return {
        "state_field": "gpio_config_variant",
        "source_variable": variable,
        "source_expr": source_expr,
        "source_condition": f"({source_expr}) == {value}",
        "true_field": "dirin",
        "false_field": "dirout",
    }


def _variant_entry(entry: dict, enabled: bool) -> dict:
    out = copy.deepcopy(entry)
    guard = "gpio_config_variant != 0" if enabled else "gpio_config_variant == 0"
    out["conditions"] = [guard]
    out["control"] = [{
        "kind": "cond", "guard": guard, "source": "gpio-config-variant",
    }]
    return out


def _unconditional_entry(entry: dict) -> dict:
    out = copy.deepcopy(entry)
    out["conditions"] = []
    out["control"] = []
    return out


def _resource_bindings(func: Func, tu) -> dict[str, int]:
    try:
        text = open(func.source_path, "r", encoding="utf-8",
                    errors="replace").read()
    except OSError:
        text = source_text(tu, func.cursor)
    bindings: dict[str, int] = {}
    pattern = re.compile(
        r"\b([A-Za-z_]\w*(?:\s*->\s*[A-Za-z_]\w*)?)\s*=\s*"
        r"devm_platform_ioremap_resource\s*"
        r"\([^,]+,\s*([0-9]+)\s*\)")
    for match in pattern.finditer(text):
        bindings[re.sub(r"\s+", "", match.group(1))] = int(match.group(2))
    return bindings


def _gpio_bank_model(fields: dict[str, list[dict]], store: dict, macros,
                     resource_bindings: dict[str, int], owner: Func) -> dict | None:
    required = [name for name in ("dat", "set", "dirout") if fields.get(name)]
    if len(required) < 2:
        return None
    addresses = []
    for name in required:
        if len(fields[name]) != 1:
            return None
        address, _register = resolve_addr(fields[name][0]["expr"], store, macros)
        indirect = address.get("Indirect")
        if not indirect or not indirect.get("expr"):
            return None
        base = indirect.get("base_reg", "")
        if resource_bindings.get(base) is None:
            return None
        addresses.append((name, base, indirect["expr"]))
    bases = {base for _name, base, _expr in addresses}
    if len(bases) != 1:
        return None
    member_sets = []
    for _name, base, expr in addresses:
        members = set(re.findall(
            r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+", expr))
        members.discard(base)
        member_sets.append(members)
    shared = set.intersection(*member_sets) if member_sets else set()
    if len(shared) != 1:
        return None
    selector = next(iter(shared))
    # The selector must be copied into the per-chip object, establishing that
    # callbacks retain the same bank chosen during config construction.
    try:
        source = open(owner.source_path, "r", encoding="utf-8",
                      errors="replace").read()
    except OSError:
        return None
    if not re.search(
            rf"\b[A-Za-z_]\w*\s*->\s*[A-Za-z_]\w*\s*=\s*"
            rf"{re.escape(selector)}\s*;", source):
        return None
    max_count = None
    limit = re.search(
        rf"{re.escape(selector)}\s*>=\s*([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)",
        source)
    if limit:
        value = eval_expr(limit.group(1), {}, macros)
        numeric = (value.n if isinstance(value, Const)
                   else macros.offset(limit.group(1)))
        if numeric is not None and 0 < numeric <= 256:
            max_count = numeric
    property_match = re.search(
        r"fwnode_property_read_u32\s*\([^,]+,\s*\"([^\"]+)\"\s*,\s*&\s*"
        rf"{re.escape(selector)}\s*\)", source)
    selector_root = selector.split("->", 1)[0].split(".", 1)[0]
    ngpio_member = rf"{re.escape(selector_root)}\s*(?:->|\.)\s*ngpio"
    ngpio_properties = re.findall(
        r"fwnode_property_read_u32\s*\([^,]+,\s*\"([^\"]+)\"\s*,\s*&\s*"
        rf"{ngpio_member}\s*\)", source)
    ngpio_default = None
    default_match = re.search(
        rf"{ngpio_member}\s*=\s*"
        r"([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)\s*;", source)
    if default_match:
        value = eval_expr(default_match.group(1), {}, macros)
        numeric = (value.n if isinstance(value, Const)
                   else macros.offset(default_match.group(1)))
        if numeric is not None and 0 < numeric <= 4096:
            ngpio_default = numeric

    irq_selector = None
    irq_match = re.search(
        rf"if\s*\(\s*{re.escape(selector)}\s*==\s*"
        r"(0[xX][0-9a-fA-F]+|\d+)\s*\)\s*"
        r"[A-Za-z_]\w*irq[A-Za-z_]*\s*\(", source)
    if irq_match:
        irq_selector = int(irq_match.group(1), 0)
    irq_model = None
    if irq_selector is not None and re.search(
            r"\bfwnode_irq_get\s*\(", source):
        irq_model = {
            "selector_value": irq_selector,
            "fwnode_indexed": True,
            "platform_indexed": bool(re.search(
                r"\bplatform_get_irq_optional\s*\(", source)),
        }
    return {
        "state_field": "gpio_bank_index",
        "selector": selector,
        "base": next(iter(bases)),
        "resource_index": resource_bindings[next(iter(bases))],
        "max_count": max_count,
        "property": property_match.group(1) if property_match else None,
        "fields": {name: expr for name, _base, expr in addresses},
        "ngpio_properties": list(dict.fromkeys(ngpio_properties)),
        "ngpio_default": ngpio_default,
        "irq": irq_model,
    }


def _apply_gpio_bank_model(ops: list[Op], model: dict) -> None:
    selector = model["selector"]
    for op in ops:
        indirect = op.addr.get("Indirect") if isinstance(op.addr, dict) else None
        if not indirect or indirect.get("base_reg") != model["base"]:
            continue
        indirect["base_reg"] = "base"
        indirect["expr"] = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(selector)}(?![A-Za-z0-9_])",
            model["state_field"], indirect.get("expr", ""))


def _synthetic_func(owner: Func, suffix: str, params: list[tuple[str, str]],
                    role: str, table: str, return_type: str = "int") -> Func:
    name = f"{owner.name}__gpio_generic_{suffix}"
    return Func(
        name=name, line=owner.line, cursor=None, params=params,
        source_path=owner.source_path, symbol_id=name, module_name=name,
        is_static=True, synthetic_role=role, synthetic_context="thread",
        synthetic_callback_table=f"gpio_chip.{table}",
        synthetic_return_type=return_type,
        synthetic_param_types={
            name: ("DeviceState" if name == "gc" else
                   "UIntPtr" if "*" in _ctype else "UInt")
            for name, _ctype in params
        },
    )


def _make_callback(owner: Func, suffix: str, params: list[tuple[str, str]],
                   role: str, table: str, ops: list[Op],
                   return_type: str = "int") -> tuple[Func, FuncExtraction]:
    func = _synthetic_func(owner, suffix, params, role, table, return_type)
    return func, FuncExtraction(
        name=func.name, params=[name for name, _ctype in params], ops=ops)


# Subsystem modules use a wildcard import for this shared helper namespace.
__all__ = [name for name in globals() if not name.startswith("__")]
