"""Intent annotation — improved over driver-harness's address-string heuristic.

Uses the *resolved register macro name* (reg_name, available because macros
are now properly expanded) instead of the address string. So GPIO_INT_EN
→ Interrupt, GPIO_DIR → Config, etc. Falls back to driver-harness's keyword
rules on the address/base string when no macro name is available.
"""
from __future__ import annotations
from .dataflow import Op


def _contains_any(text: str, keywords: list[str]) -> bool:
    up = text.upper()
    return any(k in up for k in keywords)


def annotate(op: Op, func_name: str):
    if op.intent and op.intent != "Unknown":
        return  # already set (e.g. Delay → Synchronization)

    func_upper = func_name.upper()
    is_irq = any(k in func_upper for k in ("IRQ", "HANDLER", "ACK", "MASK", "UNMASK", "SET_IRQ_TYPE"))
    is_remove = any(k in func_upper for k in ("REMOVE", "SHUTDOWN", "SUSPEND"))

    # prefer the resolved register macro name
    name_text = (op.reg_name or "")
    addr_text = _addr_search_string(op)
    search = (name_text + " " + addr_text).upper()
    value_text = (op.value or "").upper()
    is_zero_val = value_text in ("0", "0X0", "0X00", "0X00000000")

    if is_irq and _contains_any(search, ["INT", "IRQ", "CLR", "MASK", "EN"]):
        op.intent = "Interrupt"; return
    if _contains_any(search, ["POWER", "PM", "SUSPEND", "CLK", "CLOCK"]):
        op.intent = "Power"; return
    if is_remove and is_zero_val:
        op.intent = "Power"; return
    if _contains_any(search, ["INIT", "RESET", "SOFT_RESET"]):
        op.intent = "Init"; return
    if op.kind == "Write" and is_zero_val and not is_irq:
        op.intent = "Init"; return
    if op.kind == "Read" and _contains_any(search, ["STATUS", "STAT", "FLAG", "RAW", "MASKED"]):
        op.intent = "Status"; return
    if _contains_any(search, ["INT", "IRQ"]):
        op.intent = "Interrupt"; return
    if _contains_any(search, ["DATA", "FIFO", "BUFFER", "TX", "RX", "SET", "CLR"]):
        if "TX" in search or "RX" in search or "DATA" in search or "FIFO" in search:
            op.intent = "DataTransfer"; return
    if _contains_any(search, ["CONFIG", "MODE", "CTRL", "DIR", "PULL", "DEBOUNCE", "TYPE", "EDGE", "LEVEL", "PRESCALE"]):
        op.intent = "Config"; return
    if _contains_any(search, ["DOORBELL", "NOTIFY", "READY"]):
        op.intent = "Synchronization"; return

    # fallback
    op.intent = "Status" if op.kind == "Read" else "Config"


def _addr_search_string(op: Op) -> str:
    a = op.addr
    if "Fixed" in a:
        return f"0x{a['Fixed']:X}"
    if "Offset" in a:
        b = a["Offset"]
        return b.get("base", "").upper() + (f" + 0x{b['offset']:X}" if b.get("offset") else "")
    if "Indirect" in a:
        b = a["Indirect"]
        return b.get("base_reg", "").upper() + (f" + 0x{b['offset']:X}" if b.get("offset") else "")
    return ""
