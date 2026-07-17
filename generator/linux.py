"""Deterministic Linux backend.

The backend emits complete, buildable modules for the two buses exercised by
the artifact: platform MMIO devices (including GPIO controllers) and PCI MMIO
devices (including QEMU edu).  RIS operations remain the source of register
behavior; DeviceSpec/BindSpec/FactsSpec select framework glue and callbacks.

Unsupported callback kinds are reported with `REHARNESS_UNSUPPORTED` comments
and are not silently wired with an incompatible C signature.
"""
from __future__ import annotations

import os
import re
import copy

from extractor.formal import walk_leaf_ops
from extractor.spec import PUBLIC_CALLBACK_TYPES
from .subsystem_runner import (portable_sdhci_accessor_only,
                               portable_virtio_state_only)
from .common import (ops_to_c, local_decls, value_var_names,
                     _replace_expr_var, addr_to_c)

_MODELED_STATE_FIELDS = {
    "bypass_orig", "mask_cache", "skip_init", "ngpio",
    "gpio_dir", "gpio_is", "gpio_ibe", "gpio_iev", "gpio_ie",
    "version", "features",
    "ready", "idev", "evbit", "absbit",
    "virtio_evt_available", "virtio_evt_completed",
    "virtio_evt_outstanding", "virtio_evt_queue_depth",
    "virtio_evt_notified", "virtio_sts_available",
    "virtio_sts_completed", "virtio_sts_outstanding",
    "virtio_sts_queue_depth", "virtio_sts_notified",
    "xfer_mode_shadow",
    "enabled", "suspended", "connected", "remote_wakeup_allowed",
    "halted", "wedged", "dir_in", "periodic", "isochronous",
    "num_eps", "num_channels", "op_state", "lx_state",
    "fifo_size", "fifo_load", "desc_count", "next_desc", "compl_desc",
    "total_data", "target_frame", "frame_number", "dma",
    "hpi_regstep",
    "sie_num",
    "flags", "nr_ports",
}


def _cid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _callback_map(bind, facts, device_spec=None) -> dict[str, str]:
    out = {c.function: c.table_field for c in bind.callbacks}
    functions = ({function.name: function
                  for function in device_spec.functions}
                 if device_spec is not None else {})
    if facts is not None:
        for table_field, fn in facts.callbacks.items():
            function = functions.get(fn)
            owner = table_field.split(".", 1)[0]
            if (function is not None
                    and (function.role in {"unknown", "helper"}
                         or owner not in PUBLIC_CALLBACK_TYPES)):
                continue
            # BindSpec already selected the primary typed binding.  Facts may
            # retain alternate fields that share one callback function (for
            # example PM freeze/thaw/restore); they are evidence, not a reason
            # to overwrite executable backend intent.
            out.setdefault(fn, table_field)
    return out


def _source_preserved_virtio(formal: dict, device_spec, facts) -> str | None:
    """Retain a fully audited virtio lifecycle while RIS models its state."""
    if not portable_virtio_state_only(formal, device_spec):
        return None
    source = getattr(facts, "source", None) if facts is not None else None
    source = source or formal.get("metadata", {}).get("source")
    if not source or not os.path.isfile(source):
        return None
    text = open(source, encoding="utf-8", errors="replace").read()
    if (not re.search(r"\bstruct\s+virtio_driver\b", text)
            or not re.search(r"\bmodule_virtio_driver\s*\(", text)
            or not re.search(r"\bvirtio_find_vqs\s*\(", text)):
        return None
    return ("// Auto-generated source-preserving virtio backend (reharness)\n"
            "// Lifecycle retained after config/virtqueue contract audit.\n"
            + text)


def _last_read_var(module: dict) -> str | None:
    reads = [o["Read"].get("var") for o in walk_leaf_ops(module["ops"])
             if "Read" in o and o["Read"].get("var")]
    return reads[-1] if reads else None


def _portable_function_macros(formal: dict) -> dict[str, dict]:
    macros = formal.get("metadata", {}).get("function_macros", {})
    return {
        name: definition for name, definition in macros.items()
        if not re.search(r"->|\.[A-Za-z_]", definition.get("body", ""))
    }


def _bound_resource_probe_ops(ops):
    """Select the success path after backend resource binding.

    DeviceSpec backends acquire MMIO/IRQ/clock resources before replaying RIS
    probe initialization.  Source gotos into cleanup tails therefore describe
    acquisition failures already handled by backend glue, not runtime branches
    inside the bound-resource RIS contract.
    """
    out = []
    cleanup = re.compile(r"^(?:err\w*|.*(?:fail|failed)|cleanup\w*)$")
    for original in copy.deepcopy(ops):
        if "Cond" in original:
            control = original["Cond"].get("control") or {}
            if (control.get("source") == "forward-goto"
                    and cleanup.match(control.get("target_label", ""))):
                out.extend(_bound_resource_probe_ops(
                    original["Cond"].get("then_ops", [])))
                continue
            original["Cond"]["then_ops"] = _bound_resource_probe_ops(
                original["Cond"].get("then_ops", []))
            if original["Cond"].get("else_ops"):
                original["Cond"]["else_ops"] = _bound_resource_probe_ops(
                    original["Cond"]["else_ops"])
        elif "Seq" in original:
            original["Seq"]["ops"] = _bound_resource_probe_ops(
                original["Seq"].get("ops", []))
        elif "Loop" in original:
            original["Loop"]["body"] = _bound_resource_probe_ops(
                original["Loop"].get("body", []))
        out.append(original)
    return out


def _normalize_text(text: str, safe_function_calls: set[str] | None = None
                    ) -> tuple[str, bool]:
    """Lower source-private member expressions to the generated device state.

    The replacement is deliberately conservative and is reported as an
    unsupported semantic binding, so the module can be compiled/tested without
    readiness falsely claiming exact reconstruction.
    """
    unsupported = False
    original = text
    # String/character literals can leak into a recovered expression through
    # macro-expanded logging calls. They are never meaningful MMIO values.
    text = re.sub(r'"(?:\\.|[^"\\])*"', "0", text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "0", text)
    unsupported |= text != original
    text = re.sub(r"\bd->hwirq\b", "irqd_to_hwirq(d)", text)
    hpi_root = (r"\b[A-Za-z_]\w*"
                r"(?:(?:->|\.)[A-Za-z_]\w*)*?"
                r"(?:->|\.)hpi")
    text = re.sub(hpi_root + r"(?:->|\.)base\b", "base", text)
    text = re.sub(hpi_root + r"(?:->|\.)regstep\b",
                  "__state_hpi_regstep", text)
    text = re.sub(
        r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*?"
        r"(?:->|\.)sie_num\b", "__state_sie_num", text)
    text = re.sub(
        r"\b[A-Za-z_]\w*->(?:base|mmio|reg|regs|ioaddr|[A-Za-z_]\w*_base)\b",
        "base", text)
    text = re.sub(r"\b[A-Za-z_]\w*_base\b", "base", text)
    for field in _MODELED_STATE_FIELDS:
        text = re.sub(
            rf"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*"
            rf"(?:->|\.){re.escape(field)}\b",
            f"__state_{field}", text)
    text = re.sub(r"\bnum_gpios\b", "__state_ngpio", text)
    safe_calls = {
        "BIT", "GENMASK", "FIELD_GET", "FIELD_PREP", "test_bit", "sizeof",
        "lower_32_bits", "upper_32_bits", "cpu_to_le32", "le32_to_cpu",
        "cpu_to_le16", "le16_to_cpu", "irqd_to_hwirq",
        "readb", "readw", "readl", "readq",
        "ioread8", "ioread16", "ioread32", "ioread64",
        "readb_relaxed", "readw_relaxed", "readl_relaxed", "readq_relaxed",
    }
    call_re = re.compile(r"\b([A-Za-z_]\w*)\s*\([^()]*\)")
    def replace_call(match):
        nonlocal unsupported
        if (match.group(1) in safe_calls
                or match.group(1) in (safe_function_calls or set())):
            return match.group(0)
        unsupported = True
        return "0"
    for _ in range(8):
        replaced = call_re.sub(replace_call, text)
        if replaced == text:
            break
        text = replaced
    if re.fullmatch(r"\s*scoped_guard\s*\(.*\)\s*", text):
        text = "1"
    # Statement-like iteration macros are not C expressions.  A partially
    # recovered AST may expose one as a Cond guard; keep the backend buildable
    # with an explicit unsupported marker instead of emitting `if (for (...))`.
    if re.search(r"\bfor_each_[A-Za-z_]\w*\s*\(", text):
        unsupported = True
        text = "0"
    # Remaining source-private fields have no DeviceSpec binding yet.  Use a
    # neutral value and force backend readiness false via the marker.
    complex_member_re = re.compile(
        r"\b[A-Za-z_]\w*(?:\[[^]]+\])?"
        r"(?:(?:->|\.)[A-Za-z_]\w*(?:\[[^]]+\])?)+")
    if complex_member_re.search(text):
        unsupported = True
        text = complex_member_re.sub("0", text)
    member_re = re.compile(
        r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+(?:\[[^]]+\])?")
    if member_re.search(text):
        unsupported = True
        text = member_re.sub("0", text)
    array_re = re.compile(
        r"\b[A-Za-z_]\w*\[[^]]+\](?:(?:->|\.)[A-Za-z_]\w*)*")
    if array_re.search(text):
        unsupported = True
        text = array_re.sub("0", text)
    # Adjacent logical-and plus a normalized unary address-of can leave an
    # invalid `&&0`/`&& (` fragment.  This only occurs after the pointee was
    # already classified as unsupported source-private state.
    repaired = re.sub(r"^\s*&&\s*(?=0|\()", "", text)
    repaired = re.sub(r"([(<>=!?:,])\s*&&\s*(?=0|\()", r"\1 ", repaired)
    unsupported |= repaired != text
    text = repaired
    # A normalized address-of member may become `== &0`; remove only unary
    # address-of, never a legitimate bitwise `value & 0` expression.
    text = re.sub(r"^\s*&\s*0\b", "0", text)
    text = re.sub(r"(?<=[=(,])\s*&\s*0\b", " 0", text)
    text = re.sub(r"(?P<op>==|!=|\?|:)\s*&\s*0\b",
                  lambda match: match.group("op") + " 0", text)
    # A source-private upper bound normalized to zero must not be passed to
    # the kernel GENMASK constant assertions as `0 - 1`.
    repaired = re.sub(
        r"\bGENMASK\s*\(\s*0\s*-\s*1\s*,\s*[^)]+\)", "0", text)
    unsupported |= repaired != text
    text = repaired
    if re.search(r"\b0\s*->", text):
        unsupported = True
        text = "0"
    depth = 0
    balanced = True
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                balanced = False
                break
    if depth != 0 or not balanced:
        unsupported = True
        text = "0"
    if re.search(r"(?:&&|\|\||==|!=|<=|>=|[+\-*/%&|^<>=!])\s*$", text):
        unsupported = True
        text = "0"
    # Residual source fragments from macro-expanded diagnostics or incomplete
    # ternaries are not valid standalone C expressions.
    if re.search(r'["\'\\%;{}]|\+\+|--|\?|:', text):
        unsupported = True
        text = "0"
    return text, unsupported


def _bind_state_text(text: str, state_prefix: str | None) -> str:
    if not state_prefix:
        return text
    return re.sub(r"\b__state_([A-Za-z_]\w*)\b",
                  rf"{state_prefix}->\1", text)


def _mask_c_source(source: str) -> str:
    """Mask comments and literals while preserving offsets and newlines."""
    pattern = re.compile(
        r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.S)

    def mask(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return pattern.sub(mask, source)


def _matching_delimiter(masked: str, start: int, opening: str,
                        closing: str) -> int | None:
    depth = 0
    for index in range(start, len(masked)):
        char = masked[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _source_function(source: str, name: str) -> dict | None:
    """Return an exact source function definition with balanced delimiters."""
    masked = _mask_c_source(source)
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", masked):
        open_paren = masked.find("(", match.start())
        close_paren = _matching_delimiter(masked, open_paren, "(", ")")
        if close_paren is None:
            continue
        brace = close_paren + 1
        while brace < len(masked) and masked[brace].isspace():
            brace += 1
        if brace >= len(masked) or masked[brace] != "{":
            continue
        close_brace = _matching_delimiter(masked, brace, "{", "}")
        if close_brace is None:
            continue
        header_start = source.rfind("\n", 0, match.start()) + 1
        return {
            "header": source[header_start:brace].strip(),
            "params": source[open_paren + 1:close_paren],
            "body": source[brace + 1:close_brace],
            "text": source[header_start:close_brace + 1].strip(),
        }
    return None


def _parameter_names(params: str) -> list[str]:
    names = []
    for param in params.split(","):
        param = param.strip()
        if not param or param == "void":
            continue
        match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^]]*\])?\s*$", param)
        if match:
            names.append(match.group(1))
    return names


def _parse_clk_ops_groups(source: str) -> dict[str, dict[str, str]]:
    """Preserve individual clk_ops instances instead of last-field-wins."""
    masked = _mask_c_source(source)
    groups: dict[str, dict[str, str]] = {}
    pattern = re.compile(
        r"\b(?:static\s+)?(?:const\s+)?struct\s+clk_ops\s+"
        r"([A-Za-z_]\w*)\s*=\s*\{")
    for match in pattern.finditer(masked):
        brace = masked.find("{", match.start())
        close = _matching_delimiter(masked, brace, "{", "}")
        if close is None:
            continue
        block = source[brace + 1:close]
        fields = {
            field: function for field, function in re.findall(
                r"\.([A-Za-z_]\w*)\s*=\s*&?\s*([A-Za-z_]\w*)", block)
        }
        if fields:
            groups[match.group(1)] = fields
    return groups


