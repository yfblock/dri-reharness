"""Pytest/standalone tests for the reharness extractor (.ris spec language)."""
import os
import sys
import textwrap
try:
    import pytest
    _fixture = pytest.fixture
except ImportError:
    pytest = None
    def _fixture(*args, **kwargs):
        return lambda f: f

HERE = os.path.dirname(os.path.abspath(__file__))
REHARNESS = os.path.dirname(HERE)
sys.path.insert(0, REHARNESS)

from extractor import macros as M  # noqa: E402
from extractor import taint as T  # noqa: E402
from extractor.dataflow import eval_expr, resolve_addr  # noqa: E402
from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import formal_display  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────

def _leaf_ops(ops, acc):
    """Recurse Cond/Seq/Loop, collecting leaf RISOp dicts."""
    for op in ops:
        if "Cond" in op:
            _leaf_ops(op["Cond"]["then_ops"], acc)
            if op["Cond"].get("else_ops"):
                _leaf_ops(op["Cond"]["else_ops"], acc)
        elif "Seq" in op:
            _leaf_ops(op["Seq"]["ops"], acc)
        elif "Loop" in op:
            _leaf_ops(op["Loop"]["body"], acc)
        else:
            acc.append(op)


def _module(formal, name):
    return next(m for m in formal["modules"] if m["name"] == name)


# ── macros ───────────────────────────────────────────────────────────

def test_macro_eval_hex():
    assert M._eval_int_expr("0x20") == 0x20
    assert M._eval_int_expr("0xA4") == 0xA4


def test_macro_eval_bit_and_expr():
    assert M._eval_int_expr("BIT(3)") == 8
    assert M._eval_int_expr("(1 << 5)") == 32
    assert M._eval_int_expr("0x1 | 0x2") == 3
    assert M._eval_int_expr("~0x0") == 0xFFFFFFFF


def test_macro_table_collect_from_source():
    src = textwrap.dedent("""
        #define GPIO_INT_EN    0x20
        #define GPIO_DIR       0x08
        #define NOT_A_REG      foo
        #define BIT(n) (1 << (n))
    """)
    tab = M.collect_from_source(src)
    assert tab.offset("GPIO_INT_EN") == 0x20
    assert tab.offset("GPIO_DIR") == 0x08
    assert "NOT_A_REG" not in tab
    assert "BIT" not in tab


# ── taint / dataflow ─────────────────────────────────────────────────

def test_eval_hex_and_const():
    macros = M.MacroTable()
    assert isinstance(eval_expr("0xFE200000", {}, macros), T.Const)
    assert eval_expr("0x10", {}, macros).n == 0x10


def test_eval_base_plus_macro_offset():
    macros = M.MacroTable()
    macros.add("GPIO_INT_EN", "0x20")
    v = eval_expr("g->base + GPIO_INT_EN", {}, macros)
    assert isinstance(v, T.Offset)
    assert v.base == "g->base" and v.off == 0x20 and v.reg_name == "GPIO_INT_EN"


def test_eval_local_var_base_plus_macro():
    macros = M.MacroTable()
    macros.add("AHCI_VEND_PCFG", "0xA4")
    v = eval_expr("mmio + AHCI_VEND_PCFG", {}, macros)
    assert isinstance(v, T.Offset) and v.base == "mmio" and v.off == 0xA4


def test_resolve_addr_fixed():
    a, _ = resolve_addr("0xFE200000", {}, M.MacroTable())
    assert a == T.addr_fixed(0xFE200000)


def test_resolve_addr_offset_with_macro_name():
    macros = M.MacroTable()
    macros.add("GPIO_INT_CLR", "0x30")
    a, name = resolve_addr("g->base + GPIO_INT_CLR", {}, macros)
    assert a == T.addr_offset("g->base", 0x30)
    assert name == "GPIO_INT_CLR"


# ── end-to-end on gpio-ftgpio010 (.ris spec language) ────────────────

FTGPIO = os.path.join(REHARNESS, "drivers", "test", "gpio-ftgpio010.c")
VIRTIO = os.path.join(REHARNESS, "drivers", "virtio_mmio", "virtio_mmio.c")


@_fixture(scope="module")
def ftgpio_formal():
    return extract_ris(ExtractorConfig(source=FTGPIO)).formal


