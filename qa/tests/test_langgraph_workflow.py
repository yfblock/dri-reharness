from __future__ import annotations

import json
from pathlib import Path
import sys
import types

import pytest

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from langgraph_workflow.graph import run_workflow  # noqa: E402
from langgraph_workflow.tools import (  # noqa: E402
    build_synthesis_evidence,
    discover_driver_files,
    normalize_request,
    )


def _known_profile_source(tmp_path: Path) -> Path:
    source = tmp_path / "driver.c"
    source.write_text(
        (_paths.REPO_ROOT / "benchmarks/drivers/baseline/edu.c").read_text(
            encoding="utf-8"),
        encoding="utf-8",
    )
    return source


def test_build_synthesis_evidence_contains_semantics_not_only_artifact_paths(tmp_path):
    from types import SimpleNamespace

    payload = build_synthesis_evidence(
        {"driver": "demo", "register_map": [], "modules": [
            {"name": "demo_probe", "ops": []},
        ]},
        SimpleNamespace(name="demo", cls="generic_mmio", functions=[]),
        SimpleNamespace(primitives=[], types=[], state=[], callbacks=[], includes=[]),
        SimpleNamespace(constants={}, structs=[]),
        inventory={"files": ["demo.c"], "digest": "source-digest"},
        readiness={"llm_synthesis_ready": True},
        bundle_dir=tmp_path,
        bundle_digest="bundle-digest",
        contract_verification={
            "status": "inconclusive",
            "contracts": [{"id": "gpio-generic"}],
        },
    )

    assert payload["driver"] == "demo"
    assert payload["modules"][0]["name"] == "demo_probe"
    assert payload["source_files"] == ["demo.c"]
    assert payload["source_digest"] == "source-digest"
    assert payload["readiness"]["llm_synthesis_ready"] is True
    assert payload["bundle"]["directory"] == str(tmp_path)
    assert payload["subsystem_contract_verification"]["status"] == (
        "inconclusive")


def test_default_analysis_workflow_runs_without_preloaded_verification_path(
        tmp_path: Path):
    source = _known_profile_source(tmp_path)

    result = run_workflow(
        {"source": str(source), "mode": "analysis"},
        repo_root=tmp_path,
    )

    assert result["status"] == "analysis_complete"
    assert "subsystem_contract_verification" in result["analysis"]


def test_discover_driver_files_covers_every_manifest_source(tmp_path):
    first = tmp_path / "first.c"
    second = tmp_path / "second.c"
    first.write_text("int first(void) { return 1; }\n", encoding="utf-8")
    second.write_text("int second(void) { return 2; }\n", encoding="utf-8")
    manifest = tmp_path / "driver.json"
    manifest.write_text(json.dumps({
        "name": "multi",
        "sources": [first.name, second.name],
    }), encoding="utf-8")

    request = normalize_request({"source": str(manifest)}, repo_root=tmp_path)
    inventory = discover_driver_files(request, repo_root=tmp_path)

    assert inventory["driver"] == "multi"
    assert inventory["files"] == [str(first), str(second)]
    assert inventory["file_count"] == 2
    assert len(inventory["digest"]) == 64


def test_normalize_request_selects_profile_for_multisource_descriptor():
    descriptor = _paths.REPO_ROOT / "qa/tests/fixtures/spi-client.json"

    request = normalize_request(
        {"source": str(descriptor), "mode": "analysis"},
        repo_root=_paths.REPO_ROOT,
    )

    assert request["profile"]["id"] == "spi-generic"
    assert request["profile_plan"]["id"] == "spi-generic"
    assert request["profile_plan"]["bus"] == "spi"
    assert request["missing_capabilities"] == []


def test_normalize_request_preserves_subsystem_contract_without_transport_profile(
        tmp_path: Path):
    source = tmp_path / "clock-driver.c"
    source.write_text(
        """
        struct clk_ops demo_ops;
        struct clk_hw demo_hw;
        void register_clock(void) {
            clk_register(NULL, &demo_hw);
        }
        """,
        encoding="utf-8",
    )

    request = normalize_request(
        {"source": str(source), "mode": "analysis"}, repo_root=tmp_path)

    assert [item["id"] for item in request["subsystem_contracts"]] == [
        "clock-generic"
    ]
    assert request["profile_plan"] is None


