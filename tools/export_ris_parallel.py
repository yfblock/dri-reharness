#!/usr/bin/env python3
"""Export RIS for many drivers in parallel.

Each driver runs in its own `python -m extractor extract` subprocess, so
libclang crashes, clang failures, or a hung extraction cannot take down
siblings, and the per-driver outputs never share a path.  Processes are
independent: the only shared state is the read-only kernel tree, and IR
intermediates land in per-process tempdirs (ir_primary.py), so N-way
concurrency is safe up to memory.

Default corpus: benchmarks/drivers/baseline/*.c (the 19 single-source
evaluation drivers).  --multisource adds the JSON manifests under
benchmarks/drivers/multisource/.  --source accepts explicit files or
manifests.

Usage:
  python3 tools/export_ris_parallel.py [--jobs N] [--multisource]
      [--out DIR] [--timeout SEC] [--ir-mode auto|off|required]
      [--drivers name ...] [--source FILE ...]

Outputs: <out>/<driver>/<driver>.ris (+ extract.log) and
<out>/summary.json.  Exit 0 only if every driver exported.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "benchmarks" / "drivers" / "baseline"
MULTISOURCE_DIR = ROOT / "benchmarks" / "drivers" / "multisource"
DEFAULT_OUT = ROOT / "artifacts" / "output" / "ris-export"


def _driver_name(source: Path) -> str:
    """Manifests export under their stem; plain sources under theirs."""
    return source.stem


def export_one(source: Path, out_root: Path, timeout: float,
               extra: list[str]) -> dict:
    """Run one extraction subprocess; return the per-driver result row."""
    name = _driver_name(source)
    outdir = out_root / name
    outdir.mkdir(parents=True, exist_ok=True)
    ris = outdir / f"{name}.ris"
    log_path = outdir / "extract.log"

    cmd = [sys.executable, "-m", "extractor", "extract",
           "--source", str(source), "--driver-name", name,
           "--output", str(ris), *extra]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, repo-relative
            cmd, cwd=ROOT, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace")
        rc, killed, tail = proc.returncode, False, proc.stdout[-4000:]
    except subprocess.TimeoutExpired as exc:
        rc, killed = 124, True
        out = exc.stdout or ""
        tail = (out.decode("utf-8", "replace")[-4000:]
                if isinstance(out, bytes) else str(out)[-4000:])
    log_path.write_text(tail or "(no output)", encoding="utf-8")
    seconds = round(time.monotonic() - started, 1)

    return {
        "driver": name,
        "source": str(source.relative_to(ROOT)),
        "returncode": rc,
        "timed_out": killed,
        "seconds": seconds,
        "ris_bytes": ris.stat().st_size if ris.is_file() else 0,
        "log": str(log_path.relative_to(ROOT)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Parallel RIS export (one extractor subprocess per driver).")
    ap.add_argument("--jobs", type=int,
                    default=min(8, os.cpu_count() or 1),
                    help="concurrent extraction subprocesses (default: min(8, cpus))")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output root (default: artifacts/output/ris-export)")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="per-driver seconds before the subprocess is killed")
    ap.add_argument("--multisource", action="store_true",
                    help="also export benchmarks/drivers/multisource/*.json")
    ap.add_argument("--source", nargs="*", default=[],
                    help="explicit .c files or multi-source manifests")
    ap.add_argument("--drivers", nargs="*", default=[],
                    help="subset of driver names (default: all baseline)")
    ap.add_argument("--ir-mode", choices=["off", "auto", "required"],
                    default="off", help="passthrough to the extractor")
    ap.add_argument("--alias-mode", choices=["off", "auto", "required"],
                    default="off", help="passthrough to the extractor")
    ap.add_argument("--compile-context", choices=["off", "auto", "required"],
                    default="auto", help="passthrough to the extractor")
    ns = ap.parse_args()

    sources: list[Path] = sorted(BASELINE_DIR.glob("*.c")) if BASELINE_DIR.is_dir() else []
    if ns.multisource and MULTISOURCE_DIR.is_dir():
        sources += sorted(MULTISOURCE_DIR.glob("*.json"))
    if ns.source:
        sources += [Path(s).resolve() for s in ns.source]
    if ns.drivers:
        wanted = set(ns.drivers)
        sources = [s for s in sources if _driver_name(s) in wanted]
    if not sources:
        print("no sources matched", file=sys.stderr)
        return 1
    # duplicate stems (baseline + explicit same file) would write the same
    # output dir concurrently -- keep the first occurrence
    seen: set[str] = set()
    deduped = []
    for s in sources:
        if _driver_name(s) not in seen:
            seen.add(_driver_name(s))
            deduped.append(s)
    sources = deduped

    out_root = Path(ns.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    extra = ["--ir-mode", ns.ir_mode, "--alias-mode", ns.alias_mode,
             "--compile-context", ns.compile_context]

    print(f"exporting {len(sources)} drivers, jobs={ns.jobs}, out={out_root}")
    wall = time.monotonic()
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=ns.jobs) as pool:
        futures = {pool.submit(export_one, s, out_root, ns.timeout, extra): s
                   for s in sources}
        for fut in as_completed(futures):
            row = fut.result()
            rows.append(row)
            mark = "ok " if row["returncode"] == 0 else "ERR"
            note = " TIMEOUT" if row["timed_out"] else ""
            print(f"{mark} {row['driver']:<24} {row['seconds']:>8.1f}s "
                  f"ris={row['ris_bytes']:>9,} B{note}")
    rows.sort(key=lambda r: r["driver"])
    wall = round(time.monotonic() - wall, 1)
    total = round(sum(r["seconds"] for r in rows), 1)

    ok = sum(1 for r in rows if r["returncode"] == 0)
    summary = {
        "schema": 1,
        "jobs": ns.jobs,
        "wall_seconds": wall,
        "sum_per_driver_seconds": total,
        "ok": ok,
        "failed": len(rows) - ok,
        "options": {"ir_mode": ns.ir_mode, "alias_mode": ns.alias_mode,
                    "compile_context": ns.compile_context,
                    "timeout": ns.timeout},
        "drivers": rows,
    }
    summary_path = out_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n",
                            encoding="utf-8")
    print(f"\n{ok}/{len(rows)} exported | wall {wall}s "
          f"(sum of per-driver {total}s, speedup {total / max(wall, 0.1):.1f}x)")
    print(f"wrote {summary_path}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
