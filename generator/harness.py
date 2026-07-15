"""Userspace harness backend (plan Milestone 6, Backend A).

Generates a self-contained C harness with a fake MMIO region and trace logging,
so RIS behavior can be executed and compared without kernel deps. Compiles
with plain `cc`.
"""
from __future__ import annotations
import re
from extractor.formal import walk_leaf_ops, walk_all_ops
from .common import ops_to_c, local_decls, value_var_names
from .linux import _normalize_ops

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
    L.append("#define readw(a) ((uint16_t)harness_read32((uintptr_t)(a)))")
    L.append("#define readb(a) ((uint8_t)harness_read32((uintptr_t)(a)))")
    L.append("#define ioread32(a) harness_read32((uintptr_t)(a))")
    L.append("#define writel(v, a) harness_write32((uint32_t)(v), (uintptr_t)(a))")
    L.append("#define writew(v, a) harness_write32((uint16_t)(v), (uintptr_t)(a))")
    L.append("#define writeb(v, a) harness_write32((uint8_t)(v), (uintptr_t)(a))")
    L.append("#define mdelay(n) (0)")
    L.append("#define pci_resource_len(p, b) (0u)")
    L.append("#define mmc_gpio_get_cd(m) (0)")
    L.append("#define ahci_remap_dcc(i) (0u)")
    L.append("")
    L.append(f"#define MMIO_SIZE 0x1000")
    L.append("static uint32_t mmio_region[MMIO_SIZE / 4];")
    L.append("static unsigned long trace_count = 0;")
    L.append("")
    L.append("static inline uint32_t harness_read32(uintptr_t a) {")
    L.append("    uint32_t v = mmio_region[(a & 0xfff) / 4];")
    L.append('    printf("[trace %lu] R 0x%03lx = 0x%08x\\n", trace_count++, (a & 0xfff), v);')
    L.append("    return v;")
    L.append("}")
    L.append("static inline void harness_write32(uint32_t v, uintptr_t a) {")
    L.append('    printf("[trace %lu] W 0x%03lx = 0x%08x\\n", trace_count++, (a & 0xfff), v);')
    L.append("    mmio_region[(a & 0xfff) / 4] = v;")
    L.append("}")
    L.append("")
    # register macros
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
    # device struct
    L.append(f"{priv} {{ uintptr_t base; }};")
    L.append("")

    # one C function per RIS module
    func_by_name = {m["name"]: m for m in formal["modules"]}
    for fn in device_spec.functions:
        m = func_by_name.get(fn.ris_ref)
        if not m:
            continue
        safe_ops, _ = _normalize_ops(m["ops"])
        if portable_skip:
            safe_ops = []
        # drop DeviceState params (the device is passed as `dev`); keep the rest
        keep = [p for p in fn.signature.params if p.type != "DeviceState"]
        params = ", ".join(f"{_c_type(p.type, bind)} {p.name}" for p in keep)
        params = (params + ", ") if params else ""
        params += f"{priv} *dev"
        L.append(f"static void {fn.name}({params}) {{")
        # declare read vars + value/guard locals (common.local_decls skips
        # member-access read targets, which ops_to_c discards)
        declared = {p.name for p in keep} | {"base"}
        decls = local_decls(safe_ops, declared, regs, indent=1)
        if decls:
            L.append(decls)
        L.append(f"    uintptr_t base = dev->base;")
        L.append(ops_to_c(safe_ops, bind, "base", regs, indent=1))
        L.append("}")
        L.append("")

    # test main: call probe (or first function) and dump trace
    entry = next((fn for fn in device_spec.functions if fn.role == "probe"), None)
    entry = entry or (device_spec.functions[0] if device_spec.functions else None)
    L.append("int main(void) {")
    L.append(f"    {priv} dev = {{ .base = 0 }};")
    if entry:
        keep = [p for p in entry.signature.params if p.type != "DeviceState"]
        call_args = ", ".join(["0"] * len(keep)) + (", " if keep else "") + "&dev"
        L.append(f"    {entry.name}({call_args});")
    L.append('    printf("harness done: %lu MMIO ops traced\\n", trace_count);')
    L.append("    return 0;")
    L.append("}")
    return "\n".join(L) + "\n"


def _c_type(abstract: str, bind) -> str:
    return bind.type_of(abstract) or "uint32_t"
