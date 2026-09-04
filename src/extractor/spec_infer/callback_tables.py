"""Linux callback-table role contracts and callback ABI signature helpers."""
from __future__ import annotations
import clang.cindex as _cx

from ..spec import PUBLIC_CALLBACK_TYPES


# ═══════════════════════════════════════════════════════════════════
# Linux callback-table recognition (consolidated from bindings_linux.py)
# ═══════════════════════════════════════════════════════════════════
FIELD_ROLE: dict[str, tuple[str, str]] = {
    # irq_chip
    "irq_ack": ("interrupt_ack", "irq"),
    "irq_mask": ("interrupt_mask", "irq"),
    "irq_unmask": ("interrupt_unmask", "irq"),
    "irq_mask_ack": ("interrupt_mask", "irq"),
    "irq_eoi": ("interrupt_ack", "irq"),
    "irq_enable": ("interrupt_unmask", "irq"),
    "irq_disable": ("interrupt_mask", "irq"),
    "irq_set_type": ("set_irq_type", "irq"),
    "irq_set_affinity": ("set_irq_type", "irq"),
    "irq_set_wake": ("set_irq_type", "irq"),
    "handle_irq": ("interrupt_handler", "irq"),
    "irq_handler": ("interrupt_handler", "irq"),
    "parent_handler": ("interrupt_handler", "irq"),
    "init_hw": ("init", "boot"),
    # platform_driver / pci_driver / etc.
    "probe": ("probe", "boot"),
    "remove": ("remove", "thread"),
    "shutdown": ("remove", "thread"),
    "suspend": ("suspend", "sleepable"),
    "resume": ("resume", "sleepable"),
    "freeze": ("suspend", "sleepable"),
    "thaw": ("resume", "sleepable"),
    "poweroff": ("suspend", "sleepable"),
    "restore": ("resume", "sleepable"),
    # virtio_config_ops
    "get": ("read_config", "thread"),
    "get_multiple": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_multiple": ("write_config", "thread"),
    "generation": ("get_status", "thread"),
    "get_status": ("get_status", "thread"),
    "set_status": ("set_status", "thread"),
    "reset": ("reset", "thread"),
    "find_vqs": ("setup_queue", "thread"),
    "del_vqs": ("remove", "thread"),
    "get_shm_region": ("read_config", "thread"),
    "notify_vq": ("notify", "thread"),
    "notify": ("notify", "thread"),
    "callback": ("interrupt_handler", "irq"),
    "event": ("write_config", "thread"),
    # sdhci_ops logical register accessors
    "read_l": ("read_config", "thread"),
    "read_w": ("read_config", "thread"),
    "read_b": ("read_config", "thread"),
    "write_l": ("write_config", "thread"),
    "write_w": ("write_config", "thread"),
    "write_b": ("write_config", "thread"),
    # clk_ops
    "prepare": ("init", "thread"),
    "unprepare": ("remove", "thread"),
    "enable": ("init", "thread"),
    "disable": ("remove", "thread"),
    "is_enabled": ("get_status", "thread"),
    "recalc_rate": ("read_config", "thread"),
    "determine_rate": ("read_config", "thread"),
    "round_rate": ("read_config", "thread"),
    "set_rate": ("write_config", "thread"),
    # usb_ep_ops
    "alloc_request": ("init", "thread"),
    "free_request": ("remove", "thread"),
    "queue": ("setup_queue", "thread"),
    "dequeue": ("remove", "thread"),
    "set_halt": ("write_config", "thread"),
    "set_wedge": ("write_config", "thread"),
    "fifo_status": ("get_status", "thread"),
    "fifo_flush": ("write_config", "thread"),
    # usb_gadget_ops
    "get_frame": ("get_status", "thread"),
    "wakeup": ("resume", "thread"),
    "func_wakeup": ("resume", "thread"),
    "set_remote_wakeup": ("write_config", "thread"),
    "set_selfpowered": ("write_config", "thread"),
    "vbus_session": ("write_config", "thread"),
    "vbus_draw": ("write_config", "thread"),
    "pullup": ("write_config", "thread"),
    "udc_start": ("init", "thread"),
    "udc_stop": ("remove", "thread"),
    "udc_set_speed": ("write_config", "thread"),
    "match_ep": ("read_config", "thread"),
    # hc_driver
    "irq": ("interrupt_handler", "irq"),
    "start": ("init", "thread"),
    "stop": ("remove", "thread"),
    "urb_enqueue": ("setup_queue", "thread"),
    "urb_dequeue": ("remove", "thread"),
    "endpoint_disable": ("remove", "thread"),
    "endpoint_reset": ("reset", "thread"),
    "get_frame_number": ("get_status", "thread"),
    "hub_status_data": ("get_status", "thread"),
    "hub_control": ("write_config", "thread"),
    "clear_tt_buffer_complete": ("remove", "thread"),
    "bus_suspend": ("suspend", "sleepable"),
    "bus_resume": ("resume", "sleepable"),
    "map_urb_for_dma": ("setup_queue", "thread"),
    "unmap_urb_for_dma": ("remove", "thread"),
    "free_dev": ("remove", "thread"),
    "reset_device": ("reset", "thread"),
    # gpio_chip (beyond irq)
    "get_direction": ("read_config", "thread"),
    "direction_input": ("write_config", "thread"),
    "direction_output": ("write_config", "thread"),
    "get": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_config": ("write_config", "thread"),
    "request": ("init", "thread"),
    "free": ("remove", "thread"),
    # file_operations
    "open": ("init", "thread"),
    "read": ("read_config", "thread"),
    "write": ("write_config", "thread"),
    # generic
    "init": ("init", "boot"),
    "exit": ("remove", "thread"),
}

