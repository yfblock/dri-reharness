"""extract_function: flow-sensitive per-function register-op extraction."""
from __future__ import annotations
import re
from typing import Optional
import clang.cindex as cx

from .. import mmio
from .. import transactions
from ..taint import (
    BasePtr, ReadTaint, SymExpr, Top, AbsVal,
    addr_fixed, addr_base_of, addr_equal, val_to_value_str,
)
from ast_analyzer import (
    Func, function_calls, walk_with_control, continuation_guards, source_text,
)
from .ops import Op, _CONTROL_KW
from .expr_eval import _IDENT_RE, _strip_casts, eval_expr, resolve_addr
from .assign_scan import (
    _abs_expr, _buffer_write_entries, _general_assignments,
    _general_assignment_store, _local_value_entries,
    _plain_pointer_assignments, _pointer_assignment_store,
    _resolved_argument, _state_assignment_entries,
)
from .funcs import FuncExtraction, _path_return_expr
from .substitution import (
    _expand_addr_numeric_macros, _expand_pure_calls,
    _instantiate_op, _substitute_text,
)
from .rmw import (
    _bind_lhs, _has_classified_read_provenance, _norm_key,
    _proven_return_read_var, _read_initial_transform, _rmw_transform,
)


def extract_function(func: Func, macros, tu, *,
                     source_lines: Optional[list[str]] = None,
                     inline_cache: Optional[dict] = None,
                     mmio_globals: Optional[list[str]] = None,
                     mmio_alias_facts: Optional[dict[str, dict]] = None,
                     wrapper_summaries: Optional[dict[str, dict]] = None,
                     indirect_targets: Optional[dict[str, str]] = None,
                     callback_entries: Optional[set[str]] = None,
                     depth: int = 0, max_depth: int = 3,
                     condition: Optional[str] = None,
                     include_framework: bool = False,
                     extra_blacklist: Optional[set[str]] = None) -> FuncExtraction:
    """Extract register ops for one function (with wrapper inlining)."""
    result = FuncExtraction(
        name=func.name, params=[name for name, _type in func.params if name])
    returns = []
    for cursor in func.cursor.walk_preorder():
        if cursor.kind == cx.CursorKind.RETURN_STMT:
            text = source_text(tu, cursor).strip()
            match = re.fullmatch(r"return\s+(.+?)\s*;?", text, re.S)
            if match:
                returns.append((match.group(1).strip(), cursor.location.line))
    result.return_expr = _path_return_expr(func, tu)
    source_return_expr = result.return_expr
    return_value = result.return_expr
    return_line = returns[0][1] if result.return_expr else 0
    return_read_index = 0
    store: dict[str, AbsVal] = {}
    read_origins: dict[str, tuple[dict, int]] = {}
    read_initial: dict[str, str] = {}
    # seed file-scope MMIO base globals (e.g. `static void __iomem *mmio`)
    for g in (mmio_globals or []):
        store[g] = BasePtr(g)
    # seed params — iomem/pointer params are MMIO base candidates
    for pname, ptype in func.params:
        if not pname:
            continue
        if ptype and ("__iomem" in ptype or "void *" in ptype or ptype.endswith("*")):
            store[pname] = BasePtr(pname)
        else:
            store[pname] = SymExpr(pname)

    pointer_assignments = _plain_pointer_assignments(
        func.cursor, tu, store, macros)
    general_assignments = _general_assignments(func.cursor, tu)
    continuation, _modeled_exits = continuation_guards(func.cursor)

    calls = function_calls(func.cursor)
    result.calls = calls

    semantic_entries = []
    semantic_entries.extend(_local_value_entries(
        func.cursor, tu, general_assignments, calls))
    for entry in _state_assignment_entries(
            func.cursor, tu, general_assignments):
        item = dict(entry)
        item["kind"] = "StateWrite"
        semantic_entries.append(item)
    semantic_entries.extend(_buffer_write_entries(func.cursor, tu))
    semantic_entries.sort(key=lambda entry: (entry["offset"], entry["line"]))
    semantic_index = 0
    read_value_bindings: dict[str, str] = {}
    buffer_read_names: dict[str, str] = {}

    def buffer_read_name(call_text: str) -> str | None:
        normalized = re.sub(r"\s+", "", call_text).rstrip(";")
        for entry in semantic_entries:
            if (entry["kind"] == "OutputWrite"
                    and re.sub(r"\s+", "", entry["value"])
                    .rstrip(";") == normalized):
                return buffer_read_names.setdefault(
                    normalized, f"buffer_read_{len(buffer_read_names)}")
        return None

    def entry_conditions(entry):
        return [
            condition for condition in entry["conditions"]
            if condition and "scoped_guard" not in condition
            and "gpio_generic_lock" not in condition
        ]

    def emit_semantic_before(offset: int) -> None:
        nonlocal semantic_index
        while (semantic_index < len(semantic_entries)
               and semantic_entries[semantic_index]["offset"] < offset):
            entry = semantic_entries[semantic_index]
            semantic_index += 1
            conditions = [
                condition for condition in entry_conditions(entry)
            ]
            kind = entry["kind"]
            if kind == "ValueBind":
                result.ops.append(Op(
                    kind=kind, addr=addr_fixed(0), width=0,
                    value=entry["rhs"], var=entry["lhs"],
                    condition=conditions[-1] if conditions else None,
                    cond_stack=conditions,
                    control_stack=entry["control"],
                    source_loc=f"{func.name}:{entry['line']}",
                    line=entry["line"],
                    evidence={
                        "origin": "local_assignment",
                        "source": func.source_path,
                        "line": entry["line"],
                        "variable": entry["lhs"],
                    },
                ))
                continue
            if kind == "OutputWrite":
                output_value = entry["value"]
                read_var = read_value_bindings.get(output_value.strip())
                if not read_var:
                    normalized = re.sub(
                        r"\s+", "", output_value).rstrip(";")
                    read_var = next(
                        (var for expression, var in read_value_bindings.items()
                         if re.sub(r"\s+", "", expression).rstrip(";")
                         == normalized),
                        None)
                if read_var:
                    output_value = read_var
                result.ops.append(Op(
                    kind=kind, addr=addr_fixed(0), width=0,
                    value=output_value, var=entry["target"],
                    condition=conditions[-1] if conditions else None,
                    cond_stack=conditions,
                    control_stack=entry["control"],
                    source_loc=f"{func.name}:{entry['line']}",
                    line=entry["line"],
                    evidence={
                        "origin": "buffer_write",
                        "source": func.source_path,
                        "line": entry["line"],
                        "target": entry["target"],
                    },
                ))
                continue
            result.ops.append(Op(
                kind="StateWrite",
                addr=addr_fixed(0),
                width=0,
                value=entry["rhs"],
                condition=conditions[-1] if conditions else None,
                cond_stack=conditions,
                control_stack=entry["control"],
                state_field=entry["lhs"],
                source_loc=f"{func.name}:{entry['line']}",
                line=entry["line"],
                evidence={
                    "origin": "state_assignment",
                    "source": func.source_path,
                    "line": entry["line"],
                    "field": entry["lhs"],
                },
            ))

    def resolved_call_argument(arg: str, call_offset: int,
                               call_store: dict) -> str:
        token = arg.strip()
        if (_IDENT_RE.fullmatch(token)
                and any(entry["kind"] == "ValueBind"
                        and entry["lhs"] == token
                        and entry["offset"] < call_offset
                        for entry in semantic_entries)):
            return token
        return _resolved_argument(arg, call_store, macros)

    def evidence_for(cs, kind: str, addr: dict,
                     source_address: str = "",
                     effective_name: str | None = None,
                     subsystem_args: list[str] | None = None) -> dict:
        from ..accounting import callsite_evidence
        evidence = callsite_evidence(
            func, cs, kind, effective_name=effective_name)
        base = addr_base_of(addr) or ""
        for alias, fact in (mmio_alias_facts or {}).items():
            referenced = bool(re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                source_address or ""))
            if (base == alias or base.startswith(alias + "->")
                    or base.startswith(alias + ".") or referenced):
                evidence["alias_provenance"] = {"name": alias, **fact}
                break
        summary = mmio.summary_kind(effective_name or cs.name)
        if summary == "virtio_config":
            evidence["summary_contract"] = "linux.virtio_config"
            args = subsystem_args or []
            if effective_name in {"virtio_cread_le", "virtio_cwrite_le"}:
                if len(args) >= 3:
                    evidence["config_member"] = args[2]
                if args:
                    evidence["virtio_device"] = args[0]
            elif effective_name == "virtio_cread_bytes":
                if len(args) >= 2:
                    evidence["config_member"] = args[1]
                if args:
                    evidence["virtio_device"] = args[0]
        elif summary == "virtqueue":
            evidence["summary_contract"] = "linux.virtqueue"
            args = subsystem_args or []
            if args:
                evidence["queue_expr"] = args[0]
            evidence["queue_operation"] = effective_name or cs.name
        return evidence

    # map line → structured lexical control stack
    line_to_cond: dict[int, list[str]] = {}
    line_to_control: dict[int, list[dict]] = {}
    for cursor, stack in walk_with_control(func.cursor):
        if cursor.location and cursor.location.file:
            ln = cursor.location.line
            filtered_stack = [
                frame for frame in stack
                if "scoped_guard" not in frame.get("guard", "")
                and "gpio_generic_lock" not in frame.get("guard", "")
            ]
            if filtered_stack:
                line_to_control.setdefault(ln, filtered_stack)
                line_to_cond.setdefault(
                    ln, [frame.get("guard", "") for frame in filtered_stack
                         if frame.get("guard")])

    for cs in calls:
        name = cs.name
        if not name or name in _CONTROL_KW:
            continue
        if name in (extra_blacklist or set()):
            continue
        cond = None
        cond_stack = []
        control_stack = []
        if cs.line in line_to_cond:
            st = [c for c in line_to_cond[cs.line]
                  if "scoped_guard" not in c and "gpio_generic_lock" not in c]
            if st:
                cond_stack = list(st)
                cond = st[-1]
        if cs.line in line_to_control:
            control_stack = [dict(frame) for frame in line_to_control[cs.line]]

        call_offset = (cs.cursor.location.offset
                       if cs.cursor.location is not None else 0)
        emit_semantic_before(call_offset)
        for transition in continuation:
            before_offset = transition.get("before_offset", 0)
            if (transition["after_offset"]
                    and transition["after_offset"] <= call_offset
                    and (not before_offset or call_offset < before_offset)):
                frame = dict(transition["frame"])
                if frame.get("source") == "loop-transfer":
                    control_stack.append(frame)
                else:
                    control_stack.insert(0, frame)
                if frame.get("guard"):
                    if frame.get("source") == "loop-transfer":
                        cond_stack.append(frame["guard"])
                    else:
                        cond_stack.insert(0, frame["guard"])
                    cond = cond or frame["guard"]

        access_name = mmio.effective_access_name(name, cs.callee_text)
        access_args = mmio.access_args(access_name, cs)
        source_line = ((source_lines or [])[cs.line - 1]
                       if 0 < cs.line <= len(source_lines or []) else "")
        access_name, access_args = mmio.recover_source_access(
            access_name, access_args, source_line)
        lhs = _bind_lhs(source_lines or [], cs.line, access_name)
        if mmio.summary_kind(access_name) in {"virtio_config", "virtqueue"}:
            control_stack = [
                frame for frame in control_stack
                if not (frame.get("kind") == "loop"
                        and frame.get("loop_kind") == "do"
                        and "virtio_" in frame.get("source", ""))]
            cond_stack = [frame.get("guard", "") for frame in control_stack
                          if frame.get("guard")]
            cond = cond_stack[-1] if cond_stack else None
        call_store = dict(store)
        call_store.update(_general_assignment_store(
            general_assignments, call_offset, call_store, macros))
        call_store.update(_pointer_assignment_store(
            pointer_assignments, cs.line))
        # Path-sensitive scalar fold: conditional assignments to a local
        # (value = 1; if (g) value = 2; writel(value, ...)) join into a
        # ternary so the Write carries Ite(g, 2, 1) instead of the bare
        # variable.  Only overlays names still unresolved (bare SymExpr).
        for lhs, folded in _pointer_assignment_store(
                general_assignments, cs.line).items():
            current = call_store.get(lhs)
            if ("?" in folded.text
                    and (current is None
                         or (isinstance(current, SymExpr)
                             and current.text == lhs))):
                call_store[lhs] = folded

        # ioremap → taint LHS as BasePtr
        if mmio.is_ioremap(name):
            if lhs:
                store[_norm_key(lhs)] = BasePtr(lhs)
            continue

        transaction = transactions.contract_for_call(cs, lhs)
        if transaction is not None:
            from ..accounting import transaction_callsite_evidence
            evidence = transaction_callsite_evidence(func, cs, transaction)
            kind = {
                "read": "TransactionRead",
                "write": "TransactionWrite",
                "update": "TransactionUpdate",
            }[transaction["kind"]]
            result.ops.append(Op(
                kind=kind, addr=addr_fixed(0), width=0,
                condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                var=transaction.get("result"),
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
                evidence=evidence, transaction=transaction))
            result_name = transaction.get("result")
            if result_name:
                store[_norm_key(result_name)] = SymExpr(result_name)
            if lhs and transaction.get("result_convention") != "return_value":
                store[_norm_key(lhs)] = SymExpr(lhs)
            continue

        if mmio.is_mmio_read(access_name):
            addr_arg = mmio.read_addr_expr(access_name, access_args)
            source_addr_arg = addr_arg
            addr_arg = _expand_pure_calls(addr_arg, inline_cache)
            addr, reg_name = resolve_addr(addr_arg, call_store, macros)
            if addr_arg != source_addr_arg:
                addr = _expand_addr_numeric_macros(addr, macros)
            result_var = mmio.read_result_var(
                access_name, access_args, lhs) or None
            call_text = source_text(tu, cs.cursor).strip()
            if not result_var:
                result_var = buffer_read_name(call_text)
            if (not result_var and return_value and call_text
                    and call_text in return_value):
                result_var = f"__return_read_{return_read_index}"
                return_read_index += 1
                if _strip_casts(return_value) == _strip_casts(call_text):
                    result.return_read_var = result_var
                return_value = return_value.replace(call_text, result_var, 1)
            op = Op(
                kind="Read", addr=addr,
                width=mmio.infer_call_width(access_name, cs),
                value=None, condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                reg_name=reg_name,
                var=result_var,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
                evidence=evidence_for(
                    cs, "read", addr, addr_arg, access_name, access_args),
            )
            result.ops.append(op)
            if result_var:
                read_value_bindings[call_text] = result_var
                read_value_bindings[call_text.rstrip(";").strip()] = result_var
            if result_var:
                key = _norm_key(result_var)
                store[key] = ReadTaint(addr=addr, reg_name=reg_name)
                read_origins[key] = (addr, cs.line)
                read_initial[key] = _read_initial_transform(
                    key, cs, source_lines or [], tu)
            continue

        if mmio.is_mmio_rmw(name):
            parts = mmio.rmw_parts(name, cs.arg_text)
            if parts is None:
                result.warnings.append(
                    f"cannot decode register RMW call {name} at line {cs.line}")
                continue
            address_text, mask_text, update_text = parts
            source_address_text = address_text
            address_text = _expand_pure_calls(address_text, inline_cache)
            mask_text = _expand_pure_calls(mask_text, inline_cache)
            update_text = _expand_pure_calls(update_text, inline_cache)
            addr, reg_name = resolve_addr(address_text, call_store, macros)
            if address_text != source_address_text:
                addr = _expand_addr_numeric_macros(addr, macros)
            transform = (f"((__old & ~({mask_text})) | "
                         f"(({update_text}) & ({mask_text})))")
            result.ops.append(Op(
                kind="ReadModifyWrite", addr=addr,
                width=mmio.infer_width(name), value=transform,
                condition=cond, cond_stack=cond_stack,
                control_stack=control_stack, reg_name=reg_name,
                var="__old", source_loc=f"{func.name}:{cs.line}",
                line=cs.line,
                evidence=evidence_for(
                    cs, "rmw", addr, address_text, access_name, access_args)))
            continue

        if mmio.is_mmio_write(access_name):
            # Generic Linux writel(val, addr); private accessors are handled
            # through source-derived wrapper summaries below.
            val_text, addr_text = mmio.write_value_addr(
                access_name, access_args)
            source_addr_text = addr_text
            val_text = _expand_pure_calls(val_text, inline_cache)
            addr_text = _expand_pure_calls(addr_text, inline_cache)
            addr, reg_name = resolve_addr(addr_text, call_store, macros)
            if addr_text != source_addr_text:
                addr = _expand_addr_numeric_macros(addr, macros)
            preserve_local = bool(
                _IDENT_RE.fullmatch(val_text.strip())
                and any(entry["kind"] == "ValueBind"
                        and entry["lhs"] == val_text.strip()
                        and entry["offset"] < call_offset
                        for entry in semantic_entries)
                and not isinstance(
                    store.get(_norm_key(val_text.strip())), ReadTaint))
            if preserve_local:
                folded = call_store.get(_norm_key(val_text.strip()))
                val = (folded if isinstance(folded, (SymExpr, ReadTaint))
                       and not (isinstance(folded, SymExpr)
                                and folded.text == val_text.strip())
                       else SymExpr(val_text.strip()))
            else:
                val = eval_expr(val_text, call_store, macros)
            kind = "Write"
            value = val_to_value_str(val) or val_text.strip() or None
            rmw_var = None
            # RMW: value is a read-taint of the SAME address
            if isinstance(val, ReadTaint) and addr_equal(val.addr, addr):
                kind = "ReadModifyWrite"
                key = _norm_key(val_text.strip())
                origin = read_origins.get(key)
                if origin and addr_equal(origin[0], addr):
                    rmw_var = key
                    value = _rmw_transform(
                        key, origin[1], cs.line, source_lines or [],
                        line_to_cond, read_initial.get(key))
            op = Op(
                kind=kind, addr=addr,
                width=mmio.infer_call_width(access_name, cs),
                value=value, condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                reg_name=reg_name,
                var=rmw_var,
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
                evidence=evidence_for(
                    cs, "write", addr, addr_text, access_name, access_args),
            )
            result.ops.append(op)
            continue

        if mmio.is_delay(name):
            arg = cs.arg_text[0] if cs.arg_text else "0"
            ns = _parse_delay_ns(name, arg, macros)
            op = Op(
                kind="Delay", addr=addr_fixed(0), width=0,
                value=str(ns), condition=cond, cond_stack=cond_stack,
                control_stack=control_stack,
                intent="Synchronization",
                source_loc=f"{func.name}:{cs.line}", line=cs.line,
            )
            op._delay_ns = ns  # type: ignore[attr-defined]
            result.ops.append(op)
            continue

        from ..indirect import resolve_indirect_call
        indirect_target = resolve_indirect_call(cs, indirect_targets or {})
        callee_key = indirect_target or cs.symbol_id or name
        resolved_name = indirect_target or name
        inlined = ((inline_cache or {}).get(callee_key)
                   or (inline_cache or {}).get(resolved_name))
        summary = ((wrapper_summaries or {}).get(callee_key)
                   or (wrapper_summaries or {}).get(resolved_name))
        # A callback entry is an independent registration root, but a direct
        # C call to it is still an ordinary callsite whose effects must be
        # represented in the caller.  The formalizer retains the callback's
        # own module separately; keeping both views preserves registration and
        # direct-call semantics without relying on backend-specific glue.
        # An independently proven wrapper call remains useful even when the
        # caller also contains an unknown external call.  The unknown effect
        # stays visible to access accounting/readiness; dropping this known
        # operation would lose evidence rather than make the result safer.
        if (inlined is None or depth >= max_depth) and summary is not None:
            import copy
            mapping = {
                param: resolved_call_argument(arg, call_offset, call_store)
                for param, arg in zip(
                    summary.get("params", []), cs.arg_text)
                if param and arg
            }
            address_text = _substitute_text(
                summary.get("address"), mapping) or ""
            source_address_text = address_text
            address_text = _expand_pure_calls(address_text, inline_cache)
            addr, reg_name = resolve_addr(address_text, call_store, macros)
            if address_text != source_address_text:
                addr = _expand_addr_numeric_macros(addr, macros)
            # A wrapper summary has two distinct provenance layers.  The
            # primitive access belongs to the wrapper definition, while the
            # instantiated operation belongs to this caller callsite.  Using
            # the definition's site_id for both makes coverage rescue think
            # unrelated helper callsites are already covered.
            wrapper_definition = copy.deepcopy(summary.get("evidence", {}))
            evidence = evidence_for(
                cs, "read" if summary["kind"] == "Read" else "write",
                addr, address_text, effective_name=resolved_name,
                subsystem_args=cs.arg_text)
            evidence["width_bytes"] = summary["width"]
            evidence["origin"] = "wrapper_summary"
            evidence["wrapper_definition"] = wrapper_definition
            evidence["wrapper_symbol"] = summary.get("symbol")
            evidence.setdefault("summarized_at", []).append({
                "function": func.name, "line": cs.line,
                "callee": resolved_name, "source_loc": func.source_path,
                "indirect_expression": cs.callee_text if indirect_target else None,
            })
            if summary["kind"] == "Read":
                summary_var = lhs or None
                call_text = source_text(tu, cs.cursor).strip()
                if (not summary_var and return_value and call_text
                        and call_text in return_value):
                    summary_var = f"__return_read_{return_read_index}"
                    return_read_index += 1
                    if _strip_casts(return_value) == _strip_casts(call_text):
                        result.return_read_var = summary_var
                    return_value = return_value.replace(
                        call_text, summary_var, 1)
                op = Op(
                    kind="Read", addr=addr, width=summary["width"],
                    value=None, condition=cond, cond_stack=cond_stack,
                    control_stack=control_stack, reg_name=reg_name,
                    var=summary_var, evidence=evidence,
                    source_loc=f"{func.name}:{cs.line} (summary {resolved_name})",
                    line=cs.line)
                result.ops.append(op)
                if summary_var:
                    key = _norm_key(summary_var)
                    store[key] = ReadTaint(addr=addr, reg_name=reg_name)
                    read_origins[key] = (addr, cs.line)
                    read_initial[key] = key
            else:
                raw_value = _substitute_text(
                    summary.get("value"), mapping) or ""
                raw_value = _expand_pure_calls(raw_value, inline_cache)
                raw_key = _norm_key(raw_value.strip())
                original_taint = store.get(raw_key)
                if (isinstance(original_taint, ReadTaint)
                        and addr_equal(original_taint.addr, addr)):
                    abstract_value = original_taint
                else:
                    abstract_value = eval_expr(raw_value, call_store, macros)
                value = val_to_value_str(abstract_value) or raw_value or None
                kind = "Write"
                rmw_var = None
                if (isinstance(abstract_value, ReadTaint)
                        and addr_equal(abstract_value.addr, addr)):
                    kind = "ReadModifyWrite"
                    key = _norm_key(raw_value.strip())
                    origin = read_origins.get(key)
                    if origin and addr_equal(origin[0], addr):
                        rmw_var = key
                        value = _rmw_transform(
                            key, origin[1], cs.line, source_lines or [],
                            line_to_cond, read_initial.get(key))
                result.ops.append(Op(
                    kind=kind, addr=addr, width=summary["width"],
                    value=value, condition=cond, cond_stack=cond_stack,
                    control_stack=control_stack, reg_name=reg_name,
                    var=rmw_var,
                    evidence=evidence,
                    source_loc=f"{func.name}:{cs.line} (summary {resolved_name})",
                    line=cs.line))
            continue

        # framework → ignore (filtered)
        if not include_framework and mmio.is_framework(name):
            continue

        # wrapper function inlining
        if inlined is not None and depth < max_depth:
            if inlined.ops:
                mapping = {
                    param: resolved_call_argument(arg, call_offset, call_store)
                    for param, arg in zip(inlined.params, cs.arg_text)
                    if param and arg
                }
                instantiated = [
                    _instantiate_op(
                        op, mapping, macros, inline_cache,
                        inline_context=f"{func.name}:{call_offset}")
                    for op in inlined.ops
                ]
                # A callee Return describes the value of this call, not an
                # early return from its caller.  Consume it while inlining and
                # propagate the expression only when this call itself occurs
                # in the caller's unique return expression.
                inlined_returns = [
                    item for item in instantiated if item.kind == "Return"]
                instantiated = [
                    item for item in instantiated if item.kind != "Return"]
                call_text = source_text(tu, cs.cursor).strip()
                if (inlined_returns and return_value and call_text
                        and call_text in return_value):
                    returned_value = inlined_returns[-1].value or "0"
                    return_value = return_value.replace(
                        call_text, f"({returned_value})", 1)
                # If the classifier proved that a helper returns one specific
                # register-read result directly, bind that read to the caller
                # assignment target.  This preserves patterns such as
                # ``value = read_helper(...); write_helper(..., value | mask)``.
                # A helper name merely containing ``read`` is not evidence:
                # property/configuration APIs may return an unrelated scalar
                # after performing an earlier MMIO read in the same function.
                if lhs and inlined.return_read_var:
                    returned_read_var = _substitute_text(
                        inlined.return_read_var, mapping)
                    returned_read = next(
                        (item for item in reversed(instantiated)
                         if item.kind == "Read"
                         and item.var == returned_read_var), None)
                    if _has_classified_read_provenance(returned_read):
                        returned_read.var = lhs
                for o2, op in zip(instantiated, inlined.ops):
                    o2.condition = cond or o2.condition
                    o2.cond_stack = cond_stack + o2.cond_stack
                    o2.control_stack = control_stack + o2.control_stack
                    o2.source_loc = f"{func.name}:{cs.line} (↳ {op.source_loc})"
                    o2.evidence.setdefault("inlined_at", []).append({
                        "function": func.name,
                        "line": cs.line,
                        "callee": resolved_name,
                        "indirect_expression": cs.callee_text
                        if indirect_target else None,
                    })
                    if o2.kind == "Read":
                        o2.var = o2.var or buffer_read_name(call_text)
                        if o2.var:
                            read_value_bindings[call_text] = o2.var
                    result.ops.append(o2)

    emit_semantic_before(1 << 62)
    materialize_return = return_value != source_return_expr
    if return_value is not None:
        final_store = _general_assignment_store(
            general_assignments, 1 << 62, store, macros,
            include_compound=True)
        scalar_mapping = {
            name: _abs_expr(item, name)
            for name, item in final_store.items()
            if _IDENT_RE.fullmatch(name)
            and not isinstance(item, (Top, ReadTaint))
        }
        return_value = _substitute_text(return_value, scalar_mapping)
        result.return_expr = return_value
        result.return_read_var = (
            result.return_read_var
            or _proven_return_read_var(return_value, result.ops))

    if return_value is not None and materialize_return:
        result.ops.append(Op(
            kind="Return", addr=addr_fixed(0), width=0,
            value=return_value,
            source_loc=f"{func.name}:{return_line}", line=return_line,
            evidence={"access_domain": "source_result"},
        ))

    return result


def _parse_delay_ns(name: str, arg: str, macros=None) -> int:
    try:
        n = int(arg, 0)
    except Exception:
        n = macros.offset(arg.strip()) if macros is not None else None
        if n is None:
            return 0
    if name in ("mdelay", "msleep", "ssleep"):
        return n * 1_000_000
    if name == "udelay":
        return n * 1000
    if name == "ndelay":
        return n
    return n
