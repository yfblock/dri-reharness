"""Userspace harness backend (plan Milestone 6, Backend A).

Generates a self-contained C harness with a fake MMIO region and trace logging,
so RIS behavior can be executed and compared without kernel deps. Compiles
with plain `cc`.
"""
from __future__ import annotations
import re
from extractor.formal import walk_leaf_ops, walk_all_ops
from .common import ops_to_c, local_decls, value_var_names
from .linux import (_bound_resource_probe_ops, _normalize_ops,
                    _portable_function_macros)
from .subsystem_runner import (emit_gpio_callback_runner, gpio_callback_plan,
                               emit_w1c_drain_runner,
                               portable_sdhci_accessor_only, w1c_drain_plan)

_VAR_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_KEYWORDS = {"if", "else", "for", "while", "return", "uint32_t", "uint16_t",
             "uint8_t", "void", "int", "unsigned", "uintptr_t", "sizeof"}


def _value_var_names(ops) -> set[str]:
    """Identifiers referenced in value/guard expressions (for local decls)."""
    names: set[str] = set()
    for op in walk_all_ops(ops):
        if "Cond" in op:
            names |= _vars_in_expr(op["Cond"]["guard"])
        elif "Write" in op:
            names |= _vars_in_expr(op["Write"].get("value"))
        elif "ReadModifyWrite" in op:
            names |= _vars_in_expr(op["ReadModifyWrite"].get("transform"))
    return names


def _vars_in_expr(e) -> set[str]:
    if e is None:
        return set()
    out: set[str] = set()
    if "Var" in e:
        v = e["Var"]
        # only real identifiers (skip call-like or compound Var text)
        if re.fullmatch(r"[A-Za-z_]\w*", v):
            out.add(v)
    if "BinOp" in e:
        out |= _vars_in_expr(e["BinOp"]["left"])
        out |= _vars_in_expr(e["BinOp"]["right"])
    if "Ite" in e:
        out |= _vars_in_expr(e["Ite"]["guard"])
        out |= _vars_in_expr(e["Ite"]["then"])
        out |= _vars_in_expr(e["Ite"]["else"])
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"]["expr"])
    return out


