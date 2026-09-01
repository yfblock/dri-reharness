#!/usr/bin/env python3
"""Quantify device-core vs integration line composition across the baseline corpus.

四分类口径（v2，机械可查，全部来自版本化提取器的证据）：
  设备核心行     —— 被 >=1 个已发射 RIS 操作（寄存器/事务/功能状态）的
                   source evidence 引用的非空源行；
  框架入口函数体 —— 绑定到 operations 表 / 生命周期角色的函数（callback_map）
                   内、非设备核心的非空行；
  胶水/辅助及其它函数体 —— 其余函数定义内、非设备核心的非空行
                  （转发包装、未分析函数体等）；
  文件级声明与注册样板 —— 不在任何函数定义内的非空行（include、宏、
                   全局对象、operations 表初始式、module_* 宏）。
空行不计入分母。行级归属是近似：一行同时含守卫与寄存器访问时计入设备核心。

Output: research/experiments/results/glue-ratio.json (schema 2)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import walk_leaf_ops  # noqa: E402
from extractor.tu import parse_translation_unit  # noqa: E402
from extractor.spec import default_bind  # noqa: E402

BASELINE = ROOT / "benchmarks" / "drivers" / "baseline"
OUT = ROOT / "research" / "results" / "glue-ratio.json"
OUT = ROOT / "research" / "experiments" / "results" / "glue-ratio.json"


def _function_extents(source: Path) -> list[tuple[str, int, int]]:
    """Function definitions (name, start_line, end_line) via libclang."""
    import clang.cindex as cx

    tu, _warnings = parse_translation_unit(str(source))
    fns = []
    for cursor in tu.cursor.walk_preorder():
        if cursor.kind != cx.CursorKind.FUNCTION_DECL:
            continue
        if not cursor.is_definition():
            continue
        if cursor.extent.start.line is None:
            continue
        loc_file = cursor.extent.start.file
        if loc_file is not None and Path(loc_file.name).resolve() != source.resolve():
            continue
        fns.append((cursor.spelling,
                    cursor.extent.start.line, cursor.extent.end.line))
    return fns


def _callback_functions(formal_res) -> set[str]:
    """Functions bound to operations tables / lifecycle roles (fail-open)."""
    try:
        from backends.rules.linux.source_parse import callback_map
        from extractor.spec import default_bind
        bind = default_bind(formal_res.device_spec, "linux")
        mapping = callback_map(bind, formal_res.facts, formal_res.device_spec)
        return set(mapping.keys())
    except Exception as exc:  # noqa: BLE001 — 证据缺失时降级而非失败
        print(f"  [warn] callback_map unavailable: {exc}", file=sys.stderr)
        return set()


def survey_driver(source: Path) -> dict:
    res = extract_ris(ExtractorConfig(source=str(source)))
    formal = res.formal

    core_lines: set[int] = set()
    op_count = 0
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = next(iter(op.values()))
            ev = body.get("evidence") or {}
            src = ev.get("source")
            line = ev.get("line")
            if src is None or line is None:
                continue
            if Path(src).resolve() != source.resolve():
                continue  # 头文件等外部 provenance 不计入本文件
            core_lines.add(int(line))
            op_count += 1

    callbacks = _callback_functions(res)
    functions = _function_extents(source)

    text = source.read_text(encoding="utf-8", errors="replace")
    raw_lines = text.splitlines()
    total_lines = len(raw_lines)
    code_lines = {i + 1 for i, l in enumerate(raw_lines) if l.strip()}

    def enclosing(line: int) -> str | None:
        for name, start, end in functions:
            if start <= line <= end:
                return name
        return None

    counts = {"device_core": 0, "framework_entry": 0,
              "glue_helper": 0, "file_scope": 0}
    for line in code_lines:
        if line in core_lines:
            counts["device_core"] += 1
            continue
        fn = enclosing(line)
        if fn is None:
            counts["file_scope"] += 1
        elif fn in callbacks:
            counts["framework_entry"] += 1
        else:
            counts["glue_helper"] += 1

    code_n = len(code_lines)
    name = source.stem
    return {
        "driver": name,
        "source_lines": total_lines,
        "blank_lines": total_lines - code_n,
        "code_lines": code_n,
        "device_core_lines": counts["device_core"],
        "framework_entry_lines": counts["framework_entry"],
        "glue_helper_lines": counts["glue_helper"],
        "file_scope_lines": counts["file_scope"],
        "core_pct": round(100 * counts["device_core"] / code_n, 1)
        if code_n else 0.0,
        "entry_pct": round(100 * counts["framework_entry"] / code_n, 1)
        if code_n else 0.0,
        "helper_pct": round(100 * counts["glue_helper"] / code_n, 1)
        if code_n else 0.0,
        "file_scope_pct": round(100 * counts["file_scope"] / code_n, 1)
        if code_n else 0.0,
        "callbacks": len(callbacks),
        "functions": len(functions),
        "ops": op_count,
    }


def main() -> int:
    sources = sorted(p for p in BASELINE.glob("*.c"))
    rows = []
    for source in sources:
        row = survey_driver(source)
        rows.append(row)
        print(f"{row['driver']:<22} code={row['code_lines']:>5} "
              f"core={row['device_core_lines']:>4} "
              f"entry={row['framework_entry_lines']:>4} "
              f"glue={row['glue_helper_lines']:>4} "
              f"file={row['file_scope_lines']:>4} "
              f"callbacks={row['callbacks']:>2}")

    def total(key: str) -> int:
        return sum(r[key] for r in rows)

    code_total = total("code_lines")

    def pct(key: str) -> float:
        return round(100 * total(key) / code_total, 1) if code_total else 0.0

    aggregate = {
        "drivers": len(rows),
        "code_lines": code_total,
        "device_core_lines": total("device_core_lines"),
        "framework_entry_lines": total("framework_entry_lines"),
        "glue_helper_lines": total("glue_helper_lines"),
        "file_scope_lines": total("file_scope_lines"),
        "core_pct": pct("device_core_lines"),
        "entry_pct": pct("framework_entry_lines"),
        "helper_pct": pct("glue_helper_lines"),
        "file_scope_pct": pct("file_scope_lines"),
        # 兼容 v1 字段：非设备核心的统称
        "glue_lines": code_total - total("device_core_lines"),
        "glue_pct": round(100 * (code_total - total("device_core_lines"))
                          / code_total, 1) if code_total else 0.0,
    }
    report = {
        "schema": 2,
        "definition": "device-core line = non-blank line referenced by >=1 "
                      "emitted RIS operation; framework-entry = non-core lines "
                      "in functions bound to operations tables / lifecycle "
                      "roles; glue/other = non-core lines in remaining function "
                      "bodies; file-scope = lines outside function definitions "
                      "(includes, macros, globals, registration tables). "
                      "Blank lines excluded. Line-level attribution is "
                      "approximate.",
        "generated_by": "qa/verification/glue_ratio_survey.py",
        "drivers": rows,
        "aggregate": aggregate,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"\naggregate: core {aggregate['core_pct']}% / "
          f"entry {aggregate['entry_pct']}% / helper {aggregate['helper_pct']}% / "
          f"file-scope {aggregate['file_scope_pct']}%  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
