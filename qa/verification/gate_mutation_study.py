#!/usr/bin/env python3
"""Gate mutation study: does the verification gate reject the motivating
fault classes advertised in the paper's introduction?

For a pinned generated harness artifact, the study runs the unchanged
backend verification pipeline (compile + run + trace subsequence, receipt
accounting, AST leaf anchors, lowering plan) on the pristine artifact and
on four text-level mutations that mirror the motivating faults:

  M1 extra_write       an invented MMIO write to an unmapped offset
                       (the ``DMA_CMD|DMA_IRQ`` class of hallucination)
  M2 drop_irq_ack      the interrupt status/acknowledge read is deleted
  M3 width_shrink      a 32-bit register access is narrowed to 16 bits
  M4 reorder_rx_cursor the rx buffer cursor advances before the FIFO value
                       is stored into the buffer

Each mutant is rejected iff any gate check fails; the first failing check
is recorded.  A mutant that passes is reported as passing -- that is a
measured gate boundary, not a study failure.

Usage: gate_mutation_study.py <harness.c> [--manifest <multisource.json>]
                              [--out <results.json>]
                              [--with-header <header.h>]

--with-header concatenates the versioned header (minus its include guard)
ahead of the source body so a header/source pair artifact can be replayed
through the single-file gate; mutations are applied to the combined text.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
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

CACHE = ROOT / "artifacts" / "cache" / "gate-mutation-extraction.pkl"
DEFAULT_OUT = (ROOT / "research" / "experiments" / "results"
               / "dw-gate-mutation-study.json")


def _load_extraction(manifest: str):
    """Run (or reload from cache) the DW extraction used by the gate."""
    from extractor.extractor import ExtractorConfig, extract_ris

    key = (manifest,)
    if CACHE.is_file():
        with open(CACHE, "rb") as fh:
            cached_key, res = pickle.load(fh)
        if cached_key == key:
            return res
    cfg = ExtractorConfig(
        source=manifest,
        output=str(ROOT / "artifacts" / "cache" / "gate-mutation.ris"),
        compile_context_mode="auto",
        ir_mode="auto",
    )
    res = extract_ris(cfg)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump((key, res), fh)
    return res


# -- mutations --------------------------------------------------------------

def mut_extra_write(text: str) -> str | None:
    """M1: invented write to an offset no contract operation maps."""
    anchor = re.search(r"\n([ \t]*)[^\n;]*?" + _DR_WRITE, text)
    if anchor is None:
        return None
    stmt = anchor.group(0)
    recv = re.search(r"(\w+)\s*->\s*regs\b", stmt)
    base = f"{recv.group(1)}->regs" if recv else "base"
    indent = anchor.group(1)
    invented = (f"\n{indent}/* M1: invented DMA-command write (unmapped "
                f"offset) */\n{indent}mmio_write32(0x3u, {base} + 0x9cu);")
    return text[:anchor.end()] + invented + text[anchor.end():]


_STATUS_REG = r"DW_SPI_(?:ISR|RISR)"

# the DR write, in either accessor idiom the pipeline emits: a helper call
# (harness_write32 / mmio_write32 / dw_write_io_reg) or the raw volatile
# dereference form the anchors carry
_DR_WRITE = (r"(?:(?:harness|mmio)_write32\([^;\n]*?"
             r"(?:DW_SPI_DR|regs \+ 0x0)[^;\n]*?\)[^;\n]*?;"
             r"|(?:dw_write_io_reg|dw_read_io_reg)\([^;\n]*DW_SPI_DR[^;\n]*\)[^;\n]*?;"
             r"|\*\s*\(volatile uint32_t \*\)[^;\n]*?"
             r"(?:DW_SPI_DR|regs \+ 0x0)[^;\n]*?;)")

# any 32-bit status-register read, helper or raw-deref spelling
_STATUS_READ32 = (r"(?:(?:harness|mmio)_read32\(([^)]*" + _STATUS_REG
                  + r")\)"
                  r"|\*\s*\(volatile uint32_t \*\)\(([^)]*" + _STATUS_REG
                  + r")\))")


def _drop_read_block(text: str, register: str) -> str | None:
    """Remove the anchored read block (receipt + anchor + statement)."""
    pat = re.compile(
        r"[ \t]*/\* REHARNESS_RIS_OP[^*]*\*/\s*\n"
        r"[ \t]*__rh_op_\S+:\s*\{[^{}]*?"
        + register + r"[^{}]*?\}\s*\n?",
        re.S)
    if pat.search(text):
        return pat.sub("", text, count=1)
    line_pat = re.compile(
        r"^[ \t]*\S[^\n]*" + register + r"[^\n]*\n", re.M)
    if line_pat.search(text):
        return line_pat.sub("", text, count=1)
    return None


def mut_drop_irq_ack(text: str) -> str | None:
    """M2: the interrupt status read disappears (receipt goes with it)."""
    return _drop_read_block(text, _STATUS_REG)


def mut_width_shrink(text: str) -> str | None:
    """M3: a 32-bit status read narrows to 16 bits."""
    target = re.search(_STATUS_READ32, text)
    if target is None:
        return None
    if target.group(1) is not None:  # helper spelling
        arg = target.group(1)
        return (text[:target.start()] + "mmio_read16(" + arg + ")"
                + text[target.end():])
    # raw volatile dereference spelling: narrow the cast
    addr = target.group(2)
    return (text[:target.start()]
            + "*(volatile uint16_t *)(" + addr + ")"
            + text[target.end():])


_RX_STORE = (r"\n([ \t]*)\*\s*\(u?int8_t\s*\*\)[^;\n=]*?"
             r"([\w]+(?:\.\w+)*(?:->\s*rx)?)\s*(?:\(void\s*\*\))?\s*=")
# rx cursor advance, statement-anchored so the match cannot start inside
# another expression: byte-index `+=`, or pointer re-assignment through any
# integer-width cast shape (`(uint32_t *)((uint8_t *)rx + n_bytes)` and
# the `(void *)((uintptr_t)rx + n_bytes)` spelling alike)
_RX_ADV = (r"\n([ \t]*)(?:[\w]+(?:\.\w+)*->\s*)?rx\s*(?:\+=|"
           r"=\s*\(u?int\d+_t\s*\*\)\s*\(\(u?int\d+_t\s*\*\)[^;\n]*?"
           r"n_bytes|=\s*\(void\s*\*\)\s*\(\(uintptr_t\)[^;\n]*?n_bytes)")


def mut_reorder_rx_cursor(text: str) -> str | None:
    """M4: rx cursor advances before the FIFO value is stored (moved to
    right after the DR read, before the conditional buffer store)."""
    fifo_read = re.compile(
        r"\n([ \t]*)rxw\s*=\s*rh_dw_read32\([^;\n]*DW_SPI_DR[^;\n]*\);")
    advance = re.search(_RX_ADV + r"[^;\n]*;", text)
    read = fifo_read.search(text)
    if advance is None or read is None:
        return None
    adv_full = advance.group(0).strip()
    # delete the advance from the original text first, then re-locate the
    # FIFO read in the shortened text: reusing offsets from the first
    # search against modified text splices at stale positions
    out = text[:advance.start()] + text[advance.end():]
    read2 = fifo_read.search(out)
    if read2 is None:
        return None
    indent = read2.group(1)
    return (out[:read2.end()]
            + f"\n{indent}{adv_full}   /* M4: advanced early */"
            + out[read2.end():])


def mut_receipt_without_semantics(text: str) -> str | None:
    """M5: keep a well-formed receipt and anchor label, replace the actual
    hardware access inside the anchor block with a constant so the mutant
    still compiles (receipt-without-semantics, not a syntax error)."""
    block = re.compile(r"(__rh_op_\S+:\s*\{)([^{}]*?)(\})")
    helper = re.compile(
        r"(\w+)\s*=\s*(?:harness|mmio)_read32\([^)]*"
        + _STATUS_REG + r"\);")
    raw = re.compile(
        r"(\w+)\s*=\s*\*\s*\(volatile uint32_t \*\)\([^)]*"
        + _STATUS_REG + r"\)\s*;")
    for m in block.finditer(text):
        for pat in (helper, raw):
            s = pat.search(m.group(2))
            if s is not None:
                gutted = (m.group(2)[:s.start()]
                          + f"{s.group(1)} = 0u; /* M5: hw access deleted */"
                          + m.group(2)[s.end():])
                return text[:m.start(2)] + gutted + text[m.end(2):]
    return None


MUTATIONS = [
    ("pristine", lambda t: t),
    ("M1_extra_write", mut_extra_write),
    ("M2_drop_irq_ack", mut_drop_irq_ack),
    ("M3_width_shrink", mut_width_shrink),
    ("M4_reorder_rx_cursor", mut_reorder_rx_cursor),
    ("M5_receipt_without_semantics", mut_receipt_without_semantics),
]


# -- gate runner ------------------------------------------------------------

def _run_gate(res, harness_text: str, workdir: Path) -> dict:
    """Run the unchanged backend pipeline on injected harness text.

    The pipeline's LLM compile-repair loop is disabled for the replay
    (REHARNESS_LLM_REPAIR_ROUNDS=0): the study measures whether the gate's
    CHECKS reject each mutant, and letting a repair pass rewrite the
    artifact first would measure the repair loop instead (an empty or
    partial endpoint response during replay also truncates the artifact
    under test).
    """
    import backends.registry as registry
    from backends.pipeline import run_backend_pipeline

    stub = SimpleNamespace(generate=lambda *a, **k: harness_text,
                           GEN_KWARGS=[])
    workdir.mkdir(parents=True, exist_ok=True)
    original = registry.list_backends
    original_repair_rounds = os.environ.get("REHARNESS_LLM_REPAIR_ROUNDS")
    os.environ["REHARNESS_LLM_REPAIR_ROUNDS"] = "0"
    registry.list_backends = lambda: {"harness": stub}
    try:
        # third argument is the driver manifest path, not a run label
        result = run_backend_pipeline(
            res, str(workdir),
            "benchmarks/drivers/multisource/dw-apb-ssi.json")
    finally:
        registry.list_backends = original
        if original_repair_rounds is None:
            os.environ.pop("REHARNESS_LLM_REPAIR_ROUNDS", None)
        else:
            os.environ["REHARNESS_LLM_REPAIR_ROUNDS"] = original_repair_rounds
    return result["gen_results"]["harness"]


_CHECK_FIELDS = (
    ("compile", lambda gr: gr.get("compiled") is True),
    ("receipt_accounting", lambda gr: gr.get("backend_lowering", {})
        .get("complete") is True),
    ("ast_leaf_anchors", lambda gr: gr.get("backend_ast_leaf_complete")
        is True),
    ("lowering_plan", lambda gr: gr.get(
        "backend_lowering_plan_strict_complete") is True),
    ("runtime_trace", lambda gr: gr.get("trace_passed") is True),
)


def _verdict(gr: dict) -> dict:
    checks = {name: bool(ok(gr)) for name, ok in _CHECK_FIELDS}
    first_fail = next((n for n, v in checks.items() if not v), None)
    return {
        "checks": checks,
        "rejected": first_fail is not None,
        "first_failing_check": first_fail,
        "lowering_detail": {
            key: gr.get("backend_lowering", {}).get(key)
            for key in ("missing", "duplicate", "digest_mismatch",
                        "kind_mismatch", "rejected")},
        "ast_detail": {
            key: (gr.get("backend_ast_leaf") or {}).get(key)
            for key in ("missing_anchors", "primitive_mismatches",
                        "unanchored_primitives", "duplicate_anchors")},
        "result_line": gr.get("result_line"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("harness_c")
    ap.add_argument("--manifest", default=str(
        ROOT / "benchmarks" / "drivers" / "multisource" / "dw-apb-ssi.json"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--with-header", default=None,
                    help="prepend this header (guard stripped) to the source "
                         "body so a header/source pair replays through the "
                         "single-file gate")
    args = ap.parse_args()

    text = Path(args.harness_c).read_text(encoding="utf-8")
    if args.with_header:
        header = Path(args.with_header).read_text(encoding="utf-8")
        # inline the header ahead of the source body; the source's
        # self-include of the generated header is dropped so the pair
        # replays through the single-file gate as one translation unit.
        # The header's include guard is KEPT: it is inactive exactly once,
        # and guard-stripping (by first-#endif or by depth-balancing the
        # outer guard, which encloses the whole file) truncates a
        # correctly-guarded header and silently drops its declarations.
        text = re.sub(r'^[ \t]*#[ \t]*include[ \t]*"'
                      r'[\w./+-]+"\n?', "", text, count=1)
        text = header + "\n" + text
        print(f"combined with header {args.with_header} "
              f"({len(text.splitlines())} lines)")
    print("extracting (cached after first run)...")
    res = _load_extraction(args.manifest)

    rows = []
    for name, fn in MUTATIONS:
        mutated = fn(text)
        if mutated is None:
            rows.append({"mutation": name, "applied": False,
                         "note": "pattern not found in artifact"})
            print(f"[skip] {name}: pattern not found")
            continue
        workdir = (ROOT / "artifacts" / "cache" / "gate-mutation"
                   / name)
        t0 = time.time()
        try:
            gr = _run_gate(res, mutated, workdir)
            row = {"mutation": name, "applied": True, **_verdict(gr)}
        except Exception as exc:  # gate itself exploded: counts as reject
            row = {"mutation": name, "applied": True,
                   "rejected": True, "first_failing_check": "gate_exception",
                   "exception": str(exc)[-500:]}
        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)
        verdict = ("REJECTED by " + str(row.get("first_failing_check"))
                   if row.get("rejected") else "PASSED gate")
        print(f"[{'x' if row.get('rejected') else ' '}] {name}: {verdict}")

    passed_mutants = [r["mutation"] for r in rows
                      if r.get("applied") and not r.get("rejected")]
    report = {
        "schema": 1,
        "artifact": str(Path(args.harness_c).resolve()),
        "description": ("Verification-gate mutation study on the generated "
                        "harness artifact; motivating fault classes from "
                        "the paper's introduction"),
        "mutations_total": sum(1 for r in rows if r.get("applied")),
        "mutations_rejected": sum(1 for r in rows
                                  if r.get("applied") and r.get("rejected")),
        "mutations_passed_gate": passed_mutants,
        "results": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"{report['mutations_rejected']}/{report['mutations_total']} "
          f"mutants rejected -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
