"""Experiment V2: LangGraph subgraph — real drivers + QEMU closed loop.

Flow:
  build_driver (compile/stage original .ko)
    → ris_extract (RIS + generation contract)
    → llm_gen_tests (LLM generates test commands; falls back to manifest exerciser)
    → baseline_qemu (run original via the Python guest runner)
    → llm_synthesize (LLM generates candidate code)
    → candidate_compile (compile candidate)
    → candidate_qemu (run candidate with the same tests)
    → diff_compare (baseline vs candidate outcome)
    → repair (on mismatch/compile failure; bounded) → llm_synthesize
    → finalize

Module providers:
  source_build — single-file kbuild; module name = manifest runtime.qemu.module
                 (KBUILD_MODNAME controls the /dev node the exerciser opens).
  kernel_tree  — driver lives in vendor/linux; the prebuilt .ko from the kernel
                 build tree is used directly (dash/underscore name mapping).
"""
from __future__ import annotations

import json
import re
import sys
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parents[2]
KERNEL_BUILD = ROOT / "platform/kernel/build"
QEMU_RUN_PY = ROOT / "qa/verification/qemu_run.py"

_repair_count_file = os.path.join(tempfile.gettempdir(), "v2_repair_count")



def _get_rc() -> int:
    try:
        return int(Path(_repair_count_file).read_text())
    except (FileNotFoundError, ValueError):
        return 0


def _reset_rc() -> None:
    Path(_repair_count_file).write_text("0")


def _inc_rc() -> None:
    Path(_repair_count_file).write_text(str(_get_rc() + 1))


def parse_rhcov(serial: str) -> set[str]:
    """Return the set of functions whose [rhcov] probe fired in the serial."""
    return set(re.findall(r"\[rhcov\] ([A-Za-z_]\w*)", serial))


def coverage_summary(covered: set[str], inventory: list[str]) -> dict[str, Any]:
    """Whole-driver function coverage against the probe inventory."""
    unique = list(dict.fromkeys(inventory))
    hits = sorted(covered.intersection(unique))
    return {
        "covered": hits,
        "covered_count": len(hits),
        "total": len(unique),
        "pct": round(100.0 * len(hits) / len(unique), 1) if unique else None,
    }


def _inject_cov(text: str) -> tuple[str, list[str]]:
    """Inject [rhcov] probes via tools/source/inject_function_coverage."""
    import sys
    tool_dir = str(ROOT / "tools" / "source")
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    from inject_function_coverage import inject
    return inject(text)


def manifest_qemu_meta(manifest_path: str | Path) -> dict[str, str]:
    """Read qemu module name + success pattern from a manifest JSON."""
    with open(manifest_path) as fh:
        doc = json.load(fh)
    qemu = doc.get("runtime", {}).get("qemu", {}) or {}
    return {
        "module": str(qemu.get("module") or doc.get("name", "module")),
        "success_pattern": str(doc.get("test", {}).get("success_pattern") or ""),
    }


class V2State(TypedDict, total=False):
    build_ok: bool
    driver_ko: str
    formal_model: dict
    generation_contract: dict
    evidence_dir: str
    test_commands: list
    baseline_trace: str
    baseline_pass: bool
    candidate_source: str
    candidate_ko: str
    compile_ok: bool
    qemu_ok: bool
    diff_equal: bool
    repair_exhausted: bool
    last_compile_log: str
    last_serial_tail: str
    generation_result: dict
    accepted: bool
    status: str
    test_script: str
    baseline_inventory: list
    candidate_inventory: list
    baseline_coverage: dict
    candidate_coverage: dict


def _prebuilt_kernel_ko(qemu_mod: str) -> Path | None:
    """Locate a prebuilt module in the kernel build tree.

    Kernel-tree module names use dashes (usb-storage) while manifest qemu
    module names use underscores (usb_storage); try both spellings.
    """
    for name in (qemu_mod, qemu_mod.replace("_", "-")):
        hits = sorted(KERNEL_BUILD.rglob(f"{name}.ko"))
        if hits:
            return hits[0]
    return None


