from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


REHARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REHARNESS))

from extractor.spec import DeviceSpec, FunctionSpec, Signature
from verification.linux_registration_ast_oracle import (
    registration_route_fingerprint,
    verify_linux_registration_ast,
)


def _contract() -> dict:
    return {
        "schema": 1,
        "driver": "registration-test",
        "register_operations": [
            {"op_id": "op_probe", "module": "source_probe", "kind": "Read"},
            {"op_id": "op_get", "module": "source_get", "kind": "Read"},
            {"op_id": "op_ack", "module": "source_ack", "kind": "Write"},
            {"op_id": "op_parent", "module": "source_parent", "kind": "Read"},
        ],
    }


def _device_spec() -> DeviceSpec:
    callbacks = [
        ("source_probe", "platform_driver.probe"),
        ("source_get", "gpio_chip.get"),
        ("source_ack", "irq_chip.irq_ack"),
        ("source_parent", "gpio_irq_chip.parent_handler"),
    ]
    return DeviceSpec(
        name="registration-test",
        functions=[FunctionSpec(
            name=name,
            signature=Signature(),
            role="probe" if name == "source_probe" else "read_config",
            ris_ref=name,
            is_callback_entry=True,
            callback_table=callback,
        ) for name, callback in callbacks],
    )


def _plan() -> dict:
    return {
        "schema": 3,
        "oracle": "backend-lowering-plan-v3",
        "driver": "registration-test",
        "backend": "linux",
        "entries": [{
            "op_id": row["op_id"],
            "module": row["module"],
            "strict_eligible": True,
            "disposition": "candidate_definition_emit",
        } for row in _contract()["register_operations"]],
    }


HEADER = r"""
struct module { int unused; };
extern struct module __this_module;
struct device { int unused; };
struct platform_device { struct device dev; };
struct irq_desc { int unused; };
struct irq_data { int unused; };
struct gpio_chip;
struct gpio_irq_chip {
    void (*parent_handler)(struct irq_desc *);
};
struct irq_chip {
    void (*irq_ack)(struct irq_data *);
};
struct gpio_chip {
    int (*get)(struct gpio_chip *, unsigned int);
    struct gpio_irq_chip irq;
};
struct device_driver { const char *name; };
struct platform_driver {
    int (*probe)(struct platform_device *);
    void (*remove)(struct platform_device *);
    struct device_driver driver;
};
int __platform_driver_register(struct platform_driver *, struct module *);
int devm_gpiochip_add_data_with_key(
    struct device *, struct gpio_chip *, void *, void *, void *);
void gpio_irq_chip_set_chip(struct gpio_irq_chip *, const struct irq_chip *);
unsigned int readl(void *);
void writel(unsigned int, void *);
"""


SOURCE = r"""
#include "kernel_stubs.h"
struct module __this_module;
struct priv { struct gpio_chip gc; struct irq_chip irqchip; };

static int generated_get(struct gpio_chip *gc, unsigned int line)
{
    __rh_op_op_get: { (void)readl((void *)gc); }
    return (int)line;
}

static void generated_ack(struct irq_data *d)
{
    __rh_op_op_ack: { writel(1, (void *)d); }
}

static void generated_parent(struct irq_desc *d)
{
    __rh_op_op_parent: { (void)readl((void *)d); }
}

static int generated_probe(struct platform_device *pdev)
{
    struct priv *g = (void *)0;
    __rh_op_op_probe: { (void)readl((void *)pdev); }
    g->gc.get = generated_get;
    g->irqchip.irq_ack = generated_ack;
    gpio_irq_chip_set_chip(&g->gc.irq, &g->irqchip);
    g->gc.irq.parent_handler = generated_parent;
    return devm_gpiochip_add_data_with_key(
        &pdev->dev, &g->gc, g, (void *)0, (void *)0);
}

static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .driver = { .name = "registration-test" },
};

static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}

static int (*__inittest(void))(void)
{
    return generated_driver_init;
}
"""


def _fixture(root: Path, source: str = SOURCE):
    header = root / "kernel_stubs.h"
    generated = root / "registration_test.c"
    command = root / ".registration_test.o.cmd"
    header.write_text(HEADER, encoding="utf-8")
    generated.write_text(source, encoding="utf-8")
    command.write_text(
        f"cmd_registration_test.o := cc -I{root} -std=gnu11 "
        "-c registration_test.c -o registration_test.o\n",
        encoding="utf-8")
    return generated, command


def _verify(root: Path, source: str = SOURCE) -> dict:
    generated, command = _fixture(root, source)
    return verify_linux_registration_ast(
        _contract(), _device_spec(), generated, _plan(),
        kbuild_cmd=command)


def test_linux_registration_accepts_exact_platform_gpio_irq_chain(tmp_path):
    report = _verify(tmp_path)
    assert report["complete"] is True, report
    assert report["runtime_registered_ops"] == 4
    assert report["runtime_unregistered_op_ids"] == []
    callbacks = {route["callback"] for route in report["registration_routes"]}
    assert {
        "platform_driver.probe", "gpio_chip.get", "irq_chip.irq_ack",
        "gpio_irq_chip.parent_handler",
    } <= callbacks
    route = copy.deepcopy(report["registration_routes"][0])
    original = route["route_id"]
    for item in (route.get("registration") or {}).get("chain") or []:
        if isinstance(item.get("location"), dict):
            item["location"]["file"] = "/different/output/root/generated.c"
    assert registration_route_fingerprint(route) == original