def test_manifest_content_changes_invalidate_source_digest(tmp_path):
    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    manifest = tmp_path / "driver.json"
    manifest.write_text(json.dumps({
        "name": "first", "sources": [source.name],
    }), encoding="utf-8")
    request = normalize_request({"source": str(manifest)}, repo_root=tmp_path)
    before = discover_driver_files(request, repo_root=tmp_path)

    manifest.write_text(json.dumps({
        "name": "second", "sources": [source.name],
    }), encoding="utf-8")
    after = discover_driver_files(request, repo_root=tmp_path)

    assert before["digest"] != after["digest"]


def test_normalize_request_rejects_source_outside_repository(tmp_path):
    outside = tmp_path.parent / "outside-driver.c"
    outside.write_text("int outside(void) { return 0; }\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside repository"):
        normalize_request({"source": str(outside)}, repo_root=tmp_path)


def test_normalize_request_allows_explicit_external_output_dir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    output = tmp_path / "artifacts"

    request = normalize_request({
        "source": str(source), "mode": "analysis", "output_dir": str(output),
    }, repo_root=repo)

    assert request["output_dir"] == str(output.resolve())


def test_normalize_request_allows_auto_generated_manifest_in_external_output_dir(
        tmp_path):
    output = tmp_path / "artifacts"
    normalized = __import__("auto_driver").normalize_input(
        _paths.REPO_ROOT / "qa/tests/fixtures/spi-client.json",
        repo_root=_paths.REPO_ROOT,
        output_dir=output,
    )

    request = normalize_request({
        "source": str(_paths.REPO_ROOT / "qa/tests/fixtures/spi-client.json"),
        "experiment_manifest": normalized["manifest"],
        "mode": "experiment",
        "output_dir": str(output),
    }, repo_root=_paths.REPO_ROOT)

    assert request["experiment_manifest"] == normalized["manifest"]


def test_normalize_request_rejects_external_manifest_outside_output_dir(tmp_path):
    source = _paths.REPO_ROOT / "qa/tests/fixtures/spi-client.json"
    output = tmp_path / "artifacts"
    unrelated = tmp_path / "unrelated" / "manifest.json"
    unrelated.parent.mkdir()
    unrelated.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="generated manifest"):
        normalize_request({
            "source": str(source),
            "experiment_manifest": str(unrelated),
            "mode": "experiment",
            "output_dir": str(output),
        }, repo_root=_paths.REPO_ROOT)


def test_workflow_analyzes_before_running_pipeline(tmp_path):
    source = _known_profile_source(tmp_path)
    events: list[str] = []

    def analyze(request, inventory):
        events.append("analyze")
        assert inventory["files"] == [str(source)]
        return {
            "driver": "driver",
            "evidence": {"digest": "evidence"},
            "readiness": {"llm_synthesis_ready": True},
        }

    def pipeline(request, analysis):
        events.append("pipeline")
        assert analysis["driver"] == "driver"
        return {"accepted": True, "status": "accepted"}

    result = run_workflow(
        {"request": "run the pipeline", "source": str(source), "mode": "generation"},
        repo_root=tmp_path,
        analyzer=analyze,
        pipeline=pipeline,
    )

    assert events == ["analyze", "pipeline"]
    assert result["pipeline_result"] == {"accepted": True, "status": "accepted"}
    assert result["status"] == "inconclusive"
    assert result["translation_status"] == "inconclusive"
    assert result["failure"]["stage"] == "profile"


def test_pipeline_rejection_propagates_to_workflow_status(tmp_path):
    source = _known_profile_source(tmp_path)

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": True},
        },
        pipeline=lambda request, analysis: {
            "accepted": False, "status": "failed",
        },
    )

    assert result["status"] == "failed"


def test_workflow_runs_generation_without_runtime_profile_and_downgrades_status(tmp_path):
    source = tmp_path / "unknown.c"
    source.write_text("int unknown_driver(void) { return 0; }\n", encoding="utf-8")
    pipeline_calls: list[str] = []

    def pipeline(request, analysis):
        pipeline_calls.append("called")
        return {"accepted": True, "status": "accepted"}

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": True},
        },
        pipeline=pipeline,
    )

    assert pipeline_calls == ["called"]
    assert result["normalized"]["missing_capabilities"] == ["runtime_profile"]
    assert result["status"] == "inconclusive"
    assert result["translation_status"] == "inconclusive"


def test_workflow_preserves_generic_profile_plan_in_normalized_state(tmp_path):
    source = tmp_path / "renamed_bus_driver.c"
    source.write_text(
        "struct spi_driver translated_driver;\n"
        "static struct spi_device *device;\n"
        "module_spi_driver(translated_driver);\n",
        encoding="utf-8",
    )

    result = run_workflow(
        {"source": str(source), "mode": "analysis"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": False,
                           "blockers": ["runtime fixture manifest"]},
        },
    )

    assert result["normalized"]["profile"]["id"] == "spi-generic"
    assert result["normalized"]["profile_plan"]["bus"] == "spi"
    assert result["normalized"]["missing_capabilities"] == ["runtime_identity"]


