"""Top-level orchestrator: source → formal RIS (.ris spec language).

parse TU → collect macros → find target functions → dataflow extraction
(with wrapper inlining) → intent annotation → build FormalRIS.
"""
from __future__ import annotations
import os
import datetime
import json
from collections import Counter
from dataclasses import dataclass, field

from . import tu as tu_mod
from . import macros as macros_mod
from .ast_model import target_functions, target_mmio_globals
from .call_graph import extract_with_inlining
from .formalize import build_formal_ris
from .dataflow import Op


@dataclass
class ExtractorConfig:
    source: str | list[str]
    output: str = "output/ris.ris"        # formal-language text (primary, only output)
    include_framework: bool = False
    extra_blacklist: list[str] = field(default_factory=list)
    linux_root: str | None = None
    max_inline_depth: int = 3
    alias_mode: str = "off"                # off | auto | required
    driver_name: str | None = None          # required only for direct multi-source API use


@dataclass
class ExtractionResult:
    formal: dict        # FormalRIS (formal language)
    device_spec: object # DeviceSpec (backend-independent semantics)
    facts: object       # FactsSpec (source facts for LLM synthesis)
    warnings: list[str]
    stats: dict


_extraction_cache: dict[tuple, ExtractionResult] = {}


def _resolve_sources(config: ExtractorConfig) -> tuple[list[str], str, str]:
    """Resolve a source file/list or a versioned multi-source JSON manifest.

    Manifest source paths are relative to the manifest directory.  The
    descriptor path is retained as DeviceSpec/Facts provenance while each RIS
    module keeps its actual C source location.
    """
    raw = config.source
    if isinstance(raw, str) and raw.endswith(".json"):
        manifest = os.path.abspath(raw)
        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
            raise ValueError(f"multi-source manifest lacks sources[]: {manifest}")
        base = os.path.dirname(manifest)
        sources = [os.path.abspath(os.path.join(base, str(p)))
                   for p in data["sources"]]
        name = config.driver_name or data.get("name")
        if not name:
            raise ValueError(f"multi-source manifest lacks name: {manifest}")
        return sources, str(name), manifest
    if isinstance(raw, list):
        sources = [os.path.abspath(p) for p in raw]
        if not sources:
            raise ValueError("at least one C source is required")
        name = config.driver_name or os.path.splitext(os.path.basename(sources[0]))[0]
        return sources, name, ";".join(sources)
    source = os.path.abspath(raw)
    name = config.driver_name or os.path.splitext(os.path.basename(source))[0]
    return [source], name, source


def _merge_facts(parts, source: str, warnings: list[str]):
    from .spec import FactsSpec, ResourceFact

    includes: list[str] = []
    structs = []
    struct_names: set[str] = set()
    constants: dict = {}
    callbacks: dict = {}
    resources = []
    resource_keys: set[tuple] = set()
    error_paths: set[str] = set()
    helper_calls: set[str] = set()
    source_snippets: dict = {}
    for facts in parts:
        for inc in facts.includes:
            if inc not in includes:
                includes.append(inc)
        for struct in facts.structs:
            if struct.name not in struct_names:
                structs.append(struct)
                struct_names.add(struct.name)
        for name, value in facts.constants.items():
            if name in constants and constants[name] != value:
                warnings.append(f"multi-source constant conflict: {name}")
                continue
            constants.setdefault(name, value)
        for field, fn in facts.callbacks.items():
            if field in callbacks and callbacks[field] != fn:
                warnings.append(f"multi-source callback conflict: {field}")
                continue
            callbacks.setdefault(field, fn)
        for resource in facts.resources:
            key = (resource.acquisition, resource.binds_to)
            if key in resource_keys:
                continue
            resource_keys.add(key)
            resources.append(ResourceFact(
                f"resource{len(resources)}", resource.acquisition, resource.binds_to))
        error_paths.update(facts.error_paths)
        helper_calls.update(facts.helper_calls)
        for name, snippets in facts.source_snippets.items():
            source_snippets.setdefault(name, [])
            for snippet in snippets:
                if snippet not in source_snippets[name]:
                    source_snippets[name].append(snippet)
    return FactsSpec(
        source=source, includes=includes, structs=structs, constants=constants,
        callbacks=callbacks, resources=resources,
        error_paths=sorted(error_paths), helper_calls=sorted(helper_calls),
        source_snippets=source_snippets,
    )


