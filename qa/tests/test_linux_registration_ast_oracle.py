from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


if __package__:
    from ._bootstrap import QA_ROOT, SOURCE_ROOT
else:
    from _bootstrap import QA_ROOT, SOURCE_ROOT

from extractor.spec import DeviceSpec, FunctionSpec, Signature
from verification.linux_registration_ast_oracle import (
    registration_route_fingerprint,
    verify_linux_registration_ast,
)


_PYTHON_ENV = os.environ.copy()
_PYTHON_ENV["PYTHONPATH"] = os.pathsep.join(
    (str(SOURCE_ROOT), str(QA_ROOT)))


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
struct dev_pm_ops;
struct clk_hw;
struct of_device_id;
struct sdhci_host;
struct sdhci_pltfm_data;
struct hc_driver;
struct usb_hcd;
struct usb_gadget;
struct usb_ep;
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
struct device_driver {
    const char *name;
    const struct dev_pm_ops *pm;
    const struct of_device_id *of_match_table;
};
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
int devm_clk_hw_register(struct device *, struct clk_hw *);
const void *device_get_match_data(const struct device *);
struct sdhci_host *sdhci_pltfm_init(
    struct platform_device *, const struct sdhci_pltfm_data *, unsigned long);
int sdhci_add_host(struct sdhci_host *);
struct usb_hcd *usb_create_hcd(const struct hc_driver *, struct device *,
                               const char *);
int usb_add_hcd(struct usb_hcd *, unsigned int, unsigned int);
void usb_remove_hcd(struct usb_hcd *);
void usb_put_hcd(struct usb_hcd *);
void platform_set_drvdata(struct platform_device *, void *);
void *platform_get_drvdata(struct platform_device *);
int usb_add_gadget_udc(struct device *, struct usb_gadget *);
void usb_del_gadget_udc(struct usb_gadget *);
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


CLOCK_PM_SOURCE = r"""
#include "kernel_stubs.h"
struct clk_hw;
struct clk_ops { int (*enable)(struct clk_hw *); };
struct clk_init_data { const struct clk_ops *ops; };
struct clk_hw { const struct clk_init_data *init; };
struct dev_pm_ops { int (*suspend)(struct device *); };
struct priv { struct clk_hw hw; };

static int generated_suspend(struct device *dev)
{
    __rh_op_op_suspend: { (void)readl(dev); }
    return 0;
}

static int generated_enable(struct clk_hw *hw)
{
    __rh_op_op_enable: { writel(1, hw); }
    return 0;
}

static const struct dev_pm_ops generated_pm_ops = {
    .suspend = generated_suspend,
};
static const struct clk_ops generated_clk_ops = {
    .enable = generated_enable,
};
static const struct clk_init_data generated_clk_init = {
    .ops = &generated_clk_ops,
};

static int generated_probe(struct platform_device *pdev)
{
    static struct priv g;
    g.hw.init = &generated_clk_init;
    return devm_clk_hw_register(&pdev->dev, &g.hw);
}

static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .driver = { .name = "registration-test", .pm = &generated_pm_ops },
};
static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}
static int (*__inittest(void))(void) { return generated_driver_init; }
"""


SDHCI_SOURCE = r"""
#include "kernel_stubs.h"
struct sdhci_host { int unused; };
struct sdhci_ops {
    unsigned int (*read_l)(struct sdhci_host *, int);
};
struct sdhci_pltfm_data { const struct sdhci_ops *ops; };
struct of_device_id { const char *compatible; const void *data; };

static unsigned int generated_read_l(struct sdhci_host *host, int reg)
{
    __rh_op_op_read: { (void)readl(host); }
    return (unsigned int)reg;
}

static unsigned int generated_other_read_l(struct sdhci_host *host, int reg)
{
    return readl(host) + (unsigned int)reg;
}

static const struct sdhci_ops generated_sdhci_ops = {
    .read_l = generated_read_l,
};
static const struct sdhci_pltfm_data generated_pdata = {
    .ops = &generated_sdhci_ops,
};
static const struct sdhci_pltfm_data generated_fallback = {
    .ops = &generated_sdhci_ops,
};
static const struct sdhci_pltfm_data generated_wrong_pdata = {
    .ops = 0,
};
static const struct of_device_id generated_matches[] = {
    { .compatible = "vendor,controller", .data = &generated_pdata },
    { }
};

static int generated_probe(struct platform_device *pdev)
{
    const struct sdhci_pltfm_data *pdata;
    struct sdhci_host *host;
    int ret;

    pdata = device_get_match_data(&pdev->dev);
    if (!pdata)
        pdata = &generated_fallback;
    host = sdhci_pltfm_init(pdev, pdata, 0);
    if (!host)
        return -1;
    ret = sdhci_add_host(host);
    if (ret)
        return ret;
    return 0;
}

static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .driver = {
        .name = "registration-test",
        .of_match_table = generated_matches,
    },
};
static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}
static int (*__inittest(void))(void) { return generated_driver_init; }
"""


