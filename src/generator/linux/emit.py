from __future__ import annotations
import os
import re
import copy
from extractor.formal import walk_leaf_ops
from extractor.spec import TypeMap, PrimitiveMap, StateMap, CallbackMap, PUBLIC_CALLBACK_TYPES
from ..subsystem_runner import (portable_sdhci_accessor_only,
                               portable_virtio_state_only)
from ..common import (ops_to_c, local_decls, value_var_names,
                     replace_expr_var, addr_to_c, lowering_receipt,
                     ris_op_digest, lowering_recipes,
                     transaction_runtime_prelude, transaction_digest,
                     detect_transaction_transports,
                     transaction_runtime_prelude_filtered)


from .normalize import normalize_ops, normalize_module_ops
from .source_parse import (make_cid, callback_map, source_preserved_virtio,
    portable_function_macros, bound_resource_probe_ops, mask_c_source,
    matching_delimiter, source_function, parameter_names,
    parse_clk_ops_groups, lower_clock_source_callback_analysis,
    lower_clock_source_callback, analyze_clock_source_model_inner,
    clock_source_model, source_object_macros, lower_irq_source_callback,
    mfd_include_paths, selective_overlay_ops, probe_ops, pci_ids,
    balanced_initializer_blocks, initializer_expr, last_read_var)
from .source_models import (source_gpio_model, match_data_state_initializers,
    source_generic_irq_model, banked_irq_status_model, sdhci_source_model)
from .callbacks import (bank_priv, banked_gpio_callback, callback_signature,
    canonical_args, emit_callback, emit_evidence_only_callback,
    emit_banked_irq_source_callback, emit_banked_irq_handler,
    emit_source_generic_irq_callbacks, emit_source_gpio_callbacks,
    emit_source_gpio_callbacks)

def emit_transaction_runner(fn, module: dict, priv: str, regs: dict[str, int],
                             bind, safe_function_calls: set[str]) -> str:
    """Emit an unregistered, source-proven transaction leaf for Linux audit."""
    safe_ops, _normalized, contract_recipes = normalize_module_ops(
        module, "g", safe_function_calls)
    keep = [p for p in fn.signature.params if p.type != "DeviceState"]
    params = ", ".join(
        f"{bind.type_of(p.type) or 'u32'} {p.name}" for p in keep)
    params = (params + ", ") if params else ""
    params += f"struct {priv} *g"
    lines = [f"static void __rh_transaction_{fn.name}({params})", "{", "\tuintptr_t base = (uintptr_t)g->base;"]
    declared = {p.name for p in keep} | {"base"}
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1,
                    state_expr="g", _lowering_recipes=contract_recipes)
    if body:
        lines.append(body.replace("    ", "\t"))
    lines.append("}")
    return "\n".join(lines)

