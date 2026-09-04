#!/usr/bin/env python3
"""Offline LLM annotator for external-call semantics (RIS 0.3.0).

The extractor records ExternalCall nodes deterministically and classifies
them with a rule table.  This tool drafts the *rest* of the semantics
(return / effects / parameter roles / porting hint) as reviewable data:

  scan    corpus extraction census → unknown-priority callee list
          (no LLM; deterministic; cached under artifacts/cache/)
  draft   for each target callee: locate the definition in the pinned
          vendor/linux tree, ground the model with the actual source,
          and ask for a CLOSED-category JSON annotation.  Drafts land in
          data/external-call-annotations.DRAFT.json — never the live
          store.  Humans review the diff and merge by hand.
  check   schema-validate a draft or the live store.

Design constraints (see dev-docs/external-call-annotations.md):
  - closed category enum only — free-form effect prose lives in fields,
    never in the classification;
  - every draft must cite a basis (file:line of the grounding source);
  - drafts without a locatable definition are marked declaration-only;
  - a missing/failed LLM never blocks extraction (store degrades to
    rule/unknown), so this tool is strictly offline enhancement.

API keys: read from the environment / config.toml via the standard
LangChain bridge.  They never appear in any output of this tool.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "qa" / "tests"))
import _bootstrap  # noqa: F401  (kernel-include environment for the extractor)

from extractor import ExtractorConfig  # noqa: E402
from extractor.extractor import _extraction_cache, extract_ris  # noqa: E402
from extractor.external_semantics import (  # noqa: E402
    EXTERNAL_CATEGORIES, classify, rule_category)

STORE = ROOT / "data" / "external-call-annotations.json"
DRAFT = ROOT / "data" / "external-call-annotations.DRAFT.json"
CENSUS = ROOT / "artifacts" / "cache" / "external-call-census.json"

CORPUS = [
    "benchmarks/drivers/baseline/ahci.c",
    "benchmarks/drivers/baseline/ahci_ceva.c",
    "benchmarks/drivers/baseline/ahci_dwc.c",
    "benchmarks/drivers/baseline/ahci_mvebu.c",
    "benchmarks/drivers/baseline/ahci_sunxi.c",
    "benchmarks/drivers/baseline/clk-highbank.c",
    "benchmarks/drivers/baseline/clk-nomadik.c",
    "benchmarks/drivers/baseline/edu.c",
    "benchmarks/drivers/baseline/gpio-cadence.c",
    "benchmarks/drivers/baseline/gpio-ftgpio010.c",
    "benchmarks/drivers/baseline/gpio-idt3243x.c",
    "benchmarks/drivers/baseline/gpio-mb86s7x.c",
    "benchmarks/drivers/baseline/gpio-pl061.c",
    "benchmarks/drivers/baseline/gpio-sodaville.c",
    "benchmarks/drivers/baseline/pll.c",
    "benchmarks/drivers/baseline/sdhci-esdhc-mcf.c",
    "benchmarks/drivers/baseline/sdhci-of-at91.c",
    "benchmarks/drivers/baseline/virtio_mmio.c",
    "benchmarks/drivers/baseline/wmt_ge_rops.c",
    "vendor/linux/drivers/gpio/gpio-dwapb.c",
    "vendor/linux/drivers/mmc/host/sdhci-npcm.c",
    "vendor/linux/drivers/clk/clk-fixed-mmio.c",
    "vendor/linux/drivers/clk/clk-moxart.c",
    "vendor/linux/drivers/clk/clk-nspire.c",
]

VENDOR = ROOT / "vendor" / "linux"
# Where kernel library definitions actually live, in search order.  The
# final whole-tree pass catches subsystem library code (gpiolib &c.).
DEF_SEARCH_DIRS = ("include", "lib", "kernel", "drivers/base", "mm",
                   "drivers/gpio", "drivers/mmc", "drivers/clk")


def _is_definition_at(text: str, start: int) -> bool:
    """True when a function signature at ``start`` opens a body.

    Balances the parameter list, then looks for the first ``{`` or ``;``
    at depth zero (skipping whitespace and attribute tokens): prototypes
    end with ``;`` and must not be mistaken for definitions — a nearby
    ``{`` from unrelated code fooled the naive fixed look-ahead.
    """
    depth = 0
    index = start
    while index < len(text) and depth >= 0:
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                # past the parameter list; classify what follows
                index += 1
                scanned = 0
                while index < len(text) and scanned < 200:
                    char = text[index]
                    if char == "{":
                        return True
                    if char == ";":
                        return False
                    index += 1
                    scanned += 1
                return False
        index += 1
    return False


# ── scan ──────────────────────────────────────────────────────────────

def cmd_scan(args) -> int:
    census: dict[str, dict] = {}
    for rel in CORPUS:
        path = ROOT / rel
        if not path.exists():
            print(f"skip (missing): {rel}", file=sys.stderr)
            continue
        _extraction_cache.clear()
        result = extract_ris(ExtractorConfig(source=str(path)))
        formal = result.formal
        for module in formal.get("modules", []):
            for node in module.get("external_calls") or []:
                name = node.get("callee")
                if not name:
                    continue
                entry = census.setdefault(name, {
                    "callee": name,
                    "count": 0,
                    "category": node.get("category"),
                    "category_source": node.get("category_source"),
                    "decl_paths": set(),
                    "sample_callsites": [],
                })
                entry["count"] += 1
                if node.get("callee_decl_path"):
                    entry["decl_paths"].add(node["callee_decl_path"])
                if len(entry["sample_callsites"]) < 3:
                    site = node.get("callsite") or {}
                    entry["sample_callsites"].append(
                        f"{Path(site.get('source_path') or '?').name}:"
                        f"{site.get('line', 0)}")
        print(f"scanned {rel}: {formal['metadata']['external_calls'].get('emitted_nodes', 0)} nodes",
              file=sys.stderr)

    rows = sorted(census.values(),
                  key=lambda e: (e["category"] == "unknown", -e["count"], e["callee"]))
    out = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus_size": len(CORPUS),
        "distinct_callees": len(rows),
        "total_callsites": sum(e["count"] for e in rows),
        "unknown_callees": sum(1 for e in rows if e["category"] == "unknown"),
        "by_category": {},
        "callees": [{**e, "decl_paths": sorted(e["decl_paths"])} for e in rows],
    }
    for entry in rows:
        out["by_category"][entry["category"]] = \
            out["by_category"].get(entry["category"], 0) + entry["count"]
    CENSUS.parent.mkdir(parents=True, exist_ok=True)
    CENSUS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"census → {CENSUS}")
    print(f"distinct: {out['distinct_callees']}  "
          f"unknown: {out['unknown_callees']}  "
          f"callsites: {out['total_callsites']}")
    for entry in rows[:20]:
        print(f"  {entry['count']:4d}  [{entry['category']:<15}] "
              f"{entry['callee']}")
    return 0


# ── grounding ─────────────────────────────────────────────────────────

def _read_decl_block(decl_path: str, name: str) -> str:
    """Prototype plus the doc comment directly above it."""
    try:
        path = Path(decl_path)
        if not path.is_absolute():
            path = VENDOR / decl_path.lstrip("/")
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    pattern = re.compile(
        r"^.*\b" + re.escape(name) + r"\s*\(", re.MULTILINE)
    lines = text.splitlines()
    for match in pattern.finditer(text):
        line_no = text[:match.start()].count("\n")
        start = max(0, line_no - 25)
        chunk = lines[start:line_no + 12]
        # keep the comment block if one sits immediately above
        while start > 0 and not lines[start - 1].strip():
            start -= 1
            chunk.insert(0, lines[start])
        return "\n".join(chunk)[:4000]
    return ""


def _extract_body(text: str, brace_offset: int, max_lines: int = 160) -> str:
    depth = 0
    seen = False
    end = len(text)
    for index in range(brace_offset, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
            seen = True
        elif char == "}":
            depth -= 1
            if seen and depth == 0:
                end = index + 1
                break
    body = text[brace_offset:end]
    line_count = body.count("\n")
    if line_count > max_lines:
        body = "\n".join(body.splitlines()[:max_lines]) + "\n/* …truncated */"
    return body[:8000]


def find_definition(name: str, decl_path: str | None) -> dict:
    """Locate name's definition in the pinned kernel tree.

    Tries the clang-resolved declaration file first (header inline), then
    ripgrep over the kernel library directories, then the whole tree.
    Prototypes never count as definitions.
    """
    candidates: list[Path] = []
    if decl_path:
        p = Path(decl_path)
        if not p.is_absolute():
            p = VENDOR / decl_path.lstrip("/")
        if p.exists():
            candidates.append(p)
    search_batches = [
        [str(VENDOR / d) for d in DEF_SEARCH_DIRS], [str(VENDOR)]]
    for dirs in search_batches:
        try:
            # Anchored signature pattern: kernel definitions start a line
            # (attributes like __alloc_size(1, 2) are tolerated between
            # the return type and the name).  Plain call sites don't match,
            # so caller-heavy names don't flood the candidate list.
            rg = subprocess.run(
                ["rg", "-l", "--max-count", "1", "-g", "*.[ch]",
                 "-e", r"^[A-Za-z_][\w \t\*(),]*\b" + re.escape(name)
                 + r"\s*\("] + dirs,
                capture_output=True, text=True, timeout=120)
            new = [Path(line) for line in rg.stdout.splitlines()[:12]]
        except (OSError, subprocess.TimeoutExpired):
            new = []
        # header candidates first: static inline definitions live there
        candidates.extend(sorted(
            new, key=lambda path: 0 if path.suffix == ".h" else 1))
        hit = _first_definition(name, candidates)
        if hit is not None:
            return hit
    if decl_path:
        decl = _read_decl_block(decl_path, name)
        if decl:
            p = Path(decl_path)
            if not p.is_absolute() and (VENDOR / decl_path.lstrip("/")).exists():
                p = VENDOR / decl_path.lstrip("/")
            try:
                rel = str(p.resolve().relative_to(VENDOR))
            except ValueError:
                rel = str(p)
            return {
                "rel_path": rel,
                "line": None,
                "snippet": decl,
                "kind": "declaration",
            }
    return {}


def _first_definition(name: str, candidates: list[Path]) -> dict | None:
    definition_re = re.compile(
        r"^[A-Za-z_][\w \t\*(),]*\b" + re.escape(name) + r"\s*\(",
        re.MULTILINE)
    for path in candidates:
        try:
            if VENDOR not in path.resolve().parents:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in definition_re.finditer(text):
            if not _is_definition_at(text, match.start()):
                continue
            line_no = text[:match.start()].count("\n") + 1
            rel = str(path.resolve().relative_to(VENDOR))
            return {
                "rel_path": rel,
                "line": line_no,
                "snippet": _extract_body(text, match.start()),
                "kind": "definition",
            }
    return None


# ── draft ─────────────────────────────────────────────────────────────

PROMPT = """You are annotating one Linux kernel external function so a driver \
can be ported to a different runtime.  Grounded evidence follows; use it, not \
prior guesses.

FUNCTION: {name}
EVIDENCE KIND: {kind}
EVIDENCE SOURCE: {rel_path}{line_part}
```c
{snippet}
```

Classify the function into EXACTLY ONE closed category and describe it.
Categories (choose one string verbatim): {categories}

Reply with ONE JSON object, no prose, no code fence:
{{
  "category": "<one of the listed categories>",
  "confidence": <0.0-1.0>,
  "return": "<what the return value means, including failure modes>",
  "effects": ["<externally visible effect>"],
  "params": {{"<name>": "<role>"}},
  "porting_hint": "<one sentence: what to do when porting>",
  "basis": "{rel_path}{line_part2}"
}}

Rules:
- category must be one of the listed strings; never invent one.
- If the evidence is a declaration only, cap confidence at 0.5.
- basis must be the EVIDENCE SOURCE string above (verbatim).
- effects list only effects visible OUTSIDE this function (memory, locks,
  device state, scheduling); pure computation means an empty list and
  category "pure"."""


def _parse_annotation(text: str, name: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    category = data.get("category")
    if category not in EXTERNAL_CATEGORIES or category == "unknown":
        return None
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        return None
    if not isinstance(data.get("basis"), str) or not data["basis"].strip():
        return None
    return {
        "category": category,
        "confidence": round(float(confidence), 2),
        "source": "kernel-tree",
        "return": str(data.get("return", ""))[:400] or None,
        "effects": [str(item)[:200] for item in data.get("effects", [])
                    if str(item).strip()][:6],
        "params": {str(k)[:80]: str(v)[:200]
                   for k, v in list(data.get("params", {}).items())[:12]
                   if isinstance(v, str)} if isinstance(data.get("params"), dict) else {},
        "porting_hint": str(data.get("porting_hint", ""))[:400] or None,
        "basis": data["basis"].strip()[:200],
    }


def cmd_draft(args) -> int:
    import langchain_bridge
    from langchain_bridge import call_langchain, set_transcript_dir

    census = json.loads(CENSUS.read_text(encoding="utf-8")) \
        if CENSUS.exists() else None
    if args.functions:
        targets = [name.strip() for name in args.functions.split(",") if name.strip()]
    elif census:
        targets = [entry["callee"] for entry in census["callees"]
                   if entry["category"] == "unknown"][:args.limit]
    else:
        print("no census; run `scan` first or pass --functions", file=sys.stderr)
        return 2
    if args.limit:
        targets = targets[:args.limit]

    store = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
    drafts: dict = json.loads(DRAFT.read_text(encoding="utf-8")) \
        if DRAFT.exists() else {}

    transcript_dir = ROOT / "artifacts" / "transcripts" / \
        f"external-annot-{time.strftime('%Y%m%d-%H%M%S')}"
    set_transcript_dir(transcript_dir, label="external-annot")

    accepted = rejected = 0
    for name in targets:
        # a census can predate a rule-table update; never spend an LLM
        # call on a name the deterministic rules now cover
        if name in store or rule_category(name) is not None:
            print(f"= {name}: covered by rule table, skip")
            continue
        grounding = find_definition(name, None)
        decl_hint = None
        indirect_target = False
        if census:
            for entry in census["callees"]:
                if entry["callee"] == name:
                    decl_hint = entry["decl_paths"][0] \
                        if entry.get("decl_paths") else None
                    # A name with no resolved declaration is an indirect
                    # dispatch target (op-table / function pointer): the
                    # callee is genuinely unknown, and a whole-tree grep
                    # would ground some unrelated same-named function.
                    indirect_target = not entry.get("decl_paths")
                    if not grounding or grounding["kind"] != "definition":
                        alt = find_definition(name, decl_hint)
                        if alt.get("kind") == "definition":
                            grounding = alt
                    break
        if indirect_target and not decl_hint:
            print(f"? {name}: indirect dispatch target, callee unknown — "
                  f"stays unknown")
            rejected += 1
            continue
        if not grounding and decl_hint:
            grounding = {"rel_path": decl_hint, "line": None,
                         "snippet": _read_decl_block(decl_hint, name),
                         "kind": "declaration"}
        if not grounding:
            print(f"? {name}: no grounding found, skip (stays unknown)")
            rejected += 1
            continue
        line_part = f":{grounding['line']}" if grounding.get("line") else ""
        prompt = PROMPT.format(
            name=name, kind=grounding["kind"],
            rel_path=grounding["rel_path"], line_part=line_part,
            line_part2=line_part,
            snippet=grounding["snippet"] or "/* not available */",
            categories=", ".join(EXTERNAL_CATEGORIES[:-1]))
        try:
            response = call_langchain(prompt, timeout=180)
        except Exception as exc:   # endpoint down ⇒ annotation is optional
            print(f"! {name}: LLM call failed ({exc}), skip")
            rejected += 1
            continue
        # invoke_text does not transcribe (only synthesize does); record
        # the annotator's exchanges so drafts stay auditable.
        try:
            langchain_bridge._transcribe(
                prompt, response, kind="external-annot",
                meta={"callee": name, "grounding": grounding["kind"],
                      "evidence": f"{grounding['rel_path']}{line_part}"})
        except Exception:
            pass
        annotation = _parse_annotation(response, name)
        if annotation is None:
            print(f"! {name}: unparseable/invalid model output, skip")
            rejected += 1
            continue
        if grounding["kind"] == "declaration":
            annotation["confidence"] = min(annotation["confidence"], 0.5)
            annotation["source"] = "model"
        drafts[name] = annotation
        accepted += 1
        print(f"+ {name}: {annotation['category']} "
              f"(conf {annotation['confidence']}, {grounding['kind']} "
              f"{grounding['rel_path']}{line_part})")

    DRAFT.parent.mkdir(parents=True, exist_ok=True)
    DRAFT.write_text(json.dumps(drafts, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    set_transcript_dir(None)
    print(f"drafts accepted {accepted}, rejected/skipped {rejected} → {DRAFT}")
    print("review the diff, then merge reviewed entries into "
          f"{STORE.name} by hand")
    return 0


# ── check ─────────────────────────────────────────────────────────────

def cmd_check(args) -> int:
    path = Path(args.file) if args.file else STORE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable store: {exc}", file=sys.stderr)
        return 2
    problems = 0
    if not isinstance(data, dict):
        print("store must be a JSON object keyed by callee name", file=sys.stderr)
        return 2
    for name, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            print(f"{name}: entry not an object")
            problems += 1
            continue
        if entry.get("category") not in EXTERNAL_CATEGORIES:
            print(f"{name}: bad category {entry.get('category')!r}")
            problems += 1
        if entry.get("source") not in {"rule", "kernel-tree", "model"}:
            print(f"{name}: bad source {entry.get('source')!r}")
            problems += 1
        confidence = entry.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            print(f"{name}: bad confidence {confidence!r}")
            problems += 1
    status = "OK" if not problems else f"{problems} problem(s)"
    print(f"{path}: {len(data)} entries, {status}")
    # consistency against the live rule table
    disagreements = [
        (name, entry.get("category"), rule_category(name))
        for name, entry in data.items()
        if rule_category(name) not in (None, entry.get("category"))]
    for name, annotated, ruled in disagreements:
        print(f"  note: {name} annotated {annotated!r} but rule says "
              f"{ruled!r} (annotation wins; confirm intentional)")
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="corpus census (no LLM)")

    draft = sub.add_parser("draft", help="grounded LLM annotation drafts")
    draft.add_argument("--functions", default="",
                       help="comma-separated callee names (default: census unknowns)")
    draft.add_argument("--limit", type=int, default=20,
                       help="max names per run (default 20)")

    check = sub.add_parser("check", help="validate store/draft schema")
    check.add_argument("file", nargs="?", default=None)

    args = parser.parse_args()
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "draft":
        return cmd_draft(args)
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
