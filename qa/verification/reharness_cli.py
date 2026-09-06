#!/usr/bin/env python3
"""reharness 命令行入口（纯 Python，取代原 bash 版 run.sh 的分发层）。

子命令与旧 run.sh 一一对应；所有逻辑由本模块编排并转发到各 Python
runner/CLI。``run.sh`` 保留为单行兼容转发（无任何逻辑）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
QA = ROOT / "qa"
VERIFICATION = QA / "verification"
OUTPUT_ROOT = ROOT / "artifacts/output"

PY = sys.executable or "python3"

_USAGE = """\
Usage: reharness <command> [args]

Commands:
  extract <src> [out.ris]   extract RIS spec language from a C driver
  show <ris>                print a .ris file
  spec <src> [out.dspec]    infer & print backend-independent .dspec
  gen <src> <backend> [out.c]   generate C/RS (backend: harness|baremetal|linux|rust_baremetal)
  gen-pair <src> <backend> [out_base]   generate .h + .c pair
  facts <src>                  source facts (.facts) for LLM synthesis
  bundle <src> [backend] [outdir]   build LLM input bundle (RIS+dspec+bind+facts)
  metrics <src>             per-module extraction quality metrics
  score <src>               generation readiness scoring
  reliability [src ...]     machine-readable scoped RIS reliability report
  compare [-j N]            per-driver extraction stats (N=parallel jobs, 0=auto)
  test                      run the test suite
  v2 <manifest...>          V2 closed-loop experiments with function coverage
  qemu --manifest PATH      boot a module in the QEMU guest runner
  log-event <message ...>   append an engineering timeline event

