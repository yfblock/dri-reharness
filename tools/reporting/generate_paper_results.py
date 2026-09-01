#!/usr/bin/env python3
"""Generate LaTeX result macros/tables from authoritative experiment JSON."""
from __future__ import annotations

import json
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


def yn(value: bool) -> str:
    return r"\checkmark" if value else "--"


def _glue_chart(rows, gagg) -> str:
    """Horizontal 4-way stacked bars: device-core / framework entry /
    glue+other function bodies / file-scope declaration & registration."""
    segs = [
        ("device_core_lines", "figblue", None),
        ("framework_entry_lines", "figorange", None),
        ("glue_helper_lines", "gray!45", None),
        ("file_scope_lines", "gray!15", None),
    ]
    out = [r"\begin{tikzpicture}[x=0.082cm,y=1cm,font=\scriptsize]",
           r"  \draw[line width=0.7pt] (0,0.34) -- (0,0) -- (106,0);",
           r"  \foreach \x/\xl in {0/0,25/25,50/50,75/75,100/100} {",
           r"    \draw[line width=0.5pt] (\x,0) -- (\x,0.12);",
           r"    \node[above, font=\scriptsize] at (\x,0.16) {\xl};",
           r"  }",
           r"  \node[above=8pt, font=\scriptsize] at (50,0.25)",
           r"    {Composition of non-blank source lines (\%)};"]
    y = 0.0
    for row in rows:
        x = 0.0
        for key, color, _ in segs:
            span = row[key]
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
    for key, color, _ in segs:
        span = gagg[key]
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
        ("Glue wrappers & other function bodies", "gray!45"),
        ("File-scope declarations & registration", "gray!15"),
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
    for key, value in macros.items():
        lines.append(f"\\newcommand{{\\{key}}}{{{value}}}")

    if GLUE.is_file():
        glue = json.load(open(GLUE, encoding="utf-8"))
        grows = sorted(glue["drivers"], key=lambda r: r["core_pct"],
                       reverse=True)
        lines += ["", r"\newcommand{\GlueRatioChart}{%",
                  _glue_chart(grows, glue["aggregate"]), "}"]

    lines += ["", r"\newcommand{\ExtractionResultsTable}{%",
              r"\begin{tabular}{lrrrrrrrr}", r"\hline",
              r"\textbf{Driver} & \textbf{Ops} & \textbf{Sym} & \textbf{Fixed} & "
              r"\textbf{Comp} & \textbf{RMW} & \textbf{Cond} & \textbf{Regs} & \textbf{\%Sym}\\",
              r"\hline"]
    selected = ("gpio-ftgpio010", "virtio_mmio", "gpio-pl061", "gpio-cadence", "edu")
    for name in selected:
        row = next(r for r in rows if r["driver"] == name)
        m = row["metrics"]
        pct = "--" if m["pct_symbolic"] is None else f"{100*m['pct_symbolic']:.1f}\\%"
        lines.append(f"{esc(name)} & {m['ops']} & {m['symbolic']} & {m['fixed']} & "
                     f"{m['computed']} & {m['rmw']} & {m['conditions']} & "
                     f"{m['registers']} & {pct}\\\\")
    lines += [r"\hline",
              f"\\textbf{{Total ({len(rows)})}} & \\textbf{{{agg['ops']}}} & "
              f"\\textbf{{{agg['symbolic']}}} & \\textbf{{{agg['fixed']}}} & "
              f"\\textbf{{{agg['computed']}}} & \\textbf{{{agg['rmw']}}} & "
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
