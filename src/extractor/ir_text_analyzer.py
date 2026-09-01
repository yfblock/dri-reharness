"""Pure-text LLVM IR analysis: MMIO detection + SSA chains + debug line mapping.

Operates directly on .ll text (no llvmlite dependency) for reliability:
  - Function boundary: define ... @name(...) ... {
  - MMIO: asm sideeffect "movl" or load/store volatile
  - Source line: !dbg → DILocation → inlinedAt chain → driver source line
  - Address: GEP instruction → constant offset
  - Value: SSA chain (load → or 0x100 → add 1)
"""
from __future__ import annotations

import re
from typing import Any

_FN_PATTERN = re.compile(r"define\s+(?:\w+\s+)+@(\w+)\(")

# ── debug location parsing ─────────────────────────────────────────────


def parse_debug_locations(ir_text: str) -> dict[int, dict]:
    """Parse all !DILocation metadata (handles distinct keyword)."""
    locations = {}
    for line in ir_text.splitlines():
        if "DILocation" not in line or "=" not in line:
            continue
        id_m = re.search(r"!(\d+)\s*=", line)
        if not id_m:
            continue
        meta_id = int(id_m.group(1))
        line_m = re.search(r"line:\s*(\d+)", line)
        col_m = re.search(r"column:\s*(\d+)", line)
        inl_m = re.search(r"inlinedAt:\s*!(\d+)", line)
        scope_m = re.search(r"scope:\s*!(\d+)", line)
        if line_m:
            locations[meta_id] = {
                "line": int(line_m.group(1)),
                "col": int(col_m.group(1)) if col_m else None,
                "inlined_at": int(inl_m.group(1)) if inl_m else None,
                "scope": int(scope_m.group(1)) if scope_m else None,
            }
    return locations


def parse_scope_tables(ir_text: str) -> dict:
    """Subprogram/lexical-block tables for scope-aware name disambiguation.

    After inlining one SSA temporary can carry several source variables
    (callee's and caller's).  Each ``DILocalVariable`` declares the scope it
    belongs to; resolving that scope through lexical blocks to its
    ``DISubprogram`` tells us which function frame the variable lives in —
    the frame the MMIO statement itself belongs to (outermost inlinedAt)
    picks the right name instead of an arbitrary one.
    """
    subprograms: dict[int, str] = {}
    subprogram_file: dict[int, int] = {}
    lexical: dict[int, int] = {}
    var_scopes: dict[int, int] = {}
    define_subprogram: dict[str, int] = {}
    for line in ir_text.splitlines():
        m = re.search(
            r'!(\d+)\s*=\s*(?:distinct\s+)?!DISubprogram\(name:\s*"([^"]+)"'
            r'[^)]*?file:\s*!(\d+)',
            line)
        if m:
            subprograms[int(m.group(1))] = m.group(2)
            subprogram_file[int(m.group(1))] = int(m.group(3))
            continue
        m = re.search(
            r"!(\d+)\s*=\s*(?:distinct\s+)?!DILexicalBlock(?:Base)?\("
            r"[^)]*?scope:\s*!(\d+)", line)
        if m:
            lexical[int(m.group(1))] = int(m.group(2))
            continue
        m = re.search(
            r"!(\d+)\s*=\s*!DILocalVariable\([^)]*?scope:\s*!(\d+)", line)
        if m:
            var_scopes[int(m.group(1))] = int(m.group(2))
    fn_m = None
    for line in ir_text.splitlines():
        fn_m = _FN_PATTERN.search(line)
        if fn_m:
            dbg_m = re.search(r"!dbg\s+!(\d+)\s*\{", line)
            if dbg_m:
                define_subprogram[fn_m.group(1)] = int(dbg_m.group(1))
            continue

    def subprogram_of(scope_id: int | None, _depth: int = 0) -> int | None:
        while scope_id is not None and _depth < 8:
            if scope_id in subprograms:
                return scope_id
            scope_id = lexical.get(scope_id)
            _depth += 1
        return None

    return {"subprograms": subprograms, "subprogram_of": subprogram_of,
            "subprogram_file": subprogram_file,
            "var_scopes": var_scopes, "define_subprogram": define_subprogram}


