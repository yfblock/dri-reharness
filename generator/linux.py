"""Deterministic Linux backend.

The backend emits complete, buildable modules for the two buses exercised by
the artifact: platform MMIO devices (including GPIO controllers) and PCI MMIO
devices (including QEMU edu).  RIS operations remain the source of register
behavior; DeviceSpec/BindSpec/FactsSpec select framework glue and callbacks.

Unsupported callback kinds are reported with `REHARNESS_UNSUPPORTED` comments
and are not silently wired with an incompatible C signature.
"""
from __future__ import annotations

import os
import re
import copy

from extractor.formal import walk_leaf_ops
from .common import ops_to_c, local_decls, value_var_names

_MODELED_STATE_FIELDS = {
    "bypass_orig", "mask_cache", "skip_init", "ngpio",
    "gpio_dir", "gpio_is", "gpio_ibe", "gpio_iev", "gpio_ie",
    "version", "features",
}


def _cid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _callback_map(bind, facts) -> dict[str, str]:
    out = {c.function: c.table_field for c in bind.callbacks}
    if facts is not None:
        for table_field, fn in facts.callbacks.items():
            out[fn] = table_field
    return out


def _last_read_var(module: dict) -> str | None:
    reads = [o["Read"].get("var") for o in walk_leaf_ops(module["ops"])
             if "Read" in o and o["Read"].get("var")]
    return reads[-1] if reads else None


def _normalize_text(text: str) -> tuple[str, bool]:
    """Lower source-private member expressions to the generated device state.

    The replacement is deliberately conservative and is reported as an
    unsupported semantic binding, so the module can be compiled/tested without
    readiness falsely claiming exact reconstruction.
    """
    unsupported = False
    text = re.sub(r"\bd->hwirq\b", "irqd_to_hwirq(d)", text)
    text = re.sub(r"\b[A-Za-z_]\w*->(?:base|reg|regs|ioaddr)\b", "base", text)
    text = re.sub(r"\b[A-Za-z_]\w*_base\b", "base", text)
    for field in _MODELED_STATE_FIELDS:
        text = re.sub(
            rf"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
            rf"(?:->|\.){re.escape(field)}\b",
            f"__state_{field}", text)
    text = re.sub(r"\bnum_gpios\b", "__state_ngpio", text)
    safe_calls = {
        "BIT", "GENMASK", "FIELD_GET", "FIELD_PREP",
        "lower_32_bits", "upper_32_bits", "cpu_to_le32", "le32_to_cpu",
        "cpu_to_le16", "le16_to_cpu",
    }
    call_re = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*\([^()]*\)")
    def replace_call(match):
        nonlocal unsupported
        if match.group(1) in safe_calls:
            return match.group(0)
        unsupported = True
        return "0"
    text = call_re.sub(replace_call, text)
    if re.fullmatch(r"\s*scoped_guard\s*\(.*\)\s*", text):
        text = "1"
    # Statement-like iteration macros are not C expressions.  A partially
    # recovered AST may expose one as a Cond guard; keep the backend buildable
    # with an explicit unsupported marker instead of emitting `if (for (...))`.
    if re.search(r"\bfor_each_[A-Za-z_]\w*\s*\(", text):
        unsupported = True
        text = "0"
    # Remaining source-private fields have no DeviceSpec binding yet.  Use a
    # neutral value and force backend readiness false via the marker.
    member_re = re.compile(
        r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+(?:\[[^]]+\])?")
    if member_re.search(text):
        unsupported = True
        text = member_re.sub("0", text)
    array_re = re.compile(
        r"\b[A-Za-z_]\w*\[[^]]+\](?:(?:->|\.)[A-Za-z_]\w*)*")
    if array_re.search(text):
        unsupported = True
        text = array_re.sub("0", text)
    # A normalized address-of member may become `== &0`; remove only unary
    # address-of, never a legitimate bitwise `value & 0` expression.
    text = re.sub(r"^\s*&\s*0\b", "0", text)
    text = re.sub(r"(?<=[=(,])\s*&\s*0\b", " 0", text)
    return text, unsupported


def _bind_state_text(text: str, state_prefix: str | None) -> str:
    if not state_prefix:
        return text
    return re.sub(r"\b__state_([A-Za-z_]\w*)\b",
                  rf"{state_prefix}->\1", text)


