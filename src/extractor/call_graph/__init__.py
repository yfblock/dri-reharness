"""Call graph + wrapper-function inlining.

Pass 1: extract each target function's own (direct) MMIO ops.
Pass 2: build the call graph; for each function, inline callees that are
themselves target functions with MMIO ops (depth-limited, recursion-safe).

Split into layered modules (ids/call_rows/evidence/inlining/graph); every
name previously importable from ``extractor.call_graph`` is re-exported
here.
"""
from __future__ import annotations

from .ids import (  # noqa: F401
    _func_id, _callee_id, _resolved_callee_id, _cursor_parents,
    _return_binding,
)
from .call_rows import (  # noqa: F401
    _formal_calls, _op_site, _op_occurrence, _with_ops,
    _eligible_call_edges, _type_is_scalar, _types_compatible,
    _LOOP_INIT_RE, _LOOP_GUARD_RE, _LOOP_STEP_RE, _literal_int,
    _loop_executes_exactly_once, _call_row_is_proven,
)
from .evidence import (  # noqa: F401
    _definition_site, _register_ops, _op_fingerprint, _evidence_sites,
    _direct_evidence_frontier, _coverage_aware_inlined_names,
)
from .inlining import (  # noqa: F401
    _prove_inlined_call_context, _selective_frontier_call_closure,
)
from .graph import (  # noqa: F401
    build_inline_cache, call_graph, _adaptive_inline_depth,
    extract_with_inlining, extract_multi_with_inlining,
)
