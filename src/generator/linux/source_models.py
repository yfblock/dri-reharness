from __future__ import annotations
import os
import re
import copy
from extractor.formal import walk_leaf_ops
from extractor.spec import TypeMap, PrimitiveMap, StateMap, CallbackMap, PUBLIC_CALLBACK_TYPES
from ..subsystem_runner import (portable_sdhci_accessor_only,
                               portable_virtio_state_only)
from ..common import (ops_to_c, local_decls, value_var_names,
                     replace_expr_var, addr_to_c, lowering_receipt,
                     ris_op_digest, lowering_recipes,
                     transaction_runtime_prelude, transaction_digest,
                     detect_transaction_transports,
                     transaction_runtime_prelude_filtered)


from .source_parse import (source_object_macros, source_function,
    parameter_names, mask_c_source, matching_delimiter,
    balanced_initializer_blocks, initializer_expr)

def source_gpio_model(facts) -> dict | None:
    """Recover the conservative gpio_generic_chip_init configuration."""
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not os.path.isfile(source_path):
        return None
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    match = re.search(
        r"\b([A-Za-z_]\w*)\s*=\s*\(struct\s+gpio_generic_chip_config\s*\)"
        r"\s*\{(?P<body>.*?)\}\s*;",
        source, re.S)
    if match is None or not re.search(
            rf"\bgpio_generic_chip_init\s*\([^,]+,\s*&\s*"
            rf"{re.escape(match.group(1))}\s*\)", source, re.S):
        return None
    fields = dict(re.findall(
        r"\.(dev|sz|dat|set|clr|dirout|dirin|flags)\s*=\s*([^,}]+)",
        match.group("body")))
    if not {"sz", "dat", "set", "dirout"} <= set(fields):
        return None
    # The emitted model below is intentionally limited to the native-endian
    # 32-bit dat/set/dirout form.  Other gpio-mmio configurations have
    # materially different accessor semantics and must not be approximated.
    if fields["sz"].strip() != "4" or "clr" in fields or "dirin" in fields:
        return None
    if "flags" in fields and fields["flags"].strip() not in {"0", "0x0"}:
        return None

    normalized: dict[str, str] = {}
    for field, raw in fields.items():
        value = raw.strip()
        if field == "dev":
            normalized[field] = "&pdev->dev"
            continue
        value = re.sub(
            r"\b[A-Za-z_]\w*->(?:base|reg|regs|ioaddr|[A-Za-z_]\w*_base)\b",
            "g->base", value)
        residual = value.replace("g->base", "")
        if re.search(r"->|\.[A-Za-z_]", residual):
            return None
        if not re.fullmatch(r"[A-Za-z0-9_xX()|&~+\-<>\s]+", value):
            return None
        normalized[field] = value

    ngpio = None
    constants = getattr(facts, "constants", {}) if facts else {}
    for raw in re.findall(r"\.ngpio\s*=\s*([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)\s*;",
                          source):
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", raw):
            ngpio = int(raw, 0)
        elif raw in constants and isinstance(constants[raw], int):
            ngpio = constants[raw]
        if ngpio is not None:
            break
    return {"fields": normalized, "ngpio": ngpio}

def match_data_state_initializers(facts, device_spec) -> dict[str, str]:
    """Bind scalar state whose source is platform match-data selection."""
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not os.path.isfile(source_path):
        return {}
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    fields = {state.name for state in device_spec.state
              if state.type in {"UInt", "UInt64", "Bool"}}
    result: dict[str, str] = {}
    for field in fields:
        matches = re.findall(
            rf"\b[A-Za-z_]\w*\s*->\s*{re.escape(field)}\s*=\s*"
            r"(?:\(\s*uintptr_t\s*\)\s*)?"
            r"device_get_match_data\s*\(\s*([^;)]+)\s*\)\s*;",
            source)
        if len(matches) != 1:
            continue
        argument = matches[0].strip()
        aliases = re.findall(
            rf"(?<![.>])\b{re.escape(argument)}\s*=\s*([^;]+);", source)
        if aliases:
            argument = aliases[-1].strip()
        if argument in {"dev", "&pdev->dev", "pdev->dev.parent"}:
            argument = "&pdev->dev"
        if argument != "&pdev->dev":
            continue
        result[field] = "(uintptr_t)device_get_match_data(&pdev->dev)"
    return result

