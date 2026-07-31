"""Abstract value domain + taint labels for flow-sensitive dataflow.

AbsVal variants:
  BasePtr(base:str)        — pointer from ioremap/devm_ioremap (MMIO base), taint source
  Offset(base:str, off:int, reg_name:str|None) — base + constant offset (resolved register)
  ReadTaint(addr:RegAddr, reg_name:str|None)   — value loaded by readl(addr)
  Const(n:int)             — integer literal / resolved macro constant
  SymExpr(text:str)        — symbolic expression (BIT(n), variable, mask)
  Top                      — unknown

RegAddr (compatible with driver-harness ir::RegAddr, externally-tagged serde):
  ("Fixed", n)
  ("Offset", {"base": ..., "offset": n})
  ("Indirect", {"base_reg": ..., "offset": n})
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Union


# ── RegAddr (mirrors driver-harness src/ir/mod.rs) ──────────────────

def addr_fixed(n: int) -> dict:
    return {"Fixed": int(n)}


def addr_offset(base: str, offset: int) -> dict:
    return {"Offset": {"base": base, "offset": int(offset)}}


def addr_indirect(base_reg: str, offset: int, expr: str | None = None) -> dict:
    out = {"base_reg": base_reg, "offset": int(offset)}
    if expr:
        out["expr"] = expr
    return {"Indirect": out}


def addr_offset_of(a: dict) -> Optional[int]:
    if "Offset" in a:
        return a["Offset"]["offset"]
    if "Indirect" in a:
        return a["Indirect"]["offset"]
    if "Fixed" in a:
        return a["Fixed"]
    return None


def addr_base_of(a: dict) -> Optional[str]:
    if "Offset" in a:
        return a["Offset"]["base"]
    if "Indirect" in a:
        return a["Indirect"]["base_reg"]
    return None


def addr_equal(a: dict, b: dict) -> bool:
    return a == b


# ── Abstract values ──────────────────────────────────────────────────

@dataclass
class BasePtr:
    base: str  # e.g. "g->base"


@dataclass
class Offset:
    base: str
    off: int
    reg_name: Optional[str] = None


@dataclass
class ReadTaint:
    addr: dict
    reg_name: Optional[str] = None


@dataclass
class Const:
    n: int


@dataclass
class SymExpr:
    text: str


@dataclass
class Top:
    pass


AbsVal = Union[BasePtr, Offset, ReadTaint, Const, SymExpr, Top]


def val_to_regaddr(v: AbsVal) -> Optional[dict]:
    """If v denotes an MMIO address, return its RegAddr."""
    if isinstance(v, BasePtr):
        return addr_offset(v.base, 0)
    if isinstance(v, Offset):
        return addr_offset(v.base, v.off)
    if isinstance(v, Const):
        return addr_fixed(v.n)
    return None


def val_to_value_str(v: AbsVal) -> Optional[str]:
    """Render an AbsVal as the RIS `value` string (for Write ops)."""
    if isinstance(v, Const):
        return hex(v.n) if v.n >= 0 else None
    if isinstance(v, SymExpr):
        return v.text
    if isinstance(v, ReadTaint):
        return None  # read result, not a literal
    if isinstance(v, Offset):
        return None
    if isinstance(v, BasePtr):
        return None
    return None
