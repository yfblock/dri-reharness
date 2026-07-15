"""Per-driver extraction stats for reharness (no JSON, reharness-only).

Walks the formal RIS tree (including nested Cond/Seq/Loop) for every driver in
drivers/test/*.c and reports: total ops, distinct register offsets resolved,
RMW ops detected, branch conditions recorded, and register_map size.

Multi-driver parallel extraction via multiprocessing (--jobs / -j).
"""
from __future__ import annotations
import os
import sys
import argparse
import multiprocessing
import functools

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


def _extract_one(job):
    """Worker: extract a single driver, return (name, stats_dict or None)."""
    driver_path, alias_mode = job
    name = os.path.basename(driver_path)[:-2]
    try:
        res = extract_ris(ExtractorConfig(source=driver_path, alias_mode=alias_mode))
        return (name, stats(res.formal))
    except Exception as e:
        print(f"  [error on {os.path.basename(driver_path)}: {e}]", file=sys.stderr)
        return (name, None)


def main():
    parser = argparse.ArgumentParser(description="reharness per-driver extraction stats")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="parallel workers (0=auto, default min(cpu_count, num_drivers))")
    parser.add_argument("--alias-mode", choices=["off", "auto", "required"], default="off",
                        help="SVF alias analysis mode (default: off)")
    args = parser.parse_args()

    drivers_dir = os.path.join(REHARNESS, "drivers", "test")
    drivers = sorted(f for f in os.listdir(drivers_dir) if f.endswith(".c"))
    driver_paths = [os.path.join(drivers_dir, d) for d in drivers]

    n_jobs = args.jobs if args.jobs > 0 else min(os.cpu_count() or 1, len(drivers))

    print(f"{'driver':<20} {'ops':>5} {'resolved':>9} {'RMW':>5} {'conds':>6} {'regs':>6}")
    print("-" * 60)

    tot = {"ops": 0, "resolved": 0, "rmw": 0, "conds": 0, "regs": 0}

    if n_jobs <= 1:
        # 串行
        for dp in driver_paths:
            name, s = _extract_one((dp, args.alias_mode))
            if s is None:
                continue
            for k in tot:
                tot[k] += s[k]
            print(f"{name:<20} {s['ops']:>5} {s['resolved']:>9} {s['rmw']:>5} {s['conds']:>6} {s['regs']:>6}")
    else:
        # 多进程并行
        import time
        t0 = time.time()
        with multiprocessing.Pool(n_jobs) as pool:
            results = pool.map(_extract_one,
                               [(dp, args.alias_mode) for dp in driver_paths])
        elapsed = time.time() - t0

        for name, s in results:
            if s is None:
                continue
            for k in tot:
                tot[k] += s[k]
            print(f"{name:<20} {s['ops']:>5} {s['resolved']:>9} {s['rmw']:>5} {s['conds']:>6} {s['regs']:>6}")
        print(f"(并行 {n_jobs} 进程, {elapsed:.1f}s)", file=sys.stderr)

    print("-" * 60)
    print(f"{'TOTAL':<20} {tot['ops']:>5} {tot['resolved']:>9} {tot['rmw']:>5} {tot['conds']:>6} {tot['regs']:>6}")
    print()
    print("resolved = distinct register accesses with a concrete offset + register_map entries")
    print("regs     = device registers actually accessed (register_map size)")


if __name__ == "__main__":
    main()
