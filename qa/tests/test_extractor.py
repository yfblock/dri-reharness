"""Pytest/standalone tests for the reharness extractor (.ris spec language)."""
import json
import os
import re
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
if __package__:
    from ._bootstrap import (LINUX_ROOT, QA_ROOT, REPO_ROOT,
                             ROOT_STR as REHARNESS, SOURCE_ROOT,
                             resolve_logical)
else:
    from _bootstrap import (LINUX_ROOT, QA_ROOT, REPO_ROOT,
                            ROOT_STR as REHARNESS, SOURCE_ROOT,
                            resolve_logical)

from extractor import macros as M  # noqa: E402
from extractor import taint as T  # noqa: E402
from ast_analyzer import read_kbuild_command, resolve_compile_context  # noqa: E402
from extractor.dataflow import eval_expr, resolve_addr  # noqa: E402
from extractor.extractor import ExtractorConfig, extract_ris  # noqa: E402
from extractor.formal import expr_to_c, formal_display, parse_expr  # noqa: E402
from verification.check_generalization_guard import check_guard  # noqa: E402
from gate.callback_binding_oracle import (  # noqa: E402
    compare_reports as compare_callback_binding_reports,
    mutation_self_test as callback_binding_mutation_self_test,
)
from verification.materialize_holdout_contexts import validate_recipes  # noqa: E402
from verification.run_zero_shot_matrix import (  # noqa: E402
    cluster_blockers,
    normalize_blocker,
)


BASELINE_ROOT = os.fspath(REPO_ROOT / "benchmarks/drivers/baseline")
HOLDOUT_ROOT = os.fspath(REPO_ROOT / "benchmarks/drivers/holdout")
MULTISOURCE_ROOT = os.fspath(REPO_ROOT / "benchmarks/drivers/multisource")
FIXTURES_ROOT = os.fspath(QA_ROOT / "tests" / "fixtures")
GATE_ROOT = os.fspath(SOURCE_ROOT / "gate")
LINUX_SOURCE_ROOT = os.fspath(LINUX_ROOT)
REPORTING_TOOLS_ROOT = os.fspath(REPO_ROOT / "tools/reporting")
SOURCE_TOOLS_ROOT = os.fspath(REPO_ROOT / "tools/source")
_PYTHON_ENV = os.environ.copy()
_PYTHON_ENV["PYTHONPATH"] = os.pathsep.join(
    (str(SOURCE_ROOT), str(QA_ROOT)))


# ── helpers ──────────────────────────────────────────────────────────


def _ast_callback_bindings(source: str) -> dict[str, dict]:
    import tempfile
    import clang.cindex as cx
    from ast_analyzer import tu as tu_mod
    from ast_analyzer import target_functions
    from extractor.spec_infer import infer_callback_bindings

    tu_mod._configure()
    with tempfile.NamedTemporaryFile(
            "w", suffix=".c", delete=False, encoding="utf-8") as handle:
        handle.write(source)
        path = handle.name
    try:
        tu = cx.Index.create().parse(path, args=["-std=gnu11"])
        funcs = target_functions(tu, path)
        by_symbol = infer_callback_bindings(tu, funcs)
        return {info["function"]: info for info in by_symbol.values()}
    finally:
        os.unlink(path)


def test_zero_shot_holdout_is_frozen_and_not_special_cased():
    report = check_guard()
    assert report["cases"] == 12
    assert report["first_run"] == "gpio-altera"
    assert report["passed"], report["issues"]


def test_zero_shot_context_recipe_exactly_matches_frozen_sources():
    import json
    from pathlib import Path

    holdout = json.loads((
        Path(HOLDOUT_ROOT) / "zero-shot-v1.json"
    ).read_text(encoding="utf-8"))
    recipes = json.loads((
        Path(HOLDOUT_ROOT) / "zero-shot-v1-contexts.json"
    ).read_text(encoding="utf-8"))
    assert validate_recipes(holdout, recipes) == []


