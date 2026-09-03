"""Multi-backend generation + full verification pipeline.

Shared multi-backend generation pipeline so that the
V2 experiment graph and the ``gen`` CLI share one implementation:

    run_backend_pipeline(res, outdir, source, model=None)
      → oracle fan-out ×5 (gpio/sdhci/virtio/w1c/transaction)
      → backend fan-out ×4 (linux/harness/baremetal/rust_baremetal)
        each: LLM 生成 → 编译 → 逐项验证
      → write artifacts (generated/ + verify/)

Returns the aggregate result dict consumed by V2's finalize and by the
``gen`` CLI's exit-code logic.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

def _is_subsequence(sub, seq) -> bool:
    it = iter(seq)
    return all(item in it for item in sub)


def _pipeline_success(readiness: dict) -> bool:
    """Return success only when every generated backend is strictly ready."""
    return all(readiness.get(key) is True for key in (
        "backend_harness_ready", "backend_bare_metal_ready",
        "backend_linux_ready"))


_ORACLE_FILES = {
    "gpio": "gpio-mmio-source-oracle.json",
    "sdhci": "sdhci-accessor-oracle.json",
    "virtio": "virtio-state-oracle.json",
    "w1c": "w1c-drain-oracle.json",
    "transaction": "transaction-ir-oracle.json",
}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _transaction_source_paths(source: str | os.PathLike[str]) -> list[str]:
    descriptor = Path(source).resolve()
    if descriptor.suffix.lower() != ".json":
        return [str(descriptor)]
    try:
        document = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [str(descriptor)]
    entries = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return [str(descriptor)]
    return [str((descriptor.parent / item).resolve())
            for item in entries if isinstance(item, str) and item.strip()]


# ── compile-repair loop (generic feedback: the compiler is ground truth) ─

# Marker is matched unanchored: a repair splice can eat the blank lines
# between parts and glue the marker onto the previous part's last line
# (`...#endif */ /* ---- part 01 of 03 ---- */`), and an anchored pattern
# would then silently lose the whole part for routing.
_PART_MARKER = re.compile(r"/\* ---- part (\d+) of \d+ ---- \*/")
_ERR_LINE = re.compile(r"^[^\s:]+:(\d+):\d+: (?:fatal )?error", re.M)
_UNDEF_REF = re.compile(r"undefined reference to [`'`](\w+)", re.M)
_MODPOST_UNDEF = re.compile(r'modpost: "(\w+)".*undefined', re.M)
_REPAIR_FENCE = re.compile(r"```(?:c|C)?\s*\n(.*?)```", re.S)
# max part size worth one LLM echo round (~28k output tokens at 32k cap)
_REPAIR_ECHO_LIMIT = 100_000

_REPAIR_PROMPT = """\
You are fixing compile errors in one part of a generated C program
(dialect: {dialect}). The compiler diagnostics refer to the CONCATENATED
program; this part spans concatenated lines {lo}..{hi}. Fix ONLY the
compile errors attributable to this part. Typical fixes:
- declare a missing local (any v_* name or temporary you introduced)
  before its first use, with a plausible type;
- add a forward declaration for a static helper before its first use;
- make a prototype and its definition match (name, parameters, static);
- in userspace parts, drop kernel-only annotations (__maybe_unused,
  __init, ...) and undefined kernel macros;
- never start an identifier with a digit;
- keep `break`/`continue` inside a loop (else restructure with a flag);
- never shift a pointer; cast to uintptr_t first;
- reference only types defined by the includes or the scaffold struct;
- if an external function has no prototype in scope, do not call it:
  replace the call with its effect on locals (or a no-op statement)
  unless the scaffold declares it;
- when a struct-field initializer type-mismatches (e.g. a callback table
  entry), change the function's signature/return type to the field's
  type, not the initializer.

Hard constraints — the receipt chain is machine-verified after you:
- Preserve every `/* REHARNESS_RIS_OP ... */` and
  `/* REHARNESS_TRANSACTION_OP ... */` comment, every `__rh_op_<id>:` label,
  every register access statement, op id and digest EXACTLY as given.
- Do not delete functions, statements or receipts; add no TODO.
- Do not re-emit scaffold content (includes, struct, stubs, prototypes).

