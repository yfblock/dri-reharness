"""Mechanical scaffold for the harness backend.

Everything the generated program needs that does NOT depend on the
driver's semantics is emitted here deterministically: includes, generic
kernel-macro stubs, register-offset defines (from the formal's register
map), the MMIO backing window, and the bind's primitive implementations.
The primitives self-trace (one `[trace n] R|W 0x... = 0x...` line per
call, offset reported in backing-window coordinates, which equals the
device-relative register offset because every base member points at
`rh_mmio_backing`), so the LLM never emits trace printfs and cannot
forget one.  Raw readers (`rh_raw_read*`) exist for read-modify-write
value expressions: they touch the same window but do not trace, because
the trace oracle counts an RMW op as a Write only.

Emitting this mechanically removes roughly a third of the LLM's output
tokens per driver and removes an entire failure class (malformed stubs,
forgotten trace lines) from generation.
"""
from __future__ import annotations

_CTYPE = {"B1": "unsigned char", "B2": "unsigned short", "B4": "unsigned int",
          "B8": "unsigned long long"}

_HEAD = """\
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define BIT(nr)                     (1UL << (nr))
#define BITS_PER_LONG               (8u * sizeof(unsigned long))
#define GENMASK(h, l)               ((((~0UL) << (l)) & (~0UL >> (BITS_PER_LONG - 1u - (h)))))
#define ARRAY_SIZE(x)               (sizeof(x) / sizeof((x)[0]))

typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
"""

_BACKING = """\
/* Backed MMIO window: every primitive lands in this array (address is
   windowed, never dereferenced raw), so a NULL or 0 base still reads
   and writes real memory. */
static unsigned char rh_mmio_backing[65536];
static unsigned long rh_trace_count;
"""


def _window_deref(ctype: str, mutable: bool = False) -> str:
    qual = "volatile " + ("" if mutable else "const ")
    return (f"*({qual}{ctype} *)(void *)(rh_mmio_backing + (addr & 0xffffu))")


def _trace(direction: str, ctype: str, value_expr: str = "v") -> str:
    return (f'printf("[trace %lu] {direction} 0x%03lx = 0x%08x\\n", '
            f'rh_trace_count++, '
            f'(unsigned long)((addr - (uintptr_t)rh_mmio_backing) '
            f'& 0xffffu), ({ctype}){value_expr});')


def _primitive_c(op: str, width: str, symbol: str) -> str | None:
    """C definition of one bind primitive, or None for unmapped ops."""
    ctype = _CTYPE.get(width)
    if ctype is None:
        return None
    base_op = op.removesuffix("BE")
    be = op.endswith("BE") or symbol.endswith("be")
    ro = _window_deref(ctype)
    rw = _window_deref(ctype, mutable=True)
    bswap = {"B1": "8", "B2": "16", "B4": "32", "B8": "64"}[width]
    if base_op == "MmioRead":
        fetch = f"({ctype})__builtin_bswap{bswap}({ro})" if be else ro
        return (f"static {ctype} {symbol}(uintptr_t addr)\n{{\n"
                f"    {ctype} v = {fetch};\n"
                f"    {_trace('R', ctype)}\n"
                f"    return v;\n}}")
    if base_op == "MmioWrite":
        store = (f"{rw} = ({ctype})__builtin_bswap{bswap}(value);"
                 if be else f"{rw} = value;")
        return (f"static void {symbol}({ctype} value, uintptr_t addr)\n{{\n"
                f"    {store}\n"
                f"    {_trace('W', ctype, 'value')}\n}}")
    if base_op == "MmioWriteW1C":
        # write-1-to-clear: new = old & ~value; one W trace (the op is a
        # Write for the oracle; the internal read must stay untraced)
        return (f"static void {symbol}({ctype} value, uintptr_t addr)\n{{\n"
                f"    {ctype} v = ({ctype})({ro} & ({ctype})~value);\n"
                f"    {rw} = v;\n"
                f"    {_trace('W', ctype)}\n}}")
    return None


def _raw_helpers() -> str:
    """Untraced windowed reads for RMW value expressions."""
    out = ["/* Untraced raw reads: RMW value expressions read the current"
           "\n   register value through these (never a traced primitive —"
           "\n   the op's trace letter is the Write only). */"]
    for width in ("B1", "B2", "B4"):
        ctype = _CTYPE[width]
        out.append(
            f"static inline {ctype} rh_raw_read{width[1]}(uintptr_t addr)\n"
            "{\n"
            f"    return {_window_deref(ctype)};\n"
            "}")
    return "\n".join(out)


def _register_defines(formal: dict) -> str:
    """#define per register_map entry, source order, deduped by name.

    Case-insensitive dedup: two names differing only in case would both
    expand in the same expression position and shadow each other.
    """
    seen: set[str] = set()
    out = ["/* Register offsets (from the device register map) */"]
    for item in formal.get("register_map", []):
        name = item.get("name", "")
        offset = item.get("offset")
        if not name or offset is None:
            continue
        if not name.isidentifier() or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append("#define %-32s 0x%xu" % (name, int(offset)))
    return "\n".join(out) if len(out) > 1 else ""


def emit_scaffold(formal: dict, bind) -> str:
    """Full mechanical scaffold text (part 00 of the generated file)."""
    prims = [_primitive_c(p.op, p.width, p.concrete)
             for p in getattr(bind, "primitives", None) or []]
    return "\n\n".join(part for part in [
        _HEAD,
        _register_defines(formal),
        _BACKING,
        "\n\n".join(c for c in prims if c),
        _raw_helpers(),
    ] if part)


def summary(formal: dict, bind) -> str:
    """Compact prompt note of what part 00 provides (no full echo — the
    register names/offsets already travel in evidence.registers and the
    primitive names in bind.primitives)."""
    prims = ", ".join(p.concrete for p in bind.primitives) or "(none)"
    regs = len(formal.get("register_map") or [])
    return (
        "- the includes (stdint.h, stdio.h, string.h, errno.h), the kernel "
        "macros BIT/GENMASK/ARRAY_SIZE/BITS_PER_LONG and the u8/u16/u32 "
        "typedefs;\n"
        f"- `#define <NAME> <offset>u` for all {regs} registers of "
        "evidence.registers (same names — use them directly in address "
        "expressions);\n"
        "- the MMIO backing window `static unsigned char "
        "rh_mmio_backing[65536]` and the trace counter;\n"
        f"- implementations of every bind primitive ({prims}): each call "
        "windows its address into rh_mmio_backing and prints its own "
        "trace line;\n"
        "- the untraced raw readers rh_raw_read1/2/4.")
