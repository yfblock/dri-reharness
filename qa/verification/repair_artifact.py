#!/usr/bin/env python3
"""Bounded LLM repair loop for a generated backend artifact.

Runs the artifact's compile check (the same commands the 18-item
checklist uses), and if it fails, asks the configured LLM to repair the
artifact given the exact compiler diagnostics; repeats up to --max-rounds.
Every round is recorded (model, round, digest before/after) into the run
transcript so the paper can cite the iteration count honestly.

Usage: repair_artifact.py <artifact> <harness|baremetal|linux|rust>
                           [--max-rounds 3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(ROOT / "src"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

EX = ROOT / "examples" / "dw-apb-ssi"
OUT = (ROOT / "research" / "experiments" / "results"
       / "artifact-repair-log.json")

PROMPT = """The following generated {kind} artifact fails to compile.
Fix ONLY the compile errors; do not remove register accesses, receipts
(REHARNESS_RIS_OP comments), or anchor labels (__rh_op_...), and do not
change program structure beyond what the diagnostics require.

===== ARTIFACT ({path}) =====
```{lang}
{code}
```

===== COMPILER DIAGNOSTICS =====
```
{diagnostics}
```

Return the COMPLETE corrected artifact as one fenced {lang} block. Do not
omit any part of the artifact; do not add commentary.
"""


SPAN_PROMPT = """The following SPAN of a generated {kind} artifact fails to
compile. Fix ONLY the compile errors in this span; do not remove register
accesses, receipts (REHARNESS_RIS_OP comments), or anchor labels
(__rh_op_...), do not rename functions, and do not change program structure
beyond what the diagnostics require.

===== SPAN OF {path} =====
```{lang}
{code}
```

===== COMPILER DIAGNOSTICS (line numbers refer to the full artifact; the
span starts at artifact line {first_line}) =====
```
{diagnostics}
```