def resolve_source_line(dbg_id: int, locations: dict) -> tuple[int, int] | None:
    """Follow inlinedAt chain to the driver source (not the header)."""
    loc = locations.get(dbg_id)
    if not loc:
        return None
    depth = 0
    while loc.get("inlined_at") and depth < 5:
        loc = locations.get(loc["inlined_at"], {})
        depth += 1
    return (loc.get("line"), loc.get("col"))


def parse_local_variable_names(
        ir_text: str) -> tuple[dict[int, str], dict[str, dict[str, list[tuple[str, int | None]]]]]:
    """Parse debug-info variable bindings: SSA value → [(name, subprogram)].

    Pass 1: ``!N = !DILocalVariable(name: "x", scope: !S, ...)`` → names.
    Pass 2: ``llvm.dbg.value(metadata TYPE %V, metadata !N)`` inside a
    function body → {function: {ssa: [(name, var_subprogram)]}}.

    The subprogram each variable belongs to is kept per binding so the
    consumer can disambiguate inlined callees vs the enclosing frame
    instead of dropping every multi-binding SSA.
    """
    scopes = parse_scope_tables(ir_text)
    var_subprogram = {
        meta: scopes["subprogram_of"](sid)
        for meta, sid in scopes["var_scopes"].items()}
    meta_names: dict[int, str] = {}
    var_re = re.compile(r'!(\d+)\s*=\s*!DILocalVariable\(name:\s*"([^"]+)"')
    for line in ir_text.splitlines():
        m = var_re.search(line)
        if m:
            meta_names[int(m.group(1))] = m.group(2)

    dbg_value_re = re.compile(
        r'@llvm\.dbg\.(?:value|declare)\(metadata\s+[^,]+\s+(%\w+),\s+metadata\s+!(\d+)')
    bindings: dict[str, dict[str, list[tuple[str, int | None]]]] = {}
    current_fn = None
    for line in ir_text.splitlines():
        fn_m = _FN_PATTERN.search(line)
        if fn_m:
            current_fn = fn_m.group(1)
            continue
        if line.rstrip() == "}" and current_fn:
            current_fn = None
            continue
        if not current_fn:
            continue
        m = dbg_value_re.search(line)
        if m:
            meta = int(m.group(2))
            name = meta_names.get(meta)
            if name:
                entry = (name, var_subprogram.get(meta))
                bucket = bindings.setdefault(current_fn, {}).setdefault(
                    m.group(1), [])
                if entry not in bucket:
                    bucket.append(entry)
    return meta_names, bindings


def disambiguate_name(bindings: list[tuple[str, int | None]],
                      target_subprogram: int | None,
                      ) -> tuple[str | None, list[str]]:
    """Pick the variable of the frame the statement belongs to.

    Preference order: bindings whose variable lives in ``target_subprogram``
    → any globally-unambiguous name → none.  Returns (name, candidates) so
    callers can record what was ambiguous instead of hiding it.
    """
    if not bindings:
        return None, []
    if target_subprogram is not None:
        in_frame = [name for name, sp in bindings if sp == target_subprogram]
        if len(set(in_frame)) == 1:
            return in_frame[0], sorted({n for n, _ in bindings})
    distinct = {name for name, _ in bindings}
    if len(distinct) == 1:
        return bindings[0][0], []
    return None, sorted(distinct)

# ── GEP offset extraction ──────────────────────────────────────────────


def gep_offset(text: str) -> int | None:
    """Extract byte offset from a getelementptr instruction."""
    m = re.search(
        r"getelementptr\s+(?:inbounds\s+)?(i\d+),\s*ptr\s+\S+,\s*i64\s+(\d+)",
        text)
    if m:
        idx = int(m.group(2))
        size = {"i8": 1, "i16": 2, "i32": 4, "i64": 8}.get(m.group(1), 4)
        return idx * size
    return None


# ── SSA value chain ────────────────────────────────────────────────────


