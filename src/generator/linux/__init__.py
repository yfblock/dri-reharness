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

from .normalize import *  # noqa: F401,F403
from .source_parse import *  # noqa: F401,F403
from .source_models import *  # noqa: F401,F403
from .callbacks import *  # noqa: F401,F403
from .emit import *  # noqa: F401,F403

NAME = "linux"


def generate(formal: dict, device_spec, bind, **kwargs) -> str:
    """Generate code via LLM if available, otherwise fall back to rules."""
    import os
    if os.environ.get("REHARNESS_USE_LLM", "").lower() in ("1", "true", "yes"):
        try:
            from generator.llm_bridge import generate_via_llm, llm_available
            if llm_available():
                return generate_via_llm(formal, device_spec, bind, backend="linux")
        except Exception as e:
            import sys
            print("LLM failed: " + str(e) + ", using rules", file=sys.stderr)
    return generate_rules(formal, device_spec, bind, **kwargs)

def generate_rules(formal: dict, device_spec, bind, facts=None, pci_identity=None) -> str:
    dev = device_spec.name
    preserved_virtio = source_preserved_virtio(
        formal, device_spec, facts)
    if preserved_virtio is not None:
        return preserved_virtio
    priv = f"{make_cid(dev)}_priv"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    tx_selectors = {r["name"]: r["value"]
                    for r in formal.get("transaction_map", [])}
    constants = {**regs, **tx_selectors}
    callbacks = callback_map(bind, facts, device_spec)
    modules = {m["name"]: m for m in formal["modules"]}
    has_regmap_transactions = any(
        any(name in op and op[name].get("transport") == "regmap" for name in
            ("TransactionRead", "TransactionWrite", "TransactionUpdate"))
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", [])))
    selective_closure = formal.get("metadata", {}).get(
        "call_graph", {}).get("selective_closure", {})
    closure_overlays = selective_closure.get("overlays", {})
    if not isinstance(closure_overlays, dict):
        closure_overlays = {}
    # A callback may have no canonical register operations of its own.  Keep
    # canonical Formal untouched and expose an overlay-only virtual module to
    # code generation so the registered callback can still own the closure.
    for module_name, ops in closure_overlays.items():
        if (isinstance(module_name, str) and module_name
                and isinstance(ops, list) and module_name not in modules):
            modules[module_name] = {
                "name": module_name, "ops": [], "source": None,
            }
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    if device_spec.cls == "sdhci" and isinstance(summary_groups, dict):
        for item in summary_groups.get("sdhci_ops", []):
            if (item.get("implementation") == "source-private"
                    and item.get("field") and item.get("module") in modules):
                callbacks.setdefault(
                    item["module"], f"sdhci_ops.{item['field']}")
    function_macros = portable_function_macros(formal)
    safe_function_calls = set(function_macros)
    probe_refs = {
        fn.ris_ref for fn in device_spec.functions if fn.role == "probe"
    }

    def backend_ops(module: dict):
        overlay = selective_overlay_ops(formal, module.get("name"))
        ops = overlay if isinstance(overlay, list) else module.get("ops", [])
        return (bound_resource_probe_ops(ops)
                if module.get("name") in probe_refs else ops)
    callbacks_for_codegen = {
        fn: field for fn, field in callbacks.items()
        if fn in modules or field.endswith((".probe", ".remove"))
    }

    callback_code: list[str] = []
    unsupported: list[str] = []
    dropped_callbacks: set[str] = set()
    clock_model = (clock_source_model(facts, priv)
                   if device_spec.cls == "clock" else None)
    if clock_model:
        callback_code.extend(clock_model["helpers"])
        if clock_model["helpers"]:
            callback_code.append("")
        for function in sorted(clock_model["callbacks"]):
            callback_code.append(clock_model["callbacks"][function])
            callback_code.append("")
    gpio_model = (source_gpio_model(facts)
                  if device_spec.cls == "gpio_controller" else None)
    gpio_summaries = (summary_groups.get("gpio_generic", [])
                      if isinstance(summary_groups, dict) else [])
    gpio_bank = next((summary.get("bank_model") for summary in gpio_summaries
                      if summary.get("bank_model")), None)
    banked_gpio = gpio_bank is not None
    banked_irq_model = (banked_irq_status_model(facts)
                        if banked_gpio and gpio_bank.get("irq") else None)
    if banked_irq_model:
        callback_code.extend(emit_banked_irq_handler(
            make_cid(dev), priv, banked_irq_model))
    elif banked_gpio and gpio_bank.get("irq"):
        unsupported.append(
            "banked GPIO parent IRQ status register lacks source proof")
    irq_model = (source_generic_irq_model(facts)
                 if gpio_model is not None else None)
    gpio_member = "gc"
    irq_source_callbacks: dict[str, str] = {}
    source_path = getattr(facts, "source", None) if facts is not None else None
    source_text = ""
    if source_path and source_path.endswith(".c") and os.path.isfile(source_path):
        source_text = open(
            source_path, "r", encoding="utf-8", errors="replace").read()
        for fn in device_spec.functions:
            field = callbacks.get(fn.name)
            if not field:
                continue
            if banked_gpio and banked_gpio_callback(field):
                continue
            code = lower_irq_source_callback(
                source_text, fn.name, field, priv, gpio_member,
                modules.get(fn.ris_ref))
            if code:
                irq_source_callbacks[fn.name] = code
        for function in sorted(irq_source_callbacks):
            callback_code.append(irq_source_callbacks[function])
            callback_code.append("")
    if device_spec.cls == "ahci":
        unsupported.append("AHCI probe requires libata host/port state bindings")
    if (device_spec.cls == "sdhci"
            and not portable_sdhci_accessor_only(formal, device_spec)):
        unsupported.append("SDHCI probe requires mmc/host state bindings")
    if (device_spec.cls == "virtio_mmio"
            and not portable_virtio_state_only(formal, device_spec)):
        unsupported.append("virtio-mmio probe requires virtio core state bindings")
    usb_callback_fields = {
        field for field in callbacks.values()
        if field.startswith(("usb_ep_ops.", "usb_gadget_ops.", "hc_driver."))
    }
    if usb_callback_fields:
        unsupported.append(
            "USB callback tables require endpoint/gadget/HCD lifecycle registration")
    if any(normalize_module_ops(
            m, safe_function_calls=safe_function_calls,
            backend_ops=backend_ops(m))[1]
           for m in formal.get("modules", [])):
        unsupported.append("source-private expressions require explicit state bindings")

    # Once a driver is already explicitly non-ready, keep large real-driver
    # outputs compilable even when source-local macro helpers are not exported
    # through FactsSpec. Object constants recovered from headers remain exact;
    # only the residual names below receive guarded neutral fallbacks.
    fallback_refs: set[str] = set()
    fallback_calls: set[str] = set()
    if unsupported:
        for definition in function_macros.values():
            body = definition.get("body", "")
            fallback_refs |= set(re.findall(
                r"\b[A-Z][A-Za-z0-9_]{2,}\b", body))
            fallback_calls |= set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", body))
        for module in formal.get("modules", []):
            safe_ops, _, _contract_recipes = normalize_module_ops(
                module, safe_function_calls=safe_function_calls,
                backend_ops=backend_ops(module))
            fallback_refs |= {name for name in value_var_names(safe_ops)
                              if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name)}
            fallback_refs |= set(re.findall(
                r"\b[A-Z][A-Za-z0-9_]{2,}\b", repr(safe_ops)))
            fallback_calls |= set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", repr(safe_ops)))
    for fn in device_spec.functions:
        field = callbacks.get(fn.name)
        if not field or field.endswith(".probe") or field.endswith(".remove"):
            continue
        if (clock_model and field.startswith("clk_ops.")
                and fn.name in clock_model["callbacks"]):
            continue
        if fn.name in irq_source_callbacks:
            continue
        if dev == "edu" and field.startswith("file_operations."):
            # The edu PCI backend supplies checked raw-MMIO file operations
            # with the correct miscdevice private-data lifecycle below.
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        if banked_gpio and field.startswith("irq_chip.") and source_text:
            code = emit_banked_irq_source_callback(
                fn, module, field, priv, regs, source_text,
                safe_function_calls)
            if code:
                callback_code.append(code)
                continue
        code, problem = emit_callback(
            fn, module, field, priv, regs, bind, safe_function_calls,
            banked_gpio=banked_gpio, backend_ops=backend_ops(module))
        if code:
            callback_code.append(code)
        else:
            # The callback could not be lowered (e.g. its field is not in the
            # modeled signature table).  Drop it from the codegen callback map
            # so backend callback tables do not reference an undefined static
            # symbol; a designated-initializer table omits the field (NULL).
            dropped_callbacks.add(fn.name)
        if problem:
            unsupported.append(problem)

    binding_rows = formal.get("metadata", {}).get(
        "callback_binding_analysis", {}).get("bindings", [])
    multi_source = len(formal.get("metadata", {}).get("sources", [])) > 1
    evidence_only = {
        row.get("function") for row in binding_rows
        if (row.get("role") == "unknown"
            and row.get("public_callback_type") is False
            and multi_source)}
    for fn in device_spec.functions:
        if (fn.name not in evidence_only
                or fn.name in callbacks_for_codegen):
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        callback_code.append(emit_evidence_only_callback(
            fn, module, priv, regs, bind, safe_function_calls))

    emitted_names = {fn.name for fn in device_spec.functions
                     if fn.name in callbacks_for_codegen}
    for fn in device_spec.functions:
        if fn.name in emitted_names:
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        if any((op.get("TransactionRead") or op.get("TransactionWrite")
                or op.get("TransactionUpdate"))
               for op in walk_leaf_ops(module.get("ops", []))):
            callback_code.append(emit_transaction_runner(
                fn, module, priv, regs, bind, safe_function_calls))

    callbacks = callbacks_for_codegen
    if dropped_callbacks:
        callbacks = {
            fn: field for fn, field in callbacks_for_codegen.items()
            if fn not in dropped_callbacks}
    is_pci = any(field.startswith("pci_driver.") for field in callbacks.values())
    has_delay = any("Delay" in op for module in formal.get("modules", [])
                    for op in walk_leaf_ops(module.get("ops", [])))
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
    includes.extend(f"#include {path}" for path in mfd_include_paths(formal))
    if any(field.startswith(("irq_chip.", "gpio_chip.", "gpio_irq_chip."))
           for field in callbacks.values()):
        includes += ["#include <linux/gpio/driver.h>", "#include <linux/irq.h>",
                     "#include <linux/bitops.h>"]
    if gpio_model or irq_model or banked_gpio:
        includes.append("#include <linux/spinlock.h>")
    if any(field.startswith("clk_ops.") for field in callbacks.values()):
        includes += ["#include <linux/clk-provider.h>"]
    if (any(state.name == "hpi_regstep" for state in device_spec.state)
            or any(state.name == "gpio_config_variant"
                   for state in device_spec.state)
            or any(state.type == "UIntArray" for state in device_spec.state)):
        includes += ["#include <linux/property.h>"]
    if banked_gpio and gpio_bank.get("irq"):
        includes += ["#include <linux/acpi.h>", "#include <linux/irqdomain.h>"]
    if any(state.name == "gpio_config_variant" for state in device_spec.state):
        includes += ["#include <linux/of.h>"]
    if any(field.startswith(("usb_ep_ops.", "usb_gadget_ops."))
           for field in callbacks.values()):
        includes += ["#include <linux/usb/gadget.h>"]
    if any(field.startswith("hc_driver.") for field in callbacks.values()):
        includes += ["#include <linux/usb.h>", "#include <linux/usb/hcd.h>"]
    if device_spec.cls == "sdhci":
        includes += ["#include <linux/delay.h>", "#include <linux/mmc/host.h>",
                     '#include "sdhci-pltfm.h"']
    elif has_delay:
        includes += ["#include <linux/delay.h>"]
    if re.search(r"\bread_poll_timeout(?:_atomic)?\s*\(", source_text):
        includes += ["#include <linux/iopoll.h>"]

    L = [f"// Auto-generated deterministic Linux driver for {dev} (reharness)",
         "// SPDX-License-Identifier: GPL-2.0", *includes, ""]
    tx_transports = detect_transaction_transports(formal)
    L.extend(transaction_runtime_prelude_filtered(
        "linux", **tx_transports))
    L.append("")
    for name, off in constants.items():
        L.append(f"#ifndef {name}\n#define {name}\t0x{off:x}\n#endif")
    for name, definition in sorted(function_macros.items()):
        params = ", ".join(definition.get("params", []))
        body = definition.get("body", "0")
        L.append(
            f"#ifndef {name}\n#define {name}({params}) {body}\n#endif")
    source_macros = source_object_macros(facts)
    for name, value in source_macros.items():
        if name not in constants:
            L.append(f"#ifndef {name}\n#define {name}\t{value}\n#endif")
    if facts is not None:
        for name, value in sorted(facts.constants.items()):
            if name not in constants and name not in source_macros:
                L.append(f"#ifndef {name}\n#define {name}\t0x{value:x}\n#endif")
    known_constants = set(constants)
    known_functions = set(function_macros)
    if facts is not None:
        known_constants |= set(facts.constants)
    if unsupported:
        for name in sorted(fallback_calls - known_constants - known_functions):
            L.append(f"#ifndef {name}\n#define {name}(...) 0\n#endif")
        for name in sorted(fallback_refs - fallback_calls - known_constants
                           - {"MMIO", "TODO"}):
            L.append(f"#ifndef {name}\n#define {name} 0\n#endif")
    if banked_gpio:
        L += ["", f"struct {bank_priv(priv)};"]
    L += ["", f"struct {priv} {{", "\tstruct device *dev;",
          "\tvoid __iomem *base;"]
    if has_regmap_transactions:
        L.append("\tstruct regmap *regmap;")
    has_i2c_transactions = any(
        any((name in op) and op[name].get("transport") in {"i2c", "i2c_smbus"}
            for name in ("TransactionRead", "TransactionWrite", "TransactionUpdate"))
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", [])))
    if has_i2c_transactions:
        L.append("\tstruct i2c_client *client;")
    has_mfd_transactions = any(
        any((name in op) and op[name].get("transport") == "mfd"
            for name in ("TransactionRead", "TransactionWrite",
                         "TransactionUpdate"))
        for module in formal.get("modules", [])
        for op in walk_leaf_ops(module.get("ops", [])))
    if has_mfd_transactions:
        L.append("\tvoid *mfd;")
    if device_spec.cls == "sdhci":
        L.append("\tstruct sdhci_host *host;")
    if is_pci:
        L.append("\tstruct pci_dev *pdev;")
        if dev == "edu":
            L.append("\tstruct miscdevice misc;")
        if any(field.startswith(("gpio_chip.", "irq_chip.", "gpio_irq_chip.",
                                 "irq_handler."))
               for field in callbacks.values()):
            L.append("\tstruct gpio_chip gc;")
            L.append("\tstruct irq_chip irqchip;")
            if gpio_model:
                L += ["\traw_spinlock_t gpio_lock;", "\tu32 gpio_data;",
                      "\tu32 gpio_dir;"]
            if irq_model:
                L += ["\traw_spinlock_t irq_lock;", "\tu32 irq_mask_cache;"]
    else:
        if banked_gpio:
            L += [f"\tstruct {bank_priv(priv)} *banks;",
                  "\tstruct irq_chip irqchip;", "\traw_spinlock_t irq_lock;",
                  "\tstruct clk *clk;"]
        else:
            L += ["\tstruct gpio_chip gc;", "\tstruct irq_chip irqchip;",
                  "\tstruct clk *clk;"]
        if (clock_model or any(
                field.startswith("clk_ops.") for field in callbacks.values())):
            L.append("\tstruct clk_hw hw;")
        if clock_model:
            L += ["\tstruct clk_init_data init;",
                  "\tstruct clk_parent_data parent_data;"]
    if any(field.startswith("usb_ep_ops.") for field in callbacks.values()):
        L.append("\tstruct usb_ep ep;")
    if any(field.startswith("usb_gadget_ops.") for field in callbacks.values()):
        L.append("\tstruct usb_gadget gadget;")
    for state in device_spec.state:
        if state.name in {"base", "clk", "num_irqs"}:
            continue
        if banked_gpio and state.name in {
                "gpio_bank_index", "gpio_sdata", "gpio_sdir"}:
            continue
        ctype = ("void __iomem *" if state.type == "MmioBase" else
                 "u32 *" if state.type == "UIntArray" else
                 "u64" if state.type == "UInt64" else "u32")
        L.append(f"\t{ctype} {state.name};")
    L += ["};", ""]
    if banked_gpio:
        L += [f"struct {bank_priv(priv)} {{",
              "\tstruct gpio_chip gc;", f"\tstruct {priv} *parent;",
              "\tu32 gpio_bank_index;", "\tu32 gpio_sdata;",
              "\tu32 gpio_sdir;", "\tu32 ngpio;",
              "\tunsigned int *parent_irqs;",
              "\tunsigned int num_parent_irqs;", "};", ""]
    if has_delay:
        L += ["static inline void reharness_delay_ns(unsigned long ns)", "{",
              "\tif (ns <= 1000)", "\t\tndelay(ns);",
              "\telse if (ns <= 1000000)",
              "\t\tudelay(DIV_ROUND_UP(ns, 1000));", "\telse",
              "\t\tmdelay(DIV_ROUND_UP(ns, 1000000));", "}", ""]

    if unsupported:
        for item in unsupported:
            L.append(f"/* REHARNESS_UNSUPPORTED callback: {item} */")
        L.append("")

    sdhci_body = (emit_sdhci_platform(
        formal, device_spec, facts, priv, callbacks, callback_code)
        if device_spec.cls == "sdhci" else None)
    if sdhci_body is not None:
        body = sdhci_body
    elif is_pci:
        body = emit_pci(formal, device_spec, bind, facts, priv, regs,
                         callbacks, callback_code, unsupported,
                         gpio_model, irq_model, pci_identity)
    else:
        body = emit_platform(formal, device_spec, bind, facts, priv, regs,
                              callbacks, callback_code, unsupported,
                              clock_model)
    L += [body, "", 'MODULE_LICENSE("GPL");',
          f'MODULE_DESCRIPTION("reharness generated driver for {dev}");']
    return "\n".join(L) + "\n"

def make_bind(device_spec, bind, priv: str, base_expr: str) -> None:
    """Populate bind with linux-specific types, primitives, callbacks, etc."""
    from extractor.spec import (PUBLIC_CALLBACK_TYPES, _field_for_role)
    bind.includes = ["<linux/io.h>", "<linux/platform_device.h>"]
    bind.types = [
        TypeMap("DeviceState", priv),
        TypeMap("MmioBase", "void __iomem *"),
        TypeMap("LogicalIRQ", "struct irq_data *"),
        TypeMap("UInt", "u32"),
        TypeMap("UIntPtr", "unsigned long *"),
    ]
    bind.primitives = [
        PrimitiveMap("MmioRead", "B4", "readl"),
        PrimitiveMap("MmioWrite", "B4", "writel"),
        PrimitiveMap("MmioRead", "B2", "readw"),
        PrimitiveMap("MmioWrite", "B2", "writew"),
        PrimitiveMap("MmioRead", "B1", "readb"),
        PrimitiveMap("MmioWrite", "B1", "writeb"),
        PrimitiveMap("MmioWriteW1C", "B4", "writel"),
        PrimitiveMap("MmioWriteW1C", "B2", "writew"),
        PrimitiveMap("MmioWriteW1C", "B1", "writeb"),
        PrimitiveMap("MmioReadBE", "B2", "ioread16be"),
        PrimitiveMap("MmioWriteBE", "B2", "iowrite16be"),
        PrimitiveMap("MmioReadBE", "B4", "ioread32be"),
        PrimitiveMap("MmioWriteBE", "B4", "iowrite32be"),
    ]
    bind.state = [StateMap("dev.base", base_expr)]
    for fn in device_spec.functions:
        if (fn.is_callback_entry and fn.callback_table
                and fn.role not in {"unknown", "helper"}
                and fn.callback_table.split(".", 1)[0]
                in PUBLIC_CALLBACK_TYPES):
            if "." in fn.callback_table:
                bind.callbacks.append(CallbackMap(fn.callback_table, fn.name))
            else:
                f = _field_for_role(fn.role)
                if f:
                    bind.callbacks.append(CallbackMap(
                        f"{fn.callback_table}.{f}", fn.name))
        elif fn.role == "probe":
            bind.callbacks.append(CallbackMap("platform_driver.probe", fn.name))
        elif fn.role == "remove":
            bind.callbacks.append(CallbackMap("platform_driver.remove", fn.name))


NAME = 'linux'
LANG = 'C'
GEN_KWARGS = ['facts', 'pci_identity']

_analyze_clock_source_model = analyze_clock_source_model_inner  # backward compat
_balanced_initializer_blocks = balanced_initializer_blocks  # backward compat
_bank_priv = bank_priv  # backward compat
_banked_gpio_callback = banked_gpio_callback  # backward compat
_banked_irq_status_model = banked_irq_status_model  # backward compat
_bind_state_text = bind_state_text  # backward compat
_bound_resource_probe_ops = bound_resource_probe_ops  # backward compat
_callback_map = callback_map  # backward compat
_callback_signature = callback_signature  # backward compat
_canonical_args = canonical_args  # backward compat
_cid = make_cid  # backward compat
_clock_source_model = clock_source_model  # backward compat
_emit_banked_irq_handler = emit_banked_irq_handler  # backward compat
_emit_banked_irq_source_callback = emit_banked_irq_source_callback  # backward compat
_emit_callback = emit_callback  # backward compat
_emit_evidence_only_callback = emit_evidence_only_callback  # backward compat
_emit_pci = emit_pci  # backward compat
_emit_platform = emit_platform  # backward compat
_emit_probe_body = emit_probe_body  # backward compat
_emit_sdhci_platform = emit_sdhci_platform  # backward compat
_emit_source_generic_irq_callbacks = emit_source_generic_irq_callbacks  # backward compat
_emit_source_gpio_callbacks = emit_source_gpio_callbacks  # backward compat
_emit_transaction_runner = emit_transaction_runner  # backward compat
_emit_usb_callback_tables = emit_usb_callback_tables  # backward compat
_initializer_expr = initializer_expr  # backward compat
_last_read_var = last_read_var  # backward compat
_lower_clock_source_callback = lower_clock_source_callback  # backward compat
_lower_clock_source_callback_analysis = lower_clock_source_callback_analysis  # backward compat
_lower_irq_source_callback = lower_irq_source_callback  # backward compat
_mask_c_source = mask_c_source  # backward compat
_match_data_state_initializers = match_data_state_initializers  # backward compat
_matching_delimiter = matching_delimiter  # backward compat
_mfd_include_paths = mfd_include_paths  # backward compat
_normalize_expr = normalize_expr  # backward compat
_normalize_module_ops = normalize_module_ops  # backward compat
_normalize_ops = normalize_ops  # backward compat
_normalize_text = normalize_text  # backward compat
_normalize_transaction_expr = normalize_transaction_expr  # backward compat
_parameter_names = parameter_names  # backward compat
_parse_clk_ops_groups = parse_clk_ops_groups  # backward compat
_pci_ids = pci_ids  # backward compat
_portable_function_macros = portable_function_macros  # backward compat
_probe_ops = probe_ops  # backward compat
_sdhci_source_model = sdhci_source_model  # backward compat
_selective_overlay_ops = selective_overlay_ops  # backward compat
_source_function = source_function  # backward compat
_source_generic_irq_model = source_generic_irq_model  # backward compat
_source_gpio_model = source_gpio_model  # backward compat
_source_object_macros = source_object_macros  # backward compat
_source_preserved_virtio = source_preserved_virtio  # backward compat