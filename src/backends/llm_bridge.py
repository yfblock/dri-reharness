# Unified LLM bridge for backend code generation.
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path

from backends.common import ris_op_digest, transaction_digest


class GeneratedCode(str):
    """String-compatible generated source with an optional file envelope."""

    def __new__(cls, code: str, *, files=None):
        value = super().__new__(cls, code)
        value.files = ([dict(item) for item in files]
                       if isinstance(files, list) else None)
        return value


def generated_file_entries(value: str, *, default_path: str) -> list[dict[str, str]]:
    """Return files for direct output while preserving string compatibility."""
    files = getattr(value, "files", None)
    if not isinstance(files, list) or not files:
        return [{"path": default_path, "code": str(value)}]

    entries = [dict(item) for item in files]
    primary = next(
        (item for item in entries
         if Path(str(item.get("path", ""))).suffix.lower()
         in {".c", ".cc", ".cpp", ".s", ".rs"}),
        entries[0],
    )
    primary["code"] = str(value)
    return entries


def load_prompt_template(backend: str) -> str:
    p = Path(__file__).resolve().parent / backend / "prompt.md"
    if not p.exists():
        raise FileNotFoundError("No prompt template: " + str(p))
    return p.read_text(encoding="utf-8")


def llm_available() -> bool:
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return False
    return True


def build_evidence_json(formal, device_spec, bind, facts=None,
                        module_names=None, function_names=None):
    """JSON half of the evidence package: device, registers, bind, functions,
    facts.  Module *ops* travel as text RIS (`_modules_ris_text`, injected at
    the prompt's __RIS__ placeholder); this JSON only lists module names so
    "every entry in evidence.modules" prompts still address real entries.
    `module_names`/`function_names` filter both to a chunk (None =
    everything, the single-shot behavior)."""
    regs = {}
    for r in formal.get("register_map", []):
        regs[r["name"]] = {"offset": r["offset"], "width": r.get("width", "B4")}
    modules = [mod["name"] for mod in formal.get("modules", [])
               if module_names is None or mod.get("name") in module_names]
    primitives = {}
    for p in bind.primitives:
        primitives[p.op + "(" + p.width + ")"] = p.concrete
    types_map = {t.abstract: t.concrete for t in bind.types}
    state_map = {s.abstract_path: s.concrete_expr for s in bind.state}
    callbacks_map = {c.table_field: c.function for c in bind.callbacks}
    evidence = {
        "driver": formal.get("driver", device_spec.name),
        "device_class": device_spec.cls,
        "registers": regs,
        "modules": modules,
        "bind": {"types": types_map, "primitives": primitives, "state": state_map, "callbacks": callbacks_map, "includes": getattr(bind, "includes", [])},
        "functions": [
            {
                "name": fn.name,
                "role": fn.role,
                "context": fn.context,
                "source": fn.source,
                "ris_ref": fn.ris_ref,
                "is_callback_entry": fn.is_callback_entry,
                "callback_table": fn.callback_table,
                "signature": {
                    "params": [
                        {"name": param.name, "type": param.type,
                         "from_expr": param.from_expr}
                        for param in fn.signature.params
                    ],
                    "return_type": fn.signature.return_type,
                },
            }
            for fn in getattr(device_spec, "functions", [])
            if function_names is None or fn.name in function_names
        ],
    }
    if facts:
        evidence["constants"] = dict(facts.constants) if facts.constants else {}
        structs = {}
        for s in (facts.structs or []):
            structs[s.name] = {f.name: f.ctype for f in s.fields}
        evidence["structs"] = structs
        evidence["resources"] = [
            {
                "name": resource.name,
                "type": getattr(resource, "type", None),
                "acquisition": resource.acquisition,
                "binds_to": resource.binds_to,
                **({"required": False}
                   if getattr(resource, "required", True) is False else {}),
                **({"failure_policy": resource.failure_policy}
                   if getattr(resource, "failure_policy", None) else {}),
            }
            for resource in (getattr(facts, "resources", None) or [])
        ]
        evidence["framework"] = {
            "callbacks": dict(getattr(facts, "callbacks", None) or {}),
            "callback_signatures": dict(
                getattr(facts, "callback_signatures", None) or {}),
            "error_paths": list(getattr(facts, "error_paths", None) or []),
            "helper_calls": list(getattr(facts, "helper_calls", None) or []),
            "source_snippets": dict(getattr(facts, "source_snippets", None) or {}),
        }
    return json.dumps(evidence, indent=2, sort_keys=True)


# ── RIS text evidence ──────────────────────────────────────────────────
# The module op dump is fed to the LLM as text RIS (op_display form), not
# JSON: the same ops cost ~1/4 of the JSON envelope (no per-op key
# repetition, no nested tagged unions).  Register/transaction ops carry
# their receipt digest inline (`digest=<16hex>`) so receipt emission keeps
# working unchanged — the oracle recomputes digests from res.formal, never
# from this text.

