"""Source facts extraction (.facts) — plan M9."""
from __future__ import annotations
import re
import os as _os
import clang.cindex as _cx

from ..spec import FactsSpec, StructDef, StructField, ResourceFact


_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.M)
_ERROR_RE = re.compile(r'return\s+(-(?:ENOMEM|ENODEV|ENXIO|EINVAL|ENOTSUPP|EIO|EBUSY|EAGAIN|EFAULT|ENOSYS|ERANGE|ENOSPC)|PTR_ERR\([^)]*\))')

# resource acquisition call patterns → (resource kind, binds_to heuristic)
_RESOURCE_CALLS = [
    ("devm_platform_ioremap_resource", "MmioResource", "g->base"),
    ("devm_ioremap_resource", "MmioResource", "g->base"),
    ("devm_ioremap", "MmioResource", "base"),
    ("devm_request_mem_region", "MmioResource", None),
    ("platform_get_resource", "MmioResource", None),
    ("devm_clk_get_enabled", "ClockResource", "g->clk"),
    ("devm_clk_get", "ClockResource", "g->clk"),
    ("clk_get", "ClockResource", "g->clk"),
    ("platform_get_irq", "IrqResource", None),
    ("devm_request_irq", "IrqResource", None),
]

# notable subsystem helper calls worth surfacing to the LLM
_HELPER_CALLS = {
    "devm_gpiochip_add_data", "gpiochip_add_data", "bgpio_init",
    "gpio_generic_chip_init", "gpio_irq_chip_set_chip",
    "platform_driver_register", "platform_driver_unregister",
    "virtio_device_ready", "register_virtio_device", "virtio_add_status",
    "virtio_finalize_features", "devm_regmap_init_mmio",
    "clk_prepare_enable", "clk_disable_unprepare",
}


def _has_call(source_text: str, name: str) -> bool:
    """Match a helper invocation, not a longer function name containing it."""
    return re.search(rf"\b{re.escape(name)}\s*\(", source_text) is not None


def _target_structs(tu, target_file: str) -> list[StructDef]:
    tgt = _os.path.abspath(target_file)
    out: list[StructDef] = []
    for c in tu.cursor.walk_preorder():
        if c.kind != _cx.CursorKind.STRUCT_DECL or not c.is_definition():
            continue
        f = c.location.file
        if f is None or _os.path.abspath(f.name) != tgt:
            continue
        if not c.spelling:
            continue   # anonymous struct
        fields = [StructField(ch.spelling, ch.type.spelling if ch.type else "")
                  for ch in c.get_children() if ch.kind == _cx.CursorKind.FIELD_DECL]
        if fields:
            out.append(StructDef(c.spelling, fields))
    return out


