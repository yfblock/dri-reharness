"""SDHCI ops subsystem summary inference."""
from __future__ import annotations

from ._common import *


def _sdhci_initializer_blocks(text: str):
    pattern = re.compile(
        r"\bstruct\s+sdhci_ops\s+([A-Za-z_]\w*)\s*=\s*\{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield match.group(1), text[start + 1:index], match.start()
                    break


def _sdhci_evidence(source: str, text: str, offset: int, field: str,
                    callee: str, kind: str, width: int) -> dict:
    line = text.count("\n", 0, offset) + 1
    return {
        "site_id": f"{source}:{line}:0:{offset}:sdhci_ops.{field}",
        "source": source,
        "line": line,
        "column": 0,
        "offset": offset,
        "function": f"sdhci_ops.{field}",
        "symbol": callee,
        "callee": callee,
        "ast_kind": "INIT_LIST_EXPR",
        "access_kind": kind,
        "width_bytes": width,
        "origin": "subsystem_summary",
        "access_domain": "mmio",
        "subsystem_summary": "sdhci_ops",
        "effective_callee": callee,
        "library_callback": f"sdhci_ops.{field}",
        "summary_contract": "linux.sdhci_ops",
    }


_SDHCI_ACCESSOR_FIELDS = {
    "read_l": ("Read", 4), "read_w": ("Read", 2), "read_b": ("Read", 1),
    "write_l": ("Write", 4), "write_w": ("Write", 2),
    "write_b": ("Write", 1),
}

_SDHCI_CORE_DELEGATES = {
    "sdhci_set_clock", "sdhci_set_bus_width", "sdhci_reset",
    "sdhci_set_uhs_signaling",
}


def _sdhci_contract_evidence(evidence: dict, field: str, callee: str,
                             *, byte_order: str = "native",
                             access_domain: str = "mmio") -> dict:
    out = copy.deepcopy(evidence)
    out.update({
        "origin": "subsystem_summary",
        "subsystem_summary": "sdhci_accessor",
        "effective_callee": callee,
        "library_callback": f"sdhci_ops.{field}",
        "summary_contract": "linux.sdhci_ops",
        "access_domain": access_domain,
    })
    if byte_order != "native":
        out["byte_order"] = byte_order
    return out


def _sdhci_branch(op: Op, condition: str) -> Op:
    item = copy.deepcopy(op)
    item.condition = condition
    item.cond_stack = list(op.cond_stack) + [condition]
    item.control_stack = list(op.control_stack) + [{
        "kind": "cond", "guard": condition, "branch": "contract",
    }]
    return item


def _sdhci_public_accessor_ops(field: str, callee: str, evidence: dict,
                               *, source_op: Op | None = None,
                               macros=None) -> list[Op]:
    """Materialize stable SDHCI accessor semantics from public headers."""
    contract = _SDHCI_ACCESSOR_FIELDS.get(field)
    if contract is None:
        return []
    kind, width = contract
    base = "host->ioaddr"
    reg = "reg"
    value = "value"
    template = source_op or Op(
        kind=kind, addr=addr_indirect(base, 0, reg), width=width,
        value=value if kind == "Write" else None, var="value" if kind == "Read" else None,
        evidence=evidence)
    if source_op is not None:
        base = addr_base_of(source_op.addr) or base
        if "Indirect" in source_op.addr:
            reg = source_op.addr["Indirect"].get("expr") or reg
        elif source_op.reg_name:
            reg = source_op.reg_name
        value = source_op.value or value

    be32bs = callee.startswith("sdhci_be32bs_")
    byte_order = ("big" if be32bs and field != "read_b" else "native")
    mmio_evidence = _sdhci_contract_evidence(
        evidence, field, callee, byte_order=byte_order)
    state_evidence = _sdhci_contract_evidence(
        evidence, field, callee, access_domain="source_state")

    def dynamic(expr: str) -> dict:
        return addr_indirect(base, 0, expr)

    def symbolic(name: str) -> tuple[dict, str | None]:
        offset = macros.offset(name) if macros is not None else None
        if offset is None:
            return dynamic(name), None
        return addr_offset(base, offset), name

    if not be32bs:
        op = copy.deepcopy(template)
        op.addr = dynamic(reg)
        op.width = width
        op.evidence = mmio_evidence
        if kind == "Read":
            op.kind, op.var, op.value = "Read", "value", None
            returned = Op(
                kind="Return", addr=addr_fixed(0), width=0, value="value",
                evidence=state_evidence, source_loc=op.source_loc,
                line=op.line)
            return [op, returned]
        op.kind, op.value = "Write", value
        return [op]

    if field == "read_l":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(reg), 4
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "read_w":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(f"({reg}) ^ 0x2"), 2
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "read_b":
        read = copy.deepcopy(template)
        read.kind, read.addr, read.width = "Read", dynamic(f"({reg}) ^ 0x3"), 1
        read.var, read.value, read.evidence = "value", None, mmio_evidence
        return [read, Op(kind="Return", addr=addr_fixed(0), width=0,
                         value="value", evidence=state_evidence,
                         source_loc=read.source_loc, line=read.line)]
    if field == "write_l":
        write = copy.deepcopy(template)
        write.kind, write.addr, write.width = "Write", dynamic(reg), 4
        write.value, write.evidence = value, mmio_evidence
        return [write]

    base_expr = f"({reg}) & ~0x3"
    if field == "write_b":
        shift = f"(({reg}) & 0x3) * 8"
        rmw = copy.deepcopy(template)
        rmw.kind, rmw.addr, rmw.width = "ReadModifyWrite", dynamic(base_expr), 4
        rmw.var = "__old"
        rmw.value = (f"((__old & ~(0xff << ({shift}))) | "
                     f"((({value}) & 0xff) << ({shift})))")
        rmw.evidence = mmio_evidence
        return [rmw]

    transfer_addr, transfer_reg = symbolic("SDHCI_TRANSFER_MODE")
    transfer = f"({reg}) == (SDHCI_TRANSFER_MODE)"
    command = f"({reg}) == (SDHCI_COMMAND)"
    ordinary = f"!(({transfer}) || ({command}))"
    save = Op(
        kind="StateWrite", addr=addr_fixed(0), width=2, value=value,
        state_field="xfer_mode_shadow", evidence=state_evidence,
        source_loc=template.source_loc, line=template.line)
    load = Op(
        kind="StateRead", addr=addr_fixed(0), width=2,
        state_field="xfer_mode_shadow", var="__xfer_mode_shadow",
        evidence=state_evidence, source_loc=template.source_loc,
        line=template.line)
    command_write = Op(
        kind="Write", addr=transfer_addr, reg_name=transfer_reg, width=4,
        value=f"(({value}) << 16) | __xfer_mode_shadow",
        evidence=mmio_evidence, source_loc=template.source_loc,
        line=template.line)
    shift = f"(({reg}) & 0x2) * 8"
    default_rmw = Op(
        kind="ReadModifyWrite", addr=dynamic(base_expr), width=4,
        value=(f"((__old & ~(0xffff << ({shift}))) | "
               f"((({value}) & 0xffff) << ({shift})))"),
        var="__old", evidence=mmio_evidence,
        source_loc=template.source_loc, line=template.line)
    return [
        _sdhci_branch(save, transfer),
        _sdhci_branch(load, command),
        _sdhci_branch(command_write, command),
        _sdhci_branch(default_rmw, ordinary),
    ]


def _annotate_private_sdhci_accessor(extraction: FuncExtraction, field: str,
                                     callee: str, evidence: dict,
                                     macros=None) -> None:
    expanded: list[Op] = []
    for op in extraction.ops:
        if op.kind not in {"Read", "Write", "ReadModifyWrite"}:
            expanded.append(op)
            continue
        effective = (op.evidence or {}).get("effective_callee")
        if (effective in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
                or effective in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS):
            expanded.extend(_sdhci_public_accessor_ops(
                field, effective, op.evidence or evidence,
                source_op=op, macros=macros))
            continue
        op.evidence = _sdhci_contract_evidence(
            op.evidence or evidence, field, callee)
        expanded.append(op)
    extraction.ops = expanded
    for op in extraction.ops:
        if op.kind == "Return":
            op.evidence = _sdhci_contract_evidence(
                op.evidence or evidence, field, callee,
                access_domain="source_result")
    if field.startswith("read_") and extraction.return_expr and not any(
            op.kind == "Return" for op in extraction.ops):
        extraction.ops.append(Op(
            kind="Return", addr=addr_fixed(0), width=0,
            value=extraction.return_expr,
            evidence=_sdhci_contract_evidence(
                evidence, field, callee, access_domain="source_result")))


def infer_sdhci_ops_summaries(funcs: list[Func], extractions: dict, macros
                              ) -> tuple[list[Func], dict, list[dict], list[dict], list[dict]]:
    if not funcs:
        return [], {}, [], [], []
    source = funcs[0].source_path
    try:
        text = open(source, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], {}, [], [], []
    target_names = {func.name for func in funcs}
    extraction_by_name = {
        func.name: extractions.get(func.symbol_id or func.name)
        or extractions.get(func.module_name or func.name)
        or extractions.get(func.name)
        for func in funcs
    }
    synthetic_funcs: list[Func] = []
    synthetic_extractions: dict[str, FuncExtraction] = {}
    summaries: list[dict] = []
    unmodeled: list[dict] = []
    delegates: list[dict] = []
    for table_name, body, block_offset in _sdhci_initializer_blocks(text):
        for part in _split_initializer(body):
            match = re.match(
                r"\.\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)", part)
            if not match:
                continue
            field, callee = match.groups()
            entry_offset = block_offset + body.find(part)
            evidence = _sdhci_evidence(
                source, text, entry_offset, field, callee,
                "read" if field.startswith("read_") else "write",
                _SDHCI_ACCESSOR_FIELDS.get(field, ("", 4))[1])
            if callee in target_names and field in _SDHCI_ACCESSOR_FIELDS:
                extraction = extraction_by_name.get(callee)
                if extraction is not None:
                    _annotate_private_sdhci_accessor(
                        extraction, field, callee, evidence, macros)
                    summaries.append({
                        "table": table_name, "field": field,
                        "callee": callee, "module": callee,
                        "width_bytes": _SDHCI_ACCESSOR_FIELDS[field][1],
                        "implementation": "source-private",
                    })
                continue
            if callee in _SDHCI_CORE_DELEGATES:
                delegates.append({
                    "table": table_name, "field": field, "callee": callee,
                    "line": evidence["line"],
                    "summary_contract": "linux.sdhci_core_export",
                })
                continue
            is_read = callee in mmio.SUBSYSTEM_MMIO_READ_LAYOUTS
            is_write = callee in mmio.SUBSYSTEM_MMIO_WRITE_LAYOUTS
            if not is_read and not is_write:
                unmodeled.append({
                    "table": table_name,
                    "field": field,
                    "callee": callee,
                    "line": text.count("\n", 0, entry_offset) + 1,
                    "reason": "external SDHCI core callback lacks register summary",
                })
                continue
            width = mmio.infer_width(callee)
            params = [("host", "struct sdhci_host *")]
            if is_write:
                params.extend([("value", f"u{width * 8}"), ("reg", "int")])
                value, address_text = mmio.write_value_addr(
                    callee, ["host", "value", "reg"])
                kind = "Write"
                role = "write_config"
            else:
                params.append(("reg", "int"))
                address_text = mmio.read_addr_expr(callee, ["host", "reg"])
                value = None
                kind = "Read"
                role = "read_config"
            address, register = resolve_addr(
                address_text, {"host": BasePtr("host")}, macros)
            name = f"{table_name}__{field}"
            func = Func(
                name=name, line=evidence["line"], cursor=None, params=params,
                source_path=source, symbol_id=name, module_name=name,
                is_static=True, synthetic_role=role, synthetic_context="thread",
                synthetic_callback_table=f"sdhci_ops.{field}",
                synthetic_return_type=f"u{width * 8}" if is_read else "void",
            )
            template = Op(
                kind=kind, addr=address, width=width, value=value,
                reg_name=register, var="value" if is_read else None,
                evidence=evidence,
                source_loc=f"subsystem sdhci_ops.{field}:{evidence['line']}",
                line=evidence["line"],
            )
            ops = _sdhci_public_accessor_ops(
                field, callee, evidence, source_op=template, macros=macros)
            extraction = FuncExtraction(
                name=name, params=[param for param, _ctype in params], ops=ops)
            synthetic_funcs.append(func)
            synthetic_extractions[name] = extraction
            summaries.append({
                "table": table_name, "field": field, "callee": callee,
                "module": name, "width_bytes": width,
            })
    return (synthetic_funcs, synthetic_extractions, summaries,
            unmodeled, delegates)

