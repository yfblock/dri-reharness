"""LangGraph orchestration for reharness.

The v1 general workflow graph (normalize/discover/analyze/plan nodes) was
removed; the experiment v2 closed-loop graph is the only workflow:

  build_driver -> ris_extract -> llm_gen_tests -> baseline_qemu ->
  llm_synthesize -> candidate_compile -> candidate_qemu -> diff_compare,
  with a bounded repair loop back to llm_synthesize.
"""
from .experiment_v2_graph import build_experiment_v2

__all__ = ["build_experiment_v2"]