def infer_facts(source_text: str, source_path: str, tu, macros,
                callback_bindings: dict, register_names: set[str],
                formal: dict | None = None, driver_name: str = "",
                callback_signatures: dict[str, dict] | None = None
                ) -> FactsSpec:
    includes = _INCLUDE_RE.findall(source_text)
    structs = _target_structs(tu, source_path)

    # driver prefix (e.g. GPIO, VIRTIO, AHCI) from register names + driver name
    prefixes: set[str] = set()
    for rn in register_names:
        pfx = rn.split("_")[0]
        if pfx:
            prefixes.add(pfx.upper())
    if driver_name:
        prefixes.add(re.split(r"[^A-Za-z0-9]", driver_name)[0].upper())

    # names referenced by RIS / callbacks / resources / errors / helpers — these
    # constants are reconstruction-relevant even without a driver prefix
    referenced: set[str] = set(register_names)
    # Source-local numeric defines are part of the driver's semantics even
    # when they appear only in pure scalar callback arithmetic (and therefore
    # never enter the MMIO-only RIS).  Header-wide constants remain filtered
    # below; this adds only macros defined by the target source itself.
    referenced |= set(re.findall(
        r"^\s*#\s*define\s+([A-Za-z_]\w*)", source_text, flags=re.M))
    # PCI IDs are reconstruction-critical even when they come from a kernel
    # header (for example PCI_VENDOR_ID_INTEL).  Keep identifiers used as
    # PCI_DEVICE arguments instead of filtering them as header-wide noise.
    for pci_args in re.findall(r"\bPCI_DEVICE\s*\(([^)]*)\)", source_text):
        referenced |= set(re.findall(r"\b[A-Za-z_]\w*\b", pci_args))
    if formal is not None:
        from ..formal import walk_all_ops
        for m in formal["modules"]:
            for op in walk_all_ops(m["ops"]):
                if "Cond" in op:
                    referenced |= _vars_in_expr(op["Cond"]["guard"])
                elif "Write" in op:
                    referenced |= _vars_in_expr(op["Write"].get("value"))
                elif "ReadModifyWrite" in op:
                    referenced |= _vars_in_expr(op["ReadModifyWrite"].get("transform"))
    referenced |= set(callback_bindings.keys())
    for h in _HELPER_CALLS:
        if _has_call(source_text, h):
            referenced.add(h)

    # constants = int macros that are reconstruction-relevant.
    # Drop compiler builtins, kernel-wide config/arch noise, and anything not
    # driver-prefixed or referenced
    # (docs/plans/output-artifact-recommendations.md §"Trim .facts").
    constants: dict = {}
    for name in macros.names():
        if name.startswith("_") or name in register_names:
            continue
        if _is_noise_constant(name):
            continue
        off = macros.offset(name)
        if off is None:
            continue
        pfx = name.split("_")[0].upper()
        if name in referenced or pfx in prefixes:
            constants[name] = off

    # callbacks: {table.field: fn}
    callbacks: dict = {}
    for _symbol, info in callback_bindings.items():
        for binding in [info] + info.get("alternates", []):
            callbacks[f"{binding['table']}.{binding['field']}"] = \
                binding["function"]

    # resources: scan for acquisition calls
    resources: list[ResourceFact] = []

    def resource_policy(call: str, binds: str | None) -> tuple[bool, str | None]:
        """Recover source-level probe policy for acquired resources."""
        if call in {"devm_clk_get_optional_enabled", "devm_clk_get_optional",
                    "clk_get_optional"}:
            return False, "optional_api"
        if call != "devm_clk_get_enabled" or not binds:
            return True, None
        target = re.escape(binds)
        defer_only = re.search(
            rf"IS_ERR\s*\(\s*{target}\s*\)\s*&&\s*"
            rf"PTR_ERR\s*\(\s*{target}\s*\)\s*==\s*-EPROBE_DEFER",
            source_text,
        )
        if defer_only:
            return False, "probe_defer_only"
        return True, None

    for i, (call, _kind, binds) in enumerate(_RESOURCE_CALLS):
        if re.search(rf"\b{re.escape(call)}\s*\(", source_text):
            required, failure_policy = resource_policy(call, binds)
            resources.append(ResourceFact(
                f"{_kind.lower()[:4]}{i}", call, binds,
                required=required, failure_policy=failure_policy))
    # dedupe by acquisition, keep first, renumber
    seen = set()
    dedup = []
    for r in resources:
        if r.acquisition in seen:
            continue
        seen.add(r.acquisition)
        dedup.append(r)

    error_paths = sorted(set(_ERROR_RE.findall(source_text)))
    helper_calls = sorted({c for c in _HELPER_CALLS if _has_call(source_text, c)})

    return FactsSpec(
        source=source_path, includes=includes, structs=structs,
        constants=constants, callbacks=callbacks, resources=dedup,
        callback_signatures=dict(callback_signatures or {}),
        error_paths=[f"return {e}" for e in error_paths],
        helper_calls=helper_calls,
    )


# kernel-wide / config / arch constants that are NOT reconstruction-relevant
_NOISE_PREFIXES = (
    "CONFIG_", "KASAN_", "TASK_", "pt_regs_", "CPUINFO_", "BUG_", "TAINT_",
    "BITS_PER_", "PAGE_", "VM_", "SLAB_", "KMALLOC_", "NR_", "MAX_", "MIN_",
    "ULONG", "LONG", "UINT", "INT", "CHAR", "SIZE_", "ALIGNOF", "offsetof",
    "container_of", "READ", "WRITE", "unix", "linux",
)


def _is_noise_constant(name: str) -> bool:
    up = name
    for p in _NOISE_PREFIXES:
        if up.startswith(p):
            return True
    # all-lowercase or single-token generic (unix, linux, etc.) — drop
    if name.islower() and len(name) <= 8:
        return True
    return False


def _vars_in_expr(e) -> set[str]:
    if e is None:
        return set()
    out: set[str] = set()
    if "Var" in e:
        v = e["Var"]
        if re.fullmatch(r"[A-Za-z_]\w*", v):
            out.add(v)
    if "BinOp" in e:
        out |= _vars_in_expr(e["BinOp"].get("left"))
        out |= _vars_in_expr(e["BinOp"].get("right"))
    if "Ite" in e:
        out |= _vars_in_expr(e["Ite"].get("guard"))
        out |= _vars_in_expr(e["Ite"].get("then"))
        out |= _vars_in_expr(e["Ite"].get("else"))
    if "Bits" in e:
        out |= _vars_in_expr(e["Bits"].get("expr"))
    return out