def _lower_clock_source_callback_analysis(
        source: str, name: str, priv: str) -> tuple[str | None, str | None]:
    """Lower a clock callback while preserving its scalar C semantics.

    The original callback body is retained, but the source-private container
    pointer is rebound to the generated private object's MMIO base.  This
    captures arithmetic and early returns that the MMIO-only RIS does not yet
    represent; lowering is rejected if any private member remains unbound.
    """
    function = _source_function(source, name)
    if function is None:
        return None, f"callback definition not found: {name}"
    body = function["body"]
    private = re.search(
        r"\bstruct\s+[A-Za-z_]\w*\s*\*\s*([A-Za-z_]\w*)\s*=\s*"
        r"[A-Za-z_]\w*\s*\([^;]*\)\s*;", body, re.S)
    prelude: list[str] = []
    if private:
        private_name = private.group(1)
        body = body[:private.start()] + body[private.end():]
        body = re.sub(rf"\b{re.escape(private_name)}\s*->\s*reg\b",
                      "base", body)
        remaining_fields = sorted(set(re.findall(
            rf"\b{re.escape(private_name)}\s*->\s*([A-Za-z_]\w*)", body)))
        if remaining_fields:
            return None, (f"{name}: unbound private fields on {private_name}: "
                          + ", ".join(remaining_fields))
        if re.search(rf"\b{re.escape(private_name)}\b", body):
            return None, f"{name}: unbound private value {private_name}"
        params = _parameter_names(function["params"])
        if not params:
            return None, f"{name}: cannot identify callback state parameter"
        prelude = [
            f"\tstruct {priv} *g = container_of({params[0]}, struct {priv}, hw);",
            "\tvoid __iomem *base = g->base;",
        ]
    # A source callback may legitimately access framework-owned request state,
    # but no driver-private aggregate may survive the explicit rebind above.
    residual = re.findall(r"\b([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)", body)
    allowed_roots = {"req"}
    if any(root not in allowed_roots for root, _field in residual):
        roots = sorted({root for root, _field in residual
                        if root not in allowed_roots})
        return None, f"{name}: residual aggregate roots: {', '.join(roots)}"
    body = body.strip("\n")
    lines = [function["header"], "{", *prelude]
    if body.strip():
        lines.append(body)
    lines.append("}")
    return "\n".join(lines), None


def _lower_clock_source_callback(source: str, name: str, priv: str) -> str | None:
    code, _reason = _lower_clock_source_callback_analysis(source, name, priv)
    return code


def _analyze_clock_source_model(facts, priv: str) -> dict:
    result = {
        "supported": False,
        "reasons": [],
        "groups": {},
        "variants": [],
        "callbacks": {},
        "helpers": [],
    }
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not source_path.endswith(".c") or not os.path.isfile(source_path):
        result["reasons"].append("versioned C source is unavailable")
        return result
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    groups = _parse_clk_ops_groups(source)
    result["groups"] = groups
    if not groups:
        result["reasons"].append("no concrete struct clk_ops instances found")
        return result
    functions = {function for fields in groups.values() for function in fields.values()}
    lowered: dict[str, str] = {}
    for function in sorted(functions):
        code, reason = _lower_clock_source_callback_analysis(
            source, function, priv)
        if code is None:
            result["reasons"].append(reason or f"cannot lower {function}")
            continue
        lowered[function] = code
    if result["reasons"]:
        return result

    # Retain pure source helpers called by the callbacks (for example PLL rate
    # calculation).  Only helpers without aggregate member access are accepted.
    known_calls = {
        "BIT", "GENMASK", "FIELD_GET", "FIELD_PREP", "readl", "writel",
        "readb", "writeb", "readw", "writew", "container_of",
        "if", "for", "while", "switch", "sizeof", "return",
    }
    helper_names: set[str] = set()
    for code in lowered.values():
        for called in re.findall(r"\b([A-Za-z_]\w*)\s*\(", code):
            if called not in functions and called not in known_calls:
                helper = _source_function(source, called)
                if helper is not None:
                    helper_names.add(called)
    helpers: list[str] = []
    for helper_name in sorted(helper_names):
        helper = _source_function(source, helper_name)
        if helper is None or "->" in helper["body"]:
            result["reasons"].append(
                f"pure helper has unbound aggregate state: {helper_name}")
            continue
        helpers.append(helper["text"])
    if result["reasons"]:
        return result

    variants: list[tuple[str, str]] = []
    for compatible, init_function in re.findall(
            r"CLK_OF_DECLARE\s*\(\s*[A-Za-z_]\w*\s*,\s*"
            r'"([^\"]+)"\s*,\s*([A-Za-z_]\w*)\s*\)', source):
        init = _source_function(source, init_function)
        if init is None:
            continue
        candidates = [group for group in groups
                      if re.search(rf"&\s*{re.escape(group)}\b", init["body"])]
        if len(candidates) == 1:
            variants.append((compatible, candidates[0]))
    if variants and {group for _compatible, group in variants} != set(groups):
        missing = sorted(set(groups) - {group for _compatible, group in variants})
        result["reasons"].append(
            "clock variants do not cover ops groups: " + ", ".join(missing))
        return result
    result.update({
        "supported": True,
        "callbacks": lowered,
        "helpers": helpers,
        "variants": variants,
    })
    return result


def analyze_clock_source_model(facts, priv: str) -> dict:
    """Serializable acceptance/rejection evidence for clock source lowering."""
    result = _analyze_clock_source_model(facts, priv)
    return {
        "supported": result["supported"],
        "reasons": list(result["reasons"]),
        "groups": result["groups"],
        "variants": list(result["variants"]),
        "lowered_callbacks": sorted(result["callbacks"]),
        "pure_helpers": len(result["helpers"]),
    }


def _clock_source_model(facts, priv: str) -> dict | None:
    result = _analyze_clock_source_model(facts, priv)
    if not result["supported"]:
        return None
    return {
        "groups": result["groups"],
        "callbacks": result["callbacks"],
        "helpers": result["helpers"],
        "variants": result["variants"],
    }


def _source_object_macros(facts) -> dict[str, str]:
    """Return target-source object macros, including symbolic expressions."""
    source_path = getattr(facts, "source", None) if facts is not None else None
    if not source_path or not source_path.endswith(".c") or not os.path.isfile(source_path):
        return {}
    source = open(source_path, "r", encoding="utf-8", errors="replace").read()
    macros: dict[str, str] = {}
    for match in re.finditer(
            r"^\s*#\s*define\s+([A-Za-z_]\w*)[ \t]+([^\n\\]+?)\s*$",
            source, flags=re.M):
        name, value = match.group(1), match.group(2).strip()
        if value:
            macros[name] = value
    return macros


def _lower_irq_source_callback(source: str, name: str, table_field: str,
                               priv: str,
                               gpio_member: str = "gc") -> str | None:
    """Conservatively rebind generic-IRQ private state to generated state."""
    if not (table_field.startswith("irq_chip.")
            or table_field == "irq_handler.handler"):
        return None
    function = _source_function(source, name)
    if function is None:
        return None
    body = function["body"]
    prelude: list[str]
    private_name = None

    if table_field.startswith("irq_chip."):
        generic = re.search(
            r"\bstruct\s+irq_chip_generic\s*\*\s*([A-Za-z_]\w*)\s*=\s*"
            r"irq_data_get_irq_chip_data\s*\([^;]+\)\s*;", body, re.S)
        if generic is None:
            return None
        generic_name = generic.group(1)
        private = re.search(
            rf"\bstruct\s+[A-Za-z_]\w*\s*\*\s*([A-Za-z_]\w*)\s*=\s*"
            rf"{re.escape(generic_name)}\s*->\s*private\s*;", body, re.S)
        if private is None:
            return None
        private_name = private.group(1)
        spans = sorted(
            [(generic.start(), generic.end()), (private.start(), private.end())],
            reverse=True)
        for start, end in spans:
            body = body[:start] + body[end:]
        prelude = [
            "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
            f"\tstruct {priv} *g = gpiochip_get_data(gc);",
            "\tvoid __iomem *base = g->base;",
        ]
    else:
        private = re.search(
            r"\bstruct\s+[A-Za-z_]\w*\s*\*\s*([A-Za-z_]\w*)\s*=\s*"
            r"data\s*;", body, re.S)
        if private is None:
            return None
        private_name = private.group(1)
        body = body[:private.start()] + body[private.end():]
        prelude = [
            f"\tstruct {priv} *g = data;",
            "\t(void)irq;",
            "\tvoid __iomem *base = g->base;",
        ]

    body = re.sub(
        rf"\b{re.escape(private_name)}\s*->\s*[A-Za-z_]\w*base\b",
        "base", body)
    body = re.sub(
        rf"\b{re.escape(private_name)}\s*->\s*id\b",
        f"g->{gpio_member}.irq.domain", body)
    if re.search(rf"\b{re.escape(private_name)}\b", body):
        return None
    residual = re.findall(r"\b([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)", body)
    if any(root not in {"d", "g"} for root, _field in residual):
        return None
    lines = [function["header"], "{", *prelude]
    if body.strip():
        lines.append(body.strip("\n"))
    lines.append("}")
    return "\n".join(lines)


def _normalize_expr(expr, state_prefix: str | None = None,
                    safe_function_calls: set[str] | None = None):
    if not isinstance(expr, dict):
        return expr, False
    out = copy.deepcopy(expr)
    if "Var" in out:
        out["Var"], changed = _normalize_text(
            out["Var"], safe_function_calls)
        out["Var"] = _bind_state_text(out["Var"], state_prefix)
        return out, changed
    changed = False
    if "BinOp" in out:
        out["BinOp"]["left"], a = _normalize_expr(
            out["BinOp"].get("left"), state_prefix, safe_function_calls)
        out["BinOp"]["right"], b = _normalize_expr(
            out["BinOp"].get("right"), state_prefix, safe_function_calls)
        changed = a or b
    elif "Ite" in out:
        out["Ite"]["guard"], a = _normalize_expr(
            out["Ite"].get("guard"), state_prefix, safe_function_calls)
        out["Ite"]["then"], b = _normalize_expr(
            out["Ite"].get("then"), state_prefix, safe_function_calls)
        out["Ite"]["else"], c = _normalize_expr(
            out["Ite"].get("else"), state_prefix, safe_function_calls)
        changed = a or b or c
    elif "Bits" in out:
        out["Bits"]["expr"], changed = _normalize_expr(
            out["Bits"].get("expr"), state_prefix, safe_function_calls)
    return out, changed


def _normalize_ops(ops, state_prefix: str | None = None,
                   safe_function_calls: set[str] | None = None):
    out = copy.deepcopy(ops)
    changed = False
    for op in out:
        if "Cond" in op:
            op["Cond"]["guard"], c = _normalize_expr(
                op["Cond"].get("guard"), state_prefix, safe_function_calls)
            op["Cond"]["then_ops"], a = _normalize_ops(
                op["Cond"].get("then_ops", []), state_prefix,
                safe_function_calls)
            op["Cond"]["else_ops"], b = _normalize_ops(
                op["Cond"].get("else_ops") or [], state_prefix,
                safe_function_calls)
            changed |= a or b or c
        elif "Loop" in op:
            op["Loop"]["guard"], g = _normalize_expr(
                op["Loop"].get("guard"), state_prefix,
                safe_function_calls)
            op["Loop"]["count"], c = _normalize_expr(
                op["Loop"].get("count"), state_prefix, safe_function_calls)
            op["Loop"]["body"], a = _normalize_ops(
                op["Loop"].get("body", []), state_prefix,
                safe_function_calls)
            changed |= a or c or g
        elif "Seq" in op:
            op["Seq"]["ops"], a = _normalize_ops(
                op["Seq"].get("ops", []), state_prefix,
                safe_function_calls)
            changed |= a
        elif "Return" in op:
            op["Return"]["value"], a = _normalize_expr(
                op["Return"].get("value"), state_prefix,
                safe_function_calls)
            changed |= a
        else:
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if "StateRead" in op:
                body = op["StateRead"]
                if body.get("var"):
                    body["var"], a = _normalize_text(
                        body["var"], safe_function_calls)
                    body["var"] = _bind_state_text(body["var"], state_prefix)
                    changed |= a
                continue
            if "StateWrite" in op:
                body = op["StateWrite"]
                body["value"], a = _normalize_expr(
                    body.get("value"), state_prefix, safe_function_calls)
                changed |= a
                continue
            if not body:
                continue
            addr = body.get("addr", {})
            if "Computed" in addr:
                addr["Computed"], a = _normalize_expr(
                    addr["Computed"], state_prefix, safe_function_calls)
                changed |= a
            if "Read" in op and body.get("var"):
                body["var"], a = _normalize_text(
                    body["var"], safe_function_calls)
                body["var"] = _bind_state_text(body["var"], state_prefix)
                changed |= a
                if (body["var"] in {"true", "false"}
                        or re.fullmatch(r"[A-Z][A-Za-z0-9_]*",
                                        body["var"] or "")):
                    body["var"] = ""
                    changed = True
            key = "value" if "Write" in op else "transform" if "ReadModifyWrite" in op else None
            if key:
                body[key], a = _normalize_expr(
                    body.get(key), state_prefix, safe_function_calls)
                changed |= a
    return out, changed


