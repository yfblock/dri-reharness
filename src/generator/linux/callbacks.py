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


from .normalize import normalize_ops, normalize_expr, normalize_text, bind_state_text
from .source_parse import (make_cid as cid, callback_map, source_object_macros,
    lower_irq_source_callback, portable_function_macros)
from .source_models import (source_gpio_model, source_generic_irq_model,
    banked_irq_status_model)

def bank_priv(priv: str) -> str:
    return f"{priv}_bank"

def banked_gpio_callback(table_field: str) -> bool:
    return table_field.startswith(("gpio_chip.", "irq_chip.",
                                   "gpio_irq_chip."))

def callback_signature(table_field: str, priv: str, banked_gpio: bool = False):
    bank = bank_priv(priv)
    if banked_gpio and banked_gpio_callback(table_field):
        gpio_pre = (f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
                    f"\tstruct {priv} *g = bank->parent;")
        irq_pre = (
            "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);\n"
            f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
            f"\tstruct {priv} *g = bank->parent;"
        )
        chained_pre = (
            "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);\n"
            f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
            f"\tstruct {priv} *g = bank->parent;"
        )
    else:
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
    ep_pre = f"\tstruct {priv} *g = ep->driver_data;"
    gadget_pre = f"\tstruct {priv} *g = container_of(gadget, struct {priv}, gadget);"
    hcd_pre = f"\tstruct {priv} *g = dev_get_drvdata(hcd->self.controller);"
    sdhci_pre = (
        "\tstruct sdhci_pltfm_host *pltfm_host = sdhci_priv(host);\n"
        f"\tstruct {priv} *g = sdhci_pltfm_priv(pltfm_host);")
    specs = {
        "irq_chip.irq_ack": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_mask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_unmask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_enable": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_disable": ("void", "struct irq_data *d", irq_pre),
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
        "gpio_chip.get_multiple": (
            "int", "struct gpio_chip *gc, unsigned long *mask, unsigned long *bits",
            gpio_pre),
        "gpio_chip.set": (
            "int", "struct gpio_chip *gc, unsigned int offset, int value", gpio_pre),
        "gpio_chip.set_multiple": (
            "int", "struct gpio_chip *gc, unsigned long *mask, unsigned long *bits",
            gpio_pre),
        "gpio_chip.set_config": (
            "int", "struct gpio_chip *gc, unsigned int offset, unsigned long config", gpio_pre),
        "dev_pm_ops.suspend": ("int", "struct device *dev", pm_pre),
        "dev_pm_ops.resume": ("int", "struct device *dev", pm_pre),
        "clk_ops.prepare": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.unprepare": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.enable": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.disable": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.is_prepared": ("int", "struct clk_hw *hw", clk_pre),
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
        "sdhci_ops.read_l": (
            "u32", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.read_w": (
            "u16", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.read_b": (
            "u8", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.write_l": (
            "void", "struct sdhci_host *host, u32 val, int reg", sdhci_pre),
        "sdhci_ops.write_w": (
            "void", "struct sdhci_host *host, u16 val, int reg", sdhci_pre),
        "sdhci_ops.write_b": (
            "void", "struct sdhci_host *host, u8 val, int reg", sdhci_pre),
        "sdhci_ops.voltage_switch": (
            "void", "struct sdhci_host *host", sdhci_pre),
        "sdhci_ops.set_clock": (
            "void", "struct sdhci_host *host, unsigned int clock", sdhci_pre),
        "sdhci_ops.set_bus_width": (
            "void", "struct sdhci_host *host, int width", sdhci_pre),
        "sdhci_ops.set_uhs_signaling": (
            "void", "struct sdhci_host *host, unsigned int timing", sdhci_pre),
        "sdhci_ops.set_power": (
            "void", "struct sdhci_host *host, unsigned char mode, unsigned short vdd",
            sdhci_pre),
        "sdhci_ops.hw_reset": (
            "void", "struct sdhci_host *host", sdhci_pre),
        "usb_ep_ops.enable": (
            "int", "struct usb_ep *ep, const struct usb_endpoint_descriptor *desc",
            ep_pre),
        "usb_ep_ops.disable": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.alloc_request": (
            "struct usb_request *", "struct usb_ep *ep, gfp_t gfp_flags", ep_pre),
        "usb_ep_ops.free_request": (
            "void", "struct usb_ep *ep, struct usb_request *req", ep_pre),
        "usb_ep_ops.queue": (
            "int", "struct usb_ep *ep, struct usb_request *req, gfp_t gfp_flags",
            ep_pre),
        "usb_ep_ops.dequeue": (
            "int", "struct usb_ep *ep, struct usb_request *req", ep_pre),
        "usb_ep_ops.set_halt": (
            "int", "struct usb_ep *ep, int value", ep_pre),
        "usb_ep_ops.set_wedge": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.fifo_status": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.fifo_flush": ("void", "struct usb_ep *ep", ep_pre),
        "usb_gadget_ops.get_frame": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.wakeup": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.set_selfpowered": (
            "int", "struct usb_gadget *gadget, int is_selfpowered", gadget_pre),
        "usb_gadget_ops.vbus_session": (
            "int", "struct usb_gadget *gadget, int is_active", gadget_pre),
        "usb_gadget_ops.vbus_draw": (
            "int", "struct usb_gadget *gadget, unsigned int mA", gadget_pre),
        "usb_gadget_ops.pullup": (
            "int", "struct usb_gadget *gadget, int is_on", gadget_pre),
        "usb_gadget_ops.udc_start": (
            "int", "struct usb_gadget *gadget, struct usb_gadget_driver *driver",
            gadget_pre),
        "usb_gadget_ops.udc_stop": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.udc_set_speed": (
            "void", "struct usb_gadget *gadget, enum usb_device_speed speed",
            gadget_pre),
        "usb_gadget_ops.match_ep": (
            "struct usb_ep *",
            "struct usb_gadget *gadget, struct usb_endpoint_descriptor *desc, "
            "struct usb_ss_ep_comp_descriptor *comp_desc", gadget_pre),
        "hc_driver.irq": ("irqreturn_t", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.start": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.stop": ("void", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.urb_enqueue": (
            "int", "struct usb_hcd *hcd, struct urb *urb, gfp_t mem_flags", hcd_pre),
        "hc_driver.urb_dequeue": (
            "int", "struct usb_hcd *hcd, struct urb *urb, int status", hcd_pre),
        "hc_driver.endpoint_disable": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.endpoint_reset": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.get_frame_number": (
            "int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.hub_status_data": (
            "int", "struct usb_hcd *hcd, char *buf", hcd_pre),
        "hc_driver.hub_control": (
            "int", "struct usb_hcd *hcd, u16 typeReq, u16 wValue, u16 wIndex, "
            "char *buf, u16 wLength", hcd_pre),
        "hc_driver.clear_tt_buffer_complete": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.bus_suspend": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.bus_resume": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.map_urb_for_dma": (
            "int", "struct usb_hcd *hcd, struct urb *urb, gfp_t mem_flags", hcd_pre),
        "hc_driver.unmap_urb_for_dma": (
            "void", "struct usb_hcd *hcd, struct urb *urb", hcd_pre),
        "hc_driver.free_dev": (
            "void", "struct usb_hcd *hcd, struct usb_device *udev", hcd_pre),
        "hc_driver.reset_device": (
            "int", "struct usb_hcd *hcd, struct usb_device *udev", hcd_pre),
    }
    return specs.get(table_field)

