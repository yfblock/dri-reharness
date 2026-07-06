"""Linux framework callback-table recognition (plan Milestone 3).

Parses struct initializer field assignments (`.irq_ack = ftgpio_gpio_ack_irq`)
to map a function to its semantic role. The field name (not the function name)
determines the role most reliably: `.irq_ack` → interrupt_ack, `.probe` → probe,
`.find_vqs` → setup_queue, etc.

Tables covered: irq_chip, gpio_chip, platform_driver, virtio_config_ops,
dev_pm_ops, net_device_ops. Field names are unique enough across these to map
directly to a role + execution context.
"""
from __future__ import annotations
import re

# field name → (role, context)
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
    "set": ("write_config", "thread"),
    "generation": ("get_status", "thread"),
    "get_status": ("get_status", "thread"),
    "set_status": ("set_status", "thread"),
    "reset": ("reset", "thread"),
    "find_vqs": ("setup_queue", "thread"),
    "del_vqs": ("remove", "thread"),
    "get_shm_region": ("read_config", "thread"),
    "notify_vq": ("notify", "thread"),
    "notify": ("notify", "thread"),
    # gpio_chip (beyond irq)
    "get_direction": ("read_config", "thread"),
    "direction_input": ("write_config", "thread"),
    "direction_output": ("write_config", "thread"),
    "get": ("read_config", "thread"),
    "set": ("write_config", "thread"),
    "set_config": ("write_config", "thread"),
    "request": ("init", "thread"),
    "free": ("remove", "thread"),
    # generic
    "init": ("init", "boot"),
    "exit": ("remove", "thread"),
}

# which struct type a field likely belongs to (for callback_table label)
FIELD_TABLE = {
    "irq_ack": "irq_chip", "irq_mask": "irq_chip", "irq_unmask": "irq_chip",
    "irq_mask_ack": "irq_chip", "irq_eoi": "irq_chip", "irq_enable": "irq_chip",
    "irq_disable": "irq_chip", "irq_set_type": "irq_chip", "handle_irq": "irq_chip",
    "probe": "platform_driver", "remove": "platform_driver", "shutdown": "platform_driver",
    "suspend": "dev_pm_ops", "resume": "dev_pm_ops", "freeze": "dev_pm_ops",
    "thaw": "dev_pm_ops", "poweroff": "dev_pm_ops", "restore": "dev_pm_ops",
    "find_vqs": "virtio_config_ops", "del_vqs": "virtio_config_ops",
    "get_status": "virtio_config_ops", "set_status": "virtio_config_ops",
    "reset": "virtio_config_ops", "generation": "virtio_config_ops",
    "get_shm_region": "virtio_config_ops", "notify_vq": "virtio_config_ops",
}


_DESIGNATED_INIT = re.compile(
    r"\.\s*([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)\s*[,}]"
)


def _strip_comments_strings(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    out = []
    for ln in src.splitlines():
        idx = ln.find("//")
        if idx >= 0:
            ln = ln[:idx]
        out.append(ln)
    src = "\n".join(out)
    # remove string/char literals
    src = re.sub(r'"(\\.|[^"\\])*"', ' "" ', src)
    src = re.sub(r"'(\\.|[^'\\])*'", " ' ' ", src)
    return src


def parse_callback_bindings(source_text: str, target_names: set[str]) -> dict[str, dict]:
    """funcname → {field, role, context, table} for each `.field = funcname`
    where funcname is a target function."""
    src = _strip_comments_strings(source_text)
    out: dict[str, dict] = {}
    for m in _DESIGNATED_INIT.finditer(src):
        field, fname = m.group(1), m.group(2)
        if fname not in target_names:
            continue
        role_ctx = FIELD_ROLE.get(field)
        if role_ctx is None:
            continue
        role, ctx = role_ctx
        out[fname] = {
            "field": field,
            "role": role,
            "context": ctx,
            "table": FIELD_TABLE.get(field, "ops"),
        }
    return out


def name_role_hints(func_name: str) -> str | None:
    """Fallback role inference from function name keywords (weaker than field)."""
    n = func_name.lower()
    hints = [
        ("probe", "probe"), ("remove", "remove"), ("shutdown", "remove"),
        ("suspend", "suspend"), ("resume", "resume"),
        ("ack_irq", "interrupt_ack"), ("mask_irq", "interrupt_mask"),
        ("unmask_irq", "interrupt_unmask"), ("set_irq_type", "set_irq_type"),
        ("irq_handler", "interrupt_handler"), ("handler", "interrupt_handler"),
        ("setup_queue", "setup_queue"), ("init_device", "init"),
        ("notify", "notify"), ("get_status", "get_status"), ("set_status", "set_status"),
        ("reset", "reset"), ("init", "init"),
    ]
    for kw, role in hints:
        if kw in n:
            return role
    return None