def test_formal_resolves_register_offsets(ftgpio_formal):
    """Key win over regex: GPIO_INT_EN etc. resolve to symbolic registers."""
    regs = {r["name"]: r["offset"] for r in ftgpio_formal["register_map"]}
    assert regs.get("GPIO_INT_EN") == 0x20
    assert regs.get("GPIO_INT_CLR") == 0x30
    assert regs.get("GPIO_DEBOUNCE_EN") == 0x40
    assert regs.get("GPIO_DEBOUNCE_PRESCALE") == 0x44
    assert "BITS_PER_LONG" not in regs   # no kernel-header noise


def test_formal_symbolic_addr(ftgpio_formal):
    leaves = []
    _leaf_ops(_module(ftgpio_formal, "ftgpio_gpio_mask_irq")["ops"], leaves)
    read = next(o for o in leaves if "Read" in o)
    a = read["Read"]["addr"]
    assert a["Symbolic"]["register"] == "GPIO_INT_EN"
    assert a["Symbolic"]["device"] == "g->base"
    assert read["Read"]["width"] == "B4"


def test_formal_detects_rmw(ftgpio_formal):
    rmw = 0
    for m in ftgpio_formal["modules"]:
        leaves = []
        _leaf_ops(m["ops"], leaves)
        rmw += sum(1 for o in leaves if "ReadModifyWrite" in o)
    assert rmw >= 5   # mask/unmask + set_irq_type(3) + set_config


def test_formal_records_branch_conditions(ftgpio_formal):
    """set_config's `if (val == deb_div)` becomes a Cond block."""
    sc = _module(ftgpio_formal, "ftgpio_gpio_set_config")
    conds = [o for o in sc["ops"] if "Cond" in o]
    assert len(conds) >= 1
    guard = conds[0]["Cond"]["guard"]
    assert guard["BinOp"]["op"] == "Eq"
    assert len(conds[0]["Cond"]["then_ops"]) >= 2


def test_ftgpio_ack_irq_is_entry_not_inlined(ftgpio_formal):
    """ack_irq is a callback entry (.irq_ack); it keeps its own module and is
    NOT inlined into set_irq_type (no duplicated op)."""
    names = {m["name"] for m in ftgpio_formal["modules"]}
    assert "ftgpio_gpio_ack_irq" in names        # kept as its own module
    sit = _module(ftgpio_formal, "ftgpio_gpio_set_irq_type")
    leaves = []
    _leaf_ops(sit["ops"], leaves)
    # set_irq_type's own ops are the type/level/both RMWs; the ack write lives
    # in ack_irq's module, NOT inlined here (clean boundary, no duplication)
    ack_in_sit = any("Write" in o and o["Write"]["addr"]["Symbolic"]["register"] == "GPIO_INT_CLR"
                     for o in leaves)
    assert not ack_in_sit, "ack_irq should not be inlined into set_irq_type (it's a callback entry)"


def test_formal_display_text(ftgpio_formal):
    txt = formal_display(ftgpio_formal)
    assert txt.startswith("driver gpio-ftgpio010 v0.1.0 {")
    assert "module ftgpio_gpio_probe" in txt
    assert "W(B4," in txt and " := R(B4," in txt
    assert "IF " in txt
    assert "-- Interrupt" in txt


def test_formal_expr_normalization(ftgpio_formal):
    """BIT(x) -> Shl(1, x); ~0x0 -> BitXor(0, ⊤)."""
    probe = _module(ftgpio_formal, "ftgpio_gpio_probe")
    leaves = []
    _leaf_ops(probe["ops"], leaves)
    clr = next(o for o in leaves if "Write" in o
               and o["Write"]["addr"]["Symbolic"]["register"] == "GPIO_INT_CLR")
    val = clr["Write"]["value"]
    assert val["BinOp"]["op"] == "BitXor"  # ~0x0 normalized


# ── regression: source-text byte offsets & module dedup (virtio_mmio) ─

@_fixture(scope="module")
def virtio_formal():
    return extract_ris(ExtractorConfig(source=VIRTIO)).formal


def test_virtio_arg_source_not_truncated(virtio_formal):
    """libclang .offset is a BYTE offset; text-mode reading misaligned it,
    truncating values (VIRTIO_STATUS_RESET -> RTIO_STATUS_RESET). Must be intact."""
    probe = _module(virtio_formal, "virtio_mmio_probe")
    leaves = []
    _leaf_ops(probe["ops"], leaves)
    values = []
    for o in leaves:
        if "Write" in o:
            v = o["Write"]["value"]
            if "Var" in v:
                values.append(v["Var"])
    assert "VIRTIO_STATUS_RESET" in values    # not "RTIO_STATUS_RESET"
    assert "VIRTIO_STATUS_ACK" in values


