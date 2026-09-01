"""CLI entry: `python3 -m extractor extract --source ... --output out.ris`"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from .extractor import ExtractorConfig, extract_ris
from .formalize import save_formal_text

def _backend_choices():
    try:
        from backends.registry import backend_names
        names = backend_names()
        if names:
            return names
    except Exception:
        pass
    return ['harness', 'baremetal', 'linux', 'rust_baremetal']



def _is_subsequence(sub, seq) -> bool:
    """True if `sub` appears in `seq` in order (not necessarily contiguous).
    Used for trace equivalence: unconditional RIS ops must appear in the
    runtime trace in order, with conditional ops possibly interleaved."""
    it = iter(seq)
    return all(x in it for x in sub)


def _config_from_args(args) -> ExtractorConfig:
    return ExtractorConfig(
        source=args.source,
        output=(getattr(args, "output", "artifacts/output/ris.ris")
                or "artifacts/output/ris.ris"),
        include_framework=getattr(args, "include_framework", False),
        extra_blacklist=[s.strip() for s in getattr(args, "blacklist", "").split(",")
                         if s.strip()],
        linux_root=getattr(args, "linux_root", None),
        max_inline_depth=getattr(args, "max_inline_depth", None),
        alias_mode=getattr(args, "alias_mode", "off"),
        driver_name=getattr(args, "driver_name", None),
        compile_commands=getattr(args, "compile_commands", None),
        compile_context_mode=getattr(args, "compile_context", "auto"),
        ir_mode=getattr(args, "ir_mode", "off"),
    )


def _add_analysis_options(parser, *, extended: bool = False) -> None:
    parser.add_argument("--driver-name", default=None,
                        help="override driver name (manifest name is used by default)")
    parser.add_argument("--linux-root", default=None,
                        help="Linux tree (default: repository vendor/linux/ submodule)")
    parser.add_argument("--alias-mode", choices=["off", "auto", "required"], default="off",
                        help="SVF alias analysis: off (fast default), auto, or required")
    parser.add_argument("--compile-commands", default=None,
                        help="optional Linux compile_commands.json (Kbuild .cmd is auto-discovered)")
    parser.add_argument("--compile-context", choices=["off", "auto", "required"],
                        default="auto",
                        help="Kbuild context importer mode (default: auto)")
    parser.add_argument("--ir-mode", choices=["off", "auto", "required"],
                        default="off",
                        help="LLVM IR enhancement: compile to IR at -O1 to find MMIO ops missed by AST (default: off)")
    if extended:
        parser.add_argument("--include-framework", action="store_true")
        parser.add_argument("--blacklist", default="",
                            help="comma-separated extra functions to exclude")
        parser.add_argument(
            "--max-inline-depth", type=int, default=None,
            help="bound helper expansion depth (default: adaptive call-graph depth)")


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
    e.add_argument("-o", "--output", default="artifacts/output/ris.ris",
                   help="formal-language text output (.ris; default: artifacts/output/ris.ris)")
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
                   choices=_backend_choices())
    g.add_argument("-o", "--output", default=None,
                  help="output .c file (default: artifacts/output/<driver>_<backend>.c)")
    g.add_argument("--manifest", default=None,
                   help="validated experiment manifest supplying runtime policy")
    g.add_argument("--pair", action="store_true",
                  help="generate .h + .c pair instead of single .c file")
    _add_analysis_options(g)

    sc = sub.add_parser("score", help="Generation readiness scoring")
    sc.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    _add_analysis_options(sc)


    dr = sub.add_parser("driver", help="One-shot full pipeline: RIS + dspec + bind "
                                       "+ all backends + trace verification")
    dr.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    dr.add_argument("-o", "--outdir", default=None,
                    help="output dir (default: artifacts/output/<name>/)")
    _add_analysis_options(dr)

    fa = sub.add_parser("facts", help="Print source facts (.facts) for LLM synthesis")
    fa.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    fa.add_argument("-o", "--output", default=None)
    _add_analysis_options(fa)

    bu = sub.add_parser("bundle", help="Build LLM input bundle (RIS+dspec+bind+facts)")
    bu.add_argument("-s", "--source", required=True,
                    help="C source file or multi-source JSON manifest")
    bu.add_argument("-b", "--backend", default="harness",
                    choices=_backend_choices())
    bu.add_argument("-o", "--outdir", default=None,
                    help="bundle directory (default: artifacts/output/<driver>.bundle-<backend>/)")
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
        from backends.registry import get_backend as _get_backend
        from backends.common import split_header_source
        from backends.llm_bridge import generated_file_entries
        res = extract_ris(_config_from_args(args))
        bind = default_bind(res.device_spec, args.backend)
        gen_mod = _get_backend(args.backend)
        gen_kwargs = {}
        for kw in getattr(gen_mod, "GEN_KWARGS", []):
            if kw == "facts":
                gen_kwargs["facts"] = res.facts
            elif kw == "pci_identity":
                pci_identity = None
                registrar = None
                if args.manifest:
                    from experiment_manifest import load_manifest
                    runtime = load_manifest(args.manifest).runtime
                    pci_identity = runtime.pci_identity
                    registrar = (getattr(runtime.qemu, "registrar", None)
                                 if runtime.qemu is not None else None)
                gen_kwargs["pci_identity"] = pci_identity
                gen_kwargs["registrar"] = registrar
        if args.pair:
            generated = gen_mod.generate(
                res.formal, res.device_spec, bind, **gen_kwargs)
            if getattr(generated, "files", None):
                base = Path(
                    args.output or
                    f"artifacts/output/{res.formal['driver']}_{args.backend}")
                root = base.parent if base.suffix else base
                for entry in generated_file_entries(
                        generated, default_path=f"{args.backend}.c"):
                    destination = root / entry["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(entry["code"], encoding="utf-8")
                    print(f"✅ {args.backend} file saved to {destination}")
                return 0
            header, source = split_header_source(
                generated, res.formal["driver"], args.backend)
            base = (args.output
                    or f"artifacts/output/{res.formal['driver']}_{args.backend}")
            base = base[:-2] if base.endswith(".c") else base
            h_out = f"{base}.h"
            c_out = f"{base}.c"
            os.makedirs(os.path.dirname(os.path.abspath(c_out)) or ".", exist_ok=True)
            with open(h_out, "w", encoding="utf-8") as fh:
                fh.write(header)
            with open(c_out, "w", encoding="utf-8") as fh:
                fh.write(source)
            print(f"✅ {args.backend} header saved to {h_out}")
            print(f"✅ {args.backend} source saved to {c_out}")
        else:
            code = gen_mod.generate(
                res.formal, res.device_spec, bind, **gen_kwargs)
            if getattr(code, "files", None):
                out = Path(
                    args.output or
                    f"artifacts/output/{res.formal['driver']}_{args.backend}")
                root = out.parent if out.suffix else out
                for entry in generated_file_entries(
                        code, default_path=f"{args.backend}.c"):
                    destination = root / entry["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(entry["code"], encoding="utf-8")
                    print(f"✅ {args.backend} file saved to {destination}")
                return 0
            out = (args.output
                   or f"artifacts/output/{res.formal['driver']}_{args.backend}.c")
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
        from driver_pipeline import run_driver_pipeline
        res = extract_ris(_config_from_args(args))
        return run_driver_pipeline(res, args)

    if args.command == "bundle":
        import synthesis
        res = extract_ris(_config_from_args(args))
        outdir = (args.outdir or
                  f"artifacts/output/{res.formal['driver']}.bundle-{args.backend}")
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
