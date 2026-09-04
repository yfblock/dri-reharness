"""Shared C-emission helpers for all backends.

Implementation is layered: ``splitting`` (.h/.c pair splitting),
``receipts`` (receipts and semantic digests), ``bind`` (freestanding
BindSpec population), ``idents`` (identifier analysis), ``decls``
(local declarations and MMIO primitive selection), ``transactions``
(typed transaction lowering and runtime preludes), ``anchors``
(receipt-bound compound statements), and ``emit`` (ops_to_c).  This
facade keeps the historical ``backends.common`` import surface.
"""
from __future__ import annotations

from .splitting import (  # noqa: F401
    generate_pair,
    split_header_source,
)
from .receipts import (  # noqa: F401
    lowering_receipt,
    lowering_recipes,
    ris_op_digest,
    transaction_digest,
    transaction_kind,
)
from .bind import _C_KEYWORDS, make_freestanding_bind  # noqa: F401
from .idents import (  # noqa: F401
    _VAR_ID,
    called_names_in_text,
    is_simple_id,
    replace_expr_var,
    value_var_names,
    vars_in_expr,
)
from .decls import (  # noqa: F401
    local_decls,
    mmio_primitive,
    transaction_local_decls,
    width_suffix,
)
from .transactions import (  # noqa: F401
    detect_transaction_transports,
    i2c_helper,
    transaction_anchor,
    transaction_expr,
    transaction_lowering,
    transaction_receipt,
    transaction_runtime_prelude,
    transaction_runtime_prelude_filtered,
    transaction_scalar_width,
)
from .anchors import begin_operation, operation_anchor  # noqa: F401
from .emit import addr_to_c, ops_to_c  # noqa: F401
