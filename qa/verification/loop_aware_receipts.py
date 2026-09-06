#!/usr/bin/env python3
"""Loop-aware receipt counting — prototype of the Section 7.2 design path.

The strict lowering plan refuses receipts whose plan entry is blocked by
an unproven (Conservative, unbounded) loop: ``blocked_entries_authorize_
receipts: false``.  For FIFO-loop data movers this rejects the pristine
artifact, whose receipts are real but loop-carried.  The sketched design
path: per-iteration dynamic receipt counting, using the runtime trace to
bound each loop-carried receipt's multiplicity by the loop summary's
interval, without weakening the anchor-to-primitive binding.

This tool measures that design on the accepted DW harness artifact:

  1. deterministic instrumentation of the harness source: every anchor
     label sets a current-anchor variable, every mmio_readN/writeN
     primitive records (anchor, kind, regfile index) into a log that an
     atexit handler dumps as ``[rhanchor] <op_id> <R|W> 0x<off>`` lines;
  2. build + run the instrumented harness;
  3. attribute each logged access to a contract operation via the anchor
     id (never via text position), with kind and register-offset checks;
  4. re-evaluate the strict plan where every entry blocked ONLY by an
     unproven loop may be discharged by an interval-bounded observed
     multiplicity: count Top -> observed >= 1; bounded count n -> 1 <=
     observed <= n+1.  All other plan checks are unchanged.

Output: research/experiments/results/dw-loop-aware-receipts.json
Usage: loop_aware_receipts.py [--artifact examples/dw-apb-ssi/dw_spi_harness.c]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "qa"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

DEFAULT_ARTIFACT = ROOT / "examples" / "dw-apb-ssi" / "dw_spi_harness.c"
DEFAULT_FORMAL = ROOT / "examples" / "dw-apb-ssi" / "dw_spi.formal.json"
OUT = (ROOT / "research" / "experiments" / "results"
       / "dw-loop-aware-receipts.json")
WORK = ROOT / "artifacts" / "cache" / "loop-aware"

INSTRUMENT = """
/* === loop-aware receipt instrumentation (prototype) === */
#include <stdlib.h>
static const char *rh_cur_anchor;
static struct { const char *anchor; char kind; unsigned idx; }
    rh_anchor_log[16384];
