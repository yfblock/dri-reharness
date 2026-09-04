"""Generic compile-repair loop: the compiler is ground truth.

Probe-compile a generated backend file, route diagnostics to the failing
parts, and ask the LLM to rewrite only those parts with the receipt chain
pinned in the prompt and guarded after each splice.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

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