def canonical_args(table_field: str):
    return {
        "irq_chip.irq_ack": [("d", "struct irq_data *")],
        "irq_chip.irq_mask": [("d", "struct irq_data *")],
        "irq_chip.irq_unmask": [("d", "struct irq_data *")],
        "irq_chip.irq_enable": [("d", "struct irq_data *")],
        "irq_chip.irq_disable": [("d", "struct irq_data *")],
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
        "gpio_chip.get_multiple": [
            ("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
            ("bits", "unsigned long *")],
        "gpio_chip.set": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("value", "int")],
        "gpio_chip.set_multiple": [
            ("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
            ("bits", "unsigned long *")],
        "gpio_chip.set_config": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("config", "unsigned long")],
        "dev_pm_ops.suspend": [("dev", "struct device *")],
        "dev_pm_ops.resume": [("dev", "struct device *")],
        "clk_ops.prepare": [("hw", "struct clk_hw *")],
        "clk_ops.unprepare": [("hw", "struct clk_hw *")],
        "clk_ops.enable": [("hw", "struct clk_hw *")],
        "clk_ops.disable": [("hw", "struct clk_hw *")],
        "clk_ops.is_prepared": [("hw", "struct clk_hw *")],
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
        "sdhci_ops.read_l": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.read_w": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.read_b": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.write_l": [
            ("host", "struct sdhci_host *"), ("val", "u32"),
            ("reg", "int")],
        "sdhci_ops.write_w": [
            ("host", "struct sdhci_host *"), ("val", "u16"),
            ("reg", "int")],
        "sdhci_ops.write_b": [
            ("host", "struct sdhci_host *"), ("val", "u8"),
            ("reg", "int")],
        "sdhci_ops.voltage_switch": [("host", "struct sdhci_host *")],
        "sdhci_ops.set_clock": [
            ("host", "struct sdhci_host *"), ("clock", "unsigned int")],
        "sdhci_ops.set_bus_width": [
            ("host", "struct sdhci_host *"), ("width", "int")],
        "sdhci_ops.set_uhs_signaling": [
            ("host", "struct sdhci_host *"), ("timing", "unsigned int")],
        "sdhci_ops.set_power": [
            ("host", "struct sdhci_host *"), ("mode", "unsigned char"),
            ("vdd", "unsigned short")],
        "sdhci_ops.hw_reset": [("host", "struct sdhci_host *")],
        "usb_ep_ops.enable": [
            ("ep", "struct usb_ep *"),
            ("desc", "const struct usb_endpoint_descriptor *")],
        "usb_ep_ops.disable": [("ep", "struct usb_ep *")],
        "usb_ep_ops.alloc_request": [
            ("ep", "struct usb_ep *"), ("gfp_flags", "gfp_t")],
        "usb_ep_ops.free_request": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *")],
        "usb_ep_ops.queue": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *"),
            ("gfp_flags", "gfp_t")],
        "usb_ep_ops.dequeue": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *")],
        "usb_ep_ops.set_halt": [
            ("ep", "struct usb_ep *"), ("value", "int")],
        "usb_ep_ops.set_wedge": [("ep", "struct usb_ep *")],
        "usb_ep_ops.fifo_status": [("ep", "struct usb_ep *")],
        "usb_ep_ops.fifo_flush": [("ep", "struct usb_ep *")],
        "usb_gadget_ops.get_frame": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.wakeup": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.set_selfpowered": [
            ("gadget", "struct usb_gadget *"), ("is_selfpowered", "int")],
        "usb_gadget_ops.vbus_session": [
            ("gadget", "struct usb_gadget *"), ("is_active", "int")],
        "usb_gadget_ops.vbus_draw": [
            ("gadget", "struct usb_gadget *"), ("mA", "unsigned int")],
        "usb_gadget_ops.pullup": [
            ("gadget", "struct usb_gadget *"), ("is_on", "int")],
        "usb_gadget_ops.udc_start": [
            ("gadget", "struct usb_gadget *"),
            ("driver", "struct usb_gadget_driver *")],
        "usb_gadget_ops.udc_stop": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.udc_set_speed": [
            ("gadget", "struct usb_gadget *"),
            ("speed", "enum usb_device_speed")],
        "usb_gadget_ops.match_ep": [
            ("gadget", "struct usb_gadget *"),
            ("desc", "struct usb_endpoint_descriptor *"),
            ("comp_desc", "struct usb_ss_ep_comp_descriptor *")],
        "hc_driver.irq": [("hcd", "struct usb_hcd *")],
        "hc_driver.start": [("hcd", "struct usb_hcd *")],
        "hc_driver.stop": [("hcd", "struct usb_hcd *")],
        "hc_driver.urb_enqueue": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("mem_flags", "gfp_t")],
        "hc_driver.urb_dequeue": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("status", "int")],
        "hc_driver.endpoint_disable": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.endpoint_reset": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.get_frame_number": [("hcd", "struct usb_hcd *")],
        "hc_driver.hub_status_data": [
            ("hcd", "struct usb_hcd *"), ("buf", "char *")],
        "hc_driver.hub_control": [
            ("hcd", "struct usb_hcd *"), ("typeReq", "u16"),
            ("wValue", "u16"), ("wIndex", "u16"), ("buf", "char *"),
            ("wLength", "u16")],
        "hc_driver.clear_tt_buffer_complete": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.bus_suspend": [("hcd", "struct usb_hcd *")],
        "hc_driver.bus_resume": [("hcd", "struct usb_hcd *")],
        "hc_driver.map_urb_for_dma": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("mem_flags", "gfp_t")],
        "hc_driver.unmap_urb_for_dma": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *")],
        "hc_driver.free_dev": [
            ("hcd", "struct usb_hcd *"), ("udev", "struct usb_device *")],
        "hc_driver.reset_device": [
            ("hcd", "struct usb_hcd *"), ("udev", "struct usb_device *")],
    }.get(table_field, [])

