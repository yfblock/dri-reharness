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
from extractor.compile_context import read_kbuild_command, resolve_compile_context  # noqa: E402
from extractor.dataflow import eval_expr, resolve_addr  # noqa: E402
from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import expr_to_c, formal_display, parse_expr  # noqa: E402
from verification.check_generalization_guard import check_guard  # noqa: E402
from verification.materialize_holdout_contexts import validate_recipes  # noqa: E402
from verification.run_zero_shot_matrix import (  # noqa: E402
    cluster_blockers,
    normalize_blocker,
)


# ── helpers ──────────────────────────────────────────────────────────


def test_zero_shot_holdout_is_frozen_and_not_special_cased():
    report = check_guard()
    assert report["cases"] == 12
    assert report["first_run"] == "gpio-altera"
    assert report["passed"], report["issues"]


def test_zero_shot_context_recipe_exactly_matches_frozen_sources():
    import json
    from pathlib import Path

    root = Path(REHARNESS)
    holdout = json.loads((
        root / "drivers" / "holdout" / "zero-shot-v1.json"
    ).read_text(encoding="utf-8"))
    recipes = json.loads((
        root / "drivers" / "holdout" / "zero-shot-v1-contexts.json"
    ).read_text(encoding="utf-8"))
    assert validate_recipes(holdout, recipes) == []


def test_kbuild_saved_command_parser_strips_post_compile_tools():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        command_file = Path(directory) / ".demo.o.cmd"
        command_file.write_text(
            "savedcmd_drivers/demo.o := clang -DVALUE=7 -c demo.c "
            "-o demo.o ; ./tools/objtool demo.o\n",
            encoding="utf-8")
        assert read_kbuild_command(str(command_file)) == (
            "clang -DVALUE=7 -c demo.c -o demo.o")


def test_zero_shot_blocker_normalization_and_common_root_selection():
    assert normalize_blocker(
        "3 unsafe dynamic register address(es) (4 computed total)"
    ) == "unsafe_dynamic_address"
    assert normalize_blocker(
        "linux backend has unsupported semantic bindings"
    ) == "linux_semantic_binding"
    rows = [
        {"driver": f"case-{index}", "blockers": [
            "1 conservative loop summary/summaries require validation",
            "linux backend has unsupported semantic bindings",
        ]}
        for index in range(3)
    ]
    result = cluster_blockers(rows)
    assert result["first_common_semantic_blocker"] == {
        "category": "conservative_loop",
        "driver_count": 3,
        "drivers": ["case-0", "case-1", "case-2"],
    }


def test_no_register_access_blocks_every_strict_backend_even_if_code_compiles():
    import tempfile
    from pathlib import Path
    from extractor.metrics import score

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "no_mmio.c"
        source.write_text(
            "static int no_mmio_probe(void) { return 0; }\n",
            encoding="utf-8")
        result = extract_ris(ExtractorConfig(source=str(source)))
        readiness = score(
            result.device_spec, result.formal, result.warnings, result.facts,
            gen_results={
                "harness": {"compiled": True, "trace_passed": True,
                            "has_todo": False, "unsupported": False},
                "baremetal": {"compiled": True, "has_todo": False,
                              "unsupported": False},
                "linux": {"compiled": True, "syntax_ok": True,
                          "has_todo": False, "unsupported": False},
            })
        assert "no MMIO register accesses" in readiness["blockers"]
        assert readiness["backend_harness_ready"] is False
        assert readiness["backend_bare_metal_ready"] is False
        assert readiness["backend_linux_ready"] is False


def test_kbuild_cmd_compile_context_imports_only_parser_relevant_flags():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        linux = root / "linux"
        build = root / "build"
        source = linux / "drivers" / "demo" / "demo.c"
        source.parent.mkdir(parents=True)
        source.write_text("int demo(void) { return DEMO_VALUE; }\n", encoding="utf-8")
        command_file = build / "drivers" / "demo" / ".demo.o.cmd"
        command_file.parent.mkdir(parents=True)
        command_file.write_text(
            "savedcmd_drivers/demo/demo.o := gcc -nostdinc -I./include "
            f"-I{linux}/include -include {linux}/include/demo.h "
            "-DDEMO_VALUE=7 -std=gnu11 -Wall -O2 -c -o "
            f"drivers/demo/demo.o {source} ; objtool demo.o\n",
            encoding="utf-8")
        context = resolve_compile_context(
            str(source), linux_root=str(linux), build_root=str(build),
            mode="required")
        assert context is not None
        assert context.origin == "kbuild-cmd"
        assert "-DDEMO_VALUE=7" in context.arguments
        assert "-Wall" not in context.arguments
        assert "-O2" not in context.arguments
        assert "-I" + str(build / "include") in context.arguments
        assert context.provenance == str(command_file)


def test_compile_commands_precedes_kbuild_cmd_and_resolves_relative_paths():
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        linux = root / "linux"
        build = root / "build"
        source = linux / "drivers" / "demo.c"
        source.parent.mkdir(parents=True)
        source.write_text("int demo(void);\n", encoding="utf-8")
        database = root / "compile_commands.json"
        database.write_text(json.dumps([{
            "directory": str(build),
            "file": str(source),
            "arguments": ["clang", "-I./generated", "-DCOMPILE_DB=1",
                          "-c", str(source), "-o", "demo.o"],
        }]), encoding="utf-8")
        context = resolve_compile_context(
            str(source), linux_root=str(linux), build_root=str(build),
            compile_commands=str(database), mode="required")
        assert context is not None
        assert context.origin == "compile-commands"
        assert "-DCOMPILE_DB=1" in context.arguments
        assert "-I" + str(build / "generated") in context.arguments


def test_required_compile_context_does_not_silently_fallback():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "linux" / "drivers" / "missing.c"
        source.parent.mkdir(parents=True)
        source.write_text("int missing(void);\n", encoding="utf-8")
        try:
            resolve_compile_context(
                str(source), linux_root=str(root / "linux"),
                build_root=str(root / "build"), mode="required")
        except RuntimeError as exc:
            assert "no Kbuild compile context found" in str(exc)
        else:
            raise AssertionError("required compile context silently fell back")


def test_frozen_first_holdout_uses_kbuild_context_without_core_special_case():
    import json
    from pathlib import Path

    manifest_path = Path(REHARNESS) / "drivers" / "holdout" / "zero-shot-v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = next(case for case in manifest["cases"]
                if case["id"] == manifest["first_run"])
    source = (manifest_path.parent / case["source"]).resolve()
    result = extract_ris(ExtractorConfig(
        source=str(source), compile_context_mode="required"))
    assert result.stats["compile_context"]["origin"] == "kbuild-cmd"
    assert result.stats["functions_analyzed"] == 13
    assert result.stats["access_accounting"]["strict_complete"] is True
    assert result.stats["total_ops"] == 18
    assert not any("clang diag[3]" in warning or "clang diag[4]" in warning
                   for warning in result.warnings)

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
    assert M._eval_int_expr("0x10U") == 0x10
    assert M._eval_int_expr("32ULL") == 32


def test_macro_eval_bit_and_expr():
    assert M._eval_int_expr("BIT(3)") == 8
    assert M._eval_int_expr("(1 << 5)") == 32
    assert M._eval_int_expr("0x1 | 0x2") == 3
    assert M._eval_int_expr("~0x0") == 0xFFFFFFFF
    assert M._eval_int_expr("HSOTG_REG(0x14)") == 0x14


