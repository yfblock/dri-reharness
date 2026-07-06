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

    dr = sub.add_parser("driver", help="One-shot full pipeline: RIS + dspec + bind "
                                       "+ all backends + trace verification")
    dr.add_argument("-s", "--source", required=True)
    dr.add_argument("-o", "--outdir", default=None, help="output dir (default output/<name>/)")

    fa = sub.add_parser("facts", help="Print source facts (.facts) for LLM synthesis")
    fa.add_argument("-s", "--source", required=True)
    fa.add_argument("-o", "--output", default=None)

    bu = sub.add_parser("bundle", help="Build LLM input bundle (RIS+dspec+bind+facts+scaffold)")
    bu.add_argument("-s", "--source", required=True)
    bu.add_argument("-b", "--backend", default="harness", choices=["harness", "baremetal", "linux"])
    bu.add_argument("-o", "--outdir", default=None)

    sy = sub.add_parser("synth", help="LLM-assisted repair loop (scaffold -> verify -> patch)")
    sy.add_argument("-s", "--source", required=True)
    sy.add_argument("-b", "--backend", default="harness", choices=["harness", "baremetal", "linux"])
    sy.add_argument("-o", "--outdir", default=None)
    sy.add_argument("--max-iters", type=int, default=3)

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
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"✅ dspec saved to {args.output}")
        else:
            print(text)
        return 0

    if args.command == "gen":
        from .spec import default_bind
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
        from .metrics import score, format_score
        res = extract_ris(ExtractorConfig(source=args.source))
        print(format_score(score(res.device_spec, res.formal, res.warnings, res.facts)))
        return 0

    if args.command == "driver":
        import subprocess
        from .metrics import driver_metrics, format_metrics
        from .metrics import score as score_fn, format_score
        from .spec import default_bind
        from generator import harness as G_harness
        from generator import baremetal as G_baremetal
        from generator import linux as G_linux

        res = extract_ris(ExtractorConfig(source=args.source))
        name = res.formal["driver"]
        outdir = args.outdir or f"output/{name}"
        os.makedirs(outdir, exist_ok=True)

        def _w(path: str, text: str):
            with open(os.path.join(outdir, path), "w", encoding="utf-8") as fh:
                fh.write(text.rstrip() + "\n")

        print(f"🚀 driver pipeline: {name} → {outdir}/")
        # 1. RIS
        from .formalize import save_formal_text
        save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
        # 2. dspec
        _w(f"{name}.dspec", res.device_spec.display())
        # 2b. facts
        _w(f"{name}.facts", res.facts.display())
        # 3. metrics + score
        _w(f"{name}.metrics.txt", format_metrics(
            driver_metrics(res.formal, n_clang_diag=len(res.warnings))))
        sc = score_fn(res.device_spec, res.formal, res.warnings, res.facts)
        _w(f"{name}.score.txt", format_score(sc))

        # 4. three backends
        gens = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}
        results = {}
        for backend, gen in gens.items():
            bind = default_bind(res.device_spec, backend)
            _w(f"{name}.{backend}.bind", bind.display())
            code = gen.generate(res.formal, res.device_spec, bind)
            cpath = os.path.join(outdir, f"{name}.{backend}.c")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(code)
            # compile check
            if backend == "harness":
                binp = cpath + ".bin"
                r = subprocess.run(["cc", "-o", binp, cpath], capture_output=True, text=True)
                if r.returncode == 0:
                    out = subprocess.run([binp], capture_output=True, text=True).stdout
                    _w(f"{name}.{backend}.trace.txt", out)
                    n = out.count("[trace")
                    results[backend] = f"compiled+ran ({n} ops traced)"
                else:
                    _w(f"{name}.{backend}.compile.log", r.stderr)
                    results[backend] = f"compile FAILED (see .compile.log)"
            elif backend == "baremetal":
                r = subprocess.run(["cc", "-ffreestanding", "-c", "-o", "/dev/null", cpath],
                                   capture_output=True, text=True)
                results[backend] = "compiles freestanding" if r.returncode == 0 else "compile FAILED"
            else:  # linux skeleton — syntax check only (not kernel-buildable here)
                r = subprocess.run(["cc", "-fsyntax-only", "-D__KERNEL__",
                                    "-Ireharness/linux/include", cpath],
                                   capture_output=True, text=True)
                # linux skeleton intentionally has unresolved kernel symbols; just report
                results[backend] = "generated (kernel-build scaffold)"

        # summary
        print()
        print("── artifacts ──")
        for f in sorted(os.listdir(outdir)):
            if f.endswith(".bin"):
                continue
            print(f"   {outdir}/{f}")
        print()
        print("── backend results ──")
        for b, r in results.items():
            print(f"   {b:<10} {r}")
        print()
        print("── readiness ──")
        print(format_score(sc).replace("\n", "\n  "))
        return 0

    if args.command == "bundle":
        import synthesis
        res = extract_ris(ExtractorConfig(source=args.source))
        outdir = args.outdir or f"output/{res.formal['driver']}.bundle-{args.backend}"
        bdir = synthesis.build_bundle(res, args.backend, outdir)
        print(f"✅ bundle → {bdir}/")
        for f in sorted(os.listdir(bdir)):
            print(f"   {bdir}/{f}")
        return 0

    if args.command == "facts":
        res = extract_ris(ExtractorConfig(source=args.source))
        text = res.facts.display()
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"✅ facts saved to {args.output}")
        else:
            print(text)
        return 0

    if args.command == "synth":
        import synthesis
        res = extract_ris(ExtractorConfig(source=args.source))
        outdir = args.outdir or f"output/{res.formal['driver']}.synth-{args.backend}"
        print(f"🔬 LLM repair loop ({args.backend}) → {outdir}/")
        result = synthesis.run_repair_loop(res, args.backend, outdir,
                                           max_iters=args.max_iters)
        print(f"   llm: {result['llm']}  iters: {result['iters']}  "
              f"accepted: {result['accepted']}")
        print(synthesis.format_feedback(result["final_feedback"]))
        if not result["accepted"] and result["llm"] == "null":
            print("\n(set REHARNESS_LLM_CMD='<cmd>' to enable LLM repair)")
        print(f"   bundle: {result['bundle']}")
        return 0

    return 1
