"""Source-contract oracle for direct SDHCI accessor lowering."""
from __future__ import annotations

import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.formal import walk_leaf_ops
from extractor.metrics import _computed_is_lowerable


_FIELD_WIDTH = {
    "read_l": "B4", "read_w": "B2", "read_b": "B1",
    "write_l": "B4", "write_w": "B2", "write_b": "B1",
}

_PUBLIC_ACCESSOR = {
    "sdhci_readl": ("Read", "B4"),
    "sdhci_readw": ("Read", "B2"),
    "sdhci_readb": ("Read", "B1"),
    "sdhci_writel": ("Write", "B4"),
    "sdhci_writew": ("Write", "B2"),
    "sdhci_writeb": ("Write", "B1"),
}


def _expr_nodes(expr):
    if not isinstance(expr, dict):
        return
    yield expr
    for value in expr.values():
        if isinstance(value, dict):
            yield from _expr_nodes(value)


def _expr_has(expr, *, op=None, const=None, var=None) -> bool:
    for node in _expr_nodes(expr):
        if op is not None and node.get("BinOp", {}).get("op") == op:
            return True
        if const is not None and node.get("Const") == const:
            return True
        if var is not None and node.get("Var") == var:
            return True
    return False


def _field_of(body: dict) -> str | None:
    callback = body.get("evidence", {}).get("library_callback", "")
    return callback.split(".", 1)[1] if callback.startswith("sdhci_ops.") else None


def _address_mentions_reg(body: dict) -> bool:
    addr = body.get("addr", {})
    if "Computed" in addr:
        return _expr_has(addr["Computed"], var="reg")
    return "Symbolic" in addr or "Fixed" in addr


def _initializer_bodies(text: str, struct_name: str):
    pattern = re.compile(
        rf"\bstruct\s+{re.escape(struct_name)}\s+[A-Za-z_]\w*\s*=\s*\{{")
    for match in pattern.finditer(text):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start + 1:index]
                    break


