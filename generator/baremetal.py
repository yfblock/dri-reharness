"""Bare-metal C backend (plan Milestone 6, Backend B).

Generates portable freestanding register-programming functions: device struct
with `uintptr_t base`, read32/write32 wrappers, per-function RIS bodies. No
Linux framework glue. Compiles with `cc -ffreestanding`.
"""
from __future__ import annotations
import re
from extractor.formal import walk_leaf_ops
from .common import ops_to_c, local_decls, value_var_names
from .linux import _normalize_ops


def generate(formal: dict, device_spec, bind) -> str:
    dev = device_spec.name
    priv = bind.type_of("DeviceState") or f"struct {dev}"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    base = "dev->base"

    L: list[str] = []
    L.append(f"/* Auto-generated bare-metal driver for {dev} (reharness) */")
    L.append("#include <stdint.h>")
    L.append("#include <stddef.h>")
    L.append("")
    L.append("static inline uint32_t mmio_read32(uintptr_t a) {")
    L.append("    return *(volatile uint32_t *)a;")
    L.append("}")
    L.append("static inline void mmio_write32(uint32_t v, uintptr_t a) {")
    L.append("    *(volatile uint32_t *)a = v;")
    L.append("}")
    L.append("static inline uint16_t mmio_read16(uintptr_t a) { return *(volatile uint16_t *)a; }")
    L.append("static inline void mmio_write16(uint16_t v, uintptr_t a) { *(volatile uint16_t *)a = v; }")
    L.append("static inline uint8_t mmio_read8(uintptr_t a) { return *(volatile uint8_t *)a; }")
    L.append("static inline void mmio_write8(uint8_t v, uintptr_t a) { *(volatile uint8_t *)a = v; }")
    L.append("#define readl(a) mmio_read32((uintptr_t)(a))")
    L.append("#define readw(a) mmio_read16((uintptr_t)(a))")
    L.append("#define readb(a) mmio_read8((uintptr_t)(a))")
    L.append("#define ioread32(a) mmio_read32((uintptr_t)(a))")
    L.append("#define writel(v, a) mmio_write32((uint32_t)(v), (uintptr_t)(a))")
    L.append("#define writew(v, a) mmio_write16((uint16_t)(v), (uintptr_t)(a))")
    L.append("#define writeb(v, a) mmio_write8((uint8_t)(v), (uintptr_t)(a))")
    L.append("#define mdelay(n) (0)")
    L.append("#define irqd_to_hwirq(d) (d)")
    L.append("#define pci_resource_len(p, b) (0u)")
    L.append("#define mmc_gpio_get_cd(m) (0)")
    L.append("#define ahci_remap_dcc(i) (0u)")
    L.append("")
    for name, off in regs.items():
        L.append(f"#define {name} 0x{off:x}")
    normalized_any = False
    upper_refs = set()
    upper_calls = set()
    portable_skip = device_spec.cls in {"ahci", "sdhci", "virtio_mmio"}
    for module in formal["modules"]:
        safe_ops, changed = _normalize_ops(module["ops"])
        normalized_any |= changed
        upper_refs |= {v for v in value_var_names(safe_ops)
                       if re.fullmatch(r"[A-Z][A-Z0-9_]*", v)}
        upper_refs |= set(re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", repr(safe_ops)))
        upper_calls |= set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\s*\(", repr(safe_ops)))
    for name in sorted(upper_calls - set(regs)):
        L.append(f"#ifndef {name}\n#define {name}(...) 0\n#endif")
    for name in sorted(upper_refs - upper_calls - set(regs) - {"MMIO", "TODO"}):
        L.append(f"#ifndef {name}\n#define {name} 0\n#endif")
    if normalized_any or portable_skip:
        L.append("/* REHARNESS_UNSUPPORTED: source-private expressions normalized */")
    L.append("")
    L.append(f"{priv} {{")
    L.append("    uintptr_t base;")
    if any(s.name == "clk" for s in device_spec.state):
        L.append("    void *clk;")
    L.append("};")
    L.append("")

    func_by_name = {m["name"]: m for m in formal["modules"]}
    for fn in device_spec.functions:
        m = func_by_name.get(fn.ris_ref)
        if not m:
            continue
        safe_ops, _ = _normalize_ops(m["ops"])
        if portable_skip:
            safe_ops = []
        keep = [p for p in fn.signature.params if p.type != "DeviceState"]
        params_c = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in keep)
        params_c = (params_c + ", ") if params_c else ""
        params_c += f"{priv} *dev"
        L.append(f"void {fn.name}({params_c}) {{")
        declared = {p.name for p in keep} | {"base"}
        L.append(local_decls(safe_ops, declared, regs, indent=1))
        L.append(f"    uintptr_t base = {base};")
        L.append(ops_to_c(safe_ops, bind, "base", regs, indent=1))
        L.append("}")
        L.append("")
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "uint32_t"
