#!/usr/bin/env python3
"""Merge evidence-mode experiment logs into one paired analysis table.

Reads the per-run logs (each line a JSON row or a checkpoint marker)
plus the final results.json of each phase, dedups by (driver, mode)
keeping the LAST completed row, and prints:
  - per-mode pass rates over completed cells
  - per-driver paired table (full vs ris_only vs ris_semantics)
  - LLM effort accounting when present

Usage: python3 tools/eval_evidence_merge.py <log1> [log2 ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MODES = ("full", "ris_only", "ris_semantics")


def rows_from_file(path: str):
    out = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("driver") and row.get("mode"):
            out.append(row)
    return out


def main(argv: list[str]) -> int:
    rows = []
    for path in argv[1:]:
        p = Path(path)
        if p.suffix == ".json":
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows.extend(r for r in doc.get("results", [])
                        if isinstance(r, dict))
        else:
            rows.extend(rows_from_file(str(p)))
    # last completed row per (driver, mode) wins
    by_cell: dict[tuple[str, str], dict] = {}
    for r in rows:
        by_cell[(r["driver"], r["mode"])] = r

    done = [r for r in by_cell.values() if "error" not in r]
    errs = [r for r in by_cell.values() if "error" in r]
    print(f"cells: {len(by_cell)} recorded, {len(done)} completed, "
          f"{len(errs)} error")

    print(f"\n== pass rates over {len(done)} completed cells ==")
    print(f"{'mode':15s} {'n':>3s} {'compiled':>9s} {'lowering':>9s} "
          f"{'ast':>6s} {'trace':>6s} {'sec(med)'}")
    for mode in MODES:
        rs = [r for r in done if r.get("mode") == mode]
        if not rs:
            continue
        def rate(key):
            return sum(1 for r in rs if r.get(key) is True)
        secs = sorted(r.get("seconds") or 0 for r in rs)
        med = secs[len(secs) // 2] if secs else 0
        print(f"{mode:15s} {len(rs):>3d} {rate('compiled'):>9d} "
              f"{rate('lowering_complete'):>9d} "
              f"{rate('ast_leaf_complete'):>6d} {rate('trace_passed'):>6d} "
              f"{med:.0f}")

    drivers = sorted({d for d, _ in by_cell})
    print("\n== paired per-driver (C=compiled L=lowering A=ast T=trace) ==")
    print(f"{'driver':18s} " + " ".join(f"{m:>16s}" for m in MODES))
    for d in drivers:
        cells = []
        for m in MODES:
            r = by_cell.get((d, m))
            if r is None:
                cells.append(" " * 16)
            elif "error" in r:
                cells.append(f"{'ERR':>16s}")
            else:
                marks = "".join(x if r.get(k) is True else "."
                                for x, k in zip("CLAT",
                                ("compiled", "lowering_complete",
                                 "ast_leaf_complete", "trace_passed")))
                cells.append(f"{marks:>7s} {str(r.get('seconds',''))[:8]:>8s}")
        print(f"{d:18s} " + " ".join(cells))

    if errs:
        print("\n== error cells ==")
        for r in sorted(errs, key=lambda r: (r["driver"], r["mode"])):
            print(f"  {r['driver']:16s} {r['mode']:15s} {r['error'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
