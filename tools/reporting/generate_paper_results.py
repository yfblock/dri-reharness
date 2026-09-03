#!/usr/bin/env python3
"""Generate LaTeX result macros/tables from authoritative experiment JSON."""
from __future__ import annotations

import json
import re
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "research" / "experiments" / "results"
MATRIX = RESULTS / "matrix.json"
QEMU = RESULTS / "qemu.json"
MULTISOURCE = RESULTS / "multisource-matrix.json"
GLUE = RESULTS / "glue-ratio.json"
OUT = ROOT / "research" / "paper" / "generated_results.tex"


def esc(name: str) -> str:
    return name.replace("_", r"\_")


def yn(value) -> str:
    """三态：True=✓，False=✗（适用的检查失败），None=不适用 '--'。
    旧版 False 也渲染 '--'，会把真实失败藏进不适用记号（rerun 评审 minor）。"""
    if value is True:
        return r"\checkmark"
    if value is False:
        return r"$\times$"
    return "--"


def _glue_chart(rows, gagg) -> str:
    """Horizontal 4-way stacked bars: device-core / framework entry /
    glue+other function bodies / file-scope declaration & registration.
    几何使用 0--100 百分比域（与坐标轴刻度一致），行数只出现在数据源。"""
    segs = [
        ("core_pct", "figblue"),
        ("entry_pct", "figorange"),
        ("helper_pct", "gray!45"),
        ("file_scope_pct", "gray!15"),
    ]
    out = [r"\begin{tikzpicture}[x=0.082cm,y=1cm,font=\scriptsize]",
           r"  \draw[line width=0.7pt] (0,0.34) -- (0,0) -- (106,0);",
           r"  \foreach \x/\xl in {0/0,25/25,50/50,75/75,100/100} {",
           r"    \draw[line width=0.5pt] (\x,0) -- (\x,0.12);",
           r"    \node[above, font=\scriptsize] at (\x,0.16) {\xl};",
           r"  }",
           r"  \node[above=8pt, font=\scriptsize] at (50,0.25)",
           r"    {share of non-blank source lines (\%)};"]
    y = 0.0
    for row in rows:
        x = 0.0
        for i, (key, color) in enumerate(segs):
            span = float(row[key])
            if i == len(segs) - 1 and x + span > 100.0:
                # 各段百分比独立舍入，末段钳到 100：条长不超过坐标轴
                span = 100.0 - x
            out.append(
                "  \\path[fill=" + color + ", draw=black, line width=0.3pt] "
                f"({x:.2f},-{y:.2f}) rectangle ({x + span:.2f},-{y + 0.26:.2f});")
            x += span
        out.append(
            f"  \\node[left, font=\\scriptsize] at (-0.18,-{y + 0.13:.2f}) "
            f"{{{esc(row['driver'])}}};")
        out.append(
            f"  \\node[right, font=\\scriptsize] at (101.2,-{y + 0.13:.2f}) "
            f"{{{row['core_pct']:.1f}\\%}};")
        y += 0.36
    out.append(f"  \\draw[line width=0.5pt] (0,-{y:.2f}) -- (106,-{y:.2f});")
    ysep = y + 0.12
    x = 0.0
    for i, (key, color) in enumerate(segs):
        span = float(gagg[key])
        if i == len(segs) - 1 and x + span > 100.0:
            span = 100.0 - x
        out.append(
            "  \\path[fill=" + color + ", draw=black, line width=0.5pt] "
            f"({x:.2f},-{ysep:.2f}) rectangle ({x + span:.2f},-{ysep + 0.32:.2f});")
        x += span
    out.append(
        f"  \\node[left, font=\\scriptsize\\bfseries] at (-0.18,-{ysep + 0.16:.2f}) "
        f"{{\\textbf{{Total ({len(rows)})}}}};")
    out.append(
        f"  \\node[right, font=\\scriptsize\\bfseries] at (101.2,-{ysep + 0.16:.2f}) "
        f"{{{gagg['core_pct']:.1f}\\% device-core}};")
    # 图例 2×2
    legends = [
        ("Device-core lines", "figblue"),
        ("Framework entry bodies", "figorange"),
        ("Glue wrappers \\& other function bodies", "gray!45"),
        ("File-scope declarations \\& registration", "gray!15"),
    ]
    lx, ly0 = 6, ysep + 0.78
    for i, (label, color) in enumerate(legends):
        bx = lx + (i % 2) * 48
        by = ly0 - (i // 2) * 0.45
        out.append(
            "  \\path[fill=" + color + ", draw=black, line width=0.4pt] "
            f"({bx:.2f},-{by:.2f}) rectangle ({bx + 2.4:.2f},-{by + 0.26:.2f});")
        out.append(
            f"  \\node[right, font=\\scriptsize] at ({bx + 2.9:.2f},-{by + 0.13:.2f}) "
            f"{{{label}}};")
    out.append(r"\end{tikzpicture}")
    return "\n".join(out)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> None:
    matrix = json.load(open(MATRIX, encoding="utf-8"))
    qemu = json.load(open(QEMU, encoding="utf-8"))
    multisource = (json.load(open(MULTISOURCE, encoding="utf-8"))
                   if MULTISOURCE.is_file() else
                   {"aggregate": {}, "drivers": []})
    rows = matrix["drivers"]
    agg = matrix["aggregate"]
    addr_total = agg["symbolic"] + agg["fixed"] + agg["computed"]
    mean_ris = statistics.mean(r["readiness"]["ris_quality"] for r in rows)
    ready = {k: sum(r["readiness"].get(k) is True for r in rows) for k in (
        "backend_harness_ready", "backend_bare_metal_ready",
        "backend_linux_ready", "llm_synthesis_ready")}
    compiled = {k: sum(r["backends"][k] for r in rows) for k in (
        "harness_compile", "baremetal_compile", "linux_compile")}
    qemu_experiments = qemu["experiments"]

    def _qemu_row(*names):
        """清单键名历经 gpio-ftgpio010 与 ftgpio010 两种 schema，两者都接受。"""
        for name in names:
            if name in qemu_experiments:
                return qemu_experiments[name]
        raise KeyError(f"qemu.json missing experiments: {names}")

    edu_qemu = _qemu_row("edu")
    ft_qemu = _qemu_row("gpio-ftgpio010", "ftgpio010")

    multi_rows = multisource["drivers"]
    multi_agg = multisource["aggregate"]
    multi_by_driver = {row["driver"]: row for row in multi_rows}
    required_multi = {
        "AspeedVhub": "aspeed-vhub",
        "CSixtySevenXZeroZero": "c67x00",
        "DwcTwo": "dwc2",
    }
    missing_multi = [
        driver for driver in required_multi.values() if driver not in multi_by_driver
    ]
    if missing_multi:
        raise ValueError(
            "Missing required multi-source driver rows: "
            + ", ".join(missing_multi)
        )

    lines = [
        "% Auto-generated by tools/reporting/generate_paper_results.py; "
        "do not edit."
    ]
    macros = {
        "EvalDrivers": len(rows), "EvalOps": agg["ops"],
        "EvalSymbolic": agg["symbolic"], "EvalFixed": agg["fixed"],
        "EvalComputed": agg["computed"], "EvalRMW": agg["rmw"],
        "EvalConditions": agg["conditions"], "EvalRegisters": agg["registers"],
        "EvalUnknown": agg["unknown_value"],
        "EvalSymbolicPct": f"{100 * agg['symbolic'] / addr_total:.1f}\\%",
        "EvalMeanRIS": f"{mean_ris:.3f}",
        "HarnessCompileCount": compiled["harness_compile"],
        "BaremetalCompileCount": compiled["baremetal_compile"],
        "LinuxCompileCount": compiled["linux_compile"],
        "HarnessReadyCount": ready["backend_harness_ready"],
        "BaremetalReadyCount": ready["backend_bare_metal_ready"],
        "LinuxReadyCount": ready["backend_linux_ready"],
        "LLMReadyCount": ready["llm_synthesis_ready"],
        "EduQEMUOracle": esc(edu_qemu.get("value_oracle",
                                          "NOT-RUN" if not edu_qemu.get("probe")
                                          else "probe-only")),
        "FTQEMUOracle": esc("TRACE_MATCH_OK" if ft_qemu.get("trace_oracle")
                            else "TRACE_MATCH_FAIL"),
        "FTQEMUModuleCoverage": ft_qemu.get("module_coverage", "n/a"),
        "FTQEMUCallCoverage": ft_qemu.get("call_coverage", "n/a"),
        "FTQEMUOpCoverage": ft_qemu.get("op_coverage", "n/a"),
        "FTQEMURegisterCoverage": ft_qemu.get("register_coverage", "n/a"),
        "MultiSourceDrivers": multi_agg.get("drivers", 0),
        "MultiSourceTUs": multi_agg.get("translation_units", 0),
        "MultiSourceLines": multi_agg.get("source_lines", 0),
        "MultiSourceOps": multi_agg.get("ops", 0),
        "MultiSourceRMW": multi_agg.get("rmw", 0),
        "MultiSourceRegisters": multi_agg.get("registers", 0),
        "MultiSourceFunctions": sum(
            row.get("functions_analyzed", 0) for row in multi_rows),
        "MultiSourceCallEdges": multi_agg.get("call_edges", 0),
        "MultiSourceCrossTUEdges": multi_agg.get("cross_tu_call_edges", 0),
        "MultiSourceResolvedCrossTUEdges": multi_agg.get(
            "resolved_cross_tu_call_edges", 0),
        "MultiSourcePropagatedEdges": multi_agg.get(
            "propagated_mmio_edges", 0),
        "MultiSourceSourceMMIO": multi_agg.get("source_mmio_primitives", 0),
        "MultiSourceRISMMIO": multi_agg.get("ris_mmio_ops", 0),
    }
    for suffix, driver in required_multi.items():
        row = multi_by_driver[driver]
        macros[f"MultiSource{suffix}SourceMMIO"] = row[
            "source_mmio_primitives"
        ]["total"]
        macros[f"MultiSource{suffix}RISMMIO"] = row["ris_mmio_ops"]
        macros[f"MultiSource{suffix}Ops"] = row["metrics"]["ops"]
        macros[f"MultiSource{suffix}Seconds"] = row.get("seconds", 0)
        macros[f"MultiSource{suffix}UnresolvedCalls"] = row.get(
            "unresolved_internal_calls", 0)

    # QEMU 实验全记录口径：结构化 oracle 实验 vs 探针级实验 vs 未执行 manifest
    oracle_names = {"edu", "ftgpio010", "gpio-ftgpio010"}
    probe_names = sorted(
        k for k in qemu_experiments if k not in oracle_names)
    macros["QEMURecordedExperiments"] = len(qemu_experiments)
    macros["QEMUOracleExperiments"] = len(
        set(oracle_names) & set(qemu_experiments))
    macros["QEMUProbeExperiments"] = len(probe_names)
    macros["QEMUProbeNames"] = ", ".join(esc(n) for n in probe_names)

    def _probe_cov(name):
        return qemu_experiments[name].get(
            "driver_function_coverage", {}).get("percent")

    for macro, name in (("QEMUProbeNicCoverage", "e1000"),
                        ("QEMUProbeUsbCoverage", "usb-storage")):
        if name in qemu_experiments:
            macros[macro] = _probe_cov(name)
    manifest_files = sorted(
        (ROOT / "benchmarks" / "experiments").glob("*.json"))
    unexecuted = [
        p.stem for p in manifest_files
        if p.stem not in qemu_experiments
    ]
    macros["QEMUUnexecutedManifests"] = len(unexecuted)
    macros["QEMUUnexecutedNames"] = ", ".join(esc(n) for n in unexecuted)

    # v2 LangGraph closed-loop LLM experiments (artifacts/experiments-v2-real);
    # provider=source_build 行是真正的 LLM 生成候选 (kernel_tree 行为基线烟测)
    v2_dir = ROOT / "artifacts" / "experiments-v2-real"
    if (v2_dir / "edu" / "experiment.json").is_file():
        src_build = {}
        for p in sorted(v2_dir.glob("*/experiment.json")):
            d = json.load(open(p, encoding="utf-8"))
            if d.get("provider") == "source_build":
                src_build[d["driver"]] = d
        accepted = sorted(n for n, d in src_build.items()
                          if d.get("accepted"))
        macros["ClosedLoopCases"] = len(src_build)
        macros["ClosedLoopAccepted"] = len(accepted)
        macros["ClosedLoopAcceptedNames"] = ", ".join(
            esc(n) for n in accepted) if accepted else "--"
        if "edu" in src_build:
            edu_v2 = src_build["edu"]
            b, c = (edu_v2.get("baseline_coverage", {}),
                    edu_v2.get("candidate_coverage", {}))
            macros["EduRepairRounds"] = edu_v2.get("repair_count", 0)
            macros["EduBaselineFnCov"] = (
                f"{b.get('covered_count')}/{b.get('total')}")
            macros["EduCandidateFnCov"] = (
                f"{c.get('covered_count')}/{c.get('total')}")
        if "ftgpio010" in src_build:
            macros["FtRepairRounds"] = src_build["ftgpio010"].get(
                "repair_count", 0)

    # DesignWare 版本化 .ris 的模块/操作计数（正文 §7.6 引用，避免手写漂移）
    dw_ris_path = ROOT / "examples" / "dw-apb-ssi" / "dw_spi.ris"
    if dw_ris_path.is_file():
        dw_ris = dw_ris_path.read_text(encoding="utf-8")
        macros["DWRISModules"] = len(
            re.findall(r"^  module \w+", dw_ris, re.M))
        macros["DWRISOps"] = len(set(re.findall(r"@op_\d+", dw_ris)))
    dw_formal_path = (ROOT / "examples" / "dw-apb-ssi"
                      / "dw_spi.formal.json")
    if dw_formal_path.is_file():
        dw_formal = json.load(open(dw_formal_path, encoding="utf-8"))
        dw_meta = dw_formal.get("metadata", {})
        dw_acc = dw_meta.get("access_accounting", {})
        if dw_acc:
            macros["DWAccountingSource"] = dw_acc.get("source_accesses", 0)
            macros["DWAccountingEmitted"] = dw_acc.get("emitted", 0)
            macros["DWAccountingUnaccounted"] = dw_acc.get("unaccounted", 0)
            macros["DWAccountingStrict"] = (
                "true" if dw_acc.get("strict_complete") else "false")
        dw_pv = dw_meta.get("path_validation", {})
        if dw_pv:
            macros["DWPathsSatisfiable"] = dw_pv.get("satisfiable", 0)
            macros["DWPathsInfeasible"] = dw_pv.get("infeasible", 0)
            macros["DWPathsUnreachable"] = dw_pv.get(
                "intentionally_unreachable",
                dw_pv.get("unreachable", 0))
        dw_ir = dw_meta.get("ir_layer", dw_meta.get("ir_analysis", {}))
        if dw_ir:
            macros["DWIROps"] = dw_ir.get(
                "total_ir_ops", dw_ir.get("ops", 0))
            macros["DWIRMissingOffsets"] = dw_ir.get(
                "total_missing_from_ast", 0)
            macros["DWIRCoveragePct"] = dw_ir.get("coverage_pct", 100.0)

    # DW 产物行数（摘要/§1 引用；随再生成自动更新）
    ex_dir = ROOT / "examples" / "dw-apb-ssi"
    _dw_files = {
        "DwLinuxLines": ("dw_apb_ssi_linux.c", "dw_apb_ssi_linux.h"),
        "DwBaremetalLines": ("dw_spi_baremetal.c", "dw_spi_baremetal.h"),
        "DwHarnessLines": ("dw_spi_harness.c", "dw_spi_harness.h"),
        "DwRustLines": ("dw_spi_rust_baremetal.rs",),
    }
    for macro, names in _dw_files.items():
        total = sum(_line_count(ex_dir / n) for n in names
                    if (ex_dir / n).is_file())
        if total:
            macros[macro] = total

    # receipt/anchor marker lines in the harness pair (verification
    # scaffolding, not functional code) — keeps §1's size claim honest
    import re as _re
    _rec = 0
    for n in _dw_files["DwHarnessLines"]:
        p = ex_dir / n
        if not p.is_file():
            continue
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if ("REHARNESS_RIS_OP" in l or "REHARNESS_TRANSACTION_OP" in l
                    or _re.search(r"__rh_(op|txn)_\w+:", l)):
                _rec += 1
    if _rec:
        macros["DwReceiptMarkerLines"] = _rec

    # DW 产物行数（摘要/§1 引用；随再生成自动更新）— 源侧固定 1,844 行
    dw_sources = [
        ROOT / "vendor" / "linux" / "drivers" / "spi" / "spi-dw-core.c",
        ROOT / "vendor" / "linux" / "drivers" / "spi" / "spi-dw.h",
        ROOT / "vendor" / "linux" / "drivers" / "spi" / "spi-dw-mmio.c",
    ]
    macros["DwSourceLines"] = sum(_line_count(p) for p in dw_sources)

    # 直译基线（同模型、同验收门、无证据契约；Q/W2）
    direct_path = (ROOT / "research" / "experiments" / "results"
                   / "direct-llm-baseline.json")
    if direct_path.is_file():
        direct = json.load(open(direct_path, encoding="utf-8"))
        rounds = direct.get("rounds", [])
        if rounds:
            first = rounds[0]
            gate = first.get("gate", {})
            macros["DirectLlmSamples"] = len(rounds)
            macros["DirectLlmRejected"] = sum(
                1 for r in rounds if r.get("gate", {}).get("rejected"))
            fails = [r.get("gate", {}).get("first_failing_check")
                     for r in rounds]
            macros["DirectLlmFirstFail"] = esc(
                ", ".join(sorted({f for f in fails if f})) or "none")
            macros["DirectLlmPatternPass"] = sum(
                r.get("checklist_patterns_passed", 0) for r in rounds
                if r.get("checklist_patterns_passed"))
            macros["DirectLlmPatternTotal"] = sum(
                r.get("checklist_patterns_total", 0) for r in rounds
                if r.get("checklist_patterns_total"))
            # matched repair budget (W3): pre-repair vs post-repair verdict
            pre = [r.get("gate_pre_repair", {}).get("first_failing_check")
                   for r in rounds if r.get("gate_pre_repair")]
            if pre:
                macros["DirectLlmPreFirstFail"] = esc(
                    ", ".join(sorted({f for f in pre if f})) or "none")
            macro_n = sum(1 for r in rounds
                          if r.get("compile_repair_rounds") is not None)
            if macro_n:
                macros["DirectLlmRepairRoundsMax"] = max(
                    r.get("compile_repair_rounds") or 0 for r in rounds)
            post = [r.get("gate", {}).get("first_failing_check")
                    for r in rounds]
            macros["DirectLlmPostFirstFail"] = esc(
                ", ".join(sorted({f for f in post if f})) or "none")
            macros["DirectLlmPostRejected"] = sum(
                1 for r in rounds if r.get("gate", {}).get("rejected"))

    # 既有工具对比（edu 设备：QEMU 手写模型 / C2Rust 转译 / reharness）
    ext_path = (ROOT / "research" / "experiments" / "results"
                / "existing-tool-comparison.json")
    if ext_path.is_file():
        ext = json.load(open(ext_path, encoding="utf-8"))
        objs = ext.get("objects", {})
        _ext_map = {
            "ExtEduDriverLines": ("linux_driver", "total"),
            "ExtEduDriverCode": ("linux_driver", "code"),
            "ExtQemuModelLines": ("qemu_model", "total"),
            "ExtQemuModelCode": ("qemu_model", "code"),
            "ExtTranspileLines": ("c2rust", "total"),
            "ExtRhEduLinuxLines": ("reharness_linux", "total"),
            "ExtRhEduHarnessLines": ("reharness_harness", "total"),
            "ExtRhEduBareLines": ("reharness_baremetal", "total"),
            "ExtRhEduRustLines": ("reharness_rust", "total"),
        }
        for macro, (obj, key) in _ext_map.items():
            if objs.get(obj, {}).get(key) is not None:
                macros[macro] = objs[obj][key]
        qmmio = objs.get("qemu_model", {}).get("mmio_offsets", {})
        if qmmio.get("union_count") is not None:
            macros["ExtQemuMmioOffsets"] = qmmio["union_count"]
        drv = ext.get("driver_view", {})
        if drv.get("driver_accessed_count") is not None:
            macros["ExtDriverOffsets"] = drv["driver_accessed_count"]
        uns = objs.get("c2rust", {}).get("unsafe", {})
        if uns.get("unsafe_function_pct") is not None:
            macros["ExtTranspileUnsafePct"] = f'{uns["unsafe_function_pct"]:g}'

    # DW 重复试验（W1：同一候选三阶段门状态，k 次独立试验）
    def _trials_macros(tr: dict, prefix: str) -> None:
        trials = tr.get("trials", [])
        if not trials:
            return
        macros[f"{prefix}TrialsK"] = len(trials)
        _stage_keys = (("First", "first_pass"),
                       ("Post", "post_compile_repair"),
                       ("Final", "post_receipt_repair"))
        for backend in ("harness", "baremetal", "linux", "rust"):
            t_rows = [t["backends"][backend] for t in trials
                      if "checks" in t.get("backends", {}).get(
                          backend, {})]
            if not t_rows:
                continue
            tag = {"harness": "Harn", "baremetal": "Bare",
                   "linux": "Linux", "rust": "Rust"}.get(
                       backend, backend)
            macros[f"{prefix}{tag}TrialsN"] = len(t_rows)
            for stage_name, stage_key in _stage_keys:
                stages = [r["checks"][stage_key] for r in t_rows]
                macros[f"{prefix}{tag}Trials{stage_name}Compile"] = sum(
                    1 for c in stages if c.get("compile"))
                macros[f"{prefix}{tag}Trials{stage_name}Checkbacked"] = sum(
                    1 for c in stages if all(
                        c.get(k) for k in ("compile",
                                           "receipt_accounting",
                                           "ast_leaf_anchors")))
                macros[f"{prefix}{tag}Trials{stage_name}Strict"] = sum(
                    1 for c in stages if all(c.get(k) for k in (
                        "compile", "receipt_accounting",
                        "ast_leaf_anchors", "lowering_plan",
                        "runtime_trace")))
            rr = [r.get("receipt_repair", {}) for r in t_rows]
            macros[f"{prefix}{tag}TrialsReceiptRounds"] = sum(
                x.get("rounds", 0) for x in rr)
            macros[f"{prefix}{tag}TrialsReceiptCalls"] = sum(
                x.get("llm_calls", 0) for x in rr)
        gsec = sorted(r.get("gen_seconds", 0) for r in
                      (b for t in trials
                       for b in t.get("backends", {}).values()
                       if "gen_seconds" in b))
        if gsec:
            macros[f"{prefix}TrialsGenSecondsMedian"] = gsec[
                len(gsec) // 2]

    tr_path = (ROOT / "research" / "experiments" / "results"
               / "dw-repeated-trials.json")
    if tr_path.is_file():
        tr_dw = json.load(open(tr_path, encoding="utf-8"))
        _trials_macros(tr_dw, "Dw")
        # legacy un-prefixed aliases used by the DW paragraph
        if "DwTrialsK" in macros:
            macros["TrialsK"] = macros["DwTrialsK"]
        if "DwTrialsGenSecondsMedian" in macros:
            macros["TrialsGenSecondsMedian"] = macros[
                "DwTrialsGenSecondsMedian"]

    # gpio-cadence 跨驱动重复试验（重审 W1：操作数假设，小驱动）
    cad_path = (ROOT / "research" / "experiments" / "results"
                / "gpio-cadence-repeated-trials.json")
    if cad_path.is_file():
        _trials_macros(json.load(open(cad_path, encoding="utf-8")),
                       "Cadence")
        cad_row = next((r for r in rows
                        if r["driver"] == "gpio-cadence"), None)
        if cad_row:
            macros["CadenceRisOps"] = cad_row["metrics"]["ops"]

    # 验证门变异研究（Q2/W4）
    mut_path = (ROOT / "research" / "experiments" / "results"
                / "dw-gate-mutation-study.json")
    if mut_path.is_file():
        mut = json.load(open(mut_path, encoding="utf-8"))
        rows_m = mut.get("results", [])
        applied = [r for r in rows_m if r.get("applied")]
        if applied:
            macros["GateMutationsApplied"] = len(applied)
            macros["GateMutationsRejected"] = sum(
                1 for r in applied if r.get("rejected"))
        pristine = next((r for r in rows_m
                         if r.get("mutation") == "pristine"), None)
        if pristine:
            macros["GatePristineRejected"] = (
                "true" if pristine.get("rejected") else "false")

    # loop-aware receipt prototype（§7.2 设计路径：被未证循环阻塞的回执
    # 由带锚点溯源的运行时多重性放电）
    law_path = (ROOT / "research" / "experiments" / "results"
                / "dw-loop-aware-receipts.json")
    if law_path.is_file():
        law = json.load(open(law_path, encoding="utf-8"))
        if law.get("loop_blocked_entries"):
            macros["LoopAwareBlocked"] = law["loop_blocked_entries"]
            macros["LoopAwareDischarged"] = len(law.get("discharged", []))
            macros["LoopAwareUnobserved"] = len(law.get("unobserved", []))

    # DW 再生成修复循环轮次（W1：LLM 产物经有界修复后的编译状态）
    rep_path = (ROOT / "research" / "experiments" / "results"
                / "artifact-repair-log.json")
    if rep_path.is_file():
        rep = json.load(open(rep_path, encoding="utf-8"))
        by_backend: dict[str, list[dict]] = {}
        for run in rep.get("runs", []):
            by_backend.setdefault(run.get("backend", "?"), []).append(run)
        for backend, runs in by_backend.items():
            tag = {"harness": "Harn", "baremetal": "Bare",
                   "linux": "Linux", "rust": "Rust"}.get(backend, backend)
            # the log is append-only history: intermediate failed repair
            # attempts precede the final state.  Compile status comes from
            # the NEWEST entry that records an explicit compile_ok (the
            # last LLM compile-repair attempt, or the deterministic
            # normalization entry when that closed the backend).
            compile_runs = [r for r in runs
                            if r.get("compile_ok") is not None]
            last = compile_runs[-1] if compile_runs else None
            if last is not None:
                rounds = last.get("rounds")
                macros[f"Dw{tag}RepairRounds"] = (
                    len(rounds) - 1 if rounds else 0)
                macros[f"Dw{tag}CompileOk"] = (
                    "true" if last.get("compile_ok") else "false")
            lowering_runs = [r for r in runs if r.get("mode") == "lowering"]
            if lowering_runs:
                lrow = lowering_runs[-1]
                macros[f"Dw{tag}LoweringRounds"] = (
                    len(lrow.get("rounds", [])) - 1)
                macros[f"Dw{tag}LoweringComplete"] = (
                    "true" if lrow.get("lowering_complete") else "false")

    # LLM 发射元数据（W5：模型/端点/温度来自 record_llm_run.py 记录）
    meta_path = (ROOT / "research" / "experiments" / "results"
                 / "llm-run-metadata.json")
    if meta_path.is_file():
        meta = json.load(open(meta_path, encoding="utf-8"))
        if meta.get("model"):
            macros["LlmModelId"] = esc(meta["model"])
        if meta.get("endpoint_host"):
            # anonymized for double-blind review; the concrete host stays
            # in the versioned metadata JSON, out of the manuscript
            macros["LlmEndpointHost"] = (
                "a private OpenAI-compatible endpoint")
        if meta.get("temperature") is not None:
            macros["LlmTemperature"] = f'{meta["temperature"]:g}'

    # W3 修复（rerun 评审）：直接 LLM 基线候选的模型来自其自己的
    # 版本化记录（glm-5.2，2026-09-02 采录），与流水线当时的
    # glm-5.3-highspeed 不同 —— 论文如实写两个标识，不写 "same model"
    dmeta_path = (ROOT / "research" / "experiments" / "results"
                  / "direct-llm-baseline.json")
    if dmeta_path.is_file():
        dmeta = json.load(open(dmeta_path, encoding="utf-8"))
        if dmeta.get("model"):
            macros["DirectLlmModelId"] = esc(dmeta["model"])

    # 单驱动提取耗时（matrix.json seconds）与严格就绪名单
    seconds = sorted(r.get("seconds", 0.0) for r in rows)
    if seconds:
        macros["EvalSecondsMin"] = f"{seconds[0]:.1f}"
        macros["EvalSecondsMedian"] = f"{statistics.median(seconds):.1f}"
        macros["EvalSecondsMax"] = f"{seconds[-1]:.1f}"
    ready_names = {k: sorted(
        r["driver"] for r in rows if r["readiness"].get(k) is True)
        for k in ("backend_harness_ready", "backend_bare_metal_ready",
                  "backend_linux_ready")}
    for key, names in ready_names.items():
        macro = "Harness" if "harness" in key else (
            "Baremetal" if "bare_metal" in key else "Linux")
        macros[f"{macro}ReadyDriverList"] = ", ".join(
            esc(n) for n in names) if names else "--"
    multi_unresolved = sum(r.get("unresolved_internal_calls", 0)
                           for r in multi_rows)
    macros["MultiSourceUnresolvedCalls"] = multi_unresolved
    total_edges = multi_agg.get("call_edges", 0)
    if total_edges:
        macros["MultiSourceCallResolutionPct"] = (
            f"{100 * (total_edges - multi_unresolved) / total_edges:.1f}\\%")

    # 胶水/设备核心行占比（逐行 provenance 测量，非人工标注；四分法 v2）
    if GLUE.is_file():
        glue = json.load(open(GLUE, encoding="utf-8"))
        gagg = glue["aggregate"]
        macros["GlueCorePct"] = f"{gagg['core_pct']}\\%"
        macros["GlueEntryPct"] = f"{gagg['entry_pct']}\\%"
        macros["GlueHelperPct"] = f"{gagg['helper_pct']}\\%"
        macros["GlueFileScopePct"] = f"{gagg['file_scope_pct']}\\%"
        macros["GlueGluePct"] = f"{gagg['glue_pct']}\\%"
        macros["GlueCoreLines"] = gagg["device_core_lines"]
        macros["GlueCodeLines"] = gagg["code_lines"]

    # zero-shot 冻结 holdout（若存在版本化结果）
    zeroshot_path = RESULTS / "zero-shot-matrix.json"
    if zeroshot_path.is_file():
        zs = json.load(open(zeroshot_path, encoding="utf-8"))
        zagg = zs.get("aggregate", {})
        zstrict = zagg.get("strict_ready", {})
        macros["ZeroShotCases"] = zagg.get("cases", 0)
        macros["ZeroShotCompile"] = zagg.get("all_backends_compile", 0)
        macros["ZeroShotHarnessStrict"] = zstrict.get("harness", 0)
        macros["ZeroShotBaremetalStrict"] = zstrict.get("baremetal", 0)
        macros["ZeroShotLinuxStrict"] = zstrict.get("linux", 0)
        macros["ZeroShotAllStrict"] = zstrict.get("all_backends", 0)
        macros["ZeroShotHardwareCases"] = zagg.get(
            "cases_with_hardware_interactions", 0)

    # DesignWare 18 项 checklist（逐项判定来自版本化脚本，正文只引用宏）
    dw_checklist_path = RESULTS / "dw-apb-ssi-checklist.json"
    if dw_checklist_path.is_file():
        dw = json.load(open(dw_checklist_path, encoding="utf-8"))
        macros["DWChecklistPassed"] = dw.get("items_passed", 0)
        macros["DWChecklistTotal"] = dw.get("items_total", 0)
        compile_failed = sum(1 for item in dw.get("items", [])
                             if item["name"].startswith("compile_")
                             and not item["pass"])
        rust_df_failed = sum(
            1 for item in dw.get("items", [])
            if item["name"].startswith("dataflow_") and not item["pass"]
            and not item["backends"].get("rust", {"pass": True})["pass"])
        macros["DWChecklistCompileFailed"] = compile_failed
        macros["DWChecklistRustDataflowFailed"] = rust_df_failed
    for key, value in macros.items():
        lines.append(f"\\newcommand{{\\{key}}}{{{value}}}")

    if GLUE.is_file():
        glue = json.load(open(GLUE, encoding="utf-8"))
        grows = sorted(glue["drivers"], key=lambda r: r["core_pct"],
                       reverse=True)
        lines += ["", r"\newcommand{\GlueRatioChart}{%",
                  _glue_chart(grows, glue["aggregate"]), "}"]

    lines += ["", r"\newcommand{\ExtractionResultsTable}{%",
              r"\begin{tabular}{lrrrrrrrrr}", r"\hline",
              r"\textbf{Driver} & \textbf{Ops} & \textbf{Sym} & \textbf{Fixed} & "
              r"\textbf{Comp} & \textbf{NAddr} & \textbf{RMW} & \textbf{Cond} & \textbf{Regs} & \textbf{\%Sym}\\",
              r"\hline"]
    selected = ("gpio-ftgpio010", "virtio_mmio", "gpio-pl061", "gpio-cadence", "edu")
    for name in selected:
        row = next(r for r in rows if r["driver"] == name)
        m = row["metrics"]
        naddr = m["ops"] - m["symbolic"] - m["fixed"] - m["computed"]
        pct = "--" if m["pct_symbolic"] is None else f"{100*m['pct_symbolic']:.1f}\\%"
        lines.append(f"{esc(name)} & {m['ops']} & {m['symbolic']} & {m['fixed']} & "
                     f"{m['computed']} & {naddr} & {m['rmw']} & {m['conditions']} & "
                     f"{m['registers']} & {pct}\\\\")
    lines += [r"\hline",
              f"\\textbf{{Total ({len(rows)})}} & \\textbf{{{agg['ops']}}} & "
              f"\\textbf{{{agg['symbolic']}}} & \\textbf{{{agg['fixed']}}} & "
              f"\\textbf{{{agg['computed']}}} & \\textbf{{{agg['ops'] - addr_total}}} & "
              f"\\textbf{{{agg['rmw']}}} & "
              f"\\textbf{{{agg['conditions']}}} & \\textbf{{{agg['registers']}}} & "
              f"\\textbf{{{100*agg['symbolic']/addr_total:.1f}\\%}}\\\\",
              r"\hline", r"\end{tabular}", r"}", ""]

    lines += [r"\newcommand{\ReadinessResultsTable}{%",
              r"\begin{tabular}{lcccccc}", r"\hline",
              r"\textbf{Driver} & \textbf{RIS} & \textbf{FuncSpec} & \textbf{DevSpec} & "
              r"\textbf{H/B/L compile} & \textbf{Linux ready} & \textbf{Synth.-eligible}\\",
              r"\hline"]
    for name in selected:
        row = next(r for r in rows if r["driver"] == name)
        s, b = row["readiness"], row["backends"]
        comp = "/".join(yn(b[k]) for k in
                        ("harness_compile", "baremetal_compile", "linux_compile"))
        lines.append(f"{esc(name)} & {s['ris_quality']:.3f} & "
                     f"{s['function_spec_quality']:.3f} & {s['device_spec_quality']:.3f} & "
                     f"{comp} & {yn(s['backend_linux_ready'])} & "
                     f"{yn(s['llm_synthesis_ready'])}\\\\")
    lines += [r"\hline", r"\end{tabular}", r"}", ""]

    lines += [r"\newcommand{\MultiSourceResultsTable}{%",
              r"\begin{tabular}{lrrrrrrrrcc}", r"\hline",
              r"\textbf{Driver module} & \textbf{TUs} & \textbf{LoC} & "
              r"\textbf{Funcs} & \textbf{X-TU} & \textbf{Prop} & "
              r"\textbf{Src MMIO} & \textbf{RIS MMIO} & \textbf{Ops} & "
              r"\textbf{H/B/L} & \textbf{Orig. Kbuild}\\", r"\hline"]
    for row in multi_rows:
        m, b = row["metrics"], row["backends"]
        comp = "/".join(yn(b[key]) for key in
                        ("harness_compile", "baremetal_compile", "linux_compile"))
        kbuild = row.get("original_kbuild", {})
        original = (r"\checkmark" if kbuild.get("strict_success") else
                    r"\checkmark$^\dagger$" if kbuild.get("success") else "--")
        lines.append(
            f"{esc(row['driver'])} & {row['source_count']} & {row['source_lines']} & "
            f"{row['functions_analyzed']} & {row.get('cross_tu_call_edges', 0)} & "
            f"{row.get('propagated_mmio_edges', 0)} & "
            f"{row.get('source_mmio_primitives', {}).get('total', 0)} & "
            f"{row.get('ris_mmio_ops', 0)} & {m['ops']} & {comp} & {original}\\\\")
    lines += [r"\hline", r"\end{tabular}", r"}", "",
              "% QEMU evidence: " + json.dumps(qemu_experiments, sort_keys=True)]

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
