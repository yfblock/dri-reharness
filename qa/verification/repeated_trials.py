#!/usr/bin/env python3
"""Repeated-trial measurement of the constrained LLM translation (W1).

Draws k independent trials of the constrained generation pipeline on the
pinned DesignWare APB SSI extraction. Per trial and per backend (harness,
bare-metal, Linux), the same candidate is measured twice:

  first pass   generation with the pipeline's compile-repair loop disabled
               (REHARNESS_LLM_REPAIR_ROUNDS=0) — raw emission quality
  post-repair the same candidate (no regeneration) with the compile-repair
               loop at its default budget, followed by the bounded
               receipt-repair loop (the normalization pre-passes plus the
               batch-30 missing-operation prompts of repair_lowering,
               guards included, max 6 rounds) when the candidate compiles
               — the recorded chain only ever repaired compiled artifacts —
               then full re-verification

Checks recorded per stage are the gate's own: compile, receipt accounting,
AST-leaf anchors, strict lowering plan, runtime trace (harness only).
Acceptance-at-strict-gate and acceptance-at-check-backed-level
(compile+receipts+AST-leaf, the level at which the flagship artifact is
accepted) are both reported; the strict plan is expected to keep rejecting
DesignWare candidates (17 loop-carried receipts, Section 7 of the paper).

The Rust backend is not re-measured here: the pipeline's generation fan-out
covers the three C backends, and the Rust record remains single-trial.

Output: research/experiments/results/dw-repeated-trials.json
Usage: repeated_trials.py [--trials 5] [--backend harness,baremetal,linux]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "qa"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

OUT = (ROOT / "research" / "experiments" / "results"
       / "dw-repeated-trials.json")
WORK = ROOT / "artifacts" / "cache" / "repeated-trials"
MANIFEST = ROOT / "benchmarks" / "drivers" / "multisource" / "dw-apb-ssi.json"

from gate_mutation_study import _load_extraction, _verdict  # noqa: E402


class _WrappedBackend:
    """Call the real generate() once per candidate, then replay the cache.

    The compile-repair pass re-enters the pipeline; replaying the cached
    code object keeps both passes on the SAME candidate (a regeneration
    would measure a different sample, not a repair).
    """

    def __init__(self, real, gen_kwargs: dict):
        self._real = real
        self._gen_kwargs = gen_kwargs
        self._cache = None
        self.calls = 0
        self.GEN_KWARGS = getattr(real, "GEN_KWARGS", [])

    def generate(self, *a, **kw):
        if self._cache is None:
            self.calls += 1
            self._cache = self._real.generate(
                *a, **{**kw, **self._gen_kwargs})
        return self._cache


def _pipeline_pass(res, workdir: Path, registry_map: dict, repair_rounds):
    """Run the backend pipeline with a stubbed registry; returns gen_results."""
    import backends.registry as registry
    from backends.pipeline import run_backend_pipeline

    original = registry.list_backends
    env_key = "REHARNESS_LLM_REPAIR_ROUNDS"
    saved = os.environ.get(env_key)
    os.environ[env_key] = str(repair_rounds)
    registry.list_backends = lambda: registry_map
    try:
        result = run_backend_pipeline(
            res, str(workdir), str(MANIFEST))
    finally:
        registry.list_backends = original
        if saved is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = saved
    return result["gen_results"]


def _receipt_repair(formal, contract, files: dict[str, Path],
                    backend: str, max_rounds: int = 6) -> dict:
    """Bounded receipt-repair loop on the generated pair, no log writes.

    Reuses repair_lowering's prompts, normalization pre-passes, and
    response guards verbatim so the trial protocol matches the recorded
    chain; only the official artifact-repair-log append is skipped.
    """
    import repair_lowering as rl
    from verification.backend_lowering_oracle import verify_backend_lowering
    from backends.llm_bridge import _module_ris
    from langchain_bridge import call_langchain

    rows = {row["op_id"]: row for row in contract["register_operations"]}
    txn_rows = {row["op_id"]: row for row in contract.get(
        "transaction_operations", []) if row.get("op_id")}
    ris_text = "\n".join(_module_ris(m) for m in formal.get("modules", []))
    lang = "c"
    primary = files["primary"]

    def _read_all() -> str:
        # receipts, anchors, and module bodies live in the primary source
        # file; the header pair is regenerated verbatim by the backend and
        # carries no receipts to repair (matches the recorded chain, which
        # ran repair_lowering on the installed .c artifacts)
        return primary.read_text(encoding="utf-8")

    stats = {"rounds": 0, "llm_calls": 0, "guard_rejects": 0}
    for i in range(max_rounds + 1):
        text = rl._normalize_anchors(_read_all())
        text, fixed = rl._fix_digests(text, rows)
        text, txn_fixed = rl._fix_transaction_receipts(text, txn_rows)
        if fixed or txn_fixed:
            primary.write_text(text, encoding="utf-8")
        v = verify_backend_lowering(formal, text)
        if v.get("duplicate"):
            text, removed = rl._dedup_repeats(text, sorted(v["duplicate"]))
            primary.write_text(text, encoding="utf-8")
            v = verify_backend_lowering(formal, text)
        stats["rounds"] = i
        if v.get("complete") or i == max_rounds:
            stats["complete"] = bool(v.get("complete"))
            stats["missing_final"] = len(v.get("missing", [])) + len(
                v.get("missing_transaction_markers", []))
            return stats
        missing = sorted(v.get("missing", []))
        missing_txn = sorted(v.get("missing_transaction_markers", []))
        BATCH = 30
        if len(missing) > BATCH:
            missing = missing[:BATCH]
        ops_lines, modules = [], []
        if missing:
            for op in missing:
                row = rows.get(op)
                if row:
                    ops_lines.append(
                        f"MISSING {op} module={row['module']} "
                        f"kind={row['kind']} digest={row['digest']}")
                    if row["module"] not in modules:
                        modules.append(row["module"])
            prompt = rl.PROMPT.format(
                kind=f"{backend} backend", lang=lang, ops="\n".join(ops_lines),
                ris=rl._ris_lines(ris_text, missing),
                context=rl._module_windows(text, modules))
        elif missing_txn:
            for op in missing_txn[:BATCH]:
                row = txn_rows.get(op)
                if row:
                    ops_lines.append(
                        f"MISSING {op} module={row['module']} "
                        f"kind={row['kind']} transport={row['transport']} "
                        f"digest={row['digest']}")
                    if row["module"] not in modules:
                        modules.append(row["module"])
            prompt = rl.TXN_PROMPT.format(
                kind=f"{backend} backend", lang=lang, ops="\n".join(ops_lines),
                ris=rl._ris_lines(ris_text, missing_txn),
                context=rl._module_windows(text, modules))
        else:
            stats["complete"] = False
            stats["missing_final"] = 0
            return stats
        # append with a compile guard: the model sometimes re-emits a
        # WHOLE module (colliding with the live definition) or drifts to
        # a wrong access style (e.g. member syntax for an offset #define,
        # which cannot compile).  The recorded chain merged duplicate
        # lowering emissions by hand ("merged from ..." markers in the
        # installed artifact); the bounded protocol instead rejects any
        # append that breaks the previously compiling candidate, reverts,
        # and re-asks once for a uniquely named, style-matching helper.
        def _try_append(cand_text: str, marker: str) -> bool:
            primary.write_text(
                text.rstrip("\n") + f"\n\n/* ---- receipt-repair "
                f"{marker} ---- */\n" + cand_text, encoding="utf-8")
            probe = _syntax_probe(backend, primary)
            if probe is not None and probe.returncode != 0:
                primary.write_text(text, encoding="utf-8")
                return False
            return True

        block_ok = False
        for attempt in range(2):
            try:
                raw = call_langchain(
                    prompt if attempt == 0 else prompt + (
                        "\nREMINDER: your previous block was rejected "
                        "because it did not compile against the scaffold "
                        "(redefined an existing function, or used a wrong "
                        "register-access style). Emit a static helper with "
                        "a NEW, unused function name, in the scaffold's "
                        "existing register-access style, carrying only the "
                        "missing receipts and anchor blocks.\n"),
                    timeout=600)
                stats["llm_calls"] += 1
                cand = rl._extract_block(raw, lang)
                if (rl._brace_delta(cand) != 0
                        or not rl._comments_closed(cand)):
                    stats["guard_rejects"] += 1
                    continue
                marker = (f"round {i}" if attempt == 0
                          else f"round {i} (retry)")
                if _try_append(cand, marker):
                    block_ok = True
                    break
                stats["guard_rejects"] += 1
            except Exception:
                stats["llm_calls"] += 1
        if not block_ok:
            continue  # next round re-verifies the reverted text
    return stats


def _combined_text(gen_dir: Path, backend: str) -> str:
    """Header+source combined into one translation unit for re-verify."""
    bdir = gen_dir / backend
    if bdir.is_dir():
        files = sorted(bdir.rglob("*"))
        sources = [f for f in files if f.suffix == ".c"]
        headers = [f for f in files if f.suffix == ".h"]
        if sources and headers:
            body = sources[0].read_text(encoding="utf-8")
            body = re.sub(r'^[ \t]*#[ \t]*include[ \t]*"'
                          r'[\w./+-]+"\n?', "", body, count=1)
            return headers[0].read_text(encoding="utf-8") + "\n" + body
        if sources:
            return sources[0].read_text(encoding="utf-8")
    single = gen_dir / f"{backend}.c"
    if single.is_file():
        return single.read_text(encoding="utf-8")
    raise FileNotFoundError(f"no generated files for {backend}")


def _stub_for(text: str) -> SimpleNamespace:
    return SimpleNamespace(generate=lambda *a, **k: text, GEN_KWARGS=[])


def _syntax_probe(backend: str, primary: Path):
    """Cheap compile probe for the redefinition guard; None = unavailable.

    Mirrors backends.pipeline._compile_probe's dialects; returns None
    when the backend's probe environment (kernel build tree) is absent
    so the guard degrades to a no-op instead of failing the trial.
    """
    import subprocess
    import backends.pipeline as bp
    try:
        (WORK / "probe").mkdir(parents=True, exist_ok=True)
        if backend == "linux":
            kdir = ROOT / "platform" / "kernel" / "build"
            if not kdir.is_dir():
                return None
        return bp._compile_probe(
            backend, str(primary), "rh_trial_probe", ROOT,
            str(WORK / "probe"))
    except Exception:
        return None


def _run_backend_trial(res, contract, tdir: Path, backend: str,
                       max_repair_rounds: int) -> dict:
    """One trial for one backend: generate once, measure three stages."""
    import backends.registry as registry
    real = registry.list_backends()[backend]
    gen_kwargs = {}
    for kw in getattr(real, "GEN_KWARGS", []):
        if kw == "facts":
            gen_kwargs["facts"] = res.facts
        elif kw == "pci_identity":
            gen_kwargs["pci_identity"] = getattr(res, "pci_identity", None)
        elif kw == "registrar":
            gen_kwargs["registrar"] = getattr(res, "registrar", None)
    wrapped = _WrappedBackend(real, gen_kwargs)
    wmap = {backend: wrapped}

    # the private endpoint intermittently returns empty bodies on long
    # chunked prompts; a failed part poisons the whole candidate, so the
    # generation itself gets fresh retries (this retries the ENDPOINT,
    # not the sample: an empty body carries no model output)
    for gen_attempt in range(4):
        try:
            g0 = time.time()
            first = _pipeline_pass(res, tdir / f"{backend}-first", wmap, 0)
            break
        except RuntimeError:
            wrapped._cache = None
            if gen_attempt == 3:
                raise
    gen_seconds = round(time.time() - g0, 1)
    fv = _verdict(first[backend])

    post = _pipeline_pass(res, tdir / f"{backend}-repair", wmap, 3)
    pv = _verdict(post[backend])

    # -- receipt repair on the repaired candidate, then re-verify ---------
    gen_dir = tdir / f"{backend}-repair" / "generated"
    bdir = gen_dir / backend
    primary = None
    if bdir.is_dir():
        srcs = sorted(bdir.rglob("*.c"))
        primary = srcs[0] if srcs else None
    if primary is None:
        cand = gen_dir / f"{backend}.c"
        primary = cand if cand.is_file() else None
    rr = {"skipped": True}
    if primary is None:
        rr = {"skipped": "no-primary-source"}
    elif not pv["checks"]["compile"]:
        # matches the recorded chain: receipt repair only ever ran on
        # candidates that compiled; on a non-compiling candidate the
        # post-receipt verdict is predetermined, so the LLM budget is
        # not spent
        rr = {"skipped": "compile_failed"}
    else:
        rr = _receipt_repair(res.formal, contract,
                             {"primary": primary}, backend,
                             max_repair_rounds)
    combined = _combined_text(gen_dir, backend)
    final = _pipeline_pass(
        res, tdir / f"{backend}-verify", {backend: _stub_for(
            combined)}, 0)
    fvd = _verdict(final[backend])

    checks = {}
    for stage, v in (("first_pass", fv), ("post_compile_repair", pv),
                     ("post_receipt_repair", fvd)):
        checks[stage] = v["checks"]
    accepted_checkbacked = all(
        fvd["checks"][k] or k == "runtime_trace"
        for k in ("compile", "receipt_accounting", "ast_leaf_anchors"))
    return {
        "gen_seconds": gen_seconds,
        "llm_generate_calls": wrapped.calls,
        "checks": checks,
        "receipt_repair": rr,
        "first_failing_check_final": fvd["first_failing_check"],
        "accepted_strict": not fvd["rejected"],
        "accepted_checkbacked": accepted_checkbacked,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--backends", default="harness,baremetal,linux")
    ap.add_argument("--max-repair-rounds", type=int, default=6)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--resume", action="store_true",
                    help="keep recorded trials in --out and continue")
    args = ap.parse_args()

    from verification.backend_lowering_oracle import build_generation_contract

    print("loading extraction (cached)...", flush=True)
    res = _load_extraction(str(MANIFEST))
    contract = build_generation_contract(res.formal)

    from langchain_bridge import load_langchain_settings
    settings = load_langchain_settings()

    backend_names = [b.strip() for b in args.backends.split(",") if b.strip()]
    trials = []
    start = 1
    if args.resume and Path(args.out).is_file():
        try:
            trials = json.loads(
                Path(args.out).read_text(encoding="utf-8")).get("trials", [])
            start = len(trials) + 1
            print(f"resuming after {len(trials)} recorded trial(s)",
                  flush=True)
        except Exception:
            trials = []
    for t in range(start, args.trials + 1):
        tdir = WORK / f"trial{t}"
        tdir.mkdir(parents=True, exist_ok=True)
        row = {"trial": t, "backends": {}}
        t0 = time.time()
        for backend in backend_names:
            try:
                row["backends"][backend] = _run_backend_trial(
                    res, contract, tdir, backend, args.max_repair_rounds)
            except Exception:  # one backend must not kill the run
                import traceback
                traceback.print_exc()
                row["backends"][backend] = {"error": "exception (see log)"}
            v = row["backends"][backend]
            if "error" not in v:
                print(f"trial {t} {backend}: "
                      f"first={next((k for k, ok in v['checks']['first_pass'].items() if not ok), None)} "
                      f"final={v['first_failing_check_final']} "
                      f"strict={v['accepted_strict']} "
                      f"checkbacked={v['accepted_checkbacked']} "
                      f"({v['receipt_repair'].get('rounds')} rr-rounds)",
                      flush=True)
        row["seconds"] = round(time.time() - t0, 1)
        trials.append(row)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({
            "schema": 1,
            "description": ("Repeated constrained-pipeline trials on the "
                            "pinned DW APB SSI extraction; per backend, "
                            "first pass (compile repair disabled), post "
                            "compile-repair, and post receipt-repair gate "
                            "check states on the same candidate"),
            "model": settings.model,
            "temperature": settings.temperature,
            "trials_requested": args.trials,
            "backends": backend_names,
            "trials": trials,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  trial {t} complete ({row['seconds']}s) -> "
              f"{args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
