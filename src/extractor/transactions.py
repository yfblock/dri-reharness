"""Typed non-MMIO hardware transaction contracts.

The contracts in this module deliberately keep a transport handle separate
from a register/command selector.  A regmap or I2C operation is not an MMIO
address and must never be represented as ``map + reg``.

Exact public Linux APIs are modeled by name.  MFD helpers are accepted only
when libclang proves that their declaration comes from ``include/linux/mfd``
and their signature follows a narrow, generic register-helper convention.
This keeps the rule driver-independent and fail-closed.
"""
from __future__ import annotations

import re


_REGMAP = {
    "regmap_read": ("read", "scalar"),
    "regmap_write": ("write", "scalar"),
    "regmap_update_bits": ("update", "scalar"),
    "regmap_update_bits_check": ("update_check", "scalar"),
    "regmap_set_bits": ("set_bits", "scalar"),
    "regmap_clear_bits": ("clear_bits", "scalar"),
    "regmap_bulk_read": ("read", "buffer"),
    "regmap_bulk_write": ("write", "buffer"),
    "regmap_raw_read": ("read", "buffer_bytes"),
    "regmap_raw_write": ("write", "buffer_bytes"),
}

_I2C_SCALAR = {
    "i2c_smbus_read_byte": ("read", 1, False),
    "i2c_smbus_write_byte": ("write", 1, False),
    "i2c_smbus_read_byte_data": ("read", 1, True),
    "i2c_smbus_write_byte_data": ("write", 1, True),
    "i2c_smbus_read_word_data": ("read", 2, True),
    "i2c_smbus_write_word_data": ("write", 2, True),
    "i2c_smbus_read_word_swapped": ("read", 2, True),
    "i2c_smbus_write_word_swapped": ("write", 2, True),
}

_I2C_BUFFER = {
    "i2c_smbus_read_block_data": ("read", "smbus_block"),
    "i2c_smbus_write_block_data": ("write", "smbus_block"),
    "i2c_smbus_read_i2c_block_data": ("read", "i2c_block"),
    "i2c_smbus_write_i2c_block_data": ("write", "i2c_block"),
    "i2c_master_recv": ("read", "raw"),
    "i2c_master_send": ("write", "raw"),
}

_MESSAGE_TRANSFERS = {
    "i2c_transfer": ("i2c", "i2c_transfer"),
    "i2c_transfer_buffer_flags": ("i2c", "i2c_transfer_buffer_flags"),
    "spi_sync": ("spi", "spi_sync"),
    "spi_sync_locked": ("spi", "spi_sync_locked"),
}


def _strip_output(text: str) -> str:
    return (text or "").strip().lstrip("&*").strip()


def _width_from_type(type_name: str) -> int:
    compact = re.sub(r"\b(?:const|volatile|signed|unsigned)\b", "", type_name)
    compact = re.sub(r"\s+", " ", compact).strip()
    if re.search(r"\b(?:u8|s8|char|uint8_t|int8_t)\b", compact):
        return 1
    if re.search(r"\b(?:u16|s16|short|uint16_t|int16_t)\b", compact):
        return 2
    if re.search(r"\b(?:u32|s32|uint32_t|int32_t)\b", compact):
        return 4
    if re.search(r"\b(?:u64|s64|long long|uint64_t|int64_t)\b", compact):
        return 8
    return 0


def _base(kind: str, transport: str, target: str, selector: str | None,
          width: int = 0) -> dict:
    return {
        "kind": kind,
        "transport": transport,
        "target": target.strip(),
        "selector": selector.strip() if selector is not None else None,
        "element_width": width,
        "payload_kind": "scalar",
        "count": "1",
        "buffer": None,
        "value": None,
        "result": None,
        "update_mask": None,
        "update_value": None,
        "update_semantics": None,
    }


def _regmap_contract(name: str, args: list[str]) -> dict | None:
    spec = _REGMAP.get(name)
    if spec is None:
        return None
    kind, payload = spec
    minimum = {"read": 3, "write": 3, "update": 4, "update_check": 5,
               "set_bits": 3, "clear_bits": 3}[kind]
    if len(args) < minimum:
        return None
    out = _base("update" if kind in {
                    "update", "update_check", "set_bits", "clear_bits"}
                else kind, "regmap", args[0], args[1])
    if payload == "scalar":
        if kind == "read":
            out["result"] = _strip_output(args[2])
        elif kind == "write":
            out["value"] = args[2].strip()
        else:
            mask = args[2].strip()
            out["update_mask"] = mask
            out["update_value"] = (args[3].strip()
                                   if kind in {"update", "update_check"}
                                   else mask if kind == "set_bits" else "0")
            out["update_semantics"] = "masked_replace"
            if kind == "update_check":
                out["changed_result"] = _strip_output(args[4])
        return out
    out["payload_kind"] = "buffer"
    out["buffer"] = _strip_output(args[2])
    out["count"] = args[3].strip()
    # raw count is bytes; bulk count is register values whose width is defined
    # by regmap_config outside the callsite.
    if payload == "buffer_bytes":
        out["element_width"] = 1
        out["count_unit"] = "bytes"
    else:
        out["count_unit"] = "register_values"
    return out