def _normalize_expr(expr, state_prefix: str | None = None):
    if not isinstance(expr, dict):
        return expr, False
    out = copy.deepcopy(expr)
    if "Var" in out:
        out["Var"], changed = _normalize_text(out["Var"])
        out["Var"] = _bind_state_text(out["Var"], state_prefix)
        return out, changed
    changed = False
    if "BinOp" in out:
        out["BinOp"]["left"], a = _normalize_expr(
            out["BinOp"].get("left"), state_prefix)
        out["BinOp"]["right"], b = _normalize_expr(
            out["BinOp"].get("right"), state_prefix)
        changed = a or b
    elif "Ite" in out:
        out["Ite"]["guard"], a = _normalize_expr(
            out["Ite"].get("guard"), state_prefix)
        out["Ite"]["then"], b = _normalize_expr(
            out["Ite"].get("then"), state_prefix)
        out["Ite"]["else"], c = _normalize_expr(
            out["Ite"].get("else"), state_prefix)
        changed = a or b or c
    elif "Bits" in out:
        out["Bits"]["expr"], changed = _normalize_expr(
            out["Bits"].get("expr"), state_prefix)
    return out, changed


def _normalize_ops(ops, state_prefix: str | None = None):
    out = copy.deepcopy(ops)
    changed = False
    for op in out:
        if "Cond" in op:
            op["Cond"]["guard"], c = _normalize_expr(
                op["Cond"].get("guard"), state_prefix)
            op["Cond"]["then_ops"], a = _normalize_ops(
                op["Cond"].get("then_ops", []), state_prefix)
            op["Cond"]["else_ops"], b = _normalize_ops(
                op["Cond"].get("else_ops") or [], state_prefix)
            changed |= a or b or c
        elif "Loop" in op:
            op["Loop"]["count"], c = _normalize_expr(
                op["Loop"].get("count"), state_prefix)
            op["Loop"]["body"], a = _normalize_ops(
                op["Loop"].get("body", []), state_prefix)
            changed |= a or c
        elif "Seq" in op:
            op["Seq"]["ops"], a = _normalize_ops(
                op["Seq"].get("ops", []), state_prefix)
            changed |= a
        else:
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if not body:
                continue
            addr = body.get("addr", {})
            if "Computed" in addr:
                addr["Computed"], a = _normalize_expr(
                    addr["Computed"], state_prefix)
                changed |= a
            if "Read" in op and body.get("var"):
                body["var"], a = _normalize_text(body["var"])
                body["var"] = _bind_state_text(body["var"], state_prefix)
                changed |= a
            key = "value" if "Write" in op else "transform" if "ReadModifyWrite" in op else None
            if key:
                body[key], a = _normalize_expr(body.get(key), state_prefix)
                changed |= a
    return out, changed


def _callback_signature(table_field: str, priv: str):
    gpio_pre = f"\tstruct {priv} *g = gpiochip_get_data(gc);"
    irq_pre = (
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);\n"
        f"\tstruct {priv} *g = gpiochip_get_data(gc);"
    )
    chained_pre = (
        "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);\n"
        f"\tstruct {priv} *g = gpiochip_get_data(gc);"
    )
    direct_irq_pre = f"\tstruct {priv} *g = data;\n\t(void)irq;"
    pm_pre = f"\tstruct {priv} *g = dev_get_drvdata(dev);"
    clk_pre = f"\tstruct {priv} *g = container_of(hw, struct {priv}, hw);"
    specs = {
        "irq_chip.irq_ack": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_mask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_unmask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_set_type": ("int", "struct irq_data *d, unsigned int type", irq_pre),
        "gpio_irq_chip.parent_handler": ("void", "struct irq_desc *desc", chained_pre),
        "gpio_irq_chip.init_hw": ("int", "struct gpio_chip *gc", gpio_pre),
        "irq_handler.handler": (
            "irqreturn_t", "int irq, void *data", direct_irq_pre),
        "gpio_chip.request": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.free": ("void", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.get_direction": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.direction_input": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.direction_output": (
            "int", "struct gpio_chip *gc, unsigned int offset, int value", gpio_pre),
        "gpio_chip.get": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.set": (
            "int", "struct gpio_chip *gc, unsigned int offset, int value", gpio_pre),
        "gpio_chip.set_config": (
            "int", "struct gpio_chip *gc, unsigned int offset, unsigned long config", gpio_pre),
        "dev_pm_ops.suspend": ("int", "struct device *dev", pm_pre),
        "dev_pm_ops.resume": ("int", "struct device *dev", pm_pre),
        "clk_ops.prepare": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.unprepare": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.enable": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.disable": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.is_enabled": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.recalc_rate": (
            "unsigned long", "struct clk_hw *hw, unsigned long parent_rate", clk_pre),
        "clk_ops.determine_rate": (
            "int", "struct clk_hw *hw, struct clk_rate_request *req", clk_pre),
        "clk_ops.round_rate": (
            "long", "struct clk_hw *hw, unsigned long rate, unsigned long *parent_rate",
            clk_pre),
        "clk_ops.set_rate": (
            "int", "struct clk_hw *hw, unsigned long rate, unsigned long parent_rate",
            clk_pre),
    }
    return specs.get(table_field)


