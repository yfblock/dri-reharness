"""Bare-metal C backend (plan Milestone 6, Backend B).

Generates portable freestanding register-programming functions: device struct
with `uintptr_t base`, read32/write32 wrappers, per-function RIS bodies. No
Linux framework glue. Compiles with `cc -ffreestanding`.
"""
from __future__ import annotations
import re
from extractor.formal import walk_leaf_ops
from .common import ops_to_c, local_decls, value_var_names
from .linux import (_bound_resource_probe_ops, _normalize_ops,
                    _portable_function_macros)
from .subsystem_runner import (emit_gpio_callback_runner, gpio_callback_plan,
                               emit_w1c_drain_runner,
                               portable_sdhci_accessor_only, w1c_drain_plan)


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
    L.append("#ifdef REHARNESS_BAREMETAL_ORACLE")
    L.append("#include <stdio.h>")
    L.append("#define MMIO_SIZE 0x1000")
    L.append("static uint8_t oracle_mmio[MMIO_SIZE];")
    L.append("static uintptr_t oracle_base;")
    L.append("static unsigned long oracle_trace_count;")
    L.append("static void oracle_seed_mmio(void) {")
    L.append("    for (unsigned int i = 0; i < MMIO_SIZE; ++i)")
    L.append("        oracle_mmio[i] = (uint8_t)(0x5aU + 37U * i);")
    L.append("}")
    L.append("static void oracle_write_w1c(uint32_t value, uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a - oracle_base;")
    L.append("    uint32_t old = 0;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        old |= (uint32_t)oracle_mmio[off + i] << shift;")
    L.append("    }")
    L.append('    printf("[trace %lu] W 0x%03lx = 0x%08x\\n", oracle_trace_count++, off, value);')
    L.append("    old &= ~value;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        oracle_mmio[off + i] = (uint8_t)(old >> shift);")
    L.append("    }")
    L.append("}")
    L.append("static uint32_t oracle_read(uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a - oracle_base;")
    L.append("    uint32_t value = 0;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        value |= (uint32_t)oracle_mmio[off + i] << shift;")
    L.append("    }")
    L.append('    printf("[trace %lu] R 0x%03lx = 0x%08x\\n", oracle_trace_count++, off, value);')
    L.append("    return value;")
    L.append("}")
    L.append("static void oracle_write(uint32_t value, uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a - oracle_base;")
    L.append('    printf("[trace %lu] W 0x%03lx = 0x%08x\\n", oracle_trace_count++, off, value);')
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        oracle_mmio[off + i] = (uint8_t)(value >> shift);")
    L.append("    }")
    L.append("}")
    L.append("static inline uint32_t mmio_read32(uintptr_t a) { return oracle_read(a, 4, 0); }")
    L.append("static inline void mmio_write32(uint32_t v, uintptr_t a) { oracle_write(v, a, 4, 0); }")
    L.append("static inline uint16_t mmio_read16(uintptr_t a) { return (uint16_t)oracle_read(a, 2, 0); }")
    L.append("static inline void mmio_write16(uint16_t v, uintptr_t a) { oracle_write(v, a, 2, 0); }")
    L.append("static inline uint8_t mmio_read8(uintptr_t a) { return (uint8_t)oracle_read(a, 1, 0); }")
    L.append("static inline void mmio_write8(uint8_t v, uintptr_t a) { oracle_write(v, a, 1, 0); }")
    L.append("static inline void mmio_write_w1c32(uint32_t v, uintptr_t a) { oracle_write_w1c(v, a, 4, 0); }")
    L.append("static inline void mmio_write_w1c16(uint16_t v, uintptr_t a) { oracle_write_w1c(v, a, 2, 0); }")
    L.append("static inline void mmio_write_w1c8(uint8_t v, uintptr_t a) { oracle_write_w1c(v, a, 1, 0); }")
    L.append("static inline uint16_t mmio_read16be(uintptr_t a) { return (uint16_t)oracle_read(a, 2, 1); }")
    L.append("static inline void mmio_write16be(uint16_t v, uintptr_t a) { oracle_write(v, a, 2, 1); }")
    L.append("static inline uint32_t mmio_read32be(uintptr_t a) { return oracle_read(a, 4, 1); }")
    L.append("static inline void mmio_write32be(uint32_t v, uintptr_t a) { oracle_write(v, a, 4, 1); }")
    L.append('#define REHARNESS_CALLBACK_BEGIN(n) printf("[reharness-callback-begin] %u\\n", (unsigned)(n))')
    L.append('#define REHARNESS_CALLBACK_MARKER(name) printf("[reharness-callback] %s\\n", (name))')
    L.append('#define REHARNESS_CALLBACK_RESULT(v) printf("[reharness-result] 0x%llx\\n", (unsigned long long)(v))')
    L.append('#define REHARNESS_CALLBACK_OUTPUT(n, v) printf("[reharness-output] %s=0x%llx\\n", (n), (unsigned long long)(v))')
    L.append('#define REHARNESS_CALLBACK_STATE(d, r) printf("[reharness-state] sdata=0x%llx sdir=0x%llx\\n", (unsigned long long)(d), (unsigned long long)(r))')
    L.append('#define REHARNESS_CALLBACK_END() printf("[reharness-callback-end]\\n")')
    L.append('#define REHARNESS_W1C_BEGIN(n) printf("[reharness-w1c-begin] %u\\n", (unsigned)(n))')
    L.append('#define REHARNESS_W1C_MARKER(name) printf("[reharness-w1c] %s\\n", (name))')
    L.append('#define REHARNESS_W1C_END() printf("[reharness-w1c-end]\\n")')
    L.append("#else")
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
    L.append("static inline void mmio_write_w1c32(uint32_t v, uintptr_t a) { mmio_write32(v, a); }")
    L.append("static inline void mmio_write_w1c16(uint16_t v, uintptr_t a) { mmio_write16(v, a); }")
    L.append("static inline void mmio_write_w1c8(uint8_t v, uintptr_t a) { mmio_write8(v, a); }")
    L.append("static inline uint16_t mmio_read16be(uintptr_t a) {")
    L.append("    volatile uint8_t *p = (volatile uint8_t *)a;")
    L.append("    return (uint16_t)((uint16_t)p[0] << 8 | p[1]);")
    L.append("}")
    L.append("static inline void mmio_write16be(uint16_t v, uintptr_t a) {")
    L.append("    volatile uint8_t *p = (volatile uint8_t *)a;")
    L.append("    p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v;")
    L.append("}")
    L.append("static inline uint32_t mmio_read32be(uintptr_t a) {")
    L.append("    volatile uint8_t *p = (volatile uint8_t *)a;")
    L.append("    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];")
    L.append("}")
    L.append("static inline void mmio_write32be(uint32_t v, uintptr_t a) {")
    L.append("    volatile uint8_t *p = (volatile uint8_t *)a;")
    L.append("    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16);")
    L.append("    p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;")
    L.append("}")
    L.append("#define REHARNESS_CALLBACK_BEGIN(n) ((void)(n))")
    L.append("#define REHARNESS_CALLBACK_MARKER(name) ((void)(name))")
    L.append("#define REHARNESS_CALLBACK_RESULT(v) ((void)(v))")
    L.append("#define REHARNESS_CALLBACK_OUTPUT(n, v) ((void)(n), (void)(v))")
    L.append("#define REHARNESS_CALLBACK_STATE(d, r) ((void)(d), (void)(r))")
    L.append("#define REHARNESS_CALLBACK_END() ((void)0)")
    L.append("#define REHARNESS_W1C_BEGIN(n) ((void)(n))")
    L.append("#define REHARNESS_W1C_MARKER(name) ((void)(name))")
    L.append("#define REHARNESS_W1C_END() ((void)0)")
    L.append("#endif")
    L.append("#define readl(a) mmio_read32((uintptr_t)(a))")
    L.append("#define readw(a) mmio_read16((uintptr_t)(a))")
    L.append("#define readb(a) mmio_read8((uintptr_t)(a))")
    L.append("#define ioread32(a) mmio_read32((uintptr_t)(a))")
    L.append("#define writel(v, a) mmio_write32((uint32_t)(v), (uintptr_t)(a))")
    L.append("#define writew(v, a) mmio_write16((uint16_t)(v), (uintptr_t)(a))")
    L.append("#define writeb(v, a) mmio_write8((uint8_t)(v), (uintptr_t)(a))")
    L.append("#define mdelay(n) (0)")
    L.append("#define irqd_to_hwirq(d) (d)")
    L.append("#define BIT(n) (1u << (n))")
    L.append("#define GENMASK(h, l) (((~0u) << (l)) & (~0u >> (31 - (h))))")
    L.append("#define pci_resource_len(p, b) (0u)")
    L.append("#define mmc_gpio_get_cd(m) (0)")
    L.append("#define ahci_remap_dcc(i) (0u)")
    L.append("#define of_property_read_bool(np, name) (0)")
    L.append("")
    for name, off in regs.items():
        L.append(f"#define {name} 0x{off:x}")
    function_macros = _portable_function_macros(formal)
    safe_function_calls = set(function_macros)
    probe_refs = {fn.ris_ref for fn in device_spec.functions if fn.role == "probe"}
    for name, definition in sorted(function_macros.items()):
        params = ", ".join(definition.get("params", []))
        L.append(f"#define {name}({params}) {definition.get('body', '0')}")
    normalized_any = False
    upper_refs = set()
    upper_calls = set()
    portable_skip = (
        device_spec.cls in {"ahci", "virtio_mmio"}
        or (device_spec.cls == "sdhci"
            and not portable_sdhci_accessor_only(formal, device_spec)))
    for module in formal["modules"]:
        raw_ops = (_bound_resource_probe_ops(module["ops"])
                   if module["name"] in probe_refs else module["ops"])
        safe_ops, changed = _normalize_ops(
            raw_ops, safe_function_calls=safe_function_calls)
        normalized_any |= changed
        upper_refs |= {v for v in value_var_names(safe_ops)
                       if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", v)}
        upper_refs |= set(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", repr(safe_ops)))
        upper_calls |= set(re.findall(r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", repr(safe_ops)))
    for name in sorted(upper_calls - set(regs) - set(function_macros)):
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
    for state in device_spec.state:
        if state.name in {"base", "clk", "num_irqs"}:
            continue
        ctype = "uint64_t" if state.type == "UInt64" else "uint32_t"
        L.append(f"    {ctype} {state.name};")
    L.append("};")
    L.append("")

    func_by_name = {m["name"]: m for m in formal["modules"]}
    for fn in device_spec.functions:
        m = func_by_name.get(fn.ris_ref)
        if not m:
            continue
        raw_ops = (_bound_resource_probe_ops(m["ops"])
                   if fn.role == "probe" else m["ops"])
        safe_ops, _ = _normalize_ops(
            raw_ops, "dev", safe_function_calls)
        if portable_skip:
            safe_ops = []
        keep = [p for p in fn.signature.params if p.type != "DeviceState"]
        params_c = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in keep)
        params_c = (params_c + ", ") if params_c else ""
        params_c += f"{priv} *dev"
        has_return = any("Return" in op for op in walk_leaf_ops(safe_ops))
        return_type = _c_type(fn.signature.return_type, bind) if has_return else "void"
        L.append(f"{return_type} {fn.name}({params_c}) {{")
        declared = {p.name for p in keep} | {"base"}
        L.append(local_decls(safe_ops, declared, regs, indent=1))
        L.append(f"    uintptr_t base = {base};")
        L.append(ops_to_c(safe_ops, bind, "base", regs, indent=1,
                          state_expr="dev"))
        L.append("}")
        L.append("")

    L.extend(emit_gpio_callback_runner(
        formal, device_spec, priv, static=False))
    L.extend(emit_w1c_drain_runner(
        formal, device_spec, priv, static=False))

    plan = gpio_callback_plan(formal, device_spec)
    drain_plan = w1c_drain_plan(formal, device_spec)
    if plan or drain_plan:
        entry = next(
            (fn for fn in device_spec.functions if fn.role == "probe"), None)
        L.append("#ifdef REHARNESS_BAREMETAL_ORACLE")
        L.append("int main(void) {")
        L.append(f"    {priv} dev = {{ .base = 0 }};")
        L.append("    oracle_base = (uintptr_t)oracle_mmio;")
        L.append("    dev.base = oracle_base;")
        L.append("    oracle_seed_mmio();")
        if entry:
            keep = [p for p in entry.signature.params if p.type != "DeviceState"]
            call_args = ", ".join(["0"] * len(keep))
            call_args = (call_args + ", ") if call_args else ""
            L.append(f"    {entry.name}({call_args}&dev);")
        if plan:
            L.append("    oracle_seed_mmio();")
            L.append("    reharness_run_subsystem_callbacks(&dev);")
        if drain_plan:
            L.append("    oracle_seed_mmio();")
            L.append("    reharness_run_w1c_drains(&dev);")
        L.append("    return 0;")
        L.append("}")
        L.append("#endif")
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "uint32_t"