def test_macro_table_collect_from_source():
    src = textwrap.dedent("""
        #define GPIO_INT_EN    0x20
        #define GPIO_DIR       0x08
        #define NOT_A_REG      foo
        #define BIT(n) (1 << (n))
        #define FLAG           (1 << 4)
    """)
    tab = M.collect_from_source(src)
    assert tab.offset("GPIO_INT_EN") == 0x20
    assert tab.offset("GPIO_DIR") == 0x08
    assert "NOT_A_REG" not in tab
    assert "BIT" not in tab
    assert tab.offset("FLAG") == 16


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
EDU = os.path.join(REHARNESS, "drivers", "test", "edu.c")
PL061 = os.path.join(REHARNESS, "drivers", "test", "gpio-pl061.c")
MB86S7X = os.path.join(REHARNESS, "drivers", "test", "gpio-mb86s7x.c")
C67X00_MULTI = os.path.join(REHARNESS, "drivers", "multisource", "c67x00.json")
ASPEED_VHUB_MULTI = os.path.join(
    REHARNESS, "drivers", "multisource", "aspeed-vhub.json")
DWC2_MULTI = os.path.join(REHARNESS, "drivers", "multisource", "dwc2.json")


@_fixture(scope="module")
def ftgpio_formal():
    return extract_ris(ExtractorConfig(source=FTGPIO)).formal


def test_edu_pci_extraction():
    """QEMU EDU PCI driver (ciosantilli): pci_iomap global mmio, DMA writes, IRQ.
    Registers resolve to Symbolic; global mmio base recognized."""
    res = extract_ris(ExtractorConfig(source=EDU))
    regs = {r.name: r.offset for r in res.device_spec.registers}
    assert regs.get("IO_ID") == 0x00
    assert regs.get("IO_IRQ_STATUS") == 0x24
    assert regs.get("IO_IRQ_ACK") == 0x64
    # mmio global recognized as base → no Top addresses
    from extractor.formal import expr_display, walk_leaf_ops
    for m in res.formal["modules"]:
        for o in walk_leaf_ops(m["ops"]):
            if "Delay" in o:
                continue
            a = (o.get("Read") or o.get("Write") or o.get("ReadModifyWrite") or {}).get("addr", {})
            # no address should degrade to Top (completely unknown base)
            assert "Top" not in a, f"Top addr in {m['name']}: {a}"
    # probe callback bound (pci_driver.probe)
    probe = next(f for f in res.device_spec.functions if f.role == "probe")
    assert probe is not None


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


def test_rmw_preserves_straight_line_bit_transform(ftgpio_formal):
    mask_ops = []
    unmask_ops = []
    _leaf_ops(_module(ftgpio_formal, "ftgpio_gpio_mask_irq")["ops"], mask_ops)
    _leaf_ops(_module(ftgpio_formal, "ftgpio_gpio_unmask_irq")["ops"], unmask_ops)
    mask = next(o["ReadModifyWrite"] for o in mask_ops if "ReadModifyWrite" in o)
    unmask = next(o["ReadModifyWrite"] for o in unmask_ops if "ReadModifyWrite" in o)
    assert mask["transform"]["BinOp"]["op"] == "BitAnd"
    assert unmask["transform"]["BinOp"]["op"] == "BitOr"
    assert mask["read_var"] == "val" and unmask["read_var"] == "val"

    # Multi-path switch transforms are represented as nested ITEs.  Every
    # branch starts from the original register value, so the cases are not
    # incorrectly concatenated into one sequential update.
    irq_ops = []
    _leaf_ops(_module(ftgpio_formal, "ftgpio_gpio_set_irq_type")["ops"], irq_ops)
    transforms = [o["ReadModifyWrite"]["transform"]
                  for o in irq_ops if "ReadModifyWrite" in o]
    assert len(transforms) == 3
    assert all("Ite" in transform for transform in transforms)
    rendered = [expr_to_c(transform) for transform in transforms]
    assert all("?" in text and "TODO: unknown" not in text for text in rendered)
    assert all("IRQ_TYPE_EDGE_BOTH" in text and "IRQ_TYPE_LEVEL_LOW" in text
               for text in rendered)


def test_ite_codegen_uses_c_conditional_expression():
    expr = {"Ite": {
        "guard": {"BinOp": {"op": "Eq", "left": {"Var": "type"},
                              "right": {"Const": 1}}},
        "then": {"BinOp": {"op": "BitOr", "left": {"Var": "reg"},
                             "right": {"Var": "mask"}}},
        "else": {"Var": "reg"},
    }}
    assert expr_to_c(expr) == "((type == 0x1) ? (reg | mask) : reg)"


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


def test_access_accounting_and_operation_evidence_are_complete():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics, score

    result = extract_ris(ExtractorConfig(source=FTGPIO))
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == 22
    assert accounting["emitted"] == 22
    assert accounting["unaccounted"] == 0
    assert accounting["ris_ops_without_evidence"] == 0
    assert accounting["complete"] is True
    assert accounting["strict_complete"] is True

    op_ids = []
    for module in result.formal["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if body is None:
                continue
            op_ids.append(body["op_id"])
            assert body["evidence"]["site_id"]
            assert body["evidence"]["source"] == os.path.abspath(FTGPIO)
            assert body["reliability"] in {"Exact", "Conservative", "Unknown"}
            assert body["address_precision"] in {
                "symbolic", "fixed", "computed", "unknown"}
    assert len(op_ids) == len(set(op_ids)) == 22
    metrics = driver_metrics(result.formal)
    assert sum(metrics["reliability"].values()) == 22
    assert score(result.device_spec, result.formal, result.warnings,
                 result.facts)["backend_linux_ready"] is True


def test_filtered_source_mmio_access_blocks_strict_readiness():
    from extractor.metrics import score

    result = extract_ris(ExtractorConfig(
        source=FTGPIO, extra_blacklist=["readl"]))
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["filtered"] > 0
    assert accounting["complete"] is True
    assert accounting["strict_complete"] is False
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("explicitly filtered" in blocker
               for blocker in readiness["blockers"])


def test_structured_control_preserves_loop_and_branch_evidence():
    from extractor.formal import expr_display, walk_leaf_ops
    from extractor.metrics import driver_metrics, score
    from extractor.spec import default_bind
    from generator import harness as harness_gen

    source = os.path.join(REHARNESS, "tests", "fixtures", "control_flow.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "control_flow")
    assert len(module["ops"]) == 1 and "Loop" in module["ops"][0]
    loop = module["ops"][0]["Loop"]
    assert loop["loop_kind"] == "for"
    assert loop["reliability"] == "Conservative"
    assert expr_display(loop["guard"]) == "(i < count)"
    assert loop["init"] == "i = 0"
    assert loop["step"] == "i++"
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 2
    assert all((leaf["Write"]["path_precision"] == "syntactic")
               for leaf in leaves)
    metrics = driver_metrics(result.formal)
    assert metrics["loop"] == 1 and metrics["cond"] == 2
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_harness_ready"] is False
    assert any("conservative loop" in blocker
               for blocker in readiness["blockers"])
    code = harness_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "harness"))
    assert "REHARNESS_UNSUPPORTED_LOOP" in code


def test_canonical_bounded_loop_is_proved_and_lowered():
    from extractor.metrics import driver_metrics, score
    from extractor.spec import default_bind
    from generator import harness as harness_gen

    source = os.path.join(REHARNESS, "tests", "fixtures", "bounded_loop.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "bounded_loop")
    assert len(module["ops"]) == 1 and "Loop" in module["ops"][0]
    loop = module["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["count"] == {"Const": 4}
    assert loop["induction_var"] == "i"
    metrics = driver_metrics(result.formal)
    assert metrics["loop"] == 1
    assert metrics["conservative_loop"] == 0
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_bare_metal_ready"] is True
    code = harness_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "harness"))
    assert "for (i = 0; (i < 0x4); i++)" in code
    assert "REHARNESS_UNSUPPORTED_LOOP" not in code


