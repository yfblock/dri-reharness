"""Flow-sensitive intra-procedural dataflow + taint tracking.

Walks each function's calls in source order, maintaining an abstract store
(var -> AbsVal). At each MMIO call it resolves the address argument to a
RegAddr via the store + macro table, records branch conditions, and detects
read-modify-write patterns (readl→modify→writel on the same address).

Split into layered modules (ops/expr_eval/assign_scan/funcs/substitution/
rmw/extract); every name previously importable from ``extractor.dataflow``
is re-exported here.
"""
from __future__ import annotations

from .ops import BASE_FIELDS, Op, _CONTROL_KW  # noqa: F401
from .expr_eval import (  # noqa: F401
    _CAST_RE, _MEMBER_RE, _CHAINED_MEMBER_RE, _IDENT_RE, _HEX_RE, _DEC_RE,
    _BIT_RE, _strip_parens, _strip_casts, _split_top, eval_expr,
    _combine_add, _combine_sub, resolve_addr, _split_ternary_expr,
    _address_base_offset,
)
from .assign_scan import (  # noqa: F401
    _plain_pointer_assignments, _pointer_assignment_store,
    _GENERAL_ASSIGN_RE, _general_assignments, _STATE_LHS_RE,
    _state_assignment_entries, _local_value_entries, _buffer_write_entries,
    _abs_expr, _resolved_argument, _general_assignment_store,
)
from .funcs import (  # noqa: F401
    FuncExtraction, _path_return_expr, _pure_return_functions, _split_text_args,
)
from .substitution import (  # noqa: F401
    _expand_pure_calls, _expand_numeric_macros, _expand_addr_numeric_macros,
    _ADDRESS_OF_MEMBER_RE, _normalise_address_of_member, _substitute_text,
    _substitute_addr, _instantiate_op,
)
from .rmw import (  # noqa: F401
    _LHS_RE, _LHS_CONT_RE, _DECL_LHS_RE, _bind_lhs,
    _norm_key, _MUTATION_OP, _apply_mutation, _switch_rmw_transform,
    _rmw_transform, _read_initial_transform, _has_classified_read_provenance,
    _proven_return_read_var,
)
from .extract import extract_function, _parse_delay_ns  # noqa: F401

# Names the original module exposed via its own taint imports.
from ..taint import (  # noqa: F401
    BasePtr, Offset, ReadTaint, Const, SymExpr, Top, AbsVal,
    addr_fixed, addr_offset, addr_indirect, addr_equal, addr_base_of,
    val_to_value_str,
)