def emit_callback(fn, module: dict, table_field: str, priv: str,
                   regs: dict[str, int], bind,
                   safe_function_calls: set[str] | None = None,
                   banked_gpio: bool = False,
                   backend_ops: list | None = None,
                   ) -> tuple[str | None, str | None]:
    spec = callback_signature(table_field, priv, banked_gpio)
    if spec is None:
        return None, f"{table_field}={fn.name}"
    state_owner = ("bank" if banked_gpio
                   and table_field.startswith("gpio_chip.") else "g")
    safe_ops, normalized, contract_recipes = normalize_module_ops(
        module, state_owner, safe_function_calls, backend_ops=backend_ops)
    if table_field == "gpio_chip.set_multiple":
        for op in walk_leaf_ops(safe_ops):
            body = op.get("ReadModifyWrite") or op.get("Write")
            if not body:
                continue
            key = "transform" if "ReadModifyWrite" in op else "value"
            body[key] = replace_expr_var(body.get(key), "mask", "*mask")
            body[key] = replace_expr_var(body.get(key), "bits", "*bits")
    ret, params, prelude = spec
    declared = {"base"}
    canonical_args = canonical_args(table_field)
    declared.update(name for name, _ctype in canonical_args)
    declared.update({"d", "gc", "offset", "type", "config"})
    lines = [f"static {ret} {fn.name}({params})", "{", prelude]
    for param, (canonical, ctype) in zip(
            fn.signature.params, canonical_args):
        if param.name != canonical:
            lines.append(f"\t{ctype} {param.name} = {canonical};")
            declared.add(param.name)
    source_params = {param.name for param in fn.signature.params}
    if (table_field == "hc_driver.irq" and "int_status" in source_params
            and "int_status" not in declared):
        lines.append(
            "\tu32 int_status = readw(g->base + HPI_STATUS * g->hpi_regstep);")
        declared.add("int_status")
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    lines.append("\tvoid __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1,
                    word_type="u32", state_expr=state_owner,
                    _lowering_recipes=contract_recipes)
    if body:
        lines.append(body.replace("    ", "\t"))
    has_return = any("Return" in op for op in walk_leaf_ops(safe_ops))
    has_output = any("OutputWrite" in op for op in walk_leaf_ops(safe_ops))
    if table_field == "gpio_chip.get_multiple" and not has_output:
        result = last_read_var(module) or "0"
        lines.append(f"\t*bits = (*bits & ~*mask) | ({result} & *mask);")
        lines.append("\treturn 0;")
    elif has_return:
        pass
    elif ret == "irqreturn_t":
        lines.append("\treturn IRQ_HANDLED;")
    elif "*" in ret:
        lines.append("\treturn NULL;")
    elif ret in {"int", "long", "unsigned long"}:
        result = last_read_var(module) if table_field in {
            "gpio_chip.get", "gpio_chip.get_direction",
            "clk_ops.is_prepared", "clk_ops.is_enabled", "clk_ops.recalc_rate",
            "usb_ep_ops.fifo_status", "usb_gadget_ops.get_frame",
            "hc_driver.get_frame_number", "hc_driver.hub_status_data"} else None
        lines.append(f"\treturn {result or 0};")
    lines.extend(["}", ""])
    problem = f"{fn.name} source-private expressions normalized" if normalized else None
    if table_field in {
            "clk_ops.recalc_rate", "clk_ops.determine_rate", "clk_ops.round_rate"}:
        problem = f"{fn.name} requires non-MMIO clock arithmetic"
    return "\n".join(lines), problem