def test_zero_shot_v2_guard_reports_post_baseline_implementation_changes():
    path = os.path.join(HOLDOUT_ROOT, "zero-shot-v2.json")
    report = check_guard(path)
    assert report["passed"], report["issues"]
    assert "extractor" in report["protected_root_changes"]
    frozen = check_guard(path, enforce_frozen_implementation=True)
    assert not frozen["passed"]
    assert any("protected root changed" in issue for issue in frozen["issues"])


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
    assert normalize_blocker(
        "linux backend has 35 emitted definition operation(s) without "
        "independent runtime registration/callsite attestation"
    ) == "linux_runtime_attestation"
    assert normalize_blocker(
        "linux backend has 12 strict candidate operation(s) without "
        "independent runtime registration/callsite attestation"
    ) == "linux_runtime_attestation"
    assert normalize_blocker(
        "harness backend has 8 register operation(s) explicitly blocked by "
        "unsupported loop lowering"
    ) == "unsupported_loop_lowering"
    assert normalize_blocker(
        "linux backend has 3 register operation(s) explicitly blocked by "
        "a synthesized lifecycle stub"
    ) == "linux_lifecycle_stub"
    assert normalize_blocker(
        "linux backend has 2 register operation(s) explicitly blocked by "
        "an unimplemented lifecycle route"
    ) == "linux_lifecycle_unimplemented"
    assert normalize_blocker(
        "linux backend has 9 register operation(s) explicitly blocked by "
        "a missing Linux definition root"
    ) == "linux_definition_root"
    assert normalize_blocker(
        "linux backend lowering receipt reconciliation failed"
    ) == "lowering_reconciliation"
    assert normalize_blocker(
        "linux backend has 1 unexplained RIS lowering accounting "
        "discrepancy/discrepancies"
    ) == "lowering_accounting_discrepancy"
    rows = [
        {"driver": f"case-{index}", "blockers": [
            "1 conservative loop summary/summaries require validation",
            "linux backend has 35 emitted definition operation(s) without "
            "independent runtime registration/callsite attestation",
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


def test_callback_binding_baseline_oracle_catches_boundary_mutations():
    import json
    from pathlib import Path

    root = Path(REHARNESS)
    baseline = json.loads((
        root / "research" / "experiments" / "results" /
        "zero-shot-v2-matrix.json"
    ).read_text(encoding="utf-8"))
    candidate_path = (
        root / "research" / "experiments" / "results" /
        "zero-shot-v2-callback-binding.json")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert compare_callback_binding_reports(baseline, candidate) == []
    assert callback_binding_mutation_self_test(baseline, candidate) == []


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


def test_generic_gpio_library_summary_materializes_callbacks_and_tracks_mutation():
    import tempfile
    from pathlib import Path
    from extractor.formal import expr_display, walk_leaf_ops

    template = r'''
        #define DAT 0x00
        #define SET {set_offset}
        #define DIR 0x08
        struct gpio_generic_chip {{ int gc; }};
        struct gpio_generic_chip_config {{
            void *dev; unsigned long sz; void *dat; void *set; void *clr;
            void *dirout; void *dirin; unsigned long flags;
        }};
        extern void *devm_platform_ioremap_resource(void *pdev, int index);
        extern int gpio_generic_chip_init(struct gpio_generic_chip *chip,
                                          const struct gpio_generic_chip_config *cfg);
        static int demo_probe(void *pdev) {{
            struct gpio_generic_chip chip;
            struct gpio_generic_chip_config config;
            void *base = devm_platform_ioremap_resource(pdev, 0);
            config = (struct gpio_generic_chip_config) {{
                .sz = 4, .dat = base + DAT, .set = base + SET,
                .dirout = base + DIR,
            }};
            return gpio_generic_chip_init(&chip, &config);
        }}
    '''

    def run(offset):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generic_gpio_fixture.c"
            source.write_text(template.format(set_offset=offset), encoding="utf-8")
            result = extract_ris(ExtractorConfig(
                source=str(source), compile_context_mode="off"))
            return result

    baseline = run("0x04")
    mutated = run("0x0c")
    assert baseline.stats["synthetic_subsystem_functions"] == 7
    summary = baseline.stats["subsystem_summaries"]["gpio_generic"][0]
    assert summary["callbacks"] == [
        "gpio_chip.get", "gpio_chip.get_multiple", "gpio_chip.set",
        "gpio_chip.set_multiple", "gpio_chip.direction_input",
        "gpio_chip.direction_output", "gpio_chip.get_direction",
    ]
    assert all("generic_gpio_fixture" not in repr(item)
               for item in baseline.stats["subsystem_summaries"].get(
                   "unmodeled_callbacks", []))
    set_module = next(module for module in baseline.formal["modules"]
                      if module["name"].endswith("__gpio_generic_set"))
    set_leaves = list(walk_leaf_ops(set_module["ops"]))
    assert [next(iter(op)) for op in set_leaves] == [
        "StateRead", "StateWrite", "Write", "Return"]
    set_op = next(op["Write"] for op in set_leaves if "Write" in op)
    assert set_op["evidence"]["summary_contract"] == (
        "linux.gpio_generic_chip_config")
    assert set_op["evidence"]["origin"] == "subsystem_summary"
    base_regs = {reg["name"]: reg["offset"]
                 for reg in baseline.formal["register_map"]}
    mutated_regs = {reg["name"]: reg["offset"]
                    for reg in mutated.formal["register_map"]}
    assert base_regs["SET"] == 0x04
    assert mutated_regs["SET"] == 0x0c



def test_sdhci_ops_summary_models_accessors_and_reports_unknown_core_callbacks():
    import tempfile
    from pathlib import Path

    source_text = r'''
        typedef unsigned int u32;
        struct sdhci_host { void *ioaddr; };
        struct sdhci_ops {
            u32 (*read_l)(struct sdhci_host *, int);
            void (*write_l)(struct sdhci_host *, u32, int);
            void (*set_clock)(struct sdhci_host *, unsigned int);
        };
        extern u32 sdhci_readl(struct sdhci_host *host, int reg);
        extern void sdhci_writel(struct sdhci_host *host, u32 value, int reg);
        extern void sdhci_set_clock(struct sdhci_host *host, unsigned int hz);
        static void local_writel(struct sdhci_host *host, u32 value, int reg) {
            sdhci_writel(host, value, reg);
        }
        static const struct sdhci_ops demo_ops = {
            .read_l = sdhci_readl,
            .write_l = local_writel,
            .set_clock = sdhci_set_clock,
        };
    '''
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "sdhci_ops_fixture.c"
        source.write_text(source_text, encoding="utf-8")
        result = extract_ris(ExtractorConfig(
            source=str(source), compile_context_mode="off"))
    summaries = result.stats["subsystem_summaries"]
    assert summaries["sdhci_ops"] == [{
        "table": "demo_ops", "field": "read_l", "callee": "sdhci_readl",
        "module": "demo_ops__read_l", "width_bytes": 4,
    }, {
        "table": "demo_ops", "field": "write_l", "callee": "local_writel",
        "module": "local_writel", "width_bytes": 4,
        "implementation": "source-private",
    }]
    assert summaries["unmodeled_callbacks"] == []
    assert summaries["sdhci_delegates"][0]["field"] == "set_clock"
    assert any(function.callback_table == "sdhci_ops.read_l"
               for function in result.device_spec.functions)
    assert summaries["sdhci_delegates"][0]["summary_contract"] == (
        "linux.sdhci_core_export")


def test_npcm_sdhci_accessor_source_contract_and_portable_boundary():
    import copy
    from extractor.formal import walk_leaf_ops
    from backends.subsystem_runner import portable_sdhci_accessor_only
    from backends.oracles.sdhci_accessor_oracle import (
        verify_sdhci_accessor_source_contract)

    npcm = os.path.join(LINUX_SOURCE_ROOT, "drivers", "mmc", "host",
                        "sdhci-npcm.c")
    result = extract_ris(ExtractorConfig(source=npcm))
    oracle = verify_sdhci_accessor_source_contract(result.formal)
    assert oracle["sdhci_accessor_oracle_passed"], oracle
    assert oracle["sdhci_accessor_oracle_ops"] == 1
    assert portable_sdhci_accessor_only(result.formal, result.device_spec)

    mutated = copy.deepcopy(result.formal)
    op = next(
        op for module in mutated["modules"]
        for op in walk_leaf_ops(module["ops"]) if "Read" in op)
    op["Read"]["width"] = "B2"
    mutation = verify_sdhci_accessor_source_contract(mutated)
    assert mutation["sdhci_accessor_oracle_passed"] is False
    assert any("expected" in error
               for error in mutation["sdhci_accessor_oracle_errors"])



def test_virtio_config_and_queue_calls_are_distinct_unsupported_domains():
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    from extractor import mmio
    from extractor.formal import walk_leaf_ops

    fake = SimpleNamespace(
        callee_text=("virtio_cread_le(vdev, struct demo_config, value, &out)"),
        arg_text=[])
    assert mmio.effective_access_name(
        "__virtio_cread_many", fake.callee_text) == "virtio_cread_le"
    assert mmio.access_args("virtio_cread_le", fake) == [
        "vdev", "struct demo_config", "value", "&out"]

    source_text = r'''
        struct virtio_device { int unused; };
        struct virtqueue { int unused; };
        extern void virtio_cread_bytes(struct virtio_device *, unsigned int,
                                       void *, unsigned int);
        extern int virtqueue_add_outbuf(struct virtqueue *, void *, unsigned int,
                                       void *, int);
        extern void *virtqueue_get_buf(struct virtqueue *, unsigned int *);
        extern void virtqueue_kick(struct virtqueue *);
        static void demo(struct virtio_device *vdev, struct virtqueue *vq) {
            unsigned int value, len;
            virtio_cread_bytes(vdev, 4, &value, sizeof(value));
            virtqueue_add_outbuf(vq, 0, 1, &value, 0);
            (void)virtqueue_get_buf(vq, &len);
            virtqueue_kick(vq);
        }
    '''
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "virtio_domains_fixture.c"
        source.write_text(source_text, encoding="utf-8")
        result = extract_ris(ExtractorConfig(
            source=str(source), compile_context_mode="off"))
    domains = []
    for module in result.formal["modules"]:
        for op in walk_leaf_ops(module["ops"]):
            body = op.get("StateRead") or op.get("StateWrite")
            if body:
                domains.append(body["access_domain"])
                assert body["reliability"] == "Exact"
                assert body["evidence"]["origin"] == "subsystem_summary"
    assert domains.count("virtio_config") == 1
    assert domains.count("virtqueue") == 5
    assert result.stats["access_accounting"]["strict_complete"] is True
    assert result.stats["subsystem_summaries"]["virtio_state"] == [{
        "module": "demo", "config_ops": 1, "queue_ops": 5,
    }]


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
            "savedcmd_drivers/demo/demo.o := gcc -nostdinc "
            "--target=arm-linux-gnueabi -I./include "
            f"-I{linux}/include -include {linux}/include/demo.h "
            "-DDEMO_VALUE=7 -std=gnu11 -Wall -O2 -c -o "
            f"drivers/demo/demo.o {source} ; objtool demo.o\n",
            encoding="utf-8")
        context = resolve_compile_context(
            str(source), linux_root=str(linux), build_root=str(build),
            mode="required")
        assert context is not None
        assert context.origin == "kbuild-cmd"
        assert "--target=arm-linux-gnueabi" in context.arguments
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

    manifest_path = (
        Path(REHARNESS) / "benchmarks" / "drivers" / "holdout" /
        "zero-shot-v1.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = next(case for case in manifest["cases"]
                if case["id"] == manifest["first_run"])
    source = resolve_logical(manifest_path.parent, case["source"])
    result = extract_ris(ExtractorConfig(
        source=str(source), compile_context_mode="required"))
    assert result.stats["compile_context"]["origin"] == "kbuild-cmd"
    assert result.stats["functions_analyzed"] == 13
    assert result.stats["access_accounting"]["strict_complete"] is True
    assert result.stats["total_ops"] == 20
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

FTGPIO = os.path.join(BASELINE_ROOT, "gpio-ftgpio010.c")
EDU = os.path.join(BASELINE_ROOT, "edu.c")
PL061 = os.path.join(BASELINE_ROOT, "gpio-pl061.c")
TS4800 = os.path.join(LINUX_SOURCE_ROOT, "drivers", "gpio", "gpio-ts4800.c")
GPIO_GE = os.path.join(LINUX_SOURCE_ROOT, "drivers", "gpio", "gpio-ge.c")
GPIO_CLPS711X = os.path.join(
    LINUX_SOURCE_ROOT, "drivers", "gpio", "gpio-clps711x.c")
GPIO_DWAPB = os.path.join(
    LINUX_SOURCE_ROOT, "drivers", "gpio", "gpio-dwapb.c")
MB86S7X = os.path.join(BASELINE_ROOT, "gpio-mb86s7x.c")
C67X00_MULTI = os.path.join(MULTISOURCE_ROOT, "c67x00.json")
ASPEED_VHUB_MULTI = os.path.join(
    MULTISOURCE_ROOT, "aspeed-vhub.json")
DWC2_MULTI = os.path.join(MULTISOURCE_ROOT, "dwc2.json")


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
    # IR-primary: GEP-verified Fixed offset + driver-local macro name
    assert a["Fixed"]["name"] == "GPIO_INT_EN"
    assert a["Fixed"]["offset"] == 0x20
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


def test_ftgpio_ack_irq_keeps_registration_and_direct_call_effects(ftgpio_formal):
    """A registered callback keeps its module and direct calls retain effects."""
    names = {m["name"] for m in ftgpio_formal["modules"]}
    assert "ftgpio_gpio_ack_irq" in names        # kept as its own module
    sit = _module(ftgpio_formal, "ftgpio_gpio_set_irq_type")
    leaves = []
    _leaf_ops(sit["ops"], leaves)
    # set_irq_type directly calls ack_irq, so its caller view must retain the
    # write while the callback module remains available for registration.
    ack_in_sit = any(
        "Write" in o and o["Write"]["addr"].get("Fixed", {}).get("name") == "GPIO_INT_CLR"
        for o in leaves)
    assert ack_in_sit


def test_formal_display_text(ftgpio_formal):
    txt = formal_display(ftgpio_formal)
    assert txt.startswith("driver gpio-ftgpio010 v0.4.0 {")
    assert "module ftgpio_gpio_probe" in txt
    assert "W(B4," in txt and " := R(B4," in txt
    assert "IF " in txt
    assert "-- Interrupt" in txt


# ── external call nodes (RIS 0.3.0) ──────────────────────────────────

def test_external_call_semantics_rule_table():
    from extractor.external_semantics import (
        EXTERNAL_CATEGORIES, classify, rule_category)

    assert "unknown" in EXTERNAL_CATEGORIES
    assert rule_category("kmalloc") == "alloc"
    assert rule_category("kmalloc_array") == "alloc"
    assert rule_category("devm_kzalloc") == "alloc"
    assert rule_category("kfree") == "free"
    assert rule_category("spin_lock_irqsave") == "lock"
    assert rule_category("spin_unlock_irqrestore") == "unlock"
    assert rule_category("mutex_lock_interruptible") == "lock"
    assert rule_category("dev_err") == "print"
    assert rule_category("pr_info_once") == "print"
    assert rule_category("dma_map_single") == "dma-map"
    assert rule_category("dma_sync_single_for_cpu") == "dma-sync"
    assert rule_category("dma_unmap_single") == "dma-unmap"
    assert rule_category("pm_runtime_get_sync") == "power-on"
    assert rule_category("devm_clk_get_enabled") == "power-on"
    assert rule_category("reset_control_assert") == "reset"
    assert rule_category("regmap_read") == "register-access"
    assert rule_category("memset") == "pure"
    assert rule_category("gpiochip_get_data") == "pure"
    # dev_* print stems must not swallow devm_* allocators
    assert rule_category("devm_kcalloc") == "alloc"
    # unknown names stay unknown instead of a guessed category
    assert rule_category("gpio_generic_chip_init") is None
    assert rule_category("") is None
    # clang renames TU-local static inlines with a "variable" prefix
    assert rule_category("variable__ffs") == "pure"
    # classify: annotation outranks the rule table; rule outranks unknown
    assert classify("kmalloc")["category"] == "alloc"
    assert classify("kmalloc")["source"] == "rule"
    overridden = classify("kmalloc", {"kmalloc": {
        "category": "alloc", "confidence": 0.95, "source": "kernel-tree"}})
    assert overridden["source"] == "annotation"
    assert overridden["confidence"] == 0.95
    assert classify("totally_bogus") == {
        "category": "unknown", "source": "unknown", "confidence": None}
    # a malformed annotation never crashes or wins
    assert classify("kmalloc", {"kmalloc": {"category": "not-a-category"}}
                    )["source"] == "rule"


def test_external_call_nodes_recorded(ftgpio_formal):
    """Every external dependency is a reviewable, classified RIS node."""
    formal = ftgpio_formal
    assert formal["version"] == "0.4.0"
    stats = formal["metadata"]["external_calls"]
    total = sum(len(m.get("external_calls") or [])
                for m in formal["modules"])
    assert total > 0
    assert stats["emitted_nodes"] == total
    assert sum(stats["by_category"].values()) == total
    assert stats["by_category"].get("unknown", 0) < total  # rules apply

    probe = next(m for m in formal["modules"]
                 if m["name"] == "ftgpio_gpio_probe")
    nodes = {(n["callee"], n["callsite"]["line"])
             for n in probe["external_calls"]}
    # framework dependencies surface with their deterministic category
    assert ("devm_clk_get_enabled", 259) in nodes
    assert ("dev_err_probe", 278) in nodes
    for node in probe["external_calls"]:
        if node["callee"] == "devm_kmalloc":
            assert node["category"] == "alloc"
            assert node["category_source"] == "rule"
            # header-helper provenance is explicit, not flattened away
            assert node["inlined_at"][0]["callee"] == "devm_kzalloc"

    all_nodes = [n for m in formal["modules"]
                 for n in m.get("external_calls") or []]
    # modeled accessors never double-account as external calls
    assert not any(n["callee"] in {
        "readl", "writel", "readb", "writeb"} for n in all_nodes)
    # compiler intrinsics are not external API surface
    assert not any(n["callee"].startswith("__builtin")
                   for n in all_nodes)
    for node in all_nodes:
        assert node["category"] and node["resolution_authority"] in {
            "external_declaration", "unresolved_indirect"}
        assert isinstance(node["arguments"], list)

    txt = formal_display(formal)
    assert "ExternalCall devm_clk_get_enabled(" in txt
    assert "via devm_kzalloc" in txt


# ── slim text + source map + expanded-call dedup (RIS 0.4.0) ─────────

def test_slim_text_and_source_map(ftgpio_formal):
    """The .ris text carries no inline locations; the side table does."""
    from extractor.source_map import build_source_map, lookup_source

    txt = formal_display(ftgpio_formal)
    assert "vendor/linux" not in txt          # no absolute paths inline
    assert ".c:" not in txt and ".h:" not in txt
    # op anchors stay (receipt lowering keys on them)
    assert " @op_" in txt

    source_map = ftgpio_formal.get("source_map")
    assert isinstance(source_map, dict) and source_map.get("anchors")
    # op anchors resolve back to file:line on demand
    op_anchor = next(a for a, entry in source_map["anchors"].items()
                     if a.startswith("op_"))
    resolved = lookup_source(source_map, [op_anchor, "not-an-anchor"])
    assert op_anchor in resolved and ".c:" in resolved[op_anchor]
    assert "not-an-anchor" not in resolved
    # a rebuilt map over the same formal is stable
    assert build_source_map(ftgpio_formal)["anchors"].keys() == \
        source_map["anchors"].keys()


def test_llm_render_drops_reliability_keeps_contract_anchors(ftgpio_formal):
    """include_reliability=False strips audit tags but never the contract.

    The LLM evidence render must keep `@op_N` and the receipt digest (the
    backend lowering keys on them) while dropping the human-audit
    [Exact]/[Conservative] tags, including LOOP headers.
    """
    from extractor.formal import op_display
    from backends.llm_bridge import _module_ris

    full = formal_display(ftgpio_formal)
    assert "[Exact]" in full or "[Conservative]" in full
    slim = _module_ris(ftgpio_formal["modules"][0])
    assert "[Exact]" not in slim and "[Conservative]" not in slim
    assert " @op_" in slim                      # op ids stay
    assert "digest=" in slim                    # receipt digests stay
    # direct flag check on a single op
    leaf = next(op for op in ftgpio_formal["modules"][0]["ops"]
                if op.get("Read") or op.get("Write"))
    body = leaf.get("Read") or leaf.get("Write")
    body["op_id"] = body.get("op_id") or "op_test"
    body["reliability"] = body.get("reliability") or "Exact"
    rid = body["op_id"]
    assert "[Exact]" in op_display(leaf)
    slim_one = op_display(leaf, include_reliability=False)
    assert "[Exact]" not in slim_one
    assert f"@{rid}" in slim_one


def test_call_nodes_dedup_expanded_and_carry_category(ftgpio_formal):
    """Call rows whose callee ops are in the module are not re-emitted.

    A helper flattened into a caller leaves op-evidence hops naming the
    very same callsite; emitting a Call node for that row would state the
    expansion twice.  Rows without ops in the caller (allocators,
    printers) stay, classified into the closed category set.
    """
    formal = ftgpio_formal
    stats = formal["metadata"]["call_graph"]["call_nodes"]
    total = sum(len(m.get("calls") or []) for m in formal["modules"])
    assert stats["emitted_nodes"] == total
    assert stats["suppressed_expanded"] >= 0
    # every surviving Call node is classified
    for module in formal["modules"]:
        for call in module.get("calls") or []:
            assert call["schema"] == 2
            assert call["category"]
            assert call["category_source"] in {
                "annotation", "rule", "unknown"}


def test_external_calls_suppress_op_modeled_sites(ftgpio_formal):
    """Wrapper calls rewritten into ops do not double-account as externals."""
    stats = ftgpio_formal["metadata"]["external_calls"]
    assert stats["suppressed_modeled"] >= 0
    # every emitted external node has no matching modeled-call op
    from extractor.formal import walk_leaf_ops
    for module in ftgpio_formal["modules"]:
        modeled = set()
        for op in walk_leaf_ops(module.get("ops") or []):
            body = next((v for v in op.values() if isinstance(v, dict)),
                        None)
            ev = (body or {}).get("evidence") or {}
            if ev.get("ast_kind") == "CALL_EXPR" and ev.get("callee"):
                modeled.add((ev.get("function"), ev.get("line")))
        for node in module.get("external_calls") or []:
            if node["resolution_authority"] != "unresolved_indirect":
                continue
            hops = node.get("inlined_at") or []
            owner = hops[-1]["function"] if hops else module["name"]
            line = ((hops[-1].get("line") if hops else None)
                    or node["callsite"]["line"])
            assert (owner, line) not in modeled, (module["name"], node)


def test_access_accounting_and_operation_evidence_are_complete():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics, score

    result = extract_ris(ExtractorConfig(source=FTGPIO))
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == 23
    assert accounting["emitted"] == 23
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
    assert len(op_ids) == len(set(op_ids)) == 36
    metrics = driver_metrics(result.formal)
    assert sum(metrics["reliability"].values()) == 36
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("attestation results unavailable" in blocker
               for blocker in readiness["blockers"])


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




def test_large_constant_bounded_loop_is_proved_without_unrolling():
    import tempfile
    from extractor.metrics import driver_metrics

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "large_bounded_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern u32 readl(void *addr);
void large_bounded_loop(void *base)
{
    unsigned int i;
    for (i = 0; i < 1000; i++)
        (void)readl(base + i * 4);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "large_bounded_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["count"] == {"Const": 1000}
    assert driver_metrics(result.formal)["conservative_loop"] == 0


def test_large_constant_bounded_loop_keeps_exact_source_shape():
    import tempfile
    from extractor.metrics import driver_metrics

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "larger_bounded_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern u32 readl(void *addr);
void larger_bounded_loop(void *base)
{
    unsigned int i;
    for (i = 0; i < 20000; i++)
        (void)readl(base + i * 4);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "larger_bounded_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["count"] == {"Const": 20000}
    assert driver_metrics(result.formal)["conservative_loop"] == 0



def test_runtime_scalar_alias_loop_is_proved_from_integer_bound_type():
    import tempfile
    from extractor.metrics import driver_metrics

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "runtime_scalar_alias_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern u32 readl(void *addr);
void runtime_scalar_alias_loop(void *base, u32 count)
{
    u32 limit = count;
    u32 i;
    for (i = 0; i < limit; i++)
        (void)readl(base + i * 4);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "runtime_scalar_alias_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["dynamic_bound"] is True
    assert loop["count"] == {"Var": "limit"}
    assert driver_metrics(result.formal)["conservative_loop"] == 0


def test_bounded_loop_allows_independent_cursor_step():
    import tempfile
    from extractor.metrics import driver_metrics

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "cursor_step_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern u32 readl(void *addr);
void cursor_step_loop(void *base, u32 count)
{
    u32 i;
    u32 *cursor = base;
    for (i = 0; i < count; i++, cursor++)
        *cursor = readl(base + i * 4);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "cursor_step_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["count"] == {"Var": "count"}
    assert driver_metrics(result.formal)["conservative_loop"] == 0


def test_runtime_post_decrement_loop_is_finitely_bounded():
    import tempfile
    from extractor.formal import expr_display
    from extractor.metrics import driver_metrics

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "post_decrement_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern void writel(u32 value, void *addr);
void post_decrement_loop(void *base, u32 count)
{
    while (count--)
        writel(count, base);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "post_decrement_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["dynamic_bound"] is True
    assert loop["count"] == {"Var": "count"}
    assert expr_display(loop["guard"]) == "count--"
    assert driver_metrics(result.formal)["conservative_loop"] == 0


def test_runtime_post_decrement_loop_with_guarded_retry_is_bounded():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "retry_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern int ready(void);
extern void writel(u32 value, void *addr);
void retry_loop(void *base, u32 retry)
{
    while (ready() && retry--)
        writel(retry, base);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "retry_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["count"] == {"Var": "retry"}


def test_runtime_post_decrement_comparison_with_guard_is_bounded():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "comparison_retry_loop.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
extern int ready(void);
extern void writel(u32 value, void *addr);
void comparison_retry_loop(void *base, int retry)
{
    while (ready() && (retry-- >= 0))
        writel(retry, base);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    loop = _module(result.formal, "comparison_retry_loop")["ops"][0]["Loop"]
    assert loop["reliability"] == "Exact"
    assert loop["bounded"] is True
    assert loop["dynamic_bound"] is True
    assert loop["count"] == {"Var": "retry"}


def test_macro_delay_expansion_without_hardware_leaves_does_not_block_readiness():
    import tempfile
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import driver_metrics, score

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "macro_delay.c")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write(r"""
typedef unsigned int u32;
struct macro_delay_dev { void *base; };
extern void udelay(unsigned int);
extern u32 readl(void *);
#define mdelay(n) ({ unsigned long __ms = (n); while (__ms--) udelay(1000); })
void macro_delay_then_read(struct macro_delay_dev *d)
{
    mdelay(3);
    (void)readl(d->base);
}
""")
        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent"))

    metrics = driver_metrics(result.formal)
    assert metrics["conservative_loop"] == 0
    leaves = list(walk_leaf_ops(result.formal["modules"][0]["ops"]))
    assert [item["Delay"]["cycles"] for item in leaves
            if "Delay" in item] == [{"Const": 3_000_000}]
    readiness = score(result.device_spec, result.formal,
                      result.warnings, result.facts)
    assert not any("conservative loop" in blocker
                   for blocker in readiness["blockers"])


def test_path_sensitive_assignment_store_builds_ite_write_value():
    from extractor.formal import expr_display

    source = os.path.join(FIXTURES_ROOT, "path_state.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "path_state")
    write = next(op["Write"] for op in module["ops"] if "Write" in op)
    assert "Ite" in write["value"]
    rendered = expr_display(write["value"])
    assert "select" in rendered
    assert "0x2" in rendered and "0x1" in rendered
    # IR-primary: GEP-verified Fixed offset + driver-local macro name
    assert write["addr"]["Fixed"]["name"] == "VALUE_REG"
    assert write["addr"]["Fixed"]["offset"] == 0x20
    assert write["reliability"] == "Exact"


def test_simple_early_return_becomes_continuation_guard():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(FIXTURES_ROOT, "early_return.c")
    result = extract_ris(ExtractorConfig(source=source))
    module = _module(result.formal, "early_return")
    assert len(module["ops"]) == 1 and "Cond" in module["ops"][0]
    cond = module["ops"][0]["Cond"]
    assert expr_display(cond["guard"]) == "enabled"
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 1
    assert leaves[0]["Write"]["addr"]["Fixed"]["name"] == "EARLY_REG"
    validation = result.formal["metadata"]["path_validation"]
    assert validation["complete"] is True
    assert validation["infeasible"] == 0
    control = result.formal["metadata"]["control_accounting"]
    assert control["modeled_early_returns"] == 1
    assert control["complete"] is True


def test_switch_cases_with_terminal_register_returns_are_cfg_complete():
    import tempfile

    source = textwrap.dedent(r"""
        typedef unsigned int u32;
        typedef unsigned short u16;
        struct state { void *regs; u32 width; };
        extern u16 readw_relaxed(void *addr);
        extern u32 readl_relaxed(void *addr);

        static u32 read_io(struct state *dws, u32 offset)
        {
            switch (dws->width) {
            case 2:
                return readw_relaxed(dws->regs + offset);
            case 4:
            default:
                return readl_relaxed(dws->regs + offset);
            }
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "switch_returns.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(
            source=path, linux_root="/nonexistent"))

    control = result.formal["metadata"]["control_accounting"]
    assert control["unsupported"] == 0, control["sites"]
    assert control["complete"] is True


def test_loop_continue_guards_following_register_accesses():
    import tempfile

    source = textwrap.dedent(r"""
        typedef unsigned int u32;
        extern u32 readl_relaxed(void *addr);

        static void drain(void *regs, u32 len)
        {
            while (len) {
                u32 entries = readl_relaxed(regs);
                if (!entries)
                    continue;
                readl_relaxed(regs + 4);
                --len;
            }
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "continue_loop.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(
            source=path, linux_root="/nonexistent"))

    control = result.formal["metadata"]["control_accounting"]
    assert control["unsupported"] == 0, control["sites"]
    loop = next(op["Loop"] for op in result.formal["modules"][0]["ops"]
                if "Loop" in op)
    guarded = [op for op in loop["body"] if "Cond" in op]
    assert guarded


def test_forward_goto_is_lowered_to_bounded_cfg_guard():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(FIXTURES_ROOT, "goto_control.c")
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

    source = os.path.join(FIXTURES_ROOT, "goto_backward.c")
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

    source = os.path.join(FIXTURES_ROOT, "switch_paths.c")
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


def test_switch_enum_constants_receive_mutually_exclusive_path_guards():
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern void writel(u32 value, void *addr);
        enum request_kind { request_status = 1, request_reset = 2 };

        void enum_switch(void *base, enum request_kind request)
        {
            switch (request) {
            case request_status:
                writel(1, base + 0x10);
                break;
            case request_reset:
                writel(2, base + 0x10);
                break;
            }
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "enum_switch.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path))

    validation = result.formal["metadata"]["path_validation"]
    assert len(validation["switch_pairs"]) == 1
    assert validation["switch_pairs"][0]["exclusive"] is True


def test_private_callback_field_inherits_role_from_proven_dispatcher():
    source = textwrap.dedent("""
        typedef unsigned short u16;
        typedef void (*irq_fn)(void *, u16);
        struct private_ops { irq_fn irq; };
        struct device_state { struct private_ops *ops; };
        typedef void (*irq_handler_t)(int, void *);
        extern void register_irq(irq_handler_t handler, void *data);
        extern void writel(unsigned int value, void *addr);

        static void private_irq(void *state, u16 status)
        {
            writel(status, state);
        }

        static void dispatcher(int line, void *state)
        {
            struct device_state *dev = state;
            if (dev->ops->irq)
                dev->ops->irq(dev, 1);
        }

        static struct private_ops private = { .irq = private_irq };
        static void register_device(void)
        {
            register_irq(dispatcher, 0);
        }
    """)
    bindings = _ast_callback_bindings(source)
    assert bindings["private_irq"]["table"] == "private_ops"
    assert bindings["private_irq"]["field"] == "irq"
    assert bindings["private_irq"]["role"] == "interrupt_handler"


def test_private_callback_field_inherits_role_through_public_field_transfer():
    source = textwrap.dedent("""
        typedef void (*set_cs_fn)(void *, int);
        struct spi_controller { set_cs_fn set_cs; };
        struct private_ops { set_cs_fn set_cs; };
        struct device_state {
            struct spi_controller *controller;
            struct private_ops *ops;
        };

        static void private_set_cs(void *state, int enable) { (void)state; (void)enable; }
        static void connect(struct device_state *dev)
        {
            dev->ops->set_cs = private_set_cs;
            dev->controller->set_cs = dev->ops->set_cs;
        }
    """)
    bindings = _ast_callback_bindings(source)
    assert bindings["private_set_cs"]["table"] == "private_ops"
    assert bindings["private_set_cs"]["field"] == "set_cs"
    assert bindings["private_set_cs"]["role"] == "write_config"


def test_of_device_data_function_is_bound_as_callback_evidence():
    source = textwrap.dedent("""
        struct of_device_id {
            const char *compatible;
            const void *data;
        };
        static int board_init(void *state) { (void)state; return 0; }
        static const struct of_device_id matches[] = {
            { .compatible = "vendor,board", .data = board_init },
            { }
        };
    """)
    bindings = _ast_callback_bindings(source)
    assert bindings["board_init"]["table"] == "of_device_id"
    assert bindings["board_init"]["field"] == "data"
    assert bindings["board_init"]["binding_kind"] == "data_initializer"


def test_callback_binding_scope_keeps_target_file_initializers():
    import tempfile

    import clang.cindex as cx
    from ast_analyzer import tu as tu_mod
    from ast_analyzer import target_functions
    from extractor.spec_infer import infer_callback_bindings

    tu_mod._configure()
    with tempfile.TemporaryDirectory() as directory:
        header = os.path.join(directory, "ops.h")
        source = os.path.join(directory, "driver.c")
        with open(header, "w", encoding="utf-8") as handle:
            handle.write(
                "struct driver_ops { void (*probe)(void *); };\n")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent("""
                #include "ops.h"
                static void probe_impl(void *state) {}
                static const struct driver_ops ops = {
                    .probe = probe_impl,
                };
            """))
        tu = cx.Index.create().parse(source, args=["-std=gnu11"])
        funcs = target_functions(tu, source)

        bindings = infer_callback_bindings(
            tu, funcs, target_files={source})

    assert next(info for info in bindings.values()
                if info["function"] == "probe_impl")["field"] == "probe"


def test_smt_path_validation_blocks_contradictory_nested_path():
    from extractor.metrics import score

    source = os.path.join(FIXTURES_ROOT, "infeasible_path.c")
    result = extract_ris(ExtractorConfig(source=source))
    validation = result.formal["metadata"]["path_validation"]
    assert validation["complete"] is True
    assert validation["infeasible"] == 1
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("contradictory/infeasible" in blocker
               for blocker in readiness["blockers"])


def test_inlined_helper_context_classifies_unreachable_branch_without_hiding_local_contradiction():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "inline_context.c")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent("""
                extern void writel(unsigned int value, void *addr);

                static void helper(void *dev)
                {
                    struct state { int mode; } *state = dev;
                    if (state->mode)
                        writel(1, dev + 0x10);
                }

                void entry(void *dev)
                {
                    struct state { int mode; } *state = dev;
                    if (!state->mode)
                        helper(dev);
                }
            """))

        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent", max_inline_depth=1))

    validation = result.formal["metadata"]["path_validation"]
    assert validation["infeasible"] == 0
    assert validation["intentionally_unreachable"] >= 1


def test_inlined_helper_local_contradiction_still_blocks_readiness():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "inline_local_contradiction.c")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent("""
                extern void writel(unsigned int value, void *addr);

                static void helper(void *dev)
                {
                    struct state { int mode; } *state = dev;
                    if (state->mode) {
                        if (!state->mode)
                            writel(1, dev + 0x10);
                    }
                }

                void entry(void *dev) { helper(dev); }
            """))

        result = extract_ris(ExtractorConfig(
            source=source, linux_root="/nonexistent", max_inline_depth=1))

    validation = result.formal["metadata"]["path_validation"]
    assert validation["infeasible"] == 1


def test_call_context_accepts_only_exactly_once_static_loop_calls():
    from extractor.call_graph import _call_row_is_proven

    row = {
        "resolution_authority": "direct_function_declaration",
        "return_binding": {"status": "exact"},
        "multiplicity": {
            "kind": "syntactic_callsite",
            "per_caller_invocation": 1,
        },
        "argument_mapping": [],
    }
    once = dict(row, control=[{
        "kind": "loop", "loop_kind": "for",
        "init": "i = 0", "guard": "i < 1", "step": "i++",
    }])
    twice = dict(row, control=[{
        "kind": "loop", "loop_kind": "for",
        "init": "i = 0", "guard": "i < 2", "step": "i++",
    }])

    assert _call_row_is_proven(once) is True
    assert _call_row_is_proven(twice) is False


def test_smt_path_validation_separates_compile_time_unreachable_paths():
    from extractor.smt import validate_formal_paths

    formal = {
        "modules": [{
            "name": "compile_time_branch",
            "ops": [{"Cond": {
                "guard": {"Const": 0},
                "control": {"kind": "cond", "branch": "then"},
                "then_ops": [],
                "else_ops": None,
            }}],
        }],
    }

    result = validate_formal_paths(formal)

    assert result["complete"] is True
    assert result["infeasible"] == 0
    assert result["intentionally_unreachable"] == 1


def test_smt_path_validation_default_budget_allows_complex_guards():
    from extractor.smt import validate_formal_paths

    formal = {"modules": [{"name": "guard_budget", "ops": [{"Cond": {
        "guard": {"BinOp": {
            "op": "And",
            "left": {"BinOp": {
                "op": "Ge", "left": {"Var": "length"},
                "right": {"Var": "mps"},
            }},
            "right": {"BinOp": {
                "op": "Ne",
                "left": {"BinOp": {
                    "op": "Mod", "left": {"Var": "length"},
                    "right": {"Var": "mps"},
                }},
                "right": {"Const": 0},
            }},
        }},
        "control": {"kind": "cond", "branch": "then"},
        "then_ops": [], "else_ops": None,
    }}]}]}

    result = validate_formal_paths(formal)

    assert result["timeout_ms"] >= 250
    assert result["complete"] is True


def test_smt_switch_exclusivity_is_scoped_to_lexical_switch_instance():
    from extractor.smt import validate_formal_paths

    def case(switch_id, value):
        return {"Cond": {
            "guard": {"BinOp": {
                "op": "Eq", "left": {"Var": "mode"},
                "right": {"Const": value},
            }},
            "control": {
                "kind": "cond", "branch": "case", "switch": "mode",
                "switch_id": switch_id, "case": str(value),
            },
            "then_ops": [], "else_ops": None,
        }}

    formal = {"modules": [{"name": "duplicated_context", "ops": [
        case("source.c:10:1", 1),
        case("source.c:10:1", 2),
        case("source.c:20:1", 1),
        case("source.c:20:1", 2),
    ]}]}

    result = validate_formal_paths(formal)

    assert len(result["switch_pairs"]) == 2
    assert all(pair["exclusive"] for pair in result["switch_pairs"])


def test_auto_wrapper_summary_survives_zero_inline_depth():
    from extractor.formal import walk_leaf_ops

    source = os.path.join(FIXTURES_ROOT, "mmio_wrapper.c")
    result = extract_ris(ExtractorConfig(
        source=source, max_inline_depth=0))
    assert result.stats["wrapper_summary_count"] >= 1
    assert any("wrapper_read" in name
               for name in result.stats["wrapper_summaries"])
    module = _module(result.formal, "wrapper_caller")
    leaves = list(walk_leaf_ops(module["ops"]))
    assert len(leaves) == 1 and "Read" in leaves[0]
    read = leaves[0]["Read"]
    assert read["addr"]["Fixed"]["name"] == "WRAP_STATUS"
    assert read["addr"]["Fixed"]["offset"] == 0x10
    assert read["evidence"]["origin"] == "wrapper_summary"
    assert read["evidence"]["summarized_at"][0]["callee"] == "wrapper_read"


def test_mixed_helper_flattens_with_cited_chains_and_call_node():
    from extractor.formal import walk_leaf_ops
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void writel(u32 value, void *addr);

        static u32 generic_read(void *base)
        {
            return readl(base + 0x10);
        }

        static void nested_access(void *base)
        {
            (void)readl(base + 0x12);
            writel(1, base + 0x14);
        }

        static void mixed_helper(void *base)
        {
            (void)generic_read(base);
            nested_access(base);
        }

        void entry(void *base) { mixed_helper(base); }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "mixed_helper.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path))

    entry_module = _module(result.formal, "entry")
    entry_leaves = list(walk_leaf_ops(entry_module["ops"]))
    # With cited call-context proof the whole chain flattens into the entry:
    # generic_read and nested_access both arrive as two-hop inlined ops and
    # the helper modules dedup away.  The Call node records the top edge.
    assert sum("Read" in op for op in entry_leaves) == 2
    assert sum("Write" in op for op in entry_leaves) == 1
    nested_chains = [
        op for op in entry_leaves
        if any(hop.get("callee") == "nested_access"
               for hop in (next(iter(op.values()))["evidence"]
                           .get("inlined_at") or []))
    ]
    assert nested_chains, "nested_access ops must cite their call chain"
    # v0.4.0: the top Call edge is no longer restated as a Call node —
    # the flattened ops' inlined_at hops already prove the expansion, so
    # the row is suppressed (metadata.call_graph.call_nodes) instead.
    assert (entry_module.get("calls") or []) == []
    cn = result.formal["metadata"]["call_graph"]["call_nodes"]
    assert cn["suppressed_expanded"] >= 1
    assert all(c.get("schema") == 2
               for c in (entry_module.get("calls") or []))
    assert "nested_access" not in {
        m["name"] for m in result.formal["modules"]}


def test_known_wrapper_access_survives_unknown_external_call():
    from extractor.formal import walk_leaf_ops
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void external_effect(void *base);

        static u32 generic_read(void *base)
        {
            return readl(base + 0x10);
        }

        static void mixed(void *base)
        {
            (void)generic_read(base);
            external_effect(base);
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "unknown_external.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path))

    module = _module(result.formal, "mixed")
    leaves = list(walk_leaf_ops(module["ops"]))
    assert any("Read" in op for op in leaves)


def test_branching_mmio_wrapper_summary_is_inferred_without_name_rules():
    from extractor.formal import walk_leaf_ops
    from extractor import mmio
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        typedef unsigned short u16;
        extern u16 readw_relaxed(void *addr);
        extern u32 readl_relaxed(void *addr);
        extern void writew_relaxed(u16 value, void *addr);
        extern void writel_relaxed(u32 value, void *addr);
        struct generic_state { void *regs; unsigned int width; };

        static inline u32 generic_read(struct generic_state *state,
                                       u32 offset)
        {
            if (state->width == 2)
                return readw_relaxed(state->regs + offset);
            return readl_relaxed(state->regs + offset);
        }

        static inline void generic_write(struct generic_state *state,
                                         u32 offset, u32 value)
        {
            if (state->width == 2)
                writew_relaxed((u16)value, state->regs + offset);
            else
                writel_relaxed(value, state->regs + offset);
        }

        static inline u32 generic_outer_read(struct generic_state *state,
                                              u32 offset)
        {
            return generic_read(state, offset);
        }

        void generic_caller(struct generic_state *state)
        {
            u32 value = generic_outer_read(state, 0x10);
            generic_write(state, 0x10, value);
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "generic_wrapper.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path, max_inline_depth=0))

    assert result.stats["wrapper_summary_count"] >= 2
    leaves = list(walk_leaf_ops(_module(result.formal, "generic_caller")["ops"]))
    assert any("Read" in op for op in leaves)
    assert any("Write" in op or "ReadModifyWrite" in op for op in leaves)
    summaries = result.formal["metadata"]["wrapper_analysis"]["summaries"]
    assert any("generic_read" in item for item in summaries)
    assert any("generic_write" in item for item in summaries)
    assert any("generic_outer_read" in item for item in summaries)
    assert mmio.infer_width("readw_relaxed") == 2
    assert mmio.infer_width("writew_relaxed") == 2


def test_generic_mmio_wrapper_preserves_read_modify_write_taint():
    from extractor.formal import walk_leaf_ops
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void writel(u32 value, void *addr);
        struct generic_state { void *regs; };

        static inline u32 generic_read(struct generic_state *state,
                                       u32 offset)
        {
            return readl(state->regs + offset);
        }

        static inline void generic_write(struct generic_state *state,
                                         u32 offset, u32 value)
        {
            writel(value, state->regs + offset);
        }

        void generic_rmw(struct generic_state *state)
        {
            u32 value = generic_read(state, 0x10);
            generic_write(state, 0x10, value);
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "generic_rmw.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path, max_inline_depth=0))

    leaves = list(walk_leaf_ops(_module(result.formal, "generic_rmw")["ops"]))
    assert [next(iter(op)) for op in leaves] == ["Read", "ReadModifyWrite"]


def test_generic_wrapper_rmw_keeps_read_taint_across_local_update():
    from extractor.formal import walk_leaf_ops
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        extern void writel(u32 value, void *addr);
        struct generic_state { void *regs; };

        static inline u32 generic_read(struct generic_state *state,
                                       u32 offset)
        {
            return readl(state->regs + offset);
        }

        static inline void generic_write(struct generic_state *state,
                                         u32 offset, u32 value)
        {
            writel(value, state->regs + offset);
        }

        void generic_rmw_update(struct generic_state *state)
        {
            u32 value = generic_read(state, 0x10);
            value = value | 1;
            generic_write(state, 0x10, value);
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "generic_rmw_update.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(source=path, max_inline_depth=0))

    leaves = list(walk_leaf_ops(
        _module(result.formal, "generic_rmw_update")["ops"]))
    register_kinds = [next(iter(op)) for op in leaves
                      if "Read" in op or "Write" in op
                      or "ReadModifyWrite" in op]
    assert register_kinds == ["Read", "ReadModifyWrite"]


def test_generic_wrapper_summary_rebinds_provenance_to_callsite():
    from extractor.formal import walk_leaf_ops
    import tempfile

    source = textwrap.dedent("""
        typedef unsigned int u32;
        extern u32 readl(void *addr);
        struct generic_state { void *regs; };

        static inline u32 generic_read(struct generic_state *state,
                                       u32 offset)
        {
            return readl(state->regs + offset);
        }

        void generic_caller(struct generic_state *state)
        {
            (void)generic_read(state, 0x20);
        }
    """)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "generic_wrapper_provenance.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(
            source=path, max_inline_depth=0))

    leaves = list(walk_leaf_ops(
        _module(result.formal, "generic_caller")["ops"]))
    assert len(leaves) == 1
    read = leaves[0]["Read"]
    evidence = read["evidence"]
    assert evidence["origin"] == "wrapper_summary"
    assert evidence["function"] == "generic_caller"
    assert evidence["wrapper_definition"]["function"] == "generic_read"
    assert evidence["wrapper_definition"]["origin"] == "direct"

def test_static_ops_table_indirect_call_is_resolved_and_propagated():
    from extractor.formal import walk_leaf_ops

    source = os.path.join(FIXTURES_ROOT, "indirect_ops.c")
    result = extract_ris(ExtractorConfig(source=source))
    assert result.stats["resolved_indirect_calls"] == 1
    assert result.stats["indirect_call_targets"]["local_ops.emit"] == \
        "indirect_emit"
    caller = _module(result.formal, "indirect_caller")
    leaves = list(walk_leaf_ops(caller["ops"]))
    assert len(leaves) == 1 and "Write" in leaves[0]
    write = leaves[0]["Write"]
    # IR-primary: indirect call resolved AND address GEP-verified
    assert write["addr"]["Fixed"]["name"] == "INDIRECT_REG"
    assert write["addr"]["Fixed"]["offset"] == 0x18
    assert write["value"] == {"Const": 7}
    summarized = write["evidence"].get("summarized_at", [])
    inlined = write["evidence"].get("inlined_at", [])
    assert any(item.get("indirect_expression") == "local_ops.emit"
               for item in summarized + inlined)



def test_i2c_smbus_holdout_no_longer_has_zero_hardware_ops():
    from extractor.formal import walk_leaf_ops

    source = os.path.join(
        LINUX_SOURCE_ROOT, "drivers", "gpio", "gpio-tpic2810.c")
    result = extract_ris(ExtractorConfig(source=source))
    leaves = [
        op["TransactionWrite"]
        for module in result.formal["modules"]
        for op in walk_leaf_ops(module["ops"])
        if "TransactionWrite" in op
    ]
    assert leaves
    assert all(body["transport"] == "i2c_smbus" for body in leaves)
    assert all(body["payload"]["Scalar"]["width"] == "B1"
               for body in leaves)
    assert all(body["selector"] == {"Var": "TPIC2810_WS_COMMAND"}
               for body in leaves)
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == 1
    assert accounting["emitted"] == 1
    assert accounting["strict_complete"] is True
    assert result.stats["transactions"] >= 1
    assert [(resource.type, resource.bind)
            for resource in result.device_spec.resources] == [
                ("TransactionResource", "i2c_smbus")]
    assert any(effect.kind == "transaction"
               for function in result.device_spec.functions
               for effect in function.effects)


def test_public_mfd_register_helpers_form_transactions_fail_closed():
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import score

    source = os.path.join(
        LINUX_SOURCE_ROOT, "drivers", "clk", "clk-twl6040.c")
    result = extract_ris(ExtractorConfig(source=source))
    leaves = [
        op["TransactionUpdate"]
        for module in result.formal["modules"]
        for op in walk_leaf_ops(module["ops"])
        if "TransactionUpdate" in op
    ]
    # reset_one_clock does set_bits(reset_mask) THEN clear_bits(same mask)
    # on each PLL; with cited call-context proof both RMW transactions of
    # both registers flatten into prepare (previously depth-1 inlining kept
    # only one per register).
    assert len(leaves) == 4
    assert all(body["transport"] == "mfd" for body in leaves)
    assert all(body["width"] == "B1" for body in leaves)
    by_selector = {}
    for body in leaves:
        by_selector.setdefault(
            body["selector"]["Var"], []).append(body["value"])
    assert by_selector == {
        "TWL6040_REG_HPPLLCTL": [{"Var": "reset_mask"}, {"Const": 0}],
        "TWL6040_REG_LPPLLCTL": [{"Var": "reset_mask"}, {"Const": 0}],
    }
    assert {row["name"] for row in result.formal["transaction_map"]} == {
        "TWL6040_REG_HPPLLCTL", "TWL6040_REG_LPPLLCTL"}
    accounting = result.formal["metadata"]["access_accounting"]
    assert accounting["source_accesses"] == accounting["emitted"] == 2
    assert accounting["strict_complete"] is True
    assert [(resource.type, resource.bind)
            for resource in result.device_spec.resources] == [
                ("TransactionResource", "mfd")]
    readiness = score(result.device_spec, result.formal, result.warnings,
                      result.facts)
    assert readiness["backend_linux_ready"] is False
    assert any("typed hardware transaction" in blocker
               for blocker in readiness["blockers"])


def test_private_set_bits_name_is_not_inferred_as_mfd_transaction():
    from types import SimpleNamespace
    from extractor.transactions import contract_for_call

    call = SimpleNamespace(
        name="device_set_bits", arg_text=["dev", "reg", "mask"],
        callee_decl_path="/tmp/private_driver.c",
        callee_param_types=["struct device *", "unsigned int", "u8"])
    assert contract_for_call(call) is None


def test_transaction_source_oracle_catches_semantic_mutations():
    from backends.oracles.transaction_ir_oracle import mutation_suite

    source = os.path.join(FIXTURES_ROOT, "regmap_access.c")
    result = extract_ris(ExtractorConfig(source=source))
    report = mutation_suite(result.formal, source)
    assert report["complete"] is True
    assert report["mutations_detected"] == {
        "transport": True, "selector": True, "kind": True, "order": True}


def test_multi_source_transaction_oracle_validates_declared_sources():
    from backends.oracles.transaction_ir_oracle import verify_transaction_sources
    from extractor.metrics import score
    from backends.pipeline import _transaction_source_paths

    manifest = os.path.join(
        MULTISOURCE_ROOT, "dw-apb-ssi-full.json")
    result = extract_ris(ExtractorConfig(source=manifest))
    with open(manifest, encoding="utf-8") as fh:
        document = json.load(fh)
    sources = [os.path.join(os.path.dirname(manifest), item)
               for item in document["sources"]]

    report = verify_transaction_sources(result.formal, sources)

    assert report["complete"] is True, report
    # The two MSCC callbacks share one definition-owned regmap site; the
    # source-shape oracle validates that definition once, while call-context
    # multiplicity is covered by the separate call-graph proof.
    assert report["expected_transactions"] == 6
    assert report["observed_transactions"] == 6
    assert report["coverage_complete"] is True
    assert _transaction_source_paths(manifest) == [
        os.path.realpath(source) for source in sources]

    result.formal.setdefault("metadata", {})["transaction_validation"] = report
    readiness = score(result.device_spec, result.formal,
                      result.warnings, result.facts)
    assert not any("typed hardware transaction" in blocker
                   for blocker in readiness["blockers"])


def test_volatile_and_inline_asm_accesses_block_false_strict_completion():
    from extractor.metrics import score

    source = os.path.join(FIXTURES_ROOT, "opaque_access.c")
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
               and o["Write"]["addr"].get("Fixed", {}).get("name") == "GPIO_INT_CLR")
    # The dataflow evaluator may soundly fold this extracted write to the
    # all-ones constant.  Exercise the formal parser directly so this remains
    # a normalization test rather than constraining constant folding.
    assert clr["Write"]["value"] == {"Const": 0xFFFFFFFF}
    val = parse_expr("~0x0")
    assert val["BinOp"]["op"] == "BitXor"
    arithmetic = parse_expr("4 * (d->hwirq % 8)")
    assert arithmetic["BinOp"]["op"] == "Mul"
    assert arithmetic["BinOp"]["right"]["BinOp"]["op"] == "Mod"


def test_formal_expr_respects_c_logical_comparison_precedence():
    expression = parse_expr(
        "ready && length >= mps && !(length % mps)")

    assert expression["BinOp"]["op"] == "And"
    left = expression["BinOp"]["left"]
    right = expression["BinOp"]["right"]
    assert left["BinOp"]["op"] == "And"
    assert left["BinOp"]["left"] == {"Var": "ready"}
    assert left["BinOp"]["right"]["BinOp"]["op"] == "Ge"
    assert right["BinOp"]["op"] == "Eq"
    assert right["BinOp"]["left"]["BinOp"]["op"] == "Mod"
    assert right["BinOp"]["right"] == {"Const": 0}


def test_formal_expr_keeps_shift_tokens_before_relational_tokens():
    expression = parse_expr("((value & MASK) >> SHIFT) == CODE")

    assert expression["BinOp"]["op"] == "Eq"
    shifted = expression["BinOp"]["left"]
    assert shifted["BinOp"]["op"] == "Shr"
    assert shifted["BinOp"]["left"]["BinOp"]["op"] == "BitAnd"


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


def test_source_text_reuses_bytes_for_repeated_cursor_slices():
    import tempfile
    from unittest.mock import patch

    import clang.cindex as cx
    from ast_analyzer import tu as tu_mod
    from ast_analyzer import source_text

    tu_mod._configure()
    with tempfile.NamedTemporaryFile(
            "w", suffix=".c", delete=False, encoding="utf-8") as handle:
        handle.write("void probe(void) { return; }\n")
        path = handle.name
    try:
        tu = cx.Index.create().parse(path, args=["-std=gnu11"])
        function = next(cursor for cursor in tu.cursor.get_children()
                        if cursor.kind == cx.CursorKind.FUNCTION_DECL)
        with patch("builtins.open", wraps=open) as open_mock:
            first = source_text(tu, function)
            second = source_text(tu, function)
        file_opens = [call for call in open_mock.call_args_list
                      if call.args and os.fspath(path) == call.args[0]]
        assert first == second
        assert len(file_opens) == 1
    finally:
        os.unlink(path)


def test_direct_mmio_read_return_is_explicit_and_preserves_normalization():
    import tempfile

    src = textwrap.dedent("""
        #define DATA 0x10
        #define BIT(n) (1U << (n))
        extern unsigned int readl(void *addr);
        static int gpio_get(void *base, unsigned int offset)
        {
            return !!(readl(base + DATA) & BIT(offset));
        }
        int (*registered_get)(void *, unsigned int) = gpio_get;
    """)
    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "direct-return.c")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(src)
        formal = extract_ris(ExtractorConfig(source=source)).formal

    leaves = []
    _leaf_ops(_module(formal, "gpio_get")["ops"], leaves)
    assert [next(iter(op)) for op in leaves] == ["Read", "Return"]
    assert leaves[0]["Read"]["var"] == "__return_read_0"
    returned = leaves[1]["Return"]
    assert returned["access_domain"] == "source_result"
    assert returned["value"] == {
        "BinOp": {
            "op": "Eq",
            "left": {
                "BinOp": {
                    "op": "Eq",
                    "left": {
                        "BinOp": {
                            "op": "BitAnd",
                            "left": {"Var": "__return_read_0"},
                            "right": {
                                "BinOp": {
                                    "op": "Shl",
                                    "left": {"Const": 1},
                                    "right": {"Var": "offset"},
                                }
                            },
                        }
                    },
                    "right": {"Const": 0},
                }
            },
            "right": {"Const": 0},
        }
    }


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
        # Call nodes legitimately name the callee's formal parameters
        # (the parameter-to-argument binding itself); op expressions must
        # still be fully substituted, so check outside the Call lines.
        non_call = "\n".join(
            line for line in rendered.splitlines()
            if not line.strip().startswith("Call "))
        assert "dev" not in non_call
        assert " value" not in non_call
        assert result.stats["cross_tu_call_edges"] >= 1
        assert result.stats["resolved_cross_tu_call_edges"] >= 1
        assert result.stats["propagated_mmio_edges"] >= 1


def test_single_source_transitive_switch_case_inline_is_cited_and_proven():
    """A helper called only inside a switch case must still reach the entry.

    This pins the gpio-dwapb dwapb_irq_set_type -> dwapb_toggle_trigger
    regression: one-shot flattening dropped the switch-arm context entirely,
    and the call-context proof now reports that loss as an occurrence
    mismatch, so extraction itself must iterate to a fixpoint.
    """
    import tempfile

    source_text = (
        "extern unsigned int readl(const void *addr);\n"
        "extern void writel(unsigned int value, void *addr);\n"
        "static unsigned int read_reg(void *dev, unsigned int off) {\n"
        "    return readl(dev + off);\n"
        "}\n"
        "static void write_reg(void *dev, unsigned int off, unsigned int v) {\n"
        "    writel(v, dev + off);\n"
        "}\n"
        "static void toggle(void *dev, unsigned int bit) {\n"
        "    unsigned int pol = read_reg(dev, 0x10);\n"
        "    pol ^= 1u << bit;\n"
        "    write_reg(dev, 0x10, pol);\n"
        "}\n"
        "void entry(void *dev, unsigned int type) {\n"
        "    unsigned int level = read_reg(dev, 0x20);\n"
        "    switch (type) {\n"
        "    case 3:\n"
        "        toggle(dev, 0);\n"
        "        break;\n"
        "    default:\n"
        "        break;\n"
        "    }\n"
        "    write_reg(dev, 0x20, level);\n"
        "}\n")
    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "switch_inline.c")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(source_text)
        result = extract_ris(ExtractorConfig(source=source))

    rescue = result.stats["callee_rescue"]
    proof = rescue["call_context_proof"]
    assert proof["proven"] is True
    assert proof["reason"] == "exact_static_call_contexts"
    citations = proof["inline_citations"]
    assert citations["complete"] is True
    assert citations["checked_hops"] >= 5

    module = _module(result.formal, "entry")
    chains = [
        hop
        for op in walk_all_ops_of(module)
        for hop in (op.get("evidence") or {}).get("inlined_at", [])]
    switch_hops = [hop for hop in chains
                   if hop.get("callee") == "toggle"]
    assert switch_hops, "switch-case helper context was dropped"
    through_toggle = [
        chain for chain in (
            (op.get("evidence") or {}).get("inlined_at") or []
            for op in walk_all_ops_of(module))
        if any(hop.get("function") == "toggle" for hop in chain)]
    assert any(
        any(hop.get("function") == "entry" for hop in chain)
        for chain in through_toggle)
    # v0.4.0: toggle's ops are inlined with an entry->toggle hop, so the
    # Call row is suppressed as expansion-proven rather than restated.
    toggle_calls = [call for call in (module.get("calls") or [])
                    if call["callee"] == "toggle"]
    assert toggle_calls == []
    cn = result.formal["metadata"]["call_graph"]["call_nodes"]
    assert cn["suppressed_expanded"] >= 1


def walk_all_ops_of(module):
    from extractor.formal import walk_leaf_ops
    bodies = []
    for op in walk_leaf_ops(module.get("ops", [])):
        body = (op.get("Read") or op.get("Write")
                or op.get("ReadModifyWrite") or op.get("StateRead")
                or op.get("StateWrite") or op.get("TransactionRead")
                or op.get("TransactionWrite") or op.get("TransactionUpdate"))
        if body is not None:
            bodies.append(body)
    return bodies


def test_inline_citation_verifier_fails_closed_on_uncited_chain():
    from extractor.call_graph.inlining import _verify_inline_citations
    from extractor.dataflow import FuncExtraction
    from extractor.dataflow.ops import Op

    op = Op(kind="Read", addr={"Fixed": 0}, width=4)
    op.evidence = {"inlined_at": [{
        "function": "caller", "line": 7, "callee": "helper"}]}
    expanded = {"caller": FuncExtraction(name="caller", ops=[op])}
    complete = _verify_inline_citations(expanded, [])
    assert complete["complete"] is False
    assert complete["violation_count"] == 1
    assert complete["violations"][0]["reason"] == "no_matching_call_row"

    rows = [{
        "caller_module": "caller", "callee_module": "helper",
        "callsite": {"line": 7},
        "resolution_authority": "unresolved_pointer",
        "return_binding": {"status": "exact"},
        "multiplicity": {"kind": "syntactic_callsite",
                         "per_caller_invocation": 1},
        "argument_mapping": [],
    }]
    unproven = _verify_inline_citations(expanded, rows)
    assert unproven["complete"] is False
    assert unproven["violations"][0]["reason"] == "cited_call_row_unproven"

    rows[0]["resolution_authority"] = "direct_function_declaration"
    ok = _verify_inline_citations(expanded, rows)
    assert ok["complete"] is True
    assert ok["checked_hops"] == 1


def test_exact_cross_tu_call_context_proof_accepts_single_static_call():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        manifest = os.path.join(directory, "driver.json")
        sources = {
            "helper.c": (
                "extern void writel(unsigned int value, void *addr);\n"
                "void write_reg(void *dev, unsigned int reg) {\n"
                "    writel(1, dev + reg);\n"
                "}\n"),
            "entry.c": (
                "void write_reg(void *dev, unsigned int reg);\n"
                "void entry(void *dev) { write_reg(dev, 0x10); }\n"),
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "exact-call-proof",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=1))

    rescue = result.stats["callee_rescue"]
    assert rescue["candidates"] == 1
    assert rescue["rescued"] == 0
    assert rescue["call_semantics_proven"] is True
    assert result.formal["metadata"]["assurance_scope"][
        "call_semantics_proven"] is True


def test_call_context_proof_accepts_structured_loop_callsite():
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        manifest = os.path.join(directory, "driver.json")
        sources = {
            "helper.c": (
                "extern void writel(unsigned int value, void *addr);\n"
                "void write_reg(void *dev) { writel(1, dev); }\n"),
            "entry.c": (
                "void write_reg(void *dev);\n"
                "void entry(void *dev, unsigned int count) {\n"
                "    for (unsigned int i = 0; i < count; ++i)\n"
                "        write_reg(dev);\n"
                "}\n"),
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "loop-call-proof",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=1))

    rescue = result.stats["callee_rescue"]
    assert rescue["candidates"] == 1
    assert rescue["rescued"] == 0
    assert rescue["call_semantics_proven"] is True
    assert result.formal["metadata"]["assurance_scope"][
        "call_semantics_proven"] is True


def test_multi_source_export_symbol_address_is_not_callback_entry():
    """Export metadata must not block an ordinary cross-file call."""
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        sources = {
            "helper.c": textwrap.dedent("""
                #define EXPORT_SYMBOL_NS_GPL(sym, ns) \\
                    static void *__UNIQUE_ID_addressable_##sym = (void *)(sym)
                extern void writel(unsigned int value, void *addr);
                void helper(void) { writel(1, (void *)0x10); }
                EXPORT_SYMBOL_NS_GPL(helper, "TEST");
            """),
            "entry.c": "void helper(void);\nvoid entry(void) { helper(); }\n",
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        manifest = os.path.join(directory, "driver.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "export-call-context",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent",
            compile_context_mode="off", max_inline_depth=2))

    assert {module["name"] for module in result.formal["modules"]} == {"entry"}
    assert result.stats["callee_rescue"]["retained_inlined"] == 1
    assert result.formal["metadata"]["callback_binding_analysis"][
        "unbound_entries"] == []


def test_nested_formal_paths_resolve_macros_once_per_module():
    from extractor.dataflow import Op
    from extractor.formalize import _nest
    from extractor.macros import MacroTable

    macros = MacroTable()
    macros.add("REG_CASE", "0x10")
    calls = 0
    original_resolve = macros.resolve

    def resolve(name, _stack=None):
        nonlocal calls
        calls += 1
        return original_resolve(name, _stack)

    macros.resolve = resolve
    frames = [
        {"kind": "cond", "guard": "REG_CASE"},
        {"kind": "cond", "guard": "REG_CASE"},
    ]
    ops = [Op(kind="Write", addr={"Const": 0}, width=4, value="1",
              control_stack=frames)]

    _nest(ops, 0, [0], macros)

    assert calls == 1


def test_coverage_aware_callee_rescue_keeps_unpropagated_direct_site():
    import tempfile
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import score

    with tempfile.TemporaryDirectory() as directory:
        manifest = os.path.join(directory, "driver.json")
        sources = {
            "leaf.c": "void leaf(void *b) { writel(1, b + 0x10); }\n",
            "level1.c": (
                "void leaf(void *b);\n"
                "void level1(void *b) { leaf(b); }\n"),
            "level2.c": (
                "void level1(void *b);\n"
                "void level2(void *b) { level1(b); }\n"),
            "level3.c": (
                "void level2(void *b);\n"
                "void level3(void *b) { level2(b); }\n"),
            "entry.c": (
                "void level3(void *b);\n"
                "void entry(void *b) { level3(b); }\n"),
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({
                "schema": 1, "name": "callee-rescue",
                "sources": list(sources),
            }, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=3))
        modules = {module["name"]: module for module in result.formal["modules"]}
        assert set(modules) == {"leaf"}
        leaves = list(walk_leaf_ops(modules["leaf"]["ops"]))
        assert len([op for op in leaves if "Write" in op]) == 1
        accounting = result.stats["access_accounting"]
        assert accounting["source_accesses"] == 1
        assert accounting["emitted"] == 1
        assert accounting["unaccounted"] == 0
        rescue = result.stats["callee_rescue"]
        assert rescue["rescue_mode"] == "direct-evidence-frontier"
        assert rescue["rescued"] == 1
        assert rescue["rescued_direct_ops"] == 1
        assert rescue["retained_inlined"] == 3
        readiness = score(
            result.device_spec, result.formal, result.warnings, result.facts)
        assert readiness["llm_synthesis_ready"] is False
        assert readiness["backend_harness_ready"] is False
        assert readiness["backend_bare_metal_ready"] is False
        assert readiness["backend_linux_ready"] is False
        assert any("call semantics not proven" in blocker
                   for blocker in readiness["blockers"])

        complete = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=4))
        assert {module["name"] for module in complete.formal["modules"]} == {
            "entry"}
        assert complete.stats["access_accounting"]["unaccounted"] == 0
        assert complete.stats["callee_rescue"]["rescued"] == 0
        assert complete.stats["callee_rescue"][
            "call_semantics_proven"] is True
        assert complete.formal["metadata"]["assurance_scope"][
            "call_semantics_proven"] is True