# Some public callback ABIs reuse field names whose meaning is only
# unambiguous in the owning table.  Keep these contracts owner-qualified so
# new drivers can inherit the semantics without basename, compatible-string,
# or private-prefix rules.  Unknown/private owners remain evidence-only.
OWNER_FIELD_ROLE: dict[str, dict[str, tuple[str, str]]] = {
    "clk_ops": {
        "is_prepared": ("get_status", "thread"),
    },
    "sdhci_ops": {
        "voltage_switch": ("write_config", "thread"),
        "set_clock": ("write_config", "thread"),
        "set_bus_width": ("write_config", "thread"),
        "set_uhs_signaling": ("write_config", "thread"),
        "set_power": ("write_config", "thread"),
        "hw_reset": ("reset", "thread"),
    },
    "mmc_host_ops": {
        "start_signal_voltage_switch": ("write_config", "thread"),
        "execute_tuning": ("write_config", "thread"),
        "prepare_hs400_tuning": ("write_config", "thread"),
        "execute_hs400_tuning": ("write_config", "thread"),
        "prepare_sd_hs_tuning": ("write_config", "thread"),
        "execute_sd_hs_tuning": ("write_config", "thread"),
        "hs400_enhanced_strobe": ("write_config", "thread"),
        "request": ("setup_queue", "thread"),
        "request_atomic": ("setup_queue", "atomic"),
    },
    "spi_controller": {
        "setup": ("init", "thread"),
        "cleanup": ("remove", "thread"),
        "prepare_transfer_hardware": ("init", "thread"),
        "unprepare_transfer_hardware": ("remove", "thread"),
        "transfer_one": ("setup_queue", "thread"),
        "transfer_one_message": ("setup_queue", "thread"),
        "handle_err": ("reset", "thread"),
        "set_cs": ("write_config", "thread"),
        "target_abort": ("reset", "thread"),
    },
    "spi_controller_mem_ops": {
        "adjust_op_size": ("write_config", "thread"),
        "supports_op": ("read_config", "thread"),
        "exec_op": ("write_config", "thread"),
    },
}


def _callback_field_role(owner: str, field: str) -> tuple[str, str]:
    owner_roles = OWNER_FIELD_ROLE.get(owner)
    if owner_roles and field in owner_roles:
        return owner_roles[field]
    return FIELD_ROLE.get(field, ("unknown", "thread"))

_CALLBACK_TYPE_ROLES: dict[str, tuple[str, str]] = {
    "irq_handler_t": ("interrupt_handler", "irq"),
}

# Public callback ABI types may attach the existing field-level semantic role.
# Every other struct still receives owner/field binding evidence, but its role
# remains unknown so a source-private field named ``reset`` or ``write`` cannot
# accidentally become executable backend intent.
_ROLE_BEARING_CALLBACK_TYPES = PUBLIC_CALLBACK_TYPES