def test_virtio_addresses_resolve(virtio_formal):
    """v->base + VIRTIO_MMIO_STATUS must resolve to a Symbolic register,
    not degrade to [v->base] (Computed)."""
    probe = _module(virtio_formal, "virtio_mmio_probe")
    leaves = []
    _leaf_ops(probe["ops"], leaves)
    regs = {o["Write"]["addr"]["Symbolic"]["register"]
            for o in leaves if "Write" in o and "Symbolic" in o["Write"]["addr"]}
    assert "VIRTIO_MMIO_STATUS" in regs
    # none should degrade to Computed
    assert all("Symbolic" in o["Write"]["addr"]
               for o in leaves if "Write" in o)


def test_virtio_no_module_duplication(virtio_formal):
    """virtio_mmio_init_device is a pure helper (called by probe, not a callback):
    inlined into probe and must NOT also appear as its own module."""
    names = {m["name"] for m in virtio_formal["modules"]}
    assert "virtio_mmio_probe" in names
    assert "virtio_mmio_init_device" not in names   # pure helper → inlined, dedup'd


def test_virtio_probe_inlines_init_device(virtio_formal):
    """init_device's ops must actually appear (inlined) inside probe — e.g. the
    STATUS reset write — proving pure-helper inlining still works."""
    probe = _module(virtio_formal, "virtio_mmio_probe")
    leaves = []
    _leaf_ops(probe["ops"], leaves)
    regs = {o["Write"]["addr"]["Symbolic"]["register"]
            for o in leaves if "Write" in o and "Symbolic" in o["Write"]["addr"]}
    assert "VIRTIO_MMIO_STATUS" in regs
    assert "VIRTIO_MMIO_MAGIC" in {o["Read"]["addr"]["Symbolic"]["register"]
                                   for o in leaves if "Read" in o}


def test_virtio_setup_queue_order(virtio_formal):
    """setup_queue must produce the exact virtio-mmio queue setup sequence:
    W QUEUE_SEL → R QUEUE_NUM_MAX → W QUEUE_NUM → W DESC_LOW/HIGH →
    W AVAIL_LOW/HIGH → W USED_LOW/HIGH → W QUEUE_READY."""
    sq = _module(virtio_formal, "virtio_mmio_setup_queue")
    leaves = []
    _leaf_ops(sq["ops"], leaves)
    seq = []
    for o in leaves:
        if "Read" in o:
            seq.append(("R", o["Read"]["addr"]["Symbolic"]["register"]))
        elif "Write" in o:
            seq.append(("W", o["Write"]["addr"]["Symbolic"]["register"]))
    expected = [
        ("W", "VIRTIO_MMIO_QUEUE_SEL"),
        ("R", "VIRTIO_MMIO_QUEUE_NUM_MAX"),
        ("W", "VIRTIO_MMIO_QUEUE_NUM"),
        ("W", "VIRTIO_MMIO_QUEUE_DESC_LOW"),
        ("W", "VIRTIO_MMIO_QUEUE_DESC_HIGH"),
        ("W", "VIRTIO_MMIO_QUEUE_AVAIL_LOW"),
        ("W", "VIRTIO_MMIO_QUEUE_AVAIL_HIGH"),
        ("W", "VIRTIO_MMIO_QUEUE_USED_LOW"),
        ("W", "VIRTIO_MMIO_QUEUE_USED_HIGH"),
        ("W", "VIRTIO_MMIO_QUEUE_READY"),
    ]
    assert seq == expected, f"queue setup sequence mismatch:\n got {seq}\n exp {expected}"


def test_callback_entry_not_deduped(ftgpio_formal):
    """ftgpio_gpio_ack_irq is registered as .irq_ack (callback entry) AND called
    by set_irq_type; it must keep its own module, not be dedup'd as a helper."""
    names = {m["name"] for m in ftgpio_formal["modules"]}
    assert "ftgpio_gpio_ack_irq" in names   # callback entry → kept
    assert "ftgpio_gpio_set_irq_type" in names


