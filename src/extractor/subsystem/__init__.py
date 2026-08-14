"""Subsystem summary inference dispatcher."""
from __future__ import annotations

from .gpio import infer_gpio_generic_summaries
from .sdhci import infer_sdhci_ops_summaries
from .virtio import infer_virtio_state_summaries


def infer_subsystem_summaries(funcs: list[Func], extractions: dict,
                              macros, tu) -> tuple[list[Func], dict, dict]:
    virtio_stats = infer_virtio_state_summaries(funcs, extractions, tu)
    gpio_funcs, gpio_extractions, gpio_stats = infer_gpio_generic_summaries(
        funcs, extractions, macros, tu)
    (sdhci_funcs, sdhci_extractions, sdhci_stats,
     unmodeled, delegates) = infer_sdhci_ops_summaries(
        funcs, extractions, macros)
    combined = dict(gpio_extractions)
    combined.update(sdhci_extractions)
    return gpio_funcs + sdhci_funcs, combined, {
        "gpio_generic": gpio_stats,
        "sdhci_ops": sdhci_stats,
        "sdhci_delegates": delegates,
        "virtio_state": virtio_stats,
        "unmodeled_callbacks": unmodeled,
    }