Return the COMPLETE fixed part in a single ```c fenced block, nothing else.

SCAFFOLD (context only, never re-emit):
```c
{scaffold}
```

PART TO FIX:
```c
{part}
```

COMPILER DIAGNOSTICS (concatenated-program line numbers):
```
{errors}
```
"""


def _compile_probe(backend, cpath, name, root, tmp_dir):
    """Syntax probe mirroring the real build of `backend` (no products)."""
    try:
        if backend == "baremetal":
            return subprocess.run(
                ["cc", "-ffreestanding", "-Wall", "-fsyntax-only", cpath],
                capture_output=True, text=True)
        if backend == "linux":
            module_name = name.replace("-", "_")
            build_dir = os.path.abspath(
                os.path.join(tmp_dir, "linux-module-probe"))
            os.makedirs(build_dir, exist_ok=True)
            shutil.copyfile(cpath, os.path.join(build_dir, f"{module_name}.c"))
            Path(build_dir, "Makefile").write_text(
                f"obj-m += {module_name}.o\n", encoding="utf-8")
            kernel_dir = os.environ.get(
                "KERNELDIR", os.fspath(root / "platform" / "kernel" / "build"))
            return subprocess.run(
                ["make", "-C", kernel_dir, f"M={build_dir}", "modules"],
                capture_output=True, text=True)
        return subprocess.run(
            ["cc", "-o", os.path.join(tmp_dir, "harness-probe.bin"), cpath],
            capture_output=True, text=True)
    except Exception as exc:  # a probe failure must never kill the pipeline
        return subprocess.CompletedProcess([], 1, "", str(exc))


def _part_bounds(text):
    """[(lo_line, content_start, content_end, index)] per part marker.

    A file without chunk markers is one part with index 0."""
    marks = list(_PART_MARKER.finditer(text))
    if not marks:
        return [(1, 0, len(text), 0)]
    out = []
    for i, m in enumerate(marks):
        start = text.index("\n", m.start()) + 1
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        lo = text.count("\n", 0, m.start()) + 1
        out.append((lo, start, end, int(m.group(1))))
    return out


def _receipt_count(s):
    return s.count("REHARNESS_RIS_OP") + s.count("REHARNESS_TRANSACTION_OP")


def _repair_compile(backend, name, cpath, entries, ver_dir, root, tmp_dir):
    """Compile-error feedback loop for one generated backend file.

    Generic: the compiler is ground truth.  Only failing parts are
    rewritten (bounded echo), the receipt chain is pinned in the prompt
    and guarded after, so a repair round never regenerates the driver.
    Verification downstream runs on the repaired text.  Returns True when
    a repair attempt changed the file.
    """
    if os.environ.get("REHARNESS_LLM_REPAIR", "1") != "1":
        return False
    try:
        from backends.llm_bridge import call_llm
    except Exception:
        return False
    rounds = int(os.environ.get("REHARNESS_LLM_REPAIR_ROUNDS", "3"))
    dialect = {"harness": "userspace program with main()",
               "baremetal": "freestanding library (no libc)",
               "linux": "Linux kernel module"}[backend]
    log = []
    repaired = False
    for _round in range(rounds):
        r = _compile_probe(backend, cpath, name, root, tmp_dir)
        if r.returncode == 0:
            log.append("round %d: clean" % _round)
            break
        diags = r.stderr if backend != "linux" else r.stdout + "\n" + r.stderr
        text = Path(cpath).read_text(encoding="utf-8")
        bounds = _part_bounds(text)
        bmap = {b[3]: b for b in bounds}
        errs_by_part = {}
        for m in _ERR_LINE.finditer(diags):
            ln = int(m.group(1))
            idx = 0
            for lo, _s, _e, i in bounds:
                if ln >= lo:
                    idx = i
            line_end = diags.find("\n", m.end())
            errs_by_part.setdefault(idx, []).append(
                diags[m.start():line_end if line_end != -1 else len(diags)])
        # modpost (kernel) and ld (userspace) both report missing symbols
        # without file:line; the scaffold part owns the prototypes/entry
        # point, so missing or renamed definitions are routed there
        undef = sorted(set(_UNDEF_REF.findall(diags))
                       | set(_MODPOST_UNDEF.findall(diags)))
        if not errs_by_part:
            if undef:
                errs_by_part[0] = [
                    "undefined reference to `%s' — define it (static stub "
                    "{ return 0; }), rename the reference to the existing "
                    "definition, or remove the call\n" % s
                    for s in undef]
                log.append("round %d: %d undefined refs -> scaffold part"
                           % (_round, len(undef)))
            else:
                log.append("round %d: no per-line errors parsed" % _round)
                break
        elif undef:
            errs_by_part.setdefault(0, []).extend(
                "undefined reference to `%s' — define it (static stub "
                "{ return 0; }), rename the reference to the existing "
                "definition, or remove the call\n" % s for s in undef)
        scaffold_text = ("(single-file program)" if len(bounds) < 2
                         else text[bounds[0][1]:bounds[0][2]])
        # fix parts highest-offset-first so earlier splices stay valid
        todo = sorted(errs_by_part, reverse=True)[:4]
        changed = False
        for idx in todo:
            lo, start, end, _i = bmap[idx]
            part = text[start:end]
            if len(part) > _REPAIR_ECHO_LIMIT:
                log.append("part %d too large to echo (%d chars)"
                           % (idx, len(part)))
                continue
            base_prompt = _REPAIR_PROMPT.format(
                dialect=dialect, lo=lo,
                hi=text.count("\n", 0, end) + 1,
                scaffold=(scaffold_text if idx != 0
                          else "(this IS the scaffold part)"),
                part=part, errors="".join(errs_by_part[idx])[:8000])
            new = None
            for attempt in (0, 1):  # one guarded retry: temp is 0, so
                # the retry prompt must differ to produce a different fix
                extra = ""
                if attempt:
                    extra = ("\nREMINDER: your previous attempt was rejected"
                             " (it lost a receipt comment, dropped the fence,"
                             " or was not usable). Preserve every receipt"
                             " comment and every __rh_op_ anchor byte-for-"
                             "byte; change ONLY what the diagnostics require;"
                             " answer inside one ```c fence.\n")
                try:
                    fixed = call_llm(base_prompt + extra)
                except Exception as exc:
                    log.append("part %d: llm failed: %s" % (idx, exc))
                    break
                m = _REPAIR_FENCE.search(fixed)
                if m:
                    cand = m.group(1)
                else:
                    # unfenced but C-looking answer (model dropped the
                    # fence): accept the whole response when it carries
                    # receipts
                    stripped = fixed.strip()
                    if ("REHARNESS_RIS_OP" in stripped or part.count(
                            "REHARNESS_RIS_OP") == 0) and stripped.count(
                                "{") >= 3:
                        cand = stripped
                        log.append("part %d: unfenced response accepted"
                                   % idx)
                    else:
                        log.append("part %d: attempt %d: no fenced block"
                                   % (idx, attempt))
                        continue
                if (_receipt_count(cand) < _receipt_count(part)
                        or len(cand) < 0.6 * len(part) or "TODO" in cand):
                    log.append("part %d: attempt %d rejected (receipts "
                               "%d<%d, len %d/%d)"
                               % (idx, attempt, _receipt_count(cand),
                                  _receipt_count(part), len(cand), len(part)))
                    continue
                new = cand
                break
            if new is None:
                continue
            # keep the two blank lines before the next part marker — the
            # old slice being replaced consumed them, and without them
            # the marker glues onto this part's last line
            text = text[:start] + new.rstrip("\n") + "\n\n" + text[end:]
            changed = True
            repaired = True
            log.append("part %d: repaired (%d -> %d chars)"
                       % (idx, len(part), len(new)))
            part_path = ("part-00-scaffold.c" if idx == 0
                         else "part-%02d.c" % idx)
            p = Path(cpath).parent / part_path
            if p.exists():
                p.write_text(new, encoding="utf-8")
            if entries:
                for e in entries:
                    if e.get("path") == part_path:
                        e["code"] = new
        if not changed:
            log.append("round %d: nothing repaired" % _round)
            break
        Path(cpath).write_text(text, encoding="utf-8")
    if repaired:
        (Path(ver_dir) / f"{backend}.repair.log").write_text(
            "\n".join(log) + "\n", encoding="utf-8")
    return repaired