The .ris spec language remains the sole RIS artifact format; reliability
emits a separate audit JSON and does not replace the RIS.
"""


def _run(argv: list[str], *, module: str | None = None,
         script: Path | None = None) -> int:
    """Run a child Python entry with the repo import path prepared."""
    command = [PY]
    if module:
        command += ["-m", module]
    elif script:
        command += [str(script)]
    else:
        raise ValueError("module or script required")
    command += argv
    return subprocess.run(command, cwd=ROOT).returncode


def _forward(script_name: str) -> int:
    return _run([], script=VERIFICATION / script_name)


def cmd_extract(args: list[str]) -> int:
    if not args:
        print("usage: reharness extract <src> [out.ris]")
        return 1
    src, out = args[0], (args[1] if len(args) > 1
                         else str(OUTPUT_ROOT / "ris.ris"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return _run(["extract", "-s", src, "-o", out], module="extractor")


def cmd_show(args: list[str]) -> int:
    if not args:
        print("usage: reharness show <ris>")
        return 1
    sys.stdout.write(Path(args[0]).read_text(encoding="utf-8"))
    return 0


def cmd_spec(args: list[str]) -> int:
    if not args:
        print("usage: reharness spec <src> [out.dspec]")
        return 1
    argv = ["spec", "-s", args[0]]
    if len(args) > 1:
        argv += ["-o", args[1]]
    return _run(argv, module="extractor")


def _gen_args(args: list[str], *, pair: bool) -> list[str]:
    if len(args) < 2:
        raise SystemExit(
            "usage: reharness gen[-pair] <src> <backend> [out]")
    argv = ["gen", "-s", args[0], "-b", args[1]]
    if pair:
        argv.append("--pair")
    if len(args) > 2:
        argv += ["-o", args[2]]
    return argv


def cmd_gen(args: list[str]) -> int:
    return _run(_gen_args(args, pair=False), module="extractor")


def cmd_gen_pair(args: list[str]) -> int:
    return _run(_gen_args(args, pair=True), module="extractor")


def cmd_metrics(args: list[str]) -> int:
    return _run(["metrics", "-s", args[0]], module="extractor")


def cmd_facts(args: list[str]) -> int:
    argv = ["facts", "-s", args[0]]
    if len(args) > 1:
        argv += ["-o", args[1]]
    return _run(argv, module="extractor")


def cmd_bundle(args: list[str]) -> int:
    argv = ["bundle", "-s", args[0], "-b", args[1] if len(args) > 1
            else "harness"]
    if len(args) > 2:
        argv += ["-o", args[2]]
    return _run(argv, module="extractor")


def cmd_score(args: list[str]) -> int:
    return _run(["score", "-s", args[0]], module="extractor")


def cmd_reliability(args: list[str]) -> int:
    return _forward("reliability_report.py") if not args else _run(
        args, script=VERIFICATION / "reliability_report.py")


def cmd_compare(args: list[str]) -> int:
    return _run(args, script=VERIFICATION / "compare.py")


def cmd_qemu(args: list[str]) -> int:
    return _run(args, script=VERIFICATION / "qemu_run.py")


def cmd_intermediates(args: list[str]) -> int:
    """(Re)generate the reviewable intermediate chain for driver sources."""
    if not args:
        print("usage: reharness intermediates <driver.c> [more.c ...]")
        return 1
    import os
    # dumping is opt-in for ordinary runs; this command exists to enable it
    os.environ["REHARNESS_DUMP_INTERMEDIATES"] = "1"
    from extractor import ExtractorConfig, extract_ris
    from extractor.formal import formal_display
    from extractor.intermediates import intermediates_root
    root = intermediates_root()
    for src in args:
        res = extract_ris(ExtractorConfig(source=src))
        stem = Path(src).stem
        d = root / stem
        # textual RIS for quick reading alongside the JSON chain
        (d / "05-merged-ris.txt").write_text(formal_display(res.formal),
                                             encoding="utf-8")
        files = sorted(q.name for q in d.iterdir() if q.is_file())
        print(f"── {stem}: {d}")
        for name in files:
            size = (d / name).stat().st_size
            print(f"     {name:22} {size:>9,} B")
    return 0


def cmd_v2(args: list[str]) -> int:
    return _run(args, script=VERIFICATION / "run_v2_experiment.py")


def cmd_log_event(args: list[str]) -> int:
    if not args:
        print("usage: reharness log-event <message> [detail]")
        return 1
    event, detail = args[0], (args[1] if len(args) > 1 else "")
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    stamp = now.strftime("%Y%m%d-%H%M%S")
    log = ROOT / "research/history/timeline.md"
    if not log.is_file():
        log.write_text("# reharness 端到端时间线\n\n", encoding="utf-8")
    lines = [f"## [{timestamp}] {event}\n"]
    if detail:
        lines += [f"  {line}\n" for line in detail.splitlines()]
    lines.append("\n")
    with log.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)
    entry = ROOT / "research/history" / f"{stamp}.txt"
    entry.write_text(
        f"[{timestamp}] {event}\n" + (detail + "\n" if detail else ""),
        encoding="utf-8")
    print(f"logged: {event}")
    return 0


_SUITE_STANDALONE = (
    "check_generalization_guard.py",
    "test_repository_layout.py",
    "test_run_dispatcher.py",
    "test_repository_paths.py",
    "test_extractor.py",
    "test_generated_c_ast_oracle.py",
    "test_linux_registration_contracts.py",
    "test_linux_registration_ast_oracle.py",
    "test_backend_lowering_plan.py",
    "test_metrics_c20_readiness.py",
    "test_dataflow_read_return.py",
    "test_device_spec_json.py",
)

_SUITE_PYTEST = (
    "test_experiment_manifest.py",
    "test_trace_protocol.py",
    "test_trace_compare.py",
    "test_no_hardcoding.py",
    "test_subsystem_candidate_validators.py",
    "test_subsystem_contracts.py",
    "test_subsystem_contract_verification.py",
    "test_subsystem_providers.py",
)


def cmd_test(args: list[str]) -> int:
    for name in _SUITE_STANDALONE:
        code = _run([], script=QA / "tests" / name)
        if code != 0:
            return code
    pytest_argv = ["-q", *[str(QA / "tests" / n) for n in _SUITE_PYTEST]]
    return subprocess.run([PY, "-m", "pytest", *pytest_argv],
                          cwd=ROOT).returncode


_COMMANDS = {
    "extract": cmd_extract,
    "show": cmd_show,
    "spec": cmd_spec,
    "gen": cmd_gen,
    "gen-pair": cmd_gen_pair,
    "facts": cmd_facts,
    "bundle": cmd_bundle,
    "metrics": cmd_metrics,
    "score": cmd_score,
    "reliability": cmd_reliability,
    "compare": cmd_compare,
    "test": cmd_test,
    "qemu": cmd_qemu,
    "v2": cmd_v2,
    "intermediates": cmd_intermediates,
    "log-event": cmd_log_event,
}


def main(argv: list[str] | None = None) -> int:
    for path in (SRC, QA, VERIFICATION):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)
    argv = list(sys.argv[1:] if argv is None else argv)
    print("reharness — libclang + dataflow/taint RIS extraction "
          "(.ris spec language)")
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(_USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    handler = _COMMANDS.get(command)
    if handler is None:
        print(f"unknown command: {command}")
        print(_USAGE)
        return 1
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
