"""Op dataclass and shared classification constants."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


BASE_FIELDS = {"base", "base_addr", "regs", "io_base", "mmio_base",
               "reg_base", "virtbase", "base0", "base1", "ioaddr"}

_CONTROL_KW = {"if", "for", "while", "switch", "return", "sizeof", "typeof"}


@dataclass
class Op:
    kind: str                       # MMIO, state, output, return, or delay op
    addr: dict
    width: int
    value: Optional[str] = None
    condition: Optional[str] = None
    intent: str = "Unknown"
    source_loc: Optional[str] = None
    reg_name: Optional[str] = None  # resolved register macro name (internal)
    line: int = 0
    var: Optional[str] = None       # Read LHS variable (for formal `x := R(...)`)
    cond_stack: list = field(default_factory=list)  # full branch predicate stack
    control_stack: list = field(default_factory=list)  # structured cond/loop frames
    evidence: dict = field(default_factory=dict)    # auditable source provenance
    state_field: Optional[str] = None  # StateRead/StateWrite persistent field
    transaction: dict = field(default_factory=dict)  # typed non-MMIO transfer
