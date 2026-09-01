"""Registered candidate checks for Linux subsystem contracts.

The Linux candidate gate owns generic source and registration invariants.  A
subsystem contract may additionally name a validator here when its callback
or helper semantics cannot be expressed by those generic invariants.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import re
from typing import Any, Mapping


CandidateValidator = Callable[[Mapping[str, Any], str], Iterable[str]]


class CandidateValidatorRegistry:
    """Explicit registry for subsystem-specific candidate validators."""

    def __init__(self) -> None:
        self._validators: dict[str, CandidateValidator] = {}

    def register(self, validator_id: str, validator: CandidateValidator,
                 *, replace: bool = False) -> None:
        if not isinstance(validator_id, str) or not validator_id.strip():
            raise ValueError("candidate validator id must be non-empty")
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", validator_id):
            raise ValueError("candidate validator id is unsafe")
        if not callable(validator):
            raise TypeError("candidate validator must be callable")
        if validator_id in self._validators and not replace:
            raise ValueError(
                f"candidate validator already registered: {validator_id}")
        self._validators[validator_id] = validator

    def get(self, validator_id: str) -> CandidateValidator | None:
        return self._validators.get(validator_id)


def _function_body(source: str, name: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", source)
    if match is None:
        return None
    start = source.find("{", match.start())
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    return None


def _facts_helper_calls(evidence: Mapping[str, Any]) -> set[str]:
    directory = evidence.get("directory")
    if not isinstance(directory, str):
        return set()
    helpers: set[str] = set()
    for path in sorted(Path(directory).glob("*.facts")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        in_helpers = False
        for line in lines:
            if line == "helper_calls:":
                in_helpers = True
                continue
            if in_helpers and line.startswith("  - "):
                value = line[4:].strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    helpers.add(value[1:-1])
                continue
            if in_helpers:
                break
    return helpers


def _gpio_generic_validator(evidence: Mapping[str, Any],
                            source: str) -> list[str]:
    """Validate nested GPIO IRQ ownership and generic-chip argument order."""
    helpers = _facts_helper_calls(evidence)
    errors: list[str] = []
    if "gpio_irq_chip_set_chip" in helpers:
        if re.search(r"(?:->|\.)num_parents\s*=", source) is None:
            errors.append("missing_gpio_irq_parent_count")
        if re.search(r"(?:->|\.)parents\s*=", source) is None:
            errors.append("missing_gpio_irq_parents")
        if re.search(r"(?:->|\.)parents\s*\[[^]]+\]\s*=", source) is None:
            errors.append("missing_gpio_irq_parent_value")

        # gpiolib stores a gpio_chip in irq_data chip-data for a GPIO IRQ
        # domain.  Preserve that owner conversion before private state access.
        callbacks = evidence.get("bind", {}).get("callbacks", {})
        irq_functions = {
            function for table_field, function in callbacks.items()
            if isinstance(table_field, str)
            and table_field.startswith("irq_chip.")
            and isinstance(function, str)
        } if isinstance(callbacks, Mapping) else set()
        unsafe_helpers: set[str] = set()
        for match in re.finditer(
                r"(?:static\s+)?(?:inline\s+)?[^{;]+\b([A-Za-z_]\w*)"
                r"\s*\([^;{}]*\)\s*\{", source):
            name = match.group(1)
            body = _function_body(source, name)
            if (body is not None
                    and "irq_data_get_irq_chip_data" in body
                    and "gpiochip_get_data" not in body):
                unsafe_helpers.add(name)
        for function in sorted(irq_functions):
            body = _function_body(source, function)
            if body is None:
                continue
            direct = ("irq_data_get_irq_chip_data" in body
                      and "gpiochip_get_data" not in body)
            indirect = any(re.search(rf"\b{re.escape(helper)}\s*\(", body)
                           for helper in unsafe_helpers)
            if direct or indirect:
                errors.append(f"irq_callback_owner_rebind:{function}")

    if "gpio_generic_chip_init" in helpers:
        compact_source = re.sub(r"\s+", "", source)
        if re.search(
                r"gpio_generic_chip_init\(\s*&[A-Za-z_]\w*\s*,\s*"
                r"&[A-Za-z_]\w*(?:->|\.)gc\s*\)", compact_source):
            errors.append("gpio_generic_chip_init_argument_order")
    return errors


def build_default_candidate_validator_registry() -> CandidateValidatorRegistry:
    registry = CandidateValidatorRegistry()
    registry.register("linux.gpio-generic", _gpio_generic_validator)
    return registry


def _declared_validator_ids(
        contracts: Iterable[Mapping[str, Any]],
        ) -> list[str]:
    result: list[str] = []
    for contract in contracts:
        if not isinstance(contract, Mapping):
            continue
        validator_id = contract.get("candidate_validator")
        if isinstance(validator_id, str) and validator_id:
            if validator_id not in result:
                result.append(validator_id)
    return result


def validate_candidate_contracts(
        evidence: Mapping[str, Any], source: str,
        *, contracts: Iterable[Mapping[str, Any]] | None = None,
        registry: CandidateValidatorRegistry | None = None,
        root: str | Path | None = None,
        ) -> dict[str, Any]:
    """Run declared subsystem validators and aggregate fail-closed errors."""
    selected_registry = (registry or build_default_candidate_validator_registry())
    if contracts is None:
        from subsystem_contracts import build_default_contract_registry

        selected_contracts = build_default_contract_registry(root).detect(
            source, evidence=evidence)
        validator_ids = [item.candidate_validator for item in selected_contracts
                         if item.candidate_validator]
    else:
        validator_ids = _declared_validator_ids(contracts)
    validator_ids = list(dict.fromkeys(validator_ids))

    errors: list[str] = []
    for validator_id in validator_ids:
        validator = selected_registry.get(validator_id)
        if validator is None:
            errors.append(f"unknown_candidate_validator:{validator_id}")
            continue
        try:
            result = validator(evidence, source)
            errors.extend(str(error) for error in result if error)
        except (OSError, TypeError, ValueError) as exc:
            errors.append(
                f"candidate_validator_error:{validator_id}:{type(exc).__name__}")
    return {
        "validators": validator_ids,
        "errors": sorted(set(errors)),
    }


__all__ = [
    "CandidateValidatorRegistry", "build_default_candidate_validator_registry",
    "validate_candidate_contracts",
]