def _canonical_args(table_field: str):
    return {
        "irq_chip.irq_ack": [("d", "struct irq_data *")],
        "irq_chip.irq_mask": [("d", "struct irq_data *")],
        "irq_chip.irq_unmask": [("d", "struct irq_data *")],
        "irq_chip.irq_set_type": [("d", "struct irq_data *"), ("type", "unsigned int")],
        "gpio_irq_chip.parent_handler": [("desc", "struct irq_desc *")],
        "gpio_irq_chip.init_hw": [],
        "irq_handler.handler": [
            ("irq", "int"), ("data", "void *")],
        "gpio_chip.request": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.free": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.get_direction": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.direction_input": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.direction_output": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("value", "int")],
        "gpio_chip.get": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.set": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("value", "int")],
        "gpio_chip.set_config": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("config", "unsigned long")],
        "dev_pm_ops.suspend": [("dev", "struct device *")],
        "dev_pm_ops.resume": [("dev", "struct device *")],
        "clk_ops.prepare": [("hw", "struct clk_hw *")],
        "clk_ops.unprepare": [("hw", "struct clk_hw *")],
        "clk_ops.enable": [("hw", "struct clk_hw *")],
        "clk_ops.disable": [("hw", "struct clk_hw *")],
        "clk_ops.is_enabled": [("hw", "struct clk_hw *")],
        "clk_ops.recalc_rate": [
            ("hw", "struct clk_hw *"), ("parent_rate", "unsigned long")],
        "clk_ops.determine_rate": [
            ("hw", "struct clk_hw *"), ("req", "struct clk_rate_request *")],
        "clk_ops.round_rate": [
            ("hw", "struct clk_hw *"), ("rate", "unsigned long"),
            ("parent_rate", "unsigned long *")],
        "clk_ops.set_rate": [
            ("hw", "struct clk_hw *"), ("rate", "unsigned long"),
            ("parent_rate", "unsigned long")],
    }.get(table_field, [])