def test_callee_rescue_fails_closed_for_missing_operation_evidence():
    from extractor.call_graph import _coverage_aware_inlined_names
    from extractor.dataflow import FuncExtraction, Op

    helper = FuncExtraction(name="helper", ops=[
        Op(kind="Write", addr={"Computed": "opaque"}, width=4,
           value="1", evidence={}),
    ])
    inlined, rescue, frontiers = _coverage_aware_inlined_names(
        {"helper": helper}, {"root": FuncExtraction(name="root")},
        {"helper"})
    assert inlined == set()
    assert rescue["rescued"] == 1
    assert rescue["unproven_symbols"] == ["helper"]
    assert rescue["rescued_direct_ops"] == 1
    assert rescue["call_semantics_proven"] is False
    assert len(frontiers["helper"].ops) == 1


def test_default_inline_depth_adapts_to_complete_manifest_call_chain():
    """The default extractor must not truncate a finite multi-TU call chain."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        manifest = os.path.join(directory, "driver.json")
        sources = {
            "leaf.c": "void leaf(void *b) { writel(1, b + 0x10); }\n",
            "level1.c": (
                "void leaf(void *b);\n"
                "void level1(void *b) { leaf(b); }\n"),
            "level2.c": (
                "void level1(void *b);\n"
                "void level2(void *b) { level1(b); }\n"),
            "level3.c": (
                "void level2(void *b);\n"
                "void level3(void *b) { level2(b); }\n"),
            "entry.c": (
                "void level3(void *b);\n"
                "void entry(void *b) { level3(b); }\n"),
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "adaptive-depth",
                       "sources": list(sources)}, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent"))

        assert [module["name"] for module in result.formal["modules"]] == [
            "entry"]
        assert result.stats["callee_rescue"]["call_semantics_proven"] is True
        assert result.formal["metadata"]["assurance_scope"][
            "call_semantics_proven"] is True
        from extractor.metrics import score
        readiness = score(
            result.device_spec, result.formal, result.warnings, result.facts)
        assert not any("call-context proof" in blocker
                       for blocker in readiness["blockers"])


def test_pointer_argument_substitution_preserves_member_guard_semantics():
    """An address-of argument must not become a bitwise-AND guard term."""
    import tempfile
    from extractor.formal import walk_all_ops

    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, "driver.c")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(
                "struct state { unsigned ver; };\n"
                "void leaf(struct state *state, void *base) {\n"
                "    if (!state->ver) writel(1, base);\n"
                "}\n"
                "void entry(void *base) {\n"
                "    struct state state = {0};\n"
                "    leaf(&state, base);\n"
                "}\n")

        result = extract_ris(ExtractorConfig(source=source))

        assert result.formal["metadata"]["path_validation"]["unknown"] == 0
        conditions = [
            op["Cond"]["guard"]
            for module in result.formal["modules"]
            for op in walk_all_ops(module["ops"])
            if "Cond" in op
        ]
        assert conditions
        assert all("!&" not in condition for condition in conditions)


def test_shallow_site_coverage_does_not_prove_deep_call_context():
    import tempfile
    from extractor.formal import walk_leaf_ops
    from extractor.metrics import score

    with tempfile.TemporaryDirectory() as directory:
        manifest = os.path.join(directory, "driver.json")
        sources = {
            "leaf.c": (
                "void leaf(void *b, unsigned v) { writel(v, b); }\n"),
            "level1.c": (
                "void leaf(void *b, unsigned v);\n"
                "void level1(void *b) { leaf(b + 0x20, 2); }\n"),
            "level2.c": (
                "void level1(void *b);\n"
                "void level2(void *b) { level1(b); }\n"),
            "level3.c": (
                "void level2(void *b);\n"
                "void level3(void *b) { level2(b); }\n"),
            "entry.c": (
                "void leaf(void *b, unsigned v);\n"
                "void level3(void *b);\n"
                "void entry(void *b) { leaf(b + 0x10, 1); level3(b); }\n"),
        }
        for name, source in sources.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as fh:
                fh.write(source)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({
                "schema": 1, "name": "mixed-depth-call-context",
                "sources": list(sources),
            }, fh)

        result = extract_ris(ExtractorConfig(
            source=manifest, linux_root="/nonexistent", max_inline_depth=3))
        rescue = result.stats["callee_rescue"]
        assert rescue["rescued"] == 0
        assert rescue["candidates"] > 0
        assert rescue["call_semantics_proven"] is False
        assert result.stats["access_accounting"]["unaccounted"] == 0
        leaves = [
            op for module in result.formal["modules"]
            for op in walk_leaf_ops(module["ops"])
            if "Write" in op
        ]
        # Lexical site coverage sees the shallow instance, but the deeper
        # parameterized call is beyond the bounded expansion depth.
        assert len(leaves) == 1
        readiness = score(
            result.device_spec, result.formal, result.warnings, result.facts)
        assert readiness["llm_synthesis_ready"] is False
        assert any("call-context proof" in blocker
                   for blocker in readiness["blockers"])


def test_inlined_read_return_binds_the_caller_lhs():
    from extractor.formal import expr_display, walk_leaf_ops

    source = os.path.join(
        FIXTURES_ROOT, "read_return.c")
    result = extract_ris(ExtractorConfig(source=source))
    leaves = list(walk_leaf_ops(
        _module(result.formal, "read_return_update")["ops"]))
    read = next(op["Read"] for op in leaves if "Read" in op)
    write = next(op["Write"] for op in leaves if "Write" in op)
    assert read["var"] == "value"
    rendered = expr_display(write["value"])
    assert "value" in rendered and "mask" in rendered
    calls = result.formal["metadata"]["call_graph"]["calls"]
    # Call rows cover the candidate-expanded universe (header helpers such
    # as writel included); the helper under test must appear exactly once.
    helper_rows = [call for call in calls
                   if call["caller_module"] == "read_return_update"
                   and call["callee_module"] == "read_return_helper"]
    assert len(helper_rows) == 1
    call = helper_rows[0]
    assert call["resolution_authority"] == "direct_function_declaration"
    assert call["argument_mapping"][0]["parameter"] == "base"
    assert call["return_binding"]["destination"] == "value"
    assert call["multiplicity"]["runtime_count_proven"] is False


def test_call_context_proof_uses_canonical_types_for_typedef_arguments():
    from extractor.call_graph import _call_row_is_proven

    call = {
        "resolution_authority": "direct_function_declaration",
        "return_binding": {"status": "exact"},
        "multiplicity": {
            "kind": "syntactic_callsite",
            "per_caller_invocation": 1,
        },
        "argument_mapping": [{
            "parameter": "flags",
            "parameter_type": "gfp_t",
            "parameter_canonical_type": "unsigned int",
            "argument_type": "unsigned int",
            "argument_canonical_type": "unsigned int",
        }],
    }

    assert _call_row_is_proven(call) is True




def test_real_linux_c67x00_multisource_driver():
    from extractor.metrics import count_clang_errors, driver_metrics
    from gate.backend_lowering_oracle import (
        build_generation_contract, verify_backend_lowering)
    from gate.backend_lowering_plan import verify_backend_lowering_plan

    result = extract_ris(ExtractorConfig(source=C67X00_MULTI))
    assert result.stats["translation_units"] == 4
    assert result.stats["source_lines"] == 2239
    assert result.stats["functions_analyzed"] == 89
    assert all("/vendor/linux/drivers/usb/c67x00/" in source
               for source in result.stats["source_files"])
    assert count_clang_errors(result.warnings) == 0

    modules = {module["name"] for module in result.formal["modules"]}
    # Wrapper summaries now carry the low-level HPI register primitives
    # through the host-controller callback layer instead of stopping at the
    # top-level IRQ/probe entries.
    assert modules == {
        "c67x00_irq", "c67x00_drv_probe", "c67x00_hub_status_data",
        "c67x00_hub_control", "c67x00_hcd_irq", "c67x00_hcd_get_frame",
        "c67x00_urb_enqueue", "c67x00_sched_work",
    }
    metrics = driver_metrics(result.formal)
    assert metrics["total_ops"] == 262
    assert metrics["computed"] == 131
    assert metrics["unsafe_computed"] == 8
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
    assert next(function for function in result.device_spec.functions
                if function.name == "c67x00_hcd_irq").role == (
                    "interrupt_handler")
    assert all(pair["exclusive"] for pair in
               result.stats["path_validation"]["switch_pairs"])
    assert result.stats["callee_rescue"]["rescued"] == 0

    code = _linux_generate_and_compile(C67X00_MULTI, "rh_test_c67x00")
    # LLM-only: 生成内容质量由真模型决定, 此处仅保留提取/编译契约
    contract = build_generation_contract(result.formal)
    lowering = verify_backend_lowering(result.formal, code)
    plan = verify_backend_lowering_plan(
        result.formal, contract, "linux", device_spec=result.device_spec,
        lowering_report=lowering)
    assert plan["authorized_ops"] == 89
    assert plan["blocked_ops"] == 42
    assert plan["disposition_counts"]["blocked_linux_root_unreachable"] == 10
    assert plan["disposition_counts"]["blocked_unsupported_loop"] == 32
    assert plan["definition_alignment_complete"] is False
    assert plan["runtime_complete"] is False



def test_single_source_callee_rescue_closes_ahci_access_gaps_without_strict_claim():
    from extractor.metrics import score

    # dwc: every site is covered by retained inlining AND the call-context
    # proof (cited rows + exact static path counts) succeeds, so it is
    # fully proven and LLM-ready.  sunxi: the fixpoint flattening now proves
    # its whole helper chain too (previously depth-1 gaps kept it
    # fail-closed); readiness stays False on unrelated conservatism
    # (loop summaries, role inference), not on call semantics.
    cases = {
        os.path.join(BASELINE_ROOT, "ahci_dwc.c"): (9, 0, 0, True),
        os.path.join(BASELINE_ROOT, "ahci_sunxi.c"): (48, 0, 0, True),
    }
    for source, (ops, rescued, direct_ops, proven) in cases.items():
        result = extract_ris(ExtractorConfig(source=source))
        assert result.stats["total_ops"] == ops
        assert result.stats["access_accounting"]["unaccounted"] == 0
        assert result.stats["callee_rescue"]["rescued"] == rescued
        assert result.stats["callee_rescue"]["rescued_direct_ops"] == direct_ops
        assert (result.stats["callee_rescue"]["call_context_proof"]["proven"]
                is proven)
        assert (result.stats["callee_rescue"]["call_context_proof"]
                ["reason"] == "exact_static_call_contexts")

    # Call-semantics blockers must be gone for sunxi; whatever keeps it from
    # llm-readiness now has to be an unrelated family.
    result = extract_ris(ExtractorConfig(
        source=os.path.join(BASELINE_ROOT, "ahci_sunxi.c")))
    readiness = score(
        result.device_spec, result.formal, result.warnings, result.facts)
    call_families = (
        "call semantics not proven",
        "lack call-context proof",
        "retained only for lexical access coverage",
        "uncited inline chain",
    )
    assert not any(family in blocker
                   for blocker in readiness["blockers"]
                   for family in call_families)


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







def test_gpio_mmio_source_differential_suite_catches_semantic_mutations():
    from backends.linux.oracles.gpio_mmio_source_oracle import (
        verify_gpio_mmio_source_suite)

    result = verify_gpio_mmio_source_suite()
    assert len(result["cases"]) == 8
    assert all(case["passed"] for case in result["cases"].values())
    assert result["cases"]["clps711x"]["calls"] == 16
    assert result["cases"]["dwapb"]["calls"] == 32
    assert result["mutations_caught"] == 10
    assert all(item["caught"] for item in result["mutations"].values())


def test_gpio_direction_variant_requires_one_shared_register_address():
    import tempfile
    from pathlib import Path
    from extractor.formal import walk_all_ops

    source = Path(GPIO_CLPS711X).read_text(encoding="utf-8")
    source = source.replace(
        "config.dirout = dir;", "config.dirout = dat;", 1)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "gpio-path-variant.c"
        path.write_text(source, encoding="utf-8")
        result = extract_ris(ExtractorConfig(source=str(path)))

    summary = result.formal["metadata"]["subsystem_summary_analysis"][
        "summaries"]["gpio_generic"][0]
    assert summary["variant"] is True
    assert summary["variant_model"] is None
    domains = {
        (op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
         or op.get("StateRead") or op.get("StateWrite") or {}).get(
             "access_domain")
        for module in result.formal["modules"]
        for op in walk_all_ops(module["ops"])
    }
    assert "gpio_generic_config_variant" in domains


def test_dwapb_banked_addresses_and_runtime_loops_are_source_backed():
    from extractor.metrics import driver_metrics
    from verification.dwapb_banked_oracle import verify_dwapb_banked
    from backends.linux.oracles.gpio_mmio_source_oracle import (
        verify_gpio_mmio_source_differential)

    database = os.path.join(
        REHARNESS, "artifacts", "output", "zero-shot-contexts",
        "compile_commands.json")
    config = ExtractorConfig(
        source=GPIO_DWAPB,
        compile_commands=database if os.path.isfile(database) else None,
        compile_context_mode="required" if os.path.isfile(database) else "auto")
    result = extract_ris(config)
    metrics = driver_metrics(result.formal)
    assert metrics["unsafe_computed"] == 0
    assert metrics["conservative_loop"] == 0

    summary = result.formal["metadata"]["subsystem_summary_analysis"][
        "summaries"]["gpio_generic"][0]
    assert summary["bank_model"]["max_count"] == 4
    assert summary["bank_model"]["property"] == "reg"
    assert summary["bank_model"]["resource_index"] == 0
    assert summary["bank_model"]["ngpio_properties"] == [
        "ngpios", "snps,nr-gpios"]
    assert summary["bank_model"]["ngpio_default"] == 32
    assert summary["bank_model"]["irq"]["selector_value"] == 0
    assert {state.name: state.type for state in result.device_spec.state}[
        "ports_ctx_data"] == "UIntArray"

    source_oracle = verify_gpio_mmio_source_differential(
        result.formal, result.device_spec)
    assert source_oracle["gpio_mmio_source_oracle_passed"], source_oracle
    assert source_oracle["gpio_mmio_source_oracle_calls"] == 32

    oracle = verify_dwapb_banked()
    assert oracle["passed"] is True
    assert oracle["linux_lifecycle_passed"] is True
    assert oracle["mutations_caught"] == 13
    assert all(item["caught"] for item in oracle["mutations"].values())
    assert all(item["caught"] for item in oracle["linux_mutations"].values())


def test_readiness_score():
    from extractor.extractor import extract_ris
    from extractor.metrics import score
    res = extract_ris(ExtractorConfig(source=FTGPIO))
    s = score(res.device_spec, res.formal, res.warnings, res.facts)
    assert s["ris_quality"] >= 0.9
    assert s["backend_harness_ready"] is False
    assert s["backend_bare_metal_ready"] is False
    assert s["backend_linux_ready"] is False
    assert any("attestation results unavailable" in blocker
               for blocker in s["blockers"])
    assert any("generic-backend execution oracle" in blocker
               for blocker in s["blockers"])
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
    assert len(addrs) == 7
    assert all(expr_to_c(addr) ==
               "(pl061->base + (0x1 << (offset + 0x2)))" for addr in addrs)
    metrics = driver_metrics(pl061.formal)
    assert metrics["computed"] == 7 and metrics["unsafe_computed"] == 0
    ready = score(pl061.device_spec, pl061.formal, pl061.warnings, pl061.facts)
    assert ready["backend_bare_metal_ready"] is False
    assert any("attestation results unavailable" in blocker
               for blocker in ready["blockers"])

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
    assert "gpio_irq_chip_set_chip" in f.helper_calls
    assert any(r.acquisition == "devm_platform_ioremap_resource" for r in f.resources)
    assert any("ENOMEM" in e for e in f.error_paths)
    assert all(not k.startswith("_") for k in f.constants)  # no compiler builtins


def test_facts_preserve_optional_clock_probe_error_policy():
    from extractor.extractor import extract_ris

    f = extract_ris(ExtractorConfig(source=FTGPIO)).facts
    clock = next(item for item in f.resources
                 if item.acquisition == "devm_clk_get_enabled")
    assert clock.required is False
    assert clock.failure_policy == "probe_defer_only"


def test_facts_trimmed_no_kernel_noise():
    """Artifact plan: .facts must omit kernel-wide configuration noise."""
    from extractor.extractor import extract_ris
    f = extract_ris(ExtractorConfig(source=FTGPIO)).facts
    for k in f.constants:
        assert not k.startswith(("CONFIG_", "KASAN_", "TASK_", "CPUINFO_",
                                 "BUG_", "TAINT_", "pt_regs_")), f"noise kept: {k}"
    # real virtio_mmio facts: only VIRTIO_* register/status constants
    fv = extract_ris(ExtractorConfig(
        source=os.path.join(BASELINE_ROOT, "virtio_mmio.c"))).facts
    assert all(k.startswith("VIRTIO_") for k in fv.constants)


def test_merged_bind_roundtrip():
    """Per-backend .bind files merge into one multi-block file."""
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
    for need in (f"{name}.ris", f"{name}.facts",
                 f"{name}.harness.bind", f"{name}.formal.json",
                 f"{name}.device-spec.json", "generation-contract.json",
                 "score.txt"):
        assert need in files, f"missing {need}"
    contract = json.load(open(os.path.join(
        bdir, "generation-contract.json"), encoding="utf-8"))
    assert contract["policy"]["cardinality"] == "exactly-once"
    assert len(contract["register_operations"]) == 36
    assert contract["synthesis_readiness"]["llm_synthesis_ready"] is True
    assert contract["synthesis_readiness"]["backend_harness_ready"] is False
    assert contract["synthesis_readiness"]["backend_bare_metal_ready"] is False
    assert contract["synthesis_readiness"]["backend_linux_ready"] is False
    assert "whole_program_complete" in contract["claim_scope"]
    from extractor.spec import device_spec_from_dict
    device_document = json.load(open(os.path.join(
        bdir, f"{name}.device-spec.json"), encoding="utf-8"))
    assert device_spec_from_dict(device_document) == res.device_spec



def test_common_ops_to_c_emits_receipt_bound_compound_anchors():
    from backends.common import ops_to_c

    class AnchorBind:
        _primitives = {
            ("MmioRead", "B4"): "anchor_read32",
            ("MmioWrite", "B4"): "anchor_write32",
        }

        def prim(self, operation, width):
            return self._primitives.get((operation, width))

    def body(op_id, **fields):
        return {
            "op_id": op_id,
            "width": "B4",
            "addr": {"Fixed": {"base": "base", "offset": 4}},
            "access_domain": "mmio",
            "reliability": "Exact",
            "evidence": {},
            **fields,
        }

    ops = [
        {"Read": body("op_1", var="value")},
        {"Write": body("op_2", value={"Const": 7})},
        {"ReadModifyWrite": body(
            "op_3", read_var="old", transform={"Const": 9})},
        {"Write": {
            **body("op_4", value={"Const": 11}),
            "access_domain": "regmap",
            "reliability": "Unsupported",
        }},
    ]
    code = ops_to_c(ops, AnchorBind(), "base", {})
    receipt_anchor = re.compile(
        r"(?m)^\s*/\* REHARNESS_RIS_OP id=(op_\d+) "
        r"kind=(Read|Write|ReadModifyWrite) status=(lowered|rejected) "
        r"digest=[0-9a-f]+ \*/\n\s*__rh_op_\1: \{$")
    matches = list(receipt_anchor.finditer(code))
    assert [(match.group(1), match.group(3)) for match in matches] == [
        ("op_1", "lowered"),
        ("op_2", "lowered"),
        ("op_3", "lowered"),
        ("op_4", "rejected"),
    ]
    assert "__rh_op_op_1: {\n        value = anchor_read32(" in code
    assert "__rh_op_op_2: {\n        anchor_write32(0x7," in code
    assert ("__rh_op_op_3: {\n        uint32_t v = anchor_read32(" in code
            and "        anchor_write32(0x9," in code)
    rejected = re.search(
        r"__rh_op_op_4: \{(?P<body>.*?)^\s*\}", code,
        flags=re.MULTILINE | re.DOTALL)
    assert rejected is not None
    assert "REHARNESS_UNSUPPORTED_ACCESS_DOMAIN: regmap op_4" in \
        rejected.group("body")
    assert "anchor_read32" not in rejected.group("body")
    assert "anchor_write32" not in rejected.group("body")

    try:
        ops_to_c([ops[0], ops[0]], AnchorBind(), "base", {})
    except ValueError as error:
        assert "duplicate register RIS operation id: op_1" in str(error)
    else:
        raise AssertionError("duplicate operation anchors did not fail closed")


def test_harness_and_baremetal_emit_unique_operation_anchors():
    from extractor.formal import walk_leaf_ops
    from extractor.spec import default_bind
    from backends import baremetal as baremetal_gen
    from backends import harness as harness_gen

    result = extract_ris(ExtractorConfig(source=FTGPIO))
    required_ids = {
        (leaf.get("Read") or leaf.get("Write")
         or leaf.get("ReadModifyWrite"))["op_id"]
        for module in result.formal["modules"]
        for leaf in walk_leaf_ops(module["ops"])
        if (leaf.get("Read") or leaf.get("Write")
            or leaf.get("ReadModifyWrite"))
    }
    generators = {
        "harness": harness_gen.generate,
        "baremetal": baremetal_gen.generate,
    }
    receipt_anchor = re.compile(
        r"(?m)^\s*/\* REHARNESS_RIS_OP id=(op_\d+) "
        r"kind=(?:Read|Write|ReadModifyWrite) "
        r"status=(?:lowered|rejected) digest=[0-9a-f]+ \*/\n"
        r"\s*__rh_op_\1: \{$")
    label_re = re.compile(r"(?m)^\s*__rh_op_(op_\d+): \{$")
    for backend, generate in generators.items():
        code = generate(
            result.formal, result.device_spec,
            default_bind(result.device_spec, backend))
        anchored_receipts = [match.group(1)
                             for match in receipt_anchor.finditer(code)]
        labels = label_re.findall(code)
        assert set(anchored_receipts) == required_ids, backend
        assert labels == anchored_receipts, backend
        assert len(labels) == len(set(labels)), backend


def test_write_from_read_recipe_prevents_duplicate_hardware_reads():
    from extractor.spec import default_bind
    from backends import baremetal as baremetal_gen
    from backends import harness as harness_gen
    from gate.backend_lowering_oracle import build_generation_contract

    result = extract_ris(ExtractorConfig(source=FTGPIO))
    contract = build_generation_contract(result.formal)
    rows = {row["op_id"]: row for row in contract["register_operations"]}
    assert rows["op_2"]["lowering_recipe"] == {
        "kind": "read", "primitives": ["Read"]}
    assert rows["op_3"]["lowering_recipe"] == {
        "kind": "write_from_read", "primitives": ["Write"],
        "read_op_id": "op_2",
    }

    for backend, generate in {
            "harness": harness_gen.generate,
            "baremetal": baremetal_gen.generate}.items():
        code = generate(
            result.formal, result.device_spec,
            default_bind(result.device_spec, backend))
        anchor = re.search(
            r"__rh_op_op_3: \{(?P<body>.*?)^\s*\}", code,
            flags=re.MULTILINE | re.DOTALL)
        assert anchor is not None, backend
        body = anchor.group("body")
        assert "read32" not in body, (backend, body)
        assert "write32" in body, (backend, body)


def test_wrapper_summary_operations_receive_lowering_recipes():
    from gate.backend_lowering_oracle import build_generation_contract

    evidence = {
        "origin": "wrapper_summary",
        "function": "generic_caller",
        "wrapper_definition": {
            "origin": "direct",
            "function": "generic_read",
        },
    }
    common = {
        "width": "B4",
        "addr": {"Fixed": {"base": "base", "offset": 0x10}},
        "access_domain": "mmio",
        "reliability": "Exact",
        "evidence": evidence,
    }
    formal = {
        "driver": "wrapper-summary-contract",
        "metadata": {},
        "modules": [{"name": "generic_caller", "ops": [
            {"Read": {**common, "op_id": "op_read", "var": "value"}},
            {"ReadModifyWrite": {
                **common,
                "op_id": "op_write",
                "read_var": "value",
                "transform": {"Var": "value"},
            }},
            {"Write": {
                **common,
                "op_id": "op_summary_write",
                "value": {"Var": "swab32(value)"},
            }},
        ]}],
    }

    rows = {row["op_id"]: row for row in build_generation_contract(formal)[
        "register_operations"]}
    assert rows["op_read"]["lowering_recipe"] == {
        "kind": "read", "primitives": ["Read"]}
    assert rows["op_write"]["lowering_recipe"] == {
        "kind": "write_from_read", "primitives": ["Write"],
        "read_op_id": "op_read",
    }
    assert rows["op_summary_write"]["lowering_recipe"] == {
        "kind": "write_from_read", "primitives": ["Write"],
        "read_op_id": "op_read",
    }




def test_generation_contract_and_digest_are_pure_and_mutation_sensitive():
    import copy
    from backends.common import lowering_receipt, ris_op_digest
    from backends.linux import _normalize_ops
    from gate.backend_lowering_oracle import build_generation_contract

    op = {"Write": {
        "op_id": "op_1",
        "addr": {"Fixed": {"base": "base", "offset": 16}},
        "width": "B4",
        "value": {"Const": 1},
        "access_domain": "mmio",
        "reliability": "Exact",
        "evidence": {
            "source": "/tmp/driver.c",
            "line": 7,
            "byte_order": "native",
        },
    }}
    formal = {
        "driver": "pure-contract",
        "metadata": {"assurance_scope": {"whole_program_complete": True}},
        "modules": [{"name": "probe", "ops": [op]}],
    }
    original = copy.deepcopy(formal)
    first = build_generation_contract(formal)
    second = build_generation_contract(formal)
    assert first == second
    assert formal == original
    assert "contract_digest" not in op["Write"]

    # Contract output must not retain mutable aliases into canonical Formal.
    first["claim_scope"]["whole_program_complete"] = False
    first["register_operations"][0]["evidence"]["line"] = 99
    assert formal == original

    baseline = ris_op_digest(op)
    op["Write"]["value"] = {"Const": 2}
    assert ris_op_digest(op) != baseline
    assert (build_generation_contract(formal)["register_operations"][0]
            ["digest"] != second["register_operations"][0]["digest"])

    # A stale field from an older serialized Formal document is never trusted.
    mutated = copy.deepcopy(op)
    mutated["Write"]["contract_digest"] = baseline
    mutated["Write"]["addr"]["Fixed"]["offset"] = 20
    assert ris_op_digest(mutated) != baseline

    # Provenance is excluded, but lowering-relevant evidence is semantic.
    provenance_only = copy.deepcopy(op)
    provenance_only["Write"]["evidence"]["source"] = "/elsewhere/driver.c"
    assert ris_op_digest(provenance_only) == ris_op_digest(op)
    big_endian = copy.deepcopy(op)
    big_endian["Write"]["evidence"]["byte_order"] = "big"
    assert ris_op_digest(big_endian) != ris_op_digest(op)

    # Backend normalization may rewrite a deep-copy expression, but its
    # receipt must still name the canonical pre-normalization contract.
    source_private = copy.deepcopy(op)
    source_private["Write"]["value"] = {"Var": "chip->enabled"}
    canonical = ris_op_digest(source_private)
    normalized, _changed = _normalize_ops([source_private], "dev")
    assert normalized[0]["Write"]["value"] != source_private["Write"]["value"]
    assert ris_op_digest(normalized[0]) != canonical
    assert f"digest={canonical}" in lowering_receipt(normalized[0])
    assert "_backend_contract_digest" not in source_private["Write"]


def test_backend_lowering_oracle_cli_exit_status_and_output():
    import subprocess
    import tempfile
    from backends.common import lowering_receipt
    from gate.backend_lowering_oracle import build_generation_contract

    op = {"Write": {
        "op_id": "op_1",
        "addr": {"Fixed": {"base": "base", "offset": 16}},
        "width": "B4",
        "value": {"Const": 1},
        "access_domain": "mmio",
        "reliability": "Exact",
        "evidence": {},
    }}
    formal = {
        "driver": "oracle-cli",
        "modules": [{"name": "probe", "ops": [op]}],
    }
    with tempfile.TemporaryDirectory() as directory:
        formal_path = os.path.join(directory, "formal.json")
        contract_path = os.path.join(directory, "generation-contract.json")
        generated_path = os.path.join(directory, "generated.c")
        report_path = os.path.join(directory, "nested", "report.json")
        with open(formal_path, "w", encoding="utf-8") as handle:
            json.dump(formal, handle)
        with open(contract_path, "w", encoding="utf-8") as handle:
            json.dump(build_generation_contract(formal), handle)
        with open(generated_path, "w", encoding="utf-8") as handle:
            handle.write(lowering_receipt(op) + "\n")
        command = [
            sys.executable,
            os.path.join(GATE_ROOT,
                         "backend_lowering_oracle.py"),
            "--formal", formal_path,
            "--contract", contract_path,
            "--generated", generated_path,
            "--output", report_path,
        ]
        passed = subprocess.run(
            command, cwd=directory, env=_PYTHON_ENV,
            capture_output=True, text=True)
        assert passed.returncode == 0, passed.stderr
        passed_report = json.load(open(report_path, encoding="utf-8"))
        assert passed_report["complete"]
        assert len(passed_report["generated_sha256"]) == 64
        assert len(passed_report["contract_sha256"]) == 64

        with open(generated_path, "w", encoding="utf-8") as handle:
            handle.write("/* receipt deliberately removed */\n")
        failed = subprocess.run(
            command, cwd=directory, env=_PYTHON_ENV,
            capture_output=True, text=True)
        assert failed.returncode == 2
        report = json.load(open(report_path, encoding="utf-8"))
        assert report["complete"] is False
        assert report["missing"] == ["op_1"]

        frozen = json.load(open(contract_path, encoding="utf-8"))
        frozen["register_operations"][0]["digest"] = "0" * 16
        with open(contract_path, "w", encoding="utf-8") as handle:
            json.dump(frozen, handle)
        drift = subprocess.run(
            command, cwd=directory, env=_PYTHON_ENV,
            capture_output=True, text=True)
        assert drift.returncode == 3
        drift_report = json.load(open(report_path, encoding="utf-8"))
        assert drift_report["verifier_error"] == "formal_contract_mismatch"



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
    src = textwrap.dedent("""
        struct gpio_chip { int (*get)(void *, unsigned int); };
        struct pci_driver { int (*probe)(void *, void *); };
        static int chip_get(void *gc, unsigned int n) { return 0; }
        static int pci_probe(void *pdev, void *id) { return 0; }
        static const struct gpio_chip chip = { .get = chip_get };
        static struct pci_driver drv = { .probe = pci_probe };
    """)
    got = _ast_callback_bindings(src)
    assert got["chip_get"]["table"] == "gpio_chip"
    assert got["chip_get"]["field"] == "get"
    assert got["pci_probe"]["table"] == "pci_driver"
    assert got["pci_probe"]["field"] == "probe"


def test_callback_binding_covers_irq_pm_and_clock_forms():
    src = textwrap.dedent("""
        typedef int (*irq_handler_t)(int, void *);
        struct gpio_chip { int value; };
        struct gpio_irq_chip { int (*init_hw)(struct gpio_chip *); };
        struct device { int value; };
        struct dev_pm_ops {
            int (*suspend)(struct device *);
            int (*resume)(struct device *);
        };
        struct clk_hw { int value; };
        struct clk_ops {
            int (*prepare)(struct clk_hw *);
            int (*set_rate)(struct clk_hw *, unsigned long, unsigned long);
        };
        extern int register_irq(int line, irq_handler_t handler);
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
        static const struct dev_pm_ops pm = {
            .suspend = suspend_fn,
            .resume = resume_fn,
        };
        static int probe(void) {
            return register_irq(1, irq_fn);
        }
    """)
    got = _ast_callback_bindings(src)
    assert got["gpio_init_hw"]["table"] == "gpio_irq_chip"
    assert got["irq_fn"]["table"] == "irq_handler"
    assert got["suspend_fn"]["table"] == "dev_pm_ops"
    assert got["resume_fn"]["field"] == "resume"
    assert got["clk_prepare"]["table"] == "clk_ops"
    assert got["clk_set_rate"]["field"] == "set_rate"


def test_callback_binding_uses_owner_qualified_subsystem_roles():
    src = textwrap.dedent("""
        struct clk_hw { int value; };
        struct clk_ops { int (*is_prepared)(struct clk_hw *); };
        struct sdhci_host { int value; };
        struct sdhci_ops {
            void (*voltage_switch)(struct sdhci_host *);
            void (*set_clock)(struct sdhci_host *, unsigned int);
        };
        struct mmc_host { int value; };
        struct mmc_ios { int value; };
        struct mmc_host_ops {
            int (*start_signal_voltage_switch)(struct mmc_host *, struct mmc_ios *);
            int (*execute_sd_hs_tuning)(struct mmc_host *, void *);
        };
        static int prepared(struct clk_hw *hw) { return 0; }
        static void voltage(struct sdhci_host *host) {}
        static void clock(struct sdhci_host *host, unsigned int hz) {}
        static int switch_voltage(struct mmc_host *host, struct mmc_ios *ios) { return 0; }
        static int tuning(struct mmc_host *host, void *card) { return 0; }
        static const struct clk_ops clk = { .is_prepared = prepared };
        static const struct sdhci_ops sdhci = {
            .voltage_switch = voltage, .set_clock = clock,
        };
        static const struct mmc_host_ops mmc = {
            .start_signal_voltage_switch = switch_voltage,
            .execute_sd_hs_tuning = tuning,
        };
    """)
    got = _ast_callback_bindings(src)
    assert got["prepared"]["role"] == "get_status"
    assert got["voltage"]["role"] == "write_config"
    assert got["clock"]["role"] == "write_config"
    assert got["switch_voltage"]["role"] == "write_config"
    assert got["tuning"]["role"] == "write_config"


def test_callback_binding_keeps_private_owner_semantics_fail_closed():
    src = textwrap.dedent("""
        struct private_ops { void (*set_clock)(void *); };
        static void callback(void *state) {}
        static const struct private_ops ops = { .set_clock = callback };
    """)
    got = _ast_callback_bindings(src)
    assert got["callback"]["role"] == "unknown"


def test_callback_binding_assigns_roles_for_public_spi_controller_abis():
    source = r'''
        struct spi_device;
        struct spi_controller;
        struct spi_mem;
        struct spi_mem_op;
        struct spi_message;
        struct spi_transfer;

        struct spi_controller_mem_ops {
            int (*adjust_op_size)(struct spi_mem *, struct spi_mem_op *);
            int (*exec_op)(struct spi_mem *, const struct spi_mem_op *);
        };
        struct spi_controller {
            int (*setup)(struct spi_device *);
            void (*cleanup)(struct spi_device *);
            int (*transfer_one)(struct spi_controller *,
                                struct spi_device *, struct spi_transfer *);
            void (*handle_err)(struct spi_controller *, struct spi_message *);
        };

        static int setup(struct spi_device *dev) { return dev != 0; }
        static void cleanup(struct spi_device *dev) { (void)dev; }
        static int transfer_one(struct spi_controller *ctlr,
                                struct spi_device *dev,
                                struct spi_transfer *transfer) {
            (void)ctlr; (void)dev; (void)transfer; return 0;
        }
        static void handle_err(struct spi_controller *ctlr,
                               struct spi_message *message) {
            (void)ctlr; (void)message;
        }
        static int adjust_op_size(struct spi_mem *mem,
                                  struct spi_mem_op *op) {
            (void)mem; (void)op; return 0;
        }
        static int exec_op(struct spi_mem *mem,
                           const struct spi_mem_op *op) {
            (void)mem; (void)op; return 0;
        }

        static const struct spi_controller_mem_ops mem_ops = {
            .adjust_op_size = adjust_op_size,
            .exec_op = exec_op,
        };
        static const struct spi_controller controller = {
            .setup = setup,
            .cleanup = cleanup,
            .transfer_one = transfer_one,
            .handle_err = handle_err,
        };
        static void keep_tables(void) {
            (void)mem_ops;
            (void)controller;
        }
    '''
    bindings = _ast_callback_bindings(source)

    assert bindings["setup"]["public_callback_type"] is True
    assert bindings["setup"]["role"] == "init"
    assert bindings["cleanup"]["role"] == "remove"
    assert bindings["transfer_one"]["role"] == "setup_queue"
    assert bindings["handle_err"]["role"] == "reset"
    assert bindings["adjust_op_size"]["role"] == "write_config"
    assert bindings["exec_op"]["role"] == "write_config"


def test_direct_call_to_registered_callback_preserves_caller_effects():
    import tempfile

    source = textwrap.dedent(r'''
        struct irq_data { unsigned int hwirq; };
        struct irq_chip { void (*irq_ack)(struct irq_data *); };
        extern void writel(unsigned int value, void *addr);

        static void ack(struct irq_data *data)
        {
            writel(data->hwirq, (void *)0x1000);
        }

        static int configure(struct irq_data *data)
        {
            ack(data);
            return 0;
        }

        static const struct irq_chip chip = { .irq_ack = ack };
    ''')
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "direct_callback.c")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        result = extract_ris(ExtractorConfig(
            source=path, linux_root="/nonexistent"))

    from extractor.formal import walk_leaf_ops
    caller = next(module for module in result.formal["modules"]
                  if module["name"] == "configure")
    callback = next(module for module in result.formal["modules"]
                    if module["name"] == "ack")
    assert any("Write" in op for op in walk_leaf_ops(caller["ops"]))
    assert any("Write" in op for op in walk_leaf_ops(callback["ops"]))


def test_usb_lifecycle_oracle_ignores_synthetic_functions_without_ast():
    from types import SimpleNamespace
    from ast_analyzer import Func
    from extractor.usb_lifecycle import infer_usb_hcd_lifecycle

    synthetic = Func(
        name="synthetic_callback", line=1, cursor=None,
        source_path="", symbol_id="synthetic_callback",
        module_name="synthetic_callback", synthetic_role="read_config")
    result = infer_usb_hcd_lifecycle(
        [synthetic], SimpleNamespace(functions=[]),
        {"metadata": {"call_graph": {"calls": []}}})
    assert result["status"] == "unproven"
    assert result["tables"] == []
    assert result["reasons"] == ["no USB HCD lifecycle calls in source AST"]



def test_callback_signatures_reuse_binding_evidence_without_ast_walk():
    from extractor.spec_infer import infer_callback_signatures

    class Cursor:
        def walk_preorder(self):
            raise AssertionError("binding evidence should avoid an AST walk")

    class TranslationUnit:
        cursor = Cursor()

    signature = {
        "type": "int (*)(void *)",
        "return_type": "int",
        "params": [{"type": "void *"}],
        "variadic": False,
    }
    bindings = {
        "reset_impl": {
            "table": "sdhci_ops",
            "field": "reset",
            "signature": signature,
            "alternates": [],
        }
    }

    assert infer_callback_signatures(
        TranslationUnit(), {"sdhci_ops.reset"}, bindings=bindings) == {
        "sdhci_ops.reset": signature,
    }


def test_poll_accessors_are_not_declared_as_scalar_locals():
    from backends.common import value_var_names

    ops = [{"Loop": {
        "guard": {"Var": (
            "read_poll_timeout(sdhci_readl, tmp, tmp & READY, "
            "10, 1000, false, host, STATUS)")},
        "init": "read_poll_timeout(sdhci_readl, tmp, tmp & READY, 10, 1000, false, host, STATUS)",
        "step": "",
        "body": [],
    }}]
    names = value_var_names(ops)
    assert "tmp" in names
    assert "sdhci_readl" not in names
    assert "read_poll_timeout" not in names


def test_callback_binding_dynamic_gpio_irq_chip_init_hw():
    src = textwrap.dedent("""
        struct gpio_chip { int value; };
        struct gpio_irq_chip { int (*init_hw)(struct gpio_chip *); };
        struct platform_device { int value; };
        static int gpio_init_hw(struct gpio_chip *gc) { return 0; }
        static int probe(struct platform_device *pdev) {
            struct gpio_irq_chip *girq;
            girq->init_hw = gpio_init_hw;
            return 0;
        }
    """)
    got = _ast_callback_bindings(src)
    assert got["gpio_init_hw"]["table"] == "gpio_irq_chip"
    assert got["gpio_init_hw"]["field"] == "init_hw"


def test_callback_binding_tracks_struct_plus_raw_callback_call_assignment():
    src = textwrap.dedent("""
        struct device { int value; };
        struct bus_driver { int (*probe)(struct device *); };
        extern int register_probe(struct bus_driver *driver,
                                  int (*probe)(struct device *));
        static struct bus_driver driver;
        static int probe(struct device *dev) { return 0; }
        static int init(void) { return register_probe(&driver, probe); }
    """)
    got = _ast_callback_bindings(src)
    assert got["probe"]["table"] == "bus_driver"
    assert got["probe"]["field"] == "probe"
    assert got["probe"]["binding_kind"] == "call_assignment"


def test_callback_binding_tracks_positional_struct_array_initializers():
    src = textwrap.dedent("""
        struct queue_info { const char *name; void (*callback)(void *); };
        static void first(void *queue) {}
        static void second(void *queue) {}
        static void setup(void) {
            struct queue_info queues[] = {
                { "first", first },
                { "second", second },
            };
        }
    """)
    got = _ast_callback_bindings(src)
    assert got["first"]["table"] == "queue_info"
    assert got["first"]["field"] == "callback"
    assert got["first"]["binding_kind"] == "positional_initializer"
    assert got["second"]["table"] == "queue_info"


def test_callback_binding_preserves_unknown_role_and_rejects_local_pointer():
    src = textwrap.dedent("""
        struct private_ops { int (*observe)(void *); };
        static int bound(void *state) { return 0; }
        static int local_only(void *state) { return 0; }
        static const struct private_ops ops = { .observe = bound };
        static void setup(void) {
            int (*local)(void *) = local_only;
        }
    """)
    got = _ast_callback_bindings(src)
    assert got["bound"]["table"] == "private_ops"
    assert got["bound"]["field"] == "observe"
    assert got["bound"]["role"] == "unknown"
    assert got["bound"]["binding_kind"] == "initializer"
    assert "local_only" not in got


def test_callback_binding_mutations_require_owner_field_and_provenance():
    base = textwrap.dedent("""
        struct alpha_ops { void (*transition)(void *); };
        static void callback(void *state) {}
        static struct alpha_ops ops = { .transition = callback };
    """)
    binding = _ast_callback_bindings(base)["callback"]
    assert (binding["table"], binding["field"], binding["binding_kind"]) == (
        "alpha_ops", "transition", "initializer")
    assert binding["source"].endswith(".c") and binding["line"] > 0

    local_pointer = textwrap.dedent("""
        static void callback(void *state) {}
        static void setup(void) { void (*local)(void *) = callback; }
    """)
    assert "callback" not in _ast_callback_bindings(local_pointer)

    changed_owner = base.replace("alpha_ops", "beta_ops")
    changed = _ast_callback_bindings(changed_owner)["callback"]
    assert changed["table"] == "beta_ops"




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
    assert strict["audit"]["leaf_register_ops"] == 36
    assert strict["audit"]["duplicate_op_ids"] == []
    assert strict["claim_scope"]["whole_program_complete"] is False
    opaque = build_driver_report(os.path.join(
        FIXTURES_ROOT, "opaque_access.c"))
    assert opaque["strict_reliable"] is False
    assert opaque["access_accounting"]["unsupported"] == 3


def test_original_c_and_ris_differential_trace_match():
    from gate.ris_trace_oracle import verify_path_state_trace

    result = verify_path_state_trace()
    assert all(case["matched"] for case in result["cases"].values())
    assert result["mutation_caught"] is True


def test_real_ftgpio_callback_and_ris_differential_trace_match():
    from verification.ftgpio_trace_oracle import verify_ftgpio_ack_trace

    result = verify_ftgpio_ack_trace()
    assert all(case["matched"] for case in result["cases"].values())
    assert result["mutation_caught"] is True



def test_verified_linux_specific_lowering_is_not_gated_by_generic_loops():
    from extractor.metrics import score

    highbank = extract_ris(ExtractorConfig(source=os.path.join(
        BASELINE_ROOT, "clk-highbank.c")))
    readiness = score(
        highbank.device_spec, highbank.formal, highbank.warnings,
        highbank.facts,
        gen_results={"linux": {
            "compiled": True, "syntax_ok": True,
            "has_todo": False, "unsupported": False,
        }})
    assert readiness["backend_harness_ready"] is False
    assert readiness["backend_bare_metal_ready"] is False
    assert readiness["backend_linux_ready"] is False
    assert any("linux backend lowering/receipt attestation unavailable"
               in blocker for blocker in readiness["blockers"])




def test_target_clang_diagnostics_are_separate_from_header_noise():
    from extractor.metrics import count_clang_errors

    assert count_clang_errors([
        "clang header diag[3] /kernel/header.h:1: frontend mismatch",
        "clang diag[2] driver.c:1: warning",
    ]) == 0
    assert count_clang_errors(["clang diag[3] driver.c:1: real source error"]) == 1

    for filename in ("ahci.c", "sdhci-esdhc-mcf.c"):
        result = extract_ris(ExtractorConfig(source=os.path.join(
            BASELINE_ROOT, filename)))
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
    source = os.path.join(FIXTURES_ROOT, "svf_alias.c")
    result = extract_ris(ExtractorConfig(
        source=source, alias_mode="required"))
    analysis = result.stats["alias_analysis"]
    assert analysis["status"] == "success"
    assert result.stats["svf_aliases"] == ["alias"]
    assert analysis["facts"]["alias"]["accepted"] is True
    assert analysis["toolchain"]["clang_version"]
    op = next(o for o in walk_leaf_ops(result.formal["modules"][0]["ops"])
              if "Write" in o)
    evidence = op["Write"]["evidence"]
    assert evidence["alias_provenance"]["name"] == "alias"
    assert evidence["alias_provenance"]["kind"] == "MayAlias"


def test_svf_manifest_link_propagates_alias_across_translation_units():
    from extractor.alias import _tool_paths
    from extractor.formal import walk_leaf_ops

    if not all(os.path.isfile(path) for path in _tool_paths()[1:]):
        return
    fixture = os.path.join(
        FIXTURES_ROOT, "svf_linked.json")
    user_source = os.path.abspath(os.path.join(
        FIXTURES_ROOT, "svf_linked_user.c"))
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
            FIXTURES_ROOT, "svf_linked.json")
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
        source = os.path.join(FIXTURES_ROOT, "svf_alias.c")
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
    from backends import linux as linux_gen

    res = extract_ris(ExtractorConfig(source=source))
    bind = default_bind(res.device_spec, "linux")
    from deterministic_llm import DeterministicModel
    canned = ("```c\n#include <linux/module.h>\n"
              "static int rh_probe(void) { return 0; }\n"
              "module_init(rh_probe);\nMODULE_LICENSE(\"GPL\");\n```\n")
    code = linux_gen.generate(res.formal, res.device_spec, bind,
                              facts=res.facts,
                              model=DeterministicModel([canned] * 8))
    assert "TODO" not in code
    build = os.path.join(REHARNESS, "platform", "kernel", "build")
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
    clps = _linux_generate_and_compile(GPIO_CLPS711X, "rh_test_gpio_clps")
    dwapb = _linux_generate_and_compile(GPIO_DWAPB, "rh_test_gpio_dwapb")
    edu = _linux_generate_and_compile(EDU, "rh_test_edu")
    assert "module_platform_driver" in gpio
    assert "g->dat = devm_platform_ioremap_resource(pdev, 0);" in clps
    assert "g->dir = devm_platform_ioremap_resource(pdev, 1);" in clps
    assert "module_pci_driver" in edu and "struct miscdevice misc" in edu
    assert "struct gpio_dwapb_priv_bank" in dwapb
    assert "&bank->gc, bank" in dwapb
    assert "REHARNESS_UNSUPPORTED" not in gpio + clps + dwapb + edu


def test_ahci_linux_backend_builds_with_explicit_limitation():
    ahci = os.path.join(BASELINE_ROOT, "ahci.c")
    code = _linux_generate_and_compile(ahci, "rh_test_ahci")
    assert "module_pci_driver" in code
    assert "REHARNESS_UNSUPPORTED" in code


def _write_trace_formal(path):
    import json
    document = {
        "driver": "trace-test",
        "register_map": [
            {"name": "STATUS", "offset": 4},
            {"name": "CONTROL", "offset": 8},
            {"name": "DATA", "offset": 16},
        ],
        "modules": [
            {"name": "probe", "ops": [
                {"Read": {"addr": {"Symbolic": {"register": "STATUS"}}}},
                {"Write": {"addr": {"Symbolic": {"register": "CONTROL"}}}},
            ]},
            {"name": "callback", "ops": [
                {"ReadModifyWrite": {
                    "addr": {"Symbolic": {"register": "DATA"}}}},
            ]},
            {"name": "conditional", "ops": [
                {"Cond": {
                    "guard": {"Var": "set"},
                    "then_ops": [{"Write": {
                        "addr": {"Symbolic": {"register": "DATA"}}}}],
                    "else_ops": [],
                }},
                {"Cond": {
                    "guard": {"Var": "clear"},
                    "then_ops": [{"Write": {
                        "addr": {"Symbolic": {"register": "CONTROL"}}}}],
                    "else_ops": [],
                }},
            ]},
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _run_structured_trace(log, calls):
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        formal = root / "formal.json"
        serial = root / "serial.log"
        _write_trace_formal(formal)
        serial.write_text(log, encoding="utf-8")
        return subprocess.run(
            [sys.executable,
             os.path.join(REPORTING_TOOLS_ROOT, "trace_match.py"),
             str(serial), "--formal-json", str(formal),
             "--exercised-calls", calls],
            cwd=root, env=_PYTHON_ENV, text=True, capture_output=True)


def test_structured_trace_matches_reads_writes_and_rmw():
    result = _run_structured_trace("""
