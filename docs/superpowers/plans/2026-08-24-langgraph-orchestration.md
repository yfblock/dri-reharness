# LangGraph Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an input-driven LangGraph graph that analyzes complete driver descriptors and delegates accepted execution to the existing reharness Pipeline.

**Architecture:** A typed LangGraph state runs input normalization, source discovery, deterministic extractor-backed analysis, mode routing, and final status propagation. Experiment mode reuses cached evidence with `ExperimentRunner`; generation mode delegates to `driver_pipeline`.

**Tech Stack:** Python 3.12, LangGraph 1.x, existing extractor/ExperimentRunner/adapters, pytest.

---

### Task 1: Define the workflow state and source tools

**Files:**
- Create: `src/langgraph_workflow/state.py`
- Create: `src/langgraph_workflow/tools.py`
- Test: `qa/tests/test_langgraph_workflow.py`

- [x] Validate source and experiment-manifest paths, while allowing explicit external artifact output paths.
- [x] Resolve all entries from a multi-source descriptor and calculate content digests including the descriptor itself.
- [x] Run the existing extractor and bundle builder without placing live extractor objects in graph state.

### Task 2: Build the LangGraph orchestration

**Files:**
- Create: `src/langgraph_workflow/graph.py`
- Create: `src/langgraph_workflow/__init__.py`
- Create: `src/langgraph_workflow/__main__.py`
- Test: `qa/tests/test_langgraph_workflow.py`

- [x] Add normalize, discover, analyze, plan, Pipeline, and finalize nodes.
- [x] Route analysis-only requests directly to finalize.
- [x] Propagate rejected Pipeline results as a failed graph status.
- [x] Expose injectable analyzer/Pipeline callables and LangGraph checkpointers.

### Task 3: Integrate the public dispatcher and dependency declaration

**Files:**
- Modify: `run.sh`
- Modify: `README.md`
- Create: `requirements-langgraph.txt`
- Test: `qa/tests/test_run_dispatcher.py`

- [x] Add `run.sh langgraph` and document analysis and experiment invocations.
- [x] Pin the supported LangGraph major version range.

### Task 4: Verify compatibility

**Files:**
- Test: `qa/tests/test_langgraph_workflow.py`
- Test: `qa/tests/test_experiment_runner.py`
- Test: `qa/tests/test_runtime_adapters.py`

- [x] Verify source discovery, checkpointing, analysis ordering, rejection propagation, and cached evidence reuse.
- [x] Run a real `edu.c` analysis-only smoke through `run.sh` and inspect generated evidence artifacts.
- [x] Run existing ExperimentRunner, runtime adapter, and dispatcher regression tests.