_RECEIPT_OP_KINDS = ("Read", "Write", "ReadModifyWrite")
_TX_OP_KINDS = ("TransactionRead", "TransactionWrite", "TransactionUpdate")


def _annotate_receipt_digests(ops):
    """Deep-copy ops, attaching `_receipt_digest` to receipt-bearing leaves.

    Works on copies so res.formal (and its saved formal.json) never gains
    the annotation key — the oracle's ris_op_digest would otherwise see it.
    """
    out = []
    for op in ops:
        op = copy.deepcopy(op)
        for kind in _RECEIPT_OP_KINDS:
            if kind in op:
                op[kind]["_receipt_digest"] = ris_op_digest(op)
                break
        else:
            tx = next((k for k in _TX_OP_KINDS if k in op), None)
            if tx:
                op[tx]["_receipt_digest"] = transaction_digest(op)
        cond = op.get("Cond")
        if cond:
            cond["then_ops"] = _annotate_receipt_digests(cond.get("then_ops", []))
            if cond.get("else_ops"):
                cond["else_ops"] = _annotate_receipt_digests(cond["else_ops"])
        seq = op.get("Seq")
        if seq:
            seq["ops"] = _annotate_receipt_digests(seq.get("ops", []))
        loop = op.get("Loop")
        if loop:
            if loop.get("guard_ops"):
                loop["guard_ops"] = _annotate_receipt_digests(loop["guard_ops"])
            loop["body"] = _annotate_receipt_digests(loop.get("body", []))
        out.append(op)
    return out


def _module_ris(mod) -> str:
    """Render one module's ops as text RIS with receipt digests."""
    from extractor.formal import op_display
    lines = ["module %s {" % mod.get("name", "?")]
    for op in _annotate_receipt_digests(mod.get("ops", [])):
        lines.append(op_display(op, indent=1))
    lines.append("}")
    return "\n".join(lines)


def _modules_ris_text(formal, module_names=None) -> str:
    """Text RIS for the selected modules; empty-note when a chunk has none."""
    selected = [mod for mod in formal.get("modules", [])
                if module_names is None or mod.get("name") in module_names]
    if not selected:
        return ("(none for this part — module function bodies are generated "
                "in separate parts)")
    return "\n".join(_module_ris(mod) for mod in selected)


def extract_code_block(text, lang=None):
    import re as _re
    if lang:
        pat = rf"```{_re.escape(lang)}\n([\s\S]*?)\n```"
    else:
        pat = r"```(?:\w*\n)?([\s\S]*?)\n```"
    m = _re.search(pat, text)
    if m: return m.group(1)
    return text.strip()



def call_llm(prompt, timeout=120, *, model=None, retries=3):
    """Call the bridge, retrying transient endpoint failures.

    Long part emissions are sometimes cut by the endpoint mid-stream
    ("unexpected EOF"); a bounded retry keeps chunked generation from
    losing a whole part to one dropped connection.
    """
    import time as _time
    from langchain_bridge import call_langchain, LangChainBridgeError
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return call_langchain(prompt, timeout=timeout, model=model)
        except LangChainBridgeError as exc:
            last = exc
            if attempt + 1 < max(1, retries):
                _time.sleep(5 * (attempt + 1))
    raise last


# Chunked generation: drivers whose rendered module RIS text exceeds this
# many characters are synthesized one chunk per LLM call (scaffold part +
# function-body parts), each part written as its own file.  Budgets are in
# RIS-text characters (~1/4 of the old JSON envelope, and ~4x denser in
# information per character).
_CHUNK_MIN_RIS_CHARS = 16_000
_CHUNK_RIS_BUDGET = 24_000

_SCAFFOLD_MODE = """

CHUNKED GENERATION — SCAFFOLD PART (part 0 of {n}).
The module function bodies are generated by separate calls into separate
files.  Emit ONLY the scaffold of the program:
- includes and macro stubs;
- the device private struct, COMPLETE for the whole program: a field for
  every entry in bind.state AND every private-state field the real upstream
  driver for this hardware carries (module bodies are generated by separate
  calls that cannot extend this struct, and they will reference
  conventional upstream field names).  Fields are plain C — no kernel-only
  annotations (__maybe_unused and friends), the userspace dialects do not
  define them.  Struct and helper identifiers must be valid C: a driver
  name like 8250_dw cannot start an identifier, so derive names such as
  dw8250_priv instead;
- stub implementations of every bind.primitives function the dialect needs;
- a prototype for every function in evidence.functions (exact names,
  parameter counts, and parameter types from evidence.functions[].signature);
  declare these prototypes `static`;
- the entry point the dialect requires: main() that instantiates the
  device and calls each evidence.functions entry in order with
  zero-initialized / plausible default arguments for userspace targets;
  module_init/module_exit with the registration contract for kernel
  targets.
Do NOT emit any module function body.  Do not emit TODO markers.
"""

