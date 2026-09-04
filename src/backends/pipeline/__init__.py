"""Multi-backend generation + verification pipeline.

Implementation is layered: ``paths`` (small shared helpers),
``compile_repair`` (generic compiler-diagnostic feedback loop),
``receipt_repair`` (receipt-completion pass), and ``run``
(run_backend_pipeline orchestration).  This facade keeps the historical
``backends.pipeline`` import path re-exporting the same names.
"""
from __future__ import annotations

from .paths import (  # noqa: F401
    _ORACLE_FILES,
    _is_subsequence,
    _pipeline_success,
    _repository_root,
    _transaction_source_paths,
)
from .compile_repair import (  # noqa: F401
    _ERR_LINE,
    _MODPOST_UNDEF,
    _PART_MARKER,
    _REPAIR_ECHO_LIMIT,
    _REPAIR_FENCE,
    _REPAIR_PROMPT,
    _UNDEF_REF,
    _compile_probe,
    _part_bounds,
    _receipt_count,
    _repair_compile,
)
from .receipt_repair import (  # noqa: F401
    _KIND_ALIAS,
    _RECEIPT_REPAIR_PROMPT,
    _VALID_RCPT,
    _dedup_receipts,
    _receipt_line_ok,
    _repair_receipts,
    _walk_register_ops,
)
from .run import run_backend_pipeline  # noqa: F401
