"""GPIO generic chip subsystem summary inference."""
from __future__ import annotations

from ._common import *


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

