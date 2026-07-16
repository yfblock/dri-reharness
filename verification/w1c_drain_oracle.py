"""Contract and runtime oracle for masked W1C interrupt-drain loops."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.formal import walk_all_ops
from generator.subsystem_runner import w1c_drain_plan


def verify_w1c_drain_contract(formal: dict, device_spec) -> dict:
    plan = w1c_drain_plan(formal, device_spec)
    all_proofs = [
        op["Loop"] for module in formal.get("modules", [])
        for op in walk_all_ops(module.get("ops", []))
        if "Loop" in op and op["Loop"].get("proof_kind") == "masked_w1c_drain"]
    if not all_proofs:
        return {
            "w1c_drain_oracle_required": False,
            "w1c_drain_contract_passed": True,
            "w1c_drain_oracle_errors": [],
            "w1c_drain_loops": 0,
        }
    errors = []
    if len(plan) != len(all_proofs):
        errors.append(f"runner covers {len(plan)}/{len(all_proofs)} W1C loops")
    for entry in plan:
        loop = entry["loop"]
        guards = loop.get("guard_ops", [])
        body = loop.get("body", [])
        if len(guards) != 2 or not all("Read" in op for op in guards):
            errors.append(f"{entry['module']}: guard is not two MMIO reads")
            continue
        if len(body) != 1 or "Write" not in body[0]:
            errors.append(f"{entry['module']}: body is not one acknowledge write")
            continue
        pending, mask = guards[0]["Read"], guards[1]["Read"]
        acknowledge = body[0]["Write"]
        if pending.get("addr") != acknowledge.get("addr"):
            errors.append(f"{entry['module']}: ack does not target pending register")
        if acknowledge.get("evidence", {}).get("write_semantics") != "w1c":
            errors.append(f"{entry['module']}: ack lacks W1C semantics")
        expected_guard = {"BinOp": {
            "op": "BitAnd", "left": {"Var": pending.get("var")},
            "right": {"Var": mask.get("var")},
        }}
        if loop.get("guard_value") != expected_guard:
            errors.append(f"{entry['module']}: guard value is not pending & mask")
        if loop.get("max_iterations") != 1 or not loop.get(
                "environment_assumptions"):
            errors.append(f"{entry['module']}: bound lacks explicit quiescence assumption")
    return {
        "w1c_drain_oracle_required": True,
        "w1c_drain_contract_passed": not errors,
        "w1c_drain_oracle_errors": errors,
        "w1c_drain_loops": len(all_proofs),
    }


def _offset(body: dict, registers: dict[str, int]) -> int:
    addr = body["addr"]
    if "Symbolic" in addr:
        return registers[addr["Symbolic"]["register"]]
    return int(addr["Fixed"]["offset"])


def _width(body: dict) -> int:
    return {"B1": 1, "B2": 2, "B4": 4, "B8": 8}[body["width"]]


def _seed_read(offset: int, width: int) -> int:
    return sum(((0x5A + 37 * (offset + index)) & 0xFF) << (8 * index)
               for index in range(width))


def _segments(output: str) -> list[dict]:
    active = False
    current = None
    segments = []
    for line in output.splitlines():
        if "[reharness-w1c-begin]" in line:
            active = True
            continue
        if "[reharness-w1c-end]" in line:
            active = False
            current = None
            continue
        marker = re.search(r"\[reharness-w1c\]\s+([A-Za-z_]\w*)", line)
        if active and marker:
            current = {"module": marker.group(1), "trace": []}
            segments.append(current)
            continue
        operation = re.search(
            r"\[trace\s+\d+\]\s+(R|W)\s+0x([0-9a-fA-F]+)\s+=\s+0x([0-9a-fA-F]+)",
            line)
        if active and current is not None and operation:
            current["trace"].append((
                operation.group(1), int(operation.group(2), 16),
                int(operation.group(3), 16)))
    return segments


def verify_w1c_drain_runtime(formal: dict, device_spec, output: str) -> dict:
    contract = verify_w1c_drain_contract(formal, device_spec)
    if not contract["w1c_drain_oracle_required"]:
        return {**contract, "w1c_drain_runtime_passed": True}
    plan = w1c_drain_plan(formal, device_spec)
    registers = {item["name"]: int(item["offset"])
                 for item in formal.get("register_map", [])}
    observed = _segments(output)
    errors = list(contract["w1c_drain_oracle_errors"])
    if len(observed) != len(plan):
        errors.append(f"observed {len(observed)}/{len(plan)} W1C drain calls")
    for index, entry in enumerate(plan):
        if index >= len(observed):
            break
        actual = observed[index]
        loop = entry["loop"]
        pending = loop["guard_ops"][0]["Read"]
        mask = loop["guard_ops"][1]["Read"]
        pending_offset = _offset(pending, registers)
        mask_offset = _offset(mask, registers)
        pending_value = _seed_read(pending_offset, _width(pending))
        mask_value = _seed_read(mask_offset, _width(mask))
        status = pending_value & mask_value
        expected = [
            ("R", pending_offset, pending_value),
            ("R", mask_offset, mask_value),
        ]
        if status:
            expected.append(("W", pending_offset, status))
            pending_value &= ~status
            expected.extend([
                ("R", pending_offset, pending_value),
                ("R", mask_offset, mask_value),
            ])
        if actual["module"] != entry["module"] or actual["trace"] != expected:
            errors.append(
                f"{entry['module']}: runtime {actual} != expected {expected}")
    return {
        **contract,
        "w1c_drain_runtime_passed": not errors,
        "w1c_drain_oracle_errors": errors,
        "w1c_drain_calls_executed": len(observed),
    }


def verify_w1c_drain_suite() -> dict:
    from extractor.extractor import ExtractorConfig, extract_ris
    from extractor.spec import default_bind
    from generator import harness

    source = "linux/drivers/gpio/gpio-altera.c"
    result = extract_ris(ExtractorConfig(source=os.path.join(ROOT, source)))
    contract = verify_w1c_drain_contract(result.formal, result.device_spec)
    if not contract["w1c_drain_contract_passed"]:
        raise AssertionError(contract)

    code = harness.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "harness"))
    with tempfile.TemporaryDirectory() as directory:
        source_path = os.path.join(directory, "altera-harness.c")
        binary = os.path.join(directory, "altera-harness")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write(code)
        compiled = subprocess.run(
            ["cc", "-o", binary, source_path],
            capture_output=True, text=True)
        if compiled.returncode != 0:
            raise AssertionError(compiled.stderr)
        executed = subprocess.run(
            [binary], capture_output=True, text=True)
        if executed.returncode != 0:
            raise AssertionError(executed.stderr)
    runtime = verify_w1c_drain_runtime(
        result.formal, result.device_spec, executed.stdout)
    if not runtime["w1c_drain_runtime_passed"]:
        raise AssertionError(runtime)

    mutated = copy.deepcopy(result.formal)
    loop = next(
        op["Loop"] for module in mutated["modules"]
        for op in walk_all_ops(module["ops"])
        if "Loop" in op
        and op["Loop"].get("proof_kind") == "masked_w1c_drain")
    loop["body"][0]["Write"]["addr"] = copy.deepcopy(
        loop["guard_ops"][1]["Read"]["addr"])
    mutation = verify_w1c_drain_contract(mutated, result.device_spec)
    if mutation["w1c_drain_contract_passed"]:
        raise AssertionError("W1C acknowledge-address mutation was not detected")
    return {
        "schema": 1,
        "source": source,
        "contract": contract,
        "runtime": runtime,
        "mutation": {
            "name": "acknowledge_mask_register",
            "caught": not mutation["w1c_drain_contract_passed"],
            "errors": mutation["w1c_drain_oracle_errors"],
        },
        "environment_assumption": (
            "no new pending bits arrive while the generated handler drains "
            "the observed pending-and-mask snapshot"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    report = verify_w1c_drain_suite()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
