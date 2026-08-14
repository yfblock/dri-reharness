"""VirtIO state subsystem summary inference."""
from __future__ import annotations

from ._common import *


def _virtio_state_evidence(evidence: dict, contract: str) -> dict:
    out = copy.deepcopy(evidence)
    out["origin"] = "subsystem_summary"
    out["summary_contract"] = contract
    return out


def _virtio_config_field(member: str) -> str:
    text = re.sub(r"\s+", "", member or "value")
    offsetof = re.search(r"offsetof\([^,]+,([^)]+)\)", text)
    if offsetof:
        text = offsetof.group(1)
    text = text.replace("->", ".")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "value"
    return f"virtio_cfg_{text.lower()}"


def _virtio_queue_prefix(extraction: FuncExtraction) -> str:
    expressions = [
        (op.evidence or {}).get("queue_expr", "") for op in extraction.ops
        if (op.evidence or {}).get("summary_contract") == "linux.virtqueue"]
    if any(re.search(r"(?:->|\.)sts\b|status", expr, re.I)
           for expr in expressions):
        return "virtio_sts"
    if any(re.search(r"(?:->|\.)evt\b|event", expr, re.I)
           for expr in expressions):
        return "virtio_evt"
    name = extraction.name.lower()
    return "virtio_sts" if "status" in name else "virtio_evt"


def _virtio_loop_key(frame: dict) -> str:
    return frame.get("source") or frame.get("guard", "")


def _rewrite_virtio_loop_frames(extraction: FuncExtraction, prefix: str) -> None:
    bounds: dict[str, str] = {}
    for op in extraction.ops:
        evidence = op.evidence or {}
        operation = evidence.get("queue_operation")
        if not operation:
            continue
        for frame in op.control_stack:
            if frame.get("kind") != "loop":
                continue
            if operation in {"virtqueue_get_buf"}:
                field = f"{prefix}_completed"
            elif operation == "virtqueue_detach_unused_buf":
                field = f"{prefix}_outstanding"
            elif operation == "virtqueue_add_inbuf_cache_clean":
                field = f"{prefix}_queue_depth"
            else:
                continue
            bounds[_virtio_loop_key(frame)] = field
    for op in extraction.ops:
        rewritten = []
        for frame in op.control_stack:
            item = copy.deepcopy(frame)
            for key in ("guard", "source"):
                item[key] = re.sub(
                    r"sizeof\s*\(\s*struct\s+[A-Za-z_]\w*_devids\s*\)",
                    "8", item.get(key, ""))
            field = bounds.get(_virtio_loop_key(frame))
            if field:
                item.update({
                    "kind": "loop", "loop_kind": "for",
                    "init": "unsigned int __virtio_i = 0",
                    "guard": f"__virtio_i < vi->{field}",
                    "step": "__virtio_i++",
                    "subsystem_contract": "linux.virtqueue.bounded",
                })
            rewritten.append(item)
        op.control_stack = rewritten
        op.cond_stack = [frame.get("guard", "") for frame in rewritten
                         if frame.get("guard")]
        op.condition = op.cond_stack[-1] if op.cond_stack else None


def _virtio_state_ops(op: Op, prefix: str) -> list[Op]:
    evidence = op.evidence or {}
    contract = evidence.get("summary_contract")
    if contract == "linux.virtio_config":
        field = _virtio_config_field(evidence.get("config_member", "value"))
        semantic = _virtio_state_evidence(evidence, contract)
        if op.kind == "Read":
            var = op.var if re.fullmatch(r"[A-Za-z_]\w*", op.var or "") else field
            return [Op(
                kind="StateRead", addr=addr_fixed(0), width=op.width,
                state_field=field, var=var, evidence=semantic,
                condition=op.condition, cond_stack=list(op.cond_stack),
                control_stack=copy.deepcopy(op.control_stack),
                source_loc=op.source_loc, line=op.line)]
        if op.kind == "Write":
            return [Op(
                kind="StateWrite", addr=addr_fixed(0), width=op.width,
                state_field=field, value=op.value, evidence=semantic,
                condition=op.condition, cond_stack=list(op.cond_stack),
                control_stack=copy.deepcopy(op.control_stack),
                source_loc=op.source_loc, line=op.line)]
    if contract != "linux.virtqueue":
        return [op]
    operation = evidence.get("queue_operation", "")
    semantic = _virtio_state_evidence(evidence, contract)
    state = None
    delta = None
    result_var = None
    if operation == "virtqueue_add_inbuf_cache_clean":
        state, delta = f"{prefix}_available", 1
    elif operation == "virtqueue_add_outbuf":
        state, delta = f"{prefix}_outstanding", 1
    elif operation == "virtqueue_get_buf":
        state, delta = f"{prefix}_completed", -1
        result_var = op.var
    elif operation == "virtqueue_detach_unused_buf":
        state, delta = f"{prefix}_outstanding", -1
        result_var = op.var
    elif operation == "virtqueue_get_vring_size":
        state = f"{prefix}_queue_depth"
        result_var = op.var
    elif operation == "virtqueue_kick":
        return [Op(
            kind="StateWrite", addr=addr_fixed(0), width=4,
            state_field=f"{prefix}_notified", value="1",
            evidence=semantic, condition=op.condition,
            cond_stack=list(op.cond_stack),
            control_stack=copy.deepcopy(op.control_stack),
            source_loc=op.source_loc, line=op.line)]
    if state is None:
        return [op]
    temp = f"__{state}"
    read = Op(
        kind="StateRead", addr=addr_fixed(0), width=4,
        state_field=state, var=result_var or temp, evidence=semantic,
        condition=op.condition, cond_stack=list(op.cond_stack),
        control_stack=copy.deepcopy(op.control_stack),
        source_loc=op.source_loc, line=op.line)
    if delta is None:
        return [read]
    source_var = result_var or temp
    value = (f"({source_var}) + 1" if delta > 0
             else f"(({source_var}) > 0 ? ({source_var}) - 1 : 0)")
    write = Op(
        kind="StateWrite", addr=addr_fixed(0), width=4,
        state_field=state, value=value, evidence=semantic,
        condition=op.condition, cond_stack=list(op.cond_stack),
        control_stack=copy.deepcopy(op.control_stack),
        source_loc=op.source_loc, line=op.line)
    return [read, write]