def _i2c_contract(name: str, args: list[str], lhs: str | None) -> dict | None:
    scalar = _I2C_SCALAR.get(name)
    if scalar is not None:
        kind, width, has_selector = scalar
        needed = 1 + int(has_selector) + int(kind == "write")
        if len(args) < needed:
            return None
        selector = args[1] if has_selector else None
        out = _base(kind, "i2c_smbus", args[0], selector, width)
        if not has_selector:
            out["protocol"] = "smbus_byte"
        elif width == 1:
            out["protocol"] = "smbus_byte_data"
        else:
            out["protocol"] = ("smbus_word_data_swapped"
                                if name.endswith("_swapped")
                                else "smbus_word_data")
        if kind == "read":
            out["result"] = lhs
        else:
            out["value"] = args[2 if has_selector else 1].strip()
        if name.endswith("_swapped"):
            out["byte_order"] = "swapped"
        return out

    buffered = _I2C_BUFFER.get(name)
    if buffered is None:
        return None
    kind, protocol = buffered
    if protocol == "raw":
        if len(args) < 3:
            return None
        selector = None
        buffer_arg, count_arg = args[1], args[2]
        transport = "i2c"
    else:
        if len(args) < (4 if protocol == "i2c_block" else 3):
            return None
        selector = args[1]
        if protocol == "i2c_block":
            count_arg, buffer_arg = args[2], args[3]
        else:
            if kind == "write":
                count_arg, buffer_arg = args[2], args[3]
            else:
                buffer_arg = args[2]
                # SMBus block reads return the count as the call result.
                count_arg = "32"
        transport = "i2c_smbus"
    out = _base(kind, transport, args[0], selector, 1)
    out["payload_kind"] = "buffer"
    out["buffer"] = _strip_output(buffer_arg)
    out["count"] = count_arg.strip()
    out["count_unit"] = "bytes"
    out["protocol"] = protocol
    if lhs:
        out["result"] = lhs
        out["result_convention"] = "return_count"
    return out


def _message_transfer_contract(name: str, args: list[str],
                               lhs: str | None) -> dict | None:
    """Model public I2C/SPI message APIs without pretending they are MMIO."""
    transfer = _MESSAGE_TRANSFERS.get(name)
    if transfer is None or len(args) < (3 if transfer[0] == "i2c" else 2):
        return None
    transport, protocol = transfer
    message = args[1]
    out = _base("read", transport, args[0], message)
    out["payload_kind"] = "message"
    out["message"] = message.strip()
    if transport == "i2c":
        out["count"] = args[2].strip()
        out["count_unit"] = "messages"
    else:
        out.pop("count", None)
    out["protocol"] = protocol
    if lhs:
        out["result"] = lhs
        out["result_convention"] = "return_value"
    return out


def _public_mfd_contract(call, lhs: str | None) -> dict | None:
    path = (getattr(call, "callee_decl_path", "") or "").replace("\\", "/")
    if "/include/linux/mfd/" not in path:
        return None
    name = call.name or ""
    args = list(call.arg_text)
    param_types = list(getattr(call, "callee_param_types", []) or [])
    if name.endswith("_reg_read") and len(args) >= 2:
        out = _base("read", "mfd", args[0], args[1])
        out["result"] = lhs
        out["result_convention"] = "return_value"
        return out
    if name.endswith("_reg_write") and len(args) >= 3:
        width = _width_from_type(param_types[2]) if len(param_types) > 2 else 0
        out = _base("write", "mfd", args[0], args[1], width)
        out["value"] = args[2].strip()
        return out
    suffix = next((item for item in ("_set_bits", "_clear_bits")
                   if name.endswith(item)), None)
    if suffix and len(args) >= 3:
        width = _width_from_type(param_types[2]) if len(param_types) > 2 else 0
        out = _base("update", "mfd", args[0], args[1], width)
        out["update_mask"] = args[2].strip()
        out["update_value"] = args[2].strip() if suffix == "_set_bits" else "0"
        out["update_semantics"] = "masked_replace"
        out["helper_contract"] = suffix[1:]
        return out
    return None


def contract_for_call(call, lhs: str | None = None) -> dict | None:
    """Return a typed transaction contract for one AST-proven call."""
    args = list(call.arg_text)
    return (_regmap_contract(call.name, args)
            or _i2c_contract(call.name, args, lhs)
            or _message_transfer_contract(call.name, args, lhs)
            or _public_mfd_contract(call, lhs))


def is_transaction_call(call) -> bool:
    return contract_for_call(call) is not None
