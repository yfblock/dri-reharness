"""Driver pipeline: full one-shot RIS + dspec + bind + backends + trace verification.

Extracted from cli.py for maintainability.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from pathlib import Path

from extractor.formalize import save_formal_text


def run_driver_pipeline(res, args) -> int:
    name = res.formal["driver"]
    import subprocess, tempfile
    from extractor.metrics import driver_metrics, format_metrics, count_clang_errors
    from extractor.metrics import score as score_fn, format_score
    from extractor.spec import (default_bind, display_bind_set,
                       device_spec_to_dict)
    from generator.subsystem_runner import (subsystem_callback_plan,
                                            w1c_drain_plan)
    from verification.subsystem_callback_oracle import (
        verify_subsystem_callbacks)
    from verification.gpio_mmio_source_oracle import (
        verify_gpio_mmio_source_differential)
    from verification.sdhci_accessor_oracle import (
        verify_sdhci_accessor_source_contract)
    from verification.virtio_state_oracle import (
        verify_virtio_state_contract)
    from verification.w1c_drain_oracle import (
        verify_w1c_drain_contract, verify_w1c_drain_runtime)
    from verification.transaction_ir_oracle import (
        verify_transaction_source)
    from verification.backend_lowering_oracle import (
        build_generation_contract, verify_backend_lowering)
    from verification.backend_lowering_plan import (
        verify_backend_lowering_plan)
    from verification.generated_c_ast_oracle import verify_generated_c_ast
    from verification.linux_registration_ast_oracle import (
        linux_kbuild_compile_context,
        verify_linux_registration_ast)

    name = res.formal["driver"]
    outdir = args.outdir or f"artifacts/output/{name}"
    gen_dir = os.path.join(outdir, "generated")
    ver_dir = os.path.join(outdir, "verify")
    tmp_dir = os.path.join(ver_dir, "tmp")
    for d in (outdir, gen_dir, ver_dir, tmp_dir):
        os.makedirs(d, exist_ok=True)

    def _w(base: str, path: str, text: str):
        with open(os.path.join(base, path), "w", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")

    def _ast_error_report(oracle: str, generated: str, exc,
                          **extra) -> dict:
        report = {
            "schema": 1,
            "oracle": oracle,
            "driver": name,
            "complete": False,
            "generated": generated,
            "verifier_error": type(exc).__name__,
            "message": str(exc),
            **extra,
        }
        if os.path.isfile(generated):
            with open(generated, "rb") as handle:
                report["generated_sha256"] = hashlib.sha256(
                    handle.read()).hexdigest()
        return report

    def _lowering_plan_fields(plan: dict | None) -> dict:
        return {
            "backend_lowering_plan_accounting_complete": bool(
                plan and plan.get("accounting_complete")),
            "backend_lowering_plan_classification_complete": bool(
                plan and plan.get("classification_complete")),
            "backend_lowering_plan_lowering_complete": bool(
                plan and plan.get("lowering_complete")),
            "backend_lowering_plan_authorization_complete": bool(
                plan and plan.get("authorization_complete")),
            "backend_lowering_plan_reconciliation_complete": bool(
                plan and plan.get("reconciliation_complete")),
            "backend_lowering_plan_definition_alignment_complete": bool(
                plan and plan.get("definition_alignment_complete")),
            "backend_lowering_plan_runtime_complete": bool(
                plan and plan.get("runtime_complete")),
            "backend_lowering_plan_strict_complete": bool(
                plan and plan.get("strict_complete")),
            "backend_lowering_plan": plan,
        }

    print(f"🚀 driver pipeline: {name} → {outdir}/")
    # ── core reconstruction inputs (docs/plans/output-artifact-recommendations.md) ──
    generation_contract = build_generation_contract(res.formal)
    generation_contract["synthesis_readiness"] = score_fn(
        res.device_spec, res.formal, res.warnings, res.facts)
    device_spec_document = device_spec_to_dict(res.device_spec)
    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.formal.json", json.dumps(
        res.formal, indent=2, sort_keys=True))
    _w(outdir, "generation-contract.json", json.dumps(
        generation_contract, indent=2, sort_keys=True))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.device-spec.json", json.dumps(
        device_spec_document, indent=2, sort_keys=True))
    _w(outdir, f"{name}.facts", res.facts.display())
    _w(ver_dir, "analysis.json", json.dumps({
        "stats": res.stats, "warnings": res.warnings,
    }, indent=2, sort_keys=True))

    # ── generated C + verification (derived) ──
    from generator.registry import list_backends
    gens = {name: mod for name, mod in list_backends().items()
            if name in ("harness", "baremetal", "linux")}
    source_oracle = verify_gpio_mmio_source_differential(
        res.formal, res.device_spec)
    sdhci_oracle = verify_sdhci_accessor_source_contract(res.formal)
    virtio_oracle = verify_virtio_state_contract(res.formal)
    w1c_contract = verify_w1c_drain_contract(res.formal, res.device_spec)
    transaction_oracle = verify_transaction_source(
        res.formal, os.path.abspath(args.source))
    _w(ver_dir, "gpio-mmio-source-oracle.json", json.dumps(
        source_oracle, indent=2, sort_keys=True))
    _w(ver_dir, "sdhci-accessor-oracle.json", json.dumps(
        sdhci_oracle, indent=2, sort_keys=True))
    _w(ver_dir, "virtio-state-oracle.json", json.dumps(
        virtio_oracle, indent=2, sort_keys=True))
    _w(ver_dir, "w1c-drain-oracle.json", json.dumps(
        w1c_contract, indent=2, sort_keys=True))
    _w(ver_dir, "transaction-ir-oracle.json", json.dumps(
        transaction_oracle, indent=2, sort_keys=True))
    binds, results, gen_results = [], {}, {}
    for backend, gen in gens.items():
        bind = default_bind(res.device_spec, backend)
        binds.append(bind)
        gen_kwargs = {}
        for kw in getattr(gen, "GEN_KWARGS", []):
            if kw == "facts":
                gen_kwargs["facts"] = res.facts
        code = gen.generate(res.formal, res.device_spec, bind, **gen_kwargs)
        cpath = os.path.join(gen_dir, f"{backend}.c")
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write(code)
        has_todo = "TODO" in code
        unsupported = "REHARNESS_UNSUPPORTED" in code
        lowering = verify_backend_lowering(res.formal, code)
        _w(ver_dir, f"{backend}-lowering.json", json.dumps(
            lowering, indent=2, sort_keys=True))
        lowering_plan = verify_backend_lowering_plan(
            res.formal, generation_contract, backend,
            device_spec=(res.device_spec if backend == "linux" else None),
            lowering_report=lowering)
        _w(ver_dir, f"{backend}-lowering-plan.json", json.dumps(
            lowering_plan, indent=2, sort_keys=True))
        ast_leaf = None
        if backend in {"harness", "baremetal"}:
            try:
                ast_leaf = verify_generated_c_ast(
                    generation_contract, cpath)
            except Exception as exc:
                ast_leaf = {
                    "schema": 1,
                    "oracle": "generated-c-ast-leaf-v1",
                    "complete": False,
                    "verifier_error": type(exc).__name__,
                    "message": str(exc),
                }
            _w(ver_dir, f"{backend}-ast-leaf.json", json.dumps(
                ast_leaf, indent=2, sort_keys=True))
        linux_registration_ast = None
        gr: dict = {
            "has_todo": has_todo, "unsupported": unsupported,
            "backend_lowering_complete": lowering["complete"],
            "backend_lowering": lowering,
            "backend_lowering_plan_required": True,
            **_lowering_plan_fields(lowering_plan),
            "backend_ast_leaf_required": backend in {
                "harness", "baremetal", "linux"},
            "backend_ast_leaf_complete": bool(
                ast_leaf and ast_leaf.get("complete")),
            "backend_ast_leaf": ast_leaf,
            "linux_ast_leaf_required": backend == "linux",
            "linux_ast_leaf_complete": False,
            "linux_ast_leaf": None,
            "linux_registration_ast_required": backend == "linux",
            "linux_registration_ast_complete": False,
            "linux_registration_ast": None,
            **source_oracle, **sdhci_oracle, **virtio_oracle,
            "transaction_ir_oracle_complete": transaction_oracle[
                "complete"],
            "transaction_ir_oracle": transaction_oracle,
            **w1c_contract,
        }

        if backend == "harness":
            binp = os.path.join(tmp_dir, "harness.bin")
            r = subprocess.run(["cc", "-o", binp, cpath], capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            if r.returncode == 0:
                executed = subprocess.run(
                    [binp], capture_output=True, text=True)
                out = executed.stdout
                _w(ver_dir, "harness.trace.txt", out)
                gr.update(verify_subsystem_callbacks(
                    res.formal, res.device_spec, out))
                gr.update(verify_w1c_drain_runtime(
                    res.formal, res.device_spec, out))
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
                from extractor.metrics import _computed_is_lowerable
                from verification.subsystem_callback_oracle import _eval

                def trace_offset(addr):
                    if "Symbolic" in addr:
                        return regs.get(addr["Symbolic"]["register"])
                    if "Fixed" in addr:
                        return addr["Fixed"]["offset"]
                    if ("Computed" in addr
                            and _computed_is_lowerable(addr["Computed"])):
                        return _eval(addr["Computed"], {})
                    return None

                if mod:
                    for o in mod["ops"]:   # top-level only (no Cond/Loop descent)
                        if "Write" in o:
                            addr = o["Write"]["addr"]
                            off = trace_offset(addr)
                            if off is None:
                                untraceable = True
                            else:
                                expected.append(("W", off))
                        elif "Read" in o:
                            addr = o["Read"]["addr"]
                            off = trace_offset(addr)
                            if off is None:
                                untraceable = True
                            else:
                                expected.append(("R", off))
                import re as _re
                traced = [(k, int(off, 16)) for k, off in
                          _re.findall(r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)", out)]
                # runtime trace must contain the unconditional ops as a
                # subsequence (conditional ops may appear interleaved)
                gr["trace_passed"] = (
                    executed.returncode == 0 and not untraceable
                    and _is_subsequence(expected, traced))
                results[backend] = f"compiled+ran ({out.count('[trace')} ops, trace {'✓' if gr['trace_passed'] else '✗'})"
            else:
                _w(ver_dir, "harness.compile.log", r.stderr)
                results[backend] = "compile FAILED (see verify/harness.compile.log)"
        elif backend == "baremetal":
            r = subprocess.run(["cc", "-ffreestanding", "-Wall", "-c", "-o", "/dev/null", cpath],
                               capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            plan = subsystem_callback_plan(res.formal, res.device_spec)
            drain_plan = w1c_drain_plan(res.formal, res.device_spec)
            if r.returncode == 0 and (plan or drain_plan):
                oracle_bin = os.path.join(tmp_dir, "baremetal-oracle.bin")
                oracle_compile = subprocess.run(
                    ["cc", "-DREHARNESS_BAREMETAL_ORACLE", "-Wall",
                     "-Wextra", "-o", oracle_bin, cpath],
                    capture_output=True, text=True)
                if oracle_compile.returncode == 0:
                    oracle_run = subprocess.run(
                        [oracle_bin], capture_output=True, text=True)
                    _w(ver_dir, "baremetal.callback.trace.txt",
                       oracle_run.stdout)
                    gr.update(verify_subsystem_callbacks(
                        res.formal, res.device_spec, oracle_run.stdout))
                    gr.update(verify_w1c_drain_runtime(
                        res.formal, res.device_spec, oracle_run.stdout))
                    if oracle_run.returncode != 0:
                        gr["subsystem_callback_oracle_passed"] = False
                        gr["subsystem_callback_oracle_errors"].append(
                            f"host oracle exited {oracle_run.returncode}")
                else:
                    gr.update({
                        "subsystem_callbacks_total": res.stats.get(
                            "synthetic_subsystem_functions", 0),
                        "subsystem_callbacks_executed": 0,
                        "subsystem_callback_oracle_passed": False,
                        "subsystem_callback_oracle_errors": [
                            oracle_compile.stderr[-2000:]],
                    })
            else:
                gr.update(verify_subsystem_callbacks(
                    res.formal, res.device_spec, ""))
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
            makefile = f"obj-m += {module_name}.o\n"
            if res.device_spec.cls == "sdhci":
                makefile += "ccflags-y += -I$(srctree)/drivers/mmc/host\n"
            _w(build_dir, "Makefile", makefile)
            repo_root = Path(__file__).resolve().parents[2]
            kernel_dir = os.environ.get(
                "KERNELDIR", os.fspath(repo_root / "platform/kernel/build"))
            r = subprocess.run(
                ["make", "-C", kernel_dir, f"M={build_dir}", "modules"],
                capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            gr["syntax_ok"] = r.returncode == 0
            if r.returncode != 0:
                _w(ver_dir, "linux.compile.log", r.stdout + "\n" + r.stderr)
            required_ids = set(
                lowering_plan.get("strict_eligible_op_ids") or [])
            kbuild_cmd = os.path.join(
                build_dir, f".{module_name}.o.cmd")
            if r.returncode == 0:
                linux_compile_context = None
                try:
                    clang_args, linux_compile_context = \
                        linux_kbuild_compile_context(
                            Path(module_c), Path(kbuild_cmd))
                    ast_leaf = verify_generated_c_ast(
                        generation_contract, module_c,
                        clang_args=clang_args,
                        required_op_ids=required_ids,
                        compile_context=linux_compile_context)
                except Exception as exc:
                    ast_leaf = _ast_error_report(
                        "generated-c-ast-leaf-v1", module_c, exc,
                        required_op_ids=sorted(required_ids),
                        required_ast_ops=len(required_ids),
                        compile_context=linux_compile_context)
                try:
                    linux_registration_ast = verify_linux_registration_ast(
                        generation_contract, res.device_spec, module_c,
                        lowering_plan, kbuild_cmd=kbuild_cmd)
                except Exception as exc:
                    linux_registration_ast = _ast_error_report(
                        "linux-registration-ast-v1", module_c, exc,
                        runtime_registered_op_ids=[], operations=[])
            else:
                failure = RuntimeError(
                    "Linux Kbuild did not succeed; AST evidence unavailable")
                ast_leaf = _ast_error_report(
                    "generated-c-ast-leaf-v1", module_c, failure,
                    required_op_ids=sorted(required_ids),
                    required_ast_ops=len(required_ids))
                linux_registration_ast = _ast_error_report(
                    "linux-registration-ast-v1", module_c, failure,
                    runtime_registered_op_ids=[], operations=[])

            _w(ver_dir, "linux-ast-leaf.json", json.dumps(
                ast_leaf, indent=2, sort_keys=True))
            _w(ver_dir, "linux-registration-ast.json", json.dumps(
                linux_registration_ast, indent=2, sort_keys=True))
            lowering_plan = verify_backend_lowering_plan(
                res.formal, generation_contract, "linux",
                device_spec=res.device_spec,
                lowering_report=lowering,
                runtime_attestation=linux_registration_ast,
                ast_leaf_report=ast_leaf,
                generated_artifact=module_c,
                kbuild_cmd=kbuild_cmd)
            _w(ver_dir, "linux-lowering-plan.json", json.dumps(
                lowering_plan, indent=2, sort_keys=True))
            gr.update(_lowering_plan_fields(lowering_plan))
            gr.update({
                "backend_ast_leaf_complete": bool(
                    ast_leaf and ast_leaf.get("complete")),
                "backend_ast_leaf": ast_leaf,
                "linux_ast_leaf_complete": bool(
                    ast_leaf and ast_leaf.get("complete")),
                "linux_ast_leaf": ast_leaf,
                "linux_registration_ast_complete": bool(
                    linux_registration_ast
                    and linux_registration_ast.get("complete")),
                "linux_registration_ast": linux_registration_ast,
            })
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

    # merged .bind (docs/plans/output-artifact-recommendations.md §"Merge Backend Bind Files")
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
    for f in (f"{name}.ris", f"{name}.formal.json",
              "generation-contract.json", f"{name}.dspec",
              f"{name}.device-spec.json",
              f"{name}.bind", f"{name}.facts"):
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
