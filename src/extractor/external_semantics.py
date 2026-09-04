"""Closed-category external-call semantics for RIS 0.3.0.

External calls are recorded deterministically at extraction time
(``call_rows._external_call_row``) but their *meaning* is annotation data,
never free-form extractor output.  Every external call gets one category
from a closed enum so downstream consumers (porting, verification) can
dispatch on it without parsing prose:

1. the deterministic rule table here (kernel naming conventions — no
   model, no network, stable across runs);
2. a reviewed ``annotations.json`` store keyed by callee name, written by
   the offline LLM annotator and merged at formalization;
3. ``unknown`` otherwise — fail-closed, still visible as a first-class
   node instead of being silently dropped.

The rule table is intentionally small: it only claims names whose category
is unambiguous from the name itself.  Anything debatable stays for the
annotator or remains ``unknown``.
"""
from __future__ import annotations

import json
import os

# Closed category enum.  Adding a member is a schema change; consumers
# switch on exactly these strings.
EXTERNAL_CATEGORIES = (
    "pure",            # no externally visible effect; porting-safe
    "delay",           # busy/sleep wait, duration in an argument
    "alloc",           # allocate memory, may fail, returns pointer
    "free",            # release memory obtained from the alloc counterpart
    "lock",            # acquire an execution-ordering primitive
    "unlock",          # release the counterpart primitive
    "dma-map",         # make CPU memory device-accessible
    "dma-sync",        # ownership transfer between CPU and device
    "dma-unmap",       # release a DMA mapping
    "power-on",        # enable a clock / power domain / runtime PM ref
    "power-off",       # drop the counterpart reference
    "reset",           # assert/deassert a reset line
    "register-access", # register I/O through a framework bus (regmap...)
    "print",           # logging; observability only
    "probe-defer",     # may legitimately fail with -EPROBE_DEFER
    "unknown",         # not yet classified — fail closed
)

# Ordered (predicate, category) rules.  First match wins; longer names are
# listed before their prefixes.  Pure prefix families use tuple prefixes.
_RULES: list[tuple[tuple[str, ...], str]] = [
    # --- print family (dev_* prints are not devm_* allocators, so the
    # exact stems come first; pr_ is a uniform kernel namespace; the _dev_*
    # and _printk spellings are what macros like dev_err expand to) ---
    (("printk", "_printk", "print_hex_dump", "dev_err_probe",
      "dev_printk", "_dev_printk", "dev_emerg", "dev_alert", "dev_crit",
      "dev_err", "dev_warn", "dev_notice", "dev_info", "dev_dbg",
      "_dev_emerg", "_dev_alert", "_dev_crit", "_dev_err", "_dev_warn",
      "_dev_notice", "_dev_info", "_dev_dbg", "pr_"),
     "print"),
    # --- alloc / free ---
    (("kmalloc", "kzalloc", "kcalloc", "krealloc", "kstrdup", "kmemdup",
      "kstrndup", "kvasprintf", "kasprintf", "vmalloc", "vzalloc",
      "kvmalloc", "kvzalloc", "devm_kasprintf", "get_zeroed_page"),
     "alloc"),
    (("devm_kmalloc", "devm_kzalloc", "devm_kcalloc", "devm_kmemdup",
      "devm_kstrdup", "devm_kstrndup", "devm_kvasprintf"),
     "alloc"),
    (("kfree", "kfree_sensitive", "vfree", "kvfree", "free_pages"),
     "free"),
    (("devm_kfree",), "free"),
    # --- lock / unlock ---
    (("spin_lock", "spin_trylock", "raw_spin_lock", "raw_spin_trylock",
      "_raw_spin_lock", "_raw_spin_trylock",
      "mutex_lock", "mutex_lock_interruptible", "mutex_lock_killable",
      "mutex_trylock", "read_lock", "write_lock", "seqcount_init",
      "local_irq_disable", "local_bh_disable", "local_irq_save"),
     "lock"),
    (("spin_unlock", "raw_spin_unlock", "_raw_spin_unlock",
      "mutex_unlock", "read_unlock", "write_unlock",
      "local_irq_enable", "local_bh_enable", "local_irq_restore"),
     "unlock"),
    # --- DMA ---
    (("dma_map_single", "dma_map_page", "dma_map_sgtable", "dma_map_sg_attrs",
      "dma_map_resource", "dma_alloc_coherent", "dma_alloc_wc",
      "dma_pool_alloc", "dmam_alloc_coherent", "dmaengine_prep_*"),
     "dma-map"),
    (("dma_sync_single_for_cpu", "dma_sync_single_for_device",
      "dma_sync_sg_for_cpu", "dma_sync_sg_for_device"),
     "dma-sync"),
    (("dma_unmap_single", "dma_unmap_page", "dma_unmap_sg",
      "dma_unmap_resource", "dma_free_coherent", "dma_pool_free",
      "dmam_free_coherent"),
     "dma-unmap"),
    # --- power / clocks ---
    (("pm_runtime_get_sync", "pm_runtime_get_noresume", "pm_runtime_resume",
      "pm_runtime_get_suppliers", "clk_prepare", "clk_enable",
      "clk_prepare_enable", "clk_bulk_prepare_enable",
      "devm_clk_get_enabled"),
     "power-on"),
    (("pm_runtime_put_sync", "pm_runtime_put_noidle", "pm_runtime_put",
      "pm_runtime_suspend", "clk_disable", "clk_unprepare",
      "clk_disable_unprepare", "clk_bulk_disable_unprepare"),
     "power-off"),
    # --- reset control ---
    (("reset_control_assert", "reset_control_deassert",
      "reset_control_reset", "reset_control_acquire"),
     "reset"),
    # --- register access through a framework ---
    (("regmap_read", "regmap_write", "regmap_update_bits",
      "regmap_update_bits_check", "regmap_field_read",
      "regmap_field_write", "regmap_bulk_read", "regmap_bulk_write",
      "pci_read_config", "pci_write_config"),
     "register-access"),
    # --- delay ---
    (("udelay", "ndelay", "mdelay", "fsleep", "usleep_range"),
     "delay"),
    # --- pure memory/value helpers ---
    (("memset", "memcpy", "memmove", "memcmp", "strlen", "strcmp",
      "strncmp", "strnlen", "strscpy", "strscpy_pad", "strcpy",
      "strncpy", "strchr", "strrchr", "strstr", "skip_spaces",
      "strim", "kstrtoint", "kstrtouint", "kstrtoul", "kstrtou32",
      "kstrtou16", "kstrtou8", "kstrtos32", "kstrtobool",
      # value/query accessors: no externally visible effect
      "gpiochip_get_data", "clk_get_rate", "kobject_name", "dev_name",
      "dev_get_drvdata", "platform_get_drvdata", "to_platform_device",
      "__ffs", "_ffs", "find_first_zero_bit", "find_next_zero_bit",
      "is_power_of_2",
      # bit search helpers (find.h) and compile-time check shims
      "find_next_bit", "find_first_bit", "_find_next_bit",
      "find_last_bit", "__must_check_overflow",
      # descriptor unwrappers and probe-time config queries: they only
      # write caller-visible output, never device or global state
      "irq_data_to_desc", "dmi_first_match", "of_property_read",
      "of_device_is_available", "of_get_property",
      # irq descriptor accessors (irqdesc.h): pure container unwraps
      "irqd_to_hwirq", "irq_data_get_irq_chip_data",
      "irq_desc_get_chip", "irq_desc_get_handler_data"),
     "pure"),
]

