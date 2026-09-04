"""Linux registration AST oracle, split into layered modules.

Import surface is unchanged: every name previously defined in the single
``linux_registration_ast_oracle.py`` module is re-exported here.
"""
from __future__ import annotations

from .support import (  # noqa: F401
    CONTROL_KINDS,
    WRAPPER_KINDS,
    _assignment_operator,
    _canonical_type,
    _children,
    _decl_scope,
    _function_refs,
    _in_source,
    _location,
    _object_path,
    _path_key,
    _path_parent_key,
    _path_table,
    _record_name,
    _resolve_local_alias,
    _resolve_local_aliases,
    _signature,
    _signature_matches,
    _stable_chain,
    _table_for_type,
    _unwrap,
    _variable_paths,
    registration_route_fingerprint,
)
from .context import (  # noqa: F401
    _call_policy,
    _compile_context,
    _device_routes,
    linux_kbuild_compile_context,
)
from .ast_collect import _collect_ast  # noqa: F401
from .routes import _registered_routes  # noqa: F401
from .runtime_contract import _runtime_identity_contract  # noqa: F401
from .verify import (  # noqa: F401
    ORACLE,
    SCHEMA,
    _write_report,
    main,
    verify_linux_registration_ast,
)
