"""CLI entry: `python3 -m extractor extract --source ... --output out.ris`"""
from __future__ import annotations
import argparse
import os
import sys

from .extractor import ExtractorConfig, extract_ris
from .formalize import save_formal_text


def _is_subsequence(sub, seq) -> bool:
    """True if `sub` appears in `seq` in order (not necessarily contiguous).
    Used for trace equivalence: unconditional RIS ops must appear in the
    runtime trace in order, with conditional ops possibly interleaved."""
    it = iter(seq)
    return all(x in it for x in sub)


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
            # always show SVF alias analysis result (may be after clang diags)
            svf_w = [w for w in res.warnings if 'SVF' in w]
            for w in svf_w:
                if w not in res.warnings[:5]:
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
        import subprocess, tempfile
        from .metrics import driver_metrics, format_metrics
        from .metrics import score as score_fn, format_score
        from .spec import default_bind, display_bind_set
        from generator import harness as G_harness
        from generator import baremetal as G_baremetal
        from generator import linux as G_linux

        res = extract_ris(ExtractorConfig(source=args.source))
        name = res.formal["driver"]
        outdir = args.outdir or f"output/{name}"
        gen_dir = os.path.join(outdir, "generated")
        ver_dir = os.path.join(outdir, "verify")
        tmp_dir = os.path.join(ver_dir, "tmp")
        for d in (outdir, gen_dir, ver_dir, tmp_dir):
            os.makedirs(d, exist_ok=True)

        def _w(base: str, path: str, text: str):
            with open(os.path.join(base, path), "w", encoding="utf-8") as fh:
                fh.write(text.rstrip() + "\n")

        print(f"🚀 driver pipeline: {name} → {outdir}/")
        # ── core reconstruction inputs (recom.md) ──
        save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
        _w(outdir, f"{name}.dspec", res.device_spec.display())
        _w(outdir, f"{name}.facts", res.facts.display())

        # ── generated C + verification (derived) ──
        gens = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}
        binds, results, gen_results = [], {}, {}
        for backend, gen in gens.items():
            bind = default_bind(res.device_spec, backend)
            binds.append(bind)
            code = gen.generate(res.formal, res.device_spec, bind)
            cpath = os.path.join(gen_dir, f"{backend}.c")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(code)
            has_todo = "TODO" in code
            gr: dict = {"has_todo": has_todo}

            if backend == "harness":
                binp = os.path.join(tmp_dir, "harness.bin")
                r = subprocess.run(["cc", "-o", binp, cpath], capture_output=True, text=True)
                gr["compiled"] = r.returncode == 0
                if r.returncode == 0:
                    out = subprocess.run([binp], capture_output=True, text=True).stdout
                    _w(ver_dir, "harness.trace.txt", out)
                    # trace equivalence vs RIS entry (probe) module. Only the
                    # UNCONDITIONAL (top-level) ops are compared — ops inside a
                    # Cond/Loop may or may not run at runtime (RIS is path-
                    # insensitive), so they are excluded from the expected seq.
                    regs = {r2["name"]: r2["offset"] for r2 in res.formal["register_map"]}
                    probe_fn = next((fn for fn in res.device_spec.functions if fn.role == "probe"), None)
                    entry = probe_fn.ris_ref if probe_fn else res.formal["modules"][0]["name"]
                    mod = next((m for m in res.formal["modules"] if m["name"] == entry), None)
                    expected = []
                    if mod:
                        for o in mod["ops"]:   # top-level only (no Cond/Loop descent)
                            if "Write" in o:
                                expected.append(("W", regs.get(o["Write"]["addr"]["Symbolic"]["register"], 0)))
                            elif "Read" in o:
                                expected.append(("R", regs.get(o["Read"]["addr"]["Symbolic"]["register"], 0)))
                    import re as _re
                    traced = [(k, int(off, 16)) for k, off in
                              _re.findall(r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)", out)]
                    # runtime trace must contain the unconditional ops as a
                    # subsequence (conditional ops may appear interleaved)
                    gr["trace_passed"] = _is_subsequence(expected, traced)
                    results[backend] = f"compiled+ran ({out.count('[trace')} ops, trace {'✓' if gr['trace_passed'] else '✗'})"
                else:
                    _w(ver_dir, "harness.compile.log", r.stderr)
                    results[backend] = "compile FAILED (see verify/harness.compile.log)"
            elif backend == "baremetal":
                r = subprocess.run(["cc", "-ffreestanding", "-Wall", "-c", "-o", "/dev/null", cpath],
                                   capture_output=True, text=True)
                gr["compiled"] = r.returncode == 0
                if r.returncode != 0:
                    _w(ver_dir, "baremetal.compile.log", r.stderr)
                results[backend] = "compiles freestanding" if r.returncode == 0 else "compile FAILED"
            else:  # linux — syntax check (not a real kernel build)
                r = subprocess.run(["cc", "-fsyntax-only", "-D__KERNEL__",
                                    "-Ireharness/linux/include", cpath],
                                   capture_output=True, text=True)
                gr["syntax_ok"] = r.returncode == 0
                results[backend] = "generated (kernel-build scaffold)"
            gen_results[backend] = gr

        # merged .bind (recom.md §"Merge Backend Bind Files")
        _w(outdir, f"{name}.bind", display_bind_set(binds))

        # verification reports
        _w(ver_dir, "metrics.txt", format_metrics(
            driver_metrics(res.formal, n_clang_diag=len(res.warnings))))
        sc = score_fn(res.device_spec, res.formal, res.warnings, res.facts,
                      gen_results=gen_results)
        _w(ver_dir, "score.txt", format_score(sc))

        # ── summary ──
        print()
        print("── core reconstruction inputs ──")
        for f in (f"{name}.ris", f"{name}.dspec", f"{name}.bind", f"{name}.facts"):
            print(f"   {outdir}/{f}")
        print("── generated/ ──")
        for f in sorted(os.listdir(gen_dir)):
            print(f"   {gen_dir}/{f}")
        print("── verify/ ──")
        for f in sorted(os.listdir(ver_dir)):
            if f == "tmp":
                continue
            print(f"   {ver_dir}/{f}")
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
