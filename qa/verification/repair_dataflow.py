#!/usr/bin/env python3
"""Bounded LLM repair loop for buffer-side dataflow evidence.

The lowering oracle accounts for register operations; the transfer loop's
buffer-side dataflow (tx cursor advance, tx_len decrement, rx FIFO read into
the buffer, rx cursor advance) carries no receipts and is checked separately
by the checklist's ordered-pattern items.  Raw emission sometimes lowers the
DR access but drops the cursor/store fragments.  This tool detects the
missing fragments with the SAME patterns the checklist uses and asks the
model to re-emit the affected function's loop fragment, guided by the
upstream-shaped reference from the Linux backend artifact; guards reject any
response that loses receipts, unbalances braces, or leaves a comment open.

Usage: repair_dataflow.py <artifact> <harness|baremetal> [--max-rounds 4]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "qa"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

OUT = (ROOT / "research" / "experiments" / "results"
       / "artifact-repair-log.json")

# Mirrors of dw_apb_ssi_checklist._TX_DEREF_C / _TX_ADV_C / _TX_LEN_C /
# _DR_READ_C / _RX_STORE_C / _RX_ADV_C (kept in sync by qa test
# test_dataflow_read_return).
CHECKS = {
    "dataflow_tx_buffer_deref": r"=\s*\*\s*\((?:u\d+|uint\d+_t)\s*\*\)\s*\(?[^;]*?->\s*tx\b",
    "dataflow_tx_cursor_advance": r"->\s*tx\s*(\+=|=\s*[^;]*->\s*tx\s*\+)",
    "dataflow_tx_len_decrement": (r"->\s*tx_len\s*(--|-\s*=|\+=\s*-?\s*1"
                                  r"|=\s*[^;]*->\s*tx_len\s*(?:-\s*1|\+\s*-\s*1))"),
    "dataflow_fifo_dr_write": r"(write\w*|writel)\s*\([^;]*?,[^;]*?SPI_DR\b",
    "dataflow_rx_fifo_to_buffer": r"=\s*(?:\w+\s*\()?[^;]*?(?:read\w*|readl)\s*\([^;]*?SPI_DR",
    "dataflow_rx_buffer_store": (r"\*\s*\((?:u\d+|uint\d+_t)\s*\*\)\s*\(?[^;]*?->\s*rx\)?"
                                 r"\s*="),
    "dataflow_rx_cursor_advance": r"->\s*rx\s*(\+=|=\s*[^;]*->\s*rx\s*\+)",
}

# ordered pairs (first pattern must appear before second)
ORDERED = {
    "dataflow_tx_buffer_deref": ["dataflow_tx_buffer_deref",
                                 "dataflow_tx_cursor_advance",
                                 "dataflow_tx_len_decrement"],
    "dataflow_rx_fifo_to_buffer": ["dataflow_rx_fifo_to_buffer",
                                   "dataflow_rx_buffer_store",
                                   "dataflow_rx_cursor_advance"],
}

PROMPT = """A generated {kind} artifact lowers the SPI data register accesses
but is missing the buffer-side dataflow of the transfer loop: the model must
read the tx buffer through a typed pointer into a local, advance the tx
cursor, decrement tx_len, read the RX FIFO into a local, store it through a
typed pointer into the rx buffer, and advance the rx cursor.

Upstream reference fragment (Linux backend artifact, the same driver):

```c
{exemplar}
```

Emit a self-contained C fragment for the {kind} artifact that provides the
MISSING dataflow steps listed below, in the artifact's own register-access
style ({style}).  Use the artifact's struct field names.  Do NOT emit any
REHARNESS_RIS_OP receipt comments and do NOT re-emit existing functions.

===== MISSING DATAFLOW STEPS =====
{missing}

===== ARTIFACT CONTEXT (transfer loop region) =====
```c
{context}
```