USB_HCD_SOURCE = r"""
#include "kernel_stubs.h"
struct hc_driver { int (*irq)(struct usb_hcd *); };
struct usb_hcd { int unused; };

static int generated_irq(struct usb_hcd *hcd)
{
    __rh_op_op_irq: { (void)readl(hcd); }
    return 0;
}
static const struct hc_driver generated_hc_driver = {
    .irq = generated_irq,
};

static int generated_probe(struct platform_device *pdev)
{
    struct usb_hcd *hcd;
    hcd = usb_create_hcd(&generated_hc_driver, &pdev->dev, "hcd");
    if (!hcd)
        return -1;
    platform_set_drvdata(pdev, hcd);
    return usb_add_hcd(hcd, 0, 0);
}
static void generated_remove(struct platform_device *pdev)
{
    struct usb_hcd *hcd = platform_get_drvdata(pdev);
    usb_remove_hcd(hcd);
    usb_put_hcd(hcd);
}
static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .remove = generated_remove,
    .driver = { .name = "registration-test" },
};
static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}
static int (*__inittest(void))(void) { return generated_driver_init; }
"""


USB_GADGET_SOURCE = r"""
#include "kernel_stubs.h"
struct usb_gadget_ops { int (*udc_start)(struct usb_gadget *); };
struct usb_ep_ops { int (*queue)(struct usb_ep *); };
struct usb_ep { const struct usb_ep_ops *ops; };
struct usb_gadget {
    const struct usb_gadget_ops *ops;
    struct usb_ep *ep0;
};

static int generated_udc_start(struct usb_gadget *gadget)
{
    __rh_op_op_start: { (void)readl(gadget); }
    return 0;
}
static int generated_queue(struct usb_ep *ep)
{
    __rh_op_op_queue: { (void)readl(ep); }
    return 0;
}
static const struct usb_gadget_ops generated_gadget_ops = {
    .udc_start = generated_udc_start,
};
static const struct usb_ep_ops generated_ep_ops = {
    .queue = generated_queue,
};
static struct usb_ep generated_ep = { .ops = &generated_ep_ops };
static struct usb_gadget generated_gadget = {
    .ops = &generated_gadget_ops,
    .ep0 = &generated_ep,
};
static int generated_probe(struct platform_device *pdev)
{
    return usb_add_gadget_udc(&pdev->dev, &generated_gadget);
}
static void generated_remove(struct platform_device *pdev)
{
    usb_del_gadget_udc(&generated_gadget);
}
static struct platform_driver generated_driver = {
    .probe = generated_probe,
    .remove = generated_remove,
    .driver = { .name = "registration-test" },
};
static int generated_driver_init(void)
{
    return __platform_driver_register(&generated_driver, &__this_module);
}
static int (*__inittest(void))(void) { return generated_driver_init; }
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


def test_linux_registration_accepts_typed_pm_and_clock_object_chains(tmp_path):
    contract = {
        "schema": 1,
        "driver": "registration-test",
        "register_operations": [
            {"op_id": "op_suspend", "module": "source_suspend",
             "kind": "Read"},
            {"op_id": "op_enable", "module": "source_enable",
             "kind": "Write"},
        ],
    }
    device = DeviceSpec(
        name="registration-test",
        functions=[
            FunctionSpec(
                name="source_suspend", signature=Signature(),
                role="suspend", ris_ref="source_suspend",
                is_callback_entry=True,
                callback_table="dev_pm_ops.suspend"),
            FunctionSpec(
                name="source_enable", signature=Signature(),
                role="enable", ris_ref="source_enable",
                is_callback_entry=True,
                callback_table="clk_ops.enable"),
        ],
    )
    plan = {
        "schema": 3,
        "oracle": "backend-lowering-plan-v3",
        "driver": "registration-test",
        "backend": "linux",
        "entries": [{
            "op_id": row["op_id"], "module": row["module"],
            "strict_eligible": True,
            "disposition": "candidate_definition_emit",
        } for row in contract["register_operations"]],
    }
    generated, command = _fixture(tmp_path, CLOCK_PM_SOURCE)
    report = verify_linux_registration_ast(
        contract, device, generated, plan, kbuild_cmd=command)
    assert report["complete"] is True, report
    assert report["runtime_registered_op_ids"] == [
        "op_enable", "op_suspend"]
    callbacks = {route["callback"] for route in report["registration_routes"]}
    assert "dev_pm_ops.suspend" in callbacks
    assert "clk_ops.enable" in callbacks


def _verify_sdhci(root: Path, source: str = SDHCI_SOURCE) -> dict:
    contract = {
        "schema": 1,
        "driver": "registration-test",
        "register_operations": [{
            "op_id": "op_read", "module": "source_read_l", "kind": "Read",
        }],
    }
    device = DeviceSpec(
        name="registration-test",
        functions=[FunctionSpec(
            name="source_read_l", signature=Signature(), role="read_config",
            ris_ref="source_read_l", is_callback_entry=True,
            callback_table="sdhci_ops.read_l",
        )],
    )
    plan = {
        "schema": 3,
        "oracle": "backend-lowering-plan-v3",
        "driver": "registration-test",
        "backend": "linux",
        "entries": [{
            "op_id": "op_read", "module": "source_read_l",
            "strict_eligible": True,
            "disposition": "candidate_definition_emit",
        }],
    }
    generated, command = _fixture(root, source)
    return verify_linux_registration_ast(
        contract, device, generated, plan, kbuild_cmd=command)


def test_linux_registration_accepts_exact_sdhci_lifecycle(tmp_path):
    report = _verify_sdhci(tmp_path)
    assert report["complete"] is True, report
    assert report["runtime_registered_op_ids"] == ["op_read"]
    route = next(route for route in report["registration_routes"]
                 if route["callback"] == "sdhci_ops.read_l")
    kinds = [item["kind"] for item in route["registration"]["chain"]]
    assert {"match_data_edge", "finite_pdata_fallback"} & set(kinds)
    assert "sdhci_pltfm_init" in kinds
    assert "sdhci_host_result" in kinds
    assert "sdhci_add_host" in kinds


def test_linux_registration_rejects_sdhci_identity_mutations(tmp_path):
    mutations = [
        SDHCI_SOURCE.replace(
            ".ops = &generated_sdhci_ops,", ".ops = 0,", 2),
        SDHCI_SOURCE.replace(
            "sdhci_pltfm_init(pdev, pdata, 0)",
            "sdhci_pltfm_init(pdev, &generated_wrong_pdata, 0)"),
        SDHCI_SOURCE.replace(
            "struct sdhci_host *host;",
            "struct sdhci_host *host;\n    struct sdhci_host *other_host;").replace(
            "sdhci_add_host(host)", "sdhci_add_host(other_host)"),
        SDHCI_SOURCE.replace(
            "ret = sdhci_add_host(host);", "ret = 0;"),
        SDHCI_SOURCE.replace(
            ".read_l = generated_read_l,",
            ".read_l = generated_other_read_l,"),
    ]
    for index, source in enumerate(mutations):
        case = tmp_path / str(index)
        case.mkdir()
        report = _verify_sdhci(case, source)
        assert report["complete"] is False, (index, report)
        assert report["runtime_registered_op_ids"] == [], (index, report)


def _verify_usb(root: Path, source: str, callbacks: list[tuple[str, str]],
                op_ids: list[str]) -> dict:
    contract = {
        "schema": 1, "driver": "registration-test",
        "register_operations": [
            {"op_id": op_id, "module": module, "kind": "Read"}
            for op_id, (module, _callback) in zip(op_ids, callbacks)
        ],
    }
    device = DeviceSpec(
        name="registration-test",
        functions=[FunctionSpec(
            name=module, signature=Signature(), role="read_config",
            ris_ref=module, is_callback_entry=True, callback_table=callback,
        ) for module, callback in callbacks],
    )
    plan = {
        "schema": 3, "oracle": "backend-lowering-plan-v3",
        "driver": "registration-test", "backend": "linux",
        "entries": [{
            "op_id": op_id, "module": module,
            "strict_eligible": True,
            "disposition": "candidate_definition_emit",
        } for op_id, (module, _callback) in zip(op_ids, callbacks)],
    }
    generated, command = _fixture(root, source)
    return verify_linux_registration_ast(
        contract, device, generated, plan, kbuild_cmd=command)


def test_linux_registration_accepts_single_instance_usb_lifecycles(tmp_path):
    hcd_root = tmp_path / "hcd"
    hcd_root.mkdir()
    hcd = _verify_usb(
        hcd_root, USB_HCD_SOURCE,
        [("source_irq", "hc_driver.irq")], ["op_irq"])
    assert hcd["complete"] is True, hcd
    assert hcd["runtime_registered_op_ids"] == ["op_irq"]
    hcd_route = next(route for route in hcd["registration_routes"]
                     if route["callback"] == "hc_driver.irq")
    hcd_kinds = {item["kind"]
                 for item in hcd_route["registration"]["chain"]}
    assert {"usb_create_hcd", "usb_add_hcd", "usb_remove_hcd",
            "usb_put_hcd"} <= hcd_kinds

    gadget_root = tmp_path / "gadget"
    gadget_root.mkdir()
    gadget = _verify_usb(
        gadget_root, USB_GADGET_SOURCE,
        [("source_start", "usb_gadget_ops.udc_start"),
         ("source_queue", "usb_ep_ops.queue")],
        ["op_start", "op_queue"])
    assert gadget["complete"] is True, gadget
    assert gadget["runtime_registered_op_ids"] == ["op_queue", "op_start"]


def test_linux_registration_rejects_usb_lifecycle_mutations(tmp_path):
    hcd_mutations = [
        USB_HCD_SOURCE.replace(
            "platform_set_drvdata(pdev, hcd);", "(void)hcd;"),
        USB_HCD_SOURCE.replace(
            "usb_remove_hcd(hcd);", "(void)hcd;"),
        USB_HCD_SOURCE.replace(
            "usb_put_hcd(hcd);", "(void)hcd;"),
        USB_HCD_SOURCE.replace(
            ".irq = generated_irq,", ".irq = 0,"),
    ]
    for index, source in enumerate(hcd_mutations):
        root = tmp_path / f"hcd-{index}"
        root.mkdir()
        report = _verify_usb(
            root, source, [("source_irq", "hc_driver.irq")], ["op_irq"])
        assert report["complete"] is False, (index, report)
        assert report["runtime_registered_op_ids"] == [], (index, report)

    gadget_mutations = [
        USB_GADGET_SOURCE.replace(
            "usb_del_gadget_udc(&generated_gadget);", "(void)pdev;"),
        USB_GADGET_SOURCE.replace(
            ".ep0 = &generated_ep,", ".ep0 = 0,"),
        USB_GADGET_SOURCE.replace(
            ".ops = &generated_gadget_ops,", ".ops = 0,"),
    ]
    for index, source in enumerate(gadget_mutations):
        root = tmp_path / f"gadget-{index}"
        root.mkdir()
        report = _verify_usb(
            root, source,
            [("source_start", "usb_gadget_ops.udc_start"),
             ("source_queue", "usb_ep_ops.queue")],
            ["op_start", "op_queue"])
        assert report["complete"] is False, (index, report)


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
        str(QA_ROOT / "verification" / "linux_registration_ast_oracle.py"),
        "--contract", str(contract),
        "--device-spec-json", str(device),
        "--lowering-plan", str(plan),
        "--generated", str(generated),
        "--kbuild-cmd", str(command),
        "--output", str(output),
    ], cwd=tmp_path, env=_PYTHON_ENV, capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    assert json.loads(process.stdout) == json.loads(output.read_text())

    missing = subprocess.run([
        sys.executable,
        str(QA_ROOT / "verification" / "linux_registration_ast_oracle.py"),
        "--contract", str(contract),
        "--device-spec-json", str(device),
        "--lowering-plan", str(plan),
        "--generated", str(generated),
        "--kbuild-cmd", str(tmp_path / "missing.cmd"),
    ], cwd=tmp_path, env=_PYTHON_ENV, capture_output=True, text=True)
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
