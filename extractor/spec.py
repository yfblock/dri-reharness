"""Formal core IR: FunctionSpec, DeviceSpec, Effect, Binding (plan M2/M4/M5).

Backend-independent device/function semantics. Lowered from RIS by spec_infer,
serialized to/from `.dspec`. Code generators consume (RIS, DeviceSpec, bind).

  FunctionSpec = (Signature, Role, Context, Requires, Ensures, Effects, RISRef)
  DeviceSpec   = (State, Resources, Registers, Functions, Invariants, Class)
  Effect       = RegEffect | StateEffect | ResourceEffect | EventEffect
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


# ── enums ────────────────────────────────────────────────────────────

ROLES = [
    "probe", "remove", "reset", "init", "suspend", "resume",
    "interrupt_ack", "interrupt_mask", "interrupt_unmask", "set_irq_type",
    "interrupt_handler", "read_config", "write_config",
    "setup_queue", "notify", "get_status", "set_status",
    "helper", "unknown",
]

CONTEXTS = ["thread", "irq", "atomic", "sleepable", "boot"]

# abstract types (backend-independent; .bind maps them to concrete types)
TYPES = [
    "DeviceState", "MmioBase", "LogicalIRQ", "UInt", "Bool", "Register",
    "Clock", "DmaRegion", "Queue", "Status", "Void",
]


# ── signature / binding ──────────────────────────────────────────────

@dataclass
class Param:
    name: str
    type: str                 # abstract type, e.g. "LogicalIRQ"
    from_expr: Optional[str] = None   # source expression it binds to (for infer)


@dataclass
class Signature:
    params: list[Param] = field(default_factory=list)
    return_type: str = "Void"


@dataclass
class Binding:
    """Abstract value bound to device state or a source expression.

    `bind dev: DeviceState from irq.owner` → name=dev, type=DeviceState,
    from_expr="irq.owner".
    """
    name: str
    type: str
    from_expr: Optional[str] = None


# ── effects ──────────────────────────────────────────────────────────

@dataclass
class Effect:
    kind: str                 # reg | state | resource | event
    text: str                 # human-readable effect, e.g. "clears_interrupt(line)"
    detail: dict = field(default_factory=dict)


def reg_effect(register: str) -> Effect:
    return Effect("reg", f"writes_register({register})", {"register": register})


def event_effect(text: str) -> Effect:
    return Effect("event", text, {})


def state_effect(text: str) -> Effect:
    return Effect("state", text, {})


# ── FunctionSpec ─────────────────────────────────────────────────────

@dataclass
class FunctionSpec:
    name: str
    signature: Signature = field(default_factory=Signature)
    role: str = "unknown"
    context: str = "thread"
    source: Optional[str] = None          # "path:line"
    binds: list[Binding] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)   # precondition text
    ensures: list[str] = field(default_factory=list)    # postcondition text
    effects: list[Effect] = field(default_factory=list)
    ris_ref: Optional[str] = None         # linked RIS module name
    is_callback_entry: bool = False       # registered via function pointer
    callback_table: Optional[str] = None  # e.g. "irq_chip.irq_ack"

    def display(self, indent: int = 0) -> str:
        pad = "  " * indent
        params = ", ".join(f"{p.name}: {p.type}" for p in self.signature.params) or ""
        ret = self.signature.return_type
        lines = [f"{pad}function {self.name}({params}) -> {ret} {{"]
        lines.append(f"{pad}  role {self.role}")
        if self.source:
            lines.append(f'{pad}  source "{self.source}"')
        lines.append(f"{pad}  context {self.context}")
        if self.is_callback_entry and self.callback_table:
            lines.append(f"{pad}  callback {self.callback_table}")
        for b in self.binds:
            fstr = f" from {b.from_expr}" if b.from_expr else ""
            lines.append(f"{pad}  bind {b.name}: {b.type}{fstr}")
        for r in self.requires:
            lines.append(f"{pad}  require {r}")
        if self.ris_ref:
            lines.append(f"{pad}  ris {self.ris_ref}")
        for e in self.effects:
            lines.append(f"{pad}  effect {e.text}")
        for en in self.ensures:
            lines.append(f"{pad}  ensure {en}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)


# ── DeviceSpec ───────────────────────────────────────────────────────

@dataclass
class StateField:
    name: str
    type: str
    bind: Optional[str] = None   # source field it maps to, e.g. "g->base"


@dataclass
class Resource:
    name: str
    type: str                    # MmioResource | ClockResource | IrqResource | ...
    required: bool = True
    bind: Optional[str] = None


@dataclass
class RegisterDesc:
    name: str
    width: str                   # B1 | B2 | B4 | B8
    offset: int
    base: str = "base"


@dataclass
class DeviceSpec:
    name: str
    cls: str = "generic_mmio"    # gpio_controller | clock | virtio_mmio | ahci | ...
    state: list[StateField] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    registers: list[RegisterDesc] = field(default_factory=list)
    functions: list[FunctionSpec] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    source: Optional[str] = None

    def display(self) -> str:
        lines = [f"device {self.name} {{"]
        lines.append(f"  class {self.cls}")
        if self.source:
            lines.append(f'  source "{self.source}"')
        if self.state:
            lines.append("  state {")
            for s in self.state:
                b = f" bind {s.bind}" if s.bind else ""
                lines.append(f"    {s.name}: {s.type}{b}")
            lines.append("  }")
        for r in self.resources:
            b = f" bind {r.bind}" if r.bind else ""
            lines.append(f"  resource {r.name}: {r.type} {{ required {str(r.required).lower()}{b} }}")
        for reg in self.registers:
            lines.append(f"  register {reg.name}: {reg.width} at {reg.base} + 0x{reg.offset:x}")
        for inv in self.invariants:
            lines.append(f"  invariant {inv}")
        for fn in self.functions:
            lines.append(fn.display(indent=1))
        lines.append("}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# .bind — backend binding (consolidated from bind.py per plan ownership)
# ═══════════════════════════════════════════════════════════════════
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
                        PrimitiveMap("MmioWrite", "B1", "writeb"),
                        PrimitiveMap("MmioReadBE", "B2", "ioread16be"),
                        PrimitiveMap("MmioWriteBE", "B2", "iowrite16be"),
                        PrimitiveMap("MmioReadBE", "B4", "ioread32be"),
                        PrimitiveMap("MmioWriteBE", "B4", "iowrite32be")]
        b.state = [StateMap("dev.base", base_expr)]
        for fn in device_spec.functions:
            if fn.is_callback_entry and fn.callback_table:
                if "." in fn.callback_table:
                    b.callbacks.append(CallbackMap(fn.callback_table, fn.name))
                else:
                    f = _field_for_role(fn.role)
                    if f:
                        b.callbacks.append(CallbackMap(
                            f"{fn.callback_table}.{f}", fn.name))
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
                        PrimitiveMap("MmioWrite", "B1", "mmio_write8"),
                        PrimitiveMap("MmioReadBE", "B2", "mmio_read16be"),
                        PrimitiveMap("MmioWriteBE", "B2", "mmio_write16be"),
                        PrimitiveMap("MmioReadBE", "B4", "mmio_read32be"),
                        PrimitiveMap("MmioWriteBE", "B4", "mmio_write32be")]
        b.state = [StateMap("dev.base", "dev->base")]
        for fn in device_spec.functions:
            b.exports.append(ExportMap(fn.role, f"{device_spec.name}_{fn.role}"))
    elif backend == "harness":
        b.types = [TypeMap("DeviceState", priv), TypeMap("MmioBase", "uintptr_t"),
                   TypeMap("LogicalIRQ", "unsigned int"), TypeMap("UInt", "uint32_t")]
        b.primitives = [PrimitiveMap("MmioRead", "B4", "harness_read32"),
                        PrimitiveMap("MmioWrite", "B4", "harness_write32"),
                        PrimitiveMap("MmioRead", "B2", "harness_read16"),
                        PrimitiveMap("MmioWrite", "B2", "harness_write16"),
                        PrimitiveMap("MmioRead", "B1", "harness_read8"),
                        PrimitiveMap("MmioWrite", "B1", "harness_write8"),
                        PrimitiveMap("MmioReadBE", "B2", "harness_read16be"),
                        PrimitiveMap("MmioWriteBE", "B2", "harness_write16be"),
                        PrimitiveMap("MmioReadBE", "B4", "harness_read32be"),
                        PrimitiveMap("MmioWriteBE", "B4", "harness_write32be")]
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


# ═══════════════════════════════════════════════════════════════════
# .facts — source-derived facts for LLM-assisted synthesis (plan M9)
# Backend-independent reconstruction hints that should NOT pollute .dspec:
# includes, structs/fields, constants, callback tables, resource acquisition,
# error paths, subsystem idioms.
# ═══════════════════════════════════════════════════════════════════
@dataclass
class StructField:
    name: str
    ctype: str


@dataclass
class StructDef:
    name: str
    fields: list[StructField] = field(default_factory=list)


@dataclass
class ResourceFact:
    name: str                 # mmio0, clk0, irq0
    acquisition: str          # e.g. "devm_platform_ioremap_resource(pdev, 0)"
    binds_to: Optional[str] = None   # e.g. "g->base"


@dataclass
class FactsSpec:
    source: str
    includes: list[str] = field(default_factory=list)
    structs: list[StructDef] = field(default_factory=list)
    constants: dict = field(default_factory=dict)   # name -> int value
    callbacks: dict = field(default_factory=dict)   # "irq_chip.irq_ack" -> fn
    resources: list[ResourceFact] = field(default_factory=list)
    error_paths: list[str] = field(default_factory=list)      # e.g. "return -ENOMEM"
    helper_calls: list[str] = field(default_factory=list)     # notable subsystem calls
    source_snippets: dict = field(default_factory=dict)       # outline name -> [calls]

    def display(self) -> str:
        lines = [f"source: {self.source}"]
        if self.includes:
            lines.append("includes:")
            for inc in self.includes:
                lines.append(f"  - {inc}")
        if self.structs:
            lines.append("structs:")
            for st in self.structs:
                lines.append(f"  {st.name}:")
                lines.append("    fields:")
                for f in st.fields:
                    lines.append(f"      {f.name}: \"{f.ctype}\"")
        if self.constants:
            lines.append("constants:")
            for k, v in self.constants.items():
                lines.append(f"  {k}: {v if isinstance(v, str) else hex(v)}")
        if self.callbacks:
            lines.append("callbacks:")
            for k, v in self.callbacks.items():
                lines.append(f"  {k}: {v}")
        if self.resources:
            lines.append("resources:")
            for r in self.resources:
                lines.append(f"  {r.name}:")
                lines.append(f"    acquisition: \"{r.acquisition}\"")
                if r.binds_to:
                    lines.append(f"    binds_to: \"{r.binds_to}\"")
        if self.error_paths:
            lines.append("error_paths:")
            for e in self.error_paths:
                lines.append(f"  - \"{e}\"")
        if self.helper_calls:
            lines.append("helper_calls:")
            for h in self.helper_calls:
                lines.append(f"  - \"{h}\"")
        if self.source_snippets:
            lines.append("source_snippets:")
            for k, calls in self.source_snippets.items():
                lines.append(f"  {k}:")
                for c in calls:
                    lines.append(f"    - \"{c}\"")
        return "\n".join(lines)


# ── multi-backend .bind (merged file, recom.md §"Merge Backend Bind Files") ──

def display_bind_set(binds: list[BindSpec]) -> str:
    """Emit multiple backend blocks into one .bind file."""
    return "\n\n".join(b.display() for b in binds)


def parse_bind_set(text: str) -> list[BindSpec]:
    """Parse a merged .bind file containing multiple `backend ...` blocks."""
    blocks = re.split(r"\n(?=backend\s+\w+\s+for\s+device\s+\w+)", text)
    out = []
    for b in blocks:
        b = b.strip()
        if b.startswith("backend "):
            out.append(parse(b))
    return out
