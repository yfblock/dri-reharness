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

def make_cid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text)

def callback_map(bind, facts, device_spec=None) -> dict[str, str]:
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

def source_preserved_virtio(formal: dict, device_spec, facts) -> str | None:
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

def last_read_var(module: dict) -> str | None:
    reads = [o["Read"].get("var") for o in walk_leaf_ops(module["ops"])
             if "Read" in o and o["Read"].get("var")]
    return reads[-1] if reads else None

def portable_function_macros(formal: dict) -> dict[str, dict]:
    macros = formal.get("metadata", {}).get("function_macros", {})
    return {
        name: definition for name, definition in macros.items()
        if not re.search(r"->|\.[A-Za-z_]", definition.get("body", ""))
    }

def bound_resource_probe_ops(ops):
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
                out.extend(bound_resource_probe_ops(
                    original["Cond"].get("then_ops", [])))
                continue
            original["Cond"]["then_ops"] = bound_resource_probe_ops(
                original["Cond"].get("then_ops", []))
            if original["Cond"].get("else_ops"):
                original["Cond"]["else_ops"] = bound_resource_probe_ops(
                    original["Cond"]["else_ops"])
        elif "Seq" in original:
            original["Seq"]["ops"] = bound_resource_probe_ops(
                original["Seq"].get("ops", []))
        elif "Loop" in original:
            original["Loop"]["body"] = bound_resource_probe_ops(
                original["Loop"].get("body", []))
        out.append(original)
    return out

def mask_c_source(source: str) -> str:
    """Mask comments and literals while preserving offsets and newlines."""
    pattern = re.compile(
        r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.S)

    def mask(match):
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return pattern.sub(mask, source)

def matching_delimiter(masked: str, start: int, opening: str,
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

def source_function(source: str, name: str) -> dict | None:
    """Return an exact source function definition with balanced delimiters."""
    masked = mask_c_source(source)
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", masked):
        open_paren = masked.find("(", match.start())
        close_paren = matching_delimiter(masked, open_paren, "(", ")")
        if close_paren is None:
            continue
        brace = close_paren + 1
        while brace < len(masked) and masked[brace].isspace():
            brace += 1
        if brace >= len(masked) or masked[brace] != "{":
            continue
        close_brace = matching_delimiter(masked, brace, "{", "}")
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

def parameter_names(params: str) -> list[str]:
    names = []
    for param in params.split(","):
        param = param.strip()
        if not param or param == "void":
            continue
        match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^]]*\])?\s*$", param)
        if match:
            names.append(match.group(1))
    return names

def parse_clk_ops_groups(source: str) -> dict[str, dict[str, str]]:
    """Preserve individual clk_ops instances instead of last-field-wins."""
    masked = mask_c_source(source)
    groups: dict[str, dict[str, str]] = {}
    pattern = re.compile(
        r"\b(?:static\s+)?(?:const\s+)?struct\s+clk_ops\s+"
        r"([A-Za-z_]\w*)\s*=\s*\{")
    for match in pattern.finditer(masked):
        brace = masked.find("{", match.start())
        close = matching_delimiter(masked, brace, "{", "}")
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

def lower_clock_source_callback_analysis(
        source: str, name: str, priv: str) -> tuple[str | None, str | None]:
    """Lower a clock callback while preserving its scalar C semantics.

    The original callback body is retained, but the source-private container
    pointer is rebound to the generated private object's MMIO base.  This
    captures arithmetic and early returns that the MMIO-only RIS does not yet
    represent; lowering is rejected if any private member remains unbound.
    """
    function = source_function(source, name)
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
        params = parameter_names(function["params"])
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

def lower_clock_source_callback(source: str, name: str, priv: str) -> str | None:
    code, _reason = lower_clock_source_callback_analysis(source, name, priv)
    return code

