from __future__ import annotations

from pathlib import Path

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from subsystem_candidate_validators import (  # noqa: E402
    CandidateValidatorRegistry,
    validate_candidate_contracts,
)
from subsystem_contracts import build_default_contract_registry  # noqa: E402


def test_contract_catalog_declares_candidate_validator_for_gpio():
    match = next(item for item in build_default_contract_registry().detect(
        "struct gpio_chip chip; gpiochip_add_data(&chip, NULL);"
    ) if item.contract_id == "gpio-generic")

    assert match.candidate_validator == "linux.gpio-generic"


def test_candidate_validator_registry_dispatches_declared_validator():
    registry = CandidateValidatorRegistry()

    def validate(evidence, source):
        assert evidence["marker"] == "source"
        assert "candidate" in source
        return ["test_validator_error"]

    registry.register("test.validator", validate)
    report = validate_candidate_contracts(
        {"marker": "source"},
        "candidate() {}",
        contracts=[{"id": "test", "candidate_validator": "test.validator"}],
        registry=registry,
    )

    assert report == {
        "validators": ["test.validator"],
        "errors": ["test_validator_error"],
    }


def test_unknown_declared_candidate_validator_fails_closed():
    report = validate_candidate_contracts(
        {},
        "candidate() {}",
        contracts=[{"id": "test", "candidate_validator": "missing.validator"}],
        registry=CandidateValidatorRegistry(),
    )

    assert report["validators"] == ["missing.validator"]
    assert report["errors"] == [
        "unknown_candidate_validator:missing.validator"
    ]