def test_workflow_converts_node_exception_to_structured_failure(tmp_path):
    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")

    def broken_analyzer(request, inventory):
        raise RuntimeError("extractor failed: malformed translation unit")

    result = run_workflow(
        {"source": str(source), "mode": "analysis"},
        repo_root=tmp_path,
        analyzer=broken_analyzer,
    )

    assert result["status"] == "failed"
    assert result["error"]["stage"] == "workflow"
    assert result["error"]["exception"] == "RuntimeError"
    assert "malformed translation unit" in result["error"]["message"]


def test_generation_pipeline_runs_exactly_once_per_request(tmp_path, monkeypatch):
    import langgraph_workflow.pipeline_entry as entry

    calls: list[str] = []

    def fake_generation(request, analysis, *, repo_root):
        calls.append(request["source"])
        return {"accepted": True, "status": "accepted",
                "output_dir": request["output_dir"]}

    monkeypatch.setattr(entry, "_run_generation_via_graph", fake_generation)
    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    request = normalize_request({
        "source": str(source), "mode": "generation",
        "output_dir": str(tmp_path / "out"),
    }, repo_root=tmp_path)

    result = entry.run_pipeline_backend(
        request, {"driver": "driver"}, repo_root=tmp_path)

    assert result["status"] == "accepted"
    assert calls == [str(source)]


def test_generation_pipeline_preserves_multisource_transaction_evidence(
        tmp_path, monkeypatch):
    first = tmp_path / "first.c"
    second = tmp_path / "second.c"
    first.write_text("int first(void) { return 0; }\n", encoding="utf-8")
    second.write_text("int second(void) { return 0; }\n", encoding="utf-8")
    manifest = tmp_path / "driver.json"
    manifest.write_text(json.dumps({
        "name": "driver", "sources": [first.name, second.name],
    }), encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run_backend_pipeline(result, outdir, source, model=None):
        captured["validation"] = result.formal["metadata"][
            "transaction_validation"]
        return {"accepted": True, "status": "accepted",
                "output_dir": outdir, "return_code": 0}


    import langgraph_workflow.pipeline_entry as entry
    monkeypatch.setattr(entry, "run_backend_pipeline",
                        fake_run_backend_pipeline)
    request = normalize_request({
        "source": str(manifest), "mode": "generation",
        "output_dir": str(tmp_path / "out"),
    }, repo_root=tmp_path)

    result = entry.run_pipeline_backend(
        request, {"driver": "driver", "files": [str(first), str(second)]},
        repo_root=tmp_path)
    assert result["status"] == "accepted"
    assert captured["validation"]["coverage_complete"] is True


def test_pipeline_success_requires_strict_readiness_for_each_backend():
    from backends.pipeline import _pipeline_success

    assert _pipeline_success({
        "backend_harness_ready": True,
        "backend_bare_metal_ready": True,
        "backend_linux_ready": True,
    }) is True
    assert _pipeline_success({
        "backend_harness_ready": True,
        "backend_bare_metal_ready": True,
        "backend_linux_ready": False,
    }) is False


def test_generation_pipeline_returns_structured_provider_failure(tmp_path, monkeypatch):
    from langchain_bridge import LangChainBridgeError
    from types import SimpleNamespace

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "extractor", types.SimpleNamespace(
        ExtractorConfig=Config,
        extract_ris=lambda config: SimpleNamespace(formal=None)))
    import langgraph_workflow.pipeline_entry as entry

    def failing_build(*args, **kwargs):
        raise LangChainBridgeError("langchain-openai is required")

    monkeypatch.setattr(entry, "run_backend_pipeline", failing_build)
    request = normalize_request({
        "source": str(source), "mode": "generation",
        "output_dir": str(tmp_path / "out"),
    }, repo_root=tmp_path)

    result = entry.run_pipeline_backend(request, {"driver": "driver"},
                                        repo_root=tmp_path)
    assert result["accepted"] is False
    assert result["status"] == "failed"
    assert result["failure"]["failure_class"] == "infrastructure"
    assert result["failure"]["stage"] == "generation"
    assert "langchain-openai" in result["failure"]["message"]


