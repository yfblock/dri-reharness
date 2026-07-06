"""Bare-metal C backend (plan Milestone 6, Backend B).

Generates portable freestanding register-programming functions: device struct
with `uintptr_t base`, read32/write32 wrappers, per-function RIS bodies. No
Linux framework glue. Compiles with `cc -ffreestanding`.
"""
from __future__ import annotations
from extractor.formal import walk_leaf_ops
from .common import ops_to_c, local_decls


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
    L.append("")
    for name, off in regs.items():
        L.append(f"#define {name} 0x{off:x}")
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
        params_c = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in fn.signature.params)
        params_c = (params_c + ", ") if params_c else ""
        params_c += f"{priv} *dev"
        L.append(f"void {fn.name}({params_c}) {{")
        declared = {p.name for p in fn.signature.params}
        L.append(local_decls(m["ops"], declared, regs, indent=1))
        L.append(f"    uintptr_t base = {base};")
        L.append(ops_to_c(m["ops"], bind, "base", regs, indent=1))
        L.append("}")
        L.append("")
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "uint32_t"