def source_generic_irq_model(facts) -> dict | None:
    """Recover the generic-chip mask/unmask/EOI contract used by a source."""
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not os.path.isfile(source_path):
        return None
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    type_var = re.search(r"\bstruct\s+irq_chip_type\s*\*\s*([A-Za-z_]\w*)", source)
    if type_var is None:
        return None
    var = re.escape(type_var.group(1))

    def assigned(path: str) -> str | None:
        found = re.search(rf"\b{var}\s*->\s*{path}\s*=\s*([^;]+);", source)
        return found.group(1).strip() if found else None

    helpers = {
        "irq_mask": assigned(r"chip\s*\.\s*irq_mask"),
        "irq_unmask": assigned(r"chip\s*\.\s*irq_unmask"),
        "irq_eoi": assigned(r"chip\s*\.\s*irq_eoi"),
    }
    if helpers != {
            "irq_mask": "irq_gc_mask_clr_bit",
            "irq_unmask": "irq_gc_mask_set_bit",
            "irq_eoi": "irq_gc_eoi"}:
        return None
    mask_reg = assigned(r"regs\s*\.\s*mask")
    eoi_reg = assigned(r"regs\s*\.\s*eoi")
    if not mask_reg or not eoi_reg:
        return None
    for value in (mask_reg, eoi_reg):
        if not re.fullmatch(r"[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+", value):
            return None
    allocation = re.search(
        r"\bdevm_irq_alloc_generic_chip\s*\(.*?,\s*(handle_[A-Za-z_]\w*)\s*\)",
        source, re.S)
    if allocation is None:
        return None
    return {"mask_reg": mask_reg, "eoi_reg": eoi_reg,
            "handler": allocation.group(1)}

def banked_irq_status_model(facts) -> dict | None:
    """Recover the source-proven pending-register expression for a bank IRQ."""
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not os.path.isfile(source_path):
        return None
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    status = re.search(
        r"\b[A-Za-z_]\w*status\s*=\s*[A-Za-z_]\w*read[A-Za-z_]*\s*"
        r"\([^,]+,\s*([A-Za-z_]\w*)\s*\)\s*;", source)
    if status is None or not re.search(r"\bgeneric_handle_irq\s*\(", source):
        return None
    original = status.group(1)
    converted = re.search(
        rf"\bcase\s+{re.escape(original)}\s*:\s*"
        r"return\s+([A-Za-z_]\w*)\s*;", source)
    if converted is None:
        return {"expr": original}
    condition = re.search(
        r"if\s*\(\s*\(\s*[A-Za-z_]\w*\s*->\s*flags\s*&\s*"
        r"([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)\s*\)\s*==\s*"
        r"([A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+)\s*\)", source)
    if condition is None:
        return None
    mask, value = condition.groups()
    return {
        "expr": (f"(((g->flags & {mask}) == {value}) ? "
                 f"{converted.group(1)} : {original})"),
    }

def sdhci_source_model(formal: dict, facts) -> dict | None:
    source = getattr(facts, "source", None) if facts is not None else None
    source = source or formal.get("metadata", {}).get("source")
    if not source or not os.path.isfile(source):
        return None
    text = open(source, encoding="utf-8", errors="replace").read()
    pdata = []
    for name, body in balanced_initializer_blocks(text, "sdhci_pltfm_data"):
        pdata.append({
            "source_name": name,
            "quirks": initializer_expr(body, "quirks"),
            "quirks2": initializer_expr(body, "quirks2"),
            "has_ops": bool(re.search(r"\.\s*ops\s*=", body)),
        })
    if not pdata:
        return None
    matches = []
    for block in re.finditer(r"\{([^{}]*\.\s*compatible\s*=\s*\"[^\"]+\"[^{}]*)\}",
                             text, re.S):
        body = block.group(1)
        compatible = re.search(r"\.\s*compatible\s*=\s*\"([^\"]+)\"", body)
        data = re.search(r"\.\s*data\s*=\s*&\s*([A-Za-z_]\w*)", body)
        if compatible:
            matches.append({
                "compatible": compatible.group(1),
                "pdata": data.group(1) if data else pdata[0]["source_name"],
            })
    summaries = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    delegates = (summaries.get("sdhci_delegates", [])
                 if isinstance(summaries, dict) else [])
    return {
        "pdata": pdata,
        "matches": matches,
        "delegates": delegates,
        "clock": ("optional" if "devm_clk_get_optional_enabled" in text
                  else "required" if "devm_clk_get_enabled" in text else None),
        "mmc_of_parse": bool(re.search(r"\bmmc_of_parse\s*\(", text)),
        "pm": "sdhci_pltfm_pmops" in text,
    }