def test_string_literal_not_misclassified_as_callback():
    """A function name appearing inside a string literal must NOT be treated as
    a callback entry (the old text-scan did). Use a synthetic source: 'helper'
    appears in a pr_info string but is only ever called, so it's a pure helper
    → inlined into caller, not kept as a module."""
    import tempfile, os
    src = textwrap.dedent("""
        #define REG 0x10
        static void helper(void) { writel(0x1, REG); }
        static void caller(void) {
            pr_info("helper failed");   /* 'helper' in a string — not a callback */
            helper();
        }
    """)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.c")
    open(p, "w").write(src)
    formal = extract_ris(ExtractorConfig(source=p)).formal
    names = {m["name"] for m in formal["modules"]}
    assert "caller" in names
    assert "helper" not in names   # pure helper (called, no real callback ref) → inlined


def test_parenthesized_call_not_callback():
    """A parenthesized direct call `(helper)()` must NOT be misclassified as a
    callback reference (the CallExpr starts at `(`, the DeclRefExpr at `helper`).
    helper stays a pure helper → inlined into caller."""
    import tempfile, os
    src = textwrap.dedent("""
        #define REG 0x10
        static void helper(void) { writel(0x1, REG); }
        static void caller(void) { (helper)(); }
    """)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.c")
    open(p, "w").write(src)
    formal = extract_ris(ExtractorConfig(source=p)).formal
    names = {m["name"] for m in formal["modules"]}
    assert "caller" in names
    assert "helper" not in names   # (helper)() is a call, not a callback → inlined


def test_nested_conditions_counted():
    """A nested IF inside another IF must report conditions_recorded = 2, not 1."""
    import tempfile, os
    src = textwrap.dedent("""
        #define STAT 0x20
        #define OUT 0x30
        static void f(void) {
            if (readl(STAT) & 0x1) {
                if (readl(STAT) & 0x2) {
                    writel(0x1, OUT);
                }
            }
        }
    """)
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.c")
    open(p, "w").write(src)
    res = extract_ris(ExtractorConfig(source=p))
    assert res.stats["conditions_recorded"] == 2
    # verify the .ris actually has two nested IF blocks
    from extractor.formal import walk_all_ops
    conds = sum(1 for m in res.formal["modules"] for o in walk_all_ops(m["ops"]) if "Cond" in o)
    assert conds == 2


def test_cli_stats_match_emitted_ris():
    """Stats must reflect the EMITTED .ris (excludes inlined helpers), not raw
    extraction. virtio: init_device inlined → reads/writes from probe only."""
    res = extract_ris(ExtractorConfig(source=VIRTIO))
    st = res.stats
    # count leaf ops directly from the formal output
    from extractor.formal import walk_leaf_ops
    reads = sum(1 for m in res.formal["modules"] for o in walk_leaf_ops(m["ops"]) if "Read" in o)
    writes = sum(1 for m in res.formal["modules"] for o in walk_leaf_ops(m["ops"]) if "Write" in o)
    rmw = sum(1 for m in res.formal["modules"] for o in walk_leaf_ops(m["ops"]) if "ReadModifyWrite" in o)
    assert st["mmio_reads"] == reads
    assert st["mmio_writes"] == writes
    assert st["rmw"] == rmw
    assert st["total_ops"] == reads + writes + rmw


# ── Milestone 2-8: spec inference, dspec, bind, codegen, readiness ───

def test_ftgpio_function_roles(ftgpio_formal):
    """Callback-table field → role inference for ftgpio010 irq callbacks."""
    from extractor.extractor import extract_ris
    ds = extract_ris(ExtractorConfig(source=FTGPIO)).device_spec
    roles = {f.name: f.role for f in ds.functions}
    assert roles["ftgpio_gpio_ack_irq"] == "interrupt_ack"
    assert roles["ftgpio_gpio_mask_irq"] == "interrupt_mask"
    assert roles["ftgpio_gpio_unmask_irq"] == "interrupt_unmask"
    assert roles["ftgpio_gpio_set_irq_type"] == "set_irq_type"
    assert roles["ftgpio_gpio_probe"] == "probe"
    # callback entries keep their table binding
    ack = next(f for f in ds.functions if f.name == "ftgpio_gpio_ack_irq")
    assert ack.is_callback_entry and ack.callback_table == "irq_chip"