def _function_body(text: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", text)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return ""


def _source_int(text: str, token: str) -> int | None:
    try:
        return int(token, 0)
    except ValueError:
        match = re.search(
            rf"^\s*#\s*define\s+{re.escape(token)}\s+(\d+)\b", text, re.M)
        return int(match.group(1)) if match else None


def verify_sdhci_accessor_source_contract(formal: dict) -> dict:
    accessor_ops = []
    callback_leaves: dict[str, list[tuple[dict, dict]]] = {}
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = (op.get("Read") or op.get("Write")
                    or op.get("ReadModifyWrite") or op.get("StateRead")
                    or op.get("StateWrite") or op.get("Return"))
            if not body or body.get("evidence", {}).get(
                    "subsystem_summary") != "sdhci_accessor":
                continue
            field = _field_of(body)
            if field:
                callback_leaves.setdefault(field, []).append((op, body))
            if op.get("Read") or op.get("Write") or op.get("ReadModifyWrite"):
                accessor_ops.append((op, body))
    if not accessor_ops:
        return {
            "sdhci_accessor_oracle_required": False,
            "sdhci_accessor_oracle_passed": True,
            "sdhci_accessor_oracle_errors": [],
            "sdhci_accessor_oracle_ops": 0,
        }

    errors = []
    source = formal.get("metadata", {}).get("source", "")
    try:
        source_text = open(source, encoding="utf-8", errors="replace").read()
    except OSError as error:
        source_text = ""
        errors.append(f"cannot read source: {error}")
    pdata = list(_initializer_bodies(source_text, "sdhci_pltfm_data"))
    if not re.search(
            r"\bsdhci_pltfm_init(?:_and_add_host)?\s*\(", source_text):
        errors.append("source does not bind host through an SDHCI platform initializer")
    if not pdata:
        errors.append("source has no auditable sdhci_pltfm_data initializer")

    summaries = formal.get("metadata", {}).get(
        "subsystem_summary_analysis", {}).get("summaries", {})
    sdhci_summaries = summaries.get("sdhci_ops", []) if isinstance(
        summaries, dict) else []
    private_dispatch = bool(sdhci_summaries)
    if private_dispatch:
        if not any(re.search(r"\.\s*ops\s*=", body) for body in pdata):
            errors.append("source SDHCI accessor table is not bound by platform data")
    elif any(re.search(r"\.\s*ops\s*=", body) for body in pdata):
        errors.append("public-accessor case unexpectedly installs private SDHCI ops")

    modules = {module["name"]: module for module in formal.get("modules", [])}
    for summary in sdhci_summaries:
        if summary.get("implementation") != "source-private":
            continue
        function_body = _function_body(source_text, summary.get("callee", ""))
        delay = re.search(r"\b([umn]?delay)\s*\(\s*([A-Za-z_]\w*|\d+)\s*\)",
                          function_body)
        if not delay:
            continue
        amount = _source_int(source_text, delay.group(2))
        multiplier = {"udelay": 1000, "mdelay": 1_000_000,
                      "ndelay": 1}.get(delay.group(1))
        expected_delay = amount * multiplier if amount is not None else None
        delays = [op["Delay"].get("cycles")
                  for op in walk_leaf_ops(
                      modules.get(summary.get("module"), {}).get("ops", []))
                  if "Delay" in op]
        if (expected_delay is None or not any(
                item.get("Const") == expected_delay for item in delays)):
            errors.append(
                f"sdhci_ops.{summary.get('field')} lost source delay contract")

    marker = f"{os.sep}linux{os.sep}"
    linux_root = (source.split(marker, 1)[0] + marker.rstrip(os.sep)
                  if marker in source else "")
    helper_path = os.path.join(
        linux_root, "drivers", "mmc", "host", "sdhci-pltfm.c")
    header_path = os.path.join(linux_root, "drivers", "mmc", "host", "sdhci.h")
    try:
        helper_text = open(
            helper_path, encoding="utf-8", errors="replace").read()
        default_ops = list(_initializer_bodies(helper_text, "sdhci_ops"))
        if not default_ops or any(re.search(
                r"\.\s*(?:read_[lwb]|write_[lwb])\s*=", body)
                for body in default_ops):
            errors.append("default sdhci_pltfm_ops accessor dispatch is not direct")
    except OSError as error:
        errors.append(f"cannot audit sdhci-pltfm.c: {error}")
    try:
        header_text = open(
            header_path, encoding="utf-8", errors="replace").read()
        if not re.search(
                r"sdhci_readl\s*\([^)]*\)\s*\{.*?"
                r"readl\s*\(\s*host->ioaddr\s*\+\s*reg\s*\)",
                header_text, re.S):
            errors.append("sdhci_readl direct ioaddr+reg contract not found")
    except OSError as error:
        errors.append(f"cannot audit sdhci.h: {error}")

    be_header_path = os.path.join(
        linux_root, "drivers", "mmc", "host", "sdhci-pltfm.h")
    try:
        be_header = open(
            be_header_path, encoding="utf-8", errors="replace").read()
        required_fragments = {
            "sdhci_be32bs_readw": r"in_be16\s*\([^;]*reg\s*\^\s*0x2",
            "sdhci_be32bs_readb": r"in_8\s*\([^;]*reg\s*\^\s*0x3",
            "sdhci_be32bs_writew": r"xfer_mode_shadow",
            "sdhci_be32bs_writeb": r"clrsetbits_be32",
        }
        for name, fragment in required_fragments.items():
            if name in {body.get("evidence", {}).get("effective_callee")
                        for _op, body in accessor_ops} and not re.search(
                            fragment, be_header, re.S):
                errors.append(f"public {name} contract not found in sdhci-pltfm.h")
    except OSError as error:
        errors.append(f"cannot audit sdhci-pltfm.h: {error}")

    delegates = summaries.get("sdhci_delegates", []) if isinstance(
        summaries, dict) else []
    core_path = os.path.join(linux_root, "drivers", "mmc", "host", "sdhci.c")
    try:
        core_text = open(core_path, encoding="utf-8", errors="replace").read()
        for item in delegates:
            callee = item.get("callee", "")
            if not re.search(
                    rf"EXPORT_SYMBOL_GPL\s*\(\s*{re.escape(callee)}\s*\)",
                    core_text):
                errors.append(f"SDHCI core delegate {callee} is not exported")
    except OSError as error:
        if delegates:
            errors.append(f"cannot audit sdhci.c delegates: {error}")

    registers = {item["name"]: item for item in formal.get("register_map", [])}
    for op, body in accessor_ops:
        callee = body.get("evidence", {}).get("effective_callee")
        kind = next(iter(op))
        field = _field_of(body)
        if body.get("evidence", {}).get("summary_contract") != "linux.sdhci_ops":
            errors.append(f"{callee} lacks linux.sdhci_ops evidence")
        addr = body.get("addr", {})
        if "Computed" in addr and not _computed_is_lowerable(addr["Computed"]):
            errors.append(f"{callee} address is not safely lowerable")
        elif not ({"Computed", "Symbolic", "Fixed"} & set(addr)):
            errors.append(f"{callee} address is unresolved")
        if field and not _address_mentions_reg(body):
            errors.append(f"sdhci_ops.{field} address lost its register selector")
        if callee and callee.startswith("sdhci_be32bs_"):
            if field != "read_b" and body.get("evidence", {}).get(
                    "byte_order") != "big":
                errors.append(f"{callee} lost big-endian MMIO semantics")
            if field == "read_w" and not (
                    kind == "Read" and body.get("width") == "B2"
                    and _expr_has(addr.get("Computed"), op="BitXor")
                    and _expr_has(addr.get("Computed"), const=2)):
                errors.append("sdhci_be32bs_readw lost reg^2 addressing")
            if field == "read_b" and not (
                    kind == "Read" and body.get("width") == "B1"
                    and _expr_has(addr.get("Computed"), op="BitXor")
                    and _expr_has(addr.get("Computed"), const=3)):
                errors.append("sdhci_be32bs_readb lost reg^3 addressing")
        elif callee in _PUBLIC_ACCESSOR:
            if (kind, body.get("width")) != _PUBLIC_ACCESSOR[callee]:
                errors.append(
                    f"{callee} lowered as {(kind, body.get('width'))}, "
                    f"expected {_PUBLIC_ACCESSOR[callee]}")
        elif field:
            expected_width = _FIELD_WIDTH[field]
            if body.get("width") != expected_width:
                errors.append(
                    f"sdhci_ops.{field} uses {body.get('width')}, expected {expected_width}")
        symbolic = addr.get("Symbolic")
        if symbolic:
            register = registers.get(symbolic.get("register"))
            if register is None or int(register["offset"]) < 0:
                errors.append(f"{callee} symbolic register lacks a valid offset")

    for field, leaves in callback_leaves.items():
        if field.startswith("read_") and not any("Return" in op for op, _ in leaves):
            errors.append(f"sdhci_ops.{field} lacks a modeled return value")
    writew = callback_leaves.get("write_w", [])
    if any(body.get("evidence", {}).get("effective_callee")
           == "sdhci_be32bs_writew" for _op, body in writew):
        if not any(op.get("StateWrite", {}).get("field") == "xfer_mode_shadow"
                   for op, _body in writew):
            errors.append("sdhci_be32bs_writew lacks transfer-mode shadow write")
        if not any(op.get("StateRead", {}).get("field") == "xfer_mode_shadow"
                   for op, _body in writew):
            errors.append("sdhci_be32bs_writew lacks transfer-mode shadow replay")
        if not any("ReadModifyWrite" in op for op, _body in writew):
            errors.append("sdhci_be32bs_writew lacks aligned default RMW")
    return {
        "sdhci_accessor_oracle_required": True,
        "sdhci_accessor_oracle_passed": not errors,
        "sdhci_accessor_oracle_errors": errors,
        "sdhci_accessor_oracle_ops": len(accessor_ops),
        "sdhci_accessor_dispatch": (
            "sdhci_ops source-private/public contract" if private_dispatch
            else "sdhci_pltfm_ops direct ioaddr+reg"),
    }


def verify_sdhci_accessor_suite() -> dict:
    from extractor.extractor import ExtractorConfig, extract_ris
    from generator.subsystem_runner import portable_sdhci_accessor_only

    sources = {
        "npcm": "linux/drivers/mmc/host/sdhci-npcm.c",
        "dove": "linux/drivers/mmc/host/sdhci-dove.c",
        "hlwd": "linux/drivers/mmc/host/sdhci-of-hlwd.c",
    }
    extracted = {
        name: extract_ris(ExtractorConfig(source=os.path.join(ROOT, source)))
        for name, source in sources.items()
    }
    results = {
        name: verify_sdhci_accessor_source_contract(result.formal)
        for name, result in extracted.items()
    }
    portable = {
        name: portable_sdhci_accessor_only(
            result.formal, result.device_spec)
        for name, result in extracted.items()
    }
    if (not results["npcm"]["sdhci_accessor_oracle_passed"]
            or not portable["npcm"]):
        raise AssertionError(results["npcm"])
    for name in ("dove", "hlwd"):
        if (not results[name]["sdhci_accessor_oracle_passed"]
                or not portable[name]):
            raise AssertionError(results[name])

    mutated = copy.deepcopy(extracted["npcm"].formal)
    body = next(op["Read"] for module in mutated["modules"]
                for op in walk_leaf_ops(module["ops"]) if "Read" in op)
    body["width"] = "B2"
    mutation = verify_sdhci_accessor_source_contract(mutated)
    if mutation["sdhci_accessor_oracle_passed"]:
        raise AssertionError("SDHCI width mutation was not detected")
    mutated_hlwd = copy.deepcopy(extracted["hlwd"].formal)
    readw = next(
        op["Read"] for module in mutated_hlwd["modules"]
        for op in walk_leaf_ops(module["ops"])
        if "Read" in op and op["Read"].get("evidence", {}).get(
            "effective_callee") == "sdhci_be32bs_readw")
    for node in _expr_nodes(readw["addr"].get("Computed")):
        if node.get("Const") == 2:
            node["Const"] = 0
            break
    address_mutation = verify_sdhci_accessor_source_contract(mutated_hlwd)
    if address_mutation["sdhci_accessor_oracle_passed"]:
        raise AssertionError("SDHCI byte-swap address mutation was not detected")

    mutated_shadow = copy.deepcopy(extracted["hlwd"].formal)
    for module in mutated_shadow["modules"]:
        module["ops"] = [
            op for op in module["ops"]
            if not ("Cond" in op and any(
                leaf.get("StateWrite", {}).get("field") == "xfer_mode_shadow"
                for leaf in walk_leaf_ops([op])))]
    shadow_mutation = verify_sdhci_accessor_source_contract(mutated_shadow)
    if shadow_mutation["sdhci_accessor_oracle_passed"]:
        raise AssertionError("SDHCI shadow-state mutation was not detected")

    mutated_delay = copy.deepcopy(extracted["hlwd"].formal)
    delay = next(
        op["Delay"] for module in mutated_delay["modules"]
        for op in walk_leaf_ops(module["ops"]) if "Delay" in op)
    delay["cycles"] = {"Const": 0}
    delay_mutation = verify_sdhci_accessor_source_contract(mutated_delay)
    if delay_mutation["sdhci_accessor_oracle_passed"]:
        raise AssertionError("SDHCI delay mutation was not detected")

    return {
        "schema": 1,
        "cases": {name: {
            "source": sources[name],
            "contract_required": result["sdhci_accessor_oracle_required"],
            "contract_passed": result["sdhci_accessor_oracle_passed"],
            "portable": portable[name],
            "operations": result["sdhci_accessor_oracle_ops"],
            "errors": result["sdhci_accessor_oracle_errors"],
        } for name, result in results.items()},
        "mutations": [
            {"name": "npcm_accessor_width",
             "caught": not mutation["sdhci_accessor_oracle_passed"],
             "errors": mutation["sdhci_accessor_oracle_errors"]},
            {"name": "hlwd_byte_swap_address",
             "caught": not address_mutation["sdhci_accessor_oracle_passed"],
             "errors": address_mutation["sdhci_accessor_oracle_errors"]},
            {"name": "hlwd_transfer_shadow",
             "caught": not shadow_mutation["sdhci_accessor_oracle_passed"],
             "errors": shadow_mutation["sdhci_accessor_oracle_errors"]},
            {"name": "hlwd_write_delay",
             "caught": not delay_mutation["sdhci_accessor_oracle_passed"],
             "errors": delay_mutation["sdhci_accessor_oracle_errors"]},
        ],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    report = verify_sdhci_accessor_suite()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
