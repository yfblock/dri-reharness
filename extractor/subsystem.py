"""Type/callee-driven summaries for Linux subsystem library semantics."""
from __future__ import annotations

import copy
import re
from collections import defaultdict

import clang.cindex as cx

from . import mmio
from .accounting import callsite_evidence
from .ast_model import Func, function_calls, source_text, walk_with_control
from .dataflow import FuncExtraction, Op, eval_expr, resolve_addr
from .taint import BasePtr, Const


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


def _base_store(func: Func, tu) -> dict:
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
            name: ("DeviceState" if name == "gc" else "UInt")
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
            store = _base_store(owner, tu)
            variant = any(len(fields.get(name, [])) > 1
                          for name in ("dat", "set", "clr", "dirout", "dirin"))
            variant = variant or bool(fields.get("dirout") and fields.get("dirin"))
            flag_text = " ".join(
                entry.get("expr", "") for entry in fields.get("flags", []))
            flag_value = 0
            if fields.get("flags"):
                evaluated_flags = eval_expr(
                    fields["flags"][-1].get("expr", ""), {}, macros)
                flag_value = (evaluated_flags.n
                              if isinstance(evaluated_flags, Const) else None)
            flag_byte_order = 1 << 3
            flag_read_output_set = 1 << 4
            supported_flag_mask = flag_byte_order | flag_read_output_set
            if flag_value is None:
                flag_tokens = {
                    token.strip() for token in re.sub(r"[()]", "", flag_text).split("|")
                    if token.strip()
                }
                flag_constants = {
                    "GPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER": flag_byte_order,
                    "GPIO_GENERIC_READ_OUTPUT_REG_SET": flag_read_output_set,
                }
                if flag_tokens <= {"0", "0x0", *flag_constants}:
                    flag_value = 0
                    for token in flag_tokens:
                        flag_value |= flag_constants.get(token, 0)
            unsupported_flags = (
                flag_value is None
                or bool(flag_value & ~supported_flag_mask)
                or bool(flag_value & flag_byte_order and width == 8))
            domain = (
                "gpio_generic_config_variant" if variant
                else "gpio_generic_flags_variant" if unsupported_flags
                else "mmio")
            byte_order = (
                "big" if (flag_value is not None
                          and flag_value & flag_byte_order) or re.search(
                    r"\bGPIO_GENERIC_BIG_ENDIAN_BYTE_ORDER\b", flag_text)
                else "native")
            read_output_set = bool(
                flag_value is not None and flag_value & flag_read_output_set)

            def evidence(callback: str) -> dict:
                item = _summary_evidence(
                    owner, call, width, callback, domain)
                item["byte_order"] = byte_order
                return item

            # gpio_generic_chip_init reads the initial data/direction state.
            init_evidence = evidence("gpio_generic_chip_init")
            owner_extraction = extractions.get(owner.symbol_id or owner.name)
            if owner_extraction is not None:
                init_entries = list(dat)
                if read_output_set:
                    init_entries.extend(fields.get("set", []))
                init_entries.extend(fields.get("dirout", []))
                init_entries.extend(fields.get("dirin", []))
                for entry in init_entries:
                    owner_extraction.ops.append(_op_for_entry(
                        "Read", entry, store, macros, width, init_evidence,
                        var="gpio_initial_state"))
                owner_extraction.ops.sort(key=lambda op: op.line)

            callbacks: list[tuple[Func, FuncExtraction]] = []
            get_evidence = evidence("gpio_chip.get")
            get_entries = (fields.get("set", []) if read_output_set else dat)
            callbacks.append(_make_callback(
                owner, "get",
                [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                "read_config", "get",
                [_op_for_entry("Read", entry, store, macros, width,
                               get_evidence, var="value") for entry in get_entries]))
            callbacks.append(_make_callback(
                owner, "get_multiple",
                [("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
                 ("bits", "unsigned long *")],
                "read_config", "get_multiple",
                [_op_for_entry("Read", entry, store, macros, width,
                               get_evidence, var="value") for entry in get_entries]))

            set_entries = fields.get("set", []) or dat
            clr_entries = fields.get("clr", [])
            set_evidence = evidence("gpio_chip.set")
            if clr_entries and fields.get("set"):
                set_ops = [
                    _op_for_entry("Write", entry, store, macros, width,
                                  set_evidence, value="BIT(offset)")
                    for entry in set_entries + clr_entries
                ]
            else:
                set_ops = [
                    _op_for_entry(
                        "ReadModifyWrite", entry, store, macros, width,
                        set_evidence,
                        value="value ? (__old | BIT(offset)) : (__old & ~BIT(offset))",
                        var="__old")
                    for entry in set_entries
                ]
            callbacks.append(_make_callback(
                owner, "set",
                [("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
                 ("value", "int")],
                "write_config", "set", set_ops))

            multiple_ops = [
                _op_for_entry(
                    "ReadModifyWrite", entry, store, macros, width,
                    set_evidence,
                    value="(__old & ~mask) | (bits & mask)",
                    var="__old")
                for entry in set_entries
            ]
            callbacks.append(_make_callback(
                owner, "set_multiple",
                [("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
                 ("bits", "unsigned long *")],
                "write_config", "set_multiple", multiple_ops))

            direction_entries = fields.get("dirout", []) + fields.get("dirin", [])
            if direction_entries:
                dir_evidence = evidence("gpio_chip.direction")
                input_ops = []
                output_ops = []
                for entry in fields.get("dirout", []):
                    input_ops.append(_op_for_entry(
                        "ReadModifyWrite", entry, store, macros, width,
                        dir_evidence, value="__old & ~BIT(offset)", var="__old"))
                    output_ops.append(_op_for_entry(
                        "ReadModifyWrite", entry, store, macros, width,
                        dir_evidence, value="__old | BIT(offset)", var="__old"))
                for entry in fields.get("dirin", []):
                    input_ops.append(_op_for_entry(
                        "ReadModifyWrite", entry, store, macros, width,
                        dir_evidence, value="__old | BIT(offset)", var="__old"))
                    output_ops.append(_op_for_entry(
                        "ReadModifyWrite", entry, store, macros, width,
                        dir_evidence, value="__old & ~BIT(offset)", var="__old"))
                callbacks.append(_make_callback(
                    owner, "direction_input",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                    "write_config", "direction_input", input_ops))
                callbacks.append(_make_callback(
                    owner, "direction_output",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
                     ("value", "int")],
                    "write_config", "direction_output", output_ops))
                callbacks.append(_make_callback(
                    owner, "get_direction",
                    [("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
                    "read_config", "get_direction",
                    [_op_for_entry("Read", entry, store, macros, width,
                                   dir_evidence, var="direction")
                     for entry in direction_entries]))

            for synthetic, extraction in callbacks:
                if not extraction.ops:
                    continue
                synthetic_funcs.append(synthetic)
                synthetic_extractions[synthetic.symbol_id] = extraction
            stats.append({
                "function": owner.name,
                "line": call.line,
                "config": config,
                "width_bytes": width,
                "fields": {name: [entry["expr"] for entry in entries]
                           for name, entries in sorted(fields.items())},
                "variant": variant,
                "flags_value": flag_value,
                "byte_order": byte_order,
                "read_output_set": read_output_set,
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


def infer_sdhci_ops_summaries(funcs: list[Func], macros
                              ) -> tuple[list[Func], dict, list[dict], list[dict]]:
    if not funcs:
        return [], {}, [], []
    source = funcs[0].source_path
    try:
        text = open(source, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], {}, [], []
    target_names = {func.name for func in funcs}
    synthetic_funcs: list[Func] = []
    synthetic_extractions: dict[str, FuncExtraction] = {}
    summaries: list[dict] = []
    unmodeled: list[dict] = []
    for table_name, body, block_offset in _sdhci_initializer_blocks(text):
        for part in _split_initializer(body):
            match = re.match(
                r"\.\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)", part)
            if not match:
                continue
            field, callee = match.groups()
            if callee in target_names:
                continue
            is_read = callee in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
            is_write = callee in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS
            entry_offset = block_offset + body.find(part)
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
            evidence = _sdhci_evidence(
                source, text, entry_offset, field, callee,
                "write" if is_write else "read", width)
            name = f"{table_name}__{field}"
            func = Func(
                name=name, line=evidence["line"], cursor=None, params=params,
                source_path=source, symbol_id=name, module_name=name,
                is_static=True, synthetic_role=role, synthetic_context="thread",
                synthetic_callback_table=f"sdhci_ops.{field}",
                synthetic_return_type=f"u{width * 8}" if is_read else "void",
            )
            op = Op(
                kind=kind, addr=address, width=width, value=value,
                reg_name=register, var="value" if is_read else None,
                evidence=evidence,
                source_loc=f"subsystem sdhci_ops.{field}:{evidence['line']}",
                line=evidence["line"],
            )
            extraction = FuncExtraction(
                name=name, params=[param for param, _ctype in params], ops=[op])
            synthetic_funcs.append(func)
            synthetic_extractions[name] = extraction
            summaries.append({
                "table": table_name, "field": field, "callee": callee,
                "module": name, "width_bytes": width,
            })
    return synthetic_funcs, synthetic_extractions, summaries, unmodeled


def infer_subsystem_summaries(funcs: list[Func], extractions: dict,
                              macros, tu) -> tuple[list[Func], dict, dict]:
    gpio_funcs, gpio_extractions, gpio_stats = infer_gpio_generic_summaries(
        funcs, extractions, macros, tu)
    sdhci_funcs, sdhci_extractions, sdhci_stats, unmodeled = (
        infer_sdhci_ops_summaries(funcs, macros))
    combined = dict(gpio_extractions)
    combined.update(sdhci_extractions)
    return gpio_funcs + sdhci_funcs, combined, {
        "gpio_generic": gpio_stats,
        "sdhci_ops": sdhci_stats,
        "unmodeled_callbacks": unmodeled,
    }