def _emit_callback(fn, module: dict, table_field: str, priv: str,
                   regs: dict[str, int], bind) -> tuple[str | None, str | None]:
    spec = _callback_signature(table_field, priv)
    if spec is None:
        return None, f"{table_field}={fn.name}"
    safe_ops, normalized = _normalize_ops(module["ops"], "g")
    ret, params, prelude = spec
    declared = {p.name for p in fn.signature.params} | {"base"}
    declared.update({"d", "gc", "offset", "type", "value", "config"})
    lines = [f"static {ret} {fn.name}({params})", "{", prelude]
    for param, (canonical, ctype) in zip(
            fn.signature.params, _canonical_args(table_field)):
        if param.type == "DeviceState":
            continue
        if param.name != canonical:
            lines.append(f"\t{ctype} {param.name} = {canonical};")
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    lines.append("\tvoid __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1, word_type="u32")
    if body:
        lines.append(body.replace("    ", "\t"))
    if ret == "irqreturn_t":
        lines.append("\treturn IRQ_HANDLED;")
    elif ret in {"int", "long", "unsigned long"}:
        result = _last_read_var(module) if table_field in {
            "gpio_chip.get", "gpio_chip.get_direction",
            "clk_ops.is_enabled", "clk_ops.recalc_rate"} else None
        lines.append(f"\treturn {result or 0};")
    lines.extend(["}", ""])
    problem = f"{fn.name} source-private expressions normalized" if normalized else None
    if table_field in {
            "clk_ops.recalc_rate", "clk_ops.determine_rate", "clk_ops.round_rate"}:
        problem = f"{fn.name} requires non-MMIO clock arithmetic"
    return "\n".join(lines), problem


def _probe_ops(device_spec, formal: dict):
    probe = next((f for f in device_spec.functions if f.role == "probe"), None)
    if probe is None:
        return None, None
    module = next((m for m in formal["modules"] if m["name"] == probe.ris_ref), None)
    return probe, module


def _emit_probe_body(module, regs, bind, indent="\t") -> list[str]:
    if module is None:
        return []
    safe_ops, _ = _normalize_ops(module["ops"], "g")
    declared: set[str] = {"base", "ret", "g", "pdev"}
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    out = []
    if decls:
        out.extend(decls.replace("    ", indent).splitlines())
    out.append(f"{indent}void __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1, word_type="u32")
    if body:
        out.extend(body.replace("    ", indent).splitlines())
    return out


def _pci_ids(device_spec, facts) -> tuple[int, int] | None:
    if device_spec.name == "edu":
        return 0x1234, 0x11E8
    source = getattr(facts, "source", None) if facts is not None else None
    if source and os.path.isfile(source):
        text = open(source, "r", encoding="utf-8", errors="replace").read()
        m = re.search(r"PCI_DEVICE\s*\(\s*(0x[0-9a-fA-F]+|\d+)\s*,\s*"
                      r"(0x[0-9a-fA-F]+|\d+)\s*\)", text)
        if m:
            return int(m.group(1), 0), int(m.group(2), 0)
    return None


def _emit_platform(formal, device_spec, bind, facts, priv, regs,
                   callbacks: dict[str, str], callback_code: list[str],
                   unsupported: list[str]) -> str:
    dev = device_spec.name
    cid = _cid(dev)
    _, probe_module = _probe_ops(device_spec, formal)
    if device_spec.cls in {"ahci", "sdhci", "virtio_mmio"}:
        probe_module = None
    by_field = {field: fn for fn, field in callbacks.items()}
    has_gpio = device_spec.cls == "gpio_controller" or any(
        f.startswith("gpio_chip.") for f in by_field)
    has_irq = any(f.startswith("irq_chip.") for f in by_field)
    has_clk = any(s.name == "clk" for s in device_spec.state)
    has_clk_ops = any(f.startswith("clk_ops.") for f in by_field)
    pm_fields = {
        field.split(".", 1)[1]: fn for field, fn in by_field.items()
        if field.startswith("dev_pm_ops.")
    }

    L = callback_code[:]
    if has_clk_ops:
        L += [f"static const struct clk_ops {cid}_clk_ops = {{"]
        for field in ("prepare", "unprepare", "enable", "disable",
                      "is_enabled", "recalc_rate", "determine_rate",
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
    L += ["\tg = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);",
          "\tif (!g)", "\t\treturn -ENOMEM;",
          "\tg->dev = &pdev->dev;",
          "\tg->base = devm_platform_ioremap_resource(pdev, 0);",
          "\tif (IS_ERR(g->base))", "\t\treturn PTR_ERR(g->base);",
          "\tplatform_set_drvdata(pdev, g);"]
    if any(s.name == "ngpio" for s in device_spec.state):
        L.append("\tg->ngpio = 32;")
    if any(s.name == "skip_init" for s in device_spec.state):
        L.append('\tg->skip_init = device_property_read_bool(&pdev->dev, "reharness,skip-init");')
    if has_clk:
        L += ["\tg->clk = devm_clk_get_optional_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(g->clk))", "\t\treturn PTR_ERR(g->clk);"]
    if has_clk_ops:
        L += [f"\tg->hw.init = &{cid}_clk_init;",
              "\tret = devm_clk_hw_register(&pdev->dev, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
    L += _emit_probe_body(probe_module, regs, bind)
    if has_gpio:
        L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
              "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
              ("\tg->gc.ngpio = g->ngpio;" if any(
                  s.name == "ngpio" for s in device_spec.state)
               else "\tg->gc.ngpio = 32;"),
              "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "set", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\tg->gc.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_set_type"):
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
          f"static const struct of_device_id {cid}_of_match[] = {{",
          f'\t{{ .compatible = "reharness,{dev}" }},', "\t{ }", "};",
          f"MODULE_DEVICE_TABLE(of, {cid}_of_match);", "",
          f"static struct platform_driver {cid}_driver = {{",
          f"\t.probe = {cid}_probe,", f"\t.remove = {cid}_remove,",
          "\t.driver = {", f'\t\t.name = "{dev}",',
          f"\t\t.of_match_table = {cid}_of_match,"]
    if pm_fields:
        L.append(f"\t\t.pm = &{cid}_pm_ops,")
    L += ["\t},", "};", f"module_platform_driver({cid}_driver);"]
    return "\n".join(L)


def _emit_pci(formal, device_spec, bind, facts, priv, regs,
              callbacks: dict[str, str], callback_code: list[str],
              unsupported: list[str]) -> str:
    dev = device_spec.name
    cid = _cid(dev)
    _, probe_module = _probe_ops(device_spec, formal)
    if device_spec.cls == "ahci":
        # Full AHCI probe semantics depend on libata host/port objects and
        # source-specific state that are intentionally outside the current
        # DeviceSpec.  Keep framework/resource glue buildable without emitting
        # expressions containing unbound `host`/`hpriv` source variables.
        probe_module = None
    bar = 5 if device_spec.cls == "ahci" else 0
    misc = dev == "edu"
    ids = _pci_ids(device_spec, facts)
    by_field = {field: fn for fn, field in callbacks.items()}
    has_gpio = device_spec.cls == "gpio_controller" or any(
        field.startswith("gpio_chip.") for field in by_field)
    has_irq = any(field.startswith("irq_chip.") for field in by_field)
    direct_handler = by_field.get("irq_handler.handler")

    L = callback_code[:]
    if misc:
        L += [f"static int {cid}_open(struct inode *inode, struct file *file)", "{",
              f"\tstruct {priv} *g = container_of(file->private_data, struct {priv}, misc);",
              "\tfile->private_data = g;", "\treturn 0;", "}", "",
              f"static ssize_t {cid}_read(struct file *file, char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              "\tvalue = readl(g->base + *off);",
              "\tif (copy_to_user(buf, &value, sizeof(value)))", "\t\treturn -EFAULT;",
              "\t*off += sizeof(value);", "\treturn sizeof(value);", "}", "",
              f"static ssize_t {cid}_write(struct file *file, const char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              "\tif (copy_from_user(&value, buf, sizeof(value)))", "\t\treturn -EFAULT;",
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
    L += _emit_probe_body(probe_module, regs, bind)
    if has_gpio:
        L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
              "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
              "\tg->gc.ngpio = 32;", "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "set", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\tg->gc.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\tg->irqchip.{field} = {fn};")
            L += ["\tgpio_irq_chip_set_chip(&g->gc.irq, &g->irqchip);",
                  "\tg->gc.irq.handler = handle_simple_irq;",
                  "\tg->gc.irq.default_type = IRQ_TYPE_NONE;"]
        L += ["\tret = devm_gpiochip_add_data(&pdev->dev, &g->gc, g);",
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


def generate(formal: dict, device_spec, bind, facts=None) -> str:
    dev = device_spec.name
    priv = f"{_cid(dev)}_priv"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    callbacks = _callback_map(bind, facts)
    modules = {m["name"]: m for m in formal["modules"]}
    callbacks_for_codegen = {
        fn: field for fn, field in callbacks.items()
        if fn in modules or field.endswith((".probe", ".remove"))
    }

    callback_code: list[str] = []
    unsupported: list[str] = []
    if device_spec.cls == "ahci":
        unsupported.append("AHCI probe requires libata host/port state bindings")
    if device_spec.cls == "sdhci":
        unsupported.append("SDHCI probe requires mmc/host state bindings")
    if device_spec.cls == "virtio_mmio":
        unsupported.append("virtio-mmio probe requires virtio core state bindings")
    if any(_normalize_ops(m.get("ops", []))[1] for m in formal.get("modules", [])):
        unsupported.append("source-private expressions require explicit state bindings")

    # Once a driver is already explicitly non-ready, keep large real-driver
    # outputs compilable even when source-local macro helpers are not exported
    # through FactsSpec. Object constants recovered from headers remain exact;
    # only the residual names below receive guarded neutral fallbacks.
    fallback_refs: set[str] = set()
    fallback_calls: set[str] = set()
    if unsupported:
        for module in formal.get("modules", []):
            safe_ops, _ = _normalize_ops(module.get("ops", []))
            fallback_refs |= {name for name in value_var_names(safe_ops)
                              if re.fullmatch(r"[A-Z][A-Z0-9_]*", name)}
            fallback_refs |= set(re.findall(
                r"\b[A-Z][A-Z0-9_]{2,}\b", repr(safe_ops)))
            fallback_calls |= set(re.findall(
                r"\b([A-Z][A-Z0-9_]{2,})\s*\(", repr(safe_ops)))
    for fn in device_spec.functions:
        field = callbacks.get(fn.name)
        if not field or field.endswith(".probe") or field.endswith(".remove"):
            continue
        if dev == "edu" and field.startswith("file_operations."):
            # The edu PCI backend supplies checked raw-MMIO file operations
            # with the correct miscdevice private-data lifecycle below.
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        code, problem = _emit_callback(fn, module, field, priv, regs, bind)
        if code:
            callback_code.append(code)
        if problem:
            unsupported.append(problem)

    callbacks = callbacks_for_codegen
    is_pci = any(field.startswith("pci_driver.") for field in callbacks.values())
    includes = [
        "#include <linux/module.h>", "#include <linux/device.h>",
        "#include <linux/io.h>", "#include <linux/slab.h>",
        "#include <linux/err.h>", "#include <linux/interrupt.h>",
        "#include <linux/bits.h>",
    ]
    if is_pci:
        includes += ["#include <linux/pci.h>", "#include <linux/miscdevice.h>",
                     "#include <linux/fs.h>", "#include <linux/uaccess.h>"]
    else:
        includes += ["#include <linux/platform_device.h>",
                     "#include <linux/of_device.h>",
                     "#include <linux/gpio/driver.h>", "#include <linux/clk.h>"]
    if any(field.startswith(("irq_chip.", "gpio_chip.", "gpio_irq_chip."))
           for field in callbacks.values()):
        includes += ["#include <linux/gpio/driver.h>", "#include <linux/irq.h>"]
    if any(field.startswith("clk_ops.") for field in callbacks.values()):
        includes += ["#include <linux/clk-provider.h>"]

    L = [f"// Auto-generated deterministic Linux driver for {dev} (reharness)",
         "// SPDX-License-Identifier: GPL-2.0", *includes, ""]
    for name, off in regs.items():
        L.append(f"#define {name}\t0x{off:x}")
    if facts is not None:
        for name, value in sorted(facts.constants.items()):
            if name not in regs:
                L.append(f"#ifndef {name}\n#define {name}\t0x{value:x}\n#endif")
    known_constants = set(regs)
    if facts is not None:
        known_constants |= set(facts.constants)
    if unsupported:
        for name in sorted(fallback_calls - known_constants):
            L.append(f"#ifndef {name}\n#define {name}(...) 0\n#endif")
        for name in sorted(fallback_refs - fallback_calls - known_constants
                           - {"MMIO", "TODO"}):
            L.append(f"#ifndef {name}\n#define {name} 0\n#endif")
    L += ["", f"struct {priv} {{", "\tstruct device *dev;",
          "\tvoid __iomem *base;"]
    if is_pci:
        L.append("\tstruct pci_dev *pdev;")
        if dev == "edu":
            L.append("\tstruct miscdevice misc;")
        if any(field.startswith(("gpio_chip.", "irq_chip.", "gpio_irq_chip.",
                                 "irq_handler."))
               for field in callbacks.values()):
            L += ["\tstruct gpio_chip gc;", "\tstruct irq_chip irqchip;"]
    else:
        L += ["\tstruct gpio_chip gc;", "\tstruct irq_chip irqchip;",
              "\tstruct clk *clk;"]
        if any(field.startswith("clk_ops.") for field in callbacks.values()):
            L.append("\tstruct clk_hw hw;")
    for state in device_spec.state:
        if state.name in {"base", "clk", "num_irqs"}:
            continue
        ctype = "u64" if state.type == "UInt64" else "u32"
        L.append(f"\t{ctype} {state.name};")
    L += ["};", ""]

    if unsupported:
        for item in unsupported:
            L.append(f"/* REHARNESS_UNSUPPORTED callback: {item} */")
        L.append("")

    if is_pci:
        body = _emit_pci(formal, device_spec, bind, facts, priv, regs,
                         callbacks, callback_code, unsupported)
    else:
        body = _emit_platform(formal, device_spec, bind, facts, priv, regs,
                              callbacks, callback_code, unsupported)
    L += [body, "", 'MODULE_LICENSE("GPL");',
          f'MODULE_DESCRIPTION("reharness generated driver for {dev}");']
    return "\n".join(L) + "\n"