# Exact-name overrides that must win before prefix matching (dev_ prints
# are not devm_ allocators, etc.).  Kept separate from _RULES for clarity.
_EXACT: dict[str, str] = {
    "devm_kstrdup": "alloc",
    "printk": "print",
}


def rule_category(name: str) -> str | None:
    """Deterministic name-based category, or None when no rule applies."""
    if not name:
        return None
    # clang renames a TU-local static inline (e.g. find.h's __ffs) by
    # prefixing "variable" — classify by the original kernel name.
    if name.startswith("variable"):
        stripped = rule_category(name[len("variable"):])
        if stripped is not None:
            return stripped
    exact = _EXACT.get(name)
    if exact is not None:
        return exact
    for prefixes, category in _RULES:
        # A rule matches when the callee name starts with the listed stem
        # (e.g. "kmalloc" covers "kmalloc_array", "dev_warn" covers
        # "dev_warn_once").  Rules are ordered so more specific stems
        # (devm_*, raw_spin_*) precede their shorter relatives.
        if any(name.startswith(prefix) for prefix in prefixes):
            return category
    return None


def load_annotations(path: str | None = None) -> dict[str, dict]:
    """Load the reviewed external-call annotation store.

    The store maps callee name to
    ``{"category": str, "confidence": float, "source": str,
       "return": str, "effects": [...], "params": {...},
       "porting_hint": str, "basis": str}``.
    Missing file returns an empty store — annotation is an enhancement,
    never an extraction dependency.
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))),
            "data", "external-call-annotations.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        name: entry for name, entry in data.items()
        if isinstance(entry, dict)
        and entry.get("category") in EXTERNAL_CATEGORIES
    }


def classify(name: str, annotations: dict[str, dict] | None = None) -> dict:
    """Resolve one external callee to its category and provenance.

    Reviewed annotations outrank the rule table: they encode grounded
    kernel-source analysis (or deliberate human correction), while rules
    are name conventions only.  Returns
    ``{"category": ..., "source": "annotation"|"rule"|"unknown"}``.
    """
    annotations = annotations or {}
    entry = annotations.get(name)
    if isinstance(entry, dict) and entry.get("category") in EXTERNAL_CATEGORIES:
        return {
            "category": entry["category"],
            "source": "annotation",
            "confidence": entry.get("confidence"),
        }
    category = rule_category(name)
    if category is not None:
        return {"category": category, "source": "rule",
                "confidence": 0.7}
    return {"category": "unknown", "source": "unknown", "confidence": None}