def _is_function_pointer(ctype) -> bool:
    try:
        canonical = ctype.get_canonical()
        if canonical.kind != _cx.TypeKind.POINTER:
            return False
        pointee = canonical.get_pointee().get_canonical()
        return pointee.kind in {
            _cx.TypeKind.FUNCTIONPROTO, _cx.TypeKind.FUNCTIONNOPROTO}
    except Exception:
        return False


def _function_pointer_signature(ctype) -> dict | None:
    """Return the canonical C ABI represented by a function-pointer type."""
    try:
        canonical = ctype.get_canonical()
        if canonical.kind != _cx.TypeKind.POINTER:
            return None
        function_type = canonical.get_pointee().get_canonical()
        if function_type.kind not in {
                _cx.TypeKind.FUNCTIONPROTO, _cx.TypeKind.FUNCTIONNOPROTO}:
            return None
        params = []
        arguments = (function_type.argument_types()
                     if callable(function_type.argument_types)
                     else function_type.argument_types)
        for argument in arguments:
            param_type = argument.get_canonical()
            params.append({"type": param_type.spelling})
        return {
            "type": canonical.spelling,
            "return_type": function_type.get_result().get_canonical().spelling,
            "params": params,
            "variadic": bool(function_type.is_function_variadic()),
        }
    except Exception:
        return None


def infer_callback_signatures(
        tu, fields: set[str] | None = None,
        bindings: dict[str, dict] | None = None) -> dict[str, dict]:
    """Collect public framework callback field ABIs from the parsed AST."""
    requested = set(fields) if fields is not None else None
    signatures: dict[str, dict] = {}
    if bindings is not None:
        for primary in bindings.values():
            for info in [primary, *primary.get("alternates", [])]:
                table = info.get("table")
                field = info.get("field")
                signature = info.get("signature")
                key = f"{table}.{field}"
                if (isinstance(table, str) and isinstance(field, str)
                        and isinstance(signature, dict)
                        and (requested is None or key in requested)):
                    signatures[key] = signature
        missing = (requested - set(signatures)) if requested is not None else set()
        if not missing:
            return signatures
        requested = missing
    for cursor in tu.cursor.walk_preorder():
        if cursor.kind != _cx.CursorKind.FIELD_DECL:
            continue
        owner = _record_type_name(cursor)
        if owner not in PUBLIC_CALLBACK_TYPES:
            continue
        key = f"{owner}.{cursor.spelling}"
        if requested is not None and key not in requested:
            continue
        signature = _function_pointer_signature(cursor.type)
        if signature is not None:
            signatures[key] = signature
    return signatures


def _record_type_name(field_cursor) -> str | None:
    parent = field_cursor.semantic_parent or field_cursor.lexical_parent
    if parent is not None and parent.kind in {
            _cx.CursorKind.STRUCT_DECL, _cx.CursorKind.UNION_DECL}:
        return parent.spelling or None
    return None


def _named_callback_type(ctype) -> str | None:
    """Return an AST-declared callback typedef, never a guessed C signature."""
    spelling = (ctype.spelling or "").strip()
    if ctype.kind == _cx.TypeKind.TYPEDEF and spelling:
        return spelling
    declaration = ctype.get_declaration()
    if declaration is not None and declaration.kind == _cx.CursorKind.TYPEDEF_DECL:
        return declaration.spelling or None
    return None


def _record_declaration(ctype):
    try:
        current = ctype.get_canonical()
        while current.kind in {
                _cx.TypeKind.CONSTANTARRAY, _cx.TypeKind.INCOMPLETEARRAY,
                _cx.TypeKind.VARIABLEARRAY, _cx.TypeKind.DEPENDENTSIZEDARRAY}:
            current = current.element_type.get_canonical()
        if current.kind == _cx.TypeKind.POINTER:
            current = current.get_pointee().get_canonical()
        declaration = current.get_declaration()
        if declaration is not None and declaration.kind in {
                _cx.CursorKind.STRUCT_DECL, _cx.CursorKind.UNION_DECL}:
            return declaration
    except Exception:
        pass
    return None