def test_analysis_mode_stops_after_analysis(tmp_path):
    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    events: list[str] = []

    def analyze(request, inventory):
        events.append("analyze")
        return {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": False,
                           "blockers": ["incomplete evidence"]},
        }

    def unexpected_pipeline(request, analysis):
        raise AssertionError("analysis mode must not run the Pipeline")

    result = run_workflow(
        {"source": str(source), "mode": "analysis"},
        repo_root=tmp_path,
        analyzer=analyze,
        pipeline=unexpected_pipeline,
    )

    assert events == ["analyze"]
    assert result["status"] == "analysis_complete"
    assert result["translation_status"] == "blocked"
    assert result["translation_eligible"] is False
    assert "pipeline_result" not in result


def test_workflow_can_resume_from_a_langgraph_checkpoint(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver

    source = tmp_path / "driver.c"
    source.write_text("int driver(void) { return 0; }\n", encoding="utf-8")
    saver = InMemorySaver()

    result = run_workflow(
        {"source": str(source), "mode": "analysis"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": True},
        },
        checkpointer=saver,
        config={"configurable": {"thread_id": "workflow-test"}},
    )

    assert result["status"] == "analysis_complete"
    assert result["translation_status"] == "eligible"
    assert [event["node"] for event in result["events"]] == [
        "normalize_input", "discover_driver_files", "analyze_driver_files",
        "build_pipeline_plan", "finalize",
    ]





def test_translation_mode_blocks_when_analysis_is_not_ready(tmp_path):
    source = _known_profile_source(tmp_path)
    calls: list[str] = []

    def pipeline(request, analysis):
        calls.append("pipeline")
        return {"accepted": True, "status": "accepted"}

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {
                "llm_synthesis_ready": False,
                "blockers": ["call context is incomplete"],
            },
        },
        pipeline=pipeline,
    )

    assert calls == []
    assert result["status"] == "blocked"
    assert result["translation_status"] == "blocked"
    assert result["translation_eligible"] is False
    assert result["failure"]["stage"] == "readiness"
    assert "call context is incomplete" in result["failure"]["details"]["blockers"]


def test_translation_mode_fails_closed_when_readiness_is_missing(tmp_path):
    source = _known_profile_source(tmp_path)

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=tmp_path,
        analyzer=lambda request, inventory: {"driver": inventory["driver"]},
        pipeline=lambda request, analysis: pytest.fail(
            "pipeline must not run without readiness evidence"),
    )

    assert result["status"] == "blocked"
    assert result["translation_status"] == "blocked"
    assert result["translation_eligible"] is False
    assert result["failure"]["stage"] == "readiness"


def test_generation_finalization_rejects_failed_subsystem_contract(
        tmp_path: Path):
    source = _paths.REPO_ROOT / "benchmarks/drivers/baseline/edu.c"

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=_paths.REPO_ROOT,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": True},
            "subsystem_contract_verification": {
                "status": "fail",
                "contracts": [{"id": "generic-contract"}],
            },
        },
        pipeline=lambda request, analysis: {
            "accepted": True,
            "status": "accepted",
        },
    )

    assert result["status"] == "failed"
    assert result["translation_status"] == "failed"
    assert result["failure"]["stage"] == "subsystem_contract"


def test_generation_finalization_keeps_incomplete_subsystem_contract_inconclusive(
        tmp_path: Path):
    source = _paths.REPO_ROOT / "benchmarks/drivers/baseline/edu.c"

    result = run_workflow(
        {"source": str(source), "mode": "generation"},
        repo_root=_paths.REPO_ROOT,
        analyzer=lambda request, inventory: {
            "driver": inventory["driver"],
            "readiness": {"llm_synthesis_ready": True},
            "subsystem_contract_verification": {
                "status": "inconclusive",
                "contracts": [{"id": "generic-contract"}],
            },
        },
        pipeline=lambda request, analysis: {
            "accepted": True,
            "status": "accepted",
        },
    )

    assert result["status"] == "inconclusive"
    assert result["translation_status"] == "inconclusive"
    assert result["failure"]["stage"] == "subsystem_contract"



def test_analysis_mode_never_enters_the_pipeline_subgraphs(monkeypatch):
    import langgraph_workflow.pipeline_entry as entry

    monkeypatch.setattr(
        entry, "_run_experiment_via_v2",
        lambda *args, **kwargs: pytest.fail("experiment subgraph must not run"))
    monkeypatch.setattr(
        entry, "_run_generation_via_graph",
        lambda *args, **kwargs: pytest.fail("generation subgraph must not run"))

    result = entry.run_pipeline_backend(
        {"mode": "analysis", "output_dir": "/tmp/analysis-only"}, {},
        repo_root=".")
    assert result["status"] == "analysis_only"