def generate(formal: dict, device_spec, bind) -> str:
    dev = device_spec.name
    priv = bind.type_of("DeviceState") or f"struct {dev}_priv"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    base = bind.state_expr("dev.base") or "dev->base"

    L: list[str] = []
    L.append(f"/* Auto-generated userspace harness for {dev} (reharness) */")
    L.append("#include <stdint.h>")
    L.append("#include <stdio.h>")
    L.append("")
    # stubs for kernel helpers that appear in value expressions, so the harness
    # compiles standalone. Values may be approximate; trace shape is what matters.
    L.append("#define BIT(n) (1u << (n))")
    L.append("#define GENMASK(h, l) (((~0u) << (l)) & (~0u >> (31 - (h))))")
    L.append("#define irqd_to_hwirq(d) (d)")
    L.append("#define cpu_to_le32(x) (x)")
    L.append("#define le32_to_cpu(x) (x)")
    L.append("#define cpu_to_le16(x) (x)")
    L.append("#define le16_to_cpu(x) (x)")
    L.append("#define lower_32_bits(x) ((uint32_t)((x) & 0xffffffff))")
    L.append("#define upper_32_bits(x) ((uint32_t)((x) >> 32))")
    L.append("#define PAGE_SIZE 4096")
    L.append("#define PTR_ERR(x) ((long)(x))")
    L.append("#define ENOMEM (-12)")
    L.append("#define ENODEV (-19)")
    L.append("#define readl(a) harness_read32((uintptr_t)(a))")
    L.append("#define readw(a) harness_read16((uintptr_t)(a))")
    L.append("#define readb(a) harness_read8((uintptr_t)(a))")
    L.append("#define ioread32(a) harness_read32((uintptr_t)(a))")
    L.append("#define writel(v, a) harness_write32((uint32_t)(v), (uintptr_t)(a))")
    L.append("#define writew(v, a) harness_write16((uint16_t)(v), (uintptr_t)(a))")
    L.append("#define writeb(v, a) harness_write8((uint8_t)(v), (uintptr_t)(a))")
    L.append("#define mdelay(n) (0)")
    L.append("#define pci_resource_len(p, b) (0u)")
    L.append("#define mmc_gpio_get_cd(m) (0)")
    L.append("#define ahci_remap_dcc(i) (0u)")
    L.append("#define of_property_read_bool(np, name) (0)")
    L.append("")
    L.append(f"#define MMIO_SIZE 0x1000")
    L.append("static uint8_t mmio_region[MMIO_SIZE];")
    L.append("static unsigned long trace_count = 0;")
    L.append("")
    L.append("static void harness_seed_mmio(void) {")
    L.append("    for (unsigned int i = 0; i < MMIO_SIZE; ++i)")
    L.append("        mmio_region[i] = (uint8_t)(0x5aU + 37U * i);")
    L.append("}")
    L.append("static void harness_write_w1c_width(uint32_t value, uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a & 0xfff;")
    L.append("    uint32_t old = 0;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        old |= (uint32_t)mmio_region[off + i] << shift;")
    L.append("    }")
    L.append('    printf("[trace %lu] W 0x%03lx = 0x%08x\\n", trace_count++, off, value);')
    L.append("    old &= ~value;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        mmio_region[off + i] = (uint8_t)(old >> shift);")
    L.append("    }")
    L.append("}")
    L.append("static uint32_t harness_read_width(uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a & 0xfff;")
    L.append("    uint32_t value = 0;")
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        value |= (uint32_t)mmio_region[off + i] << shift;")
    L.append("    }")
    L.append('    printf("[trace %lu] R 0x%03lx = 0x%08x\\n", trace_count++, off, value);')
    L.append("    return value;")
    L.append("}")
    L.append("static void harness_write_width(uint32_t value, uintptr_t a, unsigned int width, int be) {")
    L.append("    uintptr_t off = a & 0xfff;")
    L.append('    printf("[trace %lu] W 0x%03lx = 0x%08x\\n", trace_count++, off, value);')
    L.append("    for (unsigned int i = 0; i < width; ++i) {")
    L.append("        unsigned int shift = be ? 8U * (width - i - 1U) : 8U * i;")
    L.append("        mmio_region[off + i] = (uint8_t)(value >> shift);")
    L.append("    }")
    L.append("}")
    L.append("static inline uint8_t harness_read8(uintptr_t a) { return (uint8_t)harness_read_width(a, 1, 0); }")
    L.append("static inline uint16_t harness_read16(uintptr_t a) { return (uint16_t)harness_read_width(a, 2, 0); }")
    L.append("static inline uint32_t harness_read32(uintptr_t a) { return harness_read_width(a, 4, 0); }")
    L.append("static inline uint16_t harness_read16be(uintptr_t a) { return (uint16_t)harness_read_width(a, 2, 1); }")
    L.append("static inline uint32_t harness_read32be(uintptr_t a) { return harness_read_width(a, 4, 1); }")
    L.append("static inline void harness_write8(uint8_t v, uintptr_t a) { harness_write_width(v, a, 1, 0); }")
    L.append("static inline void harness_write16(uint16_t v, uintptr_t a) { harness_write_width(v, a, 2, 0); }")
    L.append("static inline void harness_write32(uint32_t v, uintptr_t a) { harness_write_width(v, a, 4, 0); }")
    L.append("static inline void harness_write_w1c8(uint8_t v, uintptr_t a) { harness_write_w1c_width(v, a, 1, 0); }")
    L.append("static inline void harness_write_w1c16(uint16_t v, uintptr_t a) { harness_write_w1c_width(v, a, 2, 0); }")
    L.append("static inline void harness_write_w1c32(uint32_t v, uintptr_t a) { harness_write_w1c_width(v, a, 4, 0); }")
    L.append("static inline void harness_write16be(uint16_t v, uintptr_t a) { harness_write_width(v, a, 2, 1); }")
    L.append("static inline void harness_write32be(uint32_t v, uintptr_t a) { harness_write_width(v, a, 4, 1); }")
    L.append('#define REHARNESS_CALLBACK_BEGIN(n) printf("[reharness-callback-begin] %u\\n", (unsigned)(n))')
    L.append('#define REHARNESS_CALLBACK_MARKER(name) printf("[reharness-callback] %s\\n", (name))')
    L.append('#define REHARNESS_CALLBACK_RESULT(v) printf("[reharness-result] 0x%llx\\n", (unsigned long long)(v))')
    L.append('#define REHARNESS_CALLBACK_OUTPUT(n, v) printf("[reharness-output] %s=0x%llx\\n", (n), (unsigned long long)(v))')
    L.append('#define REHARNESS_CALLBACK_STATE(d, r) printf("[reharness-state] sdata=0x%llx sdir=0x%llx\\n", (unsigned long long)(d), (unsigned long long)(r))')
    L.append('#define REHARNESS_CALLBACK_END() printf("[reharness-callback-end]\\n")')
    L.append('#define REHARNESS_W1C_BEGIN(n) printf("[reharness-w1c-begin] %u\\n", (unsigned)(n))')
    L.append('#define REHARNESS_W1C_MARKER(name) printf("[reharness-w1c] %s\\n", (name))')
    L.append('#define REHARNESS_W1C_END() printf("[reharness-w1c-end]\\n")')
    L.append("")
    # register macros
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
    # device struct
    state_fields = [s for s in device_spec.state
                    if s.name not in {"base", "clk", "num_irqs"}]
    L.append(f"{priv} {{")
    L.append("    uintptr_t base;")
    for state in state_fields:
        ctype = "uint64_t" if state.type == "UInt64" else "uint32_t"
        L.append(f"    {ctype} {state.name};")
    L.append("};")
    L.append("")

    # one C function per RIS module
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
        # drop DeviceState params (the device is passed as `dev`); keep the rest
        keep = [p for p in fn.signature.params if p.type != "DeviceState"]
        params = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in keep)
        params = (params + ", ") if params else ""
        params += f"{priv} *dev"
        has_return = any("Return" in op for op in walk_leaf_ops(safe_ops))
        return_type = _c_type(fn.signature.return_type, bind) if has_return else "void"
        L.append(f"static {return_type} {fn.name}({params}) {{")
        # declare read vars + value/guard locals (common.local_decls skips
        # member-access read targets, which ops_to_c discards)
        declared = {p.name for p in keep} | {"base"}
        decls = local_decls(safe_ops, declared, regs, indent=1)
        if decls:
            L.append(decls)
        L.append(f"    uintptr_t base = dev->base;")
        L.append(ops_to_c(safe_ops, bind, "base", regs, indent=1,
                          state_expr="dev"))
        L.append("}")
        L.append("")

    L.extend(emit_gpio_callback_runner(
        formal, device_spec, priv, static=True))
    L.extend(emit_w1c_drain_runner(
        formal, device_spec, priv, static=True))

    # test main: call probe (or first function) and dump trace
    entry = next((fn for fn in device_spec.functions if fn.role == "probe"), None)
    entry = entry or (device_spec.functions[0] if device_spec.functions else None)
    L.append("int main(void) {")
    init = [".base = 0"]
    if any(s.name == "ngpio" for s in state_fields):
        init.append(".ngpio = 32")
    if any(s.name == "hpi_regstep" for s in state_fields):
        init.append(".hpi_regstep = 1")
    L.append(f"    {priv} dev = {{ {', '.join(init)} }};")
    L.append("    harness_seed_mmio();")
    if entry:
        keep = [p for p in entry.signature.params if p.type != "DeviceState"]
        call_args = ", ".join(["0"] * len(keep)) + (", " if keep else "") + "&dev"
        L.append(f"    {entry.name}({call_args});")
    if gpio_callback_plan(formal, device_spec):
        L.append("    harness_seed_mmio();")
        L.append("    reharness_run_subsystem_callbacks(&dev);")
    if w1c_drain_plan(formal, device_spec):
        L.append("    harness_seed_mmio();")
        L.append("    reharness_run_w1c_drains(&dev);")
    L.append('    printf("harness done: %lu MMIO ops traced\\n", trace_count);')
    L.append("    return 0;")
    L.append("}")
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "uint32_t"
