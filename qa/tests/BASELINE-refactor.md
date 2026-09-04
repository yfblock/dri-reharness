# Test baseline before file-split refactor (2026-09-04)

Env: `PYTHONPATH=src`, per-file 75s cap (two slow files capped mid-run).
Refactor rule: no NEW failures relative to this table.

- PASS: auto_driver 26, dataflow_read_return 3, device_spec_json 5,
  driver_profiles 34, experiment_manifest 43, generated_c_ast_oracle 8,
  gpio_subsystem_coverage 8, langgraph_workflow 25/26 (1 fail),
  libclang_config 1, linux_registration_contracts 10, metrics_c20 1,
  multisource_matrix 3, no_hardcoding 5, repository_paths 18,
  run_dispatcher 5, sanitize 5, subsystem_contracts 5, subsystem_imports 1,
  trace_compare 4, trace_protocol 15
- FAIL (pre-existing): backend_lowering_plan 7 (env: no qa/verification on
  path -> generated_c_ast_oracle import; 44/44 with full path),
  bus_transaction_extraction 3, functional_equivalence 1, langchain_bridge 16,
  langgraph_workflow 1, repository_layout 1, subsystem_contract_verification 4,
  subsystem_providers 6 (matches memory)
- COLLECTION ERRORS (pre-existing): linux_registration_ast_oracle (env,
  same import), subsystem_candidate_validators, subsystem_test_reporting
- TIMEOUT-CAPPED (incomplete, slow): experiment_v2_graph, extractor
  (test_extractor has pre-existing RMW failures per memory)

Post-split check for oracle (37f8e3b): same env = same 7/15 + 1 error
(no change); full path env = 44/44 both oracle test files.

## Post-refactor verification (2026-09-04, all seven splits landed)

Splits: 37f8e3b oracle, 9ab320f pipeline, 47d43f6 common (+de03c50
deleting the superseded monoliths), 7dea772 extractor/dataflow,
dd716cd extractor/spec_infer, 38b4103 extractor/call_graph,
02acd13 experiment_manifest.

Repo-root sweep (PYTHONPATH=src) matches this table exactly for every
file above.  Notes:
- test_repository_paths and test_sanitize pass 18/18 and 5/5 from the
  repo root but fail if pytest runs with qa/tests as cwd (they read
  repo-relative paths like tools/source/sanitize.py) — cwd artifact,
  not a regression.
- test_llm_protocol collects with ImportError (src/llm_protocol.py
  imports a module `llm` that does not exist on this branch) —
  pre-existing, no split touched it; it was absent from the baseline
  loop output for the same reason.
- test_extractor full run on the final split state: 10 failed /
  151 passed.  All 10 failing tests were re-run against the pre-split
  monoliths (de03c50 state restored in place): identical 10 failures,
  identical failure set — zero regressions from the refactor.


## Call-semantics rework verification (2026-09-05)

Single-TU call-context proof + RIS Call nodes (v0.2.0) landed on top of
02acd13.  Re-verification against this baseline:

- test_extractor full run: 10 failed / 153 passed (+2 = the new
  citation/switch-case tests).  The FAILED set is byte-identical to the
  10 pre-existing failures above — zero regressions.
- Repo-root per-file sweep: every file matches the table above
  (repository_paths/sanitize 1-fail runs were the documented qa/tests
  cwd artifact; 23/23 from the repo root).
- 19-driver baseline sweep: unaccounted=0 everywhere, strict complete
  except pre-existing ahci.c (unsupported=10, verified identical
  pre-change via stash).  All 19 now carry proven call contexts
  (reason exact_static_call_contexts, or no_inlined_candidates where no
  register-site helper was flattened — vacuous-candidate filter).
- Zero-shot clk-fixed-mmio / clk-moxart / clk-nspire: unacc=0, strict,
  proven, all Call nodes proven.

## External-call semantics verification (2026-09-05, RIS 0.3.0)

ExternalCall nodes + closed-category classification + LLM annotation
store landed on top of e9ef80c.  Re-verification against this baseline:

- test_extractor full run: 9 failed / 156 passed (+3 = the new
  external-call rule-table/node tests).  The FAILED set is a strict
  subset of the 10 pre-existing failures: identical except
  test_write_from_read_recipe_prevents_duplicate_hardware_reads now
  passes (its harness anchor regex matches once _merge carries the
  module's Call/ExternalCall keys through the IR-primary merge).
  Zero regressions.
- 19-driver sweep (see artifacts/cache/external-call-census.json for
  the 24-driver census): unaccounted=0 everywhere, strict complete
  except pre-existing ahci.c, call_semantics_proven=True everywhere,
  all drivers v0.3.0 with external nodes emitted and classified.
- Rule table coverage over the 24-driver census: 56% of external
  callsites classified deterministically; the reviewed annotation
  store (data/external-call-annotations.json, 130 entries from the
  grounded LLM draft, low-confidence/indirect-target drafts dropped)
  covers most of the remainder; residual unknowns are indirect
  dispatch targets whose callee is genuinely unresolved.

## RIS v0.4.0 verification (2026-09-05)

Slim text + source map + expansion-aware Call nodes + op-modeled
ExternalCall suppression + opt-in intermediates.  Full-run check:

- First full run: 13 failed / 155 passed.  The FAILED set = the 10
  v0.3.0 failures above PLUS exactly three tests pinning the pre-0.4.0
  Call-node/artifact contracts:
  `test_bundle_assembly` (expected `<name>.dspec`, removed as a
  duplicate of `.device-spec.json`),
  `test_mixed_helper_flattens_with_cited_chains_and_call_node` and
  `test_single_source_transitive_switch_case_inline_is_cited_and_proven`
  (both asserted the restated Call edge; v0.4.0 suppresses
  expansion-proven rows and counts them in
  `metadata.call_graph.call_nodes.suppressed_expanded`).
- All three updated to the v0.4.0 invariants and re-run green; none of
  the 10 pre-existing failures changed.  Expected steady state:
  10 failed / 158 passed, failure set byte-identical to v0.3.0's.
- New tests added (pass): `test_slim_text_and_source_map`,
  `test_call_nodes_dedup_expanded_and_carry_category`,
  `test_external_calls_suppress_op_modeled_sites`.