def _op_effective_line(op: Op) -> int:
    inlined = (op.evidence or {}).get("inlined_at", [])
    return int(inlined[-1].get("line", op.line)) if inlined else int(op.line)


def _insert_virtio_lifecycle_state(funcs: list[Func], extractions: dict, tu) -> None:
    for func in funcs:
        extraction = (extractions.get(func.symbol_id or func.name)
                      or extractions.get(func.module_name or func.name)
                      or extractions.get(func.name))
        if extraction is None:
            continue
        additions: list[Op] = []
        for cursor, control in walk_with_control(func.cursor):
            if cursor.kind != cx.CursorKind.BINARY_OPERATOR:
                continue
            text = source_text(tu, cursor).strip()
            match = re.fullmatch(
                r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
                r"(?:->|\.)ready\s*=\s*(true|false)\s*;?", text)
            if not match:
                continue
            loc = cursor.location
            line = loc.line if loc else 0
            evidence = {
                "site_id": (f"{func.source_path}:{line}:0:"
                            f"{getattr(loc, 'offset', 0) or 0}:virtio.ready"),
                "source": func.source_path, "line": line, "column": 0,
                "offset": getattr(loc, "offset", 0) or 0,
                "function": func.name, "symbol": func.symbol_id or func.name,
                "origin": "subsystem_summary",
                "subsystem_summary": "virtio_lifecycle",
                "summary_contract": "linux.virtio.lifecycle",
                "access_domain": "source_state",
            }
            additions.append(Op(
                kind="StateWrite", addr=addr_fixed(0), width=1,
                state_field="ready", value="1" if match.group(1) == "true" else "0",
                evidence=evidence, line=line,
                condition=(control[-1].get("guard") if control else None),
                cond_stack=[frame.get("guard", "") for frame in control
                            if frame.get("guard")],
                control_stack=[dict(frame) for frame in control],
                source_loc=f"{func.name}:{line}"))
        for addition in additions:
            index = next((index for index, op in enumerate(extraction.ops)
                          if _op_effective_line(op) > addition.line),
                         len(extraction.ops))
            extraction.ops.insert(index, addition)


def infer_virtio_state_summaries(funcs: list[Func], extractions: dict, tu
                                 ) -> list[dict]:
    _insert_virtio_lifecycle_state(funcs, extractions, tu)
    summaries = []
    seen: set[int] = set()
    for extraction in extractions.values():
        if id(extraction) in seen:
            continue
        seen.add(id(extraction))
        if not any((op.evidence or {}).get("summary_contract") in {
                "linux.virtio_config", "linux.virtqueue"}
                for op in extraction.ops):
            continue
        prefix = _virtio_queue_prefix(extraction)
        _rewrite_virtio_loop_frames(extraction, prefix)
        rewritten = []
        for op in extraction.ops:
            rewritten.extend(_virtio_state_ops(op, prefix))
        extraction.ops = rewritten
        summaries.append({
            "module": extraction.name,
            "config_ops": sum((op.evidence or {}).get("summary_contract")
                              == "linux.virtio_config" for op in rewritten),
            "queue_ops": sum((op.evidence or {}).get("summary_contract")
                             == "linux.virtqueue" for op in rewritten),
        })
    return summaries

