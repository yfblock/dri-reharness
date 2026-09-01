"""LangGraph workflow that orchestrates existing reharness services."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from langgraph.graph import END, START, StateGraph

from .state import WorkflowState
from .tools import (
    analyze_driver_files,
    discover_driver_files,
    normalize_request,
)
from .pipeline_entry import run_pipeline_backend


Analyzer = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
Pipeline = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class WorkflowServices:
    analyzer: Analyzer | None = None
    pipeline: Pipeline | None = None


def _event(state: WorkflowState, name: str) -> list[dict[str, Any]]:
    return [*state.get("events", []), {"node": name, "status": "passed"}]


def _translation_readiness(analysis: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Return a fail-closed translation gate and its structured explanation."""
    readiness = analysis.get("readiness")
    if not isinstance(readiness, Mapping):
        return False, {
            "stage": "readiness",
            "message": "translation readiness evidence is missing",
            "details": {"blockers": ["readiness.llm_synthesis_ready is missing"]},
        }
    if readiness.get("llm_synthesis_ready") is True:
        return True, {}
    blockers = readiness.get("blockers", [])
    if not isinstance(blockers, list):
        blockers = [str(blockers)]
    return False, {
        "stage": "readiness",
        "message": "translation readiness gate is not satisfied",
        "details": {"blockers": [str(item) for item in blockers]},
    }