def build_experiment_v2(
    *,
    driver_source: str,
    driver_name: str,
    manifest_path: str,
    llm_bridge: Any = None,
    output_root: str,
    max_repair: int = 3,
    executors: dict[str, Any] | None = None,
):
    """Build the V2 experiment subgraph."""
    repo_manifest = Path(manifest_path)
    if not repo_manifest.is_absolute():
        repo_manifest = ROOT / repo_manifest
    src = Path(driver_source)
    if not src.is_absolute():
        src = ROOT / src
    meta = manifest_qemu_meta(repo_manifest)
    qemu_mod = meta["module"]
    success_pattern = meta["success_pattern"]

    provider = ("kernel_tree"
                if src.resolve().is_relative_to(ROOT / "vendor" / "linux")
                else "source_build")
    prebuilt_ko = _prebuilt_kernel_ko(qemu_mod) if provider == "kernel_tree" else None

    out = Path(output_root)
    evd = out / "evidence"
    bld = out / "build"
    base = out / "baseline"
    cand = out / "candidate"
    for d in (out, evd, bld, base, cand):
        d.mkdir(parents=True, exist_ok=True)
    _reset_rc()

    # ── 每轮修复的可审查记录 ──────────────────────────────────────
    repairs_root = out / "repairs"
    repairs_root.mkdir(parents=True, exist_ok=True)
    _round = {"n": 0}

    def _round_dir() -> Path:
        return repairs_root / f"round-{_round['n']:03d}"

    def _round_update(**fields) -> None:
        path = _round_dir() / "round.json"
        doc = {}
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                doc = {}
        doc.update(fields)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False,
                                   default=str) + "\n", encoding="utf-8")

    def _begin_round() -> None:
        _round["n"] += 1
        import langchain_bridge
        d = _round_dir() / "llm"
        d.mkdir(parents=True, exist_ok=True)
        langchain_bridge.set_transcript_dir(d, label=f"round-{_round['n']:03d}")
        _round_update(round=_round["n"], started=time.strftime("%H:%M:%S"))

    with open(repo_manifest) as fh:
        manifest_doc = json.load(fh)

    qemu_executor = (executors or {}).get("qemu_run")
    kbuild_executor = (executors or {}).get("kbuild")
    kernel_tree_executor = (executors or {}).get("kernel_tree")
    backend_pipeline_executor = (executors or {}).get("backend_pipeline")

    def _kbuild(source_c: Path, module_name: str, build_dir: Path,
                ) -> tuple[Path | None, list[str]]:
        """Compile a single-file kernel module with [rhcov] probes injected.

        Returns (ko_path_or_None, coverage_inventory). Trimmed baseline
        sources may lack module metadata macros; modpost hard-requires
        MODULE_LICENSE, so append the standard GPL boilerplate when missing
        (never modifies the benchmark source itself).
        """
        if kbuild_executor is not None:
            return kbuild_executor(source_c, module_name, build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        text = source_c.read_text()
        try:
            text, inventory = _inject_cov(text)
        except Exception:
            inventory = []
        extras = []
        if "MODULE_LICENSE" not in text:
            extras += ['MODULE_LICENSE("GPL");',
                       'MODULE_DESCRIPTION("reharness V2 baseline module");']
        staged = build_dir / f"{module_name}.c"
        staged.write_text(text + "\n" + "\n".join(extras) + ("\n" if extras else ""))
        (build_dir / "Makefile").write_text(f"obj-m += {module_name}.o\n")
        proc = subprocess.run(
            ["make", "-C", str(KERNEL_BUILD), f"M={build_dir.resolve()}", "modules"],
            capture_output=True, text=True)
        (build_dir / "build.log").write_text(
            ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-4000:])
        ko = build_dir / f"{module_name}.ko"
        return (ko if ko.is_file() else None), inventory

    def _kernel_tree_instrumented() -> tuple[Path | None, list[str]]:
        """Instrument the vendor source dir, rebuild in-tree, restore the tree.

        Mirrors the V1 suite flow: inject probes into every source file of
        the driver directory, build the in-tree kbuild target, copy the
        instrumented .ko to the V2 build dir, then git-restore the vendor
        tree so the injection is temporary.
        """
        if kernel_tree_executor is not None:
            return kernel_tree_executor()
        src_dir = src.parent
        inventory: list[str] = []
        for c in sorted(src_dir.glob("*.c")):
            text = c.read_text(errors="replace")
            try:
                new_text, fns = _inject_cov(text)
            except Exception:
                continue
            if new_text != text:
                c.write_text(new_text)
            inventory += fns
        rel = src_dir.relative_to(ROOT / "vendor" / "linux").as_posix()
        reference = prebuilt_ko.relative_to(KERNEL_BUILD).as_posix() if prebuilt_ko else None
        targets = [reference] if reference else [
            f"{rel}/{qemu_mod}.ko", f"{rel}/{qemu_mod.replace('_', '-')}.ko"]
        built: Path | None = None
        for target in filter(None, targets):
            subprocess.run(
                ["make", "-C", str(ROOT / "vendor" / "linux"),
                 f"O={KERNEL_BUILD}", target],
                capture_output=True, text=True)
            candidate_ko = KERNEL_BUILD / target
            if candidate_ko.is_file():
                built = candidate_ko
                break
        subprocess.run(
            ["git", "-C", str(ROOT / "vendor" / "linux"), "checkout", "--", rel],
            capture_output=True, text=True)
        if built is None:
            return None, []
        staged = bld / qemu_mod / f"{qemu_mod}.ko"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, staged)
        return staged, inventory

    def _ensure_backing_files() -> None:
        """Create fixture backing files declared in the manifest if missing."""
        fixture = (manifest_doc.get("runtime", {}).get("fixture") or {})
        cfg = fixture.get("config") or {}
        backing = cfg.get("backing_file")
        if not backing:
            return
        path = Path(backing)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["truncate", "-s", str(cfg.get("backing_size", "64M")),
                            str(path)], check=True)

    def _run_qemu_experiment(module_ko: Path, work_dir: Path,
                             timeout: int = 120,
                             extra_tests: Path | None = None) -> dict:
        """Stage module under the manifest's qemu module name; run the guest."""
        if qemu_executor is not None:
            return qemu_executor(module_ko, work_dir, extra_tests=extra_tests)
        _ensure_backing_files()
        stage = work_dir / "staged" / qemu_mod
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module_ko, stage / f"{qemu_mod}.ko")

        serial_path = work_dir / "serial.log"
        env = {
            **os.environ,
            "RH_QEMU_MODULE_OUTPUT_ROOT": str(work_dir / "staged"),
            "RH_QEMU_RUN_ID": f"v2-{qemu_mod}-{work_dir.name}",
            "RH_QEMU_OUT": str(serial_path),
            "RH_QEMU_KEEP_RUNTIME": "1",
        }
        if extra_tests is not None and Path(extra_tests).is_file():
            env["RH_QEMU_EXTRA_TESTS"] = str(extra_tests)
        rc = -1
        try:
            proc = subprocess.run(
                [sys.executable, str(QEMU_RUN_PY), "--manifest", str(repo_manifest)],
                env=env, capture_output=True, text=True, timeout=timeout + 60)
            rc = proc.returncode
            (work_dir / "qemu_run.stdout").write_text(proc.stdout[-4000:])
            (work_dir / "qemu_run.stderr").write_text(proc.stderr[-4000:])
        except subprocess.TimeoutExpired:
            (work_dir / "qemu_run.stderr").write_text("TIMEOUT")

        serial = (serial_path.read_text(errors="replace")
                  if serial_path.exists() else "")
        ok = bool(success_pattern) and success_pattern in serial
        return {"serial": serial, "pass": ok,
                "serial_path": str(serial_path), "rc": rc}

    def build_driver(s: V2State) -> dict:
        """Provide the original driver module with [rhcov] probes.

        source_build: compile the single source file under the manifest's
        qemu module name (KBUILD_MODNAME controls the /dev node).
        kernel_tree: instrument the vendor source directory, rebuild the
        in-tree kbuild target, copy the module, then restore the tree.
        """
        if provider == "kernel_tree":
            ko, inventory = _kernel_tree_instrumented()
            return {"build_ok": ko is not None,
                    "driver_ko": str(ko) if ko else "",
                    "baseline_inventory": inventory}
        ko, inventory = _kbuild(src, qemu_mod, bld / qemu_mod)
        return {"build_ok": ko is not None,
                "driver_ko": str(ko) if ko else "",
                "baseline_inventory": inventory}

    def ris_extract(s: V2State) -> dict:
        """Extract RIS + generation contract evidence."""
        import sys
        for p in (str(ROOT / "src"), str(ROOT / "qa"),
                  str(ROOT / "qa" / "verification")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from extractor import ExtractorConfig, extract_ris
        from gate.backend_lowering_oracle import build_generation_contract

        cfg = ExtractorConfig(source=str(src), driver_name=driver_name)
        result = extract_ris(cfg)
        formal = result.formal
        contract = build_generation_contract(formal)
        return {
            "formal_model": formal,
            "generation_contract": contract,
            "evidence_dir": str(evd),
        }

    def llm_gen_tests(s: V2State) -> dict:
        """LLM generates test commands; the manifest exerciser remains the
        in-guest driver of the run (the guest runner consumes it from the
        manifest),
        so generated commands are recorded as evidence for coverage follow-up."""
        formal = s.get("formal_model") or {}
        ops_summary = []
        for mod in formal.get("modules", []):
            fn = mod.get("name", "?")
            for op in mod.get("ops", []):
                ops_summary.append(f"{fn}: {next(iter(op), '?')}")

        commands: list[str] = []
        if llm_bridge is not None and hasattr(llm_bridge, "invoke_text"):
            prompt = (
                f"Generate Linux shell commands to test kernel module "
                f"'{qemu_mod}' in a QEMU guest.\nOperations:\n"
                + "\n".join(ops_summary[:20])
                + "\nOne command per line, no commentary.")
            try:
                resp = llm_bridge.invoke_text(prompt)
                commands = [ln.strip() for ln in resp.splitlines()
                            if ln.strip() and not ln.startswith("#")]
            except Exception:
                commands = []
        (evd / f"{driver_name}.test_commands.json").write_text(
            json.dumps({"commands": commands}, indent=2))
        state: dict[str, Any] = {"test_commands": commands}
        if commands:
            script = evd / f"{driver_name}.llm-tests.sh"
            script.write_text("#!/bin/sh\n" + "\n".join(commands) + "\n")
            script.chmod(0o755)
            state["test_script"] = str(script)
        return state

    def baseline_qemu(s: V2State) -> dict:
        """Run the ORIGINAL module in QEMU."""
        ko = s.get("driver_ko") or ""
        if not ko or not Path(ko).is_file():
            return {"baseline_trace": "", "baseline_pass": False}
        extra = Path(s.get("test_script")) if s.get("test_script") else None
        result = _run_qemu_experiment(Path(ko), base / "qemu",
                                      extra_tests=extra)
        coverage = coverage_summary(parse_rhcov(result["serial"]),
                                    s.get("baseline_inventory") or [])
        return {"baseline_trace": result["serial_path"],
                "baseline_pass": result["pass"],
                "baseline_coverage": coverage}

    def _bridge_manifest():
        """Manifest adapter for the LangChain bridge protocol.

        The bridge needs a 64-hex digest plus compile/runtime context (for
        backend-specific generation rules); V2 reads the manifest as plain
        JSON, so wrap it with the attributes the protocol consumes.
        """
        from types import SimpleNamespace
        import hashlib
        digest = hashlib.sha256(
            Path(repo_manifest).read_bytes()).hexdigest()
        qemu = manifest_doc.get("runtime", {}).get("qemu", {}) or {}
        compile_ctx = manifest_doc.get("compile", {}) or {}
        runtime_ctx = dict(manifest_doc.get("runtime", {}) or {})
        runtime_ctx.pop("qemu", None)
        return SimpleNamespace(
            digest=digest,
            name=driver_name,
            compile=SimpleNamespace(
                backend=str(compile_ctx.get("backend", "linux")),
                language=str(compile_ctx.get("language", "c")),
                context=str(compile_ctx.get("context", "kbuild")),
            ),
            runtime=SimpleNamespace(
                adapter=str(runtime_ctx.get("adapter", "")),
                qemu=SimpleNamespace(
                    bus=str(qemu.get("bus", "")),
                ),
            ),
        )

    def _repair_feedback(s: V2State) -> dict[str, Any] | None:
        """Build structured feedback from the last candidate failure."""
        if _get_rc() == 0:
            return None
        if s.get("last_compile_log"):
            return {
                "failure_class": "compile",
                "stage": "candidate_compile",
                "message": "candidate failed to compile",
                "details": {"repair_requirements": {
                    "fix_compile_errors": "resolve every compiler error "
                    "below; emit complete, self-contained kernel C using "
                    "only real kernel APIs",
                    "compiler_output": str(s["last_compile_log"])[-2500:],
                }},
            }
        if s.get("last_serial_tail"):
            return {
                "failure_class": "runtime",
                "stage": "candidate_qemu",
                "message": f"candidate booted but success pattern "
                           f"'{success_pattern}' not observed",
                "details": {"repair_requirements": {
                    "fix_runtime_behavior": "module must probe the device "
                    "and pass the manifest exerciser",
                    "serial_evidence": str(s["last_serial_tail"])[-2000:],
                }},
            }
        return None

    def llm_synthesize(s: V2State) -> dict:
        """Generate for ALL FOUR backends + full verification + artifacts.

        Calls the shared backend pipeline (oracle fan-out ×5, backend
        fan-out ×4, generated/ + verify/ artifacts) — the same machinery
        and the shared backend-pipeline output format.  The
        linux generated module becomes the QEMU candidate; repair rounds
        feed backend/compiler evidence back through the LLM bridge.
        """
        _begin_round()
        _round_update(repair_round=_get_rc(),
                      failure_before=_repair_feedback(s))
        try:
            import sys as _sys
            for entry in (str(ROOT / "src"), str(ROOT / "qa"),
                          str(ROOT / "qa" / "verification")):
                if entry not in _sys.path:
                    _sys.path.insert(0, entry)
            from backends.pipeline import run_backend_pipeline
            from extractor import ExtractorConfig, extract_ris

            extraction = extract_ris(ExtractorConfig(
                source=str(src), driver_name=driver_name))
            if backend_pipeline_executor is not None:
                pipeline_out = backend_pipeline_executor(
                    extraction, str(out), str(src))
            else:
                pipeline_out = run_backend_pipeline(
                    extraction, str(out), str(src))
            linux_generated = (Path(out) / "generated" / "linux.c")
            linux_ko = None
            linux_tmp = out / "verify" / "tmp" / "linux-module"
            for ko in linux_tmp.rglob("*.ko"):
                linux_ko = ko
                break
            update: dict[str, Any] = {"generation_result": pipeline_out}
            if linux_generated.is_file():
                update["candidate_source"] = str(linux_generated)
            if linux_ko is not None and linux_ko.is_file():
                staged = cand / "build" / f"{qemu_mod}.ko"
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(linux_ko, staged)
                update["candidate_ko"] = str(staged)
                update["candidate_inventory"] = s.get(
                    "baseline_inventory") or []
            update["compile_ok"] = bool(
                pipeline_out.get("gen_results", {}).get("linux", {}).get(
                    "compiled"))
            _round_update(
                backends=pipeline_out.get("gen_results", {}),
                compile_ok=update["compile_ok"],
                candidate_source=update.get("candidate_source", ""),
                candidate_ko=update.get("candidate_ko", ""))
            if not update["compile_ok"]:
                log = out / "verify" / "linux.compile.log"
                update["last_compile_log"] = (
                    log.read_text(errors="replace")[-2500:]
                    if log.is_file() else
                    json.dumps(pipeline_out.get("backend_results", {})))
            return update
        except Exception as exc:
            import traceback
            traceback.print_exc()
            _round_update(compile_ok=False, pipeline_error=str(exc)[:500])
            return {"candidate_source": "", "compile_ok": False,
                    "synthesis_error": str(exc),
                    "last_compile_log": str(exc)[-2500:]}


    def candidate_compile(s: V2State) -> dict:
        """Compile the candidate. The backend pipeline already produced the
        linux .ko (staged by llm_synthesize); fall back to kbuild only when
        a candidate source exists but no staged .ko does."""
        staged = bld / qemu_mod / f"{qemu_mod}.ko"
        if s.get("candidate_ko") and Path(s["candidate_ko"]).is_file():
            return {"compile_ok": True,
                    "candidate_ko": s["candidate_ko"],
                    "candidate_inventory": s.get("candidate_inventory") or []}
        if provider == "kernel_tree":
            ko = (staged if staged.is_file()
                  else prebuilt_ko if prebuilt_ko is not None
                  and prebuilt_ko.is_file() else None)
            if ko is None:
                return {"compile_ok": False, "candidate_ko": ""}
            return {"compile_ok": True, "candidate_ko": str(ko),
                    "candidate_inventory": s.get("baseline_inventory") or []}
        cand_src = Path(s.get("candidate_source") or "")
        if not cand_src.is_file() or not cand_src.read_text().strip():
            return {"compile_ok": False, "candidate_ko": "",
                    "last_compile_log": s.get("last_compile_log") or
                    "candidate source is empty"}
        ko, inventory = _kbuild(cand_src, qemu_mod, cand / "build")
        log = ""
        build_log = cand / "build" / "build.log"
        if ko is None and build_log.is_file():
            log = build_log.read_text(errors="replace")
        return {"compile_ok": ko is not None,
                "candidate_ko": str(ko) if ko else "",
                "candidate_inventory": inventory,
                "last_compile_log": log}


    def candidate_qemu(s: V2State) -> dict:
        """Run the CANDIDATE module in QEMU with the same manifest tests."""
        ko = s.get("candidate_ko") or ""
        if not ko or not Path(ko).is_file():
            return {"qemu_ok": False, "candidate_trace": ""}
        extra = Path(s.get("test_script")) if s.get("test_script") else None
        result = _run_qemu_experiment(Path(ko), cand / "qemu",
                                      extra_tests=extra)
        coverage = coverage_summary(parse_rhcov(result["serial"]),
                                    s.get("candidate_inventory") or [])
        tail = ""
        if not result["pass"]:
            lines = [ln for ln in result["serial"].splitlines()
                     if any(k in ln for k in
                            ("insmod", "probe", "TRACE", "FAIL", "error",
                             "Error", "rhcov"))]
            tail = "\n".join(lines[-25:])
        try:
            shutil.copy2(result["serial_path"], _round_dir() / "qemu-serial.log")
        except Exception:
            pass
        _round_update(qemu_ok=result["pass"],
                      coverage=coverage,
                      serial_tail=tail or None)
        return {"qemu_ok": result["pass"],
                "candidate_trace": result["serial_path"],
                "candidate_coverage": coverage,
                "last_serial_tail": tail}

    def diff_compare(s: V2State) -> dict:
        equal = bool(s.get("baseline_pass")) and bool(s.get("qemu_ok"))
        return {"diff_equal": equal,
                "diff_detail": {"baseline_ok": bool(s.get("baseline_pass")),
                                "candidate_ok": bool(s.get("qemu_ok"))}}

    def repair(s: V2State) -> dict:
        _round_update(next_repair_directive=_repair_feedback(s),
                      repair_requested=_get_rc() + 1)
        _inc_rc()
        if _get_rc() > max_repair:
            _round_update(repair_exhausted=True)
            return {"repair_exhausted": True}
        return {}

    def finalize(s: V2State) -> dict:
        accepted = bool(s.get("diff_equal"))
        document = {
            "schema": "reharness-experiment-v2",
            "driver": driver_name,
            "qemu_module": qemu_mod,
            "provider": provider,
            "manifest": str(repo_manifest),
            "accepted": accepted,
            "status": "accepted" if accepted else "failed",
            "repair_count": _get_rc(),
            "baseline_pass": bool(s.get("baseline_pass")),
            "candidate_pass": bool(s.get("qemu_ok")),
            "baseline_coverage": s.get("baseline_coverage"),
            "candidate_coverage": s.get("candidate_coverage"),
            "baseline_trace": s.get("baseline_trace"),
            "candidate_trace": s.get("candidate_trace"),
        }
        rounds = []
        for rd in sorted(repairs_root.glob("round-*")):
            rj = rd / "round.json"
            if rj.is_file():
                try:
                    rounds.append(json.loads(rj.read_text(encoding="utf-8")))
                except Exception:
                    pass
        document["rounds"] = rounds
        (out / "experiment.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n")
        return {"accepted": accepted,
                "status": "accepted" if accepted else "failed"}

    # ===== routing =====

    def route_compile(s: V2State) -> str:
        return "candidate_qemu" if s.get("compile_ok") else "repair"

    def route_qemu(s: V2State) -> str:
        return "diff_compare" if s.get("qemu_ok") else "repair"

    def route_diff(s: V2State) -> str:
        return "finalize" if s.get("diff_equal") else "repair"

    def route_repair(s: V2State) -> str:
        return "finalize" if _get_rc() > max_repair else "llm_synthesize"

    # ===== assemble =====

    builder = StateGraph(V2State)
    for name, fn in [
        ("build_driver", build_driver),
        ("ris_extract", ris_extract),
        ("llm_gen_tests", llm_gen_tests),
        ("baseline_qemu", baseline_qemu),
        ("llm_synthesize", llm_synthesize),
        ("candidate_compile", candidate_compile),
        ("candidate_qemu", candidate_qemu),
        ("diff_compare", diff_compare),
        ("repair", repair),
        ("finalize", finalize),
    ]:
        builder.add_node(name, fn)

    builder.add_edge(START, "build_driver")
    builder.add_edge("build_driver", "ris_extract")
    builder.add_edge("ris_extract", "llm_gen_tests")
    builder.add_edge("llm_gen_tests", "baseline_qemu")
    builder.add_edge("baseline_qemu", "llm_synthesize")
    builder.add_edge("llm_synthesize", "candidate_compile")
    builder.add_conditional_edges(
        "candidate_compile", route_compile,
        {"candidate_qemu": "candidate_qemu", "repair": "repair"})
    builder.add_conditional_edges(
        "candidate_qemu", route_qemu,
        {"diff_compare": "diff_compare", "repair": "repair"})
    builder.add_conditional_edges(
        "diff_compare", route_diff,
        {"finalize": "finalize", "repair": "repair"})
    builder.add_conditional_edges(
        "repair", route_repair,
        {"llm_synthesize": "llm_synthesize", "finalize": "finalize"})
    builder.add_edge("finalize", END)
    return builder.compile()
