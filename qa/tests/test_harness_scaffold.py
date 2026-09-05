"""Mechanical harness scaffold (backends.harness.scaffold).

The scaffold is prepended as part 00 of every harness-backend generation
call; these tests pin the properties the prompt and the repair rounds
rely on: syntax-clean C, one definition per bind primitive, register
defines from the formal's register map, self-tracing primitives, and
untraced raw readers.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from backends.common import make_freestanding_bind
from backends.harness.scaffold import emit_scaffold, summary
from extractor.spec import BindSpec


def _bind(device: str = "edu") -> BindSpec:
    bind = BindSpec(backend="harness", device=device)
    priv = re.sub(r"(?<!^)([A-Z])", r"_\1", device).lower() + "_priv"
    make_freestanding_bind(bind, priv, "base", prefix="harness")
    return bind


def _formal(regs=None) -> dict:
    return {"driver": "edu",
            "register_map": [{"name": n, "offset": o}
                             for n, o in (regs or [("EDU_ID", 0),
                                                   ("EDU_CMD", 4)])]}


def test_every_bind_primitive_defined_once():
    text = emit_scaffold(_formal(), _bind())
    for prim in _bind().primitives:
        assert len(re.findall(r"\b%s\(" % re.escape(prim.concrete), text)) == 1


def test_register_defines_from_map_and_case_dedup():
    text = emit_scaffold(_formal([("EDU_ID", 0), ("edu_id", 8),
                                  ("EDU_CMD", 4), ("bad-name", 16)]),
                         _bind())
    assert "#define EDU_ID" in text
    assert re.search(r"#define EDU_ID\s+0x0u", text)
    assert "#define EDU_CMD" in text
    # case-colliding and non-identifier names are skipped, not emitted
    assert not re.search(r"#define edu_id", text)
    assert "bad-name" not in text


def test_primitives_trace_and_raw_readers_do_not():
    text = emit_scaffold(_formal(), _bind())
    # each traced primitive body contains exactly one printf ...
    for m in re.finditer(r"static [\w ]+?(harness_\w+)\(.*?\n\}", text, re.S):
        assert m.group(0).count("printf") == 1, m.group(1)
    # ... and the raw readers contain none
    for m in re.finditer(r"static inline \w+ (rh_raw_read\d)\(.*?\n\}",
                         text, re.S):
        assert "printf" not in m.group(0)


def test_w1c_reads_untraced_and_writes_traced():
    text = emit_scaffold(_formal(), _bind())
    m = re.search(r"static void harness_write_w1c32\(.*?\n\}", text, re.S)
    body = m.group(0)
    assert "printf(\"[trace %lu] W" in body
    assert body.count("printf") == 1  # the internal read adds no trace


def test_scaffold_compiles(tmp_path=None):
    path = Path(tempfile.mkstemp(suffix=".c")[1])
    try:
        path.write_text(emit_scaffold(_formal(), _bind()), encoding="utf-8")
        r = subprocess.run(["cc", "-fsyntax-only", "-Wall", str(path)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        path.unlink(missing_ok=True)


def test_summary_names_primitives_and_registers():
    s = summary(_formal(), _bind())
    assert "harness_read32" in s
    assert "rh_raw_read1/2/4" in s
    assert "2 registers" in s
    assert "rh_mmio_backing" in s