def _bank_priv(priv: str) -> str:
    return f"{priv}_bank"


def _banked_gpio_callback(table_field: str) -> bool:
    return table_field.startswith(("gpio_chip.", "irq_chip.",
                                   "gpio_irq_chip."))


def _callback_signature(table_field: str, priv: str, banked_gpio: bool = False):
    bank = _bank_priv(priv)
    if banked_gpio and _banked_gpio_callback(table_field):
        gpio_pre = (f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
                    f"\tstruct {priv} *g = bank->parent;")
        irq_pre = (
            "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);\n"
            f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
            f"\tstruct {priv} *g = bank->parent;"
        )
        chained_pre = (
            "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);\n"
            f"\tstruct {bank} *bank = gpiochip_get_data(gc);\n"
            f"\tstruct {priv} *g = bank->parent;"
        )
    else:
        gpio_pre = f"\tstruct {priv} *g = gpiochip_get_data(gc);"
        irq_pre = (
            "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);\n"
            f"\tstruct {priv} *g = gpiochip_get_data(gc);"
        )
        chained_pre = (
            "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);\n"
            f"\tstruct {priv} *g = gpiochip_get_data(gc);"
        )
    direct_irq_pre = f"\tstruct {priv} *g = data;\n\t(void)irq;"
    pm_pre = f"\tstruct {priv} *g = dev_get_drvdata(dev);"
    clk_pre = f"\tstruct {priv} *g = container_of(hw, struct {priv}, hw);"
    ep_pre = f"\tstruct {priv} *g = ep->driver_data;"
    gadget_pre = f"\tstruct {priv} *g = container_of(gadget, struct {priv}, gadget);"
    hcd_pre = f"\tstruct {priv} *g = dev_get_drvdata(hcd->self.controller);"
    sdhci_pre = (
        "\tstruct sdhci_pltfm_host *pltfm_host = sdhci_priv(host);\n"
        f"\tstruct {priv} *g = sdhci_pltfm_priv(pltfm_host);")
    specs = {
        "irq_chip.irq_ack": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_mask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_unmask": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_enable": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_disable": ("void", "struct irq_data *d", irq_pre),
        "irq_chip.irq_set_type": ("int", "struct irq_data *d, unsigned int type", irq_pre),
        "gpio_irq_chip.parent_handler": ("void", "struct irq_desc *desc", chained_pre),
        "gpio_irq_chip.init_hw": ("int", "struct gpio_chip *gc", gpio_pre),
        "irq_handler.handler": (
            "irqreturn_t", "int irq, void *data", direct_irq_pre),
        "gpio_chip.request": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.free": ("void", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.get_direction": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.direction_input": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.direction_output": (
            "int", "struct gpio_chip *gc, unsigned int offset, int value", gpio_pre),
        "gpio_chip.get": ("int", "struct gpio_chip *gc, unsigned int offset", gpio_pre),
        "gpio_chip.get_multiple": (
            "int", "struct gpio_chip *gc, unsigned long *mask, unsigned long *bits",
            gpio_pre),
        "gpio_chip.set": (
            "int", "struct gpio_chip *gc, unsigned int offset, int value", gpio_pre),
        "gpio_chip.set_multiple": (
            "int", "struct gpio_chip *gc, unsigned long *mask, unsigned long *bits",
            gpio_pre),
        "gpio_chip.set_config": (
            "int", "struct gpio_chip *gc, unsigned int offset, unsigned long config", gpio_pre),
        "dev_pm_ops.suspend": ("int", "struct device *dev", pm_pre),
        "dev_pm_ops.resume": ("int", "struct device *dev", pm_pre),
        "clk_ops.prepare": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.unprepare": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.enable": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.disable": ("void", "struct clk_hw *hw", clk_pre),
        "clk_ops.is_enabled": ("int", "struct clk_hw *hw", clk_pre),
        "clk_ops.recalc_rate": (
            "unsigned long", "struct clk_hw *hw, unsigned long parent_rate", clk_pre),
        "clk_ops.determine_rate": (
            "int", "struct clk_hw *hw, struct clk_rate_request *req", clk_pre),
        "clk_ops.round_rate": (
            "long", "struct clk_hw *hw, unsigned long rate, unsigned long *parent_rate",
            clk_pre),
        "clk_ops.set_rate": (
            "int", "struct clk_hw *hw, unsigned long rate, unsigned long parent_rate",
            clk_pre),
        "sdhci_ops.read_l": (
            "u32", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.read_w": (
            "u16", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.read_b": (
            "u8", "struct sdhci_host *host, int reg", sdhci_pre),
        "sdhci_ops.write_l": (
            "void", "struct sdhci_host *host, u32 val, int reg", sdhci_pre),
        "sdhci_ops.write_w": (
            "void", "struct sdhci_host *host, u16 val, int reg", sdhci_pre),
        "sdhci_ops.write_b": (
            "void", "struct sdhci_host *host, u8 val, int reg", sdhci_pre),
        "usb_ep_ops.enable": (
            "int", "struct usb_ep *ep, const struct usb_endpoint_descriptor *desc",
            ep_pre),
        "usb_ep_ops.disable": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.alloc_request": (
            "struct usb_request *", "struct usb_ep *ep, gfp_t gfp_flags", ep_pre),
        "usb_ep_ops.free_request": (
            "void", "struct usb_ep *ep, struct usb_request *req", ep_pre),
        "usb_ep_ops.queue": (
            "int", "struct usb_ep *ep, struct usb_request *req, gfp_t gfp_flags",
            ep_pre),
        "usb_ep_ops.dequeue": (
            "int", "struct usb_ep *ep, struct usb_request *req", ep_pre),
        "usb_ep_ops.set_halt": (
            "int", "struct usb_ep *ep, int value", ep_pre),
        "usb_ep_ops.set_wedge": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.fifo_status": ("int", "struct usb_ep *ep", ep_pre),
        "usb_ep_ops.fifo_flush": ("void", "struct usb_ep *ep", ep_pre),
        "usb_gadget_ops.get_frame": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.wakeup": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.set_selfpowered": (
            "int", "struct usb_gadget *gadget, int is_selfpowered", gadget_pre),
        "usb_gadget_ops.vbus_session": (
            "int", "struct usb_gadget *gadget, int is_active", gadget_pre),
        "usb_gadget_ops.vbus_draw": (
            "int", "struct usb_gadget *gadget, unsigned int mA", gadget_pre),
        "usb_gadget_ops.pullup": (
            "int", "struct usb_gadget *gadget, int is_on", gadget_pre),
        "usb_gadget_ops.udc_start": (
            "int", "struct usb_gadget *gadget, struct usb_gadget_driver *driver",
            gadget_pre),
        "usb_gadget_ops.udc_stop": (
            "int", "struct usb_gadget *gadget", gadget_pre),
        "usb_gadget_ops.udc_set_speed": (
            "void", "struct usb_gadget *gadget, enum usb_device_speed speed",
            gadget_pre),
        "usb_gadget_ops.match_ep": (
            "struct usb_ep *",
            "struct usb_gadget *gadget, struct usb_endpoint_descriptor *desc, "
            "struct usb_ss_ep_comp_descriptor *comp_desc", gadget_pre),
        "hc_driver.irq": ("irqreturn_t", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.start": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.stop": ("void", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.urb_enqueue": (
            "int", "struct usb_hcd *hcd, struct urb *urb, gfp_t mem_flags", hcd_pre),
        "hc_driver.urb_dequeue": (
            "int", "struct usb_hcd *hcd, struct urb *urb, int status", hcd_pre),
        "hc_driver.endpoint_disable": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.endpoint_reset": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.get_frame_number": (
            "int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.hub_status_data": (
            "int", "struct usb_hcd *hcd, char *buf", hcd_pre),
        "hc_driver.hub_control": (
            "int", "struct usb_hcd *hcd, u16 typeReq, u16 wValue, u16 wIndex, "
            "char *buf, u16 wLength", hcd_pre),
        "hc_driver.clear_tt_buffer_complete": (
            "void", "struct usb_hcd *hcd, struct usb_host_endpoint *ep", hcd_pre),
        "hc_driver.bus_suspend": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.bus_resume": ("int", "struct usb_hcd *hcd", hcd_pre),
        "hc_driver.map_urb_for_dma": (
            "int", "struct usb_hcd *hcd, struct urb *urb, gfp_t mem_flags", hcd_pre),
        "hc_driver.unmap_urb_for_dma": (
            "void", "struct usb_hcd *hcd, struct urb *urb", hcd_pre),
        "hc_driver.free_dev": (
            "void", "struct usb_hcd *hcd, struct usb_device *udev", hcd_pre),
        "hc_driver.reset_device": (
            "int", "struct usb_hcd *hcd, struct usb_device *udev", hcd_pre),
    }
    return specs.get(table_field)


def _canonical_args(table_field: str):
    return {
        "irq_chip.irq_ack": [("d", "struct irq_data *")],
        "irq_chip.irq_mask": [("d", "struct irq_data *")],
        "irq_chip.irq_unmask": [("d", "struct irq_data *")],
        "irq_chip.irq_enable": [("d", "struct irq_data *")],
        "irq_chip.irq_disable": [("d", "struct irq_data *")],
        "irq_chip.irq_set_type": [("d", "struct irq_data *"), ("type", "unsigned int")],
        "gpio_irq_chip.parent_handler": [("desc", "struct irq_desc *")],
        "gpio_irq_chip.init_hw": [],
        "irq_handler.handler": [
            ("irq", "int"), ("data", "void *")],
        "gpio_chip.request": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.free": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.get_direction": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.direction_input": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.direction_output": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("value", "int")],
        "gpio_chip.get": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int")],
        "gpio_chip.get_multiple": [
            ("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
            ("bits", "unsigned long *")],
        "gpio_chip.set": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("value", "int")],
        "gpio_chip.set_multiple": [
            ("gc", "struct gpio_chip *"), ("mask", "unsigned long *"),
            ("bits", "unsigned long *")],
        "gpio_chip.set_config": [
            ("gc", "struct gpio_chip *"), ("offset", "unsigned int"),
            ("config", "unsigned long")],
        "dev_pm_ops.suspend": [("dev", "struct device *")],
        "dev_pm_ops.resume": [("dev", "struct device *")],
        "clk_ops.prepare": [("hw", "struct clk_hw *")],
        "clk_ops.unprepare": [("hw", "struct clk_hw *")],
        "clk_ops.enable": [("hw", "struct clk_hw *")],
        "clk_ops.disable": [("hw", "struct clk_hw *")],
        "clk_ops.is_enabled": [("hw", "struct clk_hw *")],
        "clk_ops.recalc_rate": [
            ("hw", "struct clk_hw *"), ("parent_rate", "unsigned long")],
        "clk_ops.determine_rate": [
            ("hw", "struct clk_hw *"), ("req", "struct clk_rate_request *")],
        "clk_ops.round_rate": [
            ("hw", "struct clk_hw *"), ("rate", "unsigned long"),
            ("parent_rate", "unsigned long *")],
        "clk_ops.set_rate": [
            ("hw", "struct clk_hw *"), ("rate", "unsigned long"),
            ("parent_rate", "unsigned long")],
        "sdhci_ops.read_l": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.read_w": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.read_b": [
            ("host", "struct sdhci_host *"), ("reg", "int")],
        "sdhci_ops.write_l": [
            ("host", "struct sdhci_host *"), ("val", "u32"),
            ("reg", "int")],
        "sdhci_ops.write_w": [
            ("host", "struct sdhci_host *"), ("val", "u16"),
            ("reg", "int")],
        "sdhci_ops.write_b": [
            ("host", "struct sdhci_host *"), ("val", "u8"),
            ("reg", "int")],
        "usb_ep_ops.enable": [
            ("ep", "struct usb_ep *"),
            ("desc", "const struct usb_endpoint_descriptor *")],
        "usb_ep_ops.disable": [("ep", "struct usb_ep *")],
        "usb_ep_ops.alloc_request": [
            ("ep", "struct usb_ep *"), ("gfp_flags", "gfp_t")],
        "usb_ep_ops.free_request": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *")],
        "usb_ep_ops.queue": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *"),
            ("gfp_flags", "gfp_t")],
        "usb_ep_ops.dequeue": [
            ("ep", "struct usb_ep *"), ("req", "struct usb_request *")],
        "usb_ep_ops.set_halt": [
            ("ep", "struct usb_ep *"), ("value", "int")],
        "usb_ep_ops.set_wedge": [("ep", "struct usb_ep *")],
        "usb_ep_ops.fifo_status": [("ep", "struct usb_ep *")],
        "usb_ep_ops.fifo_flush": [("ep", "struct usb_ep *")],
        "usb_gadget_ops.get_frame": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.wakeup": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.set_selfpowered": [
            ("gadget", "struct usb_gadget *"), ("is_selfpowered", "int")],
        "usb_gadget_ops.vbus_session": [
            ("gadget", "struct usb_gadget *"), ("is_active", "int")],
        "usb_gadget_ops.vbus_draw": [
            ("gadget", "struct usb_gadget *"), ("mA", "unsigned int")],
        "usb_gadget_ops.pullup": [
            ("gadget", "struct usb_gadget *"), ("is_on", "int")],
        "usb_gadget_ops.udc_start": [
            ("gadget", "struct usb_gadget *"),
            ("driver", "struct usb_gadget_driver *")],
        "usb_gadget_ops.udc_stop": [("gadget", "struct usb_gadget *")],
        "usb_gadget_ops.udc_set_speed": [
            ("gadget", "struct usb_gadget *"),
            ("speed", "enum usb_device_speed")],
        "usb_gadget_ops.match_ep": [
            ("gadget", "struct usb_gadget *"),
            ("desc", "struct usb_endpoint_descriptor *"),
            ("comp_desc", "struct usb_ss_ep_comp_descriptor *")],
        "hc_driver.irq": [("hcd", "struct usb_hcd *")],
        "hc_driver.start": [("hcd", "struct usb_hcd *")],
        "hc_driver.stop": [("hcd", "struct usb_hcd *")],
        "hc_driver.urb_enqueue": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("mem_flags", "gfp_t")],
        "hc_driver.urb_dequeue": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("status", "int")],
        "hc_driver.endpoint_disable": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.endpoint_reset": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.get_frame_number": [("hcd", "struct usb_hcd *")],
        "hc_driver.hub_status_data": [
            ("hcd", "struct usb_hcd *"), ("buf", "char *")],
        "hc_driver.hub_control": [
            ("hcd", "struct usb_hcd *"), ("typeReq", "u16"),
            ("wValue", "u16"), ("wIndex", "u16"), ("buf", "char *"),
            ("wLength", "u16")],
        "hc_driver.clear_tt_buffer_complete": [
            ("hcd", "struct usb_hcd *"),
            ("ep", "struct usb_host_endpoint *")],
        "hc_driver.bus_suspend": [("hcd", "struct usb_hcd *")],
        "hc_driver.bus_resume": [("hcd", "struct usb_hcd *")],
        "hc_driver.map_urb_for_dma": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *"),
            ("mem_flags", "gfp_t")],
        "hc_driver.unmap_urb_for_dma": [
            ("hcd", "struct usb_hcd *"), ("urb", "struct urb *")],
        "hc_driver.free_dev": [
            ("hcd", "struct usb_hcd *"), ("udev", "struct usb_device *")],
        "hc_driver.reset_device": [
            ("hcd", "struct usb_hcd *"), ("udev", "struct usb_device *")],
    }.get(table_field, [])


