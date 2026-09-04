# RIS v0.4.0 — slim text, source map, expanded-call dedup

Landed 2026-09-05 on `langgraph`. Schema version `0.3.0 → 0.4.0`.

## What changed

### 1. No inline locations in the .ris text (side table instead)

`formal_display(formal, include_locations=False)` (new default) and
`op_display(op, include_locations=False)` drop every inline
`file:line` annotation from the rendered language. Op anchors stay
(`@op_42 [Exact] digest=...`) because backend receipt lowering keys on
them. gpio-dwapb: 82,266 → 48,045 rendered chars (−42%).

Locations are now first-class data in a **source map** built once per
extraction:

- `src/extractor/source_map.py` — `build_source_map(formal)` indexes
  every location-bearing node: op ids (`op_42`), `call:<module>:<i>`,
  `ext:<module>:<i>`.
- `formal["source_map"] = {"schema": 1, "anchors": {...}}` —
  each anchor maps to `{source, source_path, line, column}`.
- `lookup_source(map, anchors)` resolves anchors to `file:line` for
  on-demand LLM pass-through (unknown keys are silently absent, never an
  error).

`save_formal_text(..., include_locations=True)` restores the old
annotated render for debugging; `formal_display` keeps the kwarg too.

### 2. Call nodes: expansion-aware (the `Call dwapb_read` class fix)

v0.2.0 emitted a Call node for **every** inlined-helper call edge as an
auditability record. But the callee's ops are already flattened into the
same module right below it — the Call line restated the expansion as an
opaque call.

v0.4.0 rule (`_attach_call_nodes` in `formalize.py`): a call row is
suppressed when the module's op evidence proves the expansion — i.e.
some op carries an `inlined_at` hop `{function: caller, line: L,
callee: name}` naming the row's exact callsite. Generic match on
(function, line, callee); no driver-specific knowledge.

A Call node survives only when the callee produced **no** ops in the
caller (allocators, printers, pure accessors — `devm_kzalloc`,
`irqd_to_hwirq`, ...). Surviving nodes:

- are classified with the same closed category enum as ExternalCall
  (`external_semantics.classify`), rendered `Call devm_kzalloc(...)
  [alloc][direct_function_declaration] [proven]`;
- bump to `schema: 2` and carry `category` / `category_source`;
- count in `metadata.call_graph.call_nodes = {emitted_nodes,
  suppressed_expanded}` and the `.ris` footer `call_nodes {}` block.

### 3. ExternalCall: op-modeled wrapper suppression

`ExternalCall read_reg(reg) ... [unknown][unresolved_indirect]` noise
class: the wrapper call (`gpio_generic_read_reg(chip, X)`) was already
rewritten by the dataflow layer into the module's R/W op
(`origin=subsystem_summary`, `ast_kind=CALL_EXPR`, evidence anchored at
the wrapper callsite). Emitting both accounted the site twice.

v0.4.0 rule (`_attach_external_call_nodes`): an
`unresolved_indirect` row is suppressed when an op in the module models
its terminal call — key `(owner function, line, callee)` plus the full
`inlined_at` chain (row hops run caller→callee; op evidence runs
callee→caller, so the row chain compares **reversed**). gpio-dwapb:
unresolved externals 32 → 5; the 5 remaining are genuinely unaccounted
indirect dispatch (ops-table `get`, devm action callbacks) and stay
visible fail-closed.

Counted as `metadata.external_calls.suppressed_modeled`.

### 4. Intermediates are opt-in

`artifacts/intermediates/<stem>/` (01-ir.ll … 06-stats.json) is pure
review material with no machine readers, and was written on **every**
extraction. Now gated on `REHARNESS_DUMP_INTERMEDIATES=1`;
`./run.sh intermediates <driver.c>` sets it. Without it the compiled
`.ll` goes to a scratch temp file. Dropped duplicate writes:
`<name>.dspec` (identical content to `<name>.device-spec.json`) in
`driver_pipeline.py`, `synthesis.py`, `backends/pipeline/run.py`, and
the pre-generation `verify/analysis.json` overwrite in
`driver_pipeline.py`.

## Validation

- New tests: `test_slim_text_and_source_map`,
  `test_call_nodes_dedup_expanded_and_carry_category`,
  `test_external_calls_suppress_op_modeled_sites`
  (`qa/tests/test_extractor.py`).
- 19-driver sweep: `unaccounted=0` everywhere, `strict_complete` all
  except pre-existing ahci.c; dedup active corpus-wide.
- Full-suite identity vs the 9F/156P refactor baseline: see
  `qa/tests/BASELINE-refactor.md` addendum.
