"""Experiment V2 graph contract tests (offline; no QEMU, no kernel build).

Covers: graph topology, manifest metadata parsing, [rhcov] coverage
parsing, the repair counter, the closed-loop acceptance path and the
exhausted-repair failure path (both via injected executors), and
the experiment.json record written by ``finalize``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from langgraph_workflow import experiment_v2_graph as v2  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]


class _EchoBridge:
    """测试桥：候选 == 原始源码（原 IdentityBridge 语义，圈在测试层）。"""

    def __init__(self, source):
        self._source = Path(source)

    def synthesize(self, manifest, formal):
        return self._source.read_text()


EDU_MANIFEST = REPO_ROOT / "benchmarks/experiments/edu.json"
EDU_SOURCE = REPO_ROOT / "benchmarks/drivers/baseline/edu.c"


def test_graph_topology_has_ten_nodes():
    graph = v2.build_experiment_v2(
        driver_source=str(EDU_SOURCE), driver_name="edu",
        manifest_path=str(EDU_MANIFEST), llm_bridge=None,
        output_root="/tmp/v2-topo")
    names = set(graph.get_graph().nodes)
    for node in ("build_driver", "ris_extract", "llm_gen_tests",
                 "baseline_qemu", "llm_synthesize", "candidate_compile",
                 "candidate_qemu", "diff_compare", "repair", "finalize"):
        assert node in names, node


def test_manifest_meta_reads_module_and_success_pattern():
    meta = v2.manifest_qemu_meta(EDU_MANIFEST)
    assert meta == {"module": "edu_drv", "success_pattern": "EDU_TRACE_OK"}


def test_manifest_meta_defaults_module_to_name():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        m = Path(d) / "m.json"
        m.write_text(json.dumps({"name": "x", "runtime": {"qemu": {}}}))
        meta = v2.manifest_qemu_meta(m)
        assert meta["module"] == "x"
        assert meta["success_pattern"] == ""


def test_parse_rhcov_extracts_unique_function_names():
    serial = ("[rhcov] edu_probe\n[    0.1] noise\n[rhcov] edu_probe\n"
              "[rhcov] edu_read\n")
    assert v2.parse_rhcov(serial) == {"edu_probe", "edu_read"}


def test_coverage_summary_counts_against_inventory():
    summary = v2.coverage_summary({"a", "b", "zzz"}, ["a", "b", "c", "a"])
    assert summary["covered"] == ["a", "b"]
    assert summary["covered_count"] == 2
    assert summary["total"] == 3
    assert summary["pct"] == 66.7


def test_coverage_summary_empty_inventory_is_none():
    assert v2.coverage_summary({"a"}, [])["pct"] is None


def test_repair_counter_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "_repair_count_file", str(tmp_path / "rc"))
    v2._reset_rc()
    assert v2._get_rc() == 0
    v2._inc_rc()
    v2._inc_rc()
    assert v2._get_rc() == 2
    v2._reset_rc()
    assert v2._get_rc() == 0


def test_identity_bridge_echoes_source():
    bridge = _EchoBridge(EDU_SOURCE)
    assert bridge.synthesize({}, {}) == EDU_SOURCE.read_text()


def test_acceptance_path_writes_experiment_json(tmp_path, monkeypatch):
    """Closed loop with fake executors: both sides pass, record is written."""
    runs: list[Path] = []

    def fake_kbuild(source_c, module_name, build_dir):
        build_dir.mkdir(parents=True, exist_ok=True)
        ko = build_dir / f"{module_name}.ko"
        ko.write_bytes(b"fake-ko")
        return ko, ["edu_probe", "edu_read", "edu_write"]

    def fake_qemu(module_ko, work_dir, extra_tests=None):
        runs.append(module_ko)
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        serial = "EDU_TRACE_OK\n[rhcov] edu_probe\n[rhcov] edu_read\n"
        (work_dir / "serial.log").write_text(serial)
        return {"serial": serial, "pass": True,
                "serial_path": str(work_dir / "serial.log"), "rc": 0}

    def fake_pipeline(extraction, outdir, source):
        generated = Path(outdir) / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        (generated / "linux.c").write_text(
            "int probe(void) { return 0; }\nMODULE_LICENSE(\"GPL\");\n")
        return {"accepted": True, "status": "accepted", "return_code": 0,
                "gen_results": {"linux": {"compiled": True}},
                "backend_results": {"linux": "ok"}}

    out = tmp_path / "out"
    graph = v2.build_experiment_v2(
        driver_source=str(EDU_SOURCE), driver_name="edu",
        manifest_path=str(EDU_MANIFEST),
        llm_bridge=_EchoBridge(EDU_SOURCE),
        output_root=str(out), max_repair=2,
        executors={"kbuild": fake_kbuild, "qemu_run": fake_qemu,
                   "backend_pipeline": fake_pipeline})
    final = graph.invoke({}, config={"recursion_limit": 50})

    assert final["accepted"] is True
    assert final["status"] == "accepted"
    assert len(runs) == 2  # baseline + candidate
    record = json.loads((out / "experiment.json").read_text())
    assert record["schema"] == "reharness-experiment-v2"
    assert record["accepted"] is True
    assert record["baseline_coverage"]["total"] == 3
    assert record["baseline_coverage"]["covered_count"] == 2
    assert record["candidate_coverage"]["covered_count"] == 2


def test_failure_path_exhausts_repairs_and_fails(tmp_path, monkeypatch):
    """Candidate compile keeps failing: bounded repairs then failed status."""
    repair_calls = []

    def fake_kbuild(source_c, module_name, build_dir):
        # baseline（第一次,真实 src）成功；candidate（空/identity 后同源）失败
        if "build" in str(build_dir) and Path(build_dir).name == "build":
            return None, []
        build_dir.mkdir(parents=True, exist_ok=True)
        ko = build_dir / f"{module_name}.ko"
        ko.write_bytes(b"fake-ko")
        return ko, ["edu_probe"]

    def fake_qemu(module_ko, work_dir, extra_tests=None):
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        serial = "EDU_TRACE_OK\n[rhcov] edu_probe\n"
        (work_dir / "serial.log").write_text(serial)
        return {"serial": serial, "pass": True,
                "serial_path": str(work_dir / "serial.log"), "rc": 0}

    def failing_backend_pipeline(extraction, out_dir, source):
        # 候选编译经由共享 backend pipeline：linux 后端编译恒失败
        return {"gen_results": {"linux": {"compiled": False}},
                "backend_results": {"linux": {"compiled": False}},
                "accepted": False, "status": "failed"}

    real_repair = v2._inc_rc

    def counting_inc():
        repair_calls.append(1)
        real_repair()

    monkeypatch.setattr(v2, "_inc_rc", counting_inc)
    out = tmp_path / "out"
    graph = v2.build_experiment_v2(
        driver_source=str(EDU_SOURCE), driver_name="edu",
        manifest_path=str(EDU_MANIFEST),
        llm_bridge=_EchoBridge(EDU_SOURCE),
        output_root=str(out), max_repair=2,
        executors={"kbuild": fake_kbuild, "qemu_run": fake_qemu,
                   "backend_pipeline": failing_backend_pipeline})
    final = graph.invoke({}, config={"recursion_limit": 50})

    assert final["accepted"] is False
    assert final["status"] == "failed"
    assert len(repair_calls) >= 3  # 受限修复至少走满
    record = json.loads((out / "experiment.json").read_text())
    assert record["status"] == "failed"
    assert record["repair_count"] >= 2


def test_baseline_failure_short_circuits_to_failed(tmp_path, monkeypatch):
    """Baseline QEMU 失败：diff 不等 → 修复回路 → 最终 failed。"""

    def fake_kbuild(source_c, module_name, build_dir):
        build_dir.mkdir(parents=True, exist_ok=True)
        ko = build_dir / f"{module_name}.ko"
        ko.write_bytes(b"fake-ko")
        return ko, ["edu_probe"]

    calls = {"n": 0}

    def fake_qemu(module_ko, work_dir, extra_tests=None):
        calls["n"] += 1
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        ok = calls["n"] == 1  # 仅 baseline 通过；candidate 永远失败 → diff 恒不等
        serial = "EDU_TRACE_OK\n[rhcov] edu_probe\n" if ok else "EDU_TRACE_FAIL\n"
        (work_dir / "serial.log").write_text(serial)
        return {"serial": serial, "pass": ok,
                "serial_path": str(work_dir / "serial.log"), "rc": 0}

    out = tmp_path / "out"
    graph = v2.build_experiment_v2(
        driver_source=str(EDU_SOURCE), driver_name="edu",
        manifest_path=str(EDU_MANIFEST),
        llm_bridge=_EchoBridge(EDU_SOURCE),
        output_root=str(out), max_repair=1,
        executors={"kbuild": fake_kbuild, "qemu_run": fake_qemu})
    final = graph.invoke({}, config={"recursion_limit": 50})
    assert final["status"] == "failed"
