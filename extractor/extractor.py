"""Top-level orchestrator: source → formal RIS (.ris spec language).

parse TU → collect macros → find target functions → dataflow extraction
(with wrapper inlining) → intent annotation → build FormalRIS.
"""
from __future__ import annotations
import os
import datetime
from dataclasses import dataclass, field

from . import tu as tu_mod
from . import macros as macros_mod
from .ast_model import target_functions, target_mmio_globals
from .call_graph import extract_with_inlining
from .formalize import build_formal_ris
from .dataflow import Op


@dataclass
class ExtractorConfig:
    source: str
    output: str = "output/ris.ris"        # formal-language text (primary, only output)
    include_framework: bool = False
    extra_blacklist: list[str] = field(default_factory=list)
    linux_root: str | None = None
    max_inline_depth: int = 3


@dataclass
class ExtractionResult:
    formal: dict        # FormalRIS (formal language)
    device_spec: object # DeviceSpec (backend-independent semantics)
    facts: object       # FactsSpec (source facts for LLM synthesis)
    warnings: list[str]
    stats: dict


def extract_ris(config: ExtractorConfig) -> ExtractionResult:
    source = os.path.abspath(config.source)
    with open(source, "r", encoding="utf-8", errors="replace") as fh:
        source_text = fh.read()
    source_lines = source_text.splitlines()

    warnings: list[str] = []
    tu, diag = tu_mod.parse_translation_unit(source, config.linux_root)
    warnings.extend(diag)

    # macros (TU + regex fallback)
    macros = macros_mod.build(tu, source, source_text)

    # target-file function definitions
    funcs = target_functions(tu, source)
    if not funcs:
        warnings.append("No function definitions found in target file")

    mmio_globals = target_mmio_globals(tu, source)

    # SVF-backed alias analysis: find local variables that alias MMIO globals
    # (e.g., `p = mmio_global` → p is also a BasePtr). Falls back gracefully
    # if SVF binary is unavailable or IR generation fails.
    try:
        from .alias import find_mmio_aliases
        svf_aliases = find_mmio_aliases(source, tu, linux_root=config.linux_root)
        if svf_aliases:
            mmio_globals = list(set(mmio_globals) | svf_aliases)
            warnings.append(f"SVF alias analysis: {svf_aliases} treated as MMIO bases")
    except Exception as e:
        warnings.append(f"SVF alias analysis skipped: {e}")

    extractions, inlined_names, callback_entries = extract_with_inlining(
        funcs, macros, tu, source_lines, mmio_globals=mmio_globals,
        max_depth=config.max_inline_depth
    )

    # stats — functions_analyzed / macros_resolved are raw counts; op counts
    # are recomputed from the EMITTED formal modules (excludes inlined helpers)
    stats = {
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "functions_analyzed": len(funcs),
        "macros_resolved": sum(1 for n in macros.names() if macros.offset(n) is not None),
    }

    driver_name = os.path.splitext(os.path.basename(source))[0]
    formal = build_formal_ris(driver_name, source, funcs, extractions, macros,
                              stats, inlined_names)

    # recompute op stats from the emitted .ris (consistent with output)
    from .formal import emitted_stats
    stats.update(emitted_stats(formal))

    # infer backend-independent FunctionSpec / DeviceSpec (plan M3/M4) + facts (M9)
    from .spec_infer import infer_function_specs, infer_device_spec, infer_facts
    fn_specs, cb_bindings = infer_function_specs(formal, funcs, source_text, source,
                                                 callback_entries)
    device_spec = infer_device_spec(formal, funcs, fn_specs, source, source_text)
    register_names = {r["name"] for r in formal.get("register_map", [])}
    facts = infer_facts(source_text, source, tu, macros, cb_bindings,
                        register_names, formal=formal, driver_name=driver_name)

    return ExtractionResult(formal=formal, device_spec=device_spec, facts=facts,
                            warnings=warnings, stats=stats)
