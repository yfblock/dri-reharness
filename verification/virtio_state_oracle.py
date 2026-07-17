"""Source and mutation oracle for virtio config/queue state lowering."""
from __future__ import annotations

import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.formal import walk_all_ops, walk_leaf_ops


def _contract_ops(formal: dict):
    for module in formal.get("modules", []):
        for op in walk_leaf_ops(module.get("ops", [])):
            body = op.get("StateRead") or op.get("StateWrite")
            if body and body.get("evidence", {}).get("summary_contract") in {
                    "linux.virtio_config", "linux.virtqueue",
                    "linux.virtio.lifecycle"}:
                yield module["name"], op, body


def verify_virtio_state_contract(formal: dict) -> dict:
    operations = list(_contract_ops(formal))
    if not operations:
        return {
            "virtio_state_oracle_required": False,
            "virtio_state_oracle_passed": True,
            "virtio_state_oracle_errors": [],
            "virtio_state_oracle_ops": 0,
        }
    errors: list[str] = []
    source = formal.get("metadata", {}).get("source", "")
    try:
        text = open(source, encoding="utf-8", errors="replace").read()
    except OSError as error:
        text = ""
        errors.append(f"cannot read source: {error}")
    required_source = {
        "virtio_find_vqs": r"\bvirtio_find_vqs\s*\([^;]*\b2\b",
        "virtio config select": r"\bvirtio_cwrite_le\s*\([^;]*\bselect\b",
        "virtqueue completion": r"\bvirtqueue_get_buf\s*\(",
        "virtqueue notify": r"\bvirtqueue_kick\s*\(",
        "virtio lifecycle": r"\bstruct\s+virtio_driver\b",
    }
    for label, pattern in required_source.items():
        if not re.search(pattern, text, re.S):
            errors.append(f"source lacks {label} contract")

    fields = {}
    by_module: dict[str, list[tuple[dict, dict]]] = {}
    for module, op, body in operations:
        fields.setdefault(body.get("field"), []).append((op, body))
        by_module.setdefault(module, []).append((op, body))
        if body.get("reliability") in {"Unsupported", "Unknown"}:
            errors.append(f"{module}:{body.get('field')} is not reliable")
    for field in ("virtio_cfg_select", "virtio_cfg_subsel", "virtio_cfg_size",
                  "virtio_evt_available", "virtio_evt_completed",
                  "virtio_sts_outstanding", "virtio_evt_notified",
                  "virtio_sts_notified", "ready"):
        if field not in fields:
            errors.append(f"missing virtio state field {field}")

    def has_write(field: str, module_pattern: str | None = None,
                  value: int | None = None) -> bool:
        for module, op, body in operations:
            if "StateWrite" not in op or body.get("field") != field:
                continue
            if module_pattern and not re.search(module_pattern, module):
                continue
            if value is not None and body.get("value", {}).get("Const") != value:
                continue
            return True
        return False

    if not has_write("virtio_evt_notified"):
        errors.append("event queue notify transition is missing")
    if not has_write("virtio_sts_notified"):
        errors.append("status queue notify transition is missing")
    for pattern in (r"remove", r"freeze"):
        if not has_write("ready", pattern, 0):
            errors.append(f"{pattern} lifecycle does not clear ready")
    for pattern in (r"probe", r"restore"):
        if not has_write("ready", pattern, 1):
            errors.append(f"{pattern} lifecycle does not restore ready")

    loops = [op["Loop"] for module in formal.get("modules", [])
             for op in walk_all_ops(module.get("ops", [])) if "Loop" in op]
    if not loops:
        errors.append("virtqueue/config loops are not represented")
    for loop in loops:
        if not (loop.get("reliability") == "Exact" and loop.get("bounded")):
            errors.append("virtio loop lacks an exact finite bound")
        count = loop.get("count", {})
        if "Const" in count and int(count["Const"]) > 64:
            errors.append(f"virtio loop bound {count['Const']} exceeds source limit")

    return {
        "virtio_state_oracle_required": True,
        "virtio_state_oracle_passed": not errors,
        "virtio_state_oracle_errors": errors,
        "virtio_state_oracle_ops": len(operations),
        "virtio_state_fields": sorted(field for field in fields if field),
    }


def verify_virtio_state_suite() -> dict:
    from extractor.extractor import ExtractorConfig, extract_ris

    source = "linux/drivers/virtio/virtio_input.c"
    result = extract_ris(ExtractorConfig(source=os.path.join(ROOT, source)))
    baseline = verify_virtio_state_contract(result.formal)
    if not baseline["virtio_state_oracle_passed"]:
        raise AssertionError(baseline)

    mutations = []

    def check(name: str, mutate):
        formal = copy.deepcopy(result.formal)
        mutate(formal)
        report = verify_virtio_state_contract(formal)
        if report["virtio_state_oracle_passed"]:
            raise AssertionError(f"virtio mutation not detected: {name}")
        mutations.append({
            "name": name, "caught": True,
            "errors": report["virtio_state_oracle_errors"],
        })

    def remove_field(formal, field, module=None):
        for item in formal["modules"]:
            if module and not re.search(module, item["name"]):
                continue
            item["ops"] = [op for op in item["ops"] if not any(
                (leaf.get("StateRead") or leaf.get("StateWrite") or {}).get(
                    "field") == field for leaf in walk_leaf_ops([op]))]

    check("config_selector", lambda formal: remove_field(
        formal, "virtio_cfg_select"))
    check("event_notify", lambda formal: remove_field(
        formal, "virtio_evt_notified"))
    check("status_ownership", lambda formal: remove_field(
        formal, "virtio_sts_outstanding"))
    check("freeze_ready", lambda formal: remove_field(
        formal, "ready", r"freeze"))

    def unbound_loop(formal):
        loop = next(op["Loop"] for module in formal["modules"]
                    for op in walk_all_ops(module["ops"]) if "Loop" in op)
        loop["bounded"] = False
        loop["reliability"] = "Conservative"

    check("queue_loop_bound", unbound_loop)
    return {
        "schema": 1,
        "case": source,
        "contract": baseline,
        "mutations": mutations,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    report = verify_virtio_state_suite()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