def _extract_multi(config: ExtractorConfig, sources: list[str],
                   driver_name: str, descriptor: str) -> ExtractionResult:
    from .call_graph import extract_multi_with_inlining
    from .formal import emitted_stats
    from .spec_infer import (infer_function_specs, infer_device_spec,
                             infer_facts, parse_callback_bindings)

    warnings: list[str] = []
    units: list[dict] = []
    combined_macros = macros_mod.MacroTable()
    all_svf_aliases: set[str] = set()

    for source in sources:
        if not source.endswith(".c"):
            raise ValueError(f"multi-source entry is not a C file: {source}")
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            source_text = fh.read()
        tu, diag = tu_mod.parse_translation_unit(source, config.linux_root)
        warnings.extend(diag)
        macros = macros_mod.build(tu, source, source_text)
        conflicts = combined_macros.merge(macros)
        warnings.extend(f"multi-source macro conflict: {name}" for name in conflicts)
        funcs = target_functions(tu, source)
        mmio_globals = target_mmio_globals(tu, source)
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
                warnings.append(f"SVF alias analysis skipped for {source}: {e}")
        all_svf_aliases |= svf_aliases
        units.append({
            "source": source, "source_text": source_text,
            "source_lines": source_text.splitlines(), "tu": tu,
            "macros": macros, "funcs": funcs, "mmio_globals": mmio_globals,
        })

    funcs = [f for unit in units for f in unit["funcs"]]
    duplicates = sorted(name for name, count in
                        Counter(f.name for f in funcs).items() if count > 1)
    if duplicates:
        raise ValueError("duplicate function names across translation units: "
                         + ", ".join(duplicates))
    if not funcs:
        warnings.append("No function definitions found in target files")

    extractions, inlined_names, callback_entries = extract_multi_with_inlining(
        units, max_depth=config.max_inline_depth,
        include_framework=config.include_framework,
        extra_blacklist=set(config.extra_blacklist),
    )
    stats = {
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "functions_analyzed": len(funcs),
        "macros_resolved": sum(1 for n in combined_macros.names()
                               if combined_macros.offset(n) is not None),
        "svf_aliases": sorted(all_svf_aliases),
        "translation_units": len(units),
        "source_files": list(sources),
        "source_lines": sum(len(unit["source_lines"]) for unit in units),
    }
    formal = build_formal_ris(
        driver_name, descriptor, funcs, extractions, combined_macros,
        stats, inlined_names)
    formal["metadata"]["sources"] = list(sources)
    stats.update(emitted_stats(formal))

    combined_text = "\n\n".join(
        f"/* translation unit: {unit['source']} */\n{unit['source_text']}"
        for unit in units)
    fn_specs, cb_bindings = infer_function_specs(
        formal, funcs, combined_text, descriptor, callback_entries)
    device_spec = infer_device_spec(
        formal, funcs, fn_specs, descriptor, combined_text)
    register_names = {r["name"] for r in formal.get("register_map", [])}
    fact_parts = []
    all_names = {f.name for f in funcs}
    for unit in units:
        local_names = {f.name for f in unit["funcs"]}
        local_bindings = parse_callback_bindings(unit["source_text"], all_names)
        local_bindings = {name: info for name, info in local_bindings.items()
                          if name in local_names}
        fact_parts.append(infer_facts(
            unit["source_text"], unit["source"], unit["tu"], unit["macros"],
            local_bindings, register_names, formal=formal,
            driver_name=driver_name))
    facts = _merge_facts(fact_parts, descriptor, warnings)
    # Combined parsing can discover cross-TU registrations that no individual
    # source text contains in full; retain those authoritative bindings.
    for fname, info in cb_bindings.items():
        facts.callbacks.setdefault(f"{info['table']}.{info['field']}", fname)

    return ExtractionResult(
        formal=formal, device_spec=device_spec, facts=facts,
        warnings=warnings, stats=stats)


def extract_ris(config: ExtractorConfig) -> ExtractionResult:
    if config.alias_mode not in {"off", "auto", "required"}:
        raise ValueError(f"invalid alias_mode: {config.alias_mode}")
    sources, driver_name, descriptor = _resolve_sources(config)
    if len(sources) > 1:
        source_state = []
        for source in sources:
            try:
                source_state.append((source, os.path.getmtime(source)))
            except OSError:
                source_state.append((source, 0))
        try:
            descriptor_mtime = os.path.getmtime(descriptor)
        except OSError:
            descriptor_mtime = 0
        cache_key = (
            "multi", tuple(source_state), descriptor, descriptor_mtime,
            driver_name,
            os.path.abspath(config.linux_root) if config.linux_root else None,
            config.max_inline_depth, config.include_framework,
            tuple(sorted(config.extra_blacklist)), config.alias_mode,
        )
        if cache_key not in _extraction_cache:
            _extraction_cache[cache_key] = _extract_multi(
                config, sources, driver_name, descriptor)
        return _extraction_cache[cache_key]

    source = sources[0]
    # Cache every semantically relevant extraction option.  The previous
    # path-only cache returned stale results when callers changed linux_root,
    # inline depth, framework filtering, or alias-analysis mode.
    try:
        mtime = os.path.getmtime(source)
    except OSError:
        mtime = 0
    cache_key = (
        source, mtime, driver_name,
        os.path.abspath(config.linux_root) if config.linux_root else None,
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
