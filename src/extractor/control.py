"""Auditable boundary for control flow not represented by structured RIS."""
from __future__ import annotations

import os
import re

import clang.cindex as cx

from . import mmio
from .ast_model import continuation_guards, function_calls, source_text


_LOOPS = {cx.CursorKind.FOR_STMT, cx.CursorKind.WHILE_STMT,
          cx.CursorKind.DO_STMT}
_TRANSFERS = {cx.CursorKind.GOTO_STMT, cx.CursorKind.INDIRECT_GOTO_STMT,
              cx.CursorKind.BREAK_STMT, cx.CursorKind.CONTINUE_STMT}


def _function_cfg(func) -> dict:
    """Build a compact statement-block CFG with dominance evidence.

    The graph is intentionally source-level: each statement is a block.  This
    is finer grained than a conventional maximal basic-block CFG, but preserves
    every explicit transfer and provides stable source provenance.
    """
    tu = func.cursor.translation_unit
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple] = set()
    labels: dict[str, str] = {}
    pending_gotos: list[tuple[str, str, int]] = []
    unresolved: list[dict] = []

    def add_node(cursor=None, *, kind: str | None = None,
                 label: str = "") -> str:
        node_id = f"b{len(nodes)}"
        if cursor is None:
            nodes[node_id] = {
                "id": node_id, "kind": kind or "synthetic",
                "line": 0, "offset": 0, "end_offset": 0,
            }
            return node_id
        loc = cursor.location
        nodes[node_id] = {
            "id": node_id,
            "kind": kind or cursor.kind.name.lower(),
            "line": getattr(loc, "line", 0) or 0,
            "offset": getattr(loc, "offset", 0) or 0,
            "end_offset": getattr(cursor.extent.end, "offset", 0) or 0,
        }
        if label:
            nodes[node_id]["label"] = label
        return node_id

    def add_edge(source: str, target: str | None, kind: str,
                 guard: str = "") -> None:
        if target is None:
            unresolved.append({"source": source, "kind": kind,
                               "reason": "missing structured target"})
            return
        key = (source, target, kind, guard)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edge = {"source": source, "target": target, "kind": kind}
        if guard:
            edge["guard"] = guard[:500]
        edges.append(edge)

    entry = add_node(kind="entry")
    exit_node = add_node(kind="exit")

    def build(cursor, successor: str, break_target: str | None = None,
              continue_target: str | None = None) -> str:
        kind = cursor.kind
        children = list(cursor.get_children())
        if kind == cx.CursorKind.COMPOUND_STMT:
            current = successor
            for child in reversed(children):
                current = build(child, current, break_target, continue_target)
            return current
        if kind == cx.CursorKind.LABEL_STMT:
            node = add_node(cursor, label=cursor.spelling)
            labels[cursor.spelling] = node
            child_entry = successor
            for child in reversed(children):
                child_entry = build(
                    child, child_entry, break_target, continue_target)
            add_edge(node, child_entry, "label-fallthrough")
            return node
        if kind in {cx.CursorKind.GOTO_STMT, cx.CursorKind.INDIRECT_GOTO_STMT}:
            node = add_node(cursor)
            text = source_text(tu, cursor).strip()
            match = re.fullmatch(r"goto\s+([A-Za-z_]\w*)\s*;?", text)
            if kind == cx.CursorKind.GOTO_STMT and match:
                pending_gotos.append((node, match.group(1),
                                      nodes[node]["offset"]))
            else:
                unresolved.append({
                    "source": node, "kind": "indirect-goto",
                    "reason": text or "unresolved indirect goto"})
            return node
        if kind == cx.CursorKind.RETURN_STMT:
            node = add_node(cursor)
            add_edge(node, exit_node, "return")
            return node
        if kind == cx.CursorKind.BREAK_STMT:
            node = add_node(cursor)
            add_edge(node, break_target, "break")
            return node
        if kind == cx.CursorKind.CONTINUE_STMT:
            node = add_node(cursor)
            add_edge(node, continue_target, "continue")
            return node
        if kind == cx.CursorKind.IF_STMT and len(children) >= 2:
            node = add_node(cursor, kind="if")
            condition = source_text(tu, children[0]).strip()
            then_entry = build(
                children[1], successor, break_target, continue_target)
            else_entry = (build(children[2], successor, break_target,
                                continue_target)
                          if len(children) >= 3 else successor)
            add_edge(node, then_entry, "branch-true", condition)
            add_edge(node, else_entry, "branch-false", f"!({condition})")
            return node
        if kind in _LOOPS:
            node = add_node(cursor, kind="loop-header")
            condition = source_text(tu, children[0]).strip() if children else "loop"
            body = children[-1] if children else None
            body_entry = (build(body, node, successor, node)
                          if body is not None else node)
            add_edge(node, body_entry, "loop-body", condition)
            add_edge(node, successor, "loop-exit", f"!({condition})")
            return node
        if kind == cx.CursorKind.SWITCH_STMT and len(children) >= 2:
            node = add_node(cursor, kind="switch")
            selector = source_text(tu, children[0]).strip()
            body_entry = build(
                children[-1], successor, successor, continue_target)
            add_edge(node, body_entry, "switch-dispatch", selector)
            add_edge(node, successor, "switch-exit")
            return node

        node = add_node(cursor)
        add_edge(node, successor, "fallthrough")
        return node

    body = next((child for child in func.cursor.get_children()
                 if child.kind == cx.CursorKind.COMPOUND_STMT), None)
    body_entry = build(body, exit_node) if body is not None else exit_node
    add_edge(entry, body_entry, "entry")
    for source, label, source_offset in pending_gotos:
        target = labels.get(label)
        if target is None:
            unresolved.append({
                "source": source, "kind": "goto", "target_label": label,
                "reason": "target label not found"})
            continue
        direction = ("forward" if nodes[target]["offset"] > source_offset
                     else "backward")
        add_edge(source, target, f"goto-{direction}")

    successors = {node: set() for node in nodes}
    predecessors = {node: set() for node in nodes}
    for edge in edges:
        successors[edge["source"]].add(edge["target"])
        predecessors[edge["target"]].add(edge["source"])

    reachable: set[str] = set()
    work = [entry]
    while work:
        node = work.pop()
        if node in reachable:
            continue
        reachable.add(node)
        work.extend(successors[node] - reachable)

    dominators = {node: set(reachable) for node in reachable}
    dominators[entry] = {entry}
    changed = True
    while changed:
        changed = False
        for node in reachable - {entry}:
            preds = predecessors[node] & reachable
            value = ({node} | set.intersection(
                *(dominators[pred] for pred in preds)) if preds else {node})
            if value != dominators[node]:
                dominators[node] = value
                changed = True

    can_exit: set[str] = set()
    work = [exit_node]
    while work:
        node = work.pop()
        if node in can_exit:
            continue
        can_exit.add(node)
        work.extend(predecessors[node] - can_exit)
    postdominators = {node: set(can_exit) for node in can_exit}
    postdominators[exit_node] = {exit_node}
    changed = True
    while changed:
        changed = False
        for node in can_exit - {exit_node}:
            succs = successors[node] & can_exit
            value = ({node} | set.intersection(
                *(postdominators[succ] for succ in succs)) if succs else {node})
            if value != postdominators[node]:
                postdominators[node] = value
                changed = True

    def immediate(node: str, relation: dict[str, set[str]]) -> str | None:
        candidates = relation.get(node, set()) - {node}
        if not candidates:
            return None
        return max(candidates, key=lambda item: len(relation.get(item, set())))

    for node_id, node in nodes.items():
        node["predecessors"] = sorted(predecessors[node_id])
        node["successors"] = sorted(successors[node_id])
        node["reachable"] = node_id in reachable
        node["idom"] = immediate(node_id, dominators)
        node["ipostdom"] = immediate(node_id, postdominators)

    backedges = [
        {"source": edge["source"], "target": edge["target"],
         "kind": edge["kind"]}
        for edge in edges
        if edge["target"] in dominators.get(edge["source"], set())
    ]
    joins = [node for node in nodes
             if len(predecessors[node] & reachable) > 1]
    return {
        "function": func.name,
        "symbol": func.symbol_id or func.name,
        "source": os.path.abspath(func.source_path),
        "entry": entry,
        "exit": exit_node,
        "blocks": list(nodes.values()),
        "edges": edges,
        "join_blocks": sorted(joins),
        "backedges": backedges,
        "loop_headers": sorted({edge["target"] for edge in backedges}),
        "unresolved_transfers": unresolved,
        "complete": not unresolved,
    }