def analyze_clock_source_model_inner(facts, priv: str) -> dict:
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
    groups = parse_clk_ops_groups(source)
    result["groups"] = groups
    if not groups:
        result["reasons"].append("no concrete struct clk_ops instances found")
        return result
    functions = {function for fields in groups.values() for function in fields.values()}
    lowered: dict[str, str] = {}
    for function in sorted(functions):
        code, reason = lower_clock_source_callback_analysis(
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
                helper = source_function(source, called)
                if helper is not None:
                    helper_names.add(called)
    helpers: list[str] = []
    for helper_name in sorted(helper_names):
        helper = source_function(source, helper_name)
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
        init = source_function(source, init_function)
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
    result = analyze_clock_source_model_inner(facts, priv)
    return {
        "supported": result["supported"],
        "reasons": list(result["reasons"]),
        "groups": result["groups"],
        "variants": list(result["variants"]),
        "lowered_callbacks": sorted(result["callbacks"]),
        "pure_helpers": len(result["helpers"]),
    }

def clock_source_model(facts, priv: str) -> dict | None:
    result = analyze_clock_source_model_inner(facts, priv)
    if not result["supported"]:
        return None
    return {
        "groups": result["groups"],
        "callbacks": result["callbacks"],
        "helpers": result["helpers"],
        "variants": result["variants"],
    }

def source_object_macros(facts) -> dict[str, str]:
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

def lower_irq_source_callback(source: str, name: str, table_field: str,
                               priv: str,
                               gpio_member: str = "gc",
                               module: dict | None = None) -> str | None:
    """Conservatively rebind generic-IRQ private state to generated state."""
    if not (table_field.startswith("irq_chip.")
            or table_field == "irq_handler.handler"):
        return None
    function = source_function(source, name)
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
    receipts = [f"\t{lowering_receipt(op)}"
                for op in walk_leaf_ops((module or {}).get("ops", []))
                if any(kind in op for kind in
                       ("Read", "Write", "ReadModifyWrite"))]
    lines = [function["header"], "{", *prelude, *receipts]
    if body.strip():
        lines.append(body.strip("\n"))
    lines.append("}")
    return "\n".join(lines)

def mfd_include_paths(formal: dict) -> list[str]:
    """Return validated public MFD headers required by transaction helpers."""
    paths: set[str] = set()
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("TransactionRead") or op.get("TransactionWrite")
                    or op.get("TransactionUpdate"))
            if not body or body.get("transport") != "mfd":
                continue
            path = (body.get("evidence") or {}).get("callee_decl_path", "")
            normalized = path.replace("\\", "/")
            marker = "/include/linux/mfd/"
            if marker not in normalized:
                continue
            suffix = normalized.split("/include/linux/", 1)[1]
            if re.fullmatch(r"mfd/[A-Za-z0-9_.-]+\.h", suffix):
                paths.add(f"<linux/{suffix}>")
    return sorted(paths)

def selective_overlay_ops(formal: dict, module_name: str) -> list | None:
    overlay = (formal.get("metadata", {}).get("call_graph", {})
               .get("selective_closure", {}).get("overlays", {})
               .get(module_name))
    if not isinstance(overlay, list):
        return None
    canonical_digests = {}
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = op.get("Read") or op.get("Write") or op.get(
                "ReadModifyWrite")
            if body and isinstance(body.get("op_id"), str):
                canonical_digests[body["op_id"]] = ris_op_digest(op)
    out = copy.deepcopy(overlay)
    for op in walk_leaf_ops(out):
        body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
        if body and body.get("op_id") in canonical_digests:
            body["_backend_contract_digest"] = canonical_digests[
                body["op_id"]]
    return out

def probe_ops(device_spec, formal: dict):
    probe = next((f for f in device_spec.functions if f.role == "probe"), None)
    if probe is None:
        return None, None
    module = next((m for m in formal["modules"] if m["name"] == probe.ris_ref), None)
    overlay = selective_overlay_ops(formal, probe.ris_ref)
    if isinstance(overlay, list):
        module = dict(module or {
            "name": probe.ris_ref, "source": None,
        })
        module["ops"] = overlay
    return probe, module

def pci_ids(device_spec, facts, pci_identity=None) -> tuple[int, int] | None:
    if pci_identity is not None:
        vendor = getattr(pci_identity, "vendor", None)
        device = getattr(pci_identity, "device", None)
        if vendor is None and isinstance(pci_identity, dict):
            vendor, device = pci_identity.get("vendor"), pci_identity.get("device")
        if isinstance(vendor, int) and isinstance(device, int):
            return vendor, device
    source = getattr(facts, "source", None) if facts is not None else None
    if source and os.path.isfile(source):
        text = open(source, "r", encoding="utf-8", errors="replace").read()
        token = r"(?:0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*)"
        m = re.search(rf"PCI_DEVICE\s*\(\s*({token})\s*,\s*"
                      rf"({token})\s*\)", text)
        if m:
            values = []
            constants = getattr(facts, "constants", {}) if facts else {}
            macros = source_object_macros(facts)
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

def balanced_initializer_blocks(text: str, struct_name: str):
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

def initializer_expr(body: str, field: str) -> str | None:
    match = re.search(
        rf"\.\s*{re.escape(field)}\s*=\s*(.+?)"
        rf"(?=,\s*\.\s*[A-Za-z_]\w*\s*=|,?\s*$)", body, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None
