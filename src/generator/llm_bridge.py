# Unified LLM bridge for backend code generation.
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip(chr(39) + chr(34))
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt_template(backend: str) -> str:
    p = _PROMPT_DIR / (backend + ".md")
    if not p.exists():
        raise FileNotFoundError("No prompt template: " + str(p))
    return p.read_text(encoding="utf-8")


def llm_available() -> bool:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"):
        return True
    root = Path(__file__).resolve().parents[2]
    pi_script = root / "tools" / "pi" / "pi_synth.sh"
    if pi_script.exists() and os.access(pi_script, os.X_OK):
        return True
    return False


def build_evidence_json(formal, device_spec, bind, facts=None):
    regs = {}
    for r in formal.get("register_map", []):
        regs[r["name"]] = {"offset": r["offset"], "width": r.get("width", "B4")}
    modules = []
    for mod in formal.get("modules", []):
        modules.append({"name": mod["name"], "ops": _simplify_ops(mod.get("ops", []))})
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
    }
    if facts:
        evidence["constants"] = dict(facts.constants) if facts.constants else {}
        structs = {}
        for s in (facts.structs or []):
            structs[s.name] = {f.name: f.ctype for f in s.fields}
        evidence["structs"] = structs
    return json.dumps(evidence, indent=2, sort_keys=True)


def _simplify_ops(ops, depth=0):
    if depth > 10: return [{"error": "max depth"}]
    out = []
    for op in ops:
        if "Read" in op:
            o = op["Read"]
            out.append({"kind": "read", "op_id": o.get("op_id", "?"), "addr": _addr_str(o.get("addr", {})), "width": o.get("width", "B4"), "var": o.get("var", "")})
        elif "Write" in op:
            o = op["Write"]
            out.append({"kind": "write", "op_id": o.get("op_id", "?"), "addr": _addr_str(o.get("addr", {})), "value": _expr_str(o.get("value"))})
        elif "ReadModifyWrite" in op:
            o = op["ReadModifyWrite"]
            out.append({"kind": "rmw", "op_id": o.get("op_id", "?"), "addr": _addr_str(o.get("addr", {})), "transform": _expr_str(o.get("transform"))})
        elif "Cond" in op:
            c = op["Cond"]
            out.append({"kind": "cond", "guard": _expr_str(c.get("guard")), "then": _simplify_ops(c.get("then_ops", []), depth + 1), "else": _simplify_ops(c.get("else_ops", []), depth + 1) if c.get("else_ops") else []})
        elif "Loop" in op:
            l = op["Loop"]
            out.append({"kind": "loop", "guard": _expr_str(l.get("guard")), "body": _simplify_ops(l.get("body", []), depth + 1), "bounded": l.get("bounded", False)})
        elif "Return" in op:
            out.append({"kind": "return", "value": _expr_str(op["Return"].get("value"))})
    return out


def _addr_str(addr):
    if isinstance(addr, dict):
        if "Fixed" in addr:
            return "base + 0x" + format(addr["Fixed"].get("offset", 0), "x")
        if "Symbolic" in addr:
            return "base + " + addr["Symbolic"].get("register", "?")
    return str(addr)


def _expr_str(expr):
    if expr is None: return "0"
    if isinstance(expr, dict):
        if "Const" in expr: return "0x" + format(expr["Const"], "x")
        if "Var" in expr: return expr["Var"]
        if "BinOp" in expr:
            b = expr["BinOp"]
            return "(" + _expr_str(b.get("left")) + " " + str(b.get("op")) + " " + _expr_str(b.get("right")) + ")"
    return str(expr)


def extract_code_block(text, lang=None):
    import re as _re
    bt = chr(96) * 3
    if lang:
        pat = bt + lang + chr(92) + "n([\s\S]*?)" + chr(92) + "n" + bt
    else:
        pat = bt + "(?:\w*" + chr(92) + "n)?([\s\S]*?)" + chr(92) + "n" + bt
    m = _re.search(pat, text)
    if m: return m.group(1)
    return text.strip()


def call_llm(prompt, timeout=120):
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key: return _call_openai(prompt, api_key, timeout)
    root = Path(__file__).resolve().parents[2]
    pi_script = root / "tools" / "pi" / "pi_synth.sh"
    if pi_script.exists(): return _call_pi_synth(prompt, pi_script, timeout)
    raise RuntimeError("No LLM backend available (set OPENAI_API_KEY)")


def _call_openai(prompt, api_key, timeout):
    model = os.environ.get("REHARNESS_LLM_MODEL", "gpt-4o")
    payload = json.dumps({"model": model, "messages": [{"role": "system", "content": "Generate only code."}, {"role": "user", "content": prompt}], "temperature": 0.2})
    r = subprocess.run(["curl", "-s", "-X", "POST", (lambda b: b + "/chat/completions" if b.endswith("/v1") else b.rstrip("/") + "/v1/chat/completions")(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")), "-H", "Content-Type: application/json", "-H", "Authorization: Bearer " + api_key, "-d", "@-", "--max-time", str(timeout)], input=payload, capture_output=True, text=True, timeout=timeout + 10)
    resp = json.loads(r.stdout)
    if "error" in resp: raise RuntimeError(str(resp["error"]))
    return resp["choices"][0]["message"]["content"]


def _call_pi_synth(prompt, script, timeout):
    r = subprocess.run([str(script)], input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0: raise RuntimeError("pi_synth failed: " + r.stderr)
    return r.stdout


def generate_via_llm(formal, device_spec, bind, *, backend, facts=None, **kwargs):
    template = load_prompt_template(backend)
    evidence = build_evidence_json(formal, device_spec, bind, facts)
    prompt = template.replace("__EVIDENCE__", evidence)
    prompt = prompt.replace("__DRIVER_NAME__", formal.get("driver", device_spec.name))
    raw = call_llm(prompt)
    lang_map = {"harness": "c", "baremetal": "c", "linux": "c", "rust_baremetal": "rust"}
    code = extract_code_block(raw, lang_map.get(backend))
    if not code.strip(): raise RuntimeError("LLM returned empty code")
    return "/* Auto-generated by LLM (reharness) */\n" + code