def emit_usb_callback_tables(device_name: str,
                              callbacks: dict[str, str]) -> list[str]:
    """Emit correctly typed USB ops tables without claiming lifecycle glue."""
    cid = make_cid(device_name)
    by_field = {field: fn for fn, field in callbacks.items()}
    out: list[str] = []

    ep_fields = (
        "enable", "disable", "alloc_request", "free_request", "queue",
        "dequeue", "set_halt", "set_wedge", "fifo_status", "fifo_flush")
    if any(f"usb_ep_ops.{field}" in by_field for field in ep_fields):
        out.append(
            f"static const struct usb_ep_ops {cid}_ep_ops __maybe_unused = {{")
        for field in ep_fields:
            fn = by_field.get(f"usb_ep_ops.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]

    gadget_fields = (
        "get_frame", "wakeup", "set_selfpowered", "vbus_session",
        "vbus_draw", "pullup", "udc_start", "udc_stop", "udc_set_speed",
        "match_ep")
    if any(f"usb_gadget_ops.{field}" in by_field for field in gadget_fields):
        out.append(
            f"static const struct usb_gadget_ops {cid}_gadget_ops __maybe_unused = {{")
        for field in gadget_fields:
            fn = by_field.get(f"usb_gadget_ops.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]

    hcd_fields = (
        "irq", "start", "stop", "urb_enqueue", "urb_dequeue",
        "endpoint_disable", "endpoint_reset", "get_frame_number",
        "hub_status_data", "hub_control", "clear_tt_buffer_complete",
        "bus_suspend", "bus_resume", "map_urb_for_dma",
        "unmap_urb_for_dma", "free_dev", "reset_device")
    if any(f"hc_driver.{field}" in by_field for field in hcd_fields):
        out += [
            f"static const struct hc_driver {cid}_hc_driver __maybe_unused = {{",
            f'\t.description = "{device_name}",',
            f'\t.product_desc = "reharness {device_name}",',
            "\t.hcd_priv_size = 0,",
            "\t.flags = HCD_MEMORY | HCD_USB2,",
        ]
        for field in hcd_fields:
            fn = by_field.get(f"hc_driver.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]
    return out

def emit_probe_body(module, regs, bind, indent="\t",
                     safe_function_calls: set[str] | None = None) -> list[str]:
    if module is None:
        return []
    safe_ops, _, contract_recipes = normalize_module_ops(
        module, "g", safe_function_calls,
        backend_ops=bound_resource_probe_ops(module["ops"]))
    declared: set[str] = {"base", "ret", "g", "pdev"}
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    out = []
    if decls:
        out.extend(decls.replace("    ", indent).splitlines())
    out.append(f"{indent}void __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1,
                    word_type="u32", state_expr="g",
                    _lowering_recipes=contract_recipes)
    if body:
        out.extend(body.replace("    ", indent).splitlines())
    return out

def emit_sdhci_platform(formal, device_spec, facts, priv,
                         callbacks: dict[str, str], callback_code: list[str]
                         ) -> str | None:
    model = sdhci_source_model(formal, facts)
    if model is None:
        return None
    cid = make_cid(device_spec.name)
    by_field = {field: fn for fn, field in callbacks.items()}
    delegates = {
        f"sdhci_ops.{item['field']}": item["callee"]
        for item in model["delegates"] if item.get("field") and item.get("callee")}
    has_private_ops = any(
        field.startswith("sdhci_ops.") for field in by_field) or bool(delegates)
    L = list(callback_code)
    if has_private_ops:
        L += [f"static const struct sdhci_ops {cid}_ops = {{"]
        for field in ("read_l", "read_w", "read_b", "write_l", "write_w",
                      "write_b", "voltage_switch", "set_clock", "set_bus_width", "reset",
                      "set_uhs_signaling", "set_power", "hw_reset"):
            table = f"sdhci_ops.{field}"
            function = by_field.get(table) or delegates.get(table)
            if function:
                L.append(f"\t.{field} = {function},")
        L += ["};", ""]
    pdata_names = {}
    for index, pdata in enumerate(model["pdata"]):
        name = f"{cid}_pdata_{index}"
        pdata_names[pdata["source_name"]] = name
        L += [f"static const struct sdhci_pltfm_data {name} = {{"]
        if pdata["has_ops"] and has_private_ops:
            L.append(f"\t.ops = &{cid}_ops,")
        if pdata["quirks"]:
            L.append(f"\t.quirks = {pdata['quirks']},")
        if pdata["quirks2"]:
            L.append(f"\t.quirks2 = {pdata['quirks2']},")
        L += ["};", ""]
    default_pdata = next(iter(pdata_names.values()))
    L += [f"static int {cid}_probe(struct platform_device *pdev)", "{",
          "\tconst struct sdhci_pltfm_data *pdata;",
          "\tstruct sdhci_pltfm_host *pltfm_host;",
          "\tstruct sdhci_host *host;", f"\tstruct {priv} *g;", "\tint ret;",
          "", "\tpdata = device_get_match_data(&pdev->dev);",
          f"\tif (!pdata)\n\t\tpdata = &{default_pdata};",
          f"\thost = sdhci_pltfm_init(pdev, pdata, sizeof(struct {priv}));",
          "\tif (IS_ERR(host))", "\t\treturn PTR_ERR(host);",
          "\tpltfm_host = sdhci_priv(host);",
          "\tg = sdhci_pltfm_priv(pltfm_host);",
          "\tg->dev = &pdev->dev;", "\tg->host = host;",
          "\tg->base = host->ioaddr;"]
    if model["clock"] == "optional":
        L += ["\tpltfm_host->clk = devm_clk_get_optional_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(pltfm_host->clk))",
              "\t\treturn PTR_ERR(pltfm_host->clk);"]
    elif model["clock"] == "required":
        L += ["\tpltfm_host->clk = devm_clk_get_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(pltfm_host->clk))",
              "\t\treturn PTR_ERR(pltfm_host->clk);"]
    if model["mmc_of_parse"]:
        L += ["\tret = mmc_of_parse(host->mmc);", "\tif (ret)", "\t\treturn ret;"]
    L += ["\tret = sdhci_add_host(host);", "\tif (ret)", "\t\treturn ret;",
          "\treturn 0;", "}", "",
          f"static void {cid}_remove(struct platform_device *pdev)", "{",
          "\tsdhci_pltfm_remove(pdev);", "}", "",
          f"static const struct of_device_id {cid}_of_match[] = {{"]
    if model["matches"]:
        for match in model["matches"]:
            pdata = pdata_names.get(match["pdata"], default_pdata)
            L.append(f'\t{{ .compatible = "{match["compatible"]}", '
                     f'.data = &{pdata} }},')
    else:
        L.append(f'\t{{ .compatible = "reharness,{device_spec.name}" }},')
    L += ["\t{ }", "};", f"MODULE_DEVICE_TABLE(of, {cid}_of_match);", "",
          f"static struct platform_driver {cid}_driver = {{",
          f"\t.probe = {cid}_probe,", f"\t.remove = {cid}_remove,",
          "\t.driver = {", f'\t\t.name = "{device_spec.name}",',
          f"\t\t.of_match_table = {cid}_of_match,"]
    if model["pm"]:
        L.append("\t\t.pm = &sdhci_pltfm_pmops,")
    L += ["\t},", "};", f"module_platform_driver({cid}_driver);"]
    return "\n".join(L)

def emit_platform(formal, device_spec, bind, facts, priv, regs,
                   callbacks: dict[str, str], callback_code: list[str],
                   unsupported: list[str], clock_model: dict | None = None) -> str:
    dev = device_spec.name
    safe_function_calls = set(portable_function_macros(formal))
    cid = make_cid(dev)
    _, probe_module = probe_ops(device_spec, formal)
    if (device_spec.cls in {"ahci", "virtio_mmio"}
            or (device_spec.cls == "sdhci"
                and not portable_sdhci_accessor_only(formal, device_spec))):
        probe_module = None
    by_field = {field: fn for fn, field in callbacks.items()}
    has_gpio = device_spec.cls == "gpio_controller" or any(
        f.startswith("gpio_chip.") for f in by_field)
    has_irq = any(f.startswith("irq_chip.") for f in by_field)
    has_clk = any(s.name == "clk" for s in device_spec.state)
    has_clk_ops = bool(clock_model) or any(
        f.startswith("clk_ops.") for f in by_field)
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    gpio_summaries = (summary_groups.get("gpio_generic", [])
                      if isinstance(summary_groups, dict) else [])
    gpio_variant = next((
        summary.get("variant_model") for summary in gpio_summaries
        if summary.get("variant_model")), None)
    gpio_bank = next((
        summary.get("bank_model") for summary in gpio_summaries
        if summary.get("bank_model")), None)
    pm_fields = {
        field.split(".", 1)[1]: fn for field, fn in by_field.items()
        if field.startswith("dev_pm_ops.")
    }

    L = callback_code[:] + emit_usb_callback_tables(dev, callbacks)
    clock_table_names: dict[str, str] = {}
    if clock_model:
        for group, fields in clock_model["groups"].items():
            table_name = f"{cid}_{make_cid(group)}"
            clock_table_names[group] = table_name
            L += [f"static const struct clk_ops {table_name} = {{"]
            for field in ("prepare", "unprepare", "enable", "disable",
                          "is_prepared", "is_enabled", "recalc_rate", "determine_rate",
                          "round_rate", "set_rate"):
                function = fields.get(field)
                if function:
                    L.append(f"\t.{field} = {function},")
            L += ["};", ""]
    elif has_clk_ops:
        L += [f"static const struct clk_ops {cid}_clk_ops = {{"]
        for field in ("prepare", "unprepare", "enable", "disable",
                      "is_prepared", "is_enabled", "recalc_rate", "determine_rate",
                      "round_rate", "set_rate"):
            fn = by_field.get(f"clk_ops.{field}")
            if fn:
                L.append(f"\t.{field} = {fn},")
        L += ["};", "", f"static const struct clk_init_data {cid}_clk_init = {{",
              f'\t.name = "{dev}",', f"\t.ops = &{cid}_clk_ops,",
              "\t.num_parents = 0,", "};", ""]
    if pm_fields:
        L += [f"static const struct dev_pm_ops {cid}_pm_ops = {{"]
        for field in ("suspend", "resume"):
            if field in pm_fields:
                L.append(f"\t.{field} = {pm_fields[field]},")
        L += ["};", ""]
    L += [f"static int {cid}_probe(struct platform_device *pdev)", "{",
          f"\tstruct {priv} *g;", "\tint ret;"]
    if clock_model:
        L.append("\tconst struct clk_ops *clock_ops;")
    if gpio_bank:
        L += [f"\tstruct {bank_priv(priv)} *bank;",
              "\tunsigned int bank_index = 0;", "\tunsigned int irq_index;",
              "\tint parent_irq;"]
    L += ["\tg = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);",
          "\tif (!g)", "\t\treturn -ENOMEM;",
          "\tg->dev = &pdev->dev;"]
    mmio_resources = [resource for resource in device_spec.resources
                      if resource.type == "MmioResource"]
    for index, resource in enumerate(mmio_resources):
        field = resource.bind or "base"
        L += [
            f"\tg->{field} = devm_platform_ioremap_resource(pdev, {index});",
            f"\tif (IS_ERR(g->{field}))",
            f"\t\treturn PTR_ERR(g->{field});",
        ]
    if mmio_resources and mmio_resources[0].bind not in {None, "base"}:
        L.append(f"\tg->base = g->{mmio_resources[0].bind};")
    L.append("\tplatform_set_drvdata(pdev, g);")
    for field, initializer in sorted(
            match_data_state_initializers(facts, device_spec).items()):
        L.append(f"\tg->{field} = {initializer};")
    array_states = [state for state in device_spec.state
                    if state.type == "UIntArray"]
    if gpio_bank and any(
            state.name == "nr_ports" for state in device_spec.state):
        L += [
            "\tg->nr_ports = device_get_child_node_count(&pdev->dev);",
            "\tif (!g->nr_ports)",
            "\t\treturn -ENODEV;",
            "\tg->banks = devm_kcalloc(&pdev->dev, g->nr_ports,",
            "\t\t\t\t   sizeof(*g->banks), GFP_KERNEL);",
            "\tif (!g->banks)",
            "\t\treturn -ENOMEM;",
        ]
    for state in array_states:
        L += [
            f"\tg->{state.name} = devm_kcalloc(&pdev->dev, g->nr_ports,",
            f"\t\t\t\t      sizeof(*g->{state.name}), GFP_KERNEL);",
            f"\tif (!g->{state.name})",
            "\t\treturn -ENOMEM;",
        ]
    if (gpio_bank and gpio_bank.get("property")
            and any(state.name == "ports_idx" for state in array_states)):
        L += [
            "\tdevice_for_each_child_node_scoped(&pdev->dev, child) {",
            f"\t\tif (fwnode_property_read_u32(child, \"{gpio_bank['property']}\",",
            "\t\t\t\t\t     &g->ports_idx[bank_index]))",
            "\t\t\treturn -EINVAL;",
        ]
        if gpio_bank.get("max_count"):
            L += [
                f"\t\tif (g->ports_idx[bank_index] >= {gpio_bank['max_count']})",
                "\t\t\treturn -EINVAL;",
            ]
        L += ["\t\tbank_index++;", "\t}"]
    if gpio_variant:
        L.append(
            f"\tg->{gpio_variant['state_field']} = "
            f"{gpio_variant['source_condition']};")
    if any(s.name == "ngpio" for s in device_spec.state):
        L.append("\tg->ngpio = 32;")
    if any(s.name == "skip_init" for s in device_spec.state):
        L.append('\tg->skip_init = device_property_read_bool(&pdev->dev, "reharness,skip-init");')
    if any(s.name == "hpi_regstep" for s in device_spec.state):
        L += [
            '\tif (device_property_read_u32(&pdev->dev, "hpi-regstep",',
            "\t\t\t     &g->hpi_regstep))",
            "\t\tg->hpi_regstep = 1;",
            "\tif (!g->hpi_regstep)",
            "\t\treturn -EINVAL;",
        ]
    if any(s.name == "sie_num" for s in device_spec.state):
        L += [
            '\tif (device_property_read_u32(&pdev->dev, "sie-number",',
            "\t\t\t     &g->sie_num))",
            "\t\tg->sie_num = 0;",
            "\tif (g->sie_num >= C67X00_SIES)",
            "\t\treturn -EINVAL;",
        ]
    if has_clk:
        L += ["\tg->clk = devm_clk_get_optional_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(g->clk))", "\t\treturn PTR_ERR(g->clk);"]
    if clock_model:
        first_group = next(iter(clock_model["groups"]))
        first_table = clock_table_names[first_group]
        L += ["\tclock_ops = device_get_match_data(&pdev->dev);",
              f"\tif (!clock_ops)\n\t\tclock_ops = &{first_table};",
              "\tg->parent_data.index = 0;",
              "\tg->init.name = dev_name(&pdev->dev);",
              "\tg->init.ops = clock_ops;",
              "\tg->init.parent_data = &g->parent_data;",
              "\tg->init.num_parents = 1;",
              "\tg->hw.init = &g->init;",
              "\tret = devm_clk_hw_register(&pdev->dev, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
        L += ["\tret = devm_of_clk_add_hw_provider(&pdev->dev,",
              "\t\t\tof_clk_hw_simple_get, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
    elif has_clk_ops:
        L += [f"\tg->hw.init = &{cid}_clk_init;",
              "\tret = devm_clk_hw_register(&pdev->dev, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
    L += emit_probe_body(
        probe_module, regs, bind,
        safe_function_calls=safe_function_calls)
    if has_gpio and gpio_bank:
        if has_irq:
            L.append("\traw_spin_lock_init(&g->irq_lock);")
        ngpio_properties = gpio_bank.get("ngpio_properties") or []
        ngpio_default = int(gpio_bank.get("ngpio_default") or 32)
        selector = gpio_bank["selector"]

        def bank_addr(field: str) -> str:
            expr = gpio_bank["fields"][field]
            expr = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(selector)}(?![A-Za-z0-9_])",
                "bank->gpio_bank_index", expr)
            return f"g->base + ({expr})"

        config_receipts: dict[str, str] = {}
        config_function = next((summary.get("function")
                                for summary in gpio_summaries
                                if summary.get("bank_model") == gpio_bank), None)
        config_module = next((module for module in formal.get("modules", [])
                              if module.get("name") == config_function), None)
        if config_module:
            config_ops, _, _config_recipes = normalize_module_ops(
                config_module, "bank", safe_function_calls)
            reads = [op for op in walk_leaf_ops(config_ops) if "Read" in op]

            def numeric_shape(text: str) -> tuple[str, ...]:
                return tuple(re.findall(r"0[xX][0-9a-fA-F]+|\d+", text))

            for field in ("set", "dirout"):
                shape = numeric_shape(gpio_bank["fields"][field])
                match = next((op for op in reads
                              if numeric_shape(addr_to_c(
                                  op["Read"]["addr"], "base", {}, "bank"))
                              == shape), None)
                if match:
                    config_receipts[field] = lowering_receipt(match)

        L += ["\tbank_index = 0;",
              "\tdevice_for_each_child_node_scoped(&pdev->dev, child) {",
              "\t\tbank = &g->banks[bank_index];", "\t\tbank->parent = g;",
              "\t\tbank->gpio_bank_index = g->ports_idx[bank_index];"]
        if "set" in config_receipts:
            L.append(f"\t\t{config_receipts['set']}")
        L.append(f"\t\tbank->gpio_sdata = readl({bank_addr('set')});")
        if "dirout" in config_receipts:
            L.append(f"\t\t{config_receipts['dirout']}")
        L += [f"\t\tbank->gpio_sdir = readl({bank_addr('dirout')});",
              f'\t\tbank->gc.label = "{dev}";',
              "\t\tbank->gc.parent = &pdev->dev;",
              "\t\tbank->gc.owner = THIS_MODULE;",
              "\t\tbank->gc.fwnode = child;", "\t\tbank->gc.base = -1;",
              f"\t\tbank->ngpio = {ngpio_default};"]
        if ngpio_properties:
            conditions = [
                f'fwnode_property_read_u32(child, "{name}", &bank->ngpio)'
                for name in ngpio_properties]
            L += [f"\t\tif ({' && '.join(conditions)})",
                  f"\t\t\tbank->ngpio = {ngpio_default};"]
        L += [f"\t\tif (!bank->ngpio || bank->ngpio > {ngpio_default})",
              "\t\t\treturn -EINVAL;", "\t\tbank->gc.ngpio = bank->ngpio;",
              "\t\tbank->gc.can_sleep = false;",
              "\t\tbank->gc.request = gpiochip_generic_request;",
              "\t\tbank->gc.free = gpiochip_generic_free;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\t\tbank->gc.{field} = {fn};")
        irq = gpio_bank.get("irq")
        if has_irq and irq:
            selector_value = int(irq["selector_value"])
            L += [f"\t\tif (bank->gpio_bank_index == {selector_value}) {{",
                  "\t\t\tbank->parent_irqs = devm_kcalloc(&pdev->dev,",
                  "\t\t\t\tbank->gc.ngpio, sizeof(*bank->parent_irqs),",
                  "\t\t\t\tGFP_KERNEL);",
                  "\t\t\tif (!bank->parent_irqs)", "\t\t\t\treturn -ENOMEM;",
                  "\t\t\tfor (irq_index = 0; irq_index < bank->gc.ngpio;",
                  "\t\t\t     irq_index++) {"]
            if irq.get("platform_indexed"):
                L += ["\t\t\t\tif (has_acpi_companion(&pdev->dev))",
                      "\t\t\t\t\tparent_irq = platform_get_irq_optional(",
                      "\t\t\t\t\t\tpdev, irq_index);", "\t\t\t\telse"]
            L += ["\t\t\t\t\tparent_irq = fwnode_irq_get(child, irq_index);",
                  "\t\t\t\tif (parent_irq > 0)",
                  "\t\t\t\t\tbank->parent_irqs[bank->num_parent_irqs++] =",
                  "\t\t\t\t\t\tparent_irq;", "\t\t\t}",
                  "\t\t\tif (bank->num_parent_irqs) {"]
            L += [f'\t\t\t\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_enable",
                          "irq_disable", "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\t\t\t\tg->irqchip.{field} = {fn};")
            L += ["\t\t\t\tgpio_irq_chip_set_chip(&bank->gc.irq,",
                  "\t\t\t\t\t\t       &g->irqchip);",
                  "\t\t\t\tbank->gc.irq.handler = handle_bad_irq;",
                  "\t\t\t\tbank->gc.irq.default_type = IRQ_TYPE_NONE;",
                  "\t\t\t\tbank->gc.irq.num_parents =",
                  "\t\t\t\t\tbank->num_parent_irqs;",
                  "\t\t\t\tbank->gc.irq.parents = bank->parent_irqs;",
                  "\t\t\t\tbank->gc.irq.parent_handler_data =",
                  "\t\t\t\t\t&bank->gc;",
                  f"\t\t\t\tbank->gc.irq.parent_handler = {cid}_banked_irq_handler;",
                  "\t\t\t}", "\t\t}"]
        L += ["\t\tret = devm_gpiochip_add_data(&pdev->dev, &bank->gc, bank);",
              "\t\tif (ret)", "\t\t\treturn ret;", "\t\tbank_index++;",
              "\t}"]
    elif has_gpio:
        L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
              "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
              ("\tg->gc.ngpio = g->ngpio;" if any(
                  s.name == "ngpio" for s in device_spec.state)
               else "\tg->gc.ngpio = 32;"),
              "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\tg->gc.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_enable",
                          "irq_disable", "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\tg->irqchip.{field} = {fn};")
            L += ["\tgpio_irq_chip_set_chip(&g->gc.irq, &g->irqchip);",
                  "\tg->gc.irq.handler = handle_simple_irq;",
                  "\tg->gc.irq.default_type = IRQ_TYPE_NONE;"]
            parent_handler = by_field.get("gpio_irq_chip.parent_handler")
            if parent_handler:
                L.append(f"\tg->gc.irq.parent_handler = {parent_handler};")
            init_hw = by_field.get("gpio_irq_chip.init_hw")
            if init_hw:
                L.append(f"\tg->gc.irq.init_hw = {init_hw};")
        L += ["\tret = devm_gpiochip_add_data(&pdev->dev, &g->gc, g);",
              "\tif (ret)", "\t\treturn ret;"]
    L += [f'\tdev_info(&pdev->dev, "{dev} probed\\n");', "\treturn 0;", "}", "",
          f"static void {cid}_remove(struct platform_device *pdev)", "{",
          "\t(void)pdev;", "}", "",
          f"static const struct of_device_id {cid}_of_match[] = {{"]
    if clock_model and clock_model["variants"]:
        for compatible, group in clock_model["variants"]:
            L.append(f'\t{{ .compatible = "{compatible}", '
                     f'.data = &{clock_table_names[group]} }},')
    else:
        L.append(f'\t{{ .compatible = "reharness,{dev}" }},')
    L += ["\t{ }", "};",
          f"MODULE_DEVICE_TABLE(of, {cid}_of_match);", "",
          f"static struct platform_driver {cid}_driver = {{",
          f"\t.probe = {cid}_probe,", f"\t.remove = {cid}_remove,",
          "\t.driver = {", f'\t\t.name = "{dev}",',
          f"\t\t.of_match_table = {cid}_of_match,"]
    if pm_fields:
        L.append(f"\t\t.pm = &{cid}_pm_ops,")
    L += ["\t},", "};", f"module_platform_driver({cid}_driver);"]
    return "\n".join(L)

def emit_pci(formal, device_spec, bind, facts, priv, regs,
              callbacks: dict[str, str], callback_code: list[str],
              unsupported: list[str], gpio_model: dict | None = None,
              irq_model: dict | None = None, pci_identity=None) -> str:
    dev = device_spec.name
    safe_function_calls = set(portable_function_macros(formal))
    cid = make_cid(dev)
    _, probe_module = probe_ops(device_spec, formal)
    if device_spec.cls == "ahci":
        # Full AHCI probe semantics depend on libata host/port objects and
        # source-specific state that are intentionally outside the current
        # DeviceSpec.  Keep framework/resource glue buildable without emitting
        # expressions containing unbound `host`/`hpriv` source variables.
        probe_module = None
    bar = 5 if device_spec.cls == "ahci" else 0
    misc = dev == "edu"
    ids = pci_ids(device_spec, facts, pci_identity)
    by_field = {field: fn for fn, field in callbacks.items()}
    modules = {module.get("name"): module
               for module in formal.get("modules", [])}

    def callback_receipts(field: str) -> list[str]:
        function = by_field.get(field)
        module = modules.get(function)
        if module is None:
            return []
        return [f"\t{lowering_receipt(op)}"
                for op in walk_leaf_ops(module.get("ops", []))
                if any(kind in op for kind in
                       ("Read", "Write", "ReadModifyWrite"))]
    if irq_model:
        by_field.setdefault("irq_chip.irq_mask", f"{cid}_irq_mask")
        by_field.setdefault("irq_chip.irq_unmask", f"{cid}_irq_unmask")
        by_field.setdefault("irq_chip.irq_eoi", f"{cid}_irq_eoi")
    has_gpio = device_spec.cls == "gpio_controller" or any(
        field.startswith("gpio_chip.") for field in by_field)
    has_irq = any(field.startswith("irq_chip.") for field in by_field)
    direct_handler = by_field.get("irq_handler.handler")

    L = callback_code[:]
    if gpio_model:
        L += emit_source_gpio_callbacks(cid, priv, gpio_model)
    if irq_model:
        L += emit_source_generic_irq_callbacks(cid, priv, irq_model)
    L += emit_usb_callback_tables(dev, callbacks)
    if misc:
        L += [f"static int {cid}_open(struct inode *inode, struct file *file)", "{",
              f"\tstruct {priv} *g = container_of(file->private_data, struct {priv}, misc);",
              "\tfile->private_data = g;", "\treturn 0;", "}", "",
              f"static ssize_t {cid}_read(struct file *file, char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              *callback_receipts("file_operations.read"),
              "\tvalue = readl(g->base + *off);",
              "\tif (copy_to_user(buf, &value, sizeof(value)))", "\t\treturn -EFAULT;",
              "\t*off += sizeof(value);", "\treturn sizeof(value);", "}", "",
              f"static ssize_t {cid}_write(struct file *file, const char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              "\tif (copy_from_user(&value, buf, sizeof(value)))", "\t\treturn -EFAULT;",
              *callback_receipts("file_operations.write"),
              "\twritel(value, g->base + *off);", "\t*off += sizeof(value);",
              "\treturn sizeof(value);", "}", "",
              f"static const struct file_operations {cid}_fops = {{",
              "\t.owner = THIS_MODULE,", f"\t.open = {cid}_open,",
              f"\t.read = {cid}_read,", f"\t.write = {cid}_write,", "};", ""]

    L += [f"static int {cid}_probe(struct pci_dev *pdev, const struct pci_device_id *id)",
          "{", f"\tstruct {priv} *g;", "\tint ret;", "\t(void)id;",
          "\tg = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);",
          "\tif (!g)", "\t\treturn -ENOMEM;", "\tg->dev = &pdev->dev;",
          "\tg->pdev = pdev;", "\tret = pci_enable_device_mem(pdev);",
          "\tif (ret)", "\t\treturn ret;",
          "\tret = pci_request_regions(pdev, KBUILD_MODNAME);",
          "\tif (ret)", "\t\tgoto err_disable;",
          f"\tg->base = pci_ioremap_bar(pdev, {bar});",
          "\tif (!g->base) {", "\t\tret = -ENOMEM;", "\t\tgoto err_regions;", "}",
          "\tpci_set_drvdata(pdev, g);"]
    L += emit_probe_body(
        probe_module, regs, bind,
        safe_function_calls=safe_function_calls)
    gpio_ref = "g->gc"
    if has_gpio:
        if gpio_model:
            ngpio = gpio_model.get("ngpio") or 32
            fields = gpio_model["fields"]
            L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
                  "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
                  f"\tg->gc.ngpio = {ngpio};", "\tg->gc.can_sleep = false;",
                  "\tg->gc.request = " + cid + "_gpio_request;",
                  "\tg->gc.get = " + cid + "_gpio_get;",
                  "\tg->gc.get_multiple = " + cid + "_gpio_get_multiple;",
                  "\tg->gc.set = " + cid + "_gpio_set;",
                  "\tg->gc.set_multiple = " + cid + "_gpio_set_multiple;",
                  "\tg->gc.get_direction = " + cid + "_gpio_get_direction;",
                  "\tg->gc.direction_input = " + cid + "_gpio_direction_input;",
                  "\tg->gc.direction_output = " + cid + "_gpio_direction_output;",
                  "\traw_spin_lock_init(&g->gpio_lock);",
                  f"\tg->gpio_data = readl({fields.get('set', fields['dat'])});",
                  f"\tg->gpio_dir = readl({fields['dirout']});"]
        else:
            L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
                  "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
                  "\tg->gc.ngpio = 32;", "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\t{gpio_ref}.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            if irq_model:
                L += ["\traw_spin_lock_init(&g->irq_lock);",
                      "\tg->irq_mask_cache = 0;"]
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_eoi",
                          "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\tg->irqchip.{field} = {fn};")
            handler = irq_model["handler"] if irq_model else "handle_simple_irq"
            L += [f"\tgpio_irq_chip_set_chip(&{gpio_ref}.irq, &g->irqchip);",
                  f"\t{gpio_ref}.irq.handler = {handler};",
                  f"\t{gpio_ref}.irq.default_type = IRQ_TYPE_NONE;"]
        L += [f"\tret = devm_gpiochip_add_data(&pdev->dev, &{gpio_ref}, g);",
              "\tif (ret)", "\t\tgoto err_iounmap;"]
    if direct_handler:
        L += [f"\tret = devm_request_irq(&pdev->dev, pdev->irq, {direct_handler},",
              f'\t\t\t       IRQF_SHARED, "{dev}", g);',
              "\tif (ret)", "\t\tgoto err_iounmap;"]
    if misc:
        L += ["\tg->misc.minor = MISC_DYNAMIC_MINOR;",
              "\tg->misc.name = KBUILD_MODNAME;", f"\tg->misc.fops = &{cid}_fops;",
              "\tret = misc_register(&g->misc);", "\tif (ret)", "\t\tgoto err_iounmap;"]
    L += [f'\tdev_info(&pdev->dev, "{dev} probed\\n");', "\treturn 0;"]
    if misc or has_gpio or direct_handler:
        L += ["err_iounmap:", "\tiounmap(g->base);"]
    L += ["err_regions:",
          "\tpci_release_regions(pdev);", "err_disable:", "\tpci_disable_device(pdev);",
          "\treturn ret;", "}", "", f"static void {cid}_remove(struct pci_dev *pdev)",
          "{", f"\tstruct {priv} *g = pci_get_drvdata(pdev);"]
    if misc:
        L.append("\tmisc_deregister(&g->misc);")
    L += ["\tiounmap(g->base);", "\tpci_release_regions(pdev);",
          "\tpci_disable_device(pdev);", "}", "",
          f"static const struct pci_device_id {cid}_ids[] = {{"]
    if device_spec.cls == "ahci":
        L.append("\t{ PCI_DEVICE_CLASS(PCI_CLASS_STORAGE_SATA_AHCI, ~0) },")
    elif ids:
        L.append(f"\t{{ PCI_DEVICE(0x{ids[0]:04x}, 0x{ids[1]:04x}) }},")
    else:
        L.append("\t{ PCI_DEVICE(0xffff, 0xffff) },")
    L += ["\t{ }", "};", f"MODULE_DEVICE_TABLE(pci, {cid}_ids);", "",
          f"static struct pci_driver {cid}_driver = {{", f'\t.name = "{dev}",',
          f"\t.id_table = {cid}_ids,", f"\t.probe = {cid}_probe,",
          f"\t.remove = {cid}_remove,", "};", f"module_pci_driver({cid}_driver);"]
    return "\n".join(L)
