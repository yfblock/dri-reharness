"""Semantic inference: RIS modules → FunctionSpec → DeviceSpec (plan M3/M4).

Enriches extracted RIS with backend-independent semantics:
  - role/context from callback-table field binding (bindings_linux), falling
    back to function-name hints
  - signature: C param types → abstract types (LogicalIRQ, DeviceState, UInt...)
  - binds: MMIO base + device state from the address expressions used in the RIS
  - effects: writes_register(REG) and typed non-MMIO transactions, plus a
    role-derived event effect (e.g. interrupt_ack → clears_interrupt(line))
  - requires/ensures: role-derived Hoare-style skeletons

Split into layered modules (func_specs/device_spec/callback_tables/
callback_bindings/facts); every name previously importable from
``extractor.spec_infer`` is re-exported here.
"""
from __future__ import annotations

from .func_specs import (  # noqa: F401
    _MEMBER_BASE, _VAR_BASE, ROLE_SEMANTICS,
    _abstract_param_type, _abstract_return_type, _base_exprs_of_module,
    _bound_mmio_resources, infer_function_spec, infer_function_specs,
    name_role_hints,
)
from .device_spec import (  # noqa: F401
    _DEVICE_CLASS_HINTS, _MODELED_STATE_FIELDS, _modeled_state_fields,
    infer_device_spec,
)
from .callback_tables import (  # noqa: F401
    FIELD_ROLE, OWNER_FIELD_ROLE, _callback_field_role,
    _CALLBACK_TYPE_ROLES, _ROLE_BEARING_CALLBACK_TYPES,
    _is_function_pointer, _function_pointer_signature,
    infer_callback_signatures, _record_type_name, _named_callback_type,
    _record_declaration,
)
from .callback_bindings import (  # noqa: F401
    _target_function_refs, _walk_preorder, _function_pointer_fields,
    _designated_fields, _public_field_transfer_roles, _binding_info,
    infer_callback_bindings, callback_binding_analysis,
    propagate_callback_dispatch_roles,
)
from .facts import (  # noqa: F401
    _INCLUDE_RE, _ERROR_RE, _RESOURCE_CALLS, _HELPER_CALLS,
    _has_call, _target_structs, infer_facts,
    _NOISE_PREFIXES, _is_noise_constant, _vars_in_expr,
)
