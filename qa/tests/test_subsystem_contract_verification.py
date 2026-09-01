from __future__ import annotations

import json

if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401

from subsystem_contract_verification import (  # noqa: E402
    verify_contract_summaries,
)


GPIO_CONTRACT = {
    "id": "gpio-generic",
    "subsystem": "gpio",
    "callback_keys": [
        "gpio_chip.get",
        "gpio_chip.set",
        "gpio_chip.direction_input",
        "gpio_chip.direction_output",
    ],
    "summary_groups": ["gpio_generic"],
    "summary_contracts": ["linux.gpio_generic_chip_config"],
}


def _formal(*, callbacks=None, unmodeled=None):
    callbacks = callbacks or [
        "gpio_chip.get",
        "gpio_chip.set",
        "gpio_chip.direction_input",
        "gpio_chip.direction_output",
    ]
    evidence = [
        {
            "library_callback": callback,
            "summary_contract": "linux.gpio_generic_chip_config",
            "subsystem_summary": "gpio_generic",
        }
        for callback in callbacks
    ]
    return {
        "metadata": {
            "subsystem_summary_analysis": {
                "summaries": {
                    "gpio_generic": [{
                        "function": "probe",
                        "callbacks": callbacks,
                    }],
                    "unmodeled_callbacks": unmodeled or [],
                },
            },
        },
        "modules": [{
            "name": "probe",
            "ops": [{"Read": {"evidence": item}} for item in evidence],
        }],
    }


def test_contract_summary_verifier_accepts_complete_data_driven_summary():
    report = verify_contract_summaries(_formal(), [GPIO_CONTRACT])

    assert report["status"] == "pass"
    assert report["scope"] == "extractor-metadata"
    row = report["contracts"][0]
    assert row["detected"] is True
    assert row["summary_present"] is True
    assert row["summary_complete"] is True
    assert row["static_verified"] is True
    assert row["errors"] == []
    json.dumps(report)


def test_contract_summary_verifier_does_not_treat_detection_without_summary_as_pass():
    report = verify_contract_summaries(
        {"metadata": {"subsystem_summary_analysis": {"summaries": {}}}},
        [GPIO_CONTRACT],
    )

    assert report["status"] == "inconclusive"
    row = report["contracts"][0]
    assert row["detected"] is True
    assert row["summary_present"] is False
    assert row["static_verified"] is False
    assert "missing_summary_evidence" in row["inconclusive_reasons"]


def test_contract_summary_verifier_rejects_unmodeled_callback():
    report = verify_contract_summaries(
        _formal(unmodeled=[{
            "summary_contract": "linux.gpio_generic_chip_config",
            "callback": "gpio_chip.set",
        }]),
        [GPIO_CONTRACT],
    )

    assert report["status"] == "fail"
    row = report["contracts"][0]
    assert row["summary_complete"] is False
    assert row["static_verified"] is False
    assert any(error.startswith("unmodeled_callback:")
               for error in row["errors"])


def test_contract_without_summary_declaration_is_inconclusive():
    contract = {
        "id": "clock-generic",
        "subsystem": "clock",
        "callback_keys": ["clk_ops"],
        "summary_groups": [],
        "summary_contracts": [],
    }

    report = verify_contract_summaries(
        {"modules": [{"ops": [{"Read": {"evidence": {
            "library_callback": "clk_ops.recalc_rate",
        }}}]}]},
        [contract],
    )

    assert report["status"] == "inconclusive"
    assert report["contracts"][0]["static_verified"] is False
    assert report["contracts"][0]["summary_present"] is False
