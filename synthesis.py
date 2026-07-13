"""Bundle assembly for LLM synthesis.

Assembles the reharness extraction output (.ris/.dspec/.bind/.facts/score.txt)
into a directory for the TS+Pi synthesizer to consume. The LLM synthesis itself
is handled by tools/synth.mjs (TypeScript, Pi agent core SDK); the compile/QEMU/
trace iteration loop is handled by run_e2e.sh (shell). This module is purely
the Python-side bundle packager.
"""
from __future__ import annotations
import os
from extractor.formalize import save_formal_text
from extractor.spec import default_bind
from extractor.metrics import score as score_fn


def build_bundle(res, backend: str, outdir: str) -> str:
    """Assemble the LLM input bundle: .ris, .dspec, .bind, .facts, score.txt.
    Returns the bundle directory path."""
    os.makedirs(outdir, exist_ok=True)
    name = res.formal["driver"]
    bind = default_bind(res.device_spec, backend)

    save_formal_text(res.formal, os.path.join(outdir, f"{name}.ris"))
    _w(outdir, f"{name}.dspec", res.device_spec.display())
    _w(outdir, f"{name}.{backend}.bind", bind.display())
    _w(outdir, f"{name}.facts", res.facts.display())
    _w(outdir, "score.txt", score_fn(res.device_spec, res.formal,
                                     res.warnings, res.facts).__repr__())
    return outdir


def _w(outdir: str, name: str, text: str):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