def build_graph(*, repo_root: str | Path, services: WorkflowServices | None = None,
                analyzer: Analyzer | None = None,
                pipeline: Pipeline | None = None, checkpointer: Any = None,
                profile_registry: Any = None):
    """Compile the workflow graph with injectable services for tests."""
    root = Path(repo_root).resolve()
    configured = services or WorkflowServices(analyzer=analyzer, pipeline=pipeline)
    analysis_fn = configured.analyzer
    pipeline_fn = configured.pipeline

    def normalize_node(state: WorkflowState) -> dict[str, Any]:
        normalized = normalize_request(
            state["input"], repo_root=root, profile_registry=profile_registry)
        return {"normalized": normalized, "events": _event(state, "normalize_input")}

    def discover_node(state: WorkflowState) -> dict[str, Any]:
        inventory = discover_driver_files(state["normalized"], repo_root=root)
        return {"inventory": inventory, "events": _event(state, "discover_driver_files")}

    def analyze_node(state: WorkflowState) -> dict[str, Any]:
        fn = analysis_fn or (lambda request, inventory: analyze_driver_files(
            request, inventory, repo_root=root))
        analysis = dict(fn(state["normalized"], state["inventory"]))
        return {"analysis": analysis, "events": _event(state, "analyze_driver_files")}

    def plan_node(state: WorkflowState) -> dict[str, Any]:
        request = state["normalized"]
        translation_requested = request["mode"] != "analysis"
        translation_eligible, readiness_failure = _translation_readiness(
            state["analysis"])
        missing_capabilities = list(request.get("missing_capabilities", []))
        plan = {
            "mode": request["mode"],
            "backend": request["backend"],
            "translation_requested": translation_requested,
            "translation_eligible": translation_eligible,
            "runtime_ready": not missing_capabilities,
            "missing_capabilities": missing_capabilities,
            # Static translation and Kbuild are useful even when no runtime
            # fixture exists.  Missing runtime capabilities are classified at
            # finalization instead of preventing generation.
            "run_pipeline": translation_requested and translation_eligible,
        }
        if readiness_failure:
            plan["readiness_failure"] = readiness_failure
        if missing_capabilities:
            plan["runtime_failure"] = {
                "stage": "profile",
                "message": "required runtime profile evidence is unavailable",
                "details": {"missing_capabilities": missing_capabilities},
            }
        return {"pipeline_plan": plan, "events": _event(state, "build_pipeline_plan")}

    def _pipeline_result(state: WorkflowState) -> dict[str, Any]:
        if pipeline_fn is not None:
            return dict(pipeline_fn(state["normalized"], state["analysis"]))
        return run_pipeline_backend(
            state["normalized"], state["analysis"], repo_root=root)

    def generation_pipeline_node(state: WorkflowState) -> dict[str, Any]:
        result = _pipeline_result(state)
        return {"pipeline_result": result, "events": _event(state, "run_project_pipeline")}

    def experiment_pipeline_node(state: WorkflowState) -> dict[str, Any]:
        result = _pipeline_result(state)
        return {"pipeline_result": result, "events": _event(state, "run_project_pipeline")}

    def finalize_node(state: WorkflowState) -> dict[str, Any]:
        plan = state["pipeline_plan"]
        translation_eligible = bool(plan.get("translation_eligible", False))
        if not plan.get("translation_requested", False):
            return {
                "status": "analysis_complete",
                "translation_status": ("eligible" if translation_eligible
                                        else "blocked"),
                "translation_eligible": translation_eligible,
                "events": _event(state, "finalize"),
            }
        if not translation_eligible:
            return {
                "status": "blocked",
                "translation_status": "blocked",
                "translation_eligible": False,
                "failure": plan.get("readiness_failure", {
                    "stage": "readiness",
                    "message": "translation readiness gate is not satisfied",
                    "details": {},
                }),
                "events": _event(state, "finalize"),
            }
        pipeline_result = state.get("pipeline_result")
        failed = (isinstance(pipeline_result, Mapping)
                  and (pipeline_result.get("accepted") is False
                       or pipeline_result.get("status") in {"failed", "rejected"}))
        analysis = state.get("analysis", {})
        contract_report = (analysis.get("subsystem_contract_verification")
                           if isinstance(analysis, Mapping) else None)
        contract_rows = (contract_report.get("contracts", [])
                         if isinstance(contract_report, Mapping) else [])
        has_contracts = isinstance(contract_rows, list) and bool(contract_rows)
        contract_status = (contract_report.get("status")
                           if isinstance(contract_report, Mapping) else None)
        contract_failure = {
            "stage": "subsystem_contract",
            "message": "subsystem contract verification is not accepted",
            "details": {
                "status": contract_status,
                "report": contract_report,
            },
        }
        if plan.get("missing_capabilities"):
            if failed:
                return {
                    "status": "failed",
                    "translation_status": "failed",
                    "translation_eligible": True,
                    "failure": pipeline_result.get("failure", {
                        "stage": "pipeline",
                        "message": "static translation pipeline failed",
                        "details": {},
                    }),
                    "events": _event(state, "finalize"),
                }
            if has_contracts and contract_status == "fail":
                return {
                    "status": "failed",
                    "translation_status": "failed",
                    "translation_eligible": True,
                    "failure": contract_failure,
                    "events": _event(state, "finalize"),
                }
            if has_contracts and contract_status != "pass":
                return {
                    "status": "inconclusive",
                    "translation_status": "inconclusive",
                    "translation_eligible": True,
                    "failure": contract_failure,
                    "events": _event(state, "finalize"),
                }
            return {
                "status": "inconclusive",
                "translation_status": "inconclusive",
                "translation_eligible": True,
                "failure": plan.get("runtime_failure", {
                    "stage": "profile",
                    "message": "runtime profile evidence is unavailable",
                    "details": {},
                }),
                "events": _event(state, "finalize"),
            }
        inconclusive = (isinstance(pipeline_result, Mapping)
                        and pipeline_result.get("status") == "inconclusive")
        if failed:
            return {
                "status": "failed",
                "translation_status": "failed",
                "translation_eligible": True,
                "failure": (pipeline_result.get("failure", {
                    "stage": "pipeline",
                    "message": "static translation pipeline failed",
                    "details": {},
                }) if isinstance(pipeline_result, Mapping) else {
                    "stage": "pipeline",
                    "message": "static translation pipeline failed",
                    "details": {},
                }),
                "events": _event(state, "finalize"),
            }
        if has_contracts and contract_status == "fail":
            return {
                "status": "failed",
                "translation_status": "failed",
                "translation_eligible": True,
                "failure": contract_failure,
                "events": _event(state, "finalize"),
            }
        if has_contracts and contract_status != "pass":
            return {
                "status": "inconclusive",
                "translation_status": "inconclusive",
                "translation_eligible": True,
                "failure": contract_failure,
                "events": _event(state, "finalize"),
            }
        return {"status": "inconclusive" if inconclusive else ("failed" if failed else "completed"),
                "translation_status": "inconclusive" if inconclusive else ("failed" if failed else "accepted"),
                "translation_eligible": True,
                "events": _event(state, "finalize")}

    def route_pipeline(state: WorkflowState) -> str:
        plan = state["pipeline_plan"]
        if not plan["run_pipeline"]:
            return "finalize"
        return "experiment" if plan["mode"] == "experiment" else "generation"

    builder = StateGraph(WorkflowState)
    builder.add_node("normalize_input", normalize_node)
    builder.add_node("discover_driver_files", discover_node)
    builder.add_node("analyze_driver_files", analyze_node)
    builder.add_node("build_pipeline_plan", plan_node)
    builder.add_node("generation_pipeline", generation_pipeline_node)
    builder.add_node("experiment_pipeline", experiment_pipeline_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "normalize_input")
    builder.add_edge("normalize_input", "discover_driver_files")
    builder.add_edge("discover_driver_files", "analyze_driver_files")
    builder.add_edge("analyze_driver_files", "build_pipeline_plan")
    builder.add_conditional_edges(
        "build_pipeline_plan", route_pipeline,
        {"generation": "generation_pipeline",
         "experiment": "experiment_pipeline",
         "finalize": "finalize"},
    )
    builder.add_edge("generation_pipeline", "finalize")
    builder.add_edge("experiment_pipeline", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def run_workflow(input_data: Mapping[str, Any], *, repo_root: str | Path,
                 services: WorkflowServices | None = None,
                 analyzer: Analyzer | None = None,
                 pipeline: Pipeline | None = None,
                 checkpointer: Any = None,
                 config: Mapping[str, Any] | None = None,
                 profile_registry: Any = None) -> dict[str, Any]:
    """Run the compiled graph and return its JSON-compatible final state."""
    graph = build_graph(repo_root=repo_root, services=services,
                        analyzer=analyzer, pipeline=pipeline,
                        checkpointer=checkpointer,
                        profile_registry=profile_registry)
    try:
        result = graph.invoke({"input": dict(input_data)}, config=config)
    except Exception as exc:
        # Keep the CLI and checkpoint consumers on the JSON protocol even
        # when validation, extraction, or an injected service fails inside a
        # LangGraph node.  The original exception remains represented in the
        # result so callers can decide whether to retry or repair.
        return {
            "input": dict(input_data),
            "status": "failed",
            "error": {
                "stage": "workflow",
                "exception": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
            },
            "events": [{"node": "workflow", "status": "failed"}],
        }
    return dict(result)
