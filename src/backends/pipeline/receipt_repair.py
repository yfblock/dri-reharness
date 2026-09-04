"""Receipt-completion repair pass.

The lowering oracle requires one well-formed receipt comment per required
register op (id, kind, digest from the generation contract), placed in its
owner function. Chunked generation drifts on exactly this contract:
accessor functions get stubbed without receipts, ids get renumbered,
digests become "unknown". This pass walks the required set, finds what
the file is missing (or duplicated), and asks the LLM to complete only
the affected parts — regex-guarded, compile-guarded, revertible.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .compile_repair import (
    _REPAIR_FENCE,
    _compile_probe,
    _part_bounds,
)


_VALID_RCPT = re.compile(
    r"REHARNESS_RIS_OP\s+id=\S+\s+kind=\S+\s+status=\S+\s+"
    r"digest=[0-9a-f]{16}\s*\*/")

_RECEIPT_REPAIR_PROMPT = """\
You are completing register-operation receipts in one part of a generated
C program (dialect: {dialect}). Machine verification requires every
register operation in the REQUIRED list to appear in this part exactly
once, inside its owner function, as a receipt comment followed by an AST
anchor that wraps the actual access statement.

REQUIRED operations (owner function, op id, kind, digest — copy verbatim):
{rows}

For each required operation:
1. Locate the owner function named `<module>` in this part. If it exists
   only as a prototype or as a stub with an empty/trivial body, replace
   or complete it with the real lowering taken from the MODULE RIS block
   below (match the scaffold prototype exactly, including `static` and
   parameter types; never emit a second definition of a function that is
   already fully defined in this part). If a full body already exists,
   only insert the missing receipt + anchor.
2. Immediately before the access statement implementing the op, insert
   exactly one comment in this form, copying id, kind and digest verbatim:
   /* REHARNESS_RIS_OP id=<op_id> kind=<kind> status=lowered digest=<digest> */
3. Immediately after that comment, emit the anchor label and put the
   access statement inside its braces:
   __rh_op_<op_id>: {{ <access statement> }}
   The anchor label is MANDATORY — a receipt comment without its
   __rh_op_<op_id>: anchor fails verification. Every required op you
   touch must end up with BOTH the comment and the anchor.
4. Each op id must appear exactly once in the whole program. If this part
   contains a receipt for one of the required ids in a function OTHER
   than its owner, delete that stray receipt comment (keep the statement).
