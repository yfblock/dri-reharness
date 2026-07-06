"""LLM-assisted driver synthesis (plan Milestone 9).

Closed loop:
  RIS + dspec + bind + facts + scaffold
    -> LLM generates candidate
    -> compile / static / trace checks
    -> feedback normalized into a repair prompt
    -> LLM patches candidate
    -> repeat until accepted or blocked

Consolidated into one module (bundle assembly, verification feedback
extraction, repair-loop orchestration) per the plan's ownership rule. The LLM
is a pluggable client: a no-op stub by default (loop reports scaffold +
verification feedback without an API), or an external command via the
REHARNESS_LLM_CMD env var (prompt on stdin, candidate patch on stdout).
"""
from __future__ import annotations
import os
import re
import subprocess
from extractor.formal import walk_leaf_ops
from extractor.formalize import save_formal_text
from extractor.spec import default_bind
from extractor.metrics import score as score_fn
from generator import harness as G_harness
from generator import baremetal as G_baremetal
from generator import linux as G_linux

GENS = {"harness": G_harness, "baremetal": G_baremetal, "linux": G_linux}

_CONSTRAINTS_MD = """\
# Constraints (hard requirements for accepted output)

- Output must compile for the target backend (`{backend}`).
  - harness: `cc -Wall -o out candidate.c`
  - baremetal: `cc -ffreestanding -c candidate.c`
  - linux: kernel build system for the target tree
- No undefined identifiers. No TODOs in accepted output.
- Callback signatures must match the backend's API (see .bind).
- MMIO trace must match the RIS op sequence (op kind + register offset) where
  the backend is executable (harness).
- Do not invent registers not present in the `register_map` unless explicitly
  justified by `.facts`.
- Preserve function roles and effects from `.dspec`.
- Preserve register offsets and value expressions from `.ris`.
- Resource acquisition must follow `.facts` (devm_* / platform_get_*).
- Error paths must use the codes in `.facts` (e.g. -ENOMEM, PTR_ERR).
"""

_VERIFICATION_MD = """\
# Verification

1. Compile:
   $ cc -Wall -o {name}.harness.bin {name}.candidate.c
2. Run (harness only) and compare trace to {name}.ris:
   $ ./{name}.harness.bin
   Trace lines `[trace N] (R|W) 0xOFF = 0xVAL` must match the RIS op sequence
   (op kind + offset) for the entry module.
3. Static checks (run by `reharness synth --verify`):
   - every `ris` reference in .dspec resolves to a .ris module
   - every symbolic register is in register_map
   - every callback entry has a table binding
   - no TODOs in accepted candidate
"""


# ── bundle ───────────────────────────────────────────────────────────

def build_bundle(res, backend: str, outdir: str) -> str:
    """Assemble the LLM input bundle: RIS, dspec, bind, facts, scaffold.c,
    constraints.md, verification.md. Returns the bundle directory path."""
    os.makedirs(outdir, exist_ok=True)
    name = res.formal["driver"]
    bind = default_bind(res.device_spec, backend)

    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.{backend}.bind", bind.display())
    _w(outdir, f"{name}.facts", res.facts.display())
    scaffold = GENS[backend].generate(res.formal, res.device_spec, bind)
    _w(outdir, f"{name}.scaffold.c", scaffold)
    _w(outdir, "constraints.md", _CONSTRAINTS_MD.format(backend=backend))
    _w(outdir, "verification.md", _VERIFICATION_MD.format(name=name))
    _w(outdir, "score.txt", score_fn(res.device_spec, res.formal,
                                     res.warnings, res.facts).__repr__())
    return outdir


def _w(outdir: str, name: str, text: str):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")


# ── verification feedback ────────────────────────────────────────────

_CC_ERR_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.+)$")


