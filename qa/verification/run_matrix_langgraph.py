#!/usr/bin/env python3
"""Run the extraction/generation/compile matrix through the LangGraph pipeline.

Mirrors ``run_matrix.py``'s row schema and success signals, but each driver's
pipeline is executed by the shared backend pipeline (the
orchestration path) instead of the CLI.  Deterministic rules generation is
pinned per manifest so results are reproducible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "qa"))
sys.path.insert(0, os.path.join(ROOT, "qa", "verification"))



def _parse_score(text: str) -> dict:
    out: dict = {}
    blockers: list[str] = []
    in_blockers = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "blockers:":
            in_blockers = True
            continue
        if in_blockers:
            if line.startswith("- "):
                blockers.append(line[2:])
            continue
        if ":" in line:
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
    keys = ("ops", "symbolic", "fixed", "computed", "rmw", "unknown_value",
            "conditions", "loops", "pct_symbolic", "pct_non_top",
            "clang_diagnostics", "registers")
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
    ap.add_argument("--workdir", default=os.path.join(
        ROOT, "artifacts", "output", "experiment-matrix-langgraph"))
    ap.add_argument("--output", default=os.path.join(
        ROOT, "research", "experiments", "results", "matrix-langgraph.json"))
    ap.add_argument("--drivers", nargs="*", default=None,
                    help="subset of driver names (default: all baseline .c)")
    ns = ap.parse_args()

    from extractor import ExtractorConfig, extract_ris
    from backends.pipeline import run_backend_pipeline

    drivers_dir = os.path.join(ROOT, "benchmarks", "drivers", "baseline")
    sources = sorted(os.path.join(drivers_dir, f) for f in os.listdir(drivers_dir)
                     if f.endswith(".c"))
    if ns.drivers:
        sources = [s for s in sources
                   if os.path.splitext(os.path.basename(s))[0] in set(ns.drivers)]
    os.makedirs(ns.workdir, exist_ok=True)
    os.makedirs(os.path.dirname(ns.output), exist_ok=True)

    rows = []
    for source in sources:
        name = os.path.splitext(os.path.basename(source))[0]
        outdir = os.path.join(ns.workdir, name)
        shutil.rmtree(outdir, ignore_errors=True)
        started = time.monotonic()
        error = None
        return_code = None
        try:
            result = extract_ris(ExtractorConfig(
                source=source, driver_name=name))
            final = run_backend_pipeline(result, str(outdir), str(source_path))
            return_code = final.get("return_code")
        except Exception:
            error = traceback.format_exc(limit=6)
        seconds = round(time.monotonic() - started, 3)

        ver_dir = os.path.join(outdir, "verify")
        gen_dir = os.path.join(outdir, "generated")

        def _compiled(kind: str) -> bool:
            generated = (os.path.isfile(os.path.join(gen_dir, f"{kind}.c"))
                         or os.path.isdir(os.path.join(gen_dir, kind)))
            return (generated
                    and not os.path.exists(
                        os.path.join(ver_dir, f"{kind}.compile.log")))

        score_path = os.path.join(ver_dir, "score.txt")
        metrics_path = os.path.join(ver_dir, "metrics.txt")
        score = _parse_score(open(score_path).read()) if os.path.isfile(score_path) else {}
        metrics = _parse_metrics(open(metrics_path).read()) if os.path.isfile(metrics_path) else {}
        row = {
            "driver": name,
            "source_sha256": None,
            "seconds": seconds,
            "pipeline_exit": -1 if error is not None else (return_code if return_code is not None else -1),
            "orchestration_error": error,
            "metrics": metrics,
            "readiness": score,
            "backends": {
                "harness_compile": _compiled("harness"),
                "harness_trace": os.path.exists(
                    os.path.join(ver_dir, "harness.trace.txt")),
                "baremetal_compile": _compiled("baremetal"),
                "linux_compile": _compiled("linux"),
            },
        }
        rows.append(row)
        state = "/".join("Y" if row["backends"][k] else "N"
                         for k in ("harness_compile", "baremetal_compile",
                                   "linux_compile"))
        marker = "ERR" if error else ("ok " if row["pipeline_exit"] == 0 else "rc1")
        print(f"{marker} {name:<20} backends={state} {seconds:>7.2f}s")
        if error:
            print(error.splitlines()[-1])

    compiled = {k: sum(1 for r in rows if r["backends"][k])
                for k in ("harness_compile", "baremetal_compile", "linux_compile",
                          "harness_trace")}
    result = {
        "schema": 1,
        "orchestration": "langgraph",
        "generation_mode": "langchain",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "aggregate": {
            "drivers": len(rows),
            "orchestration_errors": sum(1 for r in rows if r["orchestration_error"]),
            "pipeline_exit_zero": sum(1 for r in rows if r["pipeline_exit"] == 0),
            **compiled,
        },
        "drivers": rows,
    }
    with open(ns.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"\naggregate: {json.dumps(result['aggregate'])}")
    print(f"wrote {ns.output}")
    return 0 if (result["aggregate"]["orchestration_errors"] == 0
                 and all(compiled.values())) else 1


if __name__ == "__main__":
    raise SystemExit(main())