def test_ftgpio_device_spec(ftgpio_formal):
    from extractor.extractor import extract_ris
    ds = extract_ris(ExtractorConfig(source=FTGPIO)).device_spec
    assert ds.cls == "gpio_controller"
    reg_names = {r.name for r in ds.registers}
    assert "GPIO_INT_EN" in reg_names and "GPIO_INT_CLR" in reg_names
    # state has base; resources include mmio + irq
    assert any(s.name == "base" for s in ds.state)
    rtypes = {r.type for r in ds.resources}
    assert "MmioResource" in rtypes and "IrqResource" in rtypes


def test_dspec_display_roundtrip():
    from extractor.extractor import extract_ris
    ds = extract_ris(ExtractorConfig(source=FTGPIO)).device_spec
    text = ds.display()
    assert text.startswith("device gpio-ftgpio010 {")
    assert "class gpio_controller" in text
    assert "function ftgpio_gpio_ack_irq" in text
    assert "role interrupt_ack" in text
    assert "effect writes_register(GPIO_INT_CLR)" in text


def test_bind_default_and_parse():
    from extractor.extractor import extract_ris
    from extractor.spec import default_bind, parse
    ds = extract_ris(ExtractorConfig(source=FTGPIO)).device_spec
    b = default_bind(ds, "linux")
    assert b.prim("MmioWrite", "B4") == "writel"
    assert b.type_of("MmioBase") == "void __iomem *"
    # round-trip parse
    text = b.display()
    b2 = parse(text)
    assert b2.backend == "linux"
    assert b2.prim("MmioWrite", "B4") == "writel"
    assert any(c.function == "ftgpio_gpio_ack_irq" for c in b2.callbacks)