Return the COMPLETE corrected span (same lines, same order, nothing omitted,
nothing added outside the span) as one fenced {lang} block, no commentary.
"""


_DIAG_LINE = re.compile(r"(\w[\w./+-]*\.(?:c|h|rs)):(\d+):", re.M)


def _top_level_regions(text: str) -> list[tuple[int, int]]:
    """Spans of top-level items: (start_line, end_line) inclusive, 1-based.

    A region starts at the first non-blank, non-comment-continuation line
    when the brace depth is zero, and ends when the depth returns to zero
    after having consumed content.  Preprocessor lines and // or /* */
    comments belong to the following region.
    """
    lines = text.split("\n")
    regions: list[tuple[int, int]] = []
    depth = 0
    in_block_comment = False
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            if start is None and depth == 0:
                start = i
            continue
        if not stripped:
            continue
        if start is None and depth == 0:
            start = i
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            depth = 0
            if start is not None:
                regions.append((start, i))
                start = None
    if start is not None:
        regions.append((start, len(lines) - 1))
    return regions


def _span_for_diag(text: str, diag: str, cap: int = 60000) -> tuple[int, int] | None:
    """Smallest contiguous top-level-region span covering all error lines.

    Regions defining a struct named by a ``'struct X' has no member``
    diagnostic are pulled in even when the error line lies elsewhere, since
    the fix is a member declaration inside the struct.
    """
    lines = text.split("\n")
    hit = set()
    for match in _DIAG_LINE.finditer(diag):
        hit.add(int(match.group(2)))
    regions = _top_level_regions(text)
    linker_syms = set(re.findall(
        r"undefined reference to [`‘'](\w+)", diag))
    if not hit and not linker_syms:
        return None
    pulled = []
    # gcc quotes diagnostics with Unicode curly quotes when writing to a tty
    # and ASCII quotes when captured; accept both.
    for name in set(re.findall(r"['‘']struct (\w+)['’']", diag)):
        for idx, (a, b) in enumerate(regions):
            body = "\n".join(lines[a:b + 1])
            if re.search(rf"\bstruct\s+{re.escape(name)}\s*\{{", body):
                pulled.append(regions[idx])
                break
    containing = [r for r in regions
                  if any(r[0] + 1 <= ln <= r[1] + 1 for ln in hit)]
    if not containing and linker_syms:
        # linker errors carry no file:line; map each undefined symbol to
        # the regions that reference it instead
        for sym in linker_syms:
            for r in regions:
                if re.search(rf"\b{re.escape(sym)}\s*\(",
                             "\n".join(lines[r[0]:r[1] + 1])):
                    containing.append(r)
        containing = list(dict.fromkeys(containing))
    if not containing and not pulled:
        return None
    picked = containing + pulled
    first = min(r[0] for r in picked)
    last = max(r[1] for r in picked)
    if sum(len(line) for line in lines[first:last + 1]) > cap:
        return None
    return (first, last)


def _compile_check(backend: str, artifact: Path, tmp: Path, *,
                   single: bool = False) -> tuple[bool, str]:
    if backend == "harness":
        stage = tmp / "h"
        stage.mkdir()
        shutil.copy(artifact, stage / "dw_spi_harness.c")
        if not single:
            for src, dst in (("dw_spi_harness.h", "dw_apb_ssi_harness.h"),
                             ("dw_spi_harness.h", "dw_spi_harness.h")):
                if (EX / src).is_file():
                    shutil.copy(EX / src, stage / dst)
        r = subprocess.run(
            ["cc", "-Wall", "-Werror", "-Wno-unused-label", "-I", str(stage),
             "-o", str(tmp / "h.bin"), str(stage / "dw_spi_harness.c")],
            capture_output=True, text=True, timeout=120)
    elif backend == "baremetal":
        stage = tmp / "b"
        stage.mkdir()
        shutil.copy(artifact, stage / "dw_spi_baremetal.c")
        if not single:
            for src, dst in (("dw_spi_baremetal.h", "dw_apb_ssi_baremetal.h"),
                             ("dw_spi_baremetal.h", "dw_spi_baremetal.h")):
                if (EX / src).is_file():
                    shutil.copy(EX / src, stage / dst)
        r = subprocess.run(
            ["cc", "-ffreestanding", "-Wall", "-Werror", "-Wno-unused-label",
             "-I", str(stage), "-c", "-o", str(tmp / "b.o"),
             str(stage / "dw_spi_baremetal.c")],
            capture_output=True, text=True, timeout=120)
    elif backend == "linux":
        kernel = ROOT / "platform" / "kernel" / "build"
        moddir = tmp / "l"
        moddir.mkdir()
        shutil.copy(artifact, moddir / "dw_apb_ssi_linux.c")
        if not single and (EX / "dw_apb_ssi_linux.h").is_file():
            shutil.copy(EX / "dw_apb_ssi_linux.h",
                        moddir / "dw_apb_ssi_linux.h")
        (moddir / "Makefile").write_text("obj-m += dw_apb_ssi_linux.o\n")
        r = subprocess.run(
            ["make", "-C", str(kernel), f"M={moddir}", "modules"],
            capture_output=True, text=True, timeout=600)
        ok = (r.returncode == 0
              and (moddir / "dw_apb_ssi_linux.ko").is_file())
        return ok, ("" if ok else (r.stdout + r.stderr)[-4000:])
    elif backend == "rust":
        proj = tmp / "rustproj"
        (proj / "src").mkdir(parents=True)
        (proj / "Cargo.toml").write_text(
            '[package]\nname = "dw_apb_ssi_check"\nversion = "0.1.0"\n'
            'edition = "2021"\n\n[dependencies]\ntock-registers = "=0.8.1"\n'
            '\n[profile.dev]\npanic = "abort"\n')
        shutil.copy(artifact, proj / "src" / "lib.rs")
        import os
        r = subprocess.run(
            ["cargo", "build", "--offline"], cwd=proj,
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "CARGO_NET_OFFLINE": "true"})
    else:
        raise ValueError(f"unknown backend {backend}")
    return r.returncode == 0, ("" if r.returncode == 0
                               else r.stderr[-4000:])


_FENCE_LANG = {"harness": "c", "baremetal": "c", "linux": "c",
               "rust": "rust"}

_RECEIPT_MARK = re.compile(
    r"REHARNESS_(?:RIS|TRANSACTION)_OP\s+id=")


def _receipt_count(text: str) -> int:
    return len(_RECEIPT_MARK.findall(text))


def _replacement_ok(new: str, old: str) -> bool:
    """Reject truncated repair responses before they are written.

    A span replacement must preserve every receipt that lived in the span
    and must not collapse the span to a stub; the same applies to a
    whole-file replacement.  Without this guard a response that silently
    omits middle sections deletes lowering evidence outright.
    """
    if _receipt_count(new) < _receipt_count(old):
        return False
    old_len = len(old.strip())
    return old_len == 0 or len(new.strip()) >= max(200, old_len // 3)


def _extract_block(raw: str, lang: str) -> str:
    fence = re.search(r"```" + lang + r"(?:\s|\n)(.*?)```", raw, re.S)
    if fence is None:
        fence = re.search(r"```(?:\s|\n)(.*?)```", raw, re.S)
    if fence is not None:
        return fence.group(1).strip() + "\n"
    # Models sometimes emit the span bare, without the requested fence.
    # Accept the raw response only when it plausibly is source code.
    if _looks_like_code(raw):
        return raw.strip() + "\n"
    raise RuntimeError("no fenced code block in repair response")


def _looks_like_code(raw: str) -> bool:
    if not raw.strip() or raw.strip().startswith("```"):
        return False
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    with_brace = sum("{" in ln for ln in lines)
    with_semi = sum(";" in ln for ln in lines)
    if ("see corrected code" in raw or "I cannot" in raw
            or "sorry" in raw.lower()):
        return False
    # tock-registers macro blocks are comma-separated, not semicolon-
    # terminated; recognize them structurally instead
    if (sum("OFFSET(" in ln for ln in lines) >= 3
            or sum(ln.startswith("register_") for ln in lines) >= 1
            or sum(re.search(r"\bfn\s+\w+\s*\(", ln) is not None
                   for ln in lines) >= 1):
        return True
    # declaration-heavy C spans (prototypes, struct members) may carry no
    # braces at all; accept them on punctuation density alone
    if with_semi >= max(2, len(lines) // 8) and sum(
            "(" in ln for ln in lines) >= 2:
        return True
    return with_brace >= 1 and with_semi >= max(2, len(lines) // 8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact")
    ap.add_argument("backend",
                    choices=["harness", "baremetal", "linux", "rust"])
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--single", action="store_true",
                    help="compile the artifact standalone (pre-split chunked "
                         "generation, no versioned header pair)")
    args = ap.parse_args()

    from langchain_bridge import load_langchain_settings, call_langchain
    settings = load_langchain_settings()
    artifact = Path(args.artifact)
    rounds = []

    def _call(prompt: str, hard_timeout: int = 900) -> str:
        """call_langchain with a wall-clock alarm the stream cannot outlive."""
        result: dict[str, object] = {}

        def _fire(signum, frame):
            raise TimeoutError(f"repair LLM call exceeded {hard_timeout}s")

        old = signal.signal(signal.SIGALRM, _fire)
        signal.alarm(hard_timeout)
        try:
            result["raw"] = call_langchain(prompt, timeout=600)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        return result["raw"]

    for i in range(args.max_rounds + 1):
        with tempfile.TemporaryDirectory() as td:
            ok, diag = _compile_check(args.backend, artifact, Path(td),
                                      single=args.single)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
        rounds.append({"round": i, "compile_ok": ok,
                       "sha256_16": digest,
                       "diagnostics_tail": diag[-600:] if not ok else ""})
        print(f"round {i}: {'OK' if ok else 'FAIL'} ({digest})")
        if ok:
            break
        if i == args.max_rounds:
            break
        code = artifact.read_text(encoding="utf-8")
        span = _span_for_diag(code, diag)
        if span is not None:
            a, b = span
            lines = code.split("\n")
            span_text = "\n".join(lines[a:b + 1])
            prompt = SPAN_PROMPT.format(
                kind=f"{args.backend} backend", path=artifact.name,
                lang=_FENCE_LANG[args.backend], code=span_text,
                diagnostics=diag, first_line=a + 1)
            rounds[-1]["span"] = [a + 1, b + 1]
        else:
            span_text = code
            prompt = PROMPT.format(
                kind=f"{args.backend} backend", path=artifact.name,
                lang=_FENCE_LANG[args.backend], code=code, diagnostics=diag)
        t0 = time.time()
        block = None
        raw_kept = ""
        for attempt in range(3):
            raw = ""
            try:
                raw = _call(prompt)
            except (TimeoutError, Exception) as exc:  # noqa: BLE001 - retry
                rounds[-1]["error"] = str(exc)[-300:]
                print(f"repair call failed: {str(exc)[-160:]}")
                time.sleep(10 * (attempt + 1))
                continue
            if not raw or not raw.strip():
                print(f"empty response (attempt {attempt + 1}); retrying")
                rounds[-1][f"empty_attempt_{attempt + 1}"] = True
                continue
            try:
                cand = _extract_block(raw, _FENCE_LANG[args.backend])
            except RuntimeError as exc:
                rounds[-1]["error"] = str(exc)
                rounds[-1]["raw_head"] = raw[:300]
                dump = Path(os.environ.get("CLAUDE_JOB_DIR", "/tmp")) / "tmp" / (
                    f"repair-raw-{args.backend}-{i}-{attempt}.txt")
                try:
                    dump.write_text(raw, encoding="utf-8")
                except OSError:
                    pass
                print(f"{exc}; retrying")
                continue
            if not _replacement_ok(cand, span_text):
                rounds[-1]["error"] = "truncated repair response rejected"
                dump = Path(os.environ.get("CLAUDE_JOB_DIR", "/tmp")) / "tmp" / (
                    f"repair-truncated-{args.backend}-{i}-{attempt}.txt")
                try:
                    dump.write_text(raw, encoding="utf-8")
                except OSError:
                    pass
                print("guard: repair response dropped receipts or collapsed "
                      "the span; retrying")
                continue
            block = cand
            raw_kept = raw
            break
        rounds[-1]["repair_seconds"] = round(time.time() - t0, 1)
        if block is None:
            print("no usable repair response; stopping")
            break
        if not block.strip():
            print("empty repair response; stopping")
            break
        if span is not None:
            lines = code.split("\n")
            lines[a:b + 1] = block.rstrip("\n").split("\n")
            artifact.write_text("\n".join(lines), encoding="utf-8")
        else:
            artifact.write_text(block, encoding="utf-8")

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
        "model": settings.model,
        "temperature": settings.temperature,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rounds": rounds,
        "compile_ok": rounds[-1]["compile_ok"],
    })
    OUT.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"log -> {OUT}")
    return 0 if rounds[-1]["compile_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