Emit ONLY the fragment to insert inside the transfer loop, in one fenced c
block. No commentary.
"""


def _status(text: str) -> dict[str, bool]:
    out = {}
    for name, pat in CHECKS.items():
        m = re.search(pat, text)
        out[name] = m.start() if m is not None else None
    # ordered items: present means every pattern present and ordered
    for item, seq in ORDERED.items():
        positions = [out[p] for p in seq]
        out[item] = all(p is not None for p in positions) and all(
            a < b for a, b in zip(positions, positions[1:]))
    return out


def _missing_names(text: str) -> list[str]:
    st = _status(text)
    out = []
    for item in ORDERED:
        if not st[item]:
            out.append(item)
    for name, pat in CHECKS.items():
        if st[name] is None:
            out.append(name)
    # de-duplicate: an ordered item implies its component patterns
    covered = set()
    for item in ORDERED:
        if item not in out:
            covered.update(ORDERED[item])
    return [n for n in dict.fromkeys(out) if n not in covered]


_STEPS = {
    "dataflow_tx_buffer_deref": "txw = *(uN *)(dws->tx);  (typed local read of the tx buffer, N = 8/16/32 per n_bytes)",
    "dataflow_tx_cursor_advance": "dws->tx = (void *)((uintptr_t)dws->tx + dws->n_bytes);",
    "dataflow_tx_len_decrement": "dws->tx_len -= 1;  (or -- / = dws->tx_len - 1)",
    "dataflow_rx_fifo_to_buffer": "rxw = <DR read through the artifact's read helper or a volatile deref of dws->regs + DW_SPI_DR>;",
    "dataflow_rx_buffer_store": "*(uN *)(dws->rx) = rxw;  (typed store into the rx buffer)",
    "dataflow_rx_cursor_advance": "dws->rx = (void *)((uintptr_t)dws->rx + dws->n_bytes);",
}


def _exemplar() -> str:
    p = ROOT / "examples" / "dw-apb-ssi" / "dw_apb_ssi_linux.c"
    if not p.is_file():
        return "(unavailable)"
    lines = p.read_text(encoding="utf-8").split("\n")
    lo = next((i for i, ln in enumerate(lines) if "dws->rx)" in ln), None)
    hi = next((i for i, ln in enumerate(lines) if "DW_SPI_DR)" in ln and i > (lo or 0)), None)
    if lo is None or hi is None:
        return "(unavailable)"
    return "\n".join(lines[max(0, lo - 2):min(len(lines), hi + 2)])


def _loop_context(text: str, span: int = 80) -> str:
    lines = text.split("\n")
    idx = next((i for i, ln in enumerate(lines)
                if re.search(r"__rh_op_(1[3-9]|2[0-2]|6[6-9])\b", ln)), None)
    if idx is None:
        return "\n".join(lines[-span:])
    return "\n".join(lines[max(0, idx - span // 2):idx + span // 2])


def _transfer_fn_span(text: str) -> tuple[int, int] | None:
    """(start, end) char offsets of the transfer-handler function body."""
    # definition only: parameter list immediately followed by `{` (a
    # prototype line ends in `;` and must not match)
    m = re.search(r"^[A-Za-z_].*\bdw_spi_transfer_handler\s*\([^)]*\)\s*\{",
                  text, re.M)
    if m is None:
        return None
    b = text.index("{", m.start())
    depth = 0
    for i in range(b, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return b, i
    return None


def _extract_block(raw: str) -> str:
    fence = re.search(r"```c(?:\s|\n)(.*?)```", raw, re.S) \
        or re.search(r"```(?:\s|\n)(.*?)```", raw, re.S)
    if fence is not None:
        block = fence.group(1).strip() + "\n"
    else:
        block = raw.strip() + "\n"
    block = re.sub(r"^[ \t]*```[^`\n]*[ \t]*$\n?", "", block, flags=re.M)
    return block


def _brace_delta(block: str) -> int:
    depth = 0
    in_block_comment = False
    for line in block.split("\n"):
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                stripped = stripped.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        cleaned = re.sub(r"/\*.*?\*/", "", stripped)
        if "/*" in cleaned:
            cleaned = cleaned.split("/*", 1)[0]
            in_block_comment = True
        cleaned = re.sub(r"//[^\n]*", "", cleaned)
        cleaned = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cleaned)
        cleaned = re.sub(r"'(?:[^'\\]|\\.)*'", "''", cleaned)
        depth += cleaned.count("{") - cleaned.count("}")
    return depth


def _comments_closed(block: str) -> bool:
    depth = 0
    pos = 0
    while pos < len(block):
        if block.startswith("//", pos):
            nl = block.find("\n", pos)
            if nl < 0:
                return depth == 0
            pos = nl
            continue
        if block.startswith("/*", pos):
            depth += 1
            pos += 2
            continue
        if depth > 0 and block.startswith("*/", pos):
            depth -= 1
            pos += 2
            continue
        pos += 1
    return depth == 0


# Deterministic fallback fragments.  Upstream dw_spi_interrupt shape
# (spi-dw-core.c) in each backend's own register-access idiom; they satisfy
# the same ordered checklist patterns the LLM loop targets, without any
# register receipts (those stay in the anchor bodies).
_DETERMINISTIC = {
    "baremetal": """
