"""Type/callee-driven summaries for Linux subsystem library semantics."""
from __future__ import annotations

import copy
import re
from collections import defaultdict

import clang.cindex as cx

from . import mmio
from .accounting import callsite_evidence
from .ast_model import Func, function_calls, source_text, walk_with_control
from .dataflow import (FuncExtraction, Op, _abs_expr, _expand_numeric_macros,
                       _substitute_text, eval_expr, resolve_addr)
from .taint import (BasePtr, Const, SymExpr, Top, addr_base_of, addr_fixed,
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


def infer_gpio_generic_summaries(funcs: list[Func], extractions: dict,
                                 macros, tu) -> tuple[list[Func], dict, list[dict]]:
    """Materialize gpio-mmio callbacks from gpio_generic_chip_config.

    The trigger is the public helper and its typed config object. Driver names
    and source basenames are intentionally absent from this mechanism.
    """
    synthetic_funcs: list[Func] = []
    synthetic_extractions: dict[str, FuncExtraction] = {}
    stats: list[dict] = []
    for owner in funcs:
        for call in function_calls(owner.cursor):
            if call.name != "gpio_generic_chip_init" or len(call.arg_text) < 2:
                continue
            config = call.arg_text[1].strip().lstrip("&*").strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", config):
                continue
            fields = _config_fields(owner, config, tu)
            dat = fields.get("dat", [])
            if not dat:
                continue
            width = _constant_width(fields.get("sz", []), macros)
            store = _base_store(owner, tu, macros)
            resource_bindings = _resource_bindings(owner, tu)
            bank_model = _gpio_bank_model(
                fields, store, macros, resource_bindings, owner)
            variant = any(len(fields.get(name, [])) > 1
                          for name in ("dat", "set", "clr", "dirout", "dirin"))
            variant = variant or bool(fields.get("dirout") and fields.get("dirin"))
            variant_model = _direction_variant_model(fields, owner, tu)
            if variant_model:
                fields = copy.deepcopy(fields)
                fields["dirin"] = [
                    _variant_entry(fields["dirin"][0], True)]
                fields["dirout"] = [
                    _variant_entry(fields["dirout"][0], False)]
            flag_text = " ".join(
                entry.get("expr", "") for entry in fields.get("flags", []))
            flag_value = 0
            if fields.get("flags"):
                evaluated_flags = eval_expr(
                    fields["flags"][-1].get("expr", ""), {}, macros)
                flag_value = (evaluated_flags.n
                              if isinstance(evaluated_flags, Const) else None)
            flag_unreadable_set = 1 << 1
            flag_unreadable_dir = 1 << 2
            flag_byte_order = 1 << 3
            flag_read_output_set = 1 << 4
            flag_no_set_on_input = 1 << 6
            supported_flag_mask = (
                flag_unreadable_set | flag_unreadable_dir | flag_byte_order
                | flag_read_output_set | flag_no_set_on_input)
            if flag_value is None:
                flag_tokens = {
                    token.strip() for token in re.sub(r"[()]", "", flag_text).split("|")
                    if token.strip()
                }
                flag_constants = {
                    "GPIO_GENERIC_UNREADABLE_REG_SET": flag_unreadable_set,
                    "GPIO_GENERIC_UNREADABLE_REG_DIR": flag_unreadable_dir,
                    "GPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER": flag_byte_order,
                    "GPIO_GENERIC_READ_OUTPUT_REG_SET": flag_read_output_set,
                    "GPIO_GENERIC_NO_SET_ON_INPUT": flag_no_set_on_input,
                }
                if flag_tokens <= {"0", "0x0", *flag_constants}:
                    flag_value = 0
                    for token in flag_tokens:
                        flag_value |= flag_constants.get(token, 0)
            unsupported_flags = (
                flag_value is None
                or bool(flag_value & ~supported_flag_mask)
                or bool(flag_value & flag_byte_order and width == 8))
            unsupported_flags = unsupported_flags or width == 8
            domain = (
                "gpio_generic_config_variant" if variant and not variant_model
                else "gpio_generic_flags_variant" if unsupported_flags
                else "mmio")
            byte_order = (
                "big" if (flag_value is not None
                          and flag_value & flag_byte_order) or re.search(
                    r"\bGPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER\b", flag_text)
                else "native")
            read_output_set = bool(
                flag_value is not None and flag_value & flag_read_output_set)
            unreadable_set = bool(
                flag_value is not None and flag_value & flag_unreadable_set)
            unreadable_dir = bool(
                flag_value is not None and flag_value & flag_unreadable_dir)
            no_set_on_input = bool(
                flag_value is not None and flag_value & flag_no_set_on_input)

            def evidence(callback: str) -> dict:
                item = _summary_evidence(
                    owner, call, width, callback, domain)
                item["byte_order"] = byte_order
                return item

            # gpio_generic_chip_init snapshots data and direction into library
            # private shadow state. These state writes are deliberately
            # separate from MMIO accounting.
            init_evidence = evidence("gpio_generic_chip_init")
            owner_extraction = extractions.get(owner.symbol_id or owner.name)
            if owner_extraction is not None:
                summary_start = len(owner_extraction.ops)
                if bank_model:
                    owner_extraction.ops.append(_semantic_op(
                        "StateRead", init_evidence, width,
                        field=bank_model["state_field"],
                        var=bank_model["state_field"]))
                if variant_model:
                    owner_extraction.ops.append(_semantic_op(
                        "StateRead", init_evidence, width,
                        field=variant_model["state_field"],
                        var="gpio_config_variant"))
                for entry in dat:
                    owner_extraction.ops.extend([
                        _op_for_entry(
                            "Read", entry, store, macros, width, init_evidence,
                            var="gpio_initial_data"),
                        _semantic_op(
                            "StateWrite", init_evidence, width,
                            field="gpio_sdata", value="gpio_initial_data"),
                    ])
                if fields.get("set") and not fields.get("clr") and not unreadable_set:
                    for entry in fields.get("set", []):
                        owner_extraction.ops.extend([
                            _op_for_entry(
                                "Read", entry, store, macros, width, init_evidence,
                                var="gpio_initial_data"),
                            _semantic_op(
                                "StateWrite", init_evidence, width,
                                field="gpio_sdata", value="gpio_initial_data"),
                        ])
                if unreadable_dir and (fields.get("dirout") or fields.get("dirin")):
                    owner_extraction.ops.append(_semantic_op(
                        "StateWrite", init_evidence, width,
                        field="gpio_sdir", value="0"))
                elif variant_model:
                    entry = _unconditional_entry(fields["dirout"][0])
                    owner_extraction.ops.extend([
                        _op_for_entry(
                            "Read", entry, store, macros, width, init_evidence,
                            var="gpio_initial_direction"),
                        _semantic_op(
                            "StateWrite", init_evidence, width,
                            field="gpio_sdir",
                            value=("gpio_config_variant ? "
                                   "(gpio_initial_direction ^ 0xffffffff) : "
                                   "gpio_initial_direction")),
                    ])
                else:
                    for entry in fields.get("dirout", []):
                        owner_extraction.ops.extend([
                            _op_for_entry(
                                "Read", entry, store, macros, width, init_evidence,
                                var="gpio_initial_direction"),
                            _semantic_for_entry(
                                "StateWrite", entry, init_evidence, width,
                                field="gpio_sdir", value="gpio_initial_direction"),
                        ])
                    for entry in fields.get("dirin", []):
                        owner_extraction.ops.extend([
                            _op_for_entry(
                                "Read", entry, store, macros, width, init_evidence,
                                var="gpio_initial_direction"),
                            _semantic_for_entry(
                                "StateWrite", entry, init_evidence, width,
                                field="gpio_sdir",
                                value="gpio_initial_direction ^ 0xffffffff"),
                        ])
                if bank_model:
                    _apply_gpio_bank_model(
                        owner_extraction.ops[summary_start:], bank_model)
                owner_extraction.ops.sort(key=lambda op: op.line)

            callbacks: list[tuple[Func, FuncExtraction]] = []
            get_evidence = evidence("gpio_chip.get")
            get_entries = (fields.get("set", []) if read_output_set else dat)
            callbacks.append(_make_callback(
                owner, "get",
                [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                "read_config", "get",
                sum(([
                    _op_for_entry("Read", entry, store, macros, width,
                                  get_evidence, var="value"),
                    _semantic_op(
                        "Return", get_evidence, width,
                        value="(value & BIT(offset)) != 0"),
                ] for entry in get_entries), [])))
            callbacks.append(_make_callback(
                owner, "get_multiple",
                [("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
                 ("bits", "unsigned long *")],
                "read_config", "get_multiple",
                sum(([
                    _op_for_entry("Read", entry, store, macros, width,
                                  get_evidence, var="value"),
                    _semantic_op(
                        "OutputWrite", get_evidence, width, var="bits",
                        value="(*bits & ~(*mask)) | (value & *mask)"),
                    _semantic_op("Return", get_evidence, width, value="0"),
                ] for entry in get_entries), [])))

            set_entries = fields.get("set", []) or dat
            clr_entries = fields.get("clr", [])
            set_evidence = evidence("gpio_chip.set")
            if clr_entries and fields.get("set"):
                set_body = [
                    _op_for_entry(
                        "Write", _conditional_entry(entry, "value != 0"),
                        store, macros, width, set_evidence,
                        value="BIT(offset)") for entry in set_entries]
                set_body += [
                    _op_for_entry(
                        "Write", _conditional_entry(entry, "value == 0"),
                        store, macros, width, set_evidence,
                        value="BIT(offset)") for entry in clr_entries]
            else:
                next_data = (
                    "value ? (__shadow_data | BIT(offset)) : "
                    "(__shadow_data & ~BIT(offset))")
                set_body = [
                    _semantic_op(
                        "StateRead", set_evidence, width,
                        field="gpio_sdata", var="__shadow_data"),
                    _semantic_op(
                        "StateWrite", set_evidence, width,
                        field="gpio_sdata", value=next_data),
                ]
                set_body += [
                    _op_for_entry(
                        "Write", entry, store, macros, width, set_evidence,
                        value=next_data) for entry in set_entries]
            set_ops = set_body + [
                _semantic_op("Return", set_evidence, width, value="0")]
            callbacks.append(_make_callback(
                owner, "set",
                [("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
                 ("value", "int")],
                "write_config", "set", set_ops))

            if clr_entries and fields.get("set"):
                multiple_ops = [
                    _op_for_entry(
                        "Write", _conditional_entry(entry, "(*bits & *mask) != 0"),
                        store, macros, width, set_evidence,
                        value="*bits & *mask") for entry in set_entries]
                multiple_ops += [
                    _op_for_entry(
                        "Write", _conditional_entry(
                            entry, "((~(*bits)) & *mask) != 0"),
                        store, macros, width, set_evidence,
                        value="(~(*bits)) & *mask") for entry in clr_entries]
            else:
                next_multiple = (
                    "(__shadow_data & ~(*mask)) | (*bits & *mask)")
                multiple_ops = [
                    _semantic_op(
                        "StateRead", set_evidence, width,
                        field="gpio_sdata", var="__shadow_data"),
                    _semantic_op(
                        "StateWrite", set_evidence, width,
                        field="gpio_sdata", value=next_multiple),
                ]
                multiple_ops += [
                    _op_for_entry(
                        "Write", entry, store, macros, width, set_evidence,
                        value=next_multiple) for entry in set_entries]
            multiple_ops.append(
                _semantic_op("Return", set_evidence, width, value="0"))
            callbacks.append(_make_callback(
                owner, "set_multiple",
                [("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
                 ("bits", "unsigned long *")],
                "write_config", "set_multiple", multiple_ops))

            direction_entries = fields.get("dirout", []) + fields.get("dirin", [])
            if direction_entries:
                dir_evidence = evidence("gpio_chip.direction")
                input_value = "__shadow_dir & ~BIT(offset)"
                output_value = "__shadow_dir | BIT(offset)"
                input_ops = [
                    _semantic_op(
                        "StateRead", dir_evidence, width,
                        field="gpio_sdir", var="__shadow_dir"),
                    _semantic_op(
                        "StateWrite", dir_evidence, width,
                        field="gpio_sdir", value=input_value),
                ]
                direction_output_ops = [
                    _semantic_op(
                        "StateRead", dir_evidence, width,
                        field="gpio_sdir", var="__shadow_dir"),
                    _semantic_op(
                        "StateWrite", dir_evidence, width,
                        field="gpio_sdir", value=output_value),
                ]
                if variant_model:
                    selector_read = _semantic_op(
                        "StateRead", dir_evidence, width,
                        field=variant_model["state_field"],
                        var="gpio_config_variant")
                    input_ops.insert(0, copy.deepcopy(selector_read))
                    direction_output_ops.insert(0, copy.deepcopy(selector_read))
                    entry = _unconditional_entry(fields["dirout"][0])
                    input_ops.append(_op_for_entry(
                        "Write", entry, store, macros, width, dir_evidence,
                        value=("gpio_config_variant ? "
                               f"(({input_value}) ^ 0xffffffff) : "
                               f"({input_value})")))
                    direction_output_ops.append(_op_for_entry(
                        "Write", entry, store, macros, width, dir_evidence,
                        value=("gpio_config_variant ? "
                               f"(({output_value}) ^ 0xffffffff) : "
                               f"({output_value})")))
                else:
                    for entry in fields.get("dirout", []):
                        input_ops.append(_op_for_entry(
                            "Write", entry, store, macros, width,
                            dir_evidence, value=input_value))
                        direction_output_ops.append(_op_for_entry(
                            "Write", entry, store, macros, width,
                            dir_evidence, value=output_value))
                    for entry in fields.get("dirin", []):
                        input_ops.append(_op_for_entry(
                            "Write", entry, store, macros, width,
                            dir_evidence, value=f"({input_value}) ^ 0xffffffff"))
                        direction_output_ops.append(_op_for_entry(
                            "Write", entry, store, macros, width,
                            dir_evidence, value=f"({output_value}) ^ 0xffffffff"))
                input_ops.append(
                    _semantic_op("Return", dir_evidence, width, value="0"))
                output_ops = (
                    direction_output_ops + set_body if no_set_on_input
                    else set_body + direction_output_ops)
                output_ops.append(
                    _semantic_op("Return", dir_evidence, width, value="0"))
                callbacks.append(_make_callback(
                    owner, "direction_input",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                    "write_config", "direction_input", input_ops))
                callbacks.append(_make_callback(
                    owner, "direction_output",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
                     ("value", "int")],
                    "write_config", "direction_output", output_ops))
                get_direction_ops = []
                if variant_model:
                    entry = _unconditional_entry(fields["dirout"][0])
                    get_direction_ops.extend([
                        _semantic_op(
                            "StateRead", dir_evidence, width,
                            field=variant_model["state_field"],
                            var="gpio_config_variant"),
                        _op_for_entry(
                            "Read", entry, store, macros, width,
                            dir_evidence, var="direction"),
                        _semantic_op(
                            "Return", dir_evidence, width,
                            value=("gpio_config_variant ? "
                                   "((direction & BIT(offset)) != 0 ? 1 : 0) : "
                                   "((direction & BIT(offset)) != 0 ? 0 : 1)")),
                    ])
                elif unreadable_dir:
                    get_direction_ops.append(_semantic_op(
                        "StateRead", dir_evidence, width,
                        field="gpio_sdir", var="direction"))
                    get_direction_ops.append(_semantic_op(
                        "Return", dir_evidence, width,
                        value="(direction & BIT(offset)) != 0 ? 0 : 1"))
                else:
                    for entry in fields.get("dirout", []):
                        get_direction_ops.extend([
                            _op_for_entry(
                                "Read", entry, store, macros, width,
                                dir_evidence, var="direction"),
                            _semantic_for_entry(
                                "Return", entry, dir_evidence, width,
                                value="(direction & BIT(offset)) != 0 ? 0 : 1"),
                        ])
                    for entry in fields.get("dirin", []):
                        get_direction_ops.extend([
                            _op_for_entry(
                                "Read", entry, store, macros, width,
                                dir_evidence, var="direction"),
                            _semantic_for_entry(
                                "Return", entry, dir_evidence, width,
                                value="(direction & BIT(offset)) != 0 ? 1 : 0"),
                        ])
                callbacks.append(_make_callback(
                    owner, "get_direction",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                    "read_config", "get_direction", get_direction_ops))

            for synthetic, extraction in callbacks:
                if not extraction.ops:
                    continue
                if bank_model:
                    _apply_gpio_bank_model(extraction.ops, bank_model)
                    extraction.ops.insert(0, _semantic_op(
                        "StateRead", evidence(
                            synthetic.synthetic_callback_table or
                            "gpio_chip.callback"), width,
                        field=bank_model["state_field"],
                        var=bank_model["state_field"]))
                synthetic_funcs.append(synthetic)
                synthetic_extractions[synthetic.symbol_id] = extraction

            resolved_fields = {}
            for field_name in ("dat", "set", "clr", "dirout", "dirin"):
                resolved = []
                for entry in fields.get(field_name, []):
                    flat_addr, register = resolve_addr(entry["expr"], store, macros)
                    offset = macros.offset(register) if register else None
                    if offset is None and "Offset" in flat_addr:
                        offset = flat_addr["Offset"].get("offset")
                    if offset is None and "Fixed" in flat_addr:
                        offset = flat_addr["Fixed"]
                    base = None
                    dynamic_expr = None
                    if "Offset" in flat_addr:
                        base = flat_addr["Offset"].get("base")
                    elif "Indirect" in flat_addr:
                        base = flat_addr["Indirect"].get("base_reg")
                        dynamic_expr = flat_addr["Indirect"].get("expr")
                    resolved.append({
                        "expr": entry["expr"], "register": register,
                        "offset": int(offset) if offset is not None else None,
                        "base": base,
                        "resource_index": resource_bindings.get(base),
                        "dynamic_expr": dynamic_expr,
                    })
                if resolved:
                    resolved_fields[field_name] = resolved
            stats.append({
                "function": owner.name,
                "line": call.line,
                "config": config,
                "width_bytes": width,
                "fields": {name: [entry["expr"] for entry in entries]
                           for name, entries in sorted(fields.items())},
                "resolved_fields": resolved_fields,
                "variant": variant,
                "variant_model": variant_model,
                "bank_model": bank_model,
                "flags_value": flag_value,
                "byte_order": byte_order,
                "read_output_set": read_output_set,
                "unreadable_set": unreadable_set,
                "unreadable_dir": unreadable_dir,
                "no_set_on_input": no_set_on_input,
                "callbacks": [func.synthetic_callback_table
                              for func, extraction in callbacks if extraction.ops],
            })
    return synthetic_funcs, synthetic_extractions, stats


def _sdhci_initializer_blocks(text: str):
    pattern = re.compile(
        r"\bstruct\s+sdhci_ops\s+([A-Za-z_]\w*)\s*=\s*\{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield match.group(1), text[start + 1:index], match.start()
                    break


def _sdhci_evidence(source: str, text: str, offset: int, field: str,
                    callee: str, kind: str, width: int) -> dict:
    line = text.count("\n", 0, offset) + 1
    return {
        "site_id": f"{source}:{line}:0:{offset}:sdhci_ops.{field}",
        "source": source,
        "line": line,
        "column": 0,
        "offset": offset,
        "function": f"sdhci_ops.{field}",
        "symbol": callee,
        "callee": callee,
        "ast_kind": "INIT_LIST_EXPR",
        "access_kind": kind,
        "width_bytes": width,
        "origin": "subsystem_summary",
        "access_domain": "mmio",
        "subsystem_summary": "sdhci_ops",
        "effective_callee": callee,
        "library_callback": f"sdhci_ops.{field}",
        "summary_contract": "linux.sdhci_ops",
    }


_SDHCI_ACCESSOR_FIELDS = {
    "read_l": ("Read", 4), "read_w": ("Read", 2), "read_b": ("Read", 1),
    "write_l": ("Write", 4), "write_w": ("Write", 2),
    "write_b": ("Write", 1),
}

_SDHCI_CORE_DELEGATES = {
    "sdhci_set_clock", "sdhci_set_bus_width", "sdhci_reset",
    "sdhci_set_uhs_signaling",
}


def _sdhci_contract_evidence(evidence: dict, field: str, callee: str,
                             *, byte_order: str = "native",
                             access_domain: str = "mmio") -> dict:
    out = copy.deepcopy(evidence)
    out.update({
        "origin": "subsystem_summary",
        "subsystem_summary": "sdhci_accessor",
        "effective_callee": callee,
        "library_callback": f"sdhci_ops.{field}",
        "summary_contract": "linux.sdhci_ops",
        "access_domain": access_domain,
    })
    if byte_order != "native":
        out["byte_order"] = byte_order
    return out


def _sdhci_branch(op: Op, condition: str) -> Op:
    item = copy.deepcopy(op)
    item.condition = condition
    item.cond_stack = list(op.cond_stack) + [condition]
    item.control_stack = list(op.control_stack) + [{
        "kind": "cond", "guard": condition, "branch": "contract",
    }]
    return item


def _sdhci_public_accessor_ops(field: str, callee: str, evidence: dict,
                               *, source_op: Op | None = None,
                               macros=None) -> list[Op]:
    """Materialize stable SDHCI accessor semantics from public headers."""
    contract = _SDHCI_ACCESSOR_FIELDS.get(field)
    if contract is None:
        return []
    kind, width = contract
    base = "host->ioaddr"
    reg = "reg"
    value = "value"
    template = source_op or Op(
        kind=kind, addr=addr_indirect(base, 0, reg), width=width,
        value=value if kind == "Write" else None, var="value" if kind == "Read" else None,
        evidence=evidence)
    if source_op is not None:
        base = addr_base_of(source_op.addr) or base
        if "Indirect" in source_op.addr:
            reg = source_op.addr["Indirect"].get("expr") or reg
        elif source_op.reg_name:
            reg = source_op.reg_name
        value = source_op.value or value

    be32bs = callee.startswith("sdhci_be32bs_")
    byte_order = ("big" if be32bs and field != "read_b" else "native")
    mmio_evidence = _sdhci_contract_evidence(
        evidence, field, callee, byte_order=byte_order)
    state_evidence = _sdhci_contract_evidence(
        evidence, field, callee, access_domain="source_state")

    def dynamic(expr: str) -> dict:
        return addr_indirect(base, 0, expr)

    def symbolic(name: str) -> tuple[dict, str | None]:
        offset = macros.offset(name) if macros is not None else None
        if offset is None:
            return dynamic(name), None
        return addr_offset(base, offset), name

    if not be32bs:
        op = copy.deepcopy(template)
        op.addr = dynamic(reg)
        op.width = width
        op.evidence = mmio_evidence
        if kind == "Read":
            op.kind, op.var, op.value = "Read", "value", None
            returned = Op(
                kind="Return", addr=addr_fixed(0), width=0, value="value",
                evidence=state_evidence, source_loc=op.source_loc,
                line=op.line)
            return [op, returned]
        op.kind, op.value = "Write", value
        return [op]

    if field == "read_l":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(reg), 4
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "read_w":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(f"({reg}) ^ 0x2"), 2
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "read_b":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(f"({reg}) ^ 0x3"), 1
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "write_l":
        write = copy.deepcopy(template)
        write.kind, write.addr, write.width = "Write", dynamic(reg), 4
        write.value, write.evidence = value, mmio_evidence
        return [write]

    base_expr = f"({reg}) & ~0x3"
    if field == "write_b":
        shift = f"(({reg}) & 0x3) * 8"
        rmw = copy.deepcopy(template)
        rmw.kind, rmw.addr, rmw.width = "ReadModifyWrite", dynamic(base_expr), 4
        rmw.var = "__old"
        rmw.value = (f"((__old & ~(0xff << ({shift}))) | "
                     f"((({value}) & 0xff) << ({shift})))")
        rmw.evidence = mmio_evidence
        return [rmw]

    transfer_addr, transfer_reg = symbolic("SDHCI_TRANSFER_MODE")
    transfer = f"({reg}) == (SDHCI_TRANSFER_MODE)"
    command = f"({reg}) == (SDHCI_COMMAND)"
    ordinary = f"!(({transfer}) || ({command}))"
    save = Op(
        kind="StateWrite", addr=addr_fixed(0), width=2, value=value,
        state_field="xfer_mode_shadow", evidence=state_evidence,
        source_loc=template.source_loc, line=template.line)
    load = Op(
        kind="StateRead", addr=addr_fixed(0), width=2,
        state_field="xfer_mode_shadow", var="__xfer_mode_shadow",
        evidence=state_evidence, source_loc=template.source_loc,
        line=template.line)
    command_write = Op(
        kind="Write", addr=transfer_addr, reg_name=transfer_reg, width=4,
        value=f"(({value}) << 16) | __xfer_mode_shadow",
        evidence=mmio_evidence, source_loc=template.source_loc,
        line=template.line)
    shift = f"(({reg}) & 0x2) * 8"
    default_rmw = Op(
        kind="ReadModifyWrite", addr=dynamic(base_expr), width=4,
        value=(f"((__old & ~(0xffff << ({shift}))) | "
               f"((({value}) & 0xffff) << ({shift})))"),
        var="__old", evidence=mmio_evidence,
        source_loc=template.source_loc, line=template.line)
    return [
        _sdhci_branch(save, transfer),
        _sdhci_branch(load, command),
        _sdhci_branch(command_write, command),
        _sdhci_branch(default_rmw, ordinary),
    ]


def _annotate_private_sdhci_accessor(extraction: FuncExtraction, field: str,
                                     callee: str, evidence: dict,
                                     macros=None) -> None:
    expanded: list[Op] = []
    for op in extraction.ops:
        if op.kind not in {"Read", "Write", "ReadModifyWrite"}:
            expanded.append(op)
            continue
        effective = (op.evidence or {}).get("effective_callee")
        if (effective in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
                or effective in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS):
            expanded.extend(_sdhci_public_accessor_ops(
                field, effective, op.evidence or evidence,
                source_op=op, macros=macros))
            continue
        op.evidence = _sdhci_contract_evidence(
            op.evidence or evidence, field, callee)
        expanded.append(op)
    extraction.ops = expanded
    for op in extraction.ops:
        if op.kind == "Return":
            op.evidence = _sdhci_contract_evidence(
                op.evidence or evidence, field, callee,
                access_domain="source_result")
    if field.startswith("read_") and extraction.return_expr and not any(
            op.kind == "Return" for op in extraction.ops):
        extraction.ops.append(Op(
            kind="Return", addr=addr_fixed(0), width=0,
            value=extraction.return_expr,
            evidence=_sdhci_contract_evidence(
                evidence, field, callee, access_domain="source_result")))


def infer_sdhci_ops_summaries(funcs: list[Func], extractions: dict, macros
                              ) -> tuple[list[Func], dict, list[dict], list[dict], list[dict]]:
    if not funcs:
        return [], {}, [], [], []
    source = funcs[0].source_path
    try:
        text = open(source, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], {}, [], [], []
    target_names = {func.name for func in funcs}
    extraction_by_name = {
        func.name: extractions.get(func.symbol_id or func.name)
        or extractions.get(func.module_name or func.name)
        or extractions.get(func.name)
        for func in funcs
    }
    synthetic_funcs: list[Func] = []
    synthetic_extractions: dict[str, FuncExtraction] = {}
    summaries: list[dict] = []
    unmodeled: list[dict] = []
    delegates: list[dict] = []
    for table_name, body, block_offset in _sdhci_initializer_blocks(text):
        for part in _split_initializer(body):
            match = re.match(
                r"\.\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)", part)
            if not match:
                continue
            field, callee = match.groups()
            entry_offset = block_offset + body.find(part)
            evidence = _sdhci_evidence(
                source, text, entry_offset, field, callee,
                "read" if field.startswith("read_") else "write",
                _SDHCI_ACCESSOR_FIELDS.get(field, ("", 4))[1])
            if callee in target_names and field in _SDHCI_ACCESSOR_FIELDS:
                extraction = extraction_by_name.get(callee)
                if extraction is not None:
                    _annotate_private_sdhci_accessor(
                        extraction, field, callee, evidence, macros)
                    summaries.append({
                        "table": table_name, "field": field,
                        "callee": callee, "module": callee,
                        "width_bytes": _SDHCI_ACCESSOR_FIELDS[field][1],
                        "implementation": "source-private",
                    })
                continue
            if callee in _SDHCI_CORE_DELEGATES:
                delegates.append({
                    "table": table_name, "field": field, "callee": callee,
                    "line": evidence["line"],
                    "summary_contract": "linux.sdhci_core_export",
                })
                continue
            is_read = callee in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
            is_write = callee in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS
            if not is_read and not is_write:
                unmodeled.append({
                    "table": table_name,
                    "field": field,
                    "callee": callee,
                    "line": text.count("\n", 0, entry_offset) + 1,
                    "reason": "external SDHCI core callback lacks register summary",
                })
                continue
            width = mmio.infer_width(callee)
            params = [("host", "struct sdhci_host *")]
            if is_write:
                params.extend([("value", f"u{width * 8}"), ("reg", "int")])
                value, address_text = mmio.write_value_addr(
                    callee, ["host", "value", "reg"])
                kind = "Write"
                role = "write_config"
            else:
                params.append(("reg", "int"))
                address_text = mmio.read_addr_expr(callee, ["host", "reg"])
                value = None
                kind = "Read"
                role = "read_config"
            address, register = resolve_addr(
                address_text, {"host": BasePtr("host")}, macros)
            name = f"{table_name}__{field}"
            func = Func(
                name=name, line=evidence["line"], cursor=None, params=params,
                source_path=source, symbol_id=name, module_name=name,
                is_static=True, synthetic_role=role, synthetic_context="thread",
                synthetic_callback_table=f"sdhci_ops.{field}",
                synthetic_return_type=f"u{width * 8}" if is_read else "void",
            )
            template = Op(
                kind=kind, addr=address, width=width, value=value,
                reg_name=register, var="value" if is_read else None,
                evidence=evidence,
                source_loc=f"subsystem sdhci_ops.{field}:{evidence['line']}",
                line=evidence["line"],
            )
            ops = _sdhci_public_accessor_ops(
                field, callee, evidence, source_op=template, macros=macros)
            extraction = FuncExtraction(
                name=name, params=[param for param, _ctype in params], ops=ops)
            synthetic_funcs.append(func)
            synthetic_extractions[name] = extraction
            summaries.append({
                "table": table_name, "field": field, "callee": callee,
                "module": name, "width_bytes": width,
            })
    return (synthetic_funcs, synthetic_extractions, summaries,
            unmodeled, delegates)


def _virtio_state_evidence(evidence: dict, contract: str) -> dict:
    out = copy.deepcopy(evidence)
    out["origin"] = "subsystem_summary"
    out["summary_contract"] = contract
    return out


def _virtio_config_field(member: str) -> str:
    text = re.sub(r"\s+", "", member or "value")
    offsetof = re.search(r"offsetof\([^,]+,([^)]+)\)", text)
    if offsetof:
        text = offsetof.group(1)
    text = text.replace("->", ".")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "value"
    return f"virtio_cfg_{text.lower()}"


def _virtio_queue_prefix(extraction: FuncExtraction) -> str:
    expressions = [
        (op.evidence or {}).get("queue_expr", "") for op in extraction.ops
        if (op.evidence or {}).get("summary_contract") == "linux.virtqueue"]
    if any(re.search(r"(?:->|\.)sts\b|status", expr, re.I)
           for expr in expressions):
        return "virtio_sts"
    if any(re.search(r"(?:->|\.)evt\b|event", expr, re.I)
           for expr in expressions):
        return "virtio_evt"
    name = extraction.name.lower()
    return "virtio_sts" if "status" in name else "virtio_evt"


def _virtio_loop_key(frame: dict) -> str:
    return frame.get("source") or frame.get("guard", "")


def _rewrite_virtio_loop_frames(extraction: FuncExtraction, prefix: str) -> None:
    bounds: dict[str, str] = {}
    for op in extraction.ops:
        evidence = op.evidence or {}
        operation = evidence.get("queue_operation")
        if not operation:
            continue
        for frame in op.control_stack:
            if frame.get("kind") != "loop":
                continue
            if operation in {"virtqueue_get_buf"}:
                field = f"{prefix}_completed"
            elif operation == "virtqueue_detach_unused_buf":
                field = f"{prefix}_outstanding"
            elif operation == "virtqueue_add_inbuf_cache_clean":
                field = f"{prefix}_queue_depth"
            else:
                continue
            bounds[_virtio_loop_key(frame)] = field
    for op in extraction.ops:
        rewritten = []
        for frame in op.control_stack:
            item = copy.deepcopy(frame)
            for key in ("guard", "source"):
                item[key] = re.sub(
                    r"sizeof\s*\(\s*struct\s+[A-Za-z_]\w*_devids\s*\)",
                    "8", item.get(key, ""))
            field = bounds.get(_virtio_loop_key(frame))
            if field:
                item.update({
                    "kind": "loop", "loop_kind": "for",
                    "init": "unsigned int __virtio_i = 0",
                    "guard": f"__virtio_i < vi->{field}",
                    "step": "__virtio_i++",
                    "subsystem_contract": "linux.virtqueue.bounded",
                })
            rewritten.append(item)
        op.control_stack = rewritten
        op.cond_stack = [frame.get("guard", "") for frame in rewritten
                         if frame.get("guard")]
        op.condition = op.cond_stack[-1] if op.cond_stack else None


def _virtio_state_ops(op: Op, prefix: str) -> list[Op]:
    evidence = op.evidence or {}
    contract = evidence.get("summary_contract")
    if contract == "linux.virtio_config":
        field = _virtio_config_field(evidence.get("config_member", "value"))
        semantic = _virtio_state_evidence(evidence, contract)
        if op.kind == "Read":
            var = op.var if re.fullmatch(r"[A-Za-z_]\w*", op.var or "") else field
            return [Op(
                kind="StateRead", addr=addr_fixed(0), width=op.width,
                state_field=field, var=var, evidence=semantic,
                condition=op.condition, cond_stack=list(op.cond_stack),
                control_stack=copy.deepcopy(op.control_stack),
                source_loc=op.source_loc, line=op.line)]
        if op.kind == "Write":
            return [Op(
                kind="StateWrite", addr=addr_fixed(0), width=op.width,
                state_field=field, value=op.value, evidence=semantic,
                condition=op.condition, cond_stack=list(op.cond_stack),
                control_stack=copy.deepcopy(op.control_stack),
                source_loc=op.source_loc, line=op.line)]
    if contract != "linux.virtqueue":
        return [op]
    operation = evidence.get("queue_operation", "")
    semantic = _virtio_state_evidence(evidence, contract)
    state = None
    delta = None
    result_var = None
    if operation == "virtqueue_add_inbuf_cache_clean":
        state, delta = f"{prefix}_available", 1
    elif operation == "virtqueue_add_outbuf":
        state, delta = f"{prefix}_outstanding", 1
    elif operation == "virtqueue_get_buf":
        state, delta = f"{prefix}_completed", -1
        result_var = op.var
    elif operation == "virtqueue_detach_unused_buf":
        state, delta = f"{prefix}_outstanding", -1
        result_var = op.var
    elif operation == "virtqueue_get_vring_size":
        state = f"{prefix}_queue_depth"
        result_var = op.var
    elif operation == "virtqueue_kick":
        return [Op(
            kind="StateWrite", addr=addr_fixed(0), width=4,
            state_field=f"{prefix}_notified", value="1",
            evidence=semantic, condition=op.condition,
            cond_stack=list(op.cond_stack),
            control_stack=copy.deepcopy(op.control_stack),
            source_loc=op.source_loc, line=op.line)]
    if state is None:
        return [op]
    temp = f"__{state}"
    read = Op(
        kind="StateRead", addr=addr_fixed(0), width=4,
        state_field=state, var=result_var or temp, evidence=semantic,
        condition=op.condition, cond_stack=list(op.cond_stack),
        control_stack=copy.deepcopy(op.control_stack),
        source_loc=op.source_loc, line=op.line)
    if delta is None:
        return [read]
    source_var = result_var or temp
    value = (f"({source_var}) + 1" if delta > 0
             else f"(({source_var}) > 0 ? ({source_var}) - 1 : 0)")
    write = Op(
        kind="StateWrite", addr=addr_fixed(0), width=4,
        state_field=state, value=value, evidence=semantic,
        condition=op.condition, cond_stack=list(op.cond_stack),
        control_stack=copy.deepcopy(op.control_stack),
        source_loc=op.source_loc, line=op.line)
    return [read, write]


def _op_effective_line(op: Op) -> int:
    inlined = (op.evidence or {}).get("inlined_at", [])
    return int(inlined[-1].get("line", op.line)) if inlined else int(op.line)


def _insert_virtio_lifecycle_state(funcs: list[Func], extractions: dict, tu) -> None:
    for func in funcs:
        extraction = (extractions.get(func.symbol_id or func.name)
                      or extractions.get(func.module_name or func.name)
                      or extractions.get(func.name))
        if extraction is None:
            continue
        additions: list[Op] = []
        for cursor, control in walk_with_control(func.cursor):
            if cursor.kind != cx.CursorKind.BINARY_OPERATOR:
                continue
            text = source_text(tu, cursor).strip()
            match = re.fullmatch(
                r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
                r"(?:->|\.)ready\s*=\s*(true|false)\s*;?", text)
            if not match:
                continue
            loc = cursor.location
            line = loc.line if loc else 0
            evidence = {
                "site_id": (f"{func.source_path}:{line}:0:"
                            f"{getattr(loc, 'offset', 0) or 0}:virtio.ready"),
                "source": func.source_path, "line": line, "column": 0,
                "offset": getattr(loc, "offset", 0) or 0,
                "function": func.name, "symbol": func.symbol_id or func.name,
                "origin": "subsystem_summary",
                "subsystem_summary": "virtio_lifecycle",
                "summary_contract": "linux.virtio.lifecycle",
                "access_domain": "source_state",
            }
            additions.append(Op(
                kind="StateWrite", addr=addr_fixed(0), width=1,
                state_field="ready", value="1" if match.group(1) == "true" else "0",
                evidence=evidence, line=line,
                condition=(control[-1].get("guard") if control else None),
                cond_stack=[frame.get("guard", "") for frame in control
                            if frame.get("guard")],
                control_stack=[dict(frame) for frame in control],
                source_loc=f"{func.name}:{line}"))
        for addition in additions:
            index = next((index for index, op in enumerate(extraction.ops)
                          if _op_effective_line(op) > addition.line),
                         len(extraction.ops))
            extraction.ops.insert(index, addition)


def infer_virtio_state_summaries(funcs: list[Func], extractions: dict, tu
                                 ) -> list[dict]:
    _insert_virtio_lifecycle_state(funcs, extractions, tu)
    summaries = []
    seen: set[int] = set()
    for extraction in extractions.values():
        if id(extraction) in seen:
            continue
        seen.add(id(extraction))
        if not any((op.evidence or {}).get("summary_contract") in {
                "linux.virtio_config", "linux.virtqueue"}
                for op in extraction.ops):
            continue
        prefix = _virtio_queue_prefix(extraction)
        _rewrite_virtio_loop_frames(extraction, prefix)
        rewritten = []
        for op in extraction.ops:
            rewritten.extend(_virtio_state_ops(op, prefix))
        extraction.ops = rewritten
        summaries.append({
            "module": extraction.name,
            "config_ops": sum((op.evidence or {}).get("summary_contract")
                              == "linux.virtio_config" for op in rewritten),
            "queue_ops": sum((op.evidence or {}).get("summary_contract")
                             == "linux.virtqueue" for op in rewritten),
        })
    return summaries


def infer_subsystem_summaries(funcs: list[Func], extractions: dict,
                              macros, tu) -> tuple[list[Func], dict, dict]:
    virtio_stats = infer_virtio_state_summaries(funcs, extractions, tu)
    gpio_funcs, gpio_extractions, gpio_stats = infer_gpio_generic_summaries(
        funcs, extractions, macros, tu)
    (sdhci_funcs, sdhci_extractions, sdhci_stats,
     unmodeled, delegates) = infer_sdhci_ops_summaries(
        funcs, extractions, macros)
    combined = dict(gpio_extractions)
    combined.update(sdhci_extractions)
    return gpio_funcs + sdhci_funcs, combined, {
        "gpio_generic": gpio_stats,
        "sdhci_ops": sdhci_stats,
        "sdhci_delegates": delegates,
        "virtio_state": virtio_stats,
        "unmodeled_callbacks": unmodeled,
    }