def emit_evidence_only_callback(fn, module: dict, priv: str,
                                 regs: dict[str, int], bind,
                                 safe_function_calls: set[str]) -> str:
    """Emit an unregistered function for an AST-bound unknown-role callback.

    This preserves the recovered operations for audit and cross-TU helpers,
    while deliberately avoiding any public callback table or lifecycle claim.
    """
    type_map = {
        "UInt": "u32", "LogicalIRQ": "unsigned int",
        "Bool": "bool", "Clock": "unsigned long",
        "MmioBase": "void __iomem *", "UIntPtr": "unsigned long *",
    }
    params = []
    aliases = []
    declared = {"base"}
    device_bound = False
    for param in fn.signature.params:
        if param.type == "DeviceState" and not device_bound:
            params.append(f"struct {priv} *g")
            declared.add("g")
            device_bound = True
            if param.name and param.name != "g":
                aliases.append(f"\tstruct {priv} *{param.name} = g;")
                declared.add(param.name)
            continue
        ctype = (f"struct {priv} *" if param.type == "DeviceState"
                 else type_map.get(param.type, "u32"))
        params.append(f"{ctype} {param.name}")
        declared.add(param.name)
    if not device_bound:
        params.insert(0, f"struct {priv} *g")
        declared.add("g")
    return_type = "void" if fn.signature.return_type == "Void" else "u32"
    safe_ops, _normalized, contract_recipes = normalize_module_ops(
        module, "g", safe_function_calls)
    lines = [
        f"/* AST-bound evidence only: role unknown, not registered */",
        f"static {return_type} {fn.name}({', '.join(params)})", "{",
        *aliases,
    ]
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    lines.append("\tvoid __iomem *base = g->base;")
    body = ops_to_c(
        safe_ops, bind, "base", regs, indent=1,
        word_type="u32", state_expr="g",
        _lowering_recipes=contract_recipes)
    if body:
        lines.append(body.replace("    ", "\t"))
    if (return_type != "void"
            and not any("Return" in op for op in walk_leaf_ops(safe_ops))):
        lines.append(f"\treturn {last_read_var(module) or 0};")
    lines.extend(["}", ""])
    return "\n".join(lines)

