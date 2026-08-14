"""Bundle assembly for LLM synthesis.

Assembles the reharness extraction output into a directory for the Pi synthesizer.
Pi communication layer has been extracted to pi_bridge.py; this module re-exports for compat.
"""
from __future__ import annotations
import json
import os

from extractor.formalize import save_formal_text
from extractor.spec import default_bind, device_spec_to_dict
from extractor.metrics import score as score_fn
from verification.backend_lowering_oracle import build_generation_contract

from pi_bridge import (
    PiRequest,
    PiResponse,
    SubprocessPiBridge,
    parse_pi_response,
    render_pi_prompt,
    run_pi_synth,
)


def build_bundle(res, backend, outdir):
    os.makedirs(outdir, exist_ok=True)
    name = res.formal['driver']
    bind = default_bind(res.device_spec, backend)
    gc = build_generation_contract(res.formal)
    gc['synthesis_readiness'] = score_fn(res.device_spec, res.formal, res.warnings, res.facts)
    save_formal_text(res.formal, os.path.join(outdir, name + '.ris'))
    _w(outdir, name + '.formal.json', json.dumps(res.formal, indent=2, sort_keys=True))
    _w(outdir, 'generation-contract.json', json.dumps(gc, indent=2, sort_keys=True))
    _w(outdir, name + '.dspec', res.device_spec.display())
    _w(outdir, name + '.device-spec.json', json.dumps(device_spec_to_dict(res.device_spec), indent=2, sort_keys=True))
    _w(outdir, name + '.' + backend + '.bind', bind.display())
    _w(outdir, name + '.facts', res.facts.display())
    _w(outdir, 'score.txt', gc['synthesis_readiness'].__repr__())
    return outdir


def _w(outdir, name, text):
    with open(os.path.join(outdir, name), 'w', encoding='utf-8') as fh:
        fh.write(text.rstrip() + chr(10))
