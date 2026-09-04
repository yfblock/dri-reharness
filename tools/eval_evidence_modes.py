#!/usr/bin/env python3
"""Evidence-mode A/B/C experiment for harness-backend translation.

Question (paper goal): is the RIS alone enough to translate a driver,
and does injecting RIS semantics raise compile/verify pass rates?

Modes, all on the SAME extracted formal:
  full           — device spec + framework facts + bind (pipeline default)
  ris_only       — RIS modules (ops + Call/ExternalCall nodes) + mechanical
                   bind mapping; no spec, no facts
  ris_semantics  — ris_only plus the RIS semantics legend and reviewed
                   external-call annotations

Each mode gets the same treatment: LLM generation (chunked identically),
the generic compile-repair round, the receipt-completion round, then the
harness-backend verification chain (cc compile, lowering oracle,
generated-C AST leaf, runtime trace subsequence).  LLM effort is counted
with the shared CallAccountant (no secrets in any report).

Usage:
  python3 tools/eval_evidence_modes.py [--drivers a,b,c] [--modes full,ris_only]
                                       [--out artifacts/output/<name>]

Requires the usual LLM endpoint configuration (config.toml or
REHARNESS_LLM_API_KEY); never writes credentials anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "qa"))
sys.path.insert(0, str(ROOT / "qa" / "verification"))

from extractor.formalize import save_formal_text  # noqa: E402


class _Accountant:
    """Count LLM calls/tokens-ish sizes around backends.llm_bridge.call_llm.

    Patches the module attribute, so generation AND both repair rounds are
    counted.  No prompt/response text or secrets are retained.
    """

    def __init__(self):
        self.calls = 0
        self.prompt_chars = 0
        self.response_chars = 0
        self.failures = 0
        self._orig = None

    def __enter__(self):
        import backends.llm_bridge as lb
        self._orig = lb.call_llm
        outer = self

        def counted(prompt, *a, **kw):
            outer.calls += 1
            outer.prompt_chars += len(prompt or "")
            try:
                out = outer._orig(prompt, *a, **kw)
            except Exception:
                outer.failures += 1
                raise
            outer.response_chars += len(out or "")
            return out

        lb.call_llm = counted
        return self

    def __exit__(self, *exc):
        import backends.llm_bridge as lb
        lb.call_llm = self._orig
        return False

    def summary(self) -> dict:
        return {"calls": self.calls, "prompt_chars": self.prompt_chars,
                "response_chars": self.response_chars,
                "failures": self.failures}


DEFAULT_DRIVERS = [
    "ahci_ceva.c", "ahci_sunxi.c", "clk-highbank.c", "edu.c",
    "gpio-cadence.c", "gpio-ftgpio010.c", "gpio-pl061.c",
    "sdhci-of-at91.c", "virtio_mmio.c", "pll.c",
]
MODES = ("full", "ris_only", "ris_semantics")


def _w(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def trace_expected_from_formal(formal: dict):
    """Expected unconditional op sequence — first module with ops.

    Formal-only rule, identical across modes, so the trace metric never
    depends on the device spec.
    """
    from extractor.metrics import _computed_is_lowerable
    from verification.subsystem_callback_oracle import _eval

    regs = {r["name"]: r["offset"] for r in formal["register_map"]}
    mod = next((m for m in formal["modules"] if m.get("ops")), None)
    if mod is None:
        return None
    expected = []
    for o in mod["ops"]:
        for kind, letter in (("Write", "W"), ("Read", "R")):
            if kind in o:
                addr = o[kind]["addr"]
                if "Symbolic" in addr:
                    off = regs.get(addr["Symbolic"]["register"])
                elif "Fixed" in addr:
                    off = addr["Fixed"]["offset"]
                elif ("Computed" in addr
                        and _computed_is_lowerable(addr["Computed"])):
                    off = _eval(addr["Computed"], {})
                else:
                    return None  # untraceable address
                expected.append((letter, off))
    return expected


def run_one(res, mode: str, outdir: Path) -> dict:
    from backends.llm_bridge import generate_via_llm, generated_file_entries
    from backends.pipeline.compile_repair import _repair_compile
    from backends.pipeline.receipt_repair import _repair_receipts
    from backends.pipeline.paths import _is_subsequence, _repository_root
    from verification.backend_lowering_oracle import (
        build_generation_contract, verify_backend_lowering)
    from verification.generated_c_ast_oracle import verify_generated_c_ast
    from verification.subsystem_callback_oracle import (
        verify_subsystem_callbacks)
    from extractor.spec import BindSpec, default_bind
    from backends.common import make_freestanding_bind

    formal = res.formal
    name = formal["driver"]
    driver_dir = outdir / f"{name}__{mode}"
    gen_dir = driver_dir / "generated"
    ver_dir = driver_dir / "verify"
    tmp_dir = ver_dir / "tmp"
    for d in (driver_dir, gen_dir, ver_dir, tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    if mode == "full":
        bind = default_bind(res.device_spec, "harness")
    else:
        # mechanical dialect plumbing only — no spec-derived state/callbacks
        bind = BindSpec(backend="harness", device=name)
        priv = re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower() + "_priv"
        make_freestanding_bind(bind, priv, "base", prefix="harness")

    t0 = time.monotonic()
    code = generate_via_llm(formal, res.device_spec, bind,
                            backend="harness", evidence_mode=mode)
    entries = generated_file_entries(code, default_path="harness.c")
    cpath = gen_dir / "harness.c"
    for entry in entries:
        (gen_dir / entry["path"]).write_text(entry["code"], encoding="utf-8")
    save_formal_text(formal, str(driver_dir / f"{name}.ris"))

    root = _repository_root()
    try:
        _repair_compile("harness", name, str(cpath),
                        entries if getattr(code, "files", None) else None,
                        str(ver_dir), root, str(tmp_dir))
    except Exception as exc:  # noqa: BLE001 — record, don't crash the sweep
        _w(ver_dir / "repair.log", f"compile repair crashed: {exc}")
    try:
        _repair_receipts("harness", name, str(cpath), formal,
                         entries if getattr(code, "files", None) else None,
                         str(ver_dir), root, str(tmp_dir))
    except Exception as exc:  # noqa: BLE001
        _w(ver_dir / "receipt-repair.log", f"receipt repair crashed: {exc}")

    generated_text = cpath.read_text(encoding="utf-8")
    contract = build_generation_contract(formal)
    lowering = verify_backend_lowering(formal, generated_text)
    try:
        ast_leaf = verify_generated_c_ast(contract, str(cpath))
        ast_ok = bool(ast_leaf.get("complete"))
    except Exception as exc:  # noqa: BLE001
        ast_ok = False
        _w(ver_dir / "ast-leaf.error", f"{type(exc).__name__}: {exc}")

    compiled = ran = trace_ok = None
    binp = tmp_dir / "harness.bin"
    r = subprocess.run(["cc", "-o", str(binp), str(cpath)],
                       capture_output=True, text=True)
    compiled = r.returncode == 0
    if not compiled:
        _w(ver_dir / "compile.log", r.stderr)
    else:
        executed = subprocess.run([str(binp)], capture_output=True, text=True)
        ran = executed.returncode == 0
        _w(ver_dir / "trace.txt", executed.stdout)
        gr = verify_subsystem_callbacks(formal, res.device_spec,
                                        executed.stdout)
        expected = trace_expected_from_formal(formal)
        traced = [(k, int(off, 16)) for k, off in re.findall(
            r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)",
            executed.stdout)]
        trace_ok = bool(
            ran and expected is not None
            and _is_subsequence(expected, traced)
            and gr.get("subsystem_callback_oracle_passed", True))

    return {
        "driver": name, "mode": mode,
        "compiled": compiled, "ran": ran, "trace_passed": trace_ok,
        "lowering_complete": lowering.get("complete"),
        "ast_leaf_complete": ast_ok,
        "seconds": round(time.monotonic() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drivers", default=",".join(DEFAULT_DRIVERS))
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--out",
                    default=f"artifacts/output/eval-evidence-modes-"
                            f"{time.strftime('%Y-%m-%d')}")
    args = ap.parse_args()
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)

    with _Accountant() as acc:
        results = []
        for stem in [d for d in args.drivers.split(",") if d]:
            source = ROOT / "benchmarks" / "drivers" / "baseline" / stem
            if not source.is_file():
                print(f"skip (missing): {source}")
                continue
            # extract once per driver; all modes share the same formal
            try:
                from extractor import ExtractorConfig, extract_ris
                from extractor.extractor import _extraction_cache
                _extraction_cache.clear()
                res = extract_ris(ExtractorConfig(source=str(source)))
            except Exception as exc:  # noqa: BLE001
                row = {"driver": stem, "mode": "*",
                       "error": f"{type(exc).__name__}: {exc}"[-500:]}
                results.append(row)
                print(json.dumps(row, sort_keys=True), flush=True)
                continue
            for mode in [m for m in args.modes.split(",") if m]:
                # endpoint intermittently returns 200-with-empty-body; a
                # cell that died on generation (not on verification) gets
                # one fresh retry so flake never masquerades as a mode gap
                row = None
                for attempt in range(2):
                    try:
                        row = run_one(res, mode, outdir)
                    except Exception as exc:  # noqa: BLE001
                        row = {"driver": res.formal.get("driver", stem),
                               "mode": mode,
                               "error": f"{type(exc).__name__}: {exc}"[-500:]}
                    if attempt == 0 and "error" in row and (
                            "empty code" in row["error"]
                            or "empty body" in row["error"]):
                        continue
                    break
                results.append(row)
                print(json.dumps(row, sort_keys=True), flush=True)
    _w(outdir / "results.json", json.dumps(
        {"results": results, "llm": acc.summary()}, indent=2))

    # summary table
    print("\n== pass rates ==")
    print(f"{'mode':15s} {'compiled':>9s} {'lowering':>9s} "
          f"{'ast':>6s} {'trace':>6s}")
    for mode in [m for m in args.modes.split(",") if m]:
        rows = [r for r in results if r.get("mode") == mode]
        n = len(rows) or 1
        def rate(key):
            got = [r for r in rows if r.get(key) is not None]
            return f"{sum(1 for r in rows if r.get(key))}/{len(rows)}" \
                if got or rows else "-"
        print(f"{mode:15s} {rate('compiled'):>9s} "
              f"{rate('lowering_complete'):>9s} "
              f"{rate('ast_leaf_complete'):>6s} {rate('trace_passed'):>6s}")
    print(f"\nresults: {outdir}/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
