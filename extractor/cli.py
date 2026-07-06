"""CLI entry: `python3 -m extractor extract --source ... --output out.ris`"""
from __future__ import annotations
import argparse
import os
import sys

from .extractor import ExtractorConfig, extract_ris
from .formalize import save_formal_text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="reharness",
        description="Extract register interaction sequences from C drivers "
                    "(libclang AST + dataflow/taint). Output: .ris spec language.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("extract", help="Extract RIS (.ris spec language) from a C source file")
    e.add_argument("-s", "--source", required=True)
    e.add_argument("-o", "--output", default="output/ris.ris",
                   help="formal-language text output (.ris)")
    e.add_argument("--include-framework", action="store_true")
    e.add_argument("--blacklist", default="", help="comma-separated extra framework fns")
    e.add_argument("--linux-root", default=None)
    e.add_argument("--max-inline-depth", type=int, default=3)

    args = p.parse_args(argv)

    if args.command == "extract":
        cfg = ExtractorConfig(
            source=args.source,
            output=args.output,
            include_framework=args.include_framework,
            extra_blacklist=[s.strip() for s in args.blacklist.split(",") if s.strip()],
            linux_root=args.linux_root,
            max_inline_depth=args.max_inline_depth,
        )
        print(f"🔍 Extracting RIS from {cfg.source} ...")
        res = extract_ris(cfg)

        out = args.output
        out_dir = os.path.dirname(os.path.abspath(out)) or "."
        os.makedirs(out_dir, exist_ok=True)
        save_formal_text(res.formal, out)

        st = res.stats
        print("📊 Stats:")
        print(f"   Functions analyzed:  {st['functions_analyzed']}")
        print(f"   MMIO reads:          {st['mmio_reads']}")
        print(f"   MMIO writes:         {st['mmio_writes']}")
        print(f"   Read-modify-write:   {st['rmw']}")
        print(f"   Conditions recorded: {st['conditions_recorded']}")
        print(f"   Macros resolved:     {st['macros_resolved']}")
        print(f"   Total ops:           {st['total_ops']}")
        n_warn = len(res.warnings)
        if n_warn:
            print(f"⚠️  {n_warn} clang diagnostics (non-fatal); first few:")
            for w in res.warnings[:5]:
                print(f"   {w}")
        print(f"✅ RIS spec saved to {out}")
        return 0

    return 1
