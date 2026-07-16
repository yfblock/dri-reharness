"""CLI entry: `python3 -m extractor extract --source ... --output out.ris`"""
from __future__ import annotations
import argparse
import json
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


def _config_from_args(args) -> ExtractorConfig:
    return ExtractorConfig(
        source=args.source,
        output=getattr(args, "output", "output/ris.ris") or "output/ris.ris",
        include_framework=getattr(args, "include_framework", False),
        extra_blacklist=[s.strip() for s in getattr(args, "blacklist", "").split(",")
                         if s.strip()],
        linux_root=getattr(args, "linux_root", None),
        max_inline_depth=getattr(args, "max_inline_depth", 3),
        alias_mode=getattr(args, "alias_mode", "off"),
        driver_name=getattr(args, "driver_name", None),
        compile_commands=getattr(args, "compile_commands", None),
        compile_context_mode=getattr(args, "compile_context", "auto"),
    )


def _add_analysis_options(parser, *, extended: bool = False) -> None:
    parser.add_argument("--driver-name", default=None,
                        help="override driver name (manifest name is used by default)")
    parser.add_argument("--linux-root", default=None,
                        help="Linux tree (default: repository linux/ submodule)")
    parser.add_argument("--alias-mode", choices=["off", "auto", "required"], default="off",
                        help="SVF alias analysis: off (fast default), auto, or required")
    parser.add_argument("--compile-commands", default=None,
                        help="optional Linux compile_commands.json (Kbuild .cmd is auto-discovered)")
    parser.add_argument("--compile-context", choices=["off", "auto", "required"],
                        default="auto",
                        help="Kbuild context importer mode (default: auto)")
    if extended:
        parser.add_argument("--include-framework", action="store_true")
        parser.add_argument("--blacklist", default="",
                            help="comma-separated extra functions to exclude")
        parser.add_argument("--max-inline-depth", type=int, default=3)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="reharness",
        description="Extract register interaction sequences from C drivers "
                    "(libclang AST + dataflow/taint). Output: .ris spec language.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("extract", help="Extract RIS (.ris spec language) from a C source file")
    e.add_argument("-s", "--source", required=True,
                   help="C source file or multi-source JSON manifest")
    e.add_argument("-o", "--output", default="output/ris.ris",
                   help="formal-language text output (.ris)")
    e.add_argument("--json-output", default=None,
                   help="optional structured Formal RIS JSON output")
    _add_analysis_options(e, extended=True)

    m = sub.add_parser("metrics", help="Print per-module extraction quality metrics")
    m.add_argument("-s", "--source", required=True,
                   help="C source file or multi-source JSON manifest")
    _add_analysis_options(m)

    sp = sub.add_parser("spec", help="Print inferred backend-independent .dspec")
    sp.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    sp.add_argument("-o", "--output", default=None, help="write .dspec to file")
    _add_analysis_options(sp)

    g = sub.add_parser("gen", help="Generate backend C from RIS + DeviceSpec + bind")
    g.add_argument("-s", "--source", required=True,
                   help="C source file or multi-source JSON manifest")
    g.add_argument("-b", "--backend", required=True,
                   choices=["harness", "baremetal", "linux"])
    g.add_argument("-o", "--output", default=None, help="output .c file")
    _add_analysis_options(g)

    sc = sub.add_parser("score", help="Generation readiness scoring")
    sc.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    _add_analysis_options(sc)

    dr = sub.add_parser("driver", help="One-shot full pipeline: RIS + dspec + bind "
                                       "+ all backends + trace verification")
    dr.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    dr.add_argument("-o", "--outdir", default=None, help="output dir (default output/<name>/)")
    _add_analysis_options(dr)

    fa = sub.add_parser("facts", help="Print source facts (.facts) for LLM synthesis")
    fa.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    fa.add_argument("-o", "--output", default=None)
    _add_analysis_options(fa)

    bu = sub.add_parser("bundle", help="Build LLM input bundle (RIS+dspec+bind+facts)")
    bu.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    bu.add_argument("-b", "--backend", default="harness", choices=["harness", "baremetal", "linux"])
    bu.add_argument("-o", "--outdir", default=None)
    _add_analysis_options(bu)

    args = p.parse_args(argv)

    if args.command == "extract":
        cfg = _config_from_args(args)
        print(f"🔍 Extracting RIS from {cfg.source} ...")
        res = extract_ris(cfg)

        out = args.output
        out_dir = os.path.dirname(os.path.abspath(out)) or "."
        os.makedirs(out_dir, exist_ok=True)
        save_formal_text(res.formal, out)
        if args.json_output:
            json_dir = os.path.dirname(os.path.abspath(args.json_output)) or "."
            os.makedirs(json_dir, exist_ok=True)
            with open(args.json_output, "w", encoding="utf-8") as fh:
                json.dump(res.formal, fh, indent=2, sort_keys=True)
                fh.write("\n")

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
        if args.json_output:
            print(f"✅ structured RIS saved to {args.json_output}")
        return 0

    if args.command == "metrics":
        from .metrics import driver_metrics, format_metrics, count_clang_errors
        res = extract_ris(_config_from_args(args))
        met = driver_metrics(res.formal, n_clang_diag=count_clang_errors(res.warnings))
        print(format_metrics(met))
        return 0

    if args.command == "spec":
        res = extract_ris(_config_from_args(args))
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
        res = extract_ris(_config_from_args(args))
        bind = default_bind(res.device_spec, args.backend)
        gens = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}
        if args.backend == "linux":
            code = gens[args.backend].generate(
                res.formal, res.device_spec, bind, res.facts)
        else:
            code = gens[args.backend].generate(res.formal, res.device_spec, bind)
        out = args.output or f"output/{res.formal['driver']}_{args.backend}.c"
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(code)
        print(f"✅ {args.backend} code saved to {out}")
        return 0

    if args.command == "score":
        from .metrics import score, format_score
        res = extract_ris(_config_from_args(args))
        print(format_score(score(res.device_spec, res.formal, res.warnings, res.facts)))
        return 0

    if args.command == "driver":
        import subprocess, tempfile
        from .metrics import driver_metrics, format_metrics, count_clang_errors
        from .metrics import score as score_fn, format_score
        from .spec import default_bind, display_bind_set
        from generator import harness as G_harness
        from generator import baremetal as G_baremetal
        from generator import linux as G_linux

        res = extract_ris(_config_from_args(args))
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
        _w(ver_dir, "analysis.json", json.dumps({
            "stats": res.stats, "warnings": res.warnings,
        }, indent=2, sort_keys=True))

        # ── generated C + verification (derived) ──
        gens = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}
        binds, results, gen_results = [], {}, {}
        for backend, gen in gens.items():
            bind = default_bind(res.device_spec, backend)
            binds.append(bind)
            if backend == "linux":
                code = gen.generate(res.formal, res.device_spec, bind, res.facts)
            else:
                code = gen.generate(res.formal, res.device_spec, bind)
            cpath = os.path.join(gen_dir, f"{backend}.c")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(code)
            has_todo = "TODO" in code
            unsupported = "REHARNESS_UNSUPPORTED" in code
            gr: dict = {"has_todo": has_todo, "unsupported": unsupported}

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
                    modules = res.formal["modules"]
                    entry = (probe_fn.ris_ref if probe_fn else
                             modules[0]["name"] if modules else None)
                    mod = next((m for m in modules if m["name"] == entry), None)
                    expected = []
                    untraceable = False
                    if mod:
                        for o in mod["ops"]:   # top-level only (no Cond/Loop descent)
                            if "Write" in o:
                                addr = o["Write"]["addr"]
                                off = (regs.get(addr["Symbolic"]["register"])
                                       if "Symbolic" in addr else
                                       addr["Fixed"]["offset"] if "Fixed" in addr else None)
                                if off is None:
                                    untraceable = True
                                else:
                                    expected.append(("W", off))
                            elif "Read" in o:
                                addr = o["Read"]["addr"]
                                off = (regs.get(addr["Symbolic"]["register"])
                                       if "Symbolic" in addr else
                                       addr["Fixed"]["offset"] if "Fixed" in addr else None)
                                if off is None:
                                    untraceable = True
                                else:
                                    expected.append(("R", off))
                    import re as _re
                    traced = [(k, int(off, 16)) for k, off in
                              _re.findall(r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)", out)]
                    # runtime trace must contain the unconditional ops as a
                    # subsequence (conditional ops may appear interleaved)
                    gr["trace_passed"] = (not untraceable and
                                          _is_subsequence(expected, traced))
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
            else:  # linux — real out-of-tree Kbuild module compilation
                import shutil
                module_name = name.replace("-", "_")
                build_dir = os.path.abspath(os.path.join(tmp_dir, "linux-module"))
                os.makedirs(build_dir, exist_ok=True)
                module_c = os.path.join(build_dir, f"{module_name}.c")
                shutil.copyfile(cpath, module_c)
                _w(build_dir, "Makefile", f"obj-m += {module_name}.o\n")
                repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                kernel_dir = os.environ.get(
                    "KERNELDIR", os.path.join(repo_root, "kernel", "build"))
                r = subprocess.run(
                    ["make", "-C", kernel_dir, f"M={build_dir}", "modules"],
                    capture_output=True, text=True)
                gr["compiled"] = r.returncode == 0
                gr["syntax_ok"] = r.returncode == 0
                if r.returncode != 0:
                    _w(ver_dir, "linux.compile.log", r.stdout + "\n" + r.stderr)
                results[backend] = ("kernel module compiles" if r.returncode == 0
                                    else "kernel compile FAILED")
            gen_results[backend] = gr

        # Persist backend evidence separately from readiness: a backend may
        # compile while remaining explicitly unsupported/strict-unready.
        _w(ver_dir, "analysis.json", json.dumps({
            "stats": res.stats,
            "warnings": res.warnings,
            "generation": gen_results,
        }, indent=2, sort_keys=True))

        # merged .bind (recom.md §"Merge Backend Bind Files")
        _w(outdir, f"{name}.bind", display_bind_set(binds))

        # verification reports
        _w(ver_dir, "metrics.txt", format_metrics(
            driver_metrics(res.formal,
                           n_clang_diag=count_clang_errors(res.warnings))))
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
        res = extract_ris(_config_from_args(args))
        outdir = args.outdir or f"output/{res.formal['driver']}.bundle-{args.backend}"
        bdir = synthesis.build_bundle(res, args.backend, outdir)
        print(f"✅ bundle → {bdir}/")
        for f in sorted(os.listdir(bdir)):
            print(f"   {bdir}/{f}")
        return 0

    if args.command == "facts":
        res = extract_ris(_config_from_args(args))
        text = res.facts.display()
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"✅ facts saved to {args.output}")
        else:
            print(text)
        return 0

    return 1