def _site(func, cursor, kind: str, reason: str,
          status: str = "unsupported") -> dict:
    loc = cursor.location
    source = (os.path.abspath(loc.file.name) if loc and loc.file
              else os.path.abspath(func.source_path))
    return {
        "site_id": (f"{source}:{getattr(loc, 'line', 0) or 0}:"
                    f"{getattr(loc, 'column', 0) or 0}:"
                    f"{getattr(loc, 'offset', 0) or 0}:{kind}"),
        "source": source,
        "line": getattr(loc, "line", 0) or 0,
        "column": getattr(loc, "column", 0) or 0,
        "offset": getattr(loc, "offset", 0) or 0,
        "function": func.name,
        "symbol": func.symbol_id or func.name,
        "kind": kind,
        "status": status,
        "reason": reason,
        "source_text": source_text(func.cursor.translation_unit, cursor).strip(),
    }


def build_control_accounting(funcs) -> dict:
    sites: list[dict] = []
    modeled_sites: list[dict] = []
    cfg_functions: list[dict] = []
    modeled_returns = 0
    modeled_forward_gotos = 0
    assumed_error_gotos = 0
    for func in funcs:
        has_transfer = any(cursor.kind in _TRANSFERS
                           for cursor in func.cursor.walk_preorder())
        cfg = _function_cfg(func) if has_transfer else None
        if cfg is not None:
            cfg_functions.append(cfg)
        cfg_forward_offsets = set()
        if cfg is not None:
            blocks = {block["id"]: block for block in cfg["blocks"]}
            cfg_forward_offsets = {
                blocks[edge["source"]]["offset"]
                for edge in cfg["edges"]
                if edge["kind"] == "goto-forward"
            }
        _transitions, modeled = continuation_guards(func.cursor)
        modeled_returns += sum(
            1 for cursor in func.cursor.walk_preorder()
            if cursor.kind == cx.CursorKind.RETURN_STMT
            and (getattr(cursor.location, "offset", 0) or 0) in modeled)
        hardware_offsets = [
            getattr(call.cursor.location, "offset", 0) or 0
            for call in function_calls(func.cursor)
            if (mmio.is_mmio_read(call.name) or mmio.is_mmio_write(call.name)
                or mmio.is_mmio_rmw(call.name)
                or mmio.is_unsupported_register_access(call.name))
        ]
        params = {name for name, _ctype in func.params if name}

        def parameter_guarded_return(ancestors) -> bool:
            parent_if = next((parent for parent in reversed(ancestors)
                              if parent.kind == cx.CursorKind.IF_STMT), None)
            if parent_if is None:
                return True
            parts = list(parent_if.get_children())
            if not parts:
                return True
            condition = source_text(
                func.cursor.translation_unit, parts[0]).strip()
            if (re.search(r"->|\.|\[|\]", condition)
                    or re.search(r"\*\s*[A-Za-z_]\w*", condition)
                    or re.search(r"\b[A-Za-z_]\w*\s*\(", condition)):
                return False
            identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", condition))
            return all(name in params or name.isupper()
                       or name in {"true", "false"}
                       for name in identifiers)

        def loop_has_register_access(ancestors) -> bool:
            loop = next((parent for parent in reversed(ancestors)
                         if parent.kind in {cx.CursorKind.FOR_STMT,
                                            cx.CursorKind.WHILE_STMT,
                                            cx.CursorKind.DO_STMT}), None)
            if loop is None:
                return False
            return any(
                mmio.is_mmio_read(call.name) or mmio.is_mmio_write(call.name)
                or mmio.is_mmio_rmw(call.name)
                or mmio.is_unsupported_register_access(call.name)
                for call in function_calls(loop))

        def visit(cursor, ancestors):
            nonlocal assumed_error_gotos, modeled_forward_gotos
            offset = getattr(cursor.location, "offset", 0) or 0
            cursor_text = source_text(
                func.cursor.translation_unit, cursor).strip()
            if cursor.kind in {cx.CursorKind.GOTO_STMT,
                               cx.CursorKind.INDIRECT_GOTO_STMT}:
                label_match = re.fullmatch(r"goto\s+([A-Za-z_]\w*)\s*;?", cursor_text)
                label = label_match.group(1) if label_match else ""
                if offset in modeled and offset in cfg_forward_offsets:
                    modeled_forward_gotos += 1
                    modeled_sites.append(_site(
                        func, cursor, "goto",
                        "resolved forward goto represented by bounded CFG guard",
                        status="modeled"))
                elif (not cursor_text or "scoped_guard" in cursor_text
                        or "gpio_generic_lock" in cursor_text):
                    pass
                else:
                    sites.append(_site(
                        func, cursor, "goto",
                        "goto target/state merge is not represented by structured RIS"))
            elif cursor.kind == cx.CursorKind.CONTINUE_STMT:
                if loop_has_register_access(ancestors):
                    sites.append(_site(
                        func, cursor, "continue",
                        "loop continue requires CFG fixpoint semantics"))
            elif cursor.kind == cx.CursorKind.BREAK_STMT:
                nearest = next((parent.kind for parent in reversed(ancestors)
                                if parent.kind in {
                                    cx.CursorKind.SWITCH_STMT,
                                    cx.CursorKind.FOR_STMT,
                                    cx.CursorKind.WHILE_STMT,
                                    cx.CursorKind.DO_STMT}), None)
                if (nearest != cx.CursorKind.SWITCH_STMT
                        and loop_has_register_access(ancestors)
                        and cursor_text
                        and "scoped_guard" not in cursor_text
                        and "gpio_generic_lock" not in cursor_text):
                    sites.append(_site(
                        func, cursor, "break",
                        "loop break requires CFG fixpoint semantics"))
            elif (cursor.kind == cx.CursorKind.RETURN_STMT
                  and offset not in modeled
                  and parameter_guarded_return(ancestors)
                  and any(other > offset for other in hardware_offsets)):
                sites.append(_site(
                    func, cursor, "early_return",
                    "return affecting later register accesses is outside the simple continuation model"))
            for child in cursor.get_children():
                visit(child, ancestors + [cursor])

        visit(func.cursor, [])

    sites.sort(key=lambda site: (
        site["source"], site["line"], site["column"], site["offset"]))
    cfg_complete = all(item["complete"] for item in cfg_functions)
    return {
        "modeled_early_returns": modeled_returns,
        "modeled_forward_gotos": modeled_forward_gotos,
        "modeled_sites": modeled_sites,
        "assumed_framework_error_gotos": assumed_error_gotos,
        "unsupported": len(sites),
        "complete": not sites and cfg_complete,
        "sites": sites,
        "cfg": {
            "schema": 1,
            "representation": "source-statement-blocks",
            "functions": cfg_functions,
            "function_count": len(cfg_functions),
            "block_count": sum(len(item["blocks"])
                               for item in cfg_functions),
            "edge_count": sum(len(item["edges"])
                              for item in cfg_functions),
            "join_count": sum(len(item["join_blocks"])
                              for item in cfg_functions),
            "backedge_count": sum(len(item["backedges"])
                                  for item in cfg_functions),
            "complete": cfg_complete,
        },
    }