def test_linux_registration_rejects_missing_or_shadowed_driver_root(tmp_path):
    missing = _verify(tmp_path, SOURCE.replace(
        "return __platform_driver_register(&generated_driver, &__this_module);",
        "return 0;"))
    assert missing["complete"] is False
    assert missing["runtime_registered_ops"] == 0

    shadowed_source = SOURCE.replace(
        "struct module __this_module;",
        "struct module __this_module;\n"
        "static int __platform_driver_register("
        "struct platform_driver *d, struct module *m) { return d != 0; }")
    shadowed = _verify(tmp_path, shadowed_source)
    assert shadowed["complete"] is False
    assert (shadowed["parse_errors"]
            or any(item["kind"] == "invalid_root_registration"
                   for item in shadowed["route_errors"]))


def test_linux_registration_rejects_wrong_owner_target_and_order(tmp_path):
    wrong_owner = SOURCE.replace(
        "struct priv *g = (void *)0;",
        "struct priv *g = (void *)0;\n    struct priv *h = (void *)0;").replace(
        "&pdev->dev, &g->gc, g,", "&pdev->dev, &h->gc, h,")
    report = _verify(tmp_path, wrong_owner)
    assert report["complete"] is False
    assert set(report["runtime_unregistered_op_ids"]) == {
        "op_get", "op_ack", "op_parent"}
    assert report["runtime_registered_op_ids"] == ["op_probe"]

    wrong_target = SOURCE.replace(
        "g->gc.get = generated_get;", "g->gc.get = generated_probe;")
    report = _verify(tmp_path, wrong_target)
    assert report["complete"] is False
    assert "op_get" in report["runtime_unregistered_op_ids"]

    registration = """return devm_gpiochip_add_data_with_key(
        &pdev->dev, &g->gc, g, (void *)0, (void *)0);"""
    moved = SOURCE.replace(registration, """int ret = devm_gpiochip_add_data_with_key(
        &pdev->dev, &g->gc, g, (void *)0, (void *)0);
    g->gc.get = generated_get;
    return ret;""").replace(
        "    g->gc.get = generated_get;\n", "", 1)
    report = _verify(tmp_path, moved)
    assert report["complete"] is False
    assert "op_get" in report["runtime_unregistered_op_ids"]


def test_linux_registration_rejects_controlled_gpio_and_wrong_irq_attach(tmp_path):
    controlled = SOURCE.replace(
        "return devm_gpiochip_add_data_with_key(",
        "if (pdev) return devm_gpiochip_add_data_with_key(")
    report = _verify(tmp_path, controlled)
    assert report["complete"] is False
    assert any(item["kind"] == "invalid_gpio_registration"
               for item in report["route_errors"])

    wrong_attach = SOURCE.replace(
        "struct priv *g = (void *)0;",
        "struct priv *g = (void *)0;\n    struct priv *h = (void *)0;").replace(
        "gpio_irq_chip_set_chip(&g->gc.irq, &g->irqchip);",
        "gpio_irq_chip_set_chip(&g->gc.irq, &h->irqchip);")
    report = _verify(tmp_path, wrong_attach)
    assert report["complete"] is False
    assert "op_ack" in report["runtime_unregistered_op_ids"]
    assert "op_parent" not in report["runtime_unregistered_op_ids"]


def test_linux_registration_cli_requires_exact_context_and_writes_report(tmp_path):
    generated, command = _fixture(tmp_path)
    contract = tmp_path / "contract.json"
    device = tmp_path / "device.json"
    plan = tmp_path / "plan.json"
    output = tmp_path / "nested" / "registration.json"
    from extractor.spec import device_spec_to_dict
    contract.write_text(json.dumps(_contract()), encoding="utf-8")
    device.write_text(json.dumps(device_spec_to_dict(_device_spec())),
                      encoding="utf-8")
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    process = subprocess.run([
        sys.executable,
        str(REHARNESS / "verification" / "linux_registration_ast_oracle.py"),
        "--contract", str(contract),
        "--device-spec-json", str(device),
        "--lowering-plan", str(plan),
        "--generated", str(generated),
        "--kbuild-cmd", str(command),
        "--output", str(output),
    ], cwd=REHARNESS, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(process.stdout) == json.loads(output.read_text())

    missing = subprocess.run([
        sys.executable,
        str(REHARNESS / "verification" / "linux_registration_ast_oracle.py"),
        "--contract", str(contract),
        "--device-spec-json", str(device),
        "--lowering-plan", str(plan),
        "--generated", str(generated),
        "--kbuild-cmd", str(tmp_path / "missing.cmd"),
    ], cwd=REHARNESS, capture_output=True, text=True)
    assert missing.returncode == 3
    assert json.loads(missing.stdout)["complete"] is False


def _run_standalone() -> int:
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            with tempfile.TemporaryDirectory() as directory:
                test(Path(directory))
            print(f"  PASS  {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
