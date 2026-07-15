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
    alias_mode: str = "off"                # off | auto | required


@dataclass
class ExtractionResult:
    formal: dict        # FormalRIS (formal language)
    device_spec: object # DeviceSpec (backend-independent semantics)
    facts: object       # FactsSpec (source facts for LLM synthesis)
    warnings: list[str]
    stats: dict


_extraction_cache: dict[tuple, ExtractionResult] = {}


def extract_ris(config: ExtractorConfig) -> ExtractionResult:
    source = os.path.abspath(config.source)
    if config.alias_mode not in {"off", "auto", "required"}:
        raise ValueError(f"invalid alias_mode: {config.alias_mode}")
    # Cache every semantically relevant extraction option.  The previous
    # path-only cache returned stale results when callers changed linux_root,
    # inline depth, framework filtering, or alias-analysis mode.
    try:
        mtime = os.path.getmtime(source)
    except OSError:
        mtime = 0
    cache_key = (
        source, mtime, os.path.abspath(config.linux_root) if config.linux_root else None,
        config.max_inline_depth, config.include_framework,
        tuple(sorted(config.extra_blacklist)), config.alias_mode,
    )
    if cache_key in _extraction_cache:
        return _extraction_cache[cache_key]
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

    # SVF is intentionally opt-in: it is useful for difficult aliases but can
    # take minutes on a single real driver.  Core extraction and the standard
    # test/experiment suite stay deterministic and fast with alias_mode=off.
    svf_aliases: set[str] = set()
    if config.alias_mode != "off":
        try:
            from .alias import find_mmio_aliases
            svf_aliases = find_mmio_aliases(
                source, tu, linux_root=config.linux_root,
                mmio_globals=set(mmio_globals),
                required=config.alias_mode == "required",
            )
            mmio_globals = list(set(mmio_globals) | svf_aliases)
        except Exception as e:
            if config.alias_mode == "required":
                raise
            warnings.append(f"SVF alias analysis skipped: {e}")

    extractions, inlined_names, callback_entries = extract_with_inlining(
        funcs, macros, tu, source_lines, mmio_globals=mmio_globals,
        max_depth=config.max_inline_depth,
        include_framework=config.include_framework,
        extra_blacklist=set(config.extra_blacklist),
    )

    # stats — functions_analyzed / macros_resolved are raw counts; op counts
    # are recomputed from the EMITTED formal modules (excludes inlined helpers)
    stats = {
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "functions_analyzed": len(funcs),
        "macros_resolved": sum(1 for n in macros.names() if macros.offset(n) is not None),
        "svf_aliases": sorted(svf_aliases),
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

    result = ExtractionResult(formal=formal, device_spec=device_spec, facts=facts,
                             warnings=warnings, stats=stats)
    _extraction_cache[cache_key] = result
    return result