_PART_MODE = """

CHUNKED GENERATION — PART {i} of {n}.
The scaffold below (includes, struct, primitive stubs, prototypes, entry
point) already exists in another file — never repeat, re-declare, or
redefine any of it, and do not emit includes.  Emit ONLY the bodies of
the functions for the modules in evidence.modules, exact module names,
in module order.  No main, no stubs, no struct definition.

Discipline rules for every function you emit (all parts are concatenated
into one translation unit, so these are compile gates):
- Declare a local variable for EVERY name assigned or read — every RIS
  name (including v_* and storage_* temporaries) and every intermediate
  you introduce yourself (v_tobool*, v_cmp*, ...) — before its first use;
  never reference an undeclared name.
- A register or field name from the evidence is data, not a C identifier:
  never use it bare as a variable or constant; map it to a declared local
  or a #define'd constant.
- If a RIS name is in a CALL position, declare it as a function pointer
  type before calling it; never call a non-function variable.
- Never apply << or >> to a pointer; cast to uintptr_t first.
- Reference struct members ONLY from the scaffold struct below, through
  the receiver variable named in the scaffold prototype; never invent
  struct members and never concatenate receiver and field names.
- Define each function exactly as its scaffold prototype declares it
  (same name, parameters, and `static` linkage).
- Any static helper you introduce must be forward-declared (or defined)
  above its first use, defined exactly once, and named with the suffix
  _p{i} so parts cannot collide.

EXISTING SCAFFOLD (context only, never re-emit):
```c
{scaffold}
```
"""


def _chunk_module_names(formal):
    """Group module names into chunks of roughly _CHUNK_RIS_BUDGET rendered
    RIS characters; None when the whole dump fits a single call."""
    mods = formal.get("modules", [])
    sizes = [len(_module_ris(mod)) for mod in mods]
    if sum(sizes) <= _CHUNK_MIN_RIS_CHARS:
        return None
    groups, cur, size = [], [], 0
    for mod, s in zip(mods, sizes):
        if cur and size + s > _CHUNK_RIS_BUDGET:
            groups.append(cur)
            cur, size = [], 0
        cur.append(mod.get("name", "?"))
        size += s
    if cur:
        groups.append(cur)
    return groups


def generate_via_llm(formal, device_spec, bind, *, backend, facts=None, bus_type=None, pci_identity=None, **kwargs):
    template = load_prompt_template(backend)
    driver = formal.get("driver", device_spec.name)

    def call(mode_note, module_names=None, function_names=None):
        ev = json.loads(build_evidence_json(
            formal, device_spec, bind, facts,
            module_names=module_names, function_names=function_names))
        # Inject bus type info into evidence JSON
        if bus_type or pci_identity:
            if bus_type:
                ev["bus_type"] = bus_type
            if pci_identity:
                if hasattr(pci_identity, "to_dict"):
                    ev["pci_identity"] = pci_identity.to_dict()
                elif isinstance(pci_identity, dict):
                    ev["pci_identity"] = pci_identity
                else:
                    ev["pci_identity"] = {"vendor": str(pci_identity)}
        prompt = (template + mode_note)
        prompt = prompt.replace("__EVIDENCE__",
                                json.dumps(ev, indent=2, sort_keys=True))
        prompt = prompt.replace("__RIS__", _modules_ris_text(formal, module_names))
        prompt = prompt.replace("__DRIVER_NAME__", driver)
        raw = call_llm(prompt, model=kwargs.get("model"))
        try:
            from langchain_bridge import _transcribe
            _transcribe(prompt, str(raw), kind=f"backend-{backend}",
                        meta={"driver": driver,
                              "repair_round": kwargs.get("repair_round", 0)})
        except Exception:
            pass
        from langchain_bridge import parse_model_response
        parsed = parse_model_response(raw)
        code = parsed["code"]
        if not code.strip():
            raise RuntimeError("LLM returned empty code")
        return code, parsed.get("files")

    groups = _chunk_module_names(formal)
    if groups is None:
        code, files = call("")
        return GeneratedCode(
            "/* Auto-generated by LLM (reharness) */\n" + code,
            files=files,
        )

    n = len(groups) + 1
    scaffold, _ = call(_SCAFFOLD_MODE.format(n=n), module_names=[])
    parts = [scaffold]
    files = [{"path": "part-00-scaffold.c", "language": "c",
              "code": scaffold}]
    for i, names in enumerate(groups, 1):
        part, _ = call(_PART_MODE.format(i=i, n=n, scaffold=scaffold),
                       module_names=names, function_names=names)
        parts.append(part)
        files.append({"path": "part-%02d.c" % i, "language": "c",
                      "code": part})
    # primary first: pipeline overwrites the primary entry's code with the
    # str() concatenation, compiles and attests it; parts land alongside
    files.insert(0, {"path": f"{backend}.c", "language": "c", "code": ""})
    concat = "\n\n".join("/* ---- part %02d of %02d ---- */\n%s" % (i, n - 1, p)
                         for i, p in enumerate(parts))
    return GeneratedCode(
        "/* Auto-generated by LLM (reharness), %d chunked parts */\n" % n
        + concat,
        files=files)
