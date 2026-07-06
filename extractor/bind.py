"""Backend binding language `.bind` (plan Milestone 5.5).

Maps backend-independent DeviceSpec concepts to a concrete runtime:
  - type mapping (DeviceState -> "struct ftgpio_gpio", MmioBase -> "void __iomem *")
  - callback table mapping (irq_chip.irq_ack = ftgpio_gpio_ack_irq)
  - MMIO primitive mapping (MmioRead(B4) -> "readl")
  - state access mapping (dev.base -> "g->base")
  - function export mapping

A default .bind is auto-generated per backend from the DeviceSpec; users may
hand-edit it. Code generators consume (RIS, DeviceSpec, BindSpec).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class TypeMap:
    abstract: str        # e.g. "DeviceState"
    concrete: str        # e.g. "struct ftgpio_gpio"


@dataclass
class CallbackMap:
    table_field: str     # e.g. "irq_chip.irq_ack"
    function: str


@dataclass
class PrimitiveMap:
    op: str              # "MmioRead" | "MmioWrite"
    width: str           # "B4"
    concrete: str        # "readl"


@dataclass
class StateMap:
    abstract_path: str   # "dev.base"
    concrete_expr: str   # "g->base"


@dataclass
class ExportMap:
    role: str            # "interrupt_ack"
    symbol: str          # "ftgpio_ack_irq"


@dataclass
class BindSpec:
    backend: str         # "linux" | "baremetal" | "harness"
    device: str
    includes: list[str] = field(default_factory=list)
    types: list[TypeMap] = field(default_factory=list)
    callbacks: list[CallbackMap] = field(default_factory=list)
    primitives: list[PrimitiveMap] = field(default_factory=list)
    state: list[StateMap] = field(default_factory=list)
    exports: list[ExportMap] = field(default_factory=list)

    def prim(self, op: str, width: str) -> Optional[str]:
        for p in self.primitives:
            if p.op == op and p.width == width:
                return p.concrete
        return None

    def type_of(self, abstract: str) -> Optional[str]:
        for t in self.types:
            if t.abstract == abstract:
                return t.concrete
        return None

    def state_expr(self, abstract_path: str) -> Optional[str]:
        for s in self.state:
            if s.abstract_path == abstract_path:
                return s.concrete_expr
        return None

    def display(self) -> str:
        lines = [f"backend {self.backend} for device {self.device} {{"]
        for inc in self.includes:
            lines.append(f'  include {inc}')
        for t in self.types:
            lines.append(f'  type {t.abstract} -> "{t.concrete}"')
        for c in self.callbacks:
            lines.append(f"  callback {c.table_field} = {c.function}")
        for e in self.exports:
            lines.append(f'  export {e.role} as "{e.symbol}"')
        for s in self.state:
            lines.append(f'  map {s.abstract_path} -> "{s.concrete_expr}"')
        for p in self.primitives:
            lines.append(f'  map {p.op}({p.width}) -> "{p.concrete}"')
        lines.append("}")
        return "\n".join(lines)


# ── default binding generation per backend ───────────────────────────

def _priv_struct_name(device_spec) -> str:
    # derive a private struct name from the driver name
    n = re.sub(r"[^A-Za-z0-9_]", "_", device_spec.name)
    return f"struct {n}_priv" if device_spec.cls != "gpio_controller" else f"struct {n}"


def default_bind(device_spec, backend: str) -> BindSpec:
    b = BindSpec(backend=backend, device=device_spec.name)
    priv = _priv_struct_name(device_spec)
    base_expr = "g->base"
    # find the inferred base bind from the first function that has one
    for fn in device_spec.functions:
        for bd in fn.binds:
            if bd.type == "MmioBase" and bd.from_expr:
                base_expr = bd.from_expr
                break
        if base_expr:
            break

    if backend == "linux":
        b.includes = ["<linux/io.h>", "<linux/platform_device.h>"]
        b.types = [TypeMap("DeviceState", priv), TypeMap("MmioBase", "void __iomem *"),
                   TypeMap("LogicalIRQ", "struct irq_data *"), TypeMap("UInt", "u32")]
        b.primitives = [PrimitiveMap("MmioRead", "B4", "readl"),
                        PrimitiveMap("MmioWrite", "B4", "writel"),
                        PrimitiveMap("MmioRead", "B2", "readw"),
                        PrimitiveMap("MmioWrite", "B2", "writew"),
                        PrimitiveMap("MmioRead", "B1", "readb"),
                        PrimitiveMap("MmioWrite", "B1", "writeb")]
        b.state = [StateMap("dev.base", base_expr)]
        for fn in device_spec.functions:
            if fn.is_callback_entry and fn.callback_table:
                field = fn.callback_table
                # table.field — recover field from role if table is bare "irq_chip"
                f = _field_for_role(fn.role)
                if f:
                    b.callbacks.append(CallbackMap(f"{field}.{f}", fn.name))
            elif fn.role == "probe":
                b.callbacks.append(CallbackMap("platform_driver.probe", fn.name))
            elif fn.role == "remove":
                b.callbacks.append(CallbackMap("platform_driver.remove", fn.name))
    elif backend == "baremetal":
        b.types = [TypeMap("DeviceState", priv), TypeMap("MmioBase", "uintptr_t"),
                   TypeMap("LogicalIRQ", "unsigned int"), TypeMap("UInt", "uint32_t")]
        b.primitives = [PrimitiveMap("MmioRead", "B4", "mmio_read32"),
                        PrimitiveMap("MmioWrite", "B4", "mmio_write32"),
                        PrimitiveMap("MmioRead", "B2", "mmio_read16"),
                        PrimitiveMap("MmioWrite", "B2", "mmio_write16"),
                        PrimitiveMap("MmioRead", "B1", "mmio_read8"),
                        PrimitiveMap("MmioWrite", "B1", "mmio_write8")]
        b.state = [StateMap("dev.base", "dev->base")]
        for fn in device_spec.functions:
            b.exports.append(ExportMap(fn.role, f"{device_spec.name}_{fn.role}"))
    elif backend == "harness":
        b.types = [TypeMap("DeviceState", priv), TypeMap("MmioBase", "uintptr_t"),
                   TypeMap("LogicalIRQ", "unsigned int"), TypeMap("UInt", "uint32_t")]
        b.primitives = [PrimitiveMap("MmioRead", "B4", "harness_read32"),
                        PrimitiveMap("MmioWrite", "B4", "harness_write32")]
        b.state = [StateMap("dev.base", "dev->base")]
    return b


_ROLE_FIELD = {
    "interrupt_ack": "irq_ack", "interrupt_mask": "irq_mask",
    "interrupt_unmask": "irq_unmask", "set_irq_type": "irq_set_type",
    "interrupt_handler": "handle_irq",
}


def _field_for_role(role: str) -> Optional[str]:
    return _ROLE_FIELD.get(role)


# ── minimal .bind parser (round-trip) ────────────────────────────────

def parse(text: str) -> BindSpec:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    header = lines[0].strip()
    m = re.match(r"backend\s+(\w+)\s+for\s+device\s+(\w+)", header)
    if not m:
        raise ValueError("bad .bind header")
    b = BindSpec(backend=m.group(1), device=m.group(2))
    for ln in lines[1:]:
        s = ln.strip()
        if s == "}":
            continue
        if s.startswith("include "):
            b.includes.append(s[len("include "):].strip())
        elif s.startswith("type "):
            mm = re.match(r'type\s+(\w+)\s+->\s+"(.+)"', s)
            if mm:
                b.types.append(TypeMap(mm.group(1), mm.group(2)))
        elif s.startswith("callback "):
            mm = re.match(r"callback\s+([\w.]+)\s*=\s*(\w+)", s)
            if mm:
                b.callbacks.append(CallbackMap(mm.group(1), mm.group(2)))
        elif s.startswith("export "):
            mm = re.match(r'export\s+(\w+)\s+as\s+"(.+)"', s)
            if mm:
                b.exports.append(ExportMap(mm.group(1), mm.group(2)))
        elif s.startswith("map "):
            mm = re.match(r'map\s+([\w.()]+)\s+->\s+"(.+)"', s)
            if mm:
                key = mm.group(1)
                if key.startswith("Mmio"):
                    pm = re.match(r"(MmioRead|MmioWrite)\((\w+)\)", key)
                    if pm:
                        b.primitives.append(PrimitiveMap(pm.group(1), pm.group(2), mm.group(2)))
                else:
                    b.state.append(StateMap(key, mm.group(2)))
    return b
