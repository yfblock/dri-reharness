"""Per-driver extraction stats for reharness (no JSON, reharness-only).

Walks the formal RIS tree (including nested Cond/Seq/Loop) for every driver in
drivers/test/*.c and reports: total ops, distinct register offsets resolved,
RMW ops detected, branch conditions recorded, and register_map size.
"""
from __future__ import annotations
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REHARNESS = os.path.dirname(HERE)
sys.path.insert(0, REHARNESS)

from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402


def _walk_ops(ops, acc):
    """Recurse into Cond/Seq/Loop, yielding leaf RISOp dicts."""
    for op in ops:
        if "Cond" in op:
            _walk_ops(op["Cond"]["then_ops"], acc)
            if op["Cond"].get("else_ops"):
                _walk_ops(op["Cond"]["else_ops"], acc)
            acc["conds"] += 1
        elif "Seq" in op:
            _walk_ops(op["Seq"]["ops"], acc)
        elif "Loop" in op:
            _walk_ops(op["Loop"]["body"], acc)
            acc["conds"] += 1
        else:
            acc["ops"] += 1
            a = _addr(op)
            if a is not None:
                off = _offset(a)
                if off is not None and off != 0:
                    acc["resolved"].add(_key(a))
                if "ReadModifyWrite" in op:
                    acc["rmw"] += 1
                    acc["resolved"].add(_key(a))


def _addr(op):
    for k in ("Read", "Write", "ReadModifyWrite"):
        if k in op:
            return op[k]["addr"]
    return None


def _offset(a):
    if "Symbolic" in a:
        return None  # offset is in register_map, not the addr
    if "Fixed" in a:
        return a["Fixed"]["offset"]
    return None  # Computed → symbolic


def _key(a):
    return repr(a)


def stats(formal: dict) -> dict:
    acc = {"ops": 0, "resolved": set(), "rmw": 0, "conds": 0}
    for m in formal["modules"]:
        _walk_ops(m["ops"], acc)
    return {
        "ops": acc["ops"],
        "resolved": len(acc["resolved"]) + len(formal["register_map"]),
        "rmw": acc["rmw"],
        "conds": acc["conds"],
        "regs": len(formal["register_map"]),
    }


def main():
    drivers_dir = os.path.join(REHARNESS, "drivers", "test")
    drivers = sorted(f for f in os.listdir(drivers_dir) if f.endswith(".c"))

    print(f"{'driver':<20} {'ops':>5} {'resolved':>9} {'RMW':>5} {'conds':>6} {'regs':>6}")
    print("-" * 60)
    tot = {"ops": 0, "resolved": 0, "rmw": 0, "conds": 0, "regs": 0}
    for d in drivers:
        src = os.path.join(drivers_dir, d)
        name = d[:-2]
        try:
            res = extract_ris(ExtractorConfig(source=src))
            s = stats(res.formal)
        except Exception as e:
            print(f"  [error on {d}: {e}]", file=sys.stderr)
            continue
        for k in tot:
            tot[k] += s[k]
        print(f"{name:<20} {s['ops']:>5} {s['resolved']:>9} {s['rmw']:>5} {s['conds']:>6} {s['regs']:>6}")
    print("-" * 60)
    print(f"{'TOTAL':<20} {tot['ops']:>5} {tot['resolved']:>9} {tot['rmw']:>5} {tot['conds']:>6} {tot['regs']:>6}")
    print()
    print("resolved = distinct register accesses with a concrete offset + register_map entries")
    print("regs     = device registers actually accessed (register_map size)")


if __name__ == "__main__":
    main()