def test_path_sensitive_assignment_store_builds_ite_write_value():
    from extractor.formal import expr_display

    source = os.path.join(REHARNESS, "tests", "fixtures", "path_state.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "path_state")
    write = next(op["Write"] for op in module["ops"] if "Write" in op)
    assert "Ite" in write["value"]
    rendered = expr_display(write["value"])
    assert "select" in rendered
    assert "0x2" in rendered and "0x1" in rendered
    assert write["addr"]["Symbolic"]["register"] == "VALUE_REG"
    assert write["reliability"] == "Exact"


def test_simple_early_return_becomes_continuation_guard():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(REHARNESS, "tests", "fixtures", "early_return.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "early_return")
    assert len(module["ops"]) == 1 and "Cond" in module["ops"][0]
    cond = module["ops"][0]["Cond"]
    assert expr_display(cond["guard"]) == "enabled"
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 1
    assert leaves[0]["Write"]["addr"]["Symbolic"]["register"] == "EARLY_REG"
    validation = result.formal["metadata"]["path_validation"]
    assert validation["complete"] is True
    assert validation["infeasible"] == 0
    control = result.formal["metadata"]["control_accounting"]
    assert control["modeled_early_returns"] == 1
    assert control["complete"] is True


def test_forward_goto_is_lowered_to_bounded_cfg_guard():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(REHARNESS, "tests", "fixtures", "goto_control.c")
    result = extract_ris(ExtractorConfig(source=source))
    control = result.formal["metadata"]["control_accounting"]
    assert control["complete"] is True
    assert control["unsupported"] == 0
    assert control["modeled_forward_gotos"] == 1
    module = _module(result.formal, "goto_control")
    assert "Cond" in module["ops"][0]
    assert expr_display(module["ops"][0]["Cond"]["guard"]) == "(skip == 0x0)"
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 2
    cfg = control["cfg"]
    assert cfg["complete"] is True
    assert cfg["join_count"] == 1
    assert cfg["backedge_count"] == 0
    function_cfg = cfg["functions"][0]
    join = function_cfg["join_blocks"][0]
    join_block = next(
        block for block in function_cfg["blocks"] if block["id"] == join)
    assert join_block["label"] == "out"
    assert join_block["idom"] is not None
    assert join_block["ipostdom"] is not None


def test_backward_goto_remains_an_explicit_control_boundary():
    from extractor.metrics import score

    source = os.path.join(REHARNESS, "tests", "fixtures", "goto_backward.c")
    result = extract_ris(ExtractorConfig(source=source))
    control = result.formal["metadata"]["control_accounting"]
    assert control["complete"] is False
    assert control["unsupported"] == 1
    assert control["sites"][0]["kind"] == "goto"
    assert control["cfg"]["complete"] is True
    assert control["cfg"]["backedge_count"] == 1
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_bare_metal_ready"] is False
    assert any("unsupported control-flow" in blocker
               for blocker in readiness["blockers"])


def test_switch_cases_receive_mutually_exclusive_path_guards():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(REHARNESS, "tests", "fixtures", "switch_paths.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "switch_paths")
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 3
    guards = []
    for top in module["ops"]:
        assert "Cond" in top
        guards.append(expr_display(top["Cond"]["guard"]))
    assert any("mode" in guard and "0x1" in guard for guard in guards)
    assert any("mode" in guard and "0x2" in guard for guard in guards)
    default = next(guard for guard in guards
                   if "||" in guard and "== 0x0" in guard)
    assert "0x1" in default and "0x2" in default
    assert all(leaf["Write"]["reliability"] == "Conservative"
               for leaf in leaves)
    validation = result.formal["metadata"]["path_validation"]
    assert validation["complete"] is True
    assert len(validation["switch_pairs"]) == 3
    assert all(pair["exclusive"] for pair in validation["switch_pairs"])


def test_smt_path_validation_blocks_contradictory_nested_path():
    from extractor.metrics import score

    source = os.path.join(REHARNESS, "tests", "fixtures", "infeasible_path.c")
    result = extract_ris(ExtractorConfig(source=source))
    validation = result.formal["metadata"]["path_validation"]
    assert validation["complete"] is True
    assert validation["infeasible"] == 1
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("contradictory/infeasible" in blocker
               for blocker in readiness["blockers"])


def test_auto_wrapper_summary_survives_zero_inline_depth():
    from extractor.formal import walk_leaf_ops

    source = os.path.join(REHARNESS, "tests", "fixtures", "mmio_wrapper.c")
    result = extract_ris(ExtractorConfig(
        source=source, max_inline_depth=0))
    assert result.stats["wrapper_summary_count"] >= 1
    assert any("wrapper_read" in name
               for name in result.stats["wrapper_summaries"])
    module = _module(result.formal, "wrapper_caller")
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 1 and "Read" in leaves[0]
    read = leaves[0]["Read"]
    assert read["addr"]["Symbolic"]["register"] == "WRAP_STATUS"
    assert read["evidence"]["origin"] == "wrapper_summary"
    assert read["evidence"]["summarized_at"][0]["callee"] == "wrapper_read"


def test_static_ops_table_indirect_call_is_resolved_and_propagated():
    from extractor.formal import walk_leaf_ops

    source = os.path.join(REHARNESS, "tests", "fixtures", "indirect_ops.c")
    result = extract_ris(ExtractorConfig(source=source))
    assert result.stats["resolved_indirect_calls"] == 1
    assert result.stats["indirect_call_targets"]["local_ops.emit"] == \
        "indirect_emit"
    caller = _module(result.formal, "indirect_caller")
    leaves = list(walk_leaf_ops(caller["ops"]))
    assert len(leaves) == 1 and "Write" in leaves[0]
    write = leaves[0]["Write"]
    assert write["addr"]["Symbolic"]["register"] == "INDIRECT_REG"
    assert write["value"] == {"Const": 7}
    summarized = write["evidence"].get("summarized_at", [])
    inlined = write["evidence"].get("inlined_at", [])
    assert any(item.get("indirect_expression") == "local_ops.emit"
               for item in summarized + inlined)


def test_regmap_operations_are_accounted_but_domain_blocked():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics, score
    from extractor.spec import default_bind
    from generator import harness as harness_gen

    source = os.path.join(REHARNESS, "tests", "fixtures", "regmap_access.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "regmap_access")
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 3
    assert {next(iter(leaf)) for leaf in leaves} == {
        "Read", "Write", "ReadModifyWrite"}
    assert all((leaf.get("Read") or leaf.get("Write")
                or leaf.get("ReadModifyWrite"))["access_domain"] == "regmap"
               for leaf in leaves)
    assert all((leaf.get("Read") or leaf.get("Write")
                or leaf.get("ReadModifyWrite"))["reliability"] == "Unsupported"
               for leaf in leaves)
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == 4
    assert accounting["emitted"] == 3
    assert accounting["unsupported"] == 1
    assert accounting["unaccounted"] == 0
    assert accounting["strict_complete"] is False
    metrics = driver_metrics(result.formal)
    assert metrics["reliability"]["Unsupported"] == 3
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("unsupported access domain" in blocker
               for blocker in readiness["blockers"])
    code = harness_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "harness"))
    assert code.count("REHARNESS_UNSUPPORTED_ACCESS_DOMAIN") == 3


def test_volatile_and_inline_asm_accesses_block_false_strict_completion():
    from extractor.metrics import score

    source = os.path.join(REHARNESS, "tests", "fixtures", "opaque_access.c")
    result = extract_ris(ExtractorConfig(source=source, linux_root="/nonexistent"))
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == 3
    assert accounting["emitted"] == 0
    assert accounting["unsupported"] == 3
    assert accounting["unaccounted"] == 0
    assert accounting["complete"] is True
    assert accounting["strict_complete"] is False
    assert {site["access_domain"] for site in accounting["sites"]} == {
        "direct_volatile", "inline_asm"}
    assert {site["access_kind"] for site in accounting["sites"]} == {
        "read", "write", "opaque"}
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("unsupported" in blocker for blocker in readiness["blockers"])


def test_formal_expr_normalization(ftgpio_formal):
    """BIT(x) -> Shl(1, x); ~0x0 -> BitXor(0, ⊤)."""
    probe = _module(ftgpio_formal, "ftgpio_gpio_probe")
    leaves = []
    _leaf_ops(probe["ops"], leaves)
    clr = next(o for o in leaves if "Write" in o
               and o["Write"]["addr"]["Symbolic"]["register"] == "GPIO_INT_CLR")
    # The dataflow evaluator may soundly fold this extracted write to the
    # all-ones constant.  Exercise the formal parser directly so this remains
    # a normalization test rather than constraining constant folding.
    assert clr["Write"]["value"] == {"Const": 0xFFFFFFFF}
    val = parse_expr("~0x0")
    assert val["BinOp"]["op"] == "BitXor"
    arithmetic = parse_expr("4 * (d->hwirq % 8)")
    assert arithmetic["BinOp"]["op"] == "Mul"
    assert arithmetic["BinOp"]["right"]["BinOp"]["op"] == "Mod"


# ── regression: source-text byte offsets & module dedup (synthetic) ──

def test_source_text_byte_offset_with_multibyte():
    """libclang .offset is a BYTE offset; a multibyte char before a writel must
    not truncate the value (regression for the text-mode read bug)."""
    import tempfile, os
    # a 2-byte UTF-8 char (©) in a comment before the writel
    src = '/* © copyright */\n#define REG 0x10\n#define VIRTIO_STATUS_RESET 0x0\nstatic void f(void *b){ writel(VIRTIO_STATUS_RESET, b + REG); }\n'
    d = tempfile.mkdtemp(); p = os.path.join(d, "t.c")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    res = extract_ris(ExtractorConfig(source=p))
    leaves = []
    _leaf_ops(res.formal["modules"][0]["ops"], leaves)
    w = next(o for o in leaves if "Write" in o)
    # value must be intact (Var "VIRTIO_STATUS_RESET"), not truncated
    assert "Var" in w["Write"]["value"]
    assert w["Write"]["value"]["Var"] == "VIRTIO_STATUS_RESET"


def test_pure_helper_is_inlined_and_deduped():
    """A pure helper (called, never callback-registered) is inlined into its
    caller and does NOT appear as its own module (no duplication)."""
    import tempfile, os
    src = textwrap.dedent("""
        #define REG 0x10
        static void helper(void *b) { writel(0x1, b + REG); }
        static void caller(void *b) { helper(b); }
    """)
    d = tempfile.mkdtemp(); p = os.path.join(d, "t.c")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(src)
    formal = extract_ris(ExtractorConfig(source=p)).formal
    names = {m["name"] for m in formal["modules"]}
    assert "caller" in names
    assert "helper" not in names   # pure helper → inlined, dedup'd
    # caller contains the inlined write
    leaves = []
    _leaf_ops(_module(formal, "caller")["ops"], leaves)
    assert any("Write" in o for o in leaves)


def test_four_translation_unit_manifest_inlines_across_sources():
    import json
    import tempfile

    sources = {
        "low.c": textwrap.dedent("""
            #define REG_LOW 0x20
            extern unsigned int readl(void *addr);
            unsigned int low(void *base) { return readl(base + REG_LOW); }
        """),
        "mid.c": textwrap.dedent("""
            extern unsigned int low(void *base);
            unsigned int mid(void *base) { return low(base); }
        """),
        "entry.c": textwrap.dedent("""
            extern unsigned int mid(void *base);
            unsigned int entry(void *base) { return mid(base); }
        """),
        "other.c": textwrap.dedent("""
            #define REG_OTHER 0x24
            extern void writel(unsigned int value, void *addr);
            void other(void *base) { writel(1, base + REG_OTHER); }
        """),
    }
    with tempfile.TemporaryDirectory() as directory:
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        manifest = os.path.join(directory, "driver.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "multi-demo",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=3))
        assert result.formal["driver"] == "multi-demo"
        assert result.stats["translation_units"] == 4
        assert len(result.stats["source_files"]) == 4
        assert len(result.formal["metadata"]["sources"]) == 4
        names = {module["name"] for module in result.formal["modules"]}
        assert names == {"entry", "other"}

        entry_ops = []
        _leaf_ops(_module(result.formal, "entry")["ops"], entry_ops)
        assert any("Read" in op for op in entry_ops)
        regs = {reg["name"]: reg["offset"]
                for reg in result.formal["register_map"]}
        assert regs == {"REG_LOW": 0x20, "REG_OTHER": 0x24}
        module_sources = {os.path.basename(module["source"][0])
                          for module in result.formal["modules"]}
        assert module_sources == {"entry.c", "other.c"}


def test_multisource_static_symbol_identity_prevents_cross_tu_crosstalk():
    import json
    import tempfile

    sources = {
        "alpha.c": textwrap.dedent("""
            #define REG_ALPHA 0x10
            extern void writel(unsigned int value, void *addr);
            static void helper(void *base) { writel(0xa1, base + REG_ALPHA); }
            void entry_alpha(void *base) { helper(base); }
            static void status(void *base) { writel(0xaa, base + REG_ALPHA); }
            void (*status_alpha)(void *) = status;
        """),
        "beta.c": textwrap.dedent("""
            #define REG_BETA 0x20
            extern void writel(unsigned int value, void *addr);
            static void helper(void *base) { writel(0xb2, base + REG_BETA); }
            void entry_beta(void *base) { helper(base); }
            static void status(void *base) { writel(0xbb, base + REG_BETA); }
            void (*status_beta)(void *) = status;
        """),
        "gamma.c": "void gamma(void) {}\n",
        "delta.c": "void delta(void) {}\n",
    }
    with tempfile.TemporaryDirectory() as directory:
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        manifest = os.path.join(directory, "driver.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "static-collision",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent"))
        names = {module["name"] for module in result.formal["modules"]}
        assert {"entry_alpha", "entry_beta"} <= names
        assert {"alpha__status", "beta__status"} <= names
        assert result.stats["duplicate_static_symbols"] == 4

        alpha_ops = []
        beta_ops = []
        _leaf_ops(_module(result.formal, "entry_alpha")["ops"], alpha_ops)
        _leaf_ops(_module(result.formal, "entry_beta")["ops"], beta_ops)
        alpha_regs = {
            op["Write"]["addr"]["Symbolic"]["register"]
            for op in alpha_ops if "Write" in op
        }
        beta_regs = {
            op["Write"]["addr"]["Symbolic"]["register"]
            for op in beta_ops if "Write" in op
        }
        assert alpha_regs == {"REG_ALPHA"}
        assert beta_regs == {"REG_BETA"}


def test_cross_tu_inline_substitutes_formal_parameters_with_call_arguments():
    import json
    import tempfile

    sources = {
        "write.c": textwrap.dedent("""
            extern void writel(unsigned int value, void *addr);
            void write_reg(void *dev, unsigned int reg, unsigned int value)
            {
                writel(value, dev + reg);
            }
        """),
        "caller.c": textwrap.dedent("""
            #define REG_A 0x34
            extern void write_reg(void *dev, unsigned int reg,
                                  unsigned int value);
            void caller(void *chip) { write_reg(chip, REG_A, 0x55); }
        """),
        "extra1.c": "void extra1(void) {}\n",
        "extra2.c": "void extra2(void) {}\n",
    }
    with tempfile.TemporaryDirectory() as directory:
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        manifest = os.path.join(directory, "driver.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "argument-instantiation",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent"))
        leaves = []
        _leaf_ops(_module(result.formal, "caller")["ops"], leaves)
        write = next(op["Write"] for op in leaves if "Write" in op)
        assert write["addr"] == {
            "Symbolic": {"device": "chip", "register": "REG_A"}}
        assert write["value"] == {"Const": 0x55}
        rendered = formal_display(result.formal)
        assert "dev" not in rendered
        assert " value" not in rendered
        assert result.stats["cross_tu_call_edges"] >= 1
        assert result.stats["resolved_cross_tu_call_edges"] >= 1
        assert result.stats["propagated_mmio_edges"] >= 1


def test_inlined_read_return_binds_the_caller_lhs():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(
        REHARNESS, "tests", "fixtures", "read_return.c")
    result = extract_ris(ExtractorConfig(source=source))
    leaves = list(walk_leaf_ops(
        _module(result.formal, "read_return_update")["ops"]))
    read = next(op["Read"] for op in leaves if "Read" in op)
    write = next(op["Write"] for op in leaves if "Write" in op)
    assert read["var"] == "value"
    rendered = expr_display(write["value"])
    assert "value" in rendered and "mask" in rendered


def test_real_linux_dwc2_ten_source_driver_models_usb_callbacks_and_state():
    result = extract_ris(ExtractorConfig(source=DWC2_MULTI))
    assert result.stats["translation_units"] == 10
    assert result.stats["source_lines"] >= 21000
    assert result.stats["functions_analyzed"] >= 400
    assert result.stats["cross_tu_call_edges"] >= 100
    assert result.stats["resolved_cross_tu_call_edges"] == \
        result.stats["cross_tu_call_edges"]
    assert result.stats["propagated_mmio_edges"] >= 400
    assert result.stats["total_ops"] >= 3000
    assert result.stats["mmio_writes"] >= 800

    callback_tables = {
        fn.callback_table for fn in result.device_spec.functions
        if fn.callback_table
    }
    assert any(table.startswith("usb_ep_ops.") for table in callback_tables)
    assert any(table.startswith("usb_gadget_ops.") for table in callback_tables)
    assert any(table.startswith("hc_driver.") for table in callback_tables)
    state = {field.name: field.type for field in result.device_spec.state}
    assert state["enabled"] == "Bool"
    assert state["halted"] == "Bool"
    assert state["dma"] == "UInt64"
    assert state["frame_number"] == "UInt"


def test_real_linux_c67x00_multisource_driver():
    from extractor.metrics import count_clang_errors, driver_metrics

    result = extract_ris(ExtractorConfig(source=C67X00_MULTI))
    assert result.stats["translation_units"] == 4
    assert result.stats["source_lines"] == 2239
    assert result.stats["functions_analyzed"] == 89
    assert all("/linux/drivers/usb/c67x00/" in source
               for source in result.stats["source_files"])
    assert count_clang_errors(result.warnings) == 0

    modules = {module["name"] for module in result.formal["modules"]}
    # Wrapper summaries now carry the low-level HPI register primitives
    # through the host-controller callback layer instead of stopping at the
    # top-level IRQ/probe entries.
    assert modules == {
        "c67x00_irq", "c67x00_drv_probe", "c67x00_hub_status_data",
        "c67x00_hub_control", "c67x00_hcd_irq", "c67x00_hcd_get_frame",
        "c67x00_urb_enqueue",
    }
    metrics = driver_metrics(result.formal)
    assert metrics["total_ops"] == 38
    assert metrics["computed"] == 32
    assert metrics["unsafe_computed"] == 0
    assert metrics["unknown_value"] == 0
    control = result.formal["metadata"]["control_accounting"]
    assert control["unsupported"] == 0
    assert control["modeled_forward_gotos"] >= 16
    assert control["cfg"]["complete"] is True
    assert result.stats["alias_analysis"]["whole_program_complete"] is False
    state = {field.name: field for field in result.device_spec.state}
    assert state["base"].bind == "hpi.base"
    assert state["hpi_regstep"].type == "UInt"
    assert state["hpi_regstep"].bind == "hpi.regstep"
    assert state["sie_num"].bind == "sie.sie_num"
    assert result.facts.callbacks["platform_driver.probe"] == "c67x00_drv_probe"
    assert result.facts.callbacks["irq_handler.handler"] == "c67x00_irq"

    code = _linux_generate_and_compile(C67X00_MULTI, "rh_test_c67x00")
    assert "u32 hpi_regstep;" in code
    assert '"hpi-regstep"' in code
    assert '"sie-number"' in code
    assert "#define SOFEOP_TO_HPI_EN(x)" in code
    assert "HPI_STATUS * g->hpi_regstep" in code
    assert "value = readw((base + (HPI_DATA * g->hpi_regstep)))" in code
    assert "writew((value |" in code
    assert "SOFEOP_TO_HPI_EN(g->sie_num)" in code
    assert "SOFEOP_FLG(g->sie_num)" in code
    assert "0 + (HPI_" not in code


def test_real_linux_aspeed_vhub_five_source_driver():
    from extractor.metrics import count_clang_errors, driver_metrics

    result = extract_ris(ExtractorConfig(source=ASPEED_VHUB_MULTI))
    assert result.stats["translation_units"] == 5
    assert result.stats["source_lines"] == 3540
    assert result.stats["functions_analyzed"] == 92
    assert count_clang_errors(result.warnings) == 0

    metrics = driver_metrics(result.formal)
    assert len(result.formal["modules"]) == 15
    assert metrics["total_ops"] == 154
    assert metrics["symbolic"] == 114
    # Declaration-initialized reads (``u32 val = readl(...)``) now retain
    # their caller LHS, exposing seven additional genuine RMW chains.
    assert metrics["rmw"] == 21
    assert metrics["register_map"] == 22
    assert metrics["unknown_value"] == 0
    # Object-like macros whose definitions begin with parentheses must be
    # recovered from the driver's local header, not mistaken for functions.
    assert result.facts.constants["VHUB_IRQ_EP_POOL_ACK_STALL"] == (1 << 16)
    assert result.facts.constants["VHUB_SW_RESET_ROOT_HUB"] == 1


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
    extraction."""
    res = extract_ris(ExtractorConfig(source=FTGPIO))
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
    assert ack.is_callback_entry and ack.callback_table == "irq_chip.irq_ack"


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
    assert s["backend_harness_ready"] is True
    assert s["backend_bare_metal_ready"] is True
    assert s["backend_linux_ready"] is True
    assert not any("unknown (Top)" in b for b in s["blockers"])
    assert 0 <= s["function_spec_quality"] <= 1.0


def test_computed_address_lowering_distinguishes_safe_and_unsafe():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics, score

    pl061 = extract_ris(ExtractorConfig(source=PL061))
    addrs = []
    for module in pl061.formal["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if body and "Computed" in body.get("addr", {}):
                addrs.append(body["addr"]["Computed"])
    assert len(addrs) == 4
    assert all(expr_to_c(addr) ==
               "(pl061->base + (0x1 << (offset + 0x2)))" for addr in addrs)
    metrics = driver_metrics(pl061.formal)
    assert metrics["computed"] == 4 and metrics["unsafe_computed"] == 0
    ready = score(pl061.device_spec, pl061.formal, pl061.warnings, pl061.facts)
    assert ready["backend_bare_metal_ready"] is True

    mb86 = extract_ris(ExtractorConfig(source=MB86S7X))
    metrics = driver_metrics(mb86.formal)
    assert metrics["computed"] > 0
    assert metrics["unsafe_computed"] == metrics["computed"]
    blocked = score(mb86.device_spec, mb86.formal, mb86.warnings, mb86.facts)
    assert blocked["backend_bare_metal_ready"] is False
    assert any("unsafe dynamic register address" in b for b in blocked["blockers"])


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
    # real virtio_mmio facts: only VIRTIO_* register/status constants
    fv = extract_ris(ExtractorConfig(
        source=os.path.join(REHARNESS, "drivers", "test", "virtio_mmio.c"))).facts
    assert all(k.startswith("VIRTIO_") for k in fv.constants)


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
                 f"{name}.harness.bind", "score.txt"):
        assert need in files, f"missing {need}"


# ── extraction configuration / optional SVF regressions ─────────────

def test_extraction_cache_respects_inline_depth():
    """Changing analysis configuration must not reuse a path-only cache."""
    import tempfile
    src = textwrap.dedent("""
        #define REG 0x10
        static void helper(void *b) {
            writel(1, b + REG);
            writel(2, b + REG);
        }
        static void caller(void *b) { helper(b); }
    """)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "cache.c")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(src)
        deep = extract_ris(ExtractorConfig(
            source=p, linux_root="/nonexistent", max_inline_depth=3))
        shallow = extract_ris(ExtractorConfig(
            source=p, linux_root="/nonexistent", max_inline_depth=0))
        assert any(m["name"] == "caller" for m in deep.formal["modules"])
        assert not any(m["name"] == "caller" for m in shallow.formal["modules"])


def test_framework_and_blacklist_options_are_effective():
    import tempfile
    src = textwrap.dedent("""
        #define REG 0x10
        static void kmalloc(void *b) { writel(1, b + REG); }
        static void caller(void *b) { kmalloc(b); }
    """)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "framework.c")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(src)
        filtered = extract_ris(ExtractorConfig(source=p, linux_root="/nonexistent"))
        included = extract_ris(ExtractorConfig(
            source=p, linux_root="/nonexistent", include_framework=True))
        blacklisted = extract_ris(ExtractorConfig(
            source=p, linux_root="/nonexistent", include_framework=True,
            extra_blacklist=["kmalloc"]))
        assert not any(m["name"] == "caller" for m in filtered.formal["modules"])
        assert any(m["name"] == "caller" for m in included.formal["modules"])
        assert not any(m["name"] == "caller" for m in blacklisted.formal["modules"])


def test_callback_binding_uses_enclosing_struct_type():
    from extractor.spec_infer import parse_callback_bindings
    src = textwrap.dedent("""
        static int chip_get(void *gc, unsigned int n) { return 0; }
        static int pci_probe(void *pdev, void *id) { return 0; }
        static const struct gpio_chip chip = { .get = chip_get };
        static struct pci_driver drv = { .probe = pci_probe };
    """)
    got = parse_callback_bindings(src, {"chip_get", "pci_probe"})
    assert got["chip_get"]["table"] == "gpio_chip"
    assert got["chip_get"]["field"] == "get"
    assert got["pci_probe"]["table"] == "pci_driver"
    assert got["pci_probe"]["field"] == "probe"


def test_callback_binding_covers_irq_pm_and_clock_forms():
    from extractor.spec_infer import parse_callback_bindings
    src = textwrap.dedent("""
        static int gpio_init_hw(struct gpio_chip *gc) { return 0; }
        static int irq_fn(int irq, void *data) { return 0; }
        static int suspend_fn(struct device *dev) { return 0; }
        static int resume_fn(struct device *dev) { return 0; }
        static int clk_prepare(struct clk_hw *hw) { return 0; }
        static int clk_set_rate(struct clk_hw *hw, unsigned long rate,
                                unsigned long parent_rate) { return 0; }
        static const struct gpio_irq_chip girq = { .init_hw = gpio_init_hw };
        static const struct clk_ops cops = {
            .prepare = clk_prepare,
            .set_rate = clk_set_rate,
        };
        DEFINE_SIMPLE_DEV_PM_OPS(pm, suspend_fn, resume_fn);
        static int probe(void) {
            return request_irq(1, irq_fn, 0, "test", 0);
        }
    """)
    names = {"gpio_init_hw", "irq_fn", "suspend_fn", "resume_fn",
             "clk_prepare", "clk_set_rate"}
    got = parse_callback_bindings(src, names)
    assert got["gpio_init_hw"]["table"] == "gpio_irq_chip"
    assert got["irq_fn"]["table"] == "irq_handler"
    assert got["suspend_fn"]["table"] == "dev_pm_ops"
    assert got["resume_fn"]["field"] == "resume"
    assert got["clk_prepare"]["table"] == "clk_ops"
    assert got["clk_set_rate"]["field"] == "set_rate"


def test_callback_binding_dynamic_gpio_irq_chip_init_hw():
    from extractor.spec_infer import parse_callback_bindings
    src = textwrap.dedent("""
        static int gpio_init_hw(struct gpio_chip *gc) { return 0; }
        static int probe(struct platform_device *pdev) {
            struct gpio_irq_chip *girq;
            girq->init_hw = gpio_init_hw;
            return 0;
        }
    """)
    got = parse_callback_bindings(src, {"gpio_init_hw", "probe"})
    assert got["gpio_init_hw"]["table"] == "gpio_irq_chip"
    assert got["gpio_init_hw"]["field"] == "init_hw"


def test_source_private_state_is_preserved_in_specs_and_codegen():
    from extractor.spec import default_bind
    from generator import linux as linux_gen

    cadence = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "gpio-cadence.c")))
    assert {"bypass_orig", "skip_init", "ngpio"} <= {
        field.name for field in cadence.device_spec.state}
    cadence_code = linux_gen.generate(
        cadence.formal, cadence.device_spec,
        default_bind(cadence.device_spec, "linux"), cadence.facts)
    assert "REHARNESS_UNSUPPORTED" not in cadence_code

    pl061 = extract_ris(ExtractorConfig(source=PL061))
    assert {"gpio_dir", "gpio_is", "gpio_ibe", "gpio_iev", "gpio_ie"} <= {
        field.name for field in pl061.device_spec.state}
    pl061_code = linux_gen.generate(
        pl061.formal, pl061.device_spec,
        default_bind(pl061.device_spec, "linux"), pl061.facts)
    assert "g->gpio_is = readb" in pl061_code
    assert "writeb(g->gpio_ie" in pl061_code
    assert "REHARNESS_UNSUPPORTED" not in pl061_code

    virtio = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "virtio_mmio.c")))
    assert {"features", "version"} <= {
        field.name for field in virtio.device_spec.state}

    clock = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "clk-highbank.c")))
    clock_code = linux_gen.generate(
        clock.formal, clock.device_spec,
        default_bind(clock.device_spec, "linux"), clock.facts)
    assert "struct clk_hw hw;" in clock_code
    assert "REHARNESS_UNSUPPORTED" not in clock_code
    assert "return vco_freq / (1 << divq);" in clock_code
    assert "clk_pll_calc(rate, parent_rate, &divq, &divf);" in clock_code
    assert "static const struct clk_ops clk_highbank_clk_pll_ops" in clock_code
    assert "static const struct clk_ops clk_highbank_periclk_ops" in clock_code
    assert 'compatible = "calxeda,hb-pll-clock"' in clock_code
    assert 'compatible = "calxeda,hb-emmc-clock"' in clock_code
    assert "devm_of_clk_add_hw_provider" in clock_code
    assert "devm_clk_get_optional_enabled" not in clock_code

    idt = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "gpio-idt3243x.c")))
    idt_code = linux_gen.generate(
        idt.formal, idt.device_spec,
        default_bind(idt.device_spec, "linux"), idt.facts)
    assert "REHARNESS_UNSUPPORTED" not in idt_code
    assert "static int idt_gpio_irq_init_hw(struct gpio_chip *gc)" in idt_code
    assert "g->gc.irq.init_hw = idt_gpio_irq_init_hw;" in idt_code


def test_highbank_clock_arithmetic_oracle_catches_mutations():
    from verification.clock_arithmetic_oracle import verify_highbank

    result = verify_highbank()
    assert result["baseline_passed"] is True
    assert result["baseline_cases"] >= 20
    assert result["mutations_caught"] == 3
    assert all(item["caught_cases"] > 0
               for item in result["mutations"].values())


def test_c67x00_hpi_differential_oracle_catches_mutations():
    from verification.c67x00_hpi_trace_oracle import verify_c67x00_hpi

    result = verify_c67x00_hpi()
    assert result["baseline_passed"] is True
    assert len(result["primitive_cases"]) == 5
    assert len(result["differential_cases"]) == 4
    assert result["mutations_caught"] == 4
    assert all(item["caught"] is True
               for item in result["mutations"].values())


def test_ris_semantic_fingerprint_catches_core_mutations():
    from verification.ris_mutation_oracle import verify_ris_mutations

    result = verify_ris_mutations()
    assert result["mutations_caught"] == 4
    assert all(item["caught"] for item in result["mutations"].values())


def test_machine_readable_reliability_report_distinguishes_strict_and_opaque():
    from verification.reliability_report import build_driver_report

    strict = build_driver_report(FTGPIO)
    assert strict["strict_reliable"] is True
    assert strict["audit"]["leaf_register_ops"] == 22
    assert strict["audit"]["duplicate_op_ids"] == []
    assert strict["claim_scope"]["whole_program_complete"] is False
    opaque = build_driver_report(os.path.join(
        REHARNESS, "tests", "fixtures", "opaque_access.c"))
    assert opaque["strict_reliable"] is False
    assert opaque["access_accounting"]["unsupported"] == 3


def test_original_c_and_ris_differential_trace_match():
    from verification.ris_trace_oracle import verify_path_state_trace

    result = verify_path_state_trace()
    assert all(case["matched"] for case in result["cases"].values())
    assert result["mutation_caught"] is True


def test_real_ftgpio_callback_and_ris_differential_trace_match():
    from verification.ftgpio_trace_oracle import verify_ftgpio_ack_trace

    result = verify_ftgpio_ack_trace()
    assert all(case["matched"] for case in result["cases"].values())
    assert result["mutation_caught"] is True


def test_visconti_clock_model_reports_conservative_boundary():
    from extractor.spec import default_bind
    from generator import linux as linux_gen
    from generator.linux import analyze_clock_source_model

    highbank = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "clk-highbank.c")))
    accepted = analyze_clock_source_model(
        highbank.facts, "clk_highbank_priv")
    assert accepted["supported"] is True
    assert len(accepted["groups"]) == 4

    visconti = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "pll.c")))
    rejected = analyze_clock_source_model(visconti.facts, "pll_priv")
    assert rejected["supported"] is False
    reasons = " ".join(rejected["reasons"])
    assert "pll_base" in reasons
    assert "rate_table" in reasons
    assert "lock" in reasons
    assert rejected["lowered_callbacks"] == []
    code = linux_gen.generate(
        visconti.formal, visconti.device_spec,
        default_bind(visconti.device_spec, "linux"), visconti.facts)
    # Aggregate-dependent macros cannot be replayed after their source struct
    # has been conservatively normalized to scalar generated state.
    assert "#define PLL_CREATE_FRACMODE" not in code


def test_verified_linux_specific_lowering_is_not_gated_by_generic_loops():
    from extractor.metrics import score

    highbank = extract_ris(ExtractorConfig(source=os.path.join(
        REHARNESS, "drivers", "test", "clk-highbank.c")))
    readiness = score(
        highbank.device_spec, highbank.formal, highbank.warnings,
        highbank.facts,
        gen_results={"linux": {
            "compiled": True, "syntax_ok": True,
            "has_todo": False, "unsupported": False,
        }})
    assert readiness["backend_harness_ready"] is False
    assert readiness["backend_bare_metal_ready"] is False
    assert readiness["backend_linux_ready"] is True


def test_sodaville_path_sensitive_local_mmio_and_irq_private_state():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics
    from extractor.spec import default_bind
    from generator import baremetal as baremetal_gen
    from generator import harness as harness_gen
    from generator import linux as linux_gen

    source = os.path.join(REHARNESS, "drivers", "test", "gpio-sodaville.c")
    result = extract_ris(ExtractorConfig(source=source))
    assert result.facts.constants["PCI_VENDOR_ID_INTEL"] == 0x8086
    assert result.facts.constants["PCI_DEVICE_ID_SDV_GPIO"] == 0x2E67
    assert result.facts.constants["SDV_NUM_PUB_GPIOS"] == 12
    module = _module(result.formal, "sdv_gpio_pub_set_type")
    leaves = list(walk_leaf_ops(module["ops"]))
    addresses = [
        (op.get("Read") or op.get("ReadModifyWrite"))["addr"]
        for op in leaves
    ]
    assert len(addresses) == 2
    assert all("Computed" in address for address in addresses)
    address_text = repr(addresses[0])
    assert "GPIT1R0" in address_text and "GPIT1R1" in address_text
    assert "d->hwirq" in address_text
    metrics = driver_metrics(result.formal)
    assert metrics["computed"] == 2
    assert metrics["unsafe_computed"] == 0

    harness = harness_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "harness"))
    baremetal = baremetal_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "baremetal"))
    linux = linux_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "linux"), result.facts)
    assert "REHARNESS_UNSUPPORTED" not in harness + baremetal + linux
    assert "return IRQ_NONE;" in linux
    assert "return -EINVAL;" in linux
    assert "generic_handle_domain_irq(g->gc.irq.domain" in linux
    assert "type_reg = base + GPIT1R0;" in linux
    assert "type_reg = base + GPIT1R1;" in linux
    assert "PCI_DEVICE(0x8086, 0x2e67)" in linux
    assert "g->gc.ngpio = 12;" in linux
    assert "g->gpio_data = readl(g->base + GPOUTR);" in linux
    assert "g->gpio_dir = readl(g->base + GPOER);" in linux
    assert "g->gc.get = gpio_sodaville_gpio_get;" in linux
    assert "g->gc.set = gpio_sodaville_gpio_set;" in linux
    assert "g->gc.direction_input = gpio_sodaville_gpio_direction_input;" in linux
    assert "g->gc.direction_output = gpio_sodaville_gpio_direction_output;" in linux
    assert "g->irqchip.irq_mask = gpio_sodaville_irq_mask;" in linux
    assert "g->irqchip.irq_unmask = gpio_sodaville_irq_unmask;" in linux
    assert "g->irqchip.irq_eoi = gpio_sodaville_irq_eoi;" in linux
    assert "g->gc.irq.handler = handle_fasteoi_irq;" in linux
    assert "writel(g->irq_mask_cache, g->base + GPIO_INT);" in linux
    assert "writel(bit, g->base + GPSTR);" in linux


def test_source_private_normalization_keeps_bitwise_and_valid():
    from generator.linux import _normalize_text

    bitwise, changed = _normalize_text("readl(base + sreg) & sclk->clkbit")
    assert changed is True
    assert bitwise == "readl(base + sreg) & 0"
    address, changed = _normalize_text("req == &u_req->req")
    assert changed is True
    assert address == "req == 0"
    address_term, changed = _normalize_text("&u_req->req")
    assert changed is True
    assert address_term == "0"


def test_target_clang_diagnostics_are_separate_from_header_noise():
    from extractor.metrics import count_clang_errors

    assert count_clang_errors([
        "clang header diag[3] /kernel/header.h:1: frontend mismatch",
        "clang diag[2] driver.c:1: warning",
    ]) == 0
    assert count_clang_errors(["clang diag[3] driver.c:1: real source error"]) == 1

    for filename in ("ahci.c", "sdhci-esdhc-mcf.c"):
        result = extract_ris(ExtractorConfig(source=os.path.join(
            REHARNESS, "drivers", "test", filename)))
        assert count_clang_errors(result.warnings) == 0, result.warnings


def test_svf_required_reports_missing_tools_without_temp_leaks():
    import tempfile
    keys = ("REHARNESS_SVF_ROOT", "REHARNESS_SVF_SETUP", "REHARNESS_SVF_WPA",
            "REHARNESS_SVF_CLANG", "REHARNESS_SVF_LLVM_AS")
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ[k] = f"/nonexistent/{k.lower()}"
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "alias.c")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("static void f(void *b) { writel(1, b); }\n")
            try:
                extract_ris(ExtractorConfig(
                    source=p, linux_root="/nonexistent", alias_mode="required"))
            except RuntimeError as e:
                assert "SVF tools missing" in str(e)
            else:
                raise AssertionError("required SVF mode accepted missing tools")
    finally:
        for k, value in old.items():
            if value is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = value


def test_svf_positive_alias_is_typed_and_attached_to_ris_evidence():
    from extractor.alias import _tool_paths
    from extractor.formal import walk_leaf_ops

    if not all(os.path.isfile(path) for path in _tool_paths()[1:]):
        return
    source = os.path.join(REHARNESS, "tests", "fixtures", "svf_alias.c")
    result = extract_ris(ExtractorConfig(
        source=source, alias_mode="required"))
    analysis = result.stats["alias_analysis"]
    assert analysis["status"] == "success"
    assert result.stats["svf_aliases"] == ["alias"]
    assert analysis["facts"]["alias"]["accepted"] is True
    assert analysis["toolchain"]["clang_version"]
    op = next(walk_leaf_ops(result.formal["modules"][0]["ops"]))
    evidence = op["Write"]["evidence"]
    assert evidence["alias_provenance"]["name"] == "alias"
    assert evidence["alias_provenance"]["kind"] == "MayAlias"


def test_svf_manifest_link_propagates_alias_across_translation_units():
    from extractor.alias import _tool_paths
    from extractor.formal import walk_leaf_ops

    if not all(os.path.isfile(path) for path in _tool_paths()[1:]):
        return
    fixture = os.path.join(
        REHARNESS, "tests", "fixtures", "svf_linked.json")
    user_source = os.path.abspath(os.path.join(
        REHARNESS, "tests", "fixtures", "svf_linked_user.c"))
    isolated = extract_ris(ExtractorConfig(
        source=user_source, alias_mode="required"))
    assert isolated.stats["svf_aliases"] == []

    result = extract_ris(ExtractorConfig(
        source=fixture, alias_mode="required"))
    analysis = result.stats["alias_analysis"]

    assert analysis["status"] == "success"
    assert analysis["scope"] == "linked-manifest"
    assert analysis["translation_units"] == 2
    assert analysis["linked_alias_complete"] is True
    assert len(analysis["linked_bitcode_sha256"]) == 64
    assert analysis["aliases_by_source"][user_source] == ["linked_alias"]
    assert analysis["facts_by_source"][user_source]["linked_alias"][
        "scope"] == "linked-manifest"
    assert analysis["whole_program_complete"] is True
    assert all(analysis["whole_program_gates"].values())
    assert result.formal["metadata"]["assurance_scope"][
        "whole_program_scope"] == "manifest-internal"
    assert result.formal["metadata"]["assurance_scope"][
        "whole_program_complete"] is True

    module = _module(result.formal, "svf_linked_alias_use")
    op = next(walk_leaf_ops(module["ops"]))
    evidence = op["Write"]["evidence"]
    assert evidence["alias_provenance"]["name"] == "linked_alias"
    assert evidence["alias_provenance"]["scope"] == "linked-manifest"


def test_svf_manifest_required_does_not_fallback_without_llvm_link():
    key = "REHARNESS_SVF_LLVM_LINK"
    old = os.environ.get(key)
    try:
        os.environ[key] = "/nonexistent/llvm-link"
        fixture = os.path.join(
            REHARNESS, "tests", "fixtures", "svf_linked.json")
        try:
            extract_ris(ExtractorConfig(
                source=fixture, alias_mode="required"))
        except RuntimeError as exc:
            assert "linked-analysis tools missing" in str(exc)
            assert "llvm-link" in str(exc)
        else:
            raise AssertionError("required linked SVF silently fell back")
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def test_svf_auto_mode_reports_tool_failure_instead_of_silent_empty_aliases():
    keys = ("REHARNESS_SVF_ROOT", "REHARNESS_SVF_SETUP", "REHARNESS_SVF_WPA",
            "REHARNESS_SVF_CLANG", "REHARNESS_SVF_LLVM_AS")
    old = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = f"/nonexistent/auto/{key.lower()}"
        source = os.path.join(REHARNESS, "tests", "fixtures", "svf_alias.c")
        result = extract_ris(ExtractorConfig(
            source=source, alias_mode="auto"))
        assert result.stats["alias_analysis"]["status"] == "missing_tools"
        assert result.stats["svf_aliases"] == []
        assert any("SVF alias analysis missing_tools" in warning
                   for warning in result.warnings)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _linux_generate_and_compile(source: str, module_name: str):
    import subprocess
    import tempfile
    from extractor.spec import default_bind
    from generator import linux as linux_gen

    res = extract_ris(ExtractorConfig(source=source))
    bind = default_bind(res.device_spec, "linux")
    code = linux_gen.generate(res.formal, res.device_spec, bind, res.facts)
    assert "TODO" not in code
    build = os.path.join(REHARNESS, "kernel", "build")
    if not os.path.isfile(os.path.join(build, "Makefile")):
        return code
    with tempfile.TemporaryDirectory() as d:
        cpath = os.path.join(d, f"{module_name}.c")
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write(code)
        with open(os.path.join(d, "Makefile"), "w", encoding="utf-8") as fh:
            fh.write(f"obj-m += {module_name}.o\n")
        run = subprocess.run(
            ["make", "-C", build, f"M={d}", "modules"],
            capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
    return code


def test_linux_backend_kernel_builds_gpio_and_edu():
    gpio = _linux_generate_and_compile(FTGPIO, "rh_test_gpio")
    edu = _linux_generate_and_compile(EDU, "rh_test_edu")
    assert "module_platform_driver" in gpio
    assert "module_pci_driver" in edu and "struct miscdevice misc" in edu
    assert "REHARNESS_UNSUPPORTED" not in gpio + edu


def test_ahci_linux_backend_builds_with_explicit_limitation():
    ahci = os.path.join(REHARNESS, "drivers", "test", "ahci.c")
    code = _linux_generate_and_compile(ahci, "rh_test_ahci")
    assert "module_pci_driver" in code
    assert "REHARNESS_UNSUPPORTED" in code


# ── standalone runner (no pytest required) ───────────────────────────

def _run_standalone():
    import traceback
    formal = extract_ris(ExtractorConfig(source=FTGPIO)).formal
    fixtures = {"ftgpio_formal": formal}
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
