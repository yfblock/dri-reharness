"""Linux driver skeleton backend (plan Milestone 6, Backend C).

Generates a Linux platform-driver scaffold: private struct, probe/remove,
of_device_id, framework ops tables, and RIS-backed callback bodies. Unsupported
semantics emit explicit TODOs (never silent incorrect code). Not auto-built —
the user wires it into a kernel tree.
"""
from __future__ import annotations
from extractor.formal import walk_leaf_ops
from .common import ops_to_c, local_decls


def generate(formal: dict, device_spec, bind) -> str:
    dev = device_spec.name
    priv = bind.type_of("DeviceState") or f"struct {dev}"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    base_expr = bind.state_expr("dev.base") or "g->base"

    L: list[str] = []
    L.append(f"// Auto-generated Linux skeleton for {dev} (reharness)")
    L.append("// SPDX-License-Identifier: GPL-2.0")
    for inc in bind.includes:
        L.append(f"#include {inc}")
    L.append("#include <linux/module.h>")
    L.append("#include <linux/of_device.h>")
    L.append("")
    for name, off in regs.items():
        L.append(f"#define {name}\t0x{off:x}")
    L.append("")
    L.append(f"{priv} {{")
    L.append("\tvoid __iomem *base;")
    if any(s.name == "clk" for s in device_spec.state):
        L.append("\tstruct clk *clk;")
    L.append("\t/* TODO: fill in remaining device state */")
    L.append("};")
    L.append("")

    func_by_name = {m["name"]: m for m in formal["modules"]}
    for fn in device_spec.functions:
        m = func_by_name.get(fn.ris_ref)
        if not m:
            continue
        ret = "void" if fn.signature.return_type == "Void" else "int"
        params_c = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in fn.signature.params)
        params_c = (params_c + ", ") if params_c else ""
        params_c += f"{priv} *g"
        L.append(f"static {ret} {fn.name}({params_c}) {{")
        declared = {p.name for p in fn.signature.params}
        decls = local_decls(m["ops"], declared, regs, indent=1, ctype="u32")
        if decls:
            L.append(decls.replace("    ", "\t"))
        L.append(f"\tvoid __iomem *base = {base_expr};")
        body = ops_to_c(m["ops"], bind, "base", regs, indent=1)
        # re-indent to tabs
        L.append(body.replace("    ", "\t"))
        if ret == "int":
            L.append("\treturn 0;")
        L.append("}")
        L.append("")

    # ops tables + platform_driver
    irq_cbs = [c for c in bind.callbacks if c.table_field.startswith("irq_chip")]
    probe_cb = next((c for c in bind.callbacks if c.table_field == "platform_driver.probe"), None)
    remove_cb = next((c for c in bind.callbacks if c.table_field == "platform_driver.remove"), None)
    if irq_cbs:
        L.append("static struct irq_chip g_irq_chip = {")
        L.append(f'\t.name = "{dev}-irq",')
        for c in irq_cbs:
            field = c.table_field.split(".", 1)[1]
            L.append(f"\t.{field} = {c.function},")
        L.append("};")
        L.append("")
    L.append("static const struct of_device_id g_match[] = {")
    L.append(f'\t{{ .compatible = "vendor,{dev}" }},')
    L.append("\t{ /* sentinel */ }")
    L.append("};")
    L.append("MODULE_DEVICE_TABLE(of, g_match);")
    L.append("")
    L.append("static struct platform_driver g_driver = {")
    if probe_cb:
        L.append(f"\t.probe = {probe_cb.function},")
    if remove_cb:
        L.append(f"\t.remove = {remove_cb.function},")
    L.append("\t.driver = {")
    L.append(f'\t\t.name = "{dev}",')
    L.append("\t\t.of_match_table = g_match,")
    L.append("\t},")
    L.append("};")
    L.append("module_platform_driver(g_driver);")
    L.append(f'MODULE_LICENSE("GPL");')
    L.append('/* TODO: bind irq_chip/gpio_chip registration, probe resource acquisition */')
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "u32"