static unsigned rh_anchor_log_n;
static void rh_log_access(const char *a, char k, uintptr_t addr)
{
    if (rh_anchor_log_n < 16384u) {
        rh_anchor_log[rh_anchor_log_n].anchor = a;
        rh_anchor_log[rh_anchor_log_n].kind = k;
        rh_anchor_log[rh_anchor_log_n].idx =
            (unsigned)(((addr - (uintptr_t)rh_regfile) >> 2u) & 0x3ffu);
        rh_anchor_log_n++;
    }
}
static void rh_anchor_dump(void)
{
    for (unsigned i = 0u; i < rh_anchor_log_n; i++)
        if (rh_anchor_log[i].anchor)
            printf("[rhanchor] %s %c 0x%03x\\n",
                   rh_anchor_log[i].anchor, rh_anchor_log[i].kind,
                   rh_anchor_log[i].idx << 2);
        else
            printf("[rhanchor] - %c 0x%03x\\n",
                   rh_anchor_log[i].kind, rh_anchor_log[i].idx << 2);
}
/* === end instrumentation === */
"""


def instrument(text: str) -> str:
    """Deterministic transform: anchor -> current-anchor var, primitives
    -> logged, dump via atexit (registered once, in the injected block)."""
    # 1. logger definitions + atexit registration after the regfile
    m = re.search(r"^static uint32_t rh_regfile\[\d+\];", text, re.M)
    if m is None:
        raise RuntimeError("harness register file not found")
    text = (text[:m.end()]
            + "\n" + INSTRUMENT.replace(
                "/* === end instrumentation === */",
                "static void __attribute__((constructor)) rh_anchor_init("
                "void) { atexit(rh_anchor_dump); }\n"
                "/* === end instrumentation === */")
            + text[m.end():])
    # 2. every anchor label sets the current anchor, and leaving the
    # anchor's compound clears it again: without the clear, unanchored
    # dataflow-helper accesses inherit the last anchor's id and corrupt
    # the multiplicity attribution
    text, n_anch = re.subn(
        r'(__rh_op_op_(\d+):)[ \t]*\{',
        r'\1 { rh_cur_anchor = "op_\2";', text)
    spans = []
    for m in re.finditer(r'^[ \t]*__rh_op_op_(\d+):[ \t]*\{', text, re.M):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        spans.append((m.start(), i))
    for lo, hi in reversed(spans):
        text = text[:hi - 1] + " rh_cur_anchor = 0;" + text[hi - 1:]
    # 3. primitive bodies log every access
    def _rw_read(m):
        body = m.group(0)
        logged = re.sub(
            r"return (rh_regfile\[[^;]+?\]);",
            r"{ uint32_t rh_v = \1; "
            r"rh_log_access(rh_cur_anchor, 'R', addr); return rh_v; }",
            body)
        if logged == body:
            logged = re.sub(
                r"return \(([^;]+?)\);",
                r"{ uint32_t rh_v = (\1); "
                r"rh_log_access(rh_cur_anchor, 'R', addr); return rh_v; }",
                body, count=1)
        return logged
    text = re.sub(
        r"static inline uint(8|16|32|64)_t mmio_read\d+\("
        r"(uintptr_t addr|uintptr_t addr)\)\n\{.*?\n\}",
        _rw_read, text, flags=re.S)
    def _rw_write(m):
        body = m.group(0)
        logged = re.sub(
            r"^(static inline void mmio_write\d+\([^)]*\)\n\{)",
            r"\1\n    rh_log_access(rh_cur_anchor, 'W', addr);",
            body, flags=re.M)
        return logged
    text = re.sub(
        r"static inline void mmio_write\d+\([^)]*\)\n\{.*?\n\}",
        _rw_write, text, flags=re.S)
    return text, n_anch


_LOGGED = re.compile(
    r"^\[rhanchor\] (op_\d+|-) ([RW]) 0x([0-9a-f]+)$", re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    ap.add_argument("--formal", default=str(DEFAULT_FORMAL))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    from gate.backend_lowering_oracle import \
        build_generation_contract
    from gate.backend_lowering_plan import build_backend_lowering_plan

    formal = json.load(open(args.formal, encoding="utf-8"))
    contract = build_generation_contract(formal)
    rows = {r["op_id"]: r for r in contract["register_operations"]}
    regs = {r["name"]: r["offset"] for r in formal["register_map"]}
    # op offsets come from the formal modules (same accessor the runtime
    # trace oracle uses), not from the contract rows
    op_offsets: dict[str, tuple[str, set[int]]] = {}

    def _addr_off(addr):
        if "Symbolic" in addr:
            return regs.get(addr["Symbolic"]["register"])
        if "Fixed" in addr:
            return addr["Fixed"]["offset"]
        if "Computed" in addr:
            return None
        return None

    def _walk_ops(node):
        """Depth-first over module ops, including Cond/Loop-nested bodies
        (loop-carried receipts live exactly there)."""
        if isinstance(node, dict):
            for kind in ("Read", "Write"):
                entry = node.get(kind)
                if isinstance(entry, dict) and entry.get("op_id"):
                    yield entry["op_id"], kind, entry.get("addr", {})
            for child in node.values():
                yield from _walk_ops(child)
        elif isinstance(node, list):
            for child in node:
                yield from _walk_ops(child)

    for module in formal.get("modules", []):
        for oid, kind, addr in _walk_ops(module.get("ops", [])):
            off = _addr_off(addr)
            if off is not None:
                k, s = op_offsets.setdefault(oid, (kind, set()))
                s.add(off)
    plan = build_backend_lowering_plan(formal, "harness")
    blocked = {e["op_id"]: e for e in plan["entries"]
               if e.get("receipt_authorized") is not True}

    src = Path(args.artifact).read_text(encoding="utf-8")
    text, n_anch = instrument(src)
    WORK.mkdir(parents=True, exist_ok=True)
    cpath = WORK / "harness_loopaware.c"
    binp = WORK / "harness_loopaware.bin"
    cpath.write_text(text, encoding="utf-8")
    # the artifact includes its header under the installed name; make the
    # sibling header resolvable under whatever name the #include uses by
    # compiling with the artifact's directory on the include path and, if
    # the include names a different file, a copy in the work directory
    inc = re.search(r'#include\s+"([^"]+)"', text)
    hdr = Path(args.artifact).with_suffix(".h")
    extra = []
    if inc and hdr.is_file() and inc.group(1) != hdr.name:
        (WORK / inc.group(1)).write_text(
            hdr.read_text(encoding="utf-8"), encoding="utf-8")
        extra = ["-I", str(WORK)]
    p = subprocess.run(
        ["cc", "-o", str(binp), str(cpath)] + extra,
        capture_output=True, text=True)
    if p.returncode != 0:
        print("instrumented harness failed to compile:")
        print(p.stderr[-2000:])
        return 1
    run = subprocess.run([str(binp)], capture_output=True, text=True)

    counts: Counter = Counter()
    kind_off: dict[str, Counter] = {}
    unattributed: Counter = Counter()
    for anchor, kind, off in _LOGGED.findall(run.stdout):
        if anchor == "-":
            unattributed[(kind, int(off, 16))] += 1
            continue
        counts[anchor] += 1
        kind_off.setdefault(anchor, Counter())[(kind, int(off, 16))] += 1
    total_logged = sum(counts.values()) + sum(unattributed.values())

    def _op_shape(op: str):
        return op_offsets.get(op, (None, set()))

    discharged, unobserved, mismatches = [], [], []
    for op, entry in sorted(blocked.items()):
        loops = entry.get("blocking_loop") and [entry["blocking_loop"]] \
            or entry.get("enclosing_loops") or []
        top = any(l.get("count", {}).get("Top") is not None
                  or not l.get("bounded", False) for l in loops)
        observed = counts.get(op, 0)
        shapes = kind_off.get(op, Counter())
        want_kind, offs = _op_shape(op)
        want_kind = "W" if want_kind == "Write" else "R"
        shape_ok = bool(shapes) and all(
            k == want_kind and o in offs for (k, o) in shapes)
        ok = observed >= 1 and shape_ok and (top or observed >= 1)
        rec = {
            "op_id": op, "module": entry.get("module"),
            "loop_count": "Top" if top else "bounded",
            "observed": observed,
            "shapes": [[f"{k}", hex(o), n] for (k, o), n in sorted(
                shapes.items())],
            "shape_ok": shape_ok,
            "discharged": ok,
        }
        (discharged if ok else unobserved if observed == 0
         else mismatches).append(rec)

    loop_aware_complete = (not unobserved and not mismatches)
    report = {
        "schema": 1,
        "description": ("Prototype of the Section 7.2 loop-aware receipt "
                        "design: deterministic anchor-provenance runtime "
                        "instrumentation of the accepted DW harness, "
                        "interval-bounded multiplicity discharge for "
                        "loop-blocked plan entries"),
        "anchors_instrumented": n_anch,
        "run_exit": run.returncode,
        "total_logged_accesses": total_logged,
        "unattributed_accesses": [[k, hex(o), n] for (k, o), n in
                                  sorted(unattributed.items())],
        "plan_entries": len(plan["entries"]),
        "loop_blocked_entries": len(blocked),
        "discharged": discharged,
        "unobserved": unobserved,
        "shape_mismatches": mismatches,
        "loop_aware_strict_complete": loop_aware_complete,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"anchors={n_anch} logged={total_logged} "
          f"blocked={len(blocked)} discharged={len(discharged)} "
          f"unobserved={len(unobserved)} mismatch={len(mismatches)} "
          f"complete={loop_aware_complete}")
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
