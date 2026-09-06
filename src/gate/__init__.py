"""Verification-gate runtime: oracles, lowering plan, and bounded repair.

These modules are production pipeline code (imported by ``src`` and by
the experiment runners), not QA tests; they moved here from
``qa/verification`` so that ``src`` no longer reaches into the qa tree
for runtime dependencies.

Modules:
  - :mod:`gate.backend_lowering_oracle` — generation contract from formal RIS
  - :mod:`gate.backend_lowering_plan` — receipt authorization / lowering plan
  - :mod:`gate.generated_c_ast_oracle` — libclang primitive-shape check
  - :mod:`gate.subsystem_callback_oracle` — subsystem callback verification
  - :mod:`gate.ris_trace_oracle` — RIS-derived expected trace
  - :mod:`gate.callback_binding_oracle` — callback-table binding check
  - :mod:`gate.repair_lowering` / :mod:`gate.repair_artifact` /
    :mod:`gate.repair_dataflow` — the three bounded repair loops
"""
