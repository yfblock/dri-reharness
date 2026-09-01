"""IR-primary RIS extraction: LLVM IR is the primary analysis, AST supplements.

Architecture:
    PRIMARY:  C → clang -S -emit-llvm -g → IR text analysis
              (MMIO detection, SSA value chains, GEP offsets, debug line mapping)
              + macro reverse-lookup (offset → register name)

    SUPPLEMENT: libclang AST — OPTIONAL, opt-in only
              (function roles, DeviceSpec, facts, switch/case enumeration)

The IR path is fully independent of libclang: kernel flags come from the
kernel build directory, not from an AST pass. This avoids libclang
RecursionError on deeply nested kernel headers.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .extractor import ExtractorConfig
from .ir_text_analyzer import analyze_ir_text


# ── kernel flags (no AST extraction) ──────────────────────────────────


def _get_kernel_flags(source: Path) -> list[str]:
    """Compile flags shared with the AST path (tu.effective_compile_args).

    Includes the Kbuild context when present and the vendor/linux fallback
    with -D_Static_assert neutralization otherwise.  A baseline driver that
    is byte-identical to a vendor/linux source borrows that file's Kbuild
    context (same bytes → same compilation, debug lines stay valid).
    No libclang involved.
    """
    from .tu import effective_compile_args
    args, context = effective_compile_args(str(source))
    if context is None or not getattr(context, "arguments", None):
        twin = _vendor_twin(source)
        if twin is not None:
            try:
                args, context = effective_compile_args(str(twin))
            except Exception:
                pass
    return args


_VENDOR_TWIN_CACHE: dict[str, Path | None] = {}


def _vendor_twin(source: Path) -> Path | None:
    """A byte-identical same-basename source under vendor/linux, if any."""
    key = str(source)
    if key in _VENDOR_TWIN_CACHE:
        return _VENDOR_TWIN_CACHE[key]
    repo = Path(__file__).resolve().parents[2]
    vendor = repo / "vendor" / "linux" / "drivers"
    twin: Path | None = None
    if vendor.is_dir():
        digest = source.stat().st_size
        import hashlib
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        for candidate in vendor.rglob(source.name):
            try:
                if (candidate.stat().st_size == digest
                        and hashlib.sha256(candidate.read_bytes()).hexdigest() == sha):
                    twin = candidate
                    break
            except OSError:
                continue
    _VENDOR_TWIN_CACHE[key] = twin
    return twin


def _compile_ir(source: Path, kernel_args: list[str]) -> str:
    """Compile C to LLVM IR with kernel build flags.

    The .ll lands in the driver's intermediate directory (reviewable,
    regenerable) instead of polluting the benchmark corpus.
    """
    from .intermediates import intermediate_dir
    ll_path = intermediate_dir(source) / "01-ir.ll"
    cmd = ["clang-18", "-S", "-emit-llvm", "-g", "-O1", "-c", "-w",
           *kernel_args, str(source), "-o", str(ll_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not ll_path.is_file():
        raise RuntimeError(f"IR compilation failed: {proc.stderr[:300]}")
    return ll_path.read_text()


# ── macro reverse-lookup ───────────────────────────────────────────────


def _driver_local_macro_names(source: Path) -> set[str]:
    """Macro names #defined in the driver's own source (not kernel headers).

    Scans the .c file plus same-directory .h files it includes — register
    macros (IO_ID, IRQ_STATUS, ...) are conventionally driver-local.
    """
    import re as _re
    names: set[str] = set()
    files = [source] + sorted(source.parent.glob("*.h"))
    define_re = _re.compile(r'^\s*#\s*define\s+(\w+)', _re.M)
    for f in files:
        try:
            names.update(define_re.findall(f.read_text(errors="replace")))
        except OSError:
            continue
    return names


def _build_macro_index(source: Path) -> dict[int, list[str]]:
    """constant → driver-local macro-name reverse lookup."""
    from .ir_analysis import export_macro_table, build_reverse_index
    table = export_macro_table(source)
    local = _driver_local_macro_names(source)
    # Keep only driver-local names; kernel-header macros are naming noise.
    local_table = {k: v for k, v in table.items() if k in local}
    idx = build_reverse_index(local_table) if local_table else {}
    return idx


# ── RIS core from IR facts ────────────────────────────────────────────


def _addr(f: dict, reg_name: str | None) -> dict:
    offset = f.get("addr_offset")
    if reg_name:
        return {"Fixed": {"base": "mmio", "offset": offset, "name": reg_name}}
    if offset is not None:
        return {"Fixed": {"base": "mmio", "offset": offset}}
    # Runtime-variable offset: honest Computed form, structurally lowerable
    # (the generated accessor takes the offset as a function parameter).
    return {"Computed": {"BinOp": {"op": "+", "left": {"Var": "mmio"},
                                   "right": {"Var": "runtime_offset"}}}}


def _value(f: dict) -> Any:
    """Displayable RIS value; SSA chain evidence lives in op evidence."""
    if f.get("value_const") is not None:
        return {"Const": f["value_const"]}
    return {"Top": None}


def _intent(fn_name: str, op: str, reg_name: str | None) -> str:
    """Semantic purpose derived from the function role and register name."""
    fn = fn_name.lower()
    reg = (reg_name or "").lower()
    if "probe" in fn or "init" in fn:
        return "device identification (probe)"
    if "irq" in fn or "interrupt" in fn:
        if op == "Write" and ("clr" in reg or "ack" in reg):
            return "acknowledge interrupt"
        if op == "Read":
            return "poll interrupt status"
        return "configure interrupt"
    if "mask" in fn and op == "Write":
        return "mask/unmask interrupt"
    if "unmask" in fn and op == "Write":
        return "unmask interrupt"
    if "set_config" in fn or "config" in fn:
        return "apply device configuration"
    if op == "Read" and ("status" in reg or "stat" in reg):
        return "read status register"
    if op == "Write" and "clr" in reg:
        return "clear register event"
    if op == "Read":
        return "read register value"
    return "write register value"


def _build_ris_core(ir_facts: list[dict], macro_idx: dict,
                    driver_name: str, source: Path) -> dict[str, Any]:
    """Primary MMIO facts from IR: register_map + per-function ops."""
    by_fn: dict[str, list[dict]] = {}
    for f in ir_facts:
        by_fn.setdefault(f["function"], []).append(f)

    reg_map: dict[int, dict] = {}
    for f in sorted(ir_facts, key=lambda x: x.get("addr_offset") or 0):
        offset = f.get("addr_offset")
        if offset is None or offset in reg_map:
            continue
        names = macro_idx.get(offset, [])
        reg_map[offset] = {
            "name": names[0] if names else f"REG_{offset:X}",
            "offset": offset, "width": "B4", "description": "",
            "has_macro": bool(names),
        }

    modules = []
    for fn_name, fn_facts in by_fn.items():
        ops = []
        seen_sites: set[tuple] = set()
        for i, f in enumerate(fn_facts):
            # Loop unrolling / peeling emits several physical instructions
            # for ONE source access (same function/line/offset/kind) — they
            # are a single logical operation.
            site = (fn_name, f.get("line"), f.get("addr_offset"), f["op"])
            if f.get("line") and site in seen_sites:
                continue
            seen_sites.add(site)
            op_id = f"op_{i + 1}"
            offset = f.get("addr_offset")
            reg_names = macro_idx.get(offset, []) if offset is not None else []
            reg_name = reg_names[0] if reg_names else None
            src_abs = str(Path(source).resolve())
            line_no = f.get("line") or 0
            evidence = {
                "origin": "llvm_ir",
                "site_id": f"{src_abs}:{fn_name}:{line_no}:{f.get('col') or 0}",
                "source": src_abs,
                "line": f.get("line"),
                "column": f.get("col") or 0,
                "function": fn_name,
                "callee": f.get("kind", "asm"),
                "ast_kind": "LLVM_IR",
                "access_kind": f["op"],
                "access_domain": "mmio",
                "method": f.get("kind", "asm"),
                "reliability": "Exact",
            }
            if f.get("value_chain"):
                evidence["value_chain"] = list(f["value_chain"])
            if f.get("addr_base"):
                evidence["addr_ssa"] = f["addr_base"]
            if f.get("addr_base_name"):
                evidence["addr_base_name"] = f["addr_base_name"]
            intent = _intent(fn_name, f["op"], reg_name)
            addr_prec = ("fixed" if f.get("addr_offset") is not None
                         else "computed")
            if f["op"] == "Read":
                # debug-info source variable name when unambiguous,
                # synthetic val_op_N otherwise
                var_name = f.get("result_name") or f"val_{op_id}"
                ops.append({"Read": {
                    "op_id": op_id, "addr": _addr(f, reg_name),
                    "var": var_name, "width": "B4",
                    "reliability": "Exact", "address_precision": addr_prec,
                    "value_precision": "exact",
                    "intent": intent, "evidence": evidence}})
            else:
                ops.append({"Write": {
                    "op_id": op_id, "addr": _addr(f, reg_name),
                    "value": _value(f), "width": "B4",
                    "reliability": "Exact", "address_precision": addr_prec,
                    "value_precision": ("exact" if f.get("value_const") is not None
                                        else "unknown"),
                    "intent": intent, "evidence": evidence}})
        if ops:
            modules.append({"name": fn_name, "ops": ops,
                            "source": [str(source)]})

    return {
        "register_map": sorted(reg_map.values(), key=lambda r: r["offset"]),
        "modules": modules,
    }


# ── AST supplement merge ──────────────────────────────────────────────


def _ast_mmio_ops(ast_module: dict) -> list[dict]:
    """AST leaf MMIO ops (Read/Write/RMW) with their body dicts."""
    out = []
    for op in ast_module.get("ops", []):
        for kind in ("Read", "Write", "ReadModifyWrite"):
            if kind in op:
                out.append({"kind": kind, "body": op[kind], "op": op})
                break
    return out


def _ast_line(body: dict) -> int | None:
    line = (body.get("evidence") or {}).get("line")
    return line if isinstance(line, int) else None


def _join_function_ops(fn: str, ir_ops: list[dict],
                       ast_mod: dict | None,
                       macro_idx: dict | None = None) -> list[dict]:
    """Enrich the AST op tree in place with IR-verified addresses.

    The AST module ops form a tree (Cond/Seq/Loop wrapping Read/Write/RMW
    leaves with values, transforms and guards).  IR analysis of the compiled
    driver verifies every physical access; matching leaves get their
    ``Symbolic`` address upgraded to ``Fixed`` (GEP offset + macro name)
    and IR provenance added — the tree structure is preserved.

    Unmatched IR ops are accesses the AST dataflow missed → appended as
    pure-IR ops.  Unmatched AST leaves are dead code or library accesses
    → flagged ``supplementary`` (origin preserved).
    """
    consumed: set[int] = set()
    name_to_offset: dict[str, int] = {}
    for off, names in (macro_idx or {}).items():
        for name in names:
            name_to_offset.setdefault(name, off)

    def ir_offset(idx: int) -> int | None:
        body = next(iter(ir_ops[idx].values()))
        return ((body.get("addr") or {}).get("Fixed") or {}).get("offset")

    def match_ir(kind: str, line: int | None,
                 sym_reg: str | None) -> int | None:
        offset_hint = name_to_offset.get(sym_reg) if sym_reg else None
        # pass 1: same kind + same source line
        if line is not None:
            for idx in range(len(ir_ops)):
                if idx in consumed or kind not in ir_ops[idx]:
                    continue
                body = ir_ops[idx][kind]
                if (body.get("evidence") or {}).get("line") == line:
                    return idx
        # pass 2: same kind + same register offset (debug lines can be 0)
        if offset_hint is not None:
            for idx in range(len(ir_ops)):
                if idx in consumed or kind not in ir_ops[idx]:
                    continue
                if ir_offset(idx) == offset_hint:
                    return idx
        return None

    def enrich(kind: str, body: dict) -> dict:
        line = (body.get("evidence") or {}).get("line")
        sym_reg = (body.get("addr") or {}).get("Symbolic", {}).get("register")
        idx = match_ir(kind, line, sym_reg)
        consumed_extra: set[int] = set()
        if idx is None and kind == "ReadModifyWrite":
            # RMW: consume the IR Read + Write pair of the same register
            w = match_ir("Write", line, sym_reg)
            r = match_ir("Read", None, sym_reg)
            if w is not None:
                idx = w
                if r is not None and r != w:
                    consumed_extra.add(r)
        if idx is None:
            ev = body.setdefault("evidence", {})
            ev["supplementary"] = True
            return body
        ir_body = next(iter(ir_ops[idx].values()))
        ir_addr = ir_body.get("addr") or {}
        ast_addr = body.get("addr") or {}
        if "Fixed" in ir_addr:
            # Only a GEP-verified Fixed offset is an upgrade.  IR's Computed
            # form is a generic encoding (mmio + runtime_offset) whose
            # structural lowerability is an artifact, not evidence about the
            # source expression — the AST address always wins there.
            body["addr"] = ir_addr
        ev = body.setdefault("evidence", {})
        ev["ir_verified"] = True
        ev["ir_line"] = (ir_body.get("evidence") or {}).get("line")
        ev["ir_method"] = (ir_body.get("evidence") or {}).get("method")
        consumed.add(idx)
        consumed.update(consumed_extra)
        return body

    def walk(ops: list[dict]) -> list[dict]:
        out: list[dict] = []
        for op in ops:
            if "Cond" in op:
                node = dict(op["Cond"])
                node["then_ops"] = walk(node.get("then_ops") or [])
                node["else_ops"] = walk(node.get("else_ops") or [])
                out.append({"Cond": node})
            elif "Seq" in op:
                node = dict(op["Seq"])
                node["ops"] = walk(node.get("ops") or [])
                out.append({"Seq": node})
            elif "Loop" in op:
                node = dict(op["Loop"])
                node["guard_ops"] = walk(node.get("guard_ops") or [])
                node["body"] = walk(node.get("body") or [])
                out.append({"Loop": node})
            elif "Read" in op:
                out.append({"Read": enrich("Read", dict(op["Read"]))})
            elif "Write" in op:
                out.append({"Write": enrich("Write", dict(op["Write"]))})
            elif "ReadModifyWrite" in op:
                out.append({"ReadModifyWrite":
                            enrich("ReadModifyWrite", dict(op["ReadModifyWrite"]))})
            else:
                out.append(op)
        return out

    joined = walk(ast_mod.get("ops", [])) if ast_mod else []
    # accesses the AST dataflow missed → pure IR ops, in IR order
    for idx, ir_op in enumerate(ir_ops):
        if idx not in consumed:
            joined.append(ir_op)
    return joined




def _mark_supplementary(ops: list[dict]) -> None:
    """Flag dead-code ops without erasing their analytical origin."""
    for op in ops:
        for key, node in op.items():
            if key in ("Cond", "Seq", "Loop"):
                for sub_key in ("then_ops", "else_ops", "ops", "guard_ops", "body"):
                    if node.get(sub_key):
                        _mark_supplementary(node[sub_key])
                break
            if isinstance(node, dict):
                ev = node.setdefault("evidence", {})
                ev["supplementary"] = True
            break

def _merge(ir_core: dict, ast_formal: dict | None, driver_name: str,
           source: Path, macro_idx: dict | None = None) -> dict[str, Any]:
    """IR MMIO facts merged into the AST formal skeleton.

    IR (primary): register_map, Fixed addresses, physical completeness.
    AST (supplement): values, RMW transforms, guards, DeviceSpec, facts,
                    dead-code ops (marked supplementary), metadata.
    """
    if not ast_formal:
        return {
            "driver": driver_name, "version": "2",
            "source": str(source), **ir_core,
            "metadata": {"extraction_method": "llvm_ir_primary"},
            "transaction_map": {},
        }

    merged = dict(ast_formal)  # driver/version/metadata/transaction_map
    merged["extraction_method"] = "llvm_ir_primary"

    # register_map: IR offsets are GEP-verified — they win; AST fills gaps.
    ir_regs = {r["offset"]: r for r in ir_core["register_map"]}
    ast_regs = ast_formal.get("register_map", [])
    combined: dict[int, dict] = dict(ir_regs)
    for r in ast_regs:
        if r.get("offset") not in combined:
            combined[r.get("offset")] = r
    merged["register_map"] = sorted(combined.values(),
                                    key=lambda r: r.get("offset") or 0)

    # modules: line-join IR ops with AST ops per function.
    ir_by_fn = {m["name"]: m for m in ir_core["modules"]}
    ast_by_fn = {m.get("name"): m for m in ast_formal.get("modules", [])}
    out_modules: list[dict] = []
    for fn, ir_mod in ir_by_fn.items():
        ops = _join_function_ops(fn, ir_mod["ops"], ast_by_fn.get(fn),
                                macro_idx)
        out_modules.append({"name": fn, "ops": ops,
                            "source": ir_mod.get("source")})
    for fn, ast_mod in ast_by_fn.items():
        if fn in ir_by_fn:
            continue
        _mark_supplementary(ast_mod.get("ops", []))
        out_modules.append(ast_mod)
    merged["modules"] = out_modules
    return merged


# ── result container ──────────────────────────────────────────────────


class IRPrimaryResult:
    """IR-primary extraction result (interface-compatible with AST result)."""

    def __init__(self, formal, facts, device_spec, stats, warnings,
                 source, ir_text, ir_facts, macro_index, ast_result):
        self.formal = formal
        self.facts = facts
        self.device_spec = device_spec
        self.stats = stats
        self.warnings = warnings
        self.source = source
        self.ir_text = ir_text
        self.ir_facts = ir_facts
        self.macro_index = macro_index
        self.ast_result = ast_result


# ── main entry point ──────────────────────────────────────────────────


def extract_ris_ir_primary(config: ExtractorConfig) -> IRPrimaryResult:
    """IR-primary extraction: LLVM IR analysis, AST as supplement.

    IR (primary):   MMIO ops, GEP offsets, macro names, source lines.
    AST (supplement): DeviceSpec, facts, roles, ValueBind, dead code,
                    metadata, transaction_map. Disabled via
                    config.skip_ast_supplement when downstream only
                    needs the IR facts.
    """
    source = Path(config.source)
    driver_name = config.driver_name or source.stem

    # Step 1: compile → IR (kernel flags shared with the AST path)
    kernel_args = _get_kernel_flags(source)
    ir_text = _compile_ir(source, kernel_args)

    # Step 2: IR text analysis (primary facts)
    ir_facts = analyze_ir_text(ir_text)

    # Step 3: macro reverse-lookup (driver-local names)
    macro_idx = _build_macro_index(source)

    # Step 4: IR core (register_map + per-function MMIO ops)
    ir_core = _build_ris_core(ir_facts, macro_idx, driver_name, source)
    try:
        from .intermediates import intermediate_dir, write_json
        out = intermediate_dir(source)
        write_json(out / "02-macros.json",
                   {"reverse_index": {str(k): v for k, v in macro_idx.items()}})
        write_json(out / "03-ir-facts.json", ir_facts)
    except Exception:
        pass

    # Step 5: AST supplement (DeviceSpec/facts/roles — pipeline needs them).
    # Fail-closed configuration errors (alias_mode/compile_context_mode
    # "required", e.g. SVF tools missing) must propagate; only lenient
    # modes degrade to IR-only when the supplement fails.
    ast_result = None
    ir_only_warning = None
    strict = (getattr(config, "alias_mode", "auto") == "required"
              or getattr(config, "compile_context_mode", "auto") == "required")
    if not getattr(config, "skip_ast_supplement", False):
        try:
            from .extractor import _extract_ris_ast
            ast_result = _extract_ris_ast(config)
        except RecursionError:
            ast_result = None
            ir_only_warning = ("AST supplement hit recursion limits; "
                               "IR facts only")
        except Exception as exc:
            if strict:
                raise
            ast_result = None
            ir_only_warning = f"AST supplement failed ({exc}); IR facts only"

    merged = _merge(ir_core,
                    getattr(ast_result, "formal", None),
                    driver_name, source, macro_idx)

    warnings = list(getattr(ast_result, "warnings", []) or [])
    if ast_result is None and not getattr(config, "skip_ast_supplement", False):
        warnings.append(ir_only_warning)

    fixed_ops = sum(1 for m in merged.get("modules", [])
                    for op in m.get("ops", [])
                    if next(iter(op.values()), {}).get("addr", {})
                    .get("Fixed", {}).get("offset") is not None)

    stats = {
        **(ast_result.stats if ast_result else {}),
        "extraction_method": "llvm_ir_primary",
        "ir_mmio_ops": len(ir_facts),
        "ir_fixed_offset_ops": fixed_ops,
        "ir_named_registers": sum(
            1 for r in merged.get("register_map", []) if r.get("has_macro")),
        "ir_lines": len(ir_text.splitlines()),
        "ir_kernel_flags": len(kernel_args),
        "ir_ast_supplement": ast_result is not None,
        "ir_enriched": True,
    }

    result = IRPrimaryResult(
        formal=merged,
        facts=getattr(ast_result, "facts", None) if ast_result else _EmptyFacts(),
        device_spec=(getattr(ast_result, "device_spec", None) if ast_result
                     else _ir_only_spec(ir_core)),
        stats=stats,
        warnings=warnings,
        source=str(source), ir_text=ir_text, ir_facts=ir_facts,
        macro_index=macro_idx, ast_result=ast_result)
    _dump_intermediates(source, driver_name, result)
    return result


def _dump_intermediates(source: Path, driver_name: str,
                        result: "IRPrimaryResult") -> None:
    """Persist every stage of the extraction chain for review/editing.

    Best-effort: a dump failure never breaks extraction.
    """
    try:
        from .intermediates import intermediate_dir, write_json
        out = intermediate_dir(source)
        ast_formal = getattr(result.ast_result, "formal", None)
        if ast_formal is not None:
            write_json(out / "04-ast-formal.json", ast_formal)
        write_json(out / "05-merged-ris.json", result.formal)
        write_json(out / "06-stats.json", result.stats)
    except Exception:
        pass




def _ir_only_spec(ir_core: dict) -> "_EmptySpec":
    """Empty DeviceSpec carrying the IR-derived register table.

    The readiness gate reads ``device_spec.registers``; IR-only extraction
    does produce a fully named register_map, so the hardware-model gate
    should measure what is genuinely absent (roles, facts bundles) rather
    than a wiring gap.
    """
    spec = _EmptySpec()

    class _Reg:
        def __init__(self, entry: dict) -> None:
            self.name = entry.get("name")
            self.offset = entry.get("offset")

    spec.registers = [_Reg(r) for r in ir_core.get("register_map", [])]
    return spec


class _EmptyFacts:
    """Display/score-compatible empty facts bundle (AST supplement off)."""

    def __init__(self) -> None:
        self.resources = []
        self.constants = {}
        self.structs = []
        self.includes = []
        self.callbacks = []
        self.error_paths = []
        self.helper_calls = []

    def display(self) -> str:
        return "(no AST facts: IR-primary only)\n"

    def facts(self):
        return []

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0


class _EmptySpec:
    """Display/score-compatible empty DeviceSpec (AST supplement off)."""

    def __init__(self) -> None:
        self.name = "ir-only"
        self.functions = []
        self.resources = []
        self.state = []
        self.registers = []
        self.callbacks = []

    def display(self) -> str:
        return "(no DeviceSpec: IR-primary only)\n"

    def bind(self, *a, **k):
        return {}