def _emit_callback(fn, module: dict, table_field: str, priv: str,
                   regs: dict[str, int], bind,
                   safe_function_calls: set[str] | None = None,
                   banked_gpio: bool = False,
                   ) -> tuple[str | None, str | None]:
    spec = _callback_signature(table_field, priv, banked_gpio)
    if spec is None:
        return None, f"{table_field}={fn.name}"
    state_owner = ("bank" if banked_gpio
                   and table_field.startswith("gpio_chip.") else "g")
    safe_ops, normalized = _normalize_ops(
        module["ops"], state_owner, safe_function_calls)
    if table_field == "gpio_chip.set_multiple":
        for op in walk_leaf_ops(safe_ops):
            body = op.get("ReadModifyWrite") or op.get("Write")
            if not body:
                continue
            key = "transform" if "ReadModifyWrite" in op else "value"
            body[key] = _replace_expr_var(body.get(key), "mask", "*mask")
            body[key] = _replace_expr_var(body.get(key), "bits", "*bits")
    ret, params, prelude = spec
    declared = {"base"}
    canonical_args = _canonical_args(table_field)
    declared.update(name for name, _ctype in canonical_args)
    declared.update({"d", "gc", "offset", "type", "config"})
    lines = [f"static {ret} {fn.name}({params})", "{", prelude]
    for param, (canonical, ctype) in zip(
            fn.signature.params, canonical_args):
        if param.name != canonical:
            lines.append(f"\t{ctype} {param.name} = {canonical};")
            declared.add(param.name)
    source_params = {param.name for param in fn.signature.params}
    if (table_field == "hc_driver.irq" and "int_status" in source_params
            and "int_status" not in declared):
        lines.append(
            "\tu32 int_status = readw(g->base + HPI_STATUS * g->hpi_regstep);")
        declared.add("int_status")
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    lines.append("\tvoid __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1,
                    word_type="u32", state_expr=state_owner)
    if body:
        lines.append(body.replace("    ", "\t"))
    has_return = any("Return" in op for op in walk_leaf_ops(safe_ops))
    has_output = any("OutputWrite" in op for op in walk_leaf_ops(safe_ops))
    if table_field == "gpio_chip.get_multiple" and not has_output:
        result = _last_read_var(module) or "0"
        lines.append(f"\t*bits = (*bits & ~*mask) | ({result} & *mask);")
        lines.append("\treturn 0;")
    elif has_return:
        pass
    elif ret == "irqreturn_t":
        lines.append("\treturn IRQ_HANDLED;")
    elif "*" in ret:
        lines.append("\treturn NULL;")
    elif ret in {"int", "long", "unsigned long"}:
        result = _last_read_var(module) if table_field in {
            "gpio_chip.get", "gpio_chip.get_direction",
            "clk_ops.is_enabled", "clk_ops.recalc_rate",
            "usb_ep_ops.fifo_status", "usb_gadget_ops.get_frame",
            "hc_driver.get_frame_number", "hc_driver.hub_status_data"} else None
        lines.append(f"\treturn {result or 0};")
    lines.extend(["}", ""])
    problem = f"{fn.name} source-private expressions normalized" if normalized else None
    if table_field in {
            "clk_ops.recalc_rate", "clk_ops.determine_rate", "clk_ops.round_rate"}:
        problem = f"{fn.name} requires non-MMIO clock arithmetic"
    return "\n".join(lines), problem


def _emit_evidence_only_callback(fn, module: dict, priv: str,
                                 regs: dict[str, int], bind,
                                 safe_function_calls: set[str]) -> str:
    """Emit an unregistered function for an AST-bound unknown-role callback.

    This preserves the recovered operations for audit and cross-TU helpers,
    while deliberately avoiding any public callback table or lifecycle claim.
    """
    type_map = {
        "UInt": "u32", "LogicalIRQ": "unsigned int",
        "Bool": "bool", "Clock": "unsigned long",
        "MmioBase": "void __iomem *", "UIntPtr": "unsigned long *",
    }
    params = []
    aliases = []
    declared = {"base"}
    device_bound = False
    for param in fn.signature.params:
        if param.type == "DeviceState" and not device_bound:
            params.append(f"struct {priv} *g")
            declared.add("g")
            device_bound = True
            if param.name and param.name != "g":
                aliases.append(f"\tstruct {priv} *{param.name} = g;")
                declared.add(param.name)
            continue
        ctype = (f"struct {priv} *" if param.type == "DeviceState"
                 else type_map.get(param.type, "u32"))
        params.append(f"{ctype} {param.name}")
        declared.add(param.name)
    if not device_bound:
        params.insert(0, f"struct {priv} *g")
        declared.add("g")
    return_type = "void" if fn.signature.return_type == "Void" else "u32"
    safe_ops, _normalized = _normalize_ops(
        module.get("ops", []), "g", safe_function_calls)
    lines = [
        f"/* AST-bound evidence only: role unknown, not registered */",
        f"static {return_type} {fn.name}({', '.join(params)})", "{",
        *aliases,
    ]
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    if decls:
        lines.append(decls.replace("    ", "\t"))
    lines.append("\tvoid __iomem *base = g->base;")
    body = ops_to_c(
        safe_ops, bind, "base", regs, indent=1,
        word_type="u32", state_expr="g")
    if body:
        lines.append(body.replace("    ", "\t"))
    if (return_type != "void"
            and not any("Return" in op for op in walk_leaf_ops(safe_ops))):
        lines.append(f"\treturn {_last_read_var(module) or 0};")
    lines.extend(["}", ""])
    return "\n".join(lines)


