# Unified LLM bridge for backend code generation.
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

def load_prompt_template(backend: str) -> str:
    p = Path(__file__).resolve().parent / backend / "prompt.md"
    if not p.exists():
        raise FileNotFoundError("No prompt template: " + str(p))
    return p.read_text(encoding="utf-8")


def llm_available() -> bool:
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
        elif "TransactionWrite" in op:
            o = op["TransactionWrite"]
            out.append({"kind": "tx_write", "op_id": o.get("op_id", "?"),
                        "transport": o.get("transport", "regmap"),
                        "target": _expr_str(o.get("target")),
                        "selector": _expr_str(o.get("selector")),
                        "payload": _expr_str(o.get("value"))})
        elif "TransactionUpdate" in op:
            o = op["TransactionUpdate"]
            out.append({"kind": "tx_update", "op_id": o.get("op_id", "?"),
                        "transport": o.get("transport", "regmap"),
                        "target": _expr_str(o.get("target")),
                        "selector": _expr_str(o.get("selector")),
                        "mask": _expr_str(o.get("update_mask")),
                        "value": _expr_str(o.get("update_value"))})
        elif "TransactionRead" in op:
            o = op["TransactionRead"]
            out.append({"kind": "tx_read", "op_id": o.get("op_id", "?"),
                        "transport": o.get("transport", "regmap"),
                        "target": _expr_str(o.get("target")),
                        "selector": _expr_str(o.get("selector"))})
        elif "StateRead" in op:
            o = op["StateRead"]
            out.append({"kind": "state_read", "op_id": o.get("op_id", "?"),
                        "field": o.get("field", ""),
                        "var": o.get("var", "state_value"),
                        "width": o.get("width", "Unknown")})
        elif "StateWrite" in op:
            o = op["StateWrite"]
            out.append({"kind": "state_write", "op_id": o.get("op_id", "?"),
                        "field": o.get("field", ""),
                        "value": _expr_str(o.get("value")),
                        "width": o.get("width", "Unknown")})
        elif "OutputWrite" in op:
            o = op["OutputWrite"]
            out.append({"kind": "output_write", "op_id": o.get("op_id", "?"),
                        "target": o.get("target", ""),
                        "value": _expr_str(o.get("value"))})
        elif "ValueBind" in op:
            o = op["ValueBind"]
            out.append({"kind": "value_bind", "op_id": o.get("op_id", "?"),
                        "var": o.get("var", ""),
                        "value": _expr_str(o.get("value"))})
        elif "Delay" in op:
            o = op["Delay"]
            out.append({"kind": "delay", "op_id": o.get("op_id", "?"),
                        "cycles": _expr_str(o.get("cycles"))})
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
    from extractor.formal import expr_to_c
    return expr_to_c(expr)


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
    root = Path(__file__).resolve().parents[2]
    pi_script = root / "tools" / "pi" / "pi_synth.sh"
    if pi_script.exists():
        r = subprocess.run([str(pi_script)], input=prompt,
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError("pi_synth failed: " + r.stderr)
        return r.stdout
    raise RuntimeError("No Pi bridge found at tools/pi/pi_synth.sh")


def generate_via_llm(formal, device_spec, bind, *, backend, facts=None, bus_type=None, pci_identity=None, **kwargs):
    template = load_prompt_template(backend)
    evidence = build_evidence_json(formal, device_spec, bind, facts)
    # Inject bus type info into evidence JSON
    if bus_type or pci_identity:
        ev = json.loads(evidence)
        if bus_type:
            ev["bus_type"] = bus_type
        if pci_identity:
            if hasattr(pci_identity, "to_dict"):
                ev["pci_identity"] = pci_identity.to_dict()
            elif isinstance(pci_identity, dict):
                ev["pci_identity"] = pci_identity
            else:
                ev["pci_identity"] = {"vendor": str(pci_identity)}
        evidence = json.dumps(ev, indent=2, sort_keys=True)
    prompt = template.replace("__EVIDENCE__", evidence)
    prompt = prompt.replace("__DRIVER_NAME__", formal.get("driver", device_spec.name))
    raw = call_llm(prompt)
    lang_map = {"harness": "c", "baremetal": "c", "linux": "c", "rust_baremetal": "rust"}
    code = extract_code_block(raw, lang_map.get(backend))
    if not code.strip(): raise RuntimeError("LLM returned empty code")
    return "/* Auto-generated by LLM (reharness) */\n" + code