def emit_banked_irq_source_callback(
        fn, module: dict, table_field: str, priv: str, regs: dict[str, int],
        source: str, safe_function_calls: set[str]) -> str | None:
    """Lower standard irq_chip bit operations after checking their source."""
    if table_field not in {
            "irq_chip.irq_ack", "irq_chip.irq_mask", "irq_chip.irq_unmask",
            "irq_chip.irq_enable", "irq_chip.irq_disable",
            "irq_chip.irq_set_type"}:
        return None
    function = source_function(source, fn.name)
    if function is None:
        return None
    body = function["body"]
    safe_ops, _, _contract_recipes = normalize_module_ops(
        module, "g", safe_function_calls)
    leaves = list(walk_leaf_ops(safe_ops))

    def addresses(kind: str) -> list[str]:
        result = []
        for op in leaves:
            item = op.get(kind)
            if item:
                result.append(addr_to_c(item["addr"], "base", regs, "g"))
        return result

    reads = addresses("Read")
    writes = addresses("Write") + addresses("ReadModifyWrite")
    bank = bank_priv(priv)
    prelude = [
        f"static {'int' if table_field.endswith('set_type') else 'void'} "
        f"{fn.name}(struct irq_data *d"
        f"{', unsigned int type' if table_field.endswith('set_type') else ''})",
        "{", "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {bank} *bank = gpiochip_get_data(gc);",
        f"\tstruct {priv} *g = bank->parent;", "\tvoid __iomem *base = g->base;",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\tu32 val;",
    ]
    field = table_field.rsplit(".", 1)[1]
    if field == "irq_ack":
        if (len(writes) != 1
                or not re.search(r"BIT\s*\(\s*irqd_to_hwirq\s*\(", body)):
            return None
        lines = prelude + ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\twritel(bit, {writes[0]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
    elif field in {"irq_mask", "irq_unmask"}:
        operator = "|" if field == "irq_mask" else "& ~"
        helper = "gpiochip_disable_irq" if field == "irq_mask" else "gpiochip_enable_irq"
        proof = r"\|\s*BIT\s*\(" if field == "irq_mask" else r"&\s*~\s*BIT\s*\("
        if len(reads) != 1 or len(writes) != 1 or not re.search(proof, body):
            return None
        lines = prelude
        if field == "irq_unmask":
            lines.append("\tgpiochip_enable_irq(gc, irqd_to_hwirq(d));")
        lines += ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                  f"\tval = readl({reads[0]});",
                  f"\tval = val {operator}bit;", f"\twritel(val, {writes[0]});",
                  "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
        if field == "irq_mask":
            lines.append("\tgpiochip_disable_irq(gc, irqd_to_hwirq(d));")
    elif field in {"irq_enable", "irq_disable"}:
        if len(reads) != 2 or len(writes) != 2:
            return None
        first = "|" if field == "irq_enable" else "|"
        second = "& ~" if field == "irq_enable" else "& ~"
        # Source ordering distinguishes enable (INTEN set, INTMASK clear)
        # from disable (INTMASK set, INTEN clear); both use the same two
        # bit transforms in their observed order.
        if field == "irq_disable":
            first, second = "|", "& ~"
        if not (re.search(r"\|\s*BIT\s*\(", body)
                and re.search(r"&\s*~\s*BIT\s*\(", body)):
            return None
        lines = prelude + ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\tval = readl({reads[0]});",
                           f"\tval = val {first}bit;",
                           f"\twritel(val, {writes[0]});",
                           f"\tval = readl({reads[1]});",
                           f"\tval = val {second}bit;",
                           f"\twritel(val, {writes[1]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
    else:
        required = {
            "IRQ_TYPE_EDGE_BOTH", "IRQ_TYPE_EDGE_RISING",
            "IRQ_TYPE_EDGE_FALLING", "IRQ_TYPE_LEVEL_HIGH",
            "IRQ_TYPE_LEVEL_LOW",
        }
        if len(reads) < 2 or len(writes) < 2 or any(
                not re.search(rf"case\s+{name}\s*:", body)
                for name in required):
            return None
        lines = prelude + ["\tu32 level;", "\tu32 polarity;",
                           "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\tlevel = readl({reads[0]});",
                           f"\tpolarity = readl({reads[1]});", "\tswitch (type) {",
                           "\tcase IRQ_TYPE_EDGE_BOTH:", "\t\tlevel |= bit;",
                           "\t\tif (gc->get(gc, irqd_to_hwirq(d)))",
                           "\t\t\tpolarity &= ~bit;", "\t\telse",
                           "\t\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_EDGE_RISING:", "\t\tlevel |= bit;",
                           "\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_EDGE_FALLING:", "\t\tlevel |= bit;",
                           "\t\tpolarity &= ~bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_LEVEL_HIGH:", "\t\tlevel &= ~bit;",
                           "\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_LEVEL_LOW:", "\t\tlevel &= ~bit;",
                           "\t\tpolarity &= ~bit;", "\t\tbreak;", "\tdefault:",
                           "\t\traw_spin_unlock_irqrestore(&g->irq_lock, flags);",
                           "\t\treturn -EINVAL;", "\t}",
                           f"\twritel(level, {writes[0]});",
                           f"\twritel(polarity, {writes[1]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);",
                           "\tif (type & IRQ_TYPE_LEVEL_MASK)",
                           "\t\tirq_set_handler_locked(d, handle_level_irq);",
                           "\telse", "\t\tirq_set_handler_locked(d, handle_edge_irq);",
                           "\treturn 0;"]
    # This callback is a source-validated specialization rather than the
    # generic ops_to_c path. Preserve per-operation receipts so lowering
    # accounting does not mistake specialized code for silently dropped RIS.
    receipt_lines = [f"\t{lowering_receipt(op)}" for op in leaves
                     if any(kind in op for kind in
                            ("Read", "Write", "ReadModifyWrite"))]
    lines[len(prelude):len(prelude)] = receipt_lines
    lines += ["}", ""]
    return "\n".join(lines)

def emit_banked_irq_handler(cid: str, priv: str, model: dict) -> list[str]:
    bank = bank_priv(priv)
    return [
        f"static void {cid}_banked_irq_handler(struct irq_desc *desc)", "{",
        "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);",
        f"\tstruct {bank} *bank = gpiochip_get_data(gc);",
        f"\tstruct {priv} *g = bank->parent;",
        "\tstruct irq_chip *chip = irq_desc_get_chip(desc);",
        "\tunsigned long pending;", "\tunsigned int hwirq;",
        f"\tpending = readl(g->base + {model['expr']});",
        "\tchained_irq_enter(chip, desc);",
        "\tfor_each_set_bit(hwirq, &pending, gc->ngpio)",
        "\t\tgeneric_handle_domain_irq(gc->irq.domain, hwirq);",
        "\tchained_irq_exit(chip, desc);", "}", "",
    ]

def emit_source_generic_irq_callbacks(cid: str, priv: str,
                                       model: dict) -> list[str]:
    mask = model["mask_reg"]
    eoi = model["eoi_reg"]
    return [
        f"static void {cid}_irq_mask(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        "\tg->irq_mask_cache &= ~bit;",
        f"\twritel(g->irq_mask_cache, g->base + {mask});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
        f"static void {cid}_irq_unmask(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        "\tg->irq_mask_cache |= bit;",
        f"\twritel(g->irq_mask_cache, g->base + {mask});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
        f"static void {cid}_irq_eoi(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        f"\twritel(bit, g->base + {eoi});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
    ]

def emit_source_gpio_callbacks(cid: str, priv: str, model: dict) -> list[str]:
    fields = model["fields"]
    dat = fields["dat"]
    set_reg = fields.get("set", dat)
    dirout = fields.get("dirout")
    if not dirout:
        return []
    return [
        f"static int {cid}_gpio_request(struct gpio_chip *gc, unsigned int line)",
        "{", "\treturn line < gc->ngpio ? 0 : -EINVAL;", "}", "",
        f"static int {cid}_gpio_get(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        f"\treturn !!(readl({dat}) & BIT(line));", "}", "",
        f"static int {cid}_gpio_get_multiple(struct gpio_chip *gc,",
        "\t\t\t\t unsigned long *mask, unsigned long *bits)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\t*bits &= ~*mask;", f"\t*bits |= readl({dat}) & *mask;",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_set(struct gpio_chip *gc, unsigned int line, int value)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(line);",
        "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tif (value)", "\t\tg->gpio_data |= bit;", "\telse",
        "\t\tg->gpio_data &= ~bit;", f"\twritel(g->gpio_data, {set_reg});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_set_multiple(struct gpio_chip *gc,",
        "\t\t\t\t unsigned long *mask, unsigned long *bits)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_data &= ~*mask;", "\tg->gpio_data |= *bits & *mask;",
        f"\twritel(g->gpio_data, {set_reg});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_get_direction(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        f"\treturn readl({dirout}) & BIT(line) ?",
        "\t\tGPIO_LINE_DIRECTION_OUT : GPIO_LINE_DIRECTION_IN;", "}", "",
        f"static int {cid}_gpio_direction_input(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_dir &= ~BIT(line);", f"\twritel(g->gpio_dir, {dirout});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);", "\treturn 0;", "}", "",
        f"static int {cid}_gpio_direction_output(struct gpio_chip *gc,",
        "\t\t\t\t    unsigned int line, int value)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);", "\tunsigned long flags;",
        f"\t{cid}_gpio_set(gc, line, value);",
        "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_dir |= BIT(line);", f"\twritel(g->gpio_dir, {dirout});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);", "\treturn 0;", "}", "",
    ]
