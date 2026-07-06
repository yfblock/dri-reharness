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

    m = sub.add_parser("metrics", help="Print per-module extraction quality metrics")
    m.add_argument("-s", "--source", required=True)

    sp = sub.add_parser("spec", help="Print inferred backend-independent .dspec")
    sp.add_argument("-s", "--source", required=True)
    sp.add_argument("-o", "--output", default=None, help="write .dspec to file")

    g = sub.add_parser("gen", help="Generate backend C from RIS + DeviceSpec + bind")
    g.add_argument("-s", "--source", required=True)
    g.add_argument("-b", "--backend", required=True,
                   choices=["harness", "baremetal", "linux"])
    g.add_argument("-o", "--output", default=None, help="output .c file")

    sc = sub.add_parser("score", help="Generation readiness scoring")
    sc.add_argument("-s", "--source", required=True)

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

    if args.command == "metrics":
        from .metrics import driver_metrics, format_metrics
        res = extract_ris(ExtractorConfig(source=args.source))
        met = driver_metrics(res.formal, n_clang_diag=len(res.warnings))
        print(format_metrics(met))
        return 0

    if args.command == "spec":
        res = extract_ris(ExtractorConfig(source=args.source))
        text = res.device_spec.display()
        if args.output:
            import os
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"✅ dspec saved to {args.output}")
        else:
            print(text)
        return 0

    if args.command == "gen":
        import os
        from extractor.bind import default_bind
        from generator import harness as G_harness
        from generator import baremetal as G_baremetal
        from generator import linux as G_linux
        res = extract_ris(ExtractorConfig(source=args.source))
        bind = default_bind(res.device_spec, args.backend)
        gens = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}
        code = gens[args.backend].generate(res.formal, res.device_spec, bind)
        out = args.output or f"output/{res.formal['driver']}_{args.backend}.c"
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(code)
        print(f"✅ {args.backend} code saved to {out}")
        return 0

    if args.command == "score":
        from .readiness import score, format_score
        res = extract_ris(ExtractorConfig(source=args.source))
        print(format_score(score(res.device_spec, res.formal, res.warnings)))
        return 0

    return 1
