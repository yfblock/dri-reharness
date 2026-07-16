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


def verify_sdhci_accessor_source_contract(formal: dict) -> dict:
    accessor_ops = []
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = op.get("Read") or op.get("Write") or op.get("ReadModifyWrite")
            if (body and body.get("evidence", {}).get("subsystem_summary")
                    == "sdhci_accessor"):
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
    if not re.search(r"\bsdhci_pltfm_init\s*\(", source_text):
        errors.append("source does not bind host through sdhci_pltfm_init")
    if not pdata:
        errors.append("source has no auditable sdhci_pltfm_data initializer")
    elif any(re.search(r"\.\s*ops\s*=", body) for body in pdata):
        errors.append("source platform data may install private SDHCI accessors")

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

    registers = {item["name"]: item for item in formal.get("register_map", [])}
    expected = {
        "sdhci_readl": ("Read", "B4"),
        "sdhci_readw": ("Read", "B2"),
        "sdhci_readb": ("Read", "B1"),
        "sdhci_writel": ("Write", "B4"),
        "sdhci_writew": ("Write", "B2"),
        "sdhci_writeb": ("Write", "B1"),
    }
    for op, body in accessor_ops:
        callee = body.get("evidence", {}).get("effective_callee")
        contract = expected.get(callee)
        kind = next(iter(op))
        if contract is None:
            errors.append(f"unknown SDHCI accessor {callee}")
            continue
        if (kind, body.get("width")) != contract:
            errors.append(
                f"{callee} lowered as {(kind, body.get('width'))}, expected {contract}")
        symbolic = body.get("addr", {}).get("Symbolic")
        if not symbolic:
            errors.append(f"{callee} address is not symbolic ioaddr+register")
            continue
        register = registers.get(symbolic.get("register"))
        if register is None:
            errors.append(f"{callee} register lacks a resolved offset")
        elif int(register["offset"]) < 0:
            errors.append(f"{callee} register offset is invalid")
    return {
        "sdhci_accessor_oracle_required": True,
        "sdhci_accessor_oracle_passed": not errors,
        "sdhci_accessor_oracle_errors": errors,
        "sdhci_accessor_oracle_ops": len(accessor_ops),
        "sdhci_accessor_dispatch": "sdhci_pltfm_ops direct ioaddr+reg",
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
        if portable[name]:
            raise AssertionError(f"SDHCI negative control accepted: {name}")

    mutated = copy.deepcopy(extracted["npcm"].formal)
    body = next(
        op["Read"] for module in mutated["modules"]
        for op in walk_leaf_ops(module["ops"]) if "Read" in op)
    body["width"] = "B2"
    mutation = verify_sdhci_accessor_source_contract(mutated)
    if mutation["sdhci_accessor_oracle_passed"]:
        raise AssertionError("SDHCI width mutation was not detected")
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
        "mutation": {
            "name": "npcm_accessor_width",
            "caught": not mutation["sdhci_accessor_oracle_passed"],
            "errors": mutation["sdhci_accessor_oracle_errors"],
        },
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