def verify_candidate(candidate_path: str, res, backend: str) -> dict:
    """Run compile + static + trace checks; return structured feedback."""
    feedback: dict = {"compile": {"status": "unknown", "errors": []},
                      "semantic": {"status": "unknown", "issues": []},
                      "trace": {"status": "skipped"}}

    # --- compile ---
    if backend == "harness":
        binp = candidate_path + ".bin"
        r = subprocess.run(["cc", "-Wall", "-o", binp, candidate_path],
                           capture_output=True, text=True)
    elif backend == "baremetal":
        r = subprocess.run(["cc", "-ffreestanding", "-c", "-o", "/dev/null",
                            candidate_path], capture_output=True, text=True)
    else:  # linux — syntax-only with kernel-ish flags (not a real kernel build)
        r = subprocess.run(["cc", "-fsyntax-only", "-D__KERNEL__",
                            f"-I{os.path.dirname(candidate_path)}", candidate_path],
                           capture_output=True, text=True)
    errs = []
    for line in r.stderr.splitlines():
        m = _CC_ERR_RE.match(line)
        if m and ("error" in line.lower() or "warning" in line.lower()):
            errs.append({"line": m.group("line"), "message": m["msg"].strip()})
    feedback["compile"] = {"status": "passed" if r.returncode == 0 else "failed",
                           "errors": errs}

    # --- semantic / static checks ---
    issues: list[str] = []
    module_names = {m["name"] for m in res.formal["modules"]}
    reg_names = {r["name"] for r in res.formal.get("register_map", [])}
    for fn in res.device_spec.functions:
        if fn.ris_ref and fn.ris_ref not in module_names:
            issues.append(f"{fn.name}: ris ref {fn.ris_ref} not in .ris modules")
        if fn.is_callback_entry and not fn.callback_table:
            issues.append(f"{fn.name}: callback entry without table binding")
    # symbolic registers all in register_map
    for m in res.formal["modules"]:
        for o in walk_leaf_ops(m["ops"]):
            addr = (o.get("Read") or o.get("Write") or o.get("ReadModifyWrite") or {}).get("addr", {})
            if "Symbolic" in addr and addr["Symbolic"]["register"] not in reg_names:
                issues.append(f"symbolic register {addr['Symbolic']['register']} not in register_map")
    # no TODOs in candidate (accepted mode)
    with open(candidate_path, "r", encoding="utf-8", errors="replace") as fh:
        cand = fh.read()
    todos = cand.count("TODO")
    if todos:
        issues.append(f"{todos} TODO marker(s) remain in candidate")
    feedback["semantic"] = {"status": "passed" if not issues else "failed", "issues": issues}

    # --- trace check (harness only, after successful compile) ---
    if backend == "harness" and feedback["compile"]["status"] == "passed":
        binp = candidate_path + ".bin"
        out = subprocess.run([binp], capture_output=True, text=True).stdout
        traced = re.findall(r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)", out)
        traced_ops = [(k, int(off, 16)) for k, off in traced]
        regs = {r["name"]: r["offset"] for r in res.formal["register_map"]}
        # compare against the module the harness actually calls as main entry
        # (the probe-role function, else the first module)
        probe_fn = next((fn for fn in res.device_spec.functions if fn.role == "probe"), None)
        entry_name = probe_fn.ris_ref if probe_fn else res.formal["modules"][0]["name"]
        entry = next((m for m in res.formal["modules"] if m["name"] == entry_name), None)
        expected = []
        if entry:
            for o in walk_leaf_ops(entry["ops"]):
                if "Write" in o:
                    reg = o["Write"]["addr"]["Symbolic"]["register"]
                    expected.append(("W", regs.get(reg, 0)))
                elif "Read" in o:
                    reg = o["Read"]["addr"]["Symbolic"]["register"]
                    expected.append(("R", regs.get(reg, 0)))
        ok = traced_ops == expected
        feedback["trace"] = {"status": "passed" if ok else "failed",
                             "traced": traced_ops, "expected": expected}

    feedback["accepted"] = (feedback["compile"]["status"] == "passed"
                            and feedback["semantic"]["status"] == "passed"
                            and feedback["trace"]["status"] in ("passed", "skipped"))
    return feedback