def _emit_banked_irq_source_callback(
        fn, module: dict, table_field: str, priv: str, regs: dict[str, int],
        source: str, safe_function_calls: set[str]) -> str | None:
    """Lower standard irq_chip bit operations after checking their source."""
    if table_field not in {
            "irq_chip.irq_ack", "irq_chip.irq_mask", "irq_chip.irq_unmask",
            "irq_chip.irq_enable", "irq_chip.irq_disable",
            "irq_chip.irq_set_type"}:
        return None
    function = _source_function(source, fn.name)
    if function is None:
        return None
    body = function["body"]
    safe_ops, _ = _normalize_ops(
        module.get("ops", []), "g", safe_function_calls)
    leaves = list(walk_leaf_ops(safe_ops))

    def addresses(kind: str) -> list[str]:
        result = []
        for op in leaves:
            item = op.get(kind)
            if item:
                result.append(addr_to_c(item["addr"], "base", regs, "g"))
        return result

    reads = addresses("Read")
    writes = addresses("Write") + addresses("ReadModifyWrite")
    bank = _bank_priv(priv)
    prelude = [
        f"static {'int' if table_field.endswith('set_type') else 'void'} "
        f"{fn.name}(struct irq_data *d"
        f"{', unsigned int type' if table_field.endswith('set_type') else ''})",
        "{", "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {bank} *bank = gpiochip_get_data(gc);",
        f"\tstruct {priv} *g = bank->parent;", "\tvoid __iomem *base = g->base;",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\tu32 val;",
    ]
    field = table_field.rsplit(".", 1)[1]
    if field == "irq_ack":
        if (len(writes) != 1
                or not re.search(r"BIT\s*\(\s*irqd_to_hwirq\s*\(", body)):
            return None
        lines = prelude + ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\twritel(bit, {writes[0]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
    elif field in {"irq_mask", "irq_unmask"}:
        operator = "|" if field == "irq_mask" else "& ~"
        helper = "gpiochip_disable_irq" if field == "irq_mask" else "gpiochip_enable_irq"
        proof = r"\|\s*BIT\s*\(" if field == "irq_mask" else r"&\s*~\s*BIT\s*\("
        if len(reads) != 1 or len(writes) != 1 or not re.search(proof, body):
            return None
        lines = prelude
        if field == "irq_unmask":
            lines.append("\tgpiochip_enable_irq(gc, irqd_to_hwirq(d));")
        lines += ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                  f"\tval = readl({reads[0]});",
                  f"\tval = val {operator}bit;", f"\twritel(val, {writes[0]});",
                  "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
        if field == "irq_mask":
            lines.append("\tgpiochip_disable_irq(gc, irqd_to_hwirq(d));")
    elif field in {"irq_enable", "irq_disable"}:
        if len(reads) != 2 or len(writes) != 2:
            return None
        first = "|" if field == "irq_enable" else "|"
        second = "& ~" if field == "irq_enable" else "& ~"
        # Source ordering distinguishes enable (INTEN set, INTMASK clear)
        # from disable (INTMASK set, INTEN clear); both use the same two
        # bit transforms in their observed order.
        if field == "irq_disable":
            first, second = "|", "& ~"
        if not (re.search(r"\|\s*BIT\s*\(", body)
                and re.search(r"&\s*~\s*BIT\s*\(", body)):
            return None
        lines = prelude + ["\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\tval = readl({reads[0]});",
                           f"\tval = val {first}bit;",
                           f"\twritel(val, {writes[0]});",
                           f"\tval = readl({reads[1]});",
                           f"\tval = val {second}bit;",
                           f"\twritel(val, {writes[1]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);"]
    else:
        required = {
            "IRQ_TYPE_EDGE_BOTH", "IRQ_TYPE_EDGE_RISING",
            "IRQ_TYPE_EDGE_FALLING", "IRQ_TYPE_LEVEL_HIGH",
            "IRQ_TYPE_LEVEL_LOW",
        }
        if len(reads) < 2 or len(writes) < 2 or any(
                not re.search(rf"case\s+{name}\s*:", body)
                for name in required):
            return None
        lines = prelude + ["\tu32 level;", "\tu32 polarity;",
                           "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
                           f"\tlevel = readl({reads[0]});",
                           f"\tpolarity = readl({reads[1]});", "\tswitch (type) {",
                           "\tcase IRQ_TYPE_EDGE_BOTH:", "\t\tlevel |= bit;",
                           "\t\tif (gc->get(gc, irqd_to_hwirq(d)))",
                           "\t\t\tpolarity &= ~bit;", "\t\telse",
                           "\t\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_EDGE_RISING:", "\t\tlevel |= bit;",
                           "\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_EDGE_FALLING:", "\t\tlevel |= bit;",
                           "\t\tpolarity &= ~bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_LEVEL_HIGH:", "\t\tlevel &= ~bit;",
                           "\t\tpolarity |= bit;", "\t\tbreak;",
                           "\tcase IRQ_TYPE_LEVEL_LOW:", "\t\tlevel &= ~bit;",
                           "\t\tpolarity &= ~bit;", "\t\tbreak;", "\tdefault:",
                           "\t\traw_spin_unlock_irqrestore(&g->irq_lock, flags);",
                           "\t\treturn -EINVAL;", "\t}",
                           f"\twritel(level, {writes[0]});",
                           f"\twritel(polarity, {writes[1]});",
                           "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);",
                           "\tif (type & IRQ_TYPE_LEVEL_MASK)",
                           "\t\tirq_set_handler_locked(d, handle_level_irq);",
                           "\telse", "\t\tirq_set_handler_locked(d, handle_edge_irq);",
                           "\treturn 0;"]
    lines += ["}", ""]
    return "\n".join(lines)


def _emit_usb_callback_tables(device_name: str,
                              callbacks: dict[str, str]) -> list[str]:
    """Emit correctly typed USB ops tables without claiming lifecycle glue."""
    cid = _cid(device_name)
    by_field = {field: fn for fn, field in callbacks.items()}
    out: list[str] = []

    ep_fields = (
        "enable", "disable", "alloc_request", "free_request", "queue",
        "dequeue", "set_halt", "set_wedge", "fifo_status", "fifo_flush")
    if any(f"usb_ep_ops.{field}" in by_field for field in ep_fields):
        out.append(
            f"static const struct usb_ep_ops {cid}_ep_ops __maybe_unused = {{")
        for field in ep_fields:
            fn = by_field.get(f"usb_ep_ops.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]

    gadget_fields = (
        "get_frame", "wakeup", "set_selfpowered", "vbus_session",
        "vbus_draw", "pullup", "udc_start", "udc_stop", "udc_set_speed",
        "match_ep")
    if any(f"usb_gadget_ops.{field}" in by_field for field in gadget_fields):
        out.append(
            f"static const struct usb_gadget_ops {cid}_gadget_ops __maybe_unused = {{")
        for field in gadget_fields:
            fn = by_field.get(f"usb_gadget_ops.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]

    hcd_fields = (
        "irq", "start", "stop", "urb_enqueue", "urb_dequeue",
        "endpoint_disable", "endpoint_reset", "get_frame_number",
        "hub_status_data", "hub_control", "clear_tt_buffer_complete",
        "bus_suspend", "bus_resume", "map_urb_for_dma",
        "unmap_urb_for_dma", "free_dev", "reset_device")
    if any(f"hc_driver.{field}" in by_field for field in hcd_fields):
        out += [
            f"static const struct hc_driver {cid}_hc_driver __maybe_unused = {{",
            f'\t.description = "{device_name}",',
            f'\t.product_desc = "reharness {device_name}",',
            "\t.hcd_priv_size = 0,",
            "\t.flags = HCD_MEMORY | HCD_USB2,",
        ]
        for field in hcd_fields:
            fn = by_field.get(f"hc_driver.{field}")
            if fn:
                out.append(f"\t.{field} = {fn},")
        out += ["};", ""]
    return out


def _probe_ops(device_spec, formal: dict):
    probe = next((f for f in device_spec.functions if f.role == "probe"), None)
    if probe is None:
        return None, None
    module = next((m for m in formal["modules"] if m["name"] == probe.ris_ref), None)
    return probe, module


def _emit_probe_body(module, regs, bind, indent="\t",
                     safe_function_calls: set[str] | None = None) -> list[str]:
    if module is None:
        return []
    safe_ops, _ = _normalize_ops(
        _bound_resource_probe_ops(module["ops"]), "g", safe_function_calls)
    declared: set[str] = {"base", "ret", "g", "pdev"}
    decls = local_decls(safe_ops, declared, regs, indent=1, ctype="u32")
    out = []
    if decls:
        out.extend(decls.replace("    ", indent).splitlines())
    out.append(f"{indent}void __iomem *base = g->base;")
    body = ops_to_c(safe_ops, bind, "base", regs, indent=1,
                    word_type="u32", state_expr="g")
    if body:
        out.extend(body.replace("    ", indent).splitlines())
    return out


def _pci_ids(device_spec, facts) -> tuple[int, int] | None:
    if device_spec.name == "edu":
        return 0x1234, 0x11E8
    source = getattr(facts, "source", None) if facts is not None else None
    if source and os.path.isfile(source):
        text = open(source, "r", encoding="utf-8", errors="replace").read()
        token = r"(?:0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*)"
        m = re.search(rf"PCI_DEVICE\s*\(\s*({token})\s*,\s*"
                      rf"({token})\s*\)", text)
        if m:
            values = []
            constants = getattr(facts, "constants", {}) if facts else {}
            macros = _source_object_macros(facts)
            for raw in m.groups():
                if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", raw):
                    values.append(int(raw, 0))
                elif raw in constants and isinstance(constants[raw], int):
                    values.append(constants[raw])
                elif raw in macros and re.fullmatch(
                        r"\(?\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)?",
                        macros[raw]):
                    values.append(int(re.sub(r"[()\s]", "", macros[raw]), 0))
                else:
                    return None
            return values[0], values[1]
    return None


def _source_gpio_model(facts) -> dict | None:
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


def _match_data_state_initializers(facts, device_spec) -> dict[str, str]:
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


def _source_generic_irq_model(facts) -> dict | None:
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


def _banked_irq_status_model(facts) -> dict | None:
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


def _emit_banked_irq_handler(cid: str, priv: str, model: dict) -> list[str]:
    bank = _bank_priv(priv)
    return [
        f"static void {cid}_banked_irq_handler(struct irq_desc *desc)", "{",
        "\tstruct gpio_chip *gc = irq_desc_get_handler_data(desc);",
        f"\tstruct {bank} *bank = gpiochip_get_data(gc);",
        f"\tstruct {priv} *g = bank->parent;",
        "\tstruct irq_chip *chip = irq_desc_get_chip(desc);",
        "\tunsigned long pending;", "\tunsigned int hwirq;",
        f"\tpending = readl(g->base + {model['expr']});",
        "\tchained_irq_enter(chip, desc);",
        "\tfor_each_set_bit(hwirq, &pending, gc->ngpio)",
        "\t\tgeneric_handle_domain_irq(gc->irq.domain, hwirq);",
        "\tchained_irq_exit(chip, desc);", "}", "",
    ]


def _emit_source_generic_irq_callbacks(cid: str, priv: str,
                                       model: dict) -> list[str]:
    mask = model["mask_reg"]
    eoi = model["eoi_reg"]
    return [
        f"static void {cid}_irq_mask(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        "\tg->irq_mask_cache &= ~bit;",
        f"\twritel(g->irq_mask_cache, g->base + {mask});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
        f"static void {cid}_irq_unmask(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        "\tg->irq_mask_cache |= bit;",
        f"\twritel(g->irq_mask_cache, g->base + {mask});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
        f"static void {cid}_irq_eoi(struct irq_data *d)", "{",
        "\tstruct gpio_chip *gc = irq_data_get_irq_chip_data(d);",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(irqd_to_hwirq(d));",
        "\traw_spin_lock_irqsave(&g->irq_lock, flags);",
        f"\twritel(bit, g->base + {eoi});",
        "\traw_spin_unlock_irqrestore(&g->irq_lock, flags);", "}", "",
    ]


def _emit_source_gpio_callbacks(cid: str, priv: str, model: dict) -> list[str]:
    fields = model["fields"]
    dat = fields["dat"]
    set_reg = fields.get("set", dat)
    dirout = fields.get("dirout")
    if not dirout:
        return []
    return [
        f"static int {cid}_gpio_request(struct gpio_chip *gc, unsigned int line)",
        "{", "\treturn line < gc->ngpio ? 0 : -EINVAL;", "}", "",
        f"static int {cid}_gpio_get(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        f"\treturn !!(readl({dat}) & BIT(line));", "}", "",
        f"static int {cid}_gpio_get_multiple(struct gpio_chip *gc,",
        "\t\t\t\t unsigned long *mask, unsigned long *bits)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\t*bits &= ~*mask;", f"\t*bits |= readl({dat}) & *mask;",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_set(struct gpio_chip *gc, unsigned int line, int value)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\tu32 bit = BIT(line);",
        "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tif (value)", "\t\tg->gpio_data |= bit;", "\telse",
        "\t\tg->gpio_data &= ~bit;", f"\twritel(g->gpio_data, {set_reg});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_set_multiple(struct gpio_chip *gc,",
        "\t\t\t\t unsigned long *mask, unsigned long *bits)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_data &= ~*mask;", "\tg->gpio_data |= *bits & *mask;",
        f"\twritel(g->gpio_data, {set_reg});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);",
        "\treturn 0;", "}", "",
        f"static int {cid}_gpio_get_direction(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        f"\treturn readl({dirout}) & BIT(line) ?",
        "\t\tGPIO_LINE_DIRECTION_OUT : GPIO_LINE_DIRECTION_IN;", "}", "",
        f"static int {cid}_gpio_direction_input(struct gpio_chip *gc, unsigned int line)",
        "{", f"\tstruct {priv} *g = gpiochip_get_data(gc);",
        "\tunsigned long flags;", "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_dir &= ~BIT(line);", f"\twritel(g->gpio_dir, {dirout});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);", "\treturn 0;", "}", "",
        f"static int {cid}_gpio_direction_output(struct gpio_chip *gc,",
        "\t\t\t\t    unsigned int line, int value)", "{",
        f"\tstruct {priv} *g = gpiochip_get_data(gc);", "\tunsigned long flags;",
        f"\t{cid}_gpio_set(gc, line, value);",
        "\traw_spin_lock_irqsave(&g->gpio_lock, flags);",
        "\tg->gpio_dir |= BIT(line);", f"\twritel(g->gpio_dir, {dirout});",
        "\traw_spin_unlock_irqrestore(&g->gpio_lock, flags);", "\treturn 0;", "}", "",
    ]


def _balanced_initializer_blocks(text: str, struct_name: str):
    pattern = re.compile(
        rf"\bstruct\s+{re.escape(struct_name)}\s+([A-Za-z_]\w*)\s*=\s*\{{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield match.group(1), text[start + 1:index]
                    break


def _initializer_expr(body: str, field: str) -> str | None:
    match = re.search(
        rf"\.\s*{re.escape(field)}\s*=\s*(.+?)"
        rf"(?=,\s*\.\s*[A-Za-z_]\w*\s*=|,?\s*$)", body, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def _sdhci_source_model(formal: dict, facts) -> dict | None:
    source = getattr(facts, "source", None) if facts is not None else None
    source = source or formal.get("metadata", {}).get("source")
    if not source or not os.path.isfile(source):
        return None
    text = open(source, encoding="utf-8", errors="replace").read()
    pdata = []
    for name, body in _balanced_initializer_blocks(text, "sdhci_pltfm_data"):
        pdata.append({
            "source_name": name,
            "quirks": _initializer_expr(body, "quirks"),
            "quirks2": _initializer_expr(body, "quirks2"),
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


def _emit_sdhci_platform(formal, device_spec, facts, priv,
                         callbacks: dict[str, str], callback_code: list[str]
                         ) -> str | None:
    model = _sdhci_source_model(formal, facts)
    if model is None:
        return None
    cid = _cid(device_spec.name)
    by_field = {field: fn for fn, field in callbacks.items()}
    delegates = {
        f"sdhci_ops.{item['field']}": item["callee"]
        for item in model["delegates"] if item.get("field") and item.get("callee")}
    has_private_ops = any(
        field.startswith("sdhci_ops.") for field in by_field) or bool(delegates)
    L = list(callback_code)
    if has_private_ops:
        L += [f"static const struct sdhci_ops {cid}_ops = {{"]
        for field in ("read_l", "read_w", "read_b", "write_l", "write_w",
                      "write_b", "set_clock", "set_bus_width", "reset",
                      "set_uhs_signaling"):
            table = f"sdhci_ops.{field}"
            function = by_field.get(table) or delegates.get(table)
            if function:
                L.append(f"\t.{field} = {function},")
        L += ["};", ""]
    pdata_names = {}
    for index, pdata in enumerate(model["pdata"]):
        name = f"{cid}_pdata_{index}"
        pdata_names[pdata["source_name"]] = name
        L += [f"static const struct sdhci_pltfm_data {name} = {{"]
        if pdata["has_ops"] and has_private_ops:
            L.append(f"\t.ops = &{cid}_ops,")
        if pdata["quirks"]:
            L.append(f"\t.quirks = {pdata['quirks']},")
        if pdata["quirks2"]:
            L.append(f"\t.quirks2 = {pdata['quirks2']},")
        L += ["};", ""]
    default_pdata = next(iter(pdata_names.values()))
    L += [f"static int {cid}_probe(struct platform_device *pdev)", "{",
          "\tconst struct sdhci_pltfm_data *pdata;",
          "\tstruct sdhci_pltfm_host *pltfm_host;",
          "\tstruct sdhci_host *host;", f"\tstruct {priv} *g;", "\tint ret;",
          "", "\tpdata = device_get_match_data(&pdev->dev);",
          f"\tif (!pdata)\n\t\tpdata = &{default_pdata};",
          f"\thost = sdhci_pltfm_init(pdev, pdata, sizeof(struct {priv}));",
          "\tif (IS_ERR(host))", "\t\treturn PTR_ERR(host);",
          "\tpltfm_host = sdhci_priv(host);",
          "\tg = sdhci_pltfm_priv(pltfm_host);",
          "\tg->dev = &pdev->dev;", "\tg->host = host;",
          "\tg->base = host->ioaddr;"]
    if model["clock"] == "optional":
        L += ["\tpltfm_host->clk = devm_clk_get_optional_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(pltfm_host->clk))",
              "\t\treturn PTR_ERR(pltfm_host->clk);"]
    elif model["clock"] == "required":
        L += ["\tpltfm_host->clk = devm_clk_get_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(pltfm_host->clk))",
              "\t\treturn PTR_ERR(pltfm_host->clk);"]
    if model["mmc_of_parse"]:
        L += ["\tret = mmc_of_parse(host->mmc);", "\tif (ret)", "\t\treturn ret;"]
    L += ["\tret = sdhci_add_host(host);", "\tif (ret)", "\t\treturn ret;",
          "\treturn 0;", "}", "",
          f"static void {cid}_remove(struct platform_device *pdev)", "{",
          "\tsdhci_pltfm_remove(pdev);", "}", "",
          f"static const struct of_device_id {cid}_of_match[] = {{"]
    if model["matches"]:
        for match in model["matches"]:
            pdata = pdata_names.get(match["pdata"], default_pdata)
            L.append(f'\t{{ .compatible = "{match["compatible"]}", '
                     f'.data = &{pdata} }},')
    else:
        L.append(f'\t{{ .compatible = "reharness,{device_spec.name}" }},')
    L += ["\t{ }", "};", f"MODULE_DEVICE_TABLE(of, {cid}_of_match);", "",
          f"static struct platform_driver {cid}_driver = {{",
          f"\t.probe = {cid}_probe,", f"\t.remove = {cid}_remove,",
          "\t.driver = {", f'\t\t.name = "{device_spec.name}",',
          f"\t\t.of_match_table = {cid}_of_match,"]
    if model["pm"]:
        L.append("\t\t.pm = &sdhci_pltfm_pmops,")
    L += ["\t},", "};", f"module_platform_driver({cid}_driver);"]
    return "\n".join(L)


def _emit_platform(formal, device_spec, bind, facts, priv, regs,
                   callbacks: dict[str, str], callback_code: list[str],
                   unsupported: list[str], clock_model: dict | None = None) -> str:
    dev = device_spec.name
    safe_function_calls = set(_portable_function_macros(formal))
    cid = _cid(dev)
    _, probe_module = _probe_ops(device_spec, formal)
    if (device_spec.cls in {"ahci", "virtio_mmio"}
            or (device_spec.cls == "sdhci"
                and not portable_sdhci_accessor_only(formal, device_spec))):
        probe_module = None
    by_field = {field: fn for fn, field in callbacks.items()}
    has_gpio = device_spec.cls == "gpio_controller" or any(
        f.startswith("gpio_chip.") for f in by_field)
    has_irq = any(f.startswith("irq_chip.") for f in by_field)
    has_clk = any(s.name == "clk" for s in device_spec.state)
    has_clk_ops = bool(clock_model) or any(
        f.startswith("clk_ops.") for f in by_field)
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    gpio_summaries = (summary_groups.get("gpio_generic", [])
                      if isinstance(summary_groups, dict) else [])
    gpio_variant = next((
        summary.get("variant_model") for summary in gpio_summaries
        if summary.get("variant_model")), None)
    gpio_bank = next((
        summary.get("bank_model") for summary in gpio_summaries
        if summary.get("bank_model")), None)
    pm_fields = {
        field.split(".", 1)[1]: fn for field, fn in by_field.items()
        if field.startswith("dev_pm_ops.")
    }

    L = callback_code[:] + _emit_usb_callback_tables(dev, callbacks)
    clock_table_names: dict[str, str] = {}
    if clock_model:
        for group, fields in clock_model["groups"].items():
            table_name = f"{cid}_{_cid(group)}"
            clock_table_names[group] = table_name
            L += [f"static const struct clk_ops {table_name} = {{"]
            for field in ("prepare", "unprepare", "enable", "disable",
                          "is_enabled", "recalc_rate", "determine_rate",
                          "round_rate", "set_rate"):
                function = fields.get(field)
                if function:
                    L.append(f"\t.{field} = {function},")
            L += ["};", ""]
    elif has_clk_ops:
        L += [f"static const struct clk_ops {cid}_clk_ops = {{"]
        for field in ("prepare", "unprepare", "enable", "disable",
                      "is_enabled", "recalc_rate", "determine_rate",
                      "round_rate", "set_rate"):
            fn = by_field.get(f"clk_ops.{field}")
            if fn:
                L.append(f"\t.{field} = {fn},")
        L += ["};", "", f"static const struct clk_init_data {cid}_clk_init = {{",
              f'\t.name = "{dev}",', f"\t.ops = &{cid}_clk_ops,",
              "\t.num_parents = 0,", "};", ""]
    if pm_fields:
        L += [f"static const struct dev_pm_ops {cid}_pm_ops = {{"]
        for field in ("suspend", "resume"):
            if field in pm_fields:
                L.append(f"\t.{field} = {pm_fields[field]},")
        L += ["};", ""]
    L += [f"static int {cid}_probe(struct platform_device *pdev)", "{",
          f"\tstruct {priv} *g;", "\tint ret;"]
    if clock_model:
        L.append("\tconst struct clk_ops *clock_ops;")
    if gpio_bank:
        L += [f"\tstruct {_bank_priv(priv)} *bank;",
              "\tunsigned int bank_index = 0;", "\tunsigned int irq_index;",
              "\tint parent_irq;"]
    L += ["\tg = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);",
          "\tif (!g)", "\t\treturn -ENOMEM;",
          "\tg->dev = &pdev->dev;"]
    mmio_resources = [resource for resource in device_spec.resources
                      if resource.type == "MmioResource"]
    for index, resource in enumerate(mmio_resources):
        field = resource.bind or "base"
        L += [
            f"\tg->{field} = devm_platform_ioremap_resource(pdev, {index});",
            f"\tif (IS_ERR(g->{field}))",
            f"\t\treturn PTR_ERR(g->{field});",
        ]
    if mmio_resources and mmio_resources[0].bind not in {None, "base"}:
        L.append(f"\tg->base = g->{mmio_resources[0].bind};")
    L.append("\tplatform_set_drvdata(pdev, g);")
    for field, initializer in sorted(
            _match_data_state_initializers(facts, device_spec).items()):
        L.append(f"\tg->{field} = {initializer};")
    array_states = [state for state in device_spec.state
                    if state.type == "UIntArray"]
    if gpio_bank and any(
            state.name == "nr_ports" for state in device_spec.state):
        L += [
            "\tg->nr_ports = device_get_child_node_count(&pdev->dev);",
            "\tif (!g->nr_ports)",
            "\t\treturn -ENODEV;",
            "\tg->banks = devm_kcalloc(&pdev->dev, g->nr_ports,",
            "\t\t\t\t   sizeof(*g->banks), GFP_KERNEL);",
            "\tif (!g->banks)",
            "\t\treturn -ENOMEM;",
        ]
    for state in array_states:
        L += [
            f"\tg->{state.name} = devm_kcalloc(&pdev->dev, g->nr_ports,",
            f"\t\t\t\t      sizeof(*g->{state.name}), GFP_KERNEL);",
            f"\tif (!g->{state.name})",
            "\t\treturn -ENOMEM;",
        ]
    if (gpio_bank and gpio_bank.get("property")
            and any(state.name == "ports_idx" for state in array_states)):
        L += [
            "\tdevice_for_each_child_node_scoped(&pdev->dev, child) {",
            f"\t\tif (fwnode_property_read_u32(child, \"{gpio_bank['property']}\",",
            "\t\t\t\t\t     &g->ports_idx[bank_index]))",
            "\t\t\treturn -EINVAL;",
        ]
        if gpio_bank.get("max_count"):
            L += [
                f"\t\tif (g->ports_idx[bank_index] >= {gpio_bank['max_count']})",
                "\t\t\treturn -EINVAL;",
            ]
        L += ["\t\tbank_index++;", "\t}"]
    if gpio_variant:
        L.append(
            f"\tg->{gpio_variant['state_field']} = "
            f"{gpio_variant['source_condition']};")
    if any(s.name == "ngpio" for s in device_spec.state):
        L.append("\tg->ngpio = 32;")
    if any(s.name == "skip_init" for s in device_spec.state):
        L.append('\tg->skip_init = device_property_read_bool(&pdev->dev, "reharness,skip-init");')
    if any(s.name == "hpi_regstep" for s in device_spec.state):
        L += [
            '\tif (device_property_read_u32(&pdev->dev, "hpi-regstep",',
            "\t\t\t     &g->hpi_regstep))",
            "\t\tg->hpi_regstep = 1;",
            "\tif (!g->hpi_regstep)",
            "\t\treturn -EINVAL;",
        ]
    if any(s.name == "sie_num" for s in device_spec.state):
        L += [
            '\tif (device_property_read_u32(&pdev->dev, "sie-number",',
            "\t\t\t     &g->sie_num))",
            "\t\tg->sie_num = 0;",
            "\tif (g->sie_num >= C67X00_SIES)",
            "\t\treturn -EINVAL;",
        ]
    if has_clk:
        L += ["\tg->clk = devm_clk_get_optional_enabled(&pdev->dev, NULL);",
              "\tif (IS_ERR(g->clk))", "\t\treturn PTR_ERR(g->clk);"]
    if clock_model:
        first_group = next(iter(clock_model["groups"]))
        first_table = clock_table_names[first_group]
        L += ["\tclock_ops = device_get_match_data(&pdev->dev);",
              f"\tif (!clock_ops)\n\t\tclock_ops = &{first_table};",
              "\tg->parent_data.index = 0;",
              "\tg->init.name = dev_name(&pdev->dev);",
              "\tg->init.ops = clock_ops;",
              "\tg->init.parent_data = &g->parent_data;",
              "\tg->init.num_parents = 1;",
              "\tg->hw.init = &g->init;",
              "\tret = devm_clk_hw_register(&pdev->dev, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
        L += ["\tret = devm_of_clk_add_hw_provider(&pdev->dev,",
              "\t\t\tof_clk_hw_simple_get, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
    elif has_clk_ops:
        L += [f"\tg->hw.init = &{cid}_clk_init;",
              "\tret = devm_clk_hw_register(&pdev->dev, &g->hw);",
              "\tif (ret)", "\t\treturn ret;"]
    L += _emit_probe_body(
        probe_module, regs, bind,
        safe_function_calls=safe_function_calls)
    if has_gpio and gpio_bank:
        if has_irq:
            L.append("\traw_spin_lock_init(&g->irq_lock);")
        ngpio_properties = gpio_bank.get("ngpio_properties") or []
        ngpio_default = int(gpio_bank.get("ngpio_default") or 32)
        selector = gpio_bank["selector"]

        def bank_addr(field: str) -> str:
            expr = gpio_bank["fields"][field]
            expr = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(selector)}(?![A-Za-z0-9_])",
                "bank->gpio_bank_index", expr)
            return f"g->base + ({expr})"

        L += ["\tbank_index = 0;",
              "\tdevice_for_each_child_node_scoped(&pdev->dev, child) {",
              "\t\tbank = &g->banks[bank_index];", "\t\tbank->parent = g;",
              "\t\tbank->gpio_bank_index = g->ports_idx[bank_index];",
              f"\t\tbank->gpio_sdata = readl({bank_addr('set')});",
              f"\t\tbank->gpio_sdir = readl({bank_addr('dirout')});",
              f'\t\tbank->gc.label = "{dev}";',
              "\t\tbank->gc.parent = &pdev->dev;",
              "\t\tbank->gc.owner = THIS_MODULE;",
              "\t\tbank->gc.fwnode = child;", "\t\tbank->gc.base = -1;",
              f"\t\tbank->ngpio = {ngpio_default};"]
        if ngpio_properties:
            conditions = [
                f'fwnode_property_read_u32(child, "{name}", &bank->ngpio)'
                for name in ngpio_properties]
            L += [f"\t\tif ({' && '.join(conditions)})",
                  f"\t\t\tbank->ngpio = {ngpio_default};"]
        L += [f"\t\tif (!bank->ngpio || bank->ngpio > {ngpio_default})",
              "\t\t\treturn -EINVAL;", "\t\tbank->gc.ngpio = bank->ngpio;",
              "\t\tbank->gc.can_sleep = false;",
              "\t\tbank->gc.request = gpiochip_generic_request;",
              "\t\tbank->gc.free = gpiochip_generic_free;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\t\tbank->gc.{field} = {fn};")
        irq = gpio_bank.get("irq")
        if has_irq and irq:
            selector_value = int(irq["selector_value"])
            L += [f"\t\tif (bank->gpio_bank_index == {selector_value}) {{",
                  "\t\t\tbank->parent_irqs = devm_kcalloc(&pdev->dev,",
                  "\t\t\t\tbank->gc.ngpio, sizeof(*bank->parent_irqs),",
                  "\t\t\t\tGFP_KERNEL);",
                  "\t\t\tif (!bank->parent_irqs)", "\t\t\t\treturn -ENOMEM;",
                  "\t\t\tfor (irq_index = 0; irq_index < bank->gc.ngpio;",
                  "\t\t\t     irq_index++) {"]
            if irq.get("platform_indexed"):
                L += ["\t\t\t\tif (has_acpi_companion(&pdev->dev))",
                      "\t\t\t\t\tparent_irq = platform_get_irq_optional(",
                      "\t\t\t\t\t\tpdev, irq_index);", "\t\t\t\telse"]
            L += ["\t\t\t\t\tparent_irq = fwnode_irq_get(child, irq_index);",
                  "\t\t\t\tif (parent_irq > 0)",
                  "\t\t\t\t\tbank->parent_irqs[bank->num_parent_irqs++] =",
                  "\t\t\t\t\t\tparent_irq;", "\t\t\t}",
                  "\t\t\tif (bank->num_parent_irqs) {"]
            L += [f'\t\t\t\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_enable",
                          "irq_disable", "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\t\t\t\tg->irqchip.{field} = {fn};")
            L += ["\t\t\t\tgpio_irq_chip_set_chip(&bank->gc.irq,",
                  "\t\t\t\t\t\t       &g->irqchip);",
                  "\t\t\t\tbank->gc.irq.handler = handle_bad_irq;",
                  "\t\t\t\tbank->gc.irq.default_type = IRQ_TYPE_NONE;",
                  "\t\t\t\tbank->gc.irq.num_parents =",
                  "\t\t\t\t\tbank->num_parent_irqs;",
                  "\t\t\t\tbank->gc.irq.parents = bank->parent_irqs;",
                  "\t\t\t\tbank->gc.irq.parent_handler_data =",
                  "\t\t\t\t\t&bank->gc;",
                  f"\t\t\t\tbank->gc.irq.parent_handler = {cid}_banked_irq_handler;",
                  "\t\t\t}", "\t\t}"]
        L += ["\t\tret = devm_gpiochip_add_data(&pdev->dev, &bank->gc, bank);",
              "\t\tif (ret)", "\t\t\treturn ret;", "\t\tbank_index++;",
              "\t}"]
    elif has_gpio:
        L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
              "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
              ("\tg->gc.ngpio = g->ngpio;" if any(
                  s.name == "ngpio" for s in device_spec.state)
               else "\tg->gc.ngpio = 32;"),
              "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\tg->gc.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_enable",
                          "irq_disable", "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\tg->irqchip.{field} = {fn};")
            L += ["\tgpio_irq_chip_set_chip(&g->gc.irq, &g->irqchip);",
                  "\tg->gc.irq.handler = handle_simple_irq;",
                  "\tg->gc.irq.default_type = IRQ_TYPE_NONE;"]
            parent_handler = by_field.get("gpio_irq_chip.parent_handler")
            if parent_handler:
                L.append(f"\tg->gc.irq.parent_handler = {parent_handler};")
            init_hw = by_field.get("gpio_irq_chip.init_hw")
            if init_hw:
                L.append(f"\tg->gc.irq.init_hw = {init_hw};")
        L += ["\tret = devm_gpiochip_add_data(&pdev->dev, &g->gc, g);",
              "\tif (ret)", "\t\treturn ret;"]
    L += [f'\tdev_info(&pdev->dev, "{dev} probed\\n");', "\treturn 0;", "}", "",
          f"static void {cid}_remove(struct platform_device *pdev)", "{",
          "\t(void)pdev;", "}", "",
          f"static const struct of_device_id {cid}_of_match[] = {{"]
    if clock_model and clock_model["variants"]:
        for compatible, group in clock_model["variants"]:
            L.append(f'\t{{ .compatible = "{compatible}", '
                     f'.data = &{clock_table_names[group]} }},')
    else:
        L.append(f'\t{{ .compatible = "reharness,{dev}" }},')
    L += ["\t{ }", "};",
          f"MODULE_DEVICE_TABLE(of, {cid}_of_match);", "",
          f"static struct platform_driver {cid}_driver = {{",
          f"\t.probe = {cid}_probe,", f"\t.remove = {cid}_remove,",
          "\t.driver = {", f'\t\t.name = "{dev}",',
          f"\t\t.of_match_table = {cid}_of_match,"]
    if pm_fields:
        L.append(f"\t\t.pm = &{cid}_pm_ops,")
    L += ["\t},", "};", f"module_platform_driver({cid}_driver);"]
    return "\n".join(L)


def _emit_pci(formal, device_spec, bind, facts, priv, regs,
              callbacks: dict[str, str], callback_code: list[str],
              unsupported: list[str], gpio_model: dict | None = None,
              irq_model: dict | None = None) -> str:
    dev = device_spec.name
    safe_function_calls = set(_portable_function_macros(formal))
    cid = _cid(dev)
    _, probe_module = _probe_ops(device_spec, formal)
    if device_spec.cls == "ahci":
        # Full AHCI probe semantics depend on libata host/port objects and
        # source-specific state that are intentionally outside the current
        # DeviceSpec.  Keep framework/resource glue buildable without emitting
        # expressions containing unbound `host`/`hpriv` source variables.
        probe_module = None
    bar = 5 if device_spec.cls == "ahci" else 0
    misc = dev == "edu"
    ids = _pci_ids(device_spec, facts)
    by_field = {field: fn for fn, field in callbacks.items()}
    if irq_model:
        by_field.setdefault("irq_chip.irq_mask", f"{cid}_irq_mask")
        by_field.setdefault("irq_chip.irq_unmask", f"{cid}_irq_unmask")
        by_field.setdefault("irq_chip.irq_eoi", f"{cid}_irq_eoi")
    has_gpio = device_spec.cls == "gpio_controller" or any(
        field.startswith("gpio_chip.") for field in by_field)
    has_irq = any(field.startswith("irq_chip.") for field in by_field)
    direct_handler = by_field.get("irq_handler.handler")

    L = callback_code[:]
    if gpio_model:
        L += _emit_source_gpio_callbacks(cid, priv, gpio_model)
    if irq_model:
        L += _emit_source_generic_irq_callbacks(cid, priv, irq_model)
    L += _emit_usb_callback_tables(dev, callbacks)
    if misc:
        L += [f"static int {cid}_open(struct inode *inode, struct file *file)", "{",
              f"\tstruct {priv} *g = container_of(file->private_data, struct {priv}, misc);",
              "\tfile->private_data = g;", "\treturn 0;", "}", "",
              f"static ssize_t {cid}_read(struct file *file, char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              "\tvalue = readl(g->base + *off);",
              "\tif (copy_to_user(buf, &value, sizeof(value)))", "\t\treturn -EFAULT;",
              "\t*off += sizeof(value);", "\treturn sizeof(value);", "}", "",
              f"static ssize_t {cid}_write(struct file *file, const char __user *buf, size_t len, loff_t *off)",
              "{", f"\tstruct {priv} *g = file->private_data;", "\tu32 value;",
              "\tif ((*off & 3) || len < sizeof(value))", "\t\treturn -EINVAL;",
              "\tif (copy_from_user(&value, buf, sizeof(value)))", "\t\treturn -EFAULT;",
              "\twritel(value, g->base + *off);", "\t*off += sizeof(value);",
              "\treturn sizeof(value);", "}", "",
              f"static const struct file_operations {cid}_fops = {{",
              "\t.owner = THIS_MODULE,", f"\t.open = {cid}_open,",
              f"\t.read = {cid}_read,", f"\t.write = {cid}_write,", "};", ""]

    L += [f"static int {cid}_probe(struct pci_dev *pdev, const struct pci_device_id *id)",
          "{", f"\tstruct {priv} *g;", "\tint ret;", "\t(void)id;",
          "\tg = devm_kzalloc(&pdev->dev, sizeof(*g), GFP_KERNEL);",
          "\tif (!g)", "\t\treturn -ENOMEM;", "\tg->dev = &pdev->dev;",
          "\tg->pdev = pdev;", "\tret = pci_enable_device_mem(pdev);",
          "\tif (ret)", "\t\treturn ret;",
          "\tret = pci_request_regions(pdev, KBUILD_MODNAME);",
          "\tif (ret)", "\t\tgoto err_disable;",
          f"\tg->base = pci_ioremap_bar(pdev, {bar});",
          "\tif (!g->base) {", "\t\tret = -ENOMEM;", "\t\tgoto err_regions;", "}",
          "\tpci_set_drvdata(pdev, g);"]
    L += _emit_probe_body(
        probe_module, regs, bind,
        safe_function_calls=safe_function_calls)
    gpio_ref = "g->gc"
    if has_gpio:
        if gpio_model:
            ngpio = gpio_model.get("ngpio") or 32
            fields = gpio_model["fields"]
            L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
                  "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
                  f"\tg->gc.ngpio = {ngpio};", "\tg->gc.can_sleep = false;",
                  "\tg->gc.request = " + cid + "_gpio_request;",
                  "\tg->gc.get = " + cid + "_gpio_get;",
                  "\tg->gc.get_multiple = " + cid + "_gpio_get_multiple;",
                  "\tg->gc.set = " + cid + "_gpio_set;",
                  "\tg->gc.set_multiple = " + cid + "_gpio_set_multiple;",
                  "\tg->gc.get_direction = " + cid + "_gpio_get_direction;",
                  "\tg->gc.direction_input = " + cid + "_gpio_direction_input;",
                  "\tg->gc.direction_output = " + cid + "_gpio_direction_output;",
                  "\traw_spin_lock_init(&g->gpio_lock);",
                  f"\tg->gpio_data = readl({fields.get('set', fields['dat'])});",
                  f"\tg->gpio_dir = readl({fields['dirout']});"]
        else:
            L += [f'\tg->gc.label = "{dev}";', "\tg->gc.parent = &pdev->dev;",
                  "\tg->gc.owner = THIS_MODULE;", "\tg->gc.base = -1;",
                  "\tg->gc.ngpio = 32;", "\tg->gc.can_sleep = false;"]
        for field in ("request", "free", "get_direction", "direction_input",
                      "direction_output", "get", "get_multiple", "set",
                      "set_multiple", "set_config"):
            fn = by_field.get(f"gpio_chip.{field}")
            if fn:
                L.append(f"\t{gpio_ref}.{field} = {fn};")
        if has_irq:
            L += [f'\tg->irqchip.name = "{dev}-irq";']
            if irq_model:
                L += ["\traw_spin_lock_init(&g->irq_lock);",
                      "\tg->irq_mask_cache = 0;"]
            for field in ("irq_ack", "irq_mask", "irq_unmask", "irq_eoi",
                          "irq_set_type"):
                fn = by_field.get(f"irq_chip.{field}")
                if fn:
                    L.append(f"\tg->irqchip.{field} = {fn};")
            handler = irq_model["handler"] if irq_model else "handle_simple_irq"
            L += [f"\tgpio_irq_chip_set_chip(&{gpio_ref}.irq, &g->irqchip);",
                  f"\t{gpio_ref}.irq.handler = {handler};",
                  f"\t{gpio_ref}.irq.default_type = IRQ_TYPE_NONE;"]
        L += [f"\tret = devm_gpiochip_add_data(&pdev->dev, &{gpio_ref}, g);",
              "\tif (ret)", "\t\tgoto err_iounmap;"]
    if direct_handler:
        L += [f"\tret = devm_request_irq(&pdev->dev, pdev->irq, {direct_handler},",
              f'\t\t\t       IRQF_SHARED, "{dev}", g);',
              "\tif (ret)", "\t\tgoto err_iounmap;"]
    if misc:
        L += ["\tg->misc.minor = MISC_DYNAMIC_MINOR;",
              "\tg->misc.name = KBUILD_MODNAME;", f"\tg->misc.fops = &{cid}_fops;",
              "\tret = misc_register(&g->misc);", "\tif (ret)", "\t\tgoto err_iounmap;"]
    L += [f'\tdev_info(&pdev->dev, "{dev} probed\\n");', "\treturn 0;"]
    if misc or has_gpio or direct_handler:
        L += ["err_iounmap:", "\tiounmap(g->base);"]
    L += ["err_regions:",
          "\tpci_release_regions(pdev);", "err_disable:", "\tpci_disable_device(pdev);",
          "\treturn ret;", "}", "", f"static void {cid}_remove(struct pci_dev *pdev)",
          "{", f"\tstruct {priv} *g = pci_get_drvdata(pdev);"]
    if misc:
        L.append("\tmisc_deregister(&g->misc);")
    L += ["\tiounmap(g->base);", "\tpci_release_regions(pdev);",
          "\tpci_disable_device(pdev);", "}", "",
          f"static const struct pci_device_id {cid}_ids[] = {{"]
    if device_spec.cls == "ahci":
        L.append("\t{ PCI_DEVICE_CLASS(PCI_CLASS_STORAGE_SATA_AHCI, ~0) },")
    elif ids:
        L.append(f"\t{{ PCI_DEVICE(0x{ids[0]:04x}, 0x{ids[1]:04x}) }},")
    else:
        L.append("\t{ PCI_DEVICE(0xffff, 0xffff) },")
    L += ["\t{ }", "};", f"MODULE_DEVICE_TABLE(pci, {cid}_ids);", "",
          f"static struct pci_driver {cid}_driver = {{", f'\t.name = "{dev}",',
          f"\t.id_table = {cid}_ids,", f"\t.probe = {cid}_probe,",
          f"\t.remove = {cid}_remove,", "};", f"module_pci_driver({cid}_driver);"]
    return "\n".join(L)


def generate(formal: dict, device_spec, bind, facts=None) -> str:
    dev = device_spec.name
    preserved_virtio = _source_preserved_virtio(
        formal, device_spec, facts)
    if preserved_virtio is not None:
        return preserved_virtio
    priv = f"{_cid(dev)}_priv"
    regs = {r["name"]: r["offset"] for r in formal.get("register_map", [])}
    callbacks = _callback_map(bind, facts, device_spec)
    modules = {m["name"]: m for m in formal["modules"]}
    summary_groups = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    if device_spec.cls == "sdhci" and isinstance(summary_groups, dict):
        for item in summary_groups.get("sdhci_ops", []):
            if (item.get("implementation") == "source-private"
                    and item.get("field") and item.get("module") in modules):
                callbacks.setdefault(
                    item["module"], f"sdhci_ops.{item['field']}")
    function_macros = _portable_function_macros(formal)
    safe_function_calls = set(function_macros)
    probe_refs = {
        fn.ris_ref for fn in device_spec.functions if fn.role == "probe"
    }

    def backend_ops(module: dict):
        ops = module.get("ops", [])
        return (_bound_resource_probe_ops(ops)
                if module.get("name") in probe_refs else ops)
    callbacks_for_codegen = {
        fn: field for fn, field in callbacks.items()
        if fn in modules or field.endswith((".probe", ".remove"))
    }

    callback_code: list[str] = []
    unsupported: list[str] = []
    clock_model = (_clock_source_model(facts, priv)
                   if device_spec.cls == "clock" else None)
    if clock_model:
        callback_code.extend(clock_model["helpers"])
        if clock_model["helpers"]:
            callback_code.append("")
        for function in sorted(clock_model["callbacks"]):
            callback_code.append(clock_model["callbacks"][function])
            callback_code.append("")
    gpio_model = (_source_gpio_model(facts)
                  if device_spec.cls == "gpio_controller" else None)
    gpio_summaries = (summary_groups.get("gpio_generic", [])
                      if isinstance(summary_groups, dict) else [])
    gpio_bank = next((summary.get("bank_model") for summary in gpio_summaries
                      if summary.get("bank_model")), None)
    banked_gpio = gpio_bank is not None
    banked_irq_model = (_banked_irq_status_model(facts)
                        if banked_gpio and gpio_bank.get("irq") else None)
    if banked_irq_model:
        callback_code.extend(_emit_banked_irq_handler(
            _cid(dev), priv, banked_irq_model))
    elif banked_gpio and gpio_bank.get("irq"):
        unsupported.append(
            "banked GPIO parent IRQ status register lacks source proof")
    irq_model = (_source_generic_irq_model(facts)
                 if gpio_model is not None else None)
    gpio_member = "gc"
    irq_source_callbacks: dict[str, str] = {}
    source_path = getattr(facts, "source", None) if facts is not None else None
    source_text = ""
    if source_path and source_path.endswith(".c") and os.path.isfile(source_path):
        source_text = open(
            source_path, "r", encoding="utf-8", errors="replace").read()
        for fn in device_spec.functions:
            field = callbacks.get(fn.name)
            if not field:
                continue
            if banked_gpio and _banked_gpio_callback(field):
                continue
            code = _lower_irq_source_callback(
                source_text, fn.name, field, priv, gpio_member)
            if code:
                irq_source_callbacks[fn.name] = code
        for function in sorted(irq_source_callbacks):
            callback_code.append(irq_source_callbacks[function])
            callback_code.append("")
    if device_spec.cls == "ahci":
        unsupported.append("AHCI probe requires libata host/port state bindings")
    if (device_spec.cls == "sdhci"
            and not portable_sdhci_accessor_only(formal, device_spec)):
        unsupported.append("SDHCI probe requires mmc/host state bindings")
    if (device_spec.cls == "virtio_mmio"
            and not portable_virtio_state_only(formal, device_spec)):
        unsupported.append("virtio-mmio probe requires virtio core state bindings")
    usb_callback_fields = {
        field for field in callbacks.values()
        if field.startswith(("usb_ep_ops.", "usb_gadget_ops.", "hc_driver."))
    }
    if usb_callback_fields:
        unsupported.append(
            "USB callback tables require endpoint/gadget/HCD lifecycle registration")
    if any(_normalize_ops(
            backend_ops(m), safe_function_calls=safe_function_calls)[1]
           for m in formal.get("modules", [])):
        unsupported.append("source-private expressions require explicit state bindings")

    # Once a driver is already explicitly non-ready, keep large real-driver
    # outputs compilable even when source-local macro helpers are not exported
    # through FactsSpec. Object constants recovered from headers remain exact;
    # only the residual names below receive guarded neutral fallbacks.
    fallback_refs: set[str] = set()
    fallback_calls: set[str] = set()
    if unsupported:
        for definition in function_macros.values():
            body = definition.get("body", "")
            fallback_refs |= set(re.findall(
                r"\b[A-Z][A-Za-z0-9_]{2,}\b", body))
            fallback_calls |= set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", body))
        for module in formal.get("modules", []):
            safe_ops, _ = _normalize_ops(
                backend_ops(module),
                safe_function_calls=safe_function_calls)
            fallback_refs |= {name for name in value_var_names(safe_ops)
                              if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name)}
            fallback_refs |= set(re.findall(
                r"\b[A-Z][A-Za-z0-9_]{2,}\b", repr(safe_ops)))
            fallback_calls |= set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]{2,})\s*\(", repr(safe_ops)))
    for fn in device_spec.functions:
        field = callbacks.get(fn.name)
        if not field or field.endswith(".probe") or field.endswith(".remove"):
            continue
        if (clock_model and field.startswith("clk_ops.")
                and fn.name in clock_model["callbacks"]):
            continue
        if fn.name in irq_source_callbacks:
            continue
        if dev == "edu" and field.startswith("file_operations."):
            # The edu PCI backend supplies checked raw-MMIO file operations
            # with the correct miscdevice private-data lifecycle below.
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        if banked_gpio and field.startswith("irq_chip.") and source_text:
            code = _emit_banked_irq_source_callback(
                fn, module, field, priv, regs, source_text,
                safe_function_calls)
            if code:
                callback_code.append(code)
                continue
        code, problem = _emit_callback(
            fn, module, field, priv, regs, bind, safe_function_calls,
            banked_gpio=banked_gpio)
        if code:
            callback_code.append(code)
        if problem:
            unsupported.append(problem)

    binding_rows = formal.get("metadata", {}).get(
        "callback_binding_analysis", {}).get("bindings", [])
    multi_source = len(formal.get("metadata", {}).get("sources", [])) > 1
    evidence_only = {
        row.get("function") for row in binding_rows
        if (row.get("role") == "unknown"
            and row.get("public_callback_type") is False
            and multi_source)}
    for fn in device_spec.functions:
        if (fn.name not in evidence_only
                or fn.name in callbacks_for_codegen):
            continue
        module = modules.get(fn.ris_ref)
        if module is None:
            continue
        callback_code.append(_emit_evidence_only_callback(
            fn, module, priv, regs, bind, safe_function_calls))

    callbacks = callbacks_for_codegen
    is_pci = any(field.startswith("pci_driver.") for field in callbacks.values())
    has_delay = any("Delay" in op for module in formal.get("modules", [])
                    for op in walk_leaf_ops(module.get("ops", [])))
    includes = [
        "#include <linux/module.h>", "#include <linux/device.h>",
        "#include <linux/io.h>", "#include <linux/slab.h>",
        "#include <linux/err.h>", "#include <linux/interrupt.h>",
        "#include <linux/bits.h>",
    ]
    if is_pci:
        includes += ["#include <linux/pci.h>", "#include <linux/miscdevice.h>",
                     "#include <linux/fs.h>", "#include <linux/uaccess.h>"]
    else:
        includes += ["#include <linux/platform_device.h>",
                     "#include <linux/of_device.h>",
                     "#include <linux/gpio/driver.h>", "#include <linux/clk.h>"]
    if any(field.startswith(("irq_chip.", "gpio_chip.", "gpio_irq_chip."))
           for field in callbacks.values()):
        includes += ["#include <linux/gpio/driver.h>", "#include <linux/irq.h>",
                     "#include <linux/bitops.h>"]
    if gpio_model or irq_model or banked_gpio:
        includes.append("#include <linux/spinlock.h>")
    if any(field.startswith("clk_ops.") for field in callbacks.values()):
        includes += ["#include <linux/clk-provider.h>"]
    if (any(state.name == "hpi_regstep" for state in device_spec.state)
            or any(state.name == "gpio_config_variant"
                   for state in device_spec.state)
            or any(state.type == "UIntArray" for state in device_spec.state)):
        includes += ["#include <linux/property.h>"]
    if banked_gpio and gpio_bank.get("irq"):
        includes += ["#include <linux/acpi.h>", "#include <linux/irqdomain.h>"]
    if any(state.name == "gpio_config_variant" for state in device_spec.state):
        includes += ["#include <linux/of.h>"]
    if any(field.startswith(("usb_ep_ops.", "usb_gadget_ops."))
           for field in callbacks.values()):
        includes += ["#include <linux/usb/gadget.h>"]
    if any(field.startswith("hc_driver.") for field in callbacks.values()):
        includes += ["#include <linux/usb.h>", "#include <linux/usb/hcd.h>"]
    if device_spec.cls == "sdhci":
        includes += ["#include <linux/delay.h>", "#include <linux/mmc/host.h>",
                     '#include "sdhci-pltfm.h"']
    elif has_delay:
        includes += ["#include <linux/delay.h>"]

    L = [f"// Auto-generated deterministic Linux driver for {dev} (reharness)",
         "// SPDX-License-Identifier: GPL-2.0", *includes, ""]
    for name, off in regs.items():
        L.append(f"#ifndef {name}\n#define {name}\t0x{off:x}\n#endif")
    for name, definition in sorted(function_macros.items()):
        params = ", ".join(definition.get("params", []))
        body = definition.get("body", "0")
        L.append(
            f"#ifndef {name}\n#define {name}({params}) {body}\n#endif")
    source_macros = _source_object_macros(facts)
    for name, value in source_macros.items():
        if name not in regs:
            L.append(f"#ifndef {name}\n#define {name}\t{value}\n#endif")
    if facts is not None:
        for name, value in sorted(facts.constants.items()):
            if name not in regs and name not in source_macros:
                L.append(f"#ifndef {name}\n#define {name}\t0x{value:x}\n#endif")
    known_constants = set(regs)
    known_functions = set(function_macros)
    if facts is not None:
        known_constants |= set(facts.constants)
    if unsupported:
        for name in sorted(fallback_calls - known_constants - known_functions):
            L.append(f"#ifndef {name}\n#define {name}(...) 0\n#endif")
        for name in sorted(fallback_refs - fallback_calls - known_constants
                           - {"MMIO", "TODO"}):
            L.append(f"#ifndef {name}\n#define {name} 0\n#endif")
    if banked_gpio:
        L += ["", f"struct {_bank_priv(priv)};"]
    L += ["", f"struct {priv} {{", "\tstruct device *dev;",
          "\tvoid __iomem *base;"]
    if device_spec.cls == "sdhci":
        L.append("\tstruct sdhci_host *host;")
    if is_pci:
        L.append("\tstruct pci_dev *pdev;")
        if dev == "edu":
            L.append("\tstruct miscdevice misc;")
        if any(field.startswith(("gpio_chip.", "irq_chip.", "gpio_irq_chip.",
                                 "irq_handler."))
               for field in callbacks.values()):
            L.append("\tstruct gpio_chip gc;")
            L.append("\tstruct irq_chip irqchip;")
            if gpio_model:
                L += ["\traw_spinlock_t gpio_lock;", "\tu32 gpio_data;",
                      "\tu32 gpio_dir;"]
            if irq_model:
                L += ["\traw_spinlock_t irq_lock;", "\tu32 irq_mask_cache;"]
    else:
        if banked_gpio:
            L += [f"\tstruct {_bank_priv(priv)} *banks;",
                  "\tstruct irq_chip irqchip;", "\traw_spinlock_t irq_lock;",
                  "\tstruct clk *clk;"]
        else:
            L += ["\tstruct gpio_chip gc;", "\tstruct irq_chip irqchip;",
                  "\tstruct clk *clk;"]
        if (clock_model or any(
                field.startswith("clk_ops.") for field in callbacks.values())):
            L.append("\tstruct clk_hw hw;")
        if clock_model:
            L += ["\tstruct clk_init_data init;",
                  "\tstruct clk_parent_data parent_data;"]
    if any(field.startswith("usb_ep_ops.") for field in callbacks.values()):
        L.append("\tstruct usb_ep ep;")
    if any(field.startswith("usb_gadget_ops.") for field in callbacks.values()):
        L.append("\tstruct usb_gadget gadget;")
    for state in device_spec.state:
        if state.name in {"base", "clk", "num_irqs"}:
            continue
        if banked_gpio and state.name in {
                "gpio_bank_index", "gpio_sdata", "gpio_sdir"}:
            continue
        ctype = ("void __iomem *" if state.type == "MmioBase" else
                 "u32 *" if state.type == "UIntArray" else
                 "u64" if state.type == "UInt64" else "u32")
        L.append(f"\t{ctype} {state.name};")
    L += ["};", ""]
    if banked_gpio:
        L += [f"struct {_bank_priv(priv)} {{",
              "\tstruct gpio_chip gc;", f"\tstruct {priv} *parent;",
              "\tu32 gpio_bank_index;", "\tu32 gpio_sdata;",
              "\tu32 gpio_sdir;", "\tu32 ngpio;",
              "\tunsigned int *parent_irqs;",
              "\tunsigned int num_parent_irqs;", "};", ""]
    if has_delay:
        L += ["static inline void reharness_delay_ns(unsigned long ns)", "{",
              "\tif (ns <= 1000)", "\t\tndelay(ns);",
              "\telse if (ns <= 1000000)",
              "\t\tudelay(DIV_ROUND_UP(ns, 1000));", "\telse",
              "\t\tmdelay(DIV_ROUND_UP(ns, 1000000));", "}", ""]

    if unsupported:
        for item in unsupported:
            L.append(f"/* REHARNESS_UNSUPPORTED callback: {item} */")
        L.append("")

    sdhci_body = (_emit_sdhci_platform(
        formal, device_spec, facts, priv, callbacks, callback_code)
        if device_spec.cls == "sdhci" else None)
    if sdhci_body is not None:
        body = sdhci_body
    elif is_pci:
        body = _emit_pci(formal, device_spec, bind, facts, priv, regs,
                         callbacks, callback_code, unsupported,
                         gpio_model, irq_model)
    else:
        body = _emit_platform(formal, device_spec, bind, facts, priv, regs,
                              callbacks, callback_code, unsupported,
                              clock_model)
    L += [body, "", 'MODULE_LICENSE("GPL");',
          f'MODULE_DESCRIPTION("reharness generated driver for {dev}");']
    return "\n".join(L) + "\n"