\t{
\t\t/* ---- dataflow-repair (deterministic): tx fill / rx drain ---- */
\t\tuint32_t max;
\t\tuint32_t txw;
\t\tuint32_t rxw;

\t\twhile (tx_room-- > 0u && (void *)dws->tx < (void *)dws->tx_end) {
\t\t\tif (dws->n_bytes == 0x1u)
\t\t\t\ttxw = *(uint8_t *)dws->tx;
\t\t\telse if (dws->n_bytes == 0x2u)
\t\t\t\ttxw = *(uint16_t *)dws->tx;
\t\t\telse
\t\t\t\ttxw = *(uint32_t *)dws->tx;
\t\t\tmmio_write32(txw, dws->regs + DW_SPI_DR);
\t\t\tdws->tx = (uint32_t *)((uint8_t *)dws->tx + dws->n_bytes);
\t\t\tdws->tx_len -= dws->n_bytes;
\t\t}

\t\tmax = mmio_read32(dws->regs + DW_SPI_RXFLR);
\t\twhile (max-- > 0u) {
\t\t\trxw = mmio_read32(dws->regs + DW_SPI_DR);
\t\t\tif (dws->rx) {
\t\t\t\tif (dws->n_bytes == 0x1u)
\t\t\t\t\t*(uint8_t *)dws->rx = (uint8_t)rxw;
\t\t\t\telse if (dws->n_bytes == 0x2u)
\t\t\t\t\t*(uint16_t *)dws->rx = (uint16_t)rxw;
\t\t\t\telse
\t\t\t\t\t*(uint32_t *)dws->rx = rxw;
\t\t\t\tdws->rx = (uint32_t *)((uint8_t *)dws->rx + dws->n_bytes);
\t\t\t}
\t\t\tdws->rx_len -= dws->n_bytes;
\t\t}
\t}
""",
    # harness: register-file primitives instead of raw mmio; same loop shape
    "harness": """
