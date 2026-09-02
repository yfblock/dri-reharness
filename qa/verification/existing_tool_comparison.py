#!/usr/bin/env python3
"""Existing-tool comparison on the QEMU edu device (2026-09 records).

Compares, for the same device, four ways of obtaining a non-Linux
realization of the driver's register protocol:

  1. the pinned Linux driver source (input),
  2. QEMU's own hand-written edu device model (hw/misc/edu.c at v9.0.0),
  3. a C2Rust 0.22.1 transpilation of a de-kernelized stub carrying the
     same register protocol (the real driver cannot be transpiled: kernel
     headers crash the transpiler -- AddressSpaceConversion, TagTypeUnknown,
     then an error avalanche; recorded 2026-09-02, C2Rust built from source
     on nightly-2022-08-08),
  4. the reharness edu artifacts (three backends, RIS contract + receipts).

Line counts are total/blank/comment-stripped code lines. The QEMU model's
MMIO offsets are parsed from its read/write case dispatches (device view);
the driver view is the set of offsets the pinned source actually accesses,
taken from the edu RIS (benchmarks contract). Output is versioned as
research/experiments/results/existing-tool-comparison.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "research" / "experiments" / "existing-tools"
OUT = (ROOT / "research" / "experiments" / "results"
       / "existing-tool-comparison.json")

SOURCES = {
    "linux_driver": ROOT / "benchmarks" / "drivers" / "baseline" / "edu.c",
    "qemu_model": HERE / "qemu-edu-v9.c",
    "c2rust_stub_c": HERE / "edu_stub.c",
    "c2rust_rust": HERE / "edu_stub.rs",
    "reharness_linux": [ROOT / "examples" / "edu" / "edu_linux.c",
                        ROOT / "examples" / "edu" / "edu_linux.h"],
    "reharness_harness": [ROOT / "examples" / "edu" / "edu_harness.c",
                          ROOT / "examples" / "edu" / "edu_harness.h"],
    "reharness_baremetal": [ROOT / "examples" / "edu" / "edu_baremetal.c",
                            ROOT / "examples" / "edu" / "edu_baremetal.h"],
    "reharness_rust": ROOT / "examples" / "edu" / "edu_rust_baremetal.rs",
}


def _counts(paths: list[Path]) -> dict:
    lines: list[str] = []
    for p in paths:
        lines += p.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    blank = sum(1 for l in lines if not l.strip())
    comment = 0
    in_block = False
    for l in lines:
        s = l.strip()
        if in_block:
            comment += 1
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("/*"):
            comment += 1
            if s.startswith("/*") and "*/" not in s:
                in_block = True
        elif s.startswith("*") or s.startswith("*/"):
            comment += 1
    return {"total": total, "blank": blank, "comment": comment,
            "code": total - blank - comment}


def _qemu_offsets() -> dict:
    text = SOURCES["qemu_model"].read_text(encoding="utf-8")
    offs: dict[str, list[str]] = {}
    for fn in ("edu_mmio_read", "edu_mmio_write"):
        m = re.search(r"static .*\b" + fn + r"\(.*?\n\{(.*?)\n\}", text, re.S)
        if m is None:
            offs[fn] = []
            continue
        offs[fn] = sorted(set(re.findall(r"case (0x[0-9a-fA-F]+):", m.group(1))),
                          key=lambda h: int(h, 16))
    union = sorted(set(offs["edu_mmio_read"]) | set(offs["edu_mmio_write"]),
                   key=lambda h: int(h, 16))
    return {"read": offs["edu_mmio_read"], "write": offs["edu_mmio_write"],
            "union": union, "union_count": len(union)}


def _unsafe_share(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    sigs = re.findall(r"^(?:pub\s+)?((?:\w+\s+)*)(?:unsafe\s+)?"
                      r"(?:extern\s+\"C\"\s+)?fn\s+\w+", text, re.M)
    fns = len(sigs)
    unsafe_fns = sum(1 for s in sigs if "unsafe" in s)
    unsafe_blocks = len(re.findall(r"unsafe\s*\{", text))
    return {"functions": fns, "unsafe_functions": unsafe_fns,
            "unsafe_blocks": unsafe_blocks,
            "unsafe_function_pct": round(100.0 * unsafe_fns / fns, 1)
            if fns else None}


def main() -> int:
    c = lambda k: _counts([SOURCES[k]] if not isinstance(SOURCES[k], list)
                          else SOURCES[k])  # noqa: E731
    qemu = _qemu_offsets()
    # driver view: registers actually accessed by the pinned driver --
    # named registers read/written in the edu RIS, mapped to offsets by
    # the edu dspec register declarations (the extraction all four
    # realizations share)
    ris = (ROOT / "examples" / "edu" / "edu.ris").read_text(encoding="utf-8")
    dspec = (ROOT / "examples" / "edu" / "edu.dspec").read_text(
        encoding="utf-8")
    at = {m.group(1): int(m.group(2), 16) for m in re.finditer(
        r"register\s+(\w+)\s*:\s*B\d+\s+at\s+base\s*\+\s*(0x[0-9a-fA-F]+)",
        dspec)}
    touched = set(re.findall(r"[RW]\(B\d+[^)]*\.(\w+)\)", ris))
    drv_offs = sorted(at[r] for r in touched if r in at)
    drv_hex = [hex(o) for o in drv_offs]

    report = {
        "schema": 1,
        "device": "qemu-edu",
        "description": ("Existing-tool comparison on the QEMU edu device: "
                        "pinned Linux driver, QEMU's hand-written device "
                        "model (v9.0.0 hw/misc/edu.c), C2Rust 0.22.1 "
                        "transpilation of a de-kernelized stub (the real "
                        "driver cannot be transpiled), and the reharness "
                        "artifacts with their RIS contract"),
        "objects": {
            "linux_driver": {**c("linux_driver"),
                             "os_binding": "Linux kernel APIs throughout",
                             "protocol": "implicit (macros + readl/writel)"},
            "qemu_model": {**c("qemu_model"), "mmio_offsets": qemu,
                           "device_view_only_offsets": sorted(
                               set(qemu["union"]) - set(drv_hex)),
                           "os_binding": "QEMU device APIs",
                           "protocol": "implicit (MMIO case dispatch)"},
            "c2rust": {**c("c2rust_rust"),
                       "stub_c_lines": c("c2rust_stub_c")["total"],
                       "unsafe": _unsafe_share(SOURCES["c2rust_rust"]),
                       "os_binding": "none (stub de-kernelized by hand)",
                       "protocol": "implicit (pointer arithmetic), "
                                   "no contract to reconcile",
                       "note": "C2Rust 0.22.1 cannot transpile the real "
                               "driver: kernel headers crash the transpiler "
                               "(AddressSpaceConversion, TagTypeUnknown, "
                               "error avalanche)"},
            "reharness_linux": {**c("reharness_linux"),
                                "os_binding": "backend adapter",
                                "protocol": "RIS contract + receipts"},
            "reharness_harness": {**c("reharness_harness"),
                                  "os_binding": "none",
                                  "protocol": "RIS contract + receipts"},
            "reharness_baremetal": {**c("reharness_baremetal"),
                                    "os_binding": "none",
                                    "protocol": "RIS contract + receipts"},
            "reharness_rust": {**c("reharness_rust"),
                               "os_binding": "none (no_std)",
                               "protocol": "RIS contract + receipts"},
        },
        "driver_view": {
            "driver_accessed_offsets": drv_hex,
            "driver_accessed_count": len(drv_hex),
            "reharness_ris_covers": len(drv_hex),
            "device_view_vs_driver_view": (
                f"QEMU model serves {qemu['union_count']} offsets; the "
                f"driver touches {len(drv_hex)}; the difference is the "
                "device-side register surface the driver never exercises"),
        },
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(OUT)
    for k, v in report["objects"].items():
        print(f"  {k:20} total={v['total']:4} code={v['code']:4}")
    print(f"  qemu offsets={qemu['union_count']} driver offsets="
          f"{len(drv_hex)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