5. Match the RIS access width inside the anchor braces: B8 means ONE
   64-bit access (readq/writeq or the dialect's 8-byte primitive) —
   never two 32-bit halves; B4 32-bit, B2 16-bit, B1 8-bit. If you find
   a required op whose anchor body uses the wrong width, replace the
   access with the correct-width primitive.

MODULE RIS for the owner functions (authoritative ops, source order):
{module_ris}

Other constraints:
- Preserve every existing `/* REHARNESS_RIS_OP ... */` and
  `/* REHARNESS_TRANSACTION_OP ... */` comment byte-for-byte, including
  ones carrying digest=unknown; do not add receipts for operations not
  in the REQUIRED list; do not renumber anything.
- Do not re-emit scaffold content (includes, struct definitions, macro
  stubs, prototypes of unrelated functions). Do not add TODO markers.
- The program is recompiled after your edit; it must still compile.

Return the COMPLETE fixed part in a single ```c fenced block, nothing else.

SCAFFOLD (context only, never re-emit):
```c
{scaffold}
```

PART TO FIX:
```c
{part}
```
"""


def _walk_register_ops(ops, module, out):
    """Collect (op_id, kind, digest, module) for register ops, mirroring
    llm_bridge._annotate_receipt_digests' traversal (Cond/Seq/Loop)."""
    from backends.common import ris_op_digest
    for op in ops or []:
        kind = next((k for k in ("Read", "Write", "ReadModifyWrite")
                     if k in op), None)
        if kind is not None and op[kind].get("op_id"):
            out.append((op[kind]["op_id"], kind, ris_op_digest(op), module))
        cond = op.get("Cond")
        if cond:
            _walk_register_ops(cond.get("then_ops", []), module, out)
            _walk_register_ops(cond.get("else_ops", []), module, out)
        seq = op.get("Seq")
        if seq:
            _walk_register_ops(seq.get("ops", []), module, out)
        loop = op.get("Loop")
        if loop:
            _walk_register_ops(loop.get("guard_ops", []), module, out)
            _walk_register_ops(loop.get("body", []), module, out)


_KIND_ALIAS = {"read": "Read", "r": "Read", "write": "Write", "w": "Write",
               "readmodifywrite": "ReadModifyWrite",
               "read_modify_write": "ReadModifyWrite", "rmw": "ReadModifyWrite"}


def _receipt_line_ok(part_text, op_id, kind, digest):
    """The op's receipt must appear exactly once, well-formed. Kind is
    alias-tolerant to mirror the oracle's _RECEIPT_KIND_ALIASES, so a
    receipt the oracle accepts (e.g. kind=read) is not "broken" here
    either — stricter matching made the repair add duplicates."""
    pat = re.compile(
        r"REHARNESS_RIS_OP\s+id=%s\s+kind=(\S+)\s+status=lowered\s+"
        r"digest=%s\s*\*/" % (re.escape(op_id), re.escape(digest)))
    hits = pat.findall(part_text)
    return sum(1 for k in hits
               if _KIND_ALIAS.get(k.lower(), k) == kind) == 1


def _dedup_receipts(text, rows):
    """Keep the last receipt comment per required op id, delete earlier
    copies (comment-only deletion — compile-safe). Returns (text, n)."""
    removed = 0
    for op_id, _kind, _digest, _module in rows:
        pat = re.compile(r"[ \t]*/\*\s*REHARNESS_RIS_OP\s+id=%s\s[^*]*"
                         r"\*/[ \t]*\n?" % re.escape(op_id))
        matches = list(pat.finditer(text))
        for m in matches[:-1]:
            text = text[:m.start()] + text[m.end():]
            removed += 1
    return text, removed


def _repair_receipts(backend, name, cpath, formal, entries,
                     ver_dir, root, tmp_dir):
    """Complete missing/duplicated required receipts in a generated file.

    Returns True when any splice survived the guards and the compile probe.
    """
    if os.environ.get("REHARNESS_LLM_REPAIR", "1") != "1":
        return False
    try:
        from backends.llm_bridge import (call_llm, _chunk_module_names,
                                         _module_ris)
    except Exception:
        return False
    original = Path(cpath).read_text(encoding="utf-8")
    # anchor-label normalization (mechanical, no LLM): op ids are always
    # `op_<n>`, so the canonical label is `__rh_op_op_<n>`.  Generation and
    # repair echoes frequently drop the inner `op_` (`__rh_op_2`); rewrite
    # digit-only labels before any contract check so a pure spelling drift
    # never burns an LLM round.  Idempotent — `__rh_op_op_2` does not match.
    text, norm_labels = re.subn(r"__rh_op_(?=\d)", "__rh_op_op_", original)
    if norm_labels:
        Path(cpath).write_text(text, encoding="utf-8")
    bounds = _part_bounds(text)
    rows = []
    for mod in formal.get("modules", []):
        _walk_register_ops(mod.get("ops", []), mod.get("name", "?"), rows)
    if not rows:
        return False
    # map each receipt id to the parts currently carrying it (diagnostics)
    have = {}
    for m in re.finditer(r"REHARNESS_RIS_OP\s+id=(\S+)", text):
        ln = text.count("\n", 0, m.start()) + 1
        idx = 0
        for lo, _s, _e, i in bounds:
            if ln >= lo:
                idx = i if i is not None else 0
        have.setdefault(m.group(1), []).append(idx)
    # Receipt comments satisfy the text reconciliation, but the AST-leaf
    # oracle additionally needs the anchor statement (`__rh_op_<id>: { ... }`)
    # next to every lowered access; generation sometimes emits the comment
    # without the anchor (8250 baremetal: 21 receipts, 0 anchors).  Linux is
    # exempt: its plan legitimately blocks ops that can never anchor, and a
    # hard anchor guard there would veto good receipt fixes wholesale.
    need_anchor = backend in ("harness", "baremetal")
    broken = [r for r in rows
              if len(re.findall(r"REHARNESS_RIS_OP\s+id=%s\s" % re.escape(r[0]),
                                text)) != 1
              or not _receipt_line_ok(text, r[0], r[1], r[2])
              or (need_anchor
                  and not re.search(r"__rh_op_%s\b" % re.escape(r[0]), text))]
    if not broken:
        return False
    # route each broken op to the part that owns (or should own) it
    groups = _chunk_module_names(formal)
    mod_to_part = {}
    if groups:
        for gi, names in enumerate(groups, 1):
            for n in names:
                mod_to_part[n] = gi
    part_of = {}
    for lo, start, end, i in bounds:
        if i is not None:
            part_of[i] = (lo, start, end)
    mods_by_name = {m.get("name"): m for m in formal.get("modules", [])}
    by_part = {}
    for op_id, kind, digest, module in broken:
        idx = None
        # prefer the part that already DEFINES the owner function (an
        # opening brace follows the parameter list — prototypes do not)
        for i in sorted(part_of):
            lo, start, end = part_of[i]
            if re.search(r"\b%s\s*\([^;{]*\)\s*\{" % re.escape(module),
                         text[start:end]):
                idx = i
                break
        if idx is None:
            idx = mod_to_part.get(module, 0)
        by_part.setdefault(idx, []).append((op_id, kind, digest, module))
    dialect = {"harness": "userspace program with main()",
               "baremetal": "freestanding library (no libc)",
               "linux": "Linux kernel module"}[backend]
    scaffold_text = ("(single-file program)" if len(bounds) < 2
                     else text[bounds[0][1]:bounds[0][2]])
    log = []
    if norm_labels:
        log.append("normalized %d anchor label(s) __rh_op_<n> -> "
                   "__rh_op_op_<n>" % norm_labels)
    changed = False
    changed_parts = []  # (part index, [(op_id, kind, digest, module)])
    for idx in sorted(by_part, reverse=True):
        if idx not in part_of:
            continue
        lo, start, end = part_of[idx]
        part = text[start:end]
        if len(part) > 100_000:
            log.append("part %d too large to echo (%d chars)"
                       % (idx, len(part)))
            continue
        sel = sorted(set(by_part[idx]))
        ris_blocks = []
        for _op_id, _kind, _digest, module in sel:
            mod = mods_by_name.get(module)
            if mod is not None:
                ris_blocks.append(_module_ris(mod))
        rows_txt = "\n".join(
            "- owner=%s id=%s kind=%s digest=%s" % (m, o, k, d)
            for o, k, d, m in sel)
        prompt = _RECEIPT_REPAIR_PROMPT.format(
            dialect=dialect, rows=rows_txt,
            module_ris="\n".join(ris_blocks) or "(none)",
            scaffold=scaffold_text if idx != 0 else "(this IS the scaffold part)",
            part=part)
        fixed = None
        for _attempt in range(2):
            attempt_prompt = prompt
            if _attempt:
                attempt_prompt = (prompt + "\nREMINDER: every listed id "
                                  "must appear exactly once with its exact "
                                  "digest; return the full part.")
            try:
                raw = call_llm(attempt_prompt, timeout=120)
            except Exception as exc:
                log.append("part %d: llm failed: %s" % (idx, exc))
                break
            m = _REPAIR_FENCE.search(raw)
            new = m.group(1) if m else None
            if new is None and (_VALID_RCPT.search(raw)
                                or "REHARNESS_RIS_OP" not in part):
                stripped = re.sub(r"^```(?:c|C)?|```$", "", raw,
                                  flags=re.M).strip()
                if stripped.count("{") >= 3:
                    new = stripped
            if new is None:
                log.append("part %d: no fenced block" % idx)
                continue
            new = re.sub(r"__rh_op_(?=\d)", "__rh_op_op_", new)
            if "TODO" in new or len(new) < 0.5 * len(part):
                log.append("part %d: rejected (len %d<%d)"
                           % (idx, len(new), len(part)))
                continue
            if len(_VALID_RCPT.findall(new)) < len(
                    _VALID_RCPT.findall(part)):
                log.append("part %d: rejected (dropped valid receipts)"
                           % idx)
                continue
            if not all(_receipt_line_ok(new, o, k, d)
                       for o, k, d, _m in sel):
                log.append("part %d: rejected (required receipt absent "
                           "or malformed)" % idx)
                continue
            if need_anchor and not all(
                    re.search(r"__rh_op_%s\b" % re.escape(o), new)
                    for o, k, d, _m in sel):
                log.append("part %d: rejected (anchor statements absent)"
                           % idx)
                continue
            fixed = new
            break
        if fixed is None:
            continue
        text = text[:start] + fixed.rstrip("\n") + "\n\n" + text[end:]
        changed = True
        changed_parts.append((idx, sel))
        log.append("part %d: receipts completed (%d -> %d chars)"
                   % (idx, len(part), len(fixed)))
    # Deterministic duplicate suppression runs unconditionally — before the
    # early return.  At e1000 scale (12 parts, 30KB each) flash rejects
    # every part echo, but the generated text still carries hundreds of
    # required-id duplicate receipts; pure deletion needs no LLM and must
    # not be gated on a successful splice.
    text, removed = _dedup_receipts(text, rows)
    if removed:
        log.append("dedup: removed %d duplicate receipt comment(s)" % removed)
        Path(cpath).write_text(text, encoding="utf-8")
    if not changed:
        (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
            ("\n".join(log) + "\n") if log else "(no changes)\n",
            encoding="utf-8")
        return removed > 0
    Path(cpath).write_text(text, encoding="utf-8")
    # splice outputs can re-introduce duplicates the LLM was told to
    # preserve — collapse them again before the compile gate
    text, removed2 = _dedup_receipts(text, rows)
    if removed2:
        log.append("dedup: removed %d duplicate receipt comment(s)"
                   % removed2)
        Path(cpath).write_text(text, encoding="utf-8")
    # the edit must not break the build; on probe failure retry the same
    # parts with the compiler diagnostics appended, then revert as a
    # last resort
    probe = _compile_probe(backend, cpath, name, root, tmp_dir)
    for retry in range(2):
        if probe.returncode == 0:
            break
        diags = (probe.stderr if backend != "linux"
                 else probe.stdout + "\n" + probe.stderr)
        log.append("probe failed after receipt repair (retry %d): %s"
                   % (retry, diags.strip()[-1500:]))
        fixed_any = False
        retry_bounds = _part_bounds(text)
        # re-ask the parts that grew in this pass, with diagnostics
        for prev_idx, sel in changed_parts:
            span = next(((s, e) for _l, s, e, _i in retry_bounds
                         if _i == prev_idx), None)
            if span is None:
                continue
            lo2, end2 = span
            part2 = text[lo2:end2]
            prompt2 = _RECEIPT_REPAIR_PROMPT.format(
                dialect=dialect,
                rows="\n".join("- owner=%s id=%s kind=%s digest=%s"
                               % (m, o, k, d) for o, k, d, m in sel),
                module_ris="(see constraints above — receipts already "
                           "inserted, fix ONLY the compile errors)",
                scaffold=scaffold_text if prev_idx != 0
                else "(this IS the scaffold part)",
                part=part2) + (
                "\nCOMPILER DIAGNOSTICS (fix these, keep every receipt):\n"
                + diags[-6000:]
                + "\nReturn the COMPLETE fixed part in one ```c fenced block.")
            try:
                raw2 = call_llm(prompt2, timeout=120)
            except Exception as exc:
                log.append("part %d retry: llm failed: %s"
                           % (prev_idx, exc))
                continue
            m2 = _REPAIR_FENCE.search(raw2)
            new2 = m2.group(1) if m2 else None
            if new2 is None and _VALID_RCPT.search(raw2):
                stripped = re.sub(r"^```(?:c|C)?|```$", "", raw2,
                                  flags=re.M).strip()
                if stripped.count("{") >= 3:
                    new2 = stripped
            if new2 is None or "TODO" in new2 or len(new2) < 0.5 * len(part2):
                continue
            if len(_VALID_RCPT.findall(new2)) < len(
                    _VALID_RCPT.findall(part2)):
                continue
            if not all(_receipt_line_ok(new2, o, k, d)
                       for o, k, d, _m in sel):
                continue
            if need_anchor and not all(
                    re.search(r"__rh_op_%s\b" % re.escape(o), new2)
                    for o, k, d, _m in sel):
                continue
            text = text[:lo2] + new2.rstrip("\n") + "\n\n" + text[end2:]
            Path(cpath).write_text(text, encoding="utf-8")
            fixed_any = True
            log.append("part %d: compile retry accepted (%d -> %d chars)"
                       % (prev_idx, len(part2), len(new2)))
        if not fixed_any:
            break
        probe = _compile_probe(backend, cpath, name, root, tmp_dir)
    if probe.returncode != 0:
        # revert the splices, but keep the dedup pass: deleting duplicate
        # comment lines cannot break a build that compiled before.
        orig_dedup, _dropped = _dedup_receipts(original, rows)
        Path(cpath).write_text(orig_dedup, encoding="utf-8")
        log.append("reverted: compile probe failed after receipt repair "
                   "(dedup retained)")
        (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
            "\n".join(log) + "\n", encoding="utf-8")
        return _dropped > 0
    # persist part files + entries so downstream file consumers stay fresh
    # (recompute bounds: earlier splices shifted offsets)
    final_bounds = _part_bounds(text)
    for lo, start, end, i in final_bounds:
        if i is None:
            continue
        part_path = ("part-00-scaffold.c" if i == 0 else "part-%02d.c" % i)
        p = Path(cpath).parent / part_path
        if p.exists():
            p.write_text(text[start:end], encoding="utf-8")
        if entries:
            for e in entries:
                if e.get("path") == part_path:
                    e["code"] = text[start:end]
    (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
        "\n".join(log) + "\n", encoding="utf-8")
    return True