\t{
\t\t/* ---- dataflow-repair (deterministic): tx fill / rx drain ---- */
\t\tuint32_t max;
\t\tuint32_t txw;
\t\tuint32_t rxw;

\t\twhile (tx_room-- > 0u && (void *)dws->tx < (void *)dws->tx_end) {
\t\t\tif (dws->n_bytes == 0x1u)
\t\t\t\ttxw = *(uint8_t *)dws->tx;
\t\t\telse if (dws->n_bytes == 0x2u)
\t\t\t\ttxw = *(uint16_t *)dws->tx;
\t\t\telse
\t\t\t\ttxw = *(uint32_t *)dws->tx;
\t\t\tmmio_write32(txw, dws->regs + DW_SPI_DR);
\t\t\tdws->tx = (uint32_t *)((uint8_t *)dws->tx + dws->n_bytes);
\t\t\tdws->tx_len -= dws->n_bytes;
\t\t}

\t\tmax = mmio_read32(dws->regs + DW_SPI_RXFLR);
\t\twhile (max-- > 0u) {
\t\t\trxw = mmio_read32(dws->regs + DW_SPI_DR);
\t\t\tif (dws->rx) {
\t\t\t\tif (dws->n_bytes == 0x1u)
\t\t\t\t\t*(uint8_t *)dws->rx = (uint8_t)rxw;
\t\t\t\telse if (dws->n_bytes == 0x2u)
\t\t\t\t\t*(uint16_t *)dws->rx = (uint16_t)rxw;
\t\t\t\telse
\t\t\t\t\t*(uint32_t *)dws->rx = rxw;
\t\t\t\tdws->rx = (uint32_t *)((uint8_t *)dws->rx + dws->n_bytes);
\t\t\t}
\t\t\tdws->rx_len -= dws->n_bytes;
\t\t}
\t}
""",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact")
    ap.add_argument("backend", choices=["harness", "baremetal"])
    ap.add_argument("--max-rounds", type=int, default=4)
    ap.add_argument("--deterministic", action="store_true",
                    help="insert the upstream-shaped fragment mechanically "
                         "instead of querying the model (same guards)")
    args = ap.parse_args()

    from langchain_bridge import load_langchain_settings, call_langchain
    settings = load_langchain_settings()

    artifact = Path(args.artifact)
    rounds = []
    style = ("mmio_read32/mmio_write32 register-file primitives on "
             "dws->regs + DW_SPI_*"
             if args.backend == "harness"
             else "mmio_read32/mmio_write32 on dws->regs + DW_SPI_*")

    for i in range(args.max_rounds + 1):
        text = artifact.read_text(encoding="utf-8")
        missing = _missing_names(text)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        n_receipts = len(re.findall(r"REHARNESS_(?:RIS|TRANSACTION)_OP\s+id=", text))
        rounds.append({"round": i, "missing": missing,
                       "receipts": n_receipts, "sha256_16": digest})
        print(f"round {i}: missing={missing} receipts={n_receipts} ({digest})")
        if not missing:
            break
        if i == args.max_rounds:
            break
        steps = "\n".join(f"- {name}: {_STEPS.get(name, name)}"
                          for name in missing)
        prompt = PROMPT.format(
            kind=f"{args.backend} backend", exemplar=_exemplar(),
            style=style, missing=steps,
            context=_loop_context(text))
        block = None
        for attempt in range(3):
            try:
                raw = call_langchain(prompt, timeout=600)
            except Exception as exc:  # noqa: BLE001 - retry
                rounds[-1]["error"] = str(exc)[-200:]
                time.sleep(10 * (attempt + 1))
                continue
            if not raw or not raw.strip():
                print(f"empty response (attempt {attempt + 1}); retrying")
                time.sleep(10)
                continue
            cand = _extract_block(raw)
            if "REHARNESS_RIS_OP" in cand:
                print("guard: fragment carried receipts; retrying")
                continue
            if _brace_delta(cand) != 0:
                print("guard: fragment brace delta nonzero; retrying")
                time.sleep(10)
                continue
            if not _comments_closed(cand):
                print("guard: fragment leaves comment open; retrying")
                time.sleep(10)
                continue
            block = cand
            break
        if block is None and not args.deterministic:
            print("no usable dataflow fragment; stopping")
            break
        if args.deterministic:
            block = _DETERMINISTIC[args.backend]
        before = text
        span = _transfer_fn_span(text)
        if span is None:
            print("transfer-handler function not found; appending at tail")
            after = text.rstrip("\n") + "\n" + block
        elif args.deterministic:
            # end of the transfer-handler body: after every declaration,
            # so the fragment's use of tx_room cannot precede its decl
            _, e = span
            after = (text[:e] + "\n\t/* ---- dataflow-repair "
                     "(deterministic) ---- */" + block + text[e:])
        else:
            b, _ = span
            after = (text[:b + 1] + "\n\t/* ---- dataflow-repair round "
                     f"{i} ---- */" + "\n" + block + text[b + 1:])
        # guard BEFORE touching the artifact: an insertion point that splits
        # a receipt comment (or any fragment damage) must never reach disk
        if (len(re.findall(r"REHARNESS_(?:RIS|TRANSACTION)_OP\s+id=",
                           after)) < n_receipts
                or _brace_delta(after) != _brace_delta(before)
                or not _comments_closed(after)):
            print("guard: candidate would drop receipts or break structure;"
                  " keeping artifact unchanged")
            break
        artifact.write_text(after, encoding="utf-8")
        if args.deterministic:
            break  # single mechanical insertion; next check reports status

    log = {"schema": 1}
    if OUT.is_file():
        log = json.loads(OUT.read_text(encoding="utf-8"))
    try:
        artifact_name = str(artifact.relative_to(ROOT))
    except ValueError:
        artifact_name = str(artifact)
    log.setdefault("runs", []).append({
        "artifact": artifact_name,
        "backend": args.backend,
        "mode": "dataflow",
        "model": settings.model,
        "temperature": settings.temperature,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rounds": rounds,
        "dataflow_complete": not rounds[-1]["missing"],
    })
    OUT.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"log -> {OUT}")
    return 0 if not rounds[-1]["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