def trace_value_chain(ssa: str, ssa_map: dict, depth: int = 0) -> list[str]:
    """Build a readable SSA chain: ['load', 'or 0x100', 'add 1']."""
    if depth > 8:
        return ["..."]
    chain = []
    current = ssa
    visited = set()
    while current in ssa_map and current not in visited:
        visited.add(current)
        text = ssa_map[current]
        op_m = re.search(r"=\s*(\w+)", text)
        if not op_m:
            break
        opcode = op_m.group(1)
        if opcode == "load":
            chain.append("MMIO_READ")
            break
        elif opcode in ("or", "and", "add", "sub", "shl", "lshr", "xor", "mul"):
            const_m = re.search(r",\s*(-?\d+)", text)
            c = f" 0x{int(const_m.group(1)) & 0xFFFFFFFF:x}" if const_m else ""
            chain.append(f"{opcode}{c}")
            next_m = re.search(r"\w+\s+(%\w+)", text)
            current = next_m.group(1) if next_m else None
            if not current:
                break
        elif opcode in ("trunc", "zext", "sext"):
            next_m = re.search(r"\w+\s+(%\w+)", text)
            current = next_m.group(1) if next_m else None
            if not current:
                break
        else:
            chain.append(opcode)
            break
    return chain


# ── main analyzer ──────────────────────────────────────────────────────