# ── receipt repair ─────────────────────────────────────────────────────
# The lowering oracle requires one well-formed receipt comment per required
# register op (id, kind, digest from the generation contract), placed in
# its owner function. Chunked generation drifts on exactly this contract:
# accessor functions get stubbed without receipts, ids get renumbered,
# digests become "unknown". This pass walks the required set, finds what
# the file is missing (or duplicated), and asks the LLM to complete only
# the affected parts — regex-guarded, compile-guarded, revertible.

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
    text = original
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
    if not changed:
        (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
            ("\n".join(log) + "\n") if log else "(no changes)\n",
            encoding="utf-8")
        return False
    Path(cpath).write_text(text, encoding="utf-8")
    # deterministic duplicate suppression before the compile gate
    text, removed = _dedup_receipts(text, rows)
    if removed:
        log.append("dedup: removed %d duplicate receipt comment(s)" % removed)
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
        Path(cpath).write_text(original, encoding="utf-8")
        log.append("reverted: compile probe failed after receipt repair")
        (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
            "\n".join(log) + "\n", encoding="utf-8")
        return False
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


def run_backend_pipeline(res: Any, outdir: str, source: str,
                         model: Any = None) -> dict[str, Any]:
    """Run the full multi-backend generation + verification pipeline.

    ``res`` is the extraction result (formal / device_spec / facts / stats /
    warnings).  ``model`` is an optional deterministic-model injection for
    offline tests.  Returns ``{"accepted", "status", "output_dir",
    "return_code", "gen_results", "backend_results"}``.
    """
    root = _repository_root()
    for entry in (str(root / "src"), str(root / "qa"),
                  str(root / "qa" / "verification")):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    from backends.registry import list_backends
    from backends.llm_bridge import generated_file_entries
    from backends.linux.oracles.gpio_mmio_source_oracle import \
        verify_gpio_mmio_source_differential
    from backends.linux.oracles.linux_registration_ast_oracle import (
        linux_kbuild_compile_context, verify_linux_registration_ast)
    from backends.oracles.sdhci_accessor_oracle import \
        verify_sdhci_accessor_source_contract
    from backends.oracles.transaction_ir_oracle import verify_transaction_sources
    from backends.oracles.virtio_state_oracle import verify_virtio_state_contract
    from backends.oracles.w1c_drain_oracle import (verify_w1c_drain_contract,
                                                   verify_w1c_drain_runtime)
    from verification.subsystem_callback_oracle import verify_subsystem_callbacks
    from verification.backend_lowering_oracle import (
        build_generation_contract, verify_backend_lowering)
    from verification.backend_lowering_plan import verify_backend_lowering_plan
    from verification.generated_c_ast_oracle import verify_generated_c_ast
    from verification.subsystem_callback_oracle import _eval
    from extractor.formalize import save_formal_text
    from extractor.metrics import (_computed_is_lowerable, count_clang_errors,
                                   driver_metrics, format_metrics, format_score,
                                   score as score_fn)
    from extractor.spec import default_bind, device_spec_to_dict
    from backends.subsystem_runner import (subsystem_callback_plan,
                                           w1c_drain_plan)

    name = res.formal["driver"]
    gen_dir = os.path.join(outdir, "generated")
    ver_dir = os.path.join(outdir, "verify")
    tmp_dir = os.path.join(ver_dir, "tmp")
    for d in (outdir, gen_dir, ver_dir, tmp_dir):
        os.makedirs(d, exist_ok=True)

    def _w(base: str, path: str, text: str) -> None:
        with open(os.path.join(base, path), "w", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")

    def _ast_error_report(oracle: str, generated: str, exc: Exception,
                          **extra: Any) -> dict:
        report = {
            "schema": 1, "oracle": oracle, "driver": name,
            "complete": False, "generated": generated,
            "verifier_error": type(exc).__name__, "message": str(exc),
            **extra,
        }
        if os.path.isfile(generated):
            import hashlib
            with open(generated, "rb") as handle:
                report["generated_sha256"] = hashlib.sha256(
                    handle.read()).hexdigest()
        return report

    def _lowering_plan_fields(plan: dict | None) -> dict:
        return {
            "backend_lowering_plan_accounting_complete": bool(
                plan and plan.get("accounting_complete")),
            "backend_lowering_plan_classification_complete": bool(
                plan and plan.get("classification_complete")),
            "backend_lowering_plan_lowering_complete": bool(
                plan and plan.get("lowering_complete")),
            "backend_lowering_plan_authorization_complete": bool(
                plan and plan.get("authorization_complete")),
            "backend_lowering_plan_reconciliation_complete": bool(
                plan and plan.get("reconciliation_complete")),
            "backend_lowering_plan_definition_alignment_complete": bool(
                plan and plan.get("definition_alignment_complete")),
            "backend_lowering_plan_runtime_complete": bool(
                plan and plan.get("runtime_complete")),
            "backend_lowering_plan_strict_complete": bool(
                plan and plan.get("strict_complete")),
            "backend_lowering_plan": plan,
        }

    # -- prepare ---------------------------------------------------------------
    generation_contract = build_generation_contract(res.formal)
    generation_contract["synthesis_readiness"] = score_fn(
        res.device_spec, res.formal, res.warnings, res.facts)
    device_spec_document = device_spec_to_dict(res.device_spec)
    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.formal.json", json.dumps(
        res.formal, indent=2, sort_keys=True))
    _w(outdir, "generation-contract.json", json.dumps(
        generation_contract, indent=2, sort_keys=True))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.device-spec.json", json.dumps(
        device_spec_document, indent=2, sort_keys=True))
    _w(outdir, f"{name}.facts", res.facts.display())
    _w(ver_dir, "analysis.json", json.dumps({
        "stats": res.stats, "warnings": res.warnings,
    }, indent=2, sort_keys=True))

    # -- oracle fan-out ×5 -----------------------------------------------------
    def _compute_oracle(kind: str) -> dict:
        if kind == "gpio":
            return verify_gpio_mmio_source_differential(res.formal,
                                                        res.device_spec)
        if kind == "sdhci":
            return verify_sdhci_accessor_source_contract(res.formal)
        if kind == "virtio":
            return verify_virtio_state_contract(res.formal)
        if kind == "w1c":
            return verify_w1c_drain_contract(res.formal, res.device_spec)
        if kind == "transaction":
            return verify_transaction_sources(
                res.formal, _transaction_source_paths(source))
        raise ValueError(f"unknown oracle kind: {kind}")

    reports: dict[str, Any] = {}
    for kind in _ORACLE_FILES:
        report = _compute_oracle(kind)
        _w(ver_dir, _ORACLE_FILES[kind], json.dumps(
            report, indent=2, sort_keys=True))
        reports[kind] = report

    # -- backend fan-out ×4 ----------------------------------------------------
    gens = {backend: mod for backend, mod in list_backends().items()
            if backend in ("harness", "baremetal", "linux")}
    backend_order = list(gens)
    gen_results: dict[str, Any] = {}
    backend_results: dict[str, str] = {}
    bind_displays: dict[str, str] = {}

    def _run_one_backend(backend: str, gen: Any) -> None:
        bind = default_bind(res.device_spec, backend)
        gen_kwargs = {}
        for kw in getattr(gen, "GEN_KWARGS", []):
            if kw == "facts":
                gen_kwargs["facts"] = res.facts
            elif kw == "pci_identity":
                gen_kwargs["pci_identity"] = getattr(res, "pci_identity", None)
            elif kw == "registrar":
                gen_kwargs["registrar"] = getattr(res, "registrar", None)
        if model is not None:
            gen_kwargs["model"] = model
        code = gen.generate(res.formal, res.device_spec, bind, **gen_kwargs)
        entries = generated_file_entries(code, default_path=f"{backend}.c")
        if getattr(code, "files", None):
            generated_root = Path(gen_dir) / backend
            for entry in entries:
                destination = generated_root / entry["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(entry["code"], encoding="utf-8")
            primary = next(
                (entry for entry in entries
                 if Path(entry["path"]).suffix.lower() in {
                     ".c", ".cc", ".cpp", ".s"}),
                entries[0],
            )
            cpath = str(generated_root / primary["path"])
        else:
            cpath = os.path.join(gen_dir, f"{backend}.c")
            with open(cpath, "w", encoding="utf-8") as fh:
                fh.write(code)
        # generic compile-repair round: probe-compile, feed diagnostics
        # back to the LLM for the failing parts only, re-probe; the
        # verification below then runs on the repaired file
        try:
            _repair_compile(
                backend, name, cpath,
                entries if getattr(code, "files", None) else None,
                ver_dir, root, tmp_dir)
        except Exception as exc:
            (Path(ver_dir) / f"{backend}.repair.log").write_text(
                f"repair crashed: {exc}\n", encoding="utf-8")
        # receipt-completion round: fill missing/duplicated required
        # receipts (id/kind/digest from the contract) via the LLM
        try:
            _repair_receipts(
                backend, name, cpath, res.formal,
                entries if getattr(code, "files", None) else None,
                ver_dir, root, tmp_dir)
        except Exception as exc:
            (Path(ver_dir) / f"{backend}.receipt-repair.log").write_text(
                f"receipt repair crashed: {exc}\n", encoding="utf-8")
        # repairs rewrite files on disk; refresh the in-memory entries so
        # verification audits the same text the compiler saw (the primary
        # entry otherwise still carries the pre-repair concatenation)
        if entries:
            for entry in entries:
                for cand in (Path(gen_dir) / backend
                             / str(entry.get("path", "")),
                             Path(gen_dir) / str(entry.get("path", ""))):
                    if cand.is_file():
                        entry["code"] = cand.read_text(encoding="utf-8")
                        break
        generated_text = "\n\n".join(entry["code"] for entry in entries)
        has_todo = "TODO" in generated_text
        unsupported = "REHARNESS_UNSUPPORTED" in generated_text
        lowering = verify_backend_lowering(res.formal, generated_text)
        _w(ver_dir, f"{backend}-lowering.json", json.dumps(
            lowering, indent=2, sort_keys=True))
        lowering_plan = verify_backend_lowering_plan(
            res.formal, generation_contract, backend,
            device_spec=(res.device_spec if backend == "linux" else None),
            lowering_report=lowering)
        _w(ver_dir, f"{backend}-lowering-plan.json", json.dumps(
            lowering_plan, indent=2, sort_keys=True))
        ast_leaf = None
        if backend in {"harness", "baremetal"}:
            try:
                ast_leaf = verify_generated_c_ast(generation_contract, cpath)
            except Exception as exc:
                ast_leaf = _ast_error_report(
                    "generated-c-ast-leaf-v1", cpath, exc)
            _w(ver_dir, f"{backend}-ast-leaf.json", json.dumps(
                ast_leaf, indent=2, sort_keys=True))
        linux_registration_ast = None
        gr: dict = {
            "has_todo": has_todo, "unsupported": unsupported,
            "backend_lowering_complete": lowering["complete"],
            "backend_lowering": lowering,
            "backend_lowering_plan_required": True,
            **_lowering_plan_fields(lowering_plan),
            "backend_ast_leaf_required": backend in {
                "harness", "baremetal", "linux"},
            "backend_ast_leaf_complete": bool(
                ast_leaf and ast_leaf.get("complete")),
            "backend_ast_leaf": ast_leaf,
            "linux_ast_leaf_required": backend == "linux",
            "linux_ast_leaf_complete": False,
            "linux_ast_leaf": None,
            "linux_registration_ast_required": backend == "linux",
            "linux_registration_ast_complete": False,
            "linux_registration_ast": None,
            **reports["gpio"], **reports["sdhci"], **reports["virtio"],
            "transaction_ir_oracle_complete": reports["transaction"][
                "complete"],
            "transaction_ir_oracle": reports["transaction"],
            **reports["w1c"],
        }

        if backend == "harness":
            binp = os.path.join(tmp_dir, "harness.bin")
            r = subprocess.run(["cc", "-o", binp, cpath],
                               capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            if r.returncode == 0:
                executed = subprocess.run([binp], capture_output=True,
                                          text=True)
                out = executed.stdout
                _w(ver_dir, "harness.trace.txt", out)
                gr.update(verify_subsystem_callbacks(
                    res.formal, res.device_spec, out))
                gr.update(verify_w1c_drain_runtime(
                    res.formal, res.device_spec, out))
                regs = {r2["name"]: r2["offset"]
                        for r2 in res.formal["register_map"]}
                probe_fn = next((fn for fn in res.device_spec.functions
                                 if fn.role == "probe"), None)
                modules = res.formal["modules"]
                entry = (probe_fn.ris_ref if probe_fn else
                         modules[0]["name"] if modules else None)
                mod = next((m for m in modules if m["name"] == entry), None)
                expected = []
                untraceable = False

                def trace_offset(addr):
                    if "Symbolic" in addr:
                        return regs.get(addr["Symbolic"]["register"])
                    if "Fixed" in addr:
                        return addr["Fixed"]["offset"]
                    if ("Computed" in addr
                            and _computed_is_lowerable(addr["Computed"])):
                        return _eval(addr["Computed"], {})
                    return None

                if mod:
                    for o in mod["ops"]:
                        if "Write" in o:
                            addr = o["Write"]["addr"]
                            off = trace_offset(addr)
                            if off is None:
                                untraceable = True
                            else:
                                expected.append(("W", off))
                        elif "Read" in o:
                            addr = o["Read"]["addr"]
                            off = trace_offset(addr)
                            if off is None:
                                untraceable = True
                            else:
                                expected.append(("R", off))
                traced = [(k, int(off, 16)) for k, off in
                          re.findall(
                              r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)",
                              out)]
                gr["trace_passed"] = (
                    executed.returncode == 0 and not untraceable
                    and _is_subsequence(expected, traced))
                result_line = (
                    f"compiled+ran ({out.count('[trace')} ops, "
                    f"trace {'✓' if gr['trace_passed'] else '✗'})")
            else:
                _w(ver_dir, "harness.compile.log", r.stderr)
                result_line = \
                    "compile FAILED (see verify/harness.compile.log)"
        elif backend == "baremetal":
            r = subprocess.run(
                ["cc", "-ffreestanding", "-Wall", "-c", "-o", "/dev/null",
                 cpath], capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            plan = subsystem_callback_plan(res.formal, res.device_spec)
            drain_plan = w1c_drain_plan(res.formal, res.device_spec)
            if r.returncode == 0 and (plan or drain_plan):
                oracle_bin = os.path.join(tmp_dir, "baremetal-oracle.bin")
                oracle_compile = subprocess.run(
                    ["cc", "-DREHARNESS_BAREMETAL_ORACLE", "-Wall",
                     "-Wextra", "-o", oracle_bin, cpath],
                    capture_output=True, text=True)
                if oracle_compile.returncode == 0:
                    oracle_run = subprocess.run([oracle_bin],
                                                capture_output=True, text=True)
                    _w(ver_dir, "baremetal.callback.trace.txt",
                       oracle_run.stdout)
                    gr.update(verify_subsystem_callbacks(
                        res.formal, res.device_spec, oracle_run.stdout))
                    gr.update(verify_w1c_drain_runtime(
                        res.formal, res.device_spec, oracle_run.stdout))
                    if oracle_run.returncode != 0:
                        gr["subsystem_callback_oracle_passed"] = False
                        gr["subsystem_callback_oracle_errors"].append(
                            f"host oracle exited {oracle_run.returncode}")
                else:
                    gr.update({
                        "subsystem_callbacks_total": res.stats.get(
                            "synthetic_subsystem_functions", 0),
                        "subsystem_callbacks_executed": 0,
                        "subsystem_callback_oracle_passed": False,
                        "subsystem_callback_oracle_errors": [
                            oracle_compile.stderr[-2000:]],
                    })
            else:
                gr.update(verify_subsystem_callbacks(
                    res.formal, res.device_spec, ""))
            if r.returncode != 0:
                _w(ver_dir, "baremetal.compile.log", r.stderr)
            result_line = ("compiles freestanding" if r.returncode == 0
                           else "compile FAILED")
        elif backend == "rust_baremetal":
            gr["compiled"] = False
            result_line = "rust backend: generated (compile TBD)"
        else:  # linux — real out-of-tree Kbuild module compilation
            module_name = name.replace("-", "_")
            build_dir = os.path.abspath(os.path.join(tmp_dir, "linux-module"))
            os.makedirs(build_dir, exist_ok=True)
            module_c = os.path.join(build_dir, f"{module_name}.c")
            shutil.copyfile(cpath, module_c)
            makefile = f"obj-m += {module_name}.o\n"
            if res.device_spec.cls == "sdhci":
                makefile += "ccflags-y += -I$(srctree)/drivers/mmc/host\n"
            _w(build_dir, "Makefile", makefile)
            kernel_dir = os.environ.get(
                "KERNELDIR", os.fspath(root / "platform" / "kernel" / "build"))
            r = subprocess.run(
                ["make", "-C", kernel_dir, f"M={build_dir}", "modules"],
                capture_output=True, text=True)
            gr["compiled"] = r.returncode == 0
            gr["syntax_ok"] = r.returncode == 0
            if r.returncode != 0:
                _w(ver_dir, "linux.compile.log", r.stdout + "\n" + r.stderr)
            required_ids = set(
                lowering_plan.get("strict_eligible_op_ids") or [])
            kbuild_cmd = os.path.join(build_dir, f".{module_name}.o.cmd")
            if r.returncode == 0:
                linux_compile_context = None
                try:
                    clang_args, linux_compile_context = \
                        linux_kbuild_compile_context(
                            Path(module_c), Path(kbuild_cmd))
                    ast_leaf = verify_generated_c_ast(
                        generation_contract, module_c,
                        clang_args=clang_args,
                        required_op_ids=required_ids,
                        compile_context=linux_compile_context)
                except Exception as exc:
                    ast_leaf = _ast_error_report(
                        "generated-c-ast-leaf-v1", module_c, exc,
                        required_op_ids=sorted(required_ids),
                        required_ast_ops=len(required_ids),
                        compile_context=linux_compile_context)
                try:
                    linux_registration_ast = verify_linux_registration_ast(
                        generation_contract, res.device_spec, module_c,
                        lowering_plan, kbuild_cmd=kbuild_cmd)
                except Exception as exc:
                    linux_registration_ast = _ast_error_report(
                        "linux-registration-ast-v1", module_c, exc,
                        runtime_registered_op_ids=[], operations=[])
            else:
                failure = RuntimeError(
                    "Linux Kbuild did not succeed; AST evidence unavailable")
                ast_leaf = _ast_error_report(
                    "generated-c-ast-leaf-v1", module_c, failure,
                    required_op_ids=sorted(required_ids),
                    required_ast_ops=len(required_ids))
                linux_registration_ast = _ast_error_report(
                    "linux-registration-ast-v1", module_c, failure,
                    runtime_registered_op_ids=[], operations=[])

            _w(ver_dir, "linux-ast-leaf.json", json.dumps(
                ast_leaf, indent=2, sort_keys=True))
            _w(ver_dir, "linux-registration-ast.json", json.dumps(
                linux_registration_ast, indent=2, sort_keys=True))
            lowering_plan = verify_backend_lowering_plan(
                res.formal, generation_contract, "linux",
                device_spec=res.device_spec,
                lowering_report=lowering,
                runtime_attestation=linux_registration_ast,
                ast_leaf_report=ast_leaf,
                generated_artifact=module_c,
                kbuild_cmd=kbuild_cmd)
            _w(ver_dir, "linux-lowering-plan.json", json.dumps(
                lowering_plan, indent=2, sort_keys=True))
            gr.update(_lowering_plan_fields(lowering_plan))
            gr.update({
                "backend_ast_leaf_complete": bool(
                    ast_leaf and ast_leaf.get("complete")),
                "backend_ast_leaf": ast_leaf,
                "linux_ast_leaf_complete": bool(
                    ast_leaf and ast_leaf.get("complete")),
                "linux_ast_leaf": ast_leaf,
                "linux_registration_ast_complete": bool(
                    linux_registration_ast
                    and linux_registration_ast.get("complete")),
                "linux_registration_ast": linux_registration_ast,
            })
            result_line = ("kernel module compiles" if r.returncode == 0
                           else "kernel compile FAILED")
        gen_results[backend] = gr
        backend_results[backend] = result_line
        bind_displays[backend] = bind.display()

    for backend in backend_order:
        _run_one_backend(backend, gens[backend])

    # -- write artifacts --------------------------------------------------------
    _w(ver_dir, "analysis.json", json.dumps({
        "stats": res.stats,
        "warnings": res.warnings,
        "generation": gen_results,
    }, indent=2, sort_keys=True))
    _w(outdir, f"{name}.bind", "\n\n".join(
        bind_displays[backend] for backend in backend_order))
    _w(ver_dir, "metrics.txt", format_metrics(
        driver_metrics(res.formal,
                       n_clang_diag=count_clang_errors(res.warnings))))
    sc = score_fn(res.device_spec, res.formal, res.warnings, res.facts,
                  gen_results=gen_results)
    _w(ver_dir, "score.txt", format_score(sc))

    return_code = 0 if _pipeline_success(sc) else 1
    return {
        "accepted": return_code == 0,
        "status": "accepted" if return_code == 0 else "failed",
        "output_dir": str(outdir),
        "return_code": return_code,
        "gen_results": gen_results,
        "backend_results": backend_results,
        "score": sc,
    }
