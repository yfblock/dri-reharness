"""Independent oracle for banked GPIO addressing and PM context loops."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.extractor import ExtractorConfig, extract_ris
from extractor.formal import walk_leaf_ops
from extractor.spec import default_bind
from generator import linux as linux_gen
from verification.subsystem_callback_oracle import _execute


REG = {
    "data": 0x00, "dir": 0x04, "inten": 0x30, "intmask": 0x34,
    "inttype": 0x38, "polarity": 0x3C, "debounce": 0x48,
    "eoi": 0x4C, "ext": 0x50,
}
V2 = {0x34: 0x44, 0x38: 0x34, 0x3C: 0x38, 0x40: 0x3C, 0x4C: 0x40}
CONTEXT_FIELDS = (
    "data", "dir", "ext", "int_en", "int_mask", "int_type",
    "int_pol", "int_deb", "wake_en",
)


def _seed() -> bytearray:
    return bytearray((0x5A + 37 * index) & 0xFF for index in range(0x1000))


def _read(memory: bytearray, offset: int) -> int:
    return sum(memory[offset + index] << (8 * index) for index in range(4))


def _write(memory: bytearray, offset: int, value: int) -> None:
    for index in range(4):
        memory[offset + index] = (value >> (8 * index)) & 0xFF


def _convert(offset: int, flags: int) -> int:
    return V2.get(offset, offset) if flags & 1 else offset


def _source_pm(flags: int, ports: list[int]) -> tuple[list, list, dict]:
    memory = _seed()
    trace_suspend = []
    context = {field: [0] * len(ports) for field in CONTEXT_FIELDS}
    context["wake_en"] = [0x01010101 * (index + 1)
                          for index in range(len(ports))]

    def read(offset: int) -> int:
        offset = _convert(offset, flags)
        value = _read(memory, offset)
        trace_suspend.append(("R", offset, value))
        return value

    def write(offset: int, value: int) -> None:
        offset = _convert(offset, flags)
        value &= 0xFFFFFFFF
        trace_suspend.append(("W", offset, value))
        _write(memory, offset, value)

    for index, bank in enumerate(ports):
        context["dir"][index] = read(REG["dir"] + bank * 0x0C)
        context["data"][index] = read(REG["data"] + bank * 0x0C)
        context["ext"][index] = read(REG["ext"] + bank * 0x04)
        if bank == 0:
            context["int_mask"][index] = read(REG["intmask"])
            context["int_en"][index] = read(REG["inten"])
            context["int_pol"][index] = read(REG["polarity"])
            context["int_type"][index] = read(REG["inttype"])
            context["int_deb"][index] = read(REG["debounce"])
            write(REG["intmask"], ~context["wake_en"][index])

    trace_resume = []

    def resume_write(offset: int, value: int) -> None:
        offset = _convert(offset, flags)
        value &= 0xFFFFFFFF
        trace_resume.append(("W", offset, value))
        _write(memory, offset, value)

    for index, bank in enumerate(ports):
        resume_write(REG["data"] + bank * 0x0C, context["data"][index])
        resume_write(REG["dir"] + bank * 0x0C, context["dir"][index])
        resume_write(REG["ext"] + bank * 0x04, context["ext"][index])
        if bank == 0:
            resume_write(REG["inttype"], context["int_type"][index])
            resume_write(REG["polarity"], context["int_pol"][index])
            resume_write(REG["debounce"], context["int_deb"][index])
            resume_write(REG["inten"], context["int_en"][index])
            resume_write(REG["intmask"], context["int_mask"][index])
            resume_write(REG["eoi"], 0xFFFFFFFF)
    return trace_suspend, trace_resume, context


def _formal_pm(formal: dict, flags: int, ports: list[int]) -> tuple[list, list, dict]:
    modules = {module["name"]: module for module in formal["modules"]}
    state = {
        "flags": flags, "nr_ports": len(ports), "ports_idx": list(ports),
        **{f"ports_ctx_{field}": [0] * len(ports)
           for field in CONTEXT_FIELDS},
    }
    state["ports_ctx_wake_en"] = [
        0x01010101 * (index + 1) for index in range(len(ports))]
    env = {
        "base": 0, "gpio->regs": 0, "gpio->flags": flags,
        "gpio->nr_ports": len(ports),
    }
    memory = _seed()
    suspend, _ = _execute(
        modules["dwapb_gpio_suspend"]["ops"], dict(env), memory, {}, state,
        {}, {"base": 0})
    resume, _ = _execute(
        modules["dwapb_gpio_resume"]["ops"], dict(env), memory, {}, state,
        {}, {"base": 0})
    context = {
        field: list(state[f"ports_ctx_{field}"]) for field in CONTEXT_FIELDS}
    return suspend, resume, context


def _verify_formal(formal: dict) -> list[str]:
    errors = []
    ports = [2, 0, 3, 1]
    for flags in (0, 1):
        expected = _source_pm(flags, ports)
        try:
            actual = _formal_pm(formal, flags, ports)
        except (KeyError, ValueError, ZeroDivisionError) as error:
            errors.append(f"flags={flags} interpreter failed: {error}")
            continue
        labels = ("suspend trace", "resume trace", "context state")
        for label, observed, source in zip(labels, actual, expected):
            if observed != source:
                errors.append(
                    f"flags={flags} {label} {observed} != source {source}")
    return errors


def _mutations(formal: dict) -> dict[str, dict]:
    results = {}

    def check(name: str, mutated: dict) -> None:
        errors = _verify_formal(mutated)
        results[name] = {"caught": bool(errors), "errors": errors}
        if not errors:
            raise AssertionError(f"DW APB oracle missed {name} mutation")

    mutated = copy.deepcopy(formal)
    suspend = next(m for m in mutated["modules"]
                   if m["name"] == "dwapb_gpio_suspend")
    changed = False
    for op in walk_leaf_ops(suspend["ops"]):
        body = op.get("Read") or op.get("Write")
        expr = (body or {}).get("addr", {}).get("Computed", {})
        right = expr.get("BinOp", {}).get("right", {})
        ite = right.get("Ite", {})
        if ite.get("else") == {"Const": 0x34} and ite.get("then") == {
                "Const": 0x44}:
            ite["then"] = {"Const": 0x48}
            changed = True
            break
    if not changed:
        raise AssertionError("DW APB v2 mutation found no INTMASK conversion")
    check("v2_offset", mutated)

    mutated = copy.deepcopy(formal)
    suspend = next(m for m in mutated["modules"]
                   if m["name"] == "dwapb_gpio_suspend")
    changed = False
    for op in walk_leaf_ops(suspend["ops"]):
        body = op.get("Read") or op.get("Write")
        expr = (body or {}).get("addr", {}).get("Computed")
        stack = [expr] if expr else []
        while stack and not changed:
            node = stack.pop()
            binop = node.get("BinOp", {})
            if (binop.get("op") == "Mul"
                    and binop.get("right") == {"Const": 12}):
                binop["right"] = {"Const": 8}
                changed = True
                break
            for value in node.values():
                if isinstance(value, dict):
                    stack.append(value)
        if changed:
            break
    check("bank_stride", mutated)

    mutated = copy.deepcopy(formal)
    suspend = next(m for m in mutated["modules"]
                   if m["name"] == "dwapb_gpio_suspend")
    next(op["Loop"] for op in suspend["ops"] if "Loop" in op)["count"] = {
        "Const": 1}
    check("loop_count", mutated)

    mutated = copy.deepcopy(formal)
    suspend = next(m for m in mutated["modules"]
                   if m["name"] == "dwapb_gpio_suspend")
    state_write = next(
        op["StateWrite"] for op in walk_leaf_ops(suspend["ops"])
        if "StateWrite" in op and op["StateWrite"]["field"] == "ports_ctx_dir")
    state_write["index"] = {"Const": 0}
    check("context_slot", mutated)

    mutated = copy.deepcopy(formal)
    resume = next(m for m in mutated["modules"]
                  if m["name"] == "dwapb_gpio_resume")
    loop = next(op["Loop"] for op in resume["ops"] if "Loop" in op)
    indexes = [index for index, op in enumerate(loop["body"]) if "Write" in op]
    loop["body"][indexes[0]], loop["body"][indexes[1]] = (
        loop["body"][indexes[1]], loop["body"][indexes[0]])
    check("resume_order", mutated)
    return results


def _verify_linux_lifecycle(code: str, model: dict) -> list[str]:
    errors = []

    def require(pattern: str, label: str) -> None:
        if not re.search(pattern, code, re.S):
            errors.append(f"missing {label}")

    require(r"struct\s+gpio_dwapb_priv_bank\s*\{.*?struct gpio_chip gc;"
            r".*?struct gpio_dwapb_priv \*parent;", "per-bank chip owner")
    require(r"g->banks\s*=\s*devm_kcalloc\([^;]+g->nr_ports",
            "bounded bank allocation")
    require(r"bank->gpio_bank_index\s*=\s*g->ports_idx\[bank_index\]",
            "per-bank selector copy")
    require(r"bank->gpio_sdata\s*=\s*readl\([^;]+gpio_bank_index",
            "per-bank data shadow")
    require(r"bank->gpio_sdir\s*=\s*readl\([^;]+gpio_bank_index",
            "per-bank direction shadow")
    require(r"gpiochip_get_data\(gc\).*?bank->parent", "callback owner rebind")
    require(r"bank->gpio_sdata\s*=", "callback data state isolation")
    require(r"bank->gpio_sdir\s*=", "callback direction state isolation")
    require(r"devm_gpiochip_add_data\([^;]+&bank->gc,\s*bank\)",
            "one registration per bank")
    for prop in model.get("ngpio_properties", []):
        require(rf'fwnode_property_read_u32\(child,\s*"{re.escape(prop)}"',
                f"ngpio property {prop}")
    irq = model.get("irq")
    if irq:
        require(rf"if\s*\(bank->gpio_bank_index\s*==\s*"
                rf"{int(irq['selector_value'])}\)", "source-selected IRQ bank")
        require(r"fwnode_irq_get\(child,\s*irq_index\)",
                "indexed parent IRQ discovery")
        require(r"bank->gc\.irq\.parents\s*=\s*bank->parent_irqs",
                "persistent parent IRQ ownership")
        require(r"bank->gc\.irq\.parent_handler_data\s*=\s*&bank->gc",
                "parent handler bank identity")
        require(r"bank->gc\.irq\.parent_handler\s*=\s*"
                r"gpio_dwapb_banked_irq_handler", "parent IRQ handler")
        require(r"generic_handle_domain_irq\(gc->irq.domain,\s*hwirq\)",
                "IRQ domain dispatch")
        require(r"dwapb_irq_ack\([^}]+writel\(bit,", "IRQ acknowledge bit")
        require(r"dwapb_irq_mask\([^}]+val\s*=\s*val\s*\|\s*bit",
                "IRQ mask set-bit transform")
        require(r"dwapb_irq_unmask\([^}]+val\s*=\s*val\s*&\s*~bit",
                "IRQ unmask clear-bit transform")
        require(r"dwapb_irq_set_type\([^}]+case IRQ_TYPE_EDGE_BOTH:"
                r".*?case IRQ_TYPE_LEVEL_LOW:", "IRQ type switch semantics")
    if "g->gpio_bank_index" in code:
        errors.append("callbacks retain shared gpio bank selector")
    if "g->gpio_sdata" in code or "g->gpio_sdir" in code:
        errors.append("callbacks retain shared GPIO shadow state")
    if "REHARNESS_UNSUPPORTED" in code:
        errors.append("Linux lifecycle remains explicitly unsupported")
    return errors


def _linux_mutations(code: str, model: dict) -> dict[str, dict]:
    results = {}

    def check(name: str, mutated: str) -> None:
        errors = _verify_linux_lifecycle(mutated, model)
        results[name] = {"caught": bool(errors), "errors": errors}
        if not errors:
            raise AssertionError(f"DW APB Linux oracle missed {name} mutation")

    check("shared_bank_selector", code.replace(
        "bank->gpio_bank_index = g->ports_idx[bank_index];",
        "bank->gpio_bank_index = g->ports_idx[0];", 1))
    check("shared_data_shadow", code.replace(
        "bank->gpio_sdata = (", "g->gpio_sdata = (", 1))
    check("single_chip_registration", code.replace(
        "&bank->gc, bank);", "&g->gc, g);", 1))
    irq = model.get("irq")
    if irq:
        selector = int(irq["selector_value"])
        check("irq_bank_selector", code.replace(
            f"bank->gpio_bank_index == {selector}",
            f"bank->gpio_bank_index == {selector + 1}", 1))
        check("parent_irq_handler", code.replace(
            "bank->gc.irq.parent_handler = gpio_dwapb_banked_irq_handler;",
            "bank->gc.irq.parent_handler = NULL;", 1))
        check("irq_ack_value", code.replace(
            "writel(bit,", "writel(0,", 1))
        check("irq_mask_transform", code.replace(
            "val = val |bit;", "val = val & ~bit;", 1))
        check("irq_type_semantics", code.replace(
            "case IRQ_TYPE_EDGE_BOTH:", "case IRQ_TYPE_NONE:", 1))
    return results


def verify_dwapb_banked() -> dict:
    source = os.path.join(ROOT, "linux", "drivers", "gpio", "gpio-dwapb.c")
    database = os.path.join(
        ROOT, "output", "zero-shot-contexts", "compile_commands.json")
    result = extract_ris(ExtractorConfig(
        source=source,
        compile_commands=database if os.path.isfile(database) else None,
        compile_context_mode="required" if os.path.isfile(database) else "auto"))
    errors = _verify_formal(result.formal)
    if errors:
        raise AssertionError("; ".join(errors))
    mutations = _mutations(result.formal)
    summary = result.formal["metadata"]["subsystem_summary_analysis"][
        "summaries"]["gpio_generic"][0]
    model = summary["bank_model"]
    code = linux_gen.generate(
        result.formal, result.device_spec,
        default_bind(result.device_spec, "linux"), result.facts)
    linux_errors = _verify_linux_lifecycle(code, model)
    if linux_errors:
        raise AssertionError("; ".join(linux_errors))
    linux_mutations = _linux_mutations(code, model)
    return {
        "schema": 1,
        "source": "linux/drivers/gpio/gpio-dwapb.c",
        "cases": 2,
        "ports": [2, 0, 3, 1],
        "passed": True,
        "linux_lifecycle_passed": True,
        "mutations": mutations,
        "linux_mutations": linux_mutations,
        "mutations_caught": (
            sum(item["caught"] for item in mutations.values())
            + sum(item["caught"] for item in linux_mutations.values())),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = verify_dwapb_banked()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