def analyze_ir_text(ir_text: str) -> list[dict[str, Any]]:
    """Analyze LLVM IR text: extract MMIO ops with source lines and value chains."""
    locations = parse_debug_locations(ir_text)
    _, ssa_bindings = parse_local_variable_names(ir_text)
    scope_tables = parse_scope_tables(ir_text)
    facts: list[dict] = []
    lines = ir_text.splitlines()

    def driver_frame_chain(dbg_id: int | None,
                           fn: str | None) -> list[int]:
        """Subprograms of the statement's frames, innermost first, keeping
        only frames from the driver source file (header inline frames such
        as readl/writel locals are not driver variables)."""
        chain: list[int] = []
        loc = locations.get(dbg_id) if dbg_id is not None else None
        depth = 0
        while loc is not None and depth < 6:
            sp = scope_tables["subprogram_of"](loc.get("scope"))
            if sp is not None and sp not in chain:
                chain.append(sp)
            nxt = locations.get(loc.get("inlined_at")) if loc.get("inlined_at") else None
            loc = nxt
            depth += 1
        if fn is not None:
            own = scope_tables["define_subprogram"].get(fn)
            if own is not None and own not in chain:
                chain.append(own)
        own_file = None
        if fn is not None:
            own = scope_tables["define_subprogram"].get(fn)
            own_file = scope_tables["subprogram_file"].get(own)
        if own_file is not None:
            chain = [sp for sp in chain
                     if scope_tables["subprogram_file"].get(sp) == own_file]
        return chain

    current_fn = None
    ssa_map: dict[str, str] = {}

    for line in lines:
        fn_m = _FN_PATTERN.search(line)
        if fn_m:
            current_fn = fn_m.group(1)
            ssa_map = {}
            continue
        if line.rstrip() == "}" and current_fn:
            current_fn = None
            continue
        if not current_fn:
            continue

        text = line.strip()

        # Register SSA definitions
        ssa_m = re.match(r"(%\w+)\s*=\s*(.*)", text)
        if ssa_m:
            ssa_map[ssa_m.group(1)] = text

        # Detect MMIO
        is_read = (("asm sideeffect" in text and '"movl $1,$0"' in text)
                   or "load volatile" in text)
        is_write = (("asm sideeffect" in text and '"movl $0,$1"' in text)
                    or "store volatile" in text)
        if not (is_read or is_write):
            continue

        # Source line via !dbg → DILocation → inlinedAt
        line_num = col_num = None
        dbg_m = re.search(r"!dbg\s+!(\d+)", text)
        if dbg_m:
            result = resolve_source_line(int(dbg_m.group(1)), locations)
            if result:
                line_num, col_num = result

        # Address offset: walk the SSA definition chain accumulating GEPs.
        #   GEP(base, i64 K)  → constant byte offset
        #   GEP(base, i64 %v) → computed (variable)
        #   no GEP (ioremap call / plain load) → base + 0
        addr_offset = addr_base = None
        ptr_m = (re.search(r"ptr\s+(?:nonnull\s+)?elementtype\(\w+\)\s+(%\w+)", text)
                 or re.search(r",\s*ptr\s+(%\w+)", text))
        if ptr_m:
            addr_ssa = ptr_m.group(1)
            addr_offset = 0
            addr_base = addr_ssa
            seen = set()
            current = addr_ssa
            while current and current not in seen:
                seen.add(current)
                defn = ssa_map.get(current)
                if not defn:
                    break
                if "getelementptr" not in defn:
                    break  # ioremap call or plain load: offset stays as-is
                gep_type_m = re.search(
                    r"getelementptr\s+(?:inbounds\s+)?(\S+?),\s*ptr", defn)
                gep_type = (gep_type_m.group(1) if gep_type_m else "").lstrip("%")
                if not re.fullmatch(r"i\d+", gep_type):
                    break  # struct/class GEP: driver-private field, not MMIO
                off = gep_offset(defn)
                if off is None:
                    # variable index — record the base, mark computed
                    addr_offset = None
                    base_m = re.search(r"ptr\s+(%\w+)", defn)
                    addr_base = base_m.group(1) if base_m else current
                    break
                addr_offset = (addr_offset or 0) + off
                base_m = re.search(r"ptr\s+(%\w+)", defn)
                current = base_m.group(1) if base_m else None
                addr_base = current or addr_base

        # Value (Write only)
        value_const = None
        value_chain = []
        if is_write:
            val_m = re.search(r"(?:i32|i64)\s+(\S+),\s*ptr", text)
            if val_m:
                val = val_m.group(1)
                if val.lstrip("-").isdigit():
                    value_const = int(val) & 0xFFFFFFFF
                    value_chain = [f"const 0x{value_const:x}"]
                else:
                    value_chain = trace_value_chain(val, ssa_map)

        fn_binds = ssa_bindings.get(current_fn, {})
        frame_chain = driver_frame_chain(
            int(dbg_m.group(1)) if dbg_m else None, current_fn)

        def _resolve(ssa: str | None) -> tuple[str | None, list[str]]:
            """Frame-chain disambiguation: innermost driver-source frame
            with a unique binding wins; header locals never do."""
            if not ssa or ssa not in fn_binds:
                return None, []
            binds = fn_binds[ssa]
            for frame in frame_chain:
                in_frame = [n for n, sp in binds if sp == frame]
                if len(set(in_frame)) == 1 and in_frame[0]:
                    if re.fullmatch(r"[A-Za-z_]\w*", in_frame[0]):
                        return in_frame[0], sorted({n for n, _ in binds})
            distinct = {n for n, _ in binds}
            if len(distinct) == 1:
                name = binds[0][0]
                if re.fullmatch(r"[A-Za-z_]\w*", name):
                    return name, []
            return None, sorted(distinct)

        base_name, base_cands = _resolve(addr_base)
        name_candidates: list[str] = list(base_cands)
        result_name = None
        if is_read:
            # the SSA receiving the loaded value maps to the source variable
            res_m = re.match(r"(%\w+)\s*=\s*", text)
            if res_m:
                result_name, rc = _resolve(res_m.group(1))
                if rc:
                    name_candidates = sorted(set(name_candidates) | set(rc))
        if value_chain and not value_chain[0].startswith("const "):
            # name the SSA origin of the written value, when debug info has it
            origin = re.search(r"(?:i32|i64)\s+(%\w+),\s*ptr", text)
            origin_name, oc = _resolve(origin.group(1)) if origin else (None, [])
            if origin_name:
                value_chain = [f"var {origin_name}", *value_chain]
            if oc:
                name_candidates = sorted(set(name_candidates) | set(oc))

        facts.append({
            "op": "Read" if is_read else "Write",
            "line": line_num, "col": col_num,
            "function": current_fn,
            "addr_offset": addr_offset,
            "addr_base": addr_base,
            "addr_base_name": base_name,
            "result_name": result_name,
            "name_candidates": name_candidates or None,
            "value_const": value_const,
            "value_chain": value_chain,
            "kind": "asm" if "asm" in text else "volatile",
            "ir_line": text[:120],
        })

    return facts
