"""Bundle assembly for LLM synthesis.

Assembles the reharness extraction output (.ris/.dspec/DeviceSpec JSON/
.bind/.facts/score.txt)
into a directory for the TS+Pi synthesizer to consume. The LLM synthesis itself
is handled by ``tools/pi/synth.mjs``; the compile/QEMU/trace iteration loop is
handled by ``scripts/e2e/run_e2e.sh``. This module is purely the Python-side
bundle packager.
"""
from __future__ import annotations
import json
import os
from extractor.formalize import save_formal_text
from extractor.spec import default_bind, device_spec_to_dict
from extractor.metrics import score as score_fn
from verification.backend_lowering_oracle import build_generation_contract


def build_bundle(res, backend: str, outdir: str) -> str:
    """Assemble the LLM input bundle: RIS, DeviceSpec, bind, facts, score.
    Returns the bundle directory path."""
    os.makedirs(outdir, exist_ok=True)
    name = res.formal["driver"]
    bind = default_bind(res.device_spec, backend)
    generation_contract = build_generation_contract(res.formal)
    generation_contract["synthesis_readiness"] = score_fn(
        res.device_spec, res.formal, res.warnings, res.facts)

    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.formal.json", json.dumps(
        res.formal, indent=2, sort_keys=True))
    _w(outdir, "generation-contract.json", json.dumps(
        generation_contract, indent=2, sort_keys=True))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.device-spec.json", json.dumps(
        device_spec_to_dict(res.device_spec), indent=2, sort_keys=True))
    _w(outdir, f"{name}.{backend}.bind", bind.display())
    _w(outdir, f"{name}.facts", res.facts.display())
    _w(outdir, "score.txt", generation_contract[
        "synthesis_readiness"].__repr__())
    return outdir


def _w(outdir: str, name: str, text: str):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