[rhfn] runtime_probe
[rh] R 0x4 0x0
[rh] W 0x8 0x1
[rhfn] runtime_callback
[rh] R 0x10 0x0
[rh] W 0x10 0x1
""", "probe=runtime_probe,callback=runtime_callback")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TRACE_MATCH_OK" in result.stdout
    assert "op 覆盖: 4/4" in result.stderr
    assert "寄存器覆盖: 3/3" in result.stderr


def test_structured_trace_accepts_the_executed_conditional_variant():
    result = _run_structured_trace("""
[rhfn] runtime_conditional
[rh] W 0x10 0x1
""", "conditional=runtime_conditional")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TRACE_MATCH_OK" in result.stdout
    assert "op 覆盖: 1/1" in result.stderr


def test_structured_trace_does_not_reuse_one_callback_segment():
    result = _run_structured_trace("""
[rhfn] runtime_probe
[rh] R 0x4 0x0
[rh] W 0x8 0x1
[rhfn] runtime_callback
[rh] R 0x10 0x0
[rh] W 0x10 0x1
""", "probe=runtime_probe,callback=runtime_callback,callback=runtime_callback")
    assert result.returncode == 1
    assert "call#3" in result.stdout
    assert "TRACE_MATCH_FAIL" in result.stdout


def test_structured_trace_uses_exact_runtime_function_names():
    result = _run_structured_trace("""
