"""Formal core IR: FunctionSpec, DeviceSpec, Effect, Binding (plan M2/M4/M5).

Backend-independent device/function semantics. Lowered from RIS by spec_infer,
serialized to/from `.dspec`. Code generators consume (RIS, DeviceSpec, bind).

  FunctionSpec = (Signature, Role, Context, Requires, Ensures, Effects, RISRef)
  DeviceSpec   = (State, Resources, Registers, Functions, Invariants, Class)
  Effect       = RegEffect | StateEffect | ResourceEffect | EventEffect
"""
from __future__ import annotations
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
