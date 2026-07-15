#!/usr/bin/env python3
"""Runtime differential oracle over an original FTGPIO driver callback."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from extractor.ast_model import source_text, target_functions  # noqa: E402
from extractor.tu import parse_translation_unit  # noqa: E402
from verification.ris_trace_oracle import _ris_trace  # noqa: E402


def _original_function_source(source: str) -> str:
    tu, _diagnostics = parse_translation_unit(source)
    function = next(func for func in target_functions(tu, source)
                    if func.name == "ftgpio_gpio_ack_irq")
    return source_text(tu, function.cursor)


def _compile_original(directory: str, function_source: str) -> str:
    combined = os.path.join(directory, "ftgpio_ack_original.c")
    with open(combined, "w", encoding="utf-8") as handle:
        handle.write(r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define __iomem
#define GPIO_INT_CLR 0x30
#define BIT(n) (1u << (n))
struct irq_data { unsigned int hwirq; };
struct gpio_chip { int unused; };
struct ftgpio_gpio { unsigned char *base; };
static unsigned char memory[256];
static struct gpio_chip chip;
static struct ftgpio_gpio gpio = { memory };
static struct gpio_chip *irq_data_get_irq_chip_data(struct irq_data *d)
{ (void)d; return &chip; }
static struct ftgpio_gpio *gpiochip_get_data(struct gpio_chip *gc)
{ (void)gc; return &gpio; }
static unsigned int irqd_to_hwirq(struct irq_data *d) { return d->hwirq; }
static void writel(uint32_t value, void *address)
{
    printf("W %ld %u\n", (long)((unsigned char *)address - memory), value);
}
''')
        handle.write("\n")
        handle.write(function_source)
        handle.write(r'''
int main(int argc, char **argv)
{
    struct irq_data data;
    if (argc != 2) return 2;
    data.hwirq = (unsigned int)strtoul(argv[1], 0, 0);
    ftgpio_gpio_ack_irq(&data);
    return 0;
}
''')
    binary = os.path.join(directory, "ftgpio_ack_original")
    compiler = shutil.which("cc")
    if not compiler:
        raise RuntimeError("C compiler unavailable")
    run = subprocess.run(
        [compiler, "-std=gnu11", "-Wall", "-Werror", combined, "-o", binary],
        capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return binary


def _original_trace(binary: str, hwirq: int) -> list[tuple[str, int, int]]:
    run = subprocess.run(
        [binary, str(hwirq)], capture_output=True, text=True)
    if run.returncode:
        raise AssertionError(run.stdout + run.stderr)
    return [(kind, int(offset), int(value))
            for kind, offset, value in
            (line.split() for line in run.stdout.splitlines() if line.strip())]


def verify_ftgpio_ack_trace() -> dict:
    from extractor.extractor import ExtractorConfig, extract_ris

    source = os.path.join(ROOT, "drivers", "test", "gpio-ftgpio010.c")
    result = extract_ris(ExtractorConfig(source=source))
    function_source = _original_function_source(source)
    cases = {}
    with tempfile.TemporaryDirectory(prefix="rh_ftgpio_trace_") as directory:
        binary = _compile_original(directory, function_source)
        for hwirq in (0, 3, 15):
            original = _original_trace(binary, hwirq)
            ris = _ris_trace(
                result.formal, "ftgpio_gpio_ack_irq",
                {"irqd_to_hwirq(d)": hwirq})
            if original != ris:
                raise AssertionError(
                    f"hwirq={hwirq}: original={original}, ris={ris}")
            cases[str(hwirq)] = {"trace": ris, "matched": True}

        mutated = copy.deepcopy(result.formal)
        register = next(reg for reg in mutated["register_map"]
                        if reg["name"] == "GPIO_INT_CLR")
        register["offset"] += 4
        mutation_caught = (
            _ris_trace(mutated, "ftgpio_gpio_ack_irq",
                       {"irqd_to_hwirq(d)": 3})
            != _original_trace(binary, 3))
        if not mutation_caught:
            raise AssertionError("FTGPIO trace oracle missed offset mutation")
    return {
        "schema": 1,
        "source": source,
        "function": "ftgpio_gpio_ack_irq",
        "cases": cases,
        "mutation_caught": mutation_caught,
    }


if __name__ == "__main__":
    print(json.dumps(verify_ftgpio_ack_trace(), indent=2, sort_keys=True))
