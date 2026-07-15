#!/usr/bin/env python3
"""Run the reproducible extraction/generation/compile matrix.

The detailed generated artifacts stay under ignored `output/experiment-matrix/`.
The compact JSON result is versioned under `experiments/results/` and is the
authoritative input for paper tables.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _run(args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _git_rev(path: str) -> str:
    r = _run(["git", "-C", path, "rev-parse", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _parse_score(text: str) -> dict:
    out = {}
    blockers = []
    in_blockers = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "blockers:":
            in_blockers = True
            continue
        if line == "blockers: []":
            out["blockers"] = []
            continue
        if in_blockers and line.startswith("- "):
            blockers.append(line[2:])
            continue
        if ":" not in line or line == "generation_readiness:":
            continue
        key, value = [x.strip() for x in line.split(":", 1)]
        if value in ("True", "False"):
            out[key] = value == "True"
        else:
            try:
                out[key] = float(value)
            except ValueError:
                out[key] = value
    out.setdefault("blockers", blockers)
    if blockers:
        out["blockers"] = blockers
    return out


def _parse_metrics(text: str) -> dict:
    first = text.splitlines()[0] if text else ""
    m = re.search(
        r"driver metrics: (\d+) ops \| symbolic (\d+) fixed (\d+) computed (\d+) "
        r"\| rmw (\d+) unknown_value (\d+) \| cond (\d+) loop (\d+) \| "
        r"pct_symbolic ([^ ]+) pct_non_top ([^ ]+) \| clang_diag (\d+) \| regs (\d+)",
        first,
    )
    if not m:
        return {}
    keys = ("ops", "symbolic", "fixed", "computed", "rmw", "unknown_value", "conditions",
            "loops", "pct_symbolic", "pct_non_top", "clang_diagnostics", "registers")
    values = list(m.groups())
    out = {}
    for key, value in zip(keys, values):
        if key.startswith("pct_"):
            out[key] = None if value == "None" else float(value)
        else:
            out[key] = int(value)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias-mode", choices=("off", "auto", "required"), default="off")
    ap.add_argument("--workdir", default=os.path.join(ROOT, "output", "experiment-matrix"))
    ap.add_argument("--output", default=os.path.join(ROOT, "experiments", "results", "matrix.json"))
    ns = ap.parse_args()

    drivers_dir = os.path.join(ROOT, "drivers", "test")
    drivers = sorted(os.path.join(drivers_dir, f) for f in os.listdir(drivers_dir)
                     if f.endswith(".c"))
    os.makedirs(ns.workdir, exist_ok=True)
    os.makedirs(os.path.dirname(ns.output), exist_ok=True)

    rows = []
    for source in drivers:
        name = os.path.splitext(os.path.basename(source))[0]
        outdir = os.path.join(ns.workdir, name)
        shutil.rmtree(outdir, ignore_errors=True)
        started = time.monotonic()
        cmd = [sys.executable, "-m", "extractor", "driver", "-s", source,
               "-o", outdir, "--alias-mode", ns.alias_mode]
        run = _run(cmd)
        score_path = os.path.join(outdir, "verify", "score.txt")
        metrics_path = os.path.join(outdir, "verify", "metrics.txt")
        score = _parse_score(open(score_path).read()) if os.path.isfile(score_path) else {}
        metrics = _parse_metrics(open(metrics_path).read()) if os.path.isfile(metrics_path) else {}
        row = {
            "driver": name,
            "source_sha256": _sha256(source),
            "seconds": round(time.monotonic() - started, 3),
            "pipeline_exit": run.returncode,
            "metrics": metrics,
            "readiness": score,
            "backends": {
                "harness_compile": not os.path.exists(os.path.join(outdir, "verify", "harness.compile.log")),
                "harness_trace": os.path.exists(os.path.join(outdir, "verify", "harness.trace.txt")),
                "baremetal_compile": not os.path.exists(os.path.join(outdir, "verify", "baremetal.compile.log")),
                "linux_compile": not os.path.exists(os.path.join(outdir, "verify", "linux.compile.log")),
            },
        }
        rows.append(row)
        state = "/".join("Y" if row["backends"][k] else "N"
                         for k in ("harness_compile", "baremetal_compile", "linux_compile"))
        print(f"{name:<20} ops={metrics.get('ops', '?'):>3} backends={state} {row['seconds']:>6.2f}s")

    aggregate = {k: sum(r["metrics"].get(k, 0) for r in rows)
                 for k in ("ops", "symbolic", "fixed", "computed", "rmw", "unknown_value",
                           "conditions", "loops", "registers", "clang_diagnostics")}
    result = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "alias_mode": ns.alias_mode,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "reharness_commit": _git_rev(ROOT),
            "linux_commit": _git_rev(os.path.join(ROOT, "linux")),
            "kernel_release": _run(["make", "-s", "-C", os.path.join(ROOT, "kernel", "build"),
                                    "kernelrelease"]).stdout.strip(),
        },
        "aggregate": aggregate,
        "drivers": rows,
    }
    with open(ns.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {ns.output}")
    return 0 if all(r["pipeline_exit"] == 0 for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