def format_feedback(fb: dict) -> str:
    lines = ["verification feedback:"]
    lines.append(f"  compile:   {fb['compile']['status']}")
    for e in fb["compile"]["errors"][:8]:
        lines.append(f"    - line {e['line']}: {e['message']}")
    lines.append(f"  semantic:  {fb['semantic']['status']}")
    for i in fb["semantic"]["issues"][:8]:
        lines.append(f"    - {i}")
    lines.append(f"  trace:     {fb['trace']['status']}")
    lines.append(f"  accepted:  {fb['accepted']}")
    return "\n".join(lines)


# ── LLM client (pluggable) ───────────────────────────────────────────

class NullLLM:
    """No-op LLM: returns the candidate unchanged (loop reports feedback only)."""
    name = "null"
    def patch(self, system_prompt: str, candidate: str, feedback: str) -> str:
        return candidate  # no repair performed


class ShellLLM:
    """External LLM via a shell command (REHARNESS_LLM_CMD).
    The full prompt (system + feedback + candidate) is piped to stdin; the
    patched candidate is read from stdout."""
    name = "shell"
    def __init__(self, cmd: str):
        self.cmd = cmd
    def patch(self, system_prompt: str, candidate: str, feedback: str) -> str:
        full = f"{system_prompt}\n\n# Verification feedback\n{feedback}\n\n" \
               f"# Current candidate\n```c\n{candidate}\n```\n\n# Patched candidate (C only):\n"
        try:
            r = subprocess.run(self.cmd, shell=True, input=full,
                               capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                return _extract_code(r.stdout)
        except Exception:
            pass
        return candidate


def make_llm() -> object:
    cmd = os.environ.get("REHARNESS_LLM_CMD")
    return ShellLLM(cmd) if cmd else NullLLM()


def _extract_code(text: str) -> str:
    m = re.search(r"```c\n(.*?)```", text, re.S)
    return m.group(1) if m else text


_SYSTEM_PROMPT = """\
You are a driver-code repair agent. You are given:
- a backend-independent device spec (.dspec), register interaction sequence
  (.ris), backend binding (.bind), and source facts (.facts),
- a deterministic scaffold (candidate.c) that compiles imperfectly,
- structured verification feedback (compile errors, semantic issues, trace
  mismatch).

Produce a patched C candidate that satisfies the constraints in constraints.md.
Output ONLY the patched C source (in a ```c block). Do not add TODOs. Preserve
register offsets and value expressions from the RIS. Use .facts for resource
acquisition, error codes, and callback tables.
"""


# ── repair loop ──────────────────────────────────────────────────────

def run_repair_loop(res, backend: str, outdir: str, llm=None,
                    max_iters: int = 3) -> dict:
    """Scaffold -> verify -> (LLM patch) -> repeat until accepted or blocked.

    Without a real LLM (NullLLM), this still emits the scaffold + first
    verification feedback so the loop is fully runnable offline."""
    llm = llm or make_llm()
    bundle = build_bundle(res, backend, outdir)
    name = res.formal["driver"]
    cand_path = os.path.join(bundle, f"{name}.candidate.c")
    # start from the scaffold
    scaffold_path = os.path.join(bundle, f"{name}.scaffold.c")
    with open(scaffold_path, "r", encoding="utf-8") as fh:
        candidate = fh.read()
    with open(cand_path, "w", encoding="utf-8") as fh:
        fh.write(candidate)

    history: list[dict] = []
    for i in range(max_iters):
        fb = verify_candidate(cand_path, res, backend)
        history.append({"iter": i, "feedback": fb})
        with open(os.path.join(bundle, f"feedback.iter{i}.txt"), "w") as fh:
            fh.write(format_feedback(fb) + "\n")
        if fb["accepted"]:
            break
        if llm.name == "null":
            break  # no repair possible offline — report scaffold feedback
        patched = llm.patch(_SYSTEM_PROMPT, candidate, format_feedback(fb))
        if patched.strip() == candidate.strip():
            break  # LLM made no change — stop
        candidate = patched
        with open(cand_path, "w", encoding="utf-8") as fh:
            fh.write(candidate)

    final = history[-1]["feedback"]
    return {"bundle": bundle, "candidate": cand_path, "iters": len(history),
            "llm": llm.name, "accepted": final["accepted"],
            "final_feedback": final, "history": history}
