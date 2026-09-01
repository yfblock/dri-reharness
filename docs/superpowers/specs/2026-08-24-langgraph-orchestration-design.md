# LangGraph Orchestration Design

## Goal

Add an input-driven LangGraph orchestration layer around the existing reharness
Python pipeline. The graph must analyze every source listed by a single-source
or multi-source driver descriptor before delegating execution to the existing
extractor and experiment pipeline.

## Boundaries

Source files and manifests must resolve inside the repository. Explicit output
directories may be outside the repository so temporary evidence can be stored
under `/tmp`. A source JSON descriptor is either a reharness multi-source
manifest with `sources[]` or a descriptor containing `source.path`; experiment
manifests are passed separately as `experiment_manifest`.

The graph does not make semantic acceptance decisions. Existing generation
contracts, safety policies, compile results, runtime results, trace comparison,
and retry limits remain authoritative.

## Graph

```text
START -> normalize_input -> discover_driver_files -> analyze_driver_files
       -> build_pipeline_plan -> run_project_pipeline -> finalize -> END
                                      | analysis mode -> finalize
```

`analyze_driver_files` runs the existing extractor over the complete source
descriptor, writes the normal bundle artifacts, and returns source/evidence
digests. `run_project_pipeline` reuses cached evidence for experiment mode and
delegates the closed loop to `ExperimentRunner`; generation mode delegates to
the existing `driver_pipeline`.

## State and Extension Points

`WorkflowState` contains only JSON-compatible input, inventory, analysis,
artifact paths, stage events, and results. `WorkflowServices.analyzer` and
`WorkflowServices.pipeline` are injectable callables, so projects can replace
the analysis Agent or Pipeline adapter without changing graph topology.
LangGraph checkpointers are passed through `build_graph` or `run_workflow`.

## Failure Policy

Input and source-boundary errors fail before analysis. Pipeline results with
`accepted: false`, `failed`, or `rejected` status propagate to the graph's
final `failed` status. The existing ExperimentRunner remains responsible for
compile/runtime/trace retry policy and structured repair feedback.

## Artifacts and CLI

The public entry point is `./run.sh langgraph <source>`. Analysis artifacts
default to `artifacts/langgraph/<driver>/`; `--output-dir` can redirect them.
The optional dependency is declared in `requirements-langgraph.txt`.