def test_baremetal_backend_compiles():
    """Generated bare-metal C compiles freestanding."""
    import tempfile, subprocess
    from extractor.extractor import extract_ris
    from extractor.spec import default_bind
    from generator import baremetal
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    bind = default_bind(res.device_spec, "baremetal")
    code = baremetal.generate(res.formal, res.device_spec, bind)
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as tf:
        tf.write(code)
        path = tf.name
    r = subprocess.run(["cc", "-ffreestanding", "-c", "-o", "/dev/null", path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"bare-metal compile failed:\n{r.stderr}"


def test_harness_trace_matches_ris():
    """Userspace harness trace shape (op kind + offset) matches extracted RIS."""
    import tempfile, subprocess, re
    from extractor.extractor import extract_ris
    from extractor.spec import default_bind
    from generator import harness
    from extractor.formal import walk_leaf_ops, expr_to_c

    res = extract_ris(ExtractorConfig(source=FTGPIO))
    bind = default_bind(res.device_spec, "harness")
    code = harness.generate(res.formal, res.device_spec, bind)
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as tf:
        tf.write(code); path = tf.name
    binp = path + ".bin"
    r = subprocess.run(["cc", "-o", binp, path], capture_output=True, text=True)
    assert r.returncode == 0, f"harness compile failed:\n{r.stderr}"
    out = subprocess.run([binp], capture_output=True, text=True).stdout

    # parse trace lines: [trace N] (R|W) 0xOFF = 0xVAL
    traced = re.findall(r"\[(?:trace \d+)?\]?\s*(R|W)\s+0x([0-9a-f]+)", out)
    traced_ops = [(k, int(off, 16)) for k, off in traced]

    # expected: probe's 4 writes (the entry the harness calls)
    probe = next(m for m in res.formal["modules"] if m["name"] == "ftgpio_gpio_probe")
    regs = {r["name"]: r["offset"] for r in res.formal["register_map"]}
    expected = []
    for o in walk_leaf_ops(probe["ops"]):
        if "Write" in o:
            reg = o["Write"]["addr"]["Symbolic"]["register"]
            expected.append(("W", regs[reg]))
    assert traced_ops == expected, f"trace {traced_ops} != expected {expected}"


def test_readiness_score():
    from extractor.extractor import extract_ris
    from extractor.metrics import score
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    s = score(res.device_spec, res.formal, res.warnings, res.facts)
    assert s["ris_quality"] >= 0.9
    assert s["backend_bare_metal_ready"] is True
    assert 0 <= s["function_spec_quality"] <= 1.0


# ── Milestone 9: facts, bundle, llm_synthesis_ready, repair loop ─────

def test_facts_extraction():
    from extractor.extractor import extract_ris
    f = extract_ris(ExtractorConfig(source=FTGPIO)).facts
    assert any(s.name == "ftgpio_gpio" for s in f.structs)
    assert f.callbacks.get("irq_chip.irq_ack") == "ftgpio_gpio_ack_irq"
    assert any(r.acquisition == "devm_platform_ioremap_resource" for r in f.resources)
    assert any("ENOMEM" in e for e in f.error_paths)
    assert all(not k.startswith("_") for k in f.constants)  # no compiler builtins


def test_facts_trimmed_no_kernel_noise():
    """recom.md: .facts must not dump kernel-wide CONFIG_*/KASAN_*/TASK_* noise."""
    from extractor.extractor import extract_ris
    f = extract_ris(ExtractorConfig(source=FTGPIO)).facts
    for k in f.constants:
        assert not k.startswith(("CONFIG_", "KASAN_", "TASK_", "CPUINFO_",
                                 "BUG_", "TAINT_", "pt_regs_")), f"noise kept: {k}"
    # virtio facts: only VIRTIO_* register/status constants
    fv = extract_ris(ExtractorConfig(source=VIRTIO)).facts
    assert all(k.startswith("VIRTIO_") for k in fv.constants)
    assert "VIRTIO_STATUS_RESET" in fv.constants


def test_merged_bind_roundtrip():
    """recom.md: per-backend .bind files merge into one multi-block file."""
    from extractor.extractor import extract_ris
    from extractor.spec import default_bind, display_bind_set, parse_bind_set
    ds = extract_ris(ExtractorConfig(source=FTGPIO)).device_spec
    binds = [default_bind(ds, b) for b in ("harness", "baremetal", "linux")]
    text = display_bind_set(binds)
    assert text.count("backend ") == 3
    parsed = parse_bind_set(text)
    assert len(parsed) == 3
    assert {b.backend for b in parsed} == {"harness", "baremetal", "linux"}
    assert parsed[0].prim("MmioWrite", "B4")  # round-trips primitives


def test_llm_synthesis_ready_gate():
    from extractor.extractor import extract_ris
    from extractor.metrics import score
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    s = score(res.device_spec, res.formal, res.warnings, res.facts)
    assert "llm_synthesis_ready" in s and "facts_quality" in s
    assert s["facts_quality"] >= 0.6
    assert s["llm_synthesis_ready"] is True


def test_bundle_assembly():
    import tempfile, os
    from extractor.extractor import extract_ris
    import synthesis
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    bdir = synthesis.build_bundle(res, "harness", tempfile.mkdtemp())
    files = set(os.listdir(bdir))
    name = res.formal["driver"]
    for need in (f"{name}.ris", f"{name}.dspec", f"{name}.facts",
                 f"{name}.harness.bind", f"{name}.scaffold.c",
                 "constraints.md", "verification.md"):
        assert need in files, f"missing {need}"


def test_repair_loop_offline():
    import tempfile, os
    from extractor.extractor import extract_ris
    import synthesis
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    result = synthesis.run_repair_loop(res, "harness", tempfile.mkdtemp(),
                                       llm=synthesis.NullLLM(), max_iters=2)
    assert result["llm"] == "null" and result["iters"] >= 1
    assert os.path.exists(result["candidate"])
    assert any(f.startswith("feedback.iter") for f in os.listdir(result["bundle"]))


def test_verify_feedback_trace_match():
    import tempfile, os, shutil
    from extractor.extractor import extract_ris
    import synthesis
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    bdir = synthesis.build_bundle(res, "harness", tempfile.mkdtemp())
    name = res.formal["driver"]
    shutil.copy(os.path.join(bdir, f"{name}.scaffold.c"),
                os.path.join(bdir, f"{name}.candidate.c"))
    fb = synthesis.verify_candidate(os.path.join(bdir, f"{name}.candidate.c"), res, "harness")
    assert fb["compile"]["status"] == "passed"
    assert fb["trace"]["status"] == "passed"


# ── standalone runner (no pytest required) ───────────────────────────

def _run_standalone():
    import traceback
    formal = extract_ris(ExtractorConfig(source=FTGPIO)).formal
    vio = extract_ris(ExtractorConfig(source=VIRTIO)).formal
    fixtures = {"ftgpio_formal": formal, "virtio_formal": vio}
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            args = t.__code__.co_varnames[: t.__code__.co_argcount]
            t(*[fixtures[a] for a in args])
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