[rhfn] runtime_probe__callback
[rh] R 0x4 0x0
[rh] W 0x8 0x1
""", "probe=runtime_probe")
    assert result.returncode == 1
    assert "probe=>runtime_probe" in result.stdout


def test_instrument_mmio_adds_idempotent_function_boundaries():
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "driver.c"
        source.write_text("""#include <linux/io.h>
static int callback(void *base)
{
    return readl(base + 4);
}
""", encoding="utf-8")
        for _ in range(2):
            result = subprocess.run(
                [sys.executable,
                 os.path.join(SOURCE_TOOLS_ROOT, "instrument_mmio.py"),
                 str(source)], cwd=source.parent, env=_PYTHON_ENV,
                text=True, capture_output=True)
            assert result.returncode == 0, result.stderr
        text = source.read_text(encoding="utf-8")
        assert text.count('RH_TRACE_FN("callback");') == 1
        assert text.count("reharness MMIO trace instrumentation") == 1


def test_callback_signature_evidence_preserves_public_linux_abi():
    result = extract_ris(ExtractorConfig(source=FTGPIO))
    signatures = result.facts.callback_signatures

    direction_input = signatures["gpio_chip.direction_input"]
    assert direction_input["return_type"] == "int"
    assert [param["type"] for param in direction_input["params"]] == [
        "struct gpio_chip *", "unsigned int"]

    direction_output = signatures["gpio_chip.direction_output"]
    assert [param["type"] for param in direction_output["params"]] == [
        "struct gpio_chip *", "unsigned int", "int"]

    get_multiple = signatures["gpio_chip.get_multiple"]
    assert [param["type"] for param in get_multiple["params"]] == [
        "struct gpio_chip *", "unsigned long *", "unsigned long *"]


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